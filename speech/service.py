"""
SpeechService: the one access point other parts of the project should use
for speech I/O. Sensor fusion, haptics, and the orchestrator should import
`speech` from here and never touch tts.py / stt.py directly -- that's what
lets the backend, transport, or even the OS underneath this module change
later without touching the rest of the codebase.

Example, from any other module:

    from speech import speech, Priority

    speech.speak("obstacle close, front left", priority=Priority.HIGH, interrupt=True)
    speech.on("mute", lambda cmd: haptics.set_muted(True))
    speech.on("volume up", lambda cmd: audio.change_volume(+10))

Handlers receive a frozen `Command` (text, seq, recognized_at, age at
dispatch, source_mode) so they can build request IDs and their own
staleness checks; `source_mode` is "live" from the microphone and
"simulated" / "replay" from `speech.fakes.FakeSTT`.

Startup wires real backends with `speech.configure(SpeechConfig.load(...))`;
tests and the simulator wire fakes with
`speech.attach(tts=FakeTTS(), stt=FakeSTT(), config=SpeechConfig(...))`.
Either backend may be missing -- `speech.health` reports which side is
`ready`, `partial` (listening, but some grammar phrases are unsupported by
the model), `fault`, or `unavailable`, and the other keeps working.

Thread model: recognized commands are queued and handlers run on a
dedicated dispatcher thread, never on the recognition thread, so a slow
handler cannot stall listening. Commands older than
`max_command_age_seconds` when they reach the dispatcher are discarded.

Wake phrase (optional, off by default): when set, a command is dispatched
only if it was recognized within `wake_window_seconds` after the wake
phrase, except for `always_on_commands` (e.g. "stop speaking"), which
always dispatch. Arming is judged on the recognizer's own timestamps, so a
replayed transcript arms and rejects exactly as the live one did.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .config import SpeechConfig
from .tts import Priority

__all__ = ["Command", "SpeechConfig", "SpeechService", "Priority", "speech"]

log = logging.getLogger(__name__)


SOURCE_MODES = ("live", "simulated", "replay")


@dataclass(frozen=True)
class Command:
    """A recognized utterance as handed to `speech.on()` handlers."""

    text: str
    seq: int
    recognized_at: float   # time.monotonic() at end of utterance, STT clock
    dispatched_at: float   # time.monotonic() when the handler was invoked
    source_mode: str       # "live" | "simulated" | "replay"

    @property
    def age_seconds(self) -> float:
        return self.dispatched_at - self.recognized_at


@dataclass
class _Pending:
    seq: int
    text: str
    recognized_at: float
    source_mode: str


class SpeechService:
    def __init__(self):
        self._tts = None
        self._stt = None
        self._handlers: Dict[str, List[Callable[[Command], None]]] = defaultdict(list)
        # How long to keep the mic muted after TTS playback ends, to cover
        # speaker/room echo tail and mic latency before we trust input again.
        self._echo_guard_seconds = 0.3
        self._unmute_timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()

        self._max_command_age_seconds = 2.0
        self._wake_phrase: Optional[str] = None
        self._wake_window_seconds = 5.0
        self._always_on: frozenset = frozenset({"stop speaking"})
        # recognized_at deadline (STT clock) until which commands dispatch.
        self.armed_until: float = float("-inf")
        self._commands: "queue.Queue[_Pending]" = queue.Queue(maxsize=8)
        self._seq = itertools.count()
        self._dispatcher: Optional[threading.Thread] = None
        self._closing = threading.Event()

        self.config = SpeechConfig()
        self.health: Dict[str, str] = {"tts": "unavailable", "stt": "unavailable"}
        self.health_reason: Dict[str, Optional[str]] = {"tts": None, "stt": None}

    # -- wiring ---------------------------------------------------------------

    def configure(self, config: SpeechConfig) -> Dict[str, str]:
        """Call this once at startup with a validated `SpeechConfig` that
        names real model paths. Kept separate from __init__ so `speech`
        can be imported anywhere as a singleton before models are loaded.

        A backend that fails to load is reported in `health` rather than
        raised, so a missing mic doesn't take the speaker down with it.
        Returns the health dict."""
        from .stt import VoskSTT
        from .tts import PiperTTS

        config.validate(require_models=True)
        tts = stt = None
        try:
            tts = PiperTTS(
                config.tts_model_path,
                config.tts_config_path,
                device=config.tts_device,
                max_queue=config.max_queue,
                dedup_window_seconds=config.dedup_window_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("speech_fault subsystem=tts reason=load_failed error=%s: %s", type(exc).__name__, exc)
            self._set_health("tts", "fault", "load_failed")
        try:
            stt = VoskSTT(
                config.stt_model_path,
                config.grammar,
                samplerate=config.samplerate,
                device=config.stt_device,
                blocksize=config.blocksize,
                max_capture_seconds=config.max_capture_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("speech_fault subsystem=stt reason=load_failed error=%s: %s", type(exc).__name__, exc)
            self._set_health("stt", "fault", "load_failed")

        return self.attach(tts=tts, stt=stt, config=config)

    def attach(self, tts=None, stt=None, config: Optional[SpeechConfig] = None) -> Dict[str, str]:
        """Wire already-constructed backends (real or fake) and start them.
        `config` supplies the service-level settings (echo guard, command
        age, wake phrase); model paths in it are ignored here.

        `tts` must provide speak/cancel_all/start/shutdown and the
        on_speak_start/on_speak_end/on_fault attributes (see QueuedTTS);
        `stt` must provide start/stop/set_muted and on_command/on_fault, and
        call `on_command(text, recognized_at, source_mode)`."""
        config = config or SpeechConfig()
        self.config = config
        self._echo_guard_seconds = config.echo_guard_seconds
        self._max_command_age_seconds = config.max_command_age_seconds
        self._wake_phrase = config.wake_phrase
        self._wake_window_seconds = config.wake_window_seconds
        self._always_on = frozenset(config.always_on_commands)
        self.armed_until = float("-inf")

        self._tts = tts
        if tts is not None:
            tts.on_speak_start = self._on_speak_start
            tts.on_speak_end = self._on_speak_end
            tts.on_fault = lambda reason: self._set_health("tts", "fault", reason)
            tts.start()
            self._set_health("tts", "ready")

        self._stt = stt
        if stt is not None:
            stt.on_command = self._on_recognized
            stt.on_fault = lambda reason: self._set_health("stt", "fault", reason)
            try:
                stt.start()
                unsupported = getattr(stt, "unsupported_phrases", None)
                if unsupported:
                    # Listening works, but part of the grammar can never fire.
                    self._set_health("stt", "partial", f"unsupported_phrases: {unsupported}")
                else:
                    self._set_health("stt", "ready")
            except Exception as exc:  # noqa: BLE001
                log.warning("speech_fault subsystem=stt reason=start_failed error=%s: %s", type(exc).__name__, exc)
                self._set_health("stt", "fault", "start_failed")

        if self._dispatcher is None:
            self._dispatcher = threading.Thread(
                target=self._dispatch_loop, name="speech-dispatch", daemon=True
            )
            self._dispatcher.start()
        return dict(self.health)

    def _set_health(self, subsystem: str, state: str, reason: Optional[str] = None):
        previous = self.health.get(subsystem)
        self.health[subsystem] = state
        self.health_reason[subsystem] = reason
        if previous != state:
            log.log(
                logging.WARNING if state == "fault" else logging.INFO,
                "speech: %s %s -> %s%s", subsystem, previous, state, f" ({reason})" if reason else "",
            )

    # -- echo guard: mute the mic while (and briefly after) we talk -----------

    def _on_speak_start(self):
        with self._timer_lock:
            if self._unmute_timer:
                self._unmute_timer.cancel()
                self._unmute_timer = None
        if self._stt:
            self._stt.set_muted(True)

    def _on_speak_end(self):
        with self._timer_lock:
            if self._closing.is_set():
                return
            if self._unmute_timer:
                self._unmute_timer.cancel()
            self._unmute_timer = threading.Timer(self._echo_guard_seconds, self._unmute_stt)
            self._unmute_timer.daemon = True
            self._unmute_timer.start()

    def _unmute_stt(self):
        if self._stt:
            self._stt.set_muted(False)

    # -- speaking -------------------------------------------------------------

    def speak(
        self,
        text: str,
        priority: Priority = Priority.NORMAL,
        interrupt: bool = False,
        ttl_seconds: Optional[float] = None,
        *, on_started: Optional[Callable[[float], None]] = None,
        is_valid: Optional[Callable[[], bool]] = None,
        bypass_mute: bool = False,
    ) -> bool:
        """Queue `text`. Returns False (and logs) if no TTS is available or
        the text was suppressed as a recent repeat."""
        if self._closing.is_set() or self._tts is None:
            log.warning("speech: TTS unavailable; not speaking %r", text)
            return False
        return self._tts.speak(text, priority=priority, interrupt=interrupt, ttl_seconds=ttl_seconds,
                               on_started=on_started, is_valid=is_valid, bypass_mute=bypass_mute)

    @property
    def volume_level(self) -> int:
        return self._tts.volume_level if self._tts is not None else 5

    @property
    def muted(self) -> bool:
        return bool(self._tts is not None and self._tts.muted)

    def set_volume(self, level: int) -> int:
        if type(level) is not int or not 1 <= level <= 5:
            raise ValueError("volume level must be an integer in 1..5")
        if self._tts is None:
            raise RuntimeError("tts_unavailable")
        return self._tts.set_volume(level)

    def set_muted(self, muted: bool) -> None:
        if type(muted) is not bool:
            raise ValueError("muted must be boolean")
        if self._tts is None:
            raise RuntimeError("tts_unavailable")
        self._tts.set_muted(muted)

    @property
    def handled_commands(self) -> frozenset[str]:
        return frozenset(k for k, handlers in self._handlers.items() if handlers)

    def stop_speaking(self):
        """Cancel current playback and everything queued."""
        if self._tts is not None:
            self._tts.cancel_all()

    # -- listening ------------------------------------------------------------

    def on(self, command: str, handler: Callable[[Command], None]):
        """Register `handler(cmd: Command)` for a recognized grammar phrase.
        `command` must match an entry in the grammar list passed to configure()."""
        self._handlers[command.lower()].append(handler)

    # -- question capture -----------------------------------------------------

    @property
    def is_capturing(self) -> bool:
        return bool(self._stt is not None and getattr(self._stt, "is_capturing", False))

    def capture_question(self, seconds: float) -> Optional[bytes]:
        """Record `seconds` of raw mic audio as WAV bytes for the assistant,
        bypassing command recognition. Returns None when STT is unavailable,
        muted (speaker playing / echo guard), already capturing, or the
        stream stalls -- callers report "could not hear the question".

        Blocks for ~`seconds`, so never call it from a `speech.on(...)`
        handler: that runs on the dispatcher thread, which must return
        promptly. The orchestrator spawns a worker thread that calls
        capture_question() and then hands the bytes to omni.scene."""
        if (self._closing.is_set() or self._stt is None
                or self.health.get("stt") not in ("ready", "partial")
                or self._stt.muted or self.is_capturing):
            return None
        if not 0 < seconds <= self.config.max_capture_seconds:
            raise ValueError("capture seconds outside configured bounds")
        if self.config.listening_tone:
            try:
                self.play_listening_tone()
            except Exception:
                log.warning("listening_tone_failed reason=audio_output_failed")
        return self._stt.capture(seconds)

    def play_listening_tone(self):
        """Provisional 60 ms / 880 Hz cue, complete before capture; bypasses TTS.

        A dedicated stream avoids sounddevice.play() stopping unrelated playback.
        No device is opened on import.
        """
        import numpy as np
        import sounddevice as sd

        rate = self.config.samplerate
        t = np.arange(int(rate * 0.06)) / rate
        samples = (0.08 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))).astype("float32")
        with sd.OutputStream(samplerate=rate, channels=1, dtype="float32",
                             device=self.config.tts_device) as stream:
            stream.write(samples)

    def _on_recognized(self, text: str, recognized_at: float, source_mode: str):
        # Called on the STT thread: enqueue only, never run handlers here.
        if source_mode not in SOURCE_MODES:
            log.error("speech: rejected command %r with invalid source_mode %r", text, source_mode)
            return
        pending = _Pending(seq=next(self._seq), text=text, recognized_at=recognized_at, source_mode=source_mode)
        try:
            self._commands.put_nowait(pending)
        except queue.Full:
            log.warning("speech: command queue full; dropped %r (seq %d, %s)", text, pending.seq, source_mode)

    def _dispatch_loop(self):
        while not self._closing.is_set():
            try:
                pending = self._commands.get(timeout=0.2)
            except queue.Empty:
                continue
            cmd = Command(
                text=pending.text,
                seq=pending.seq,
                recognized_at=pending.recognized_at,
                dispatched_at=time.monotonic(),
                source_mode=pending.source_mode,
            )
            tag = f"seq {cmd.seq}, {cmd.source_mode}, age {cmd.age_seconds:.2f}s"
            if cmd.age_seconds > self._max_command_age_seconds:
                log.warning("speech: dropped stale command %r (%s)", cmd.text, tag)
                continue
            if not self._arming_allows(cmd):
                log.info("speech: rejected %r: not armed, say %r first (%s)", cmd.text, self._wake_phrase, tag)
                continue
            handlers = self._handlers.get(cmd.text.lower(), [])
            if not handlers:
                if cmd.text.strip() == "[unk]":
                    # Speech was heard but matched nothing in the grammar.
                    log.info("speech: not_understood (%s)", tag)
                else:
                    log.info("speech: unmatched utterance %r (%s)", cmd.text, tag)
                continue
            log.info("speech: command %r (%s)", cmd.text, tag)
            for handler in handlers:
                try:
                    handler(cmd)
                except Exception as exc:  # noqa: BLE001
                    log.warning("speech_command_failed reason=handler_failed error=%s (%s)", type(exc).__name__, tag)

    def _arming_allows(self, cmd: Command) -> bool:
        """Wake-phrase gate. Runs on the dispatcher thread only."""
        if self._wake_phrase is None:
            return True
        text = cmd.text.lower()
        if text == self._wake_phrase:
            self.armed_until = cmd.recognized_at + self._wake_window_seconds
            log.info("speech: armed for %.1fs (seq %d)", self._wake_window_seconds, cmd.seq)
            return True  # handlers on the wake phrase itself may e.g. chirp
        if text in self._always_on:
            return True
        return cmd.recognized_at <= self.armed_until

    def is_armed(self, now: Optional[float] = None) -> bool:
        """True when a command recognized at `now` (STT clock, default:
        time.monotonic()) would dispatch without the wake phrase."""
        if self._wake_phrase is None:
            return True
        return (time.monotonic() if now is None else now) <= self.armed_until

    # -- lifecycle ------------------------------------------------------------

    def shutdown(self):
        self._closing.set()
        with self._timer_lock:
            if self._unmute_timer:
                self._unmute_timer.cancel()
                self._unmute_timer = None
        if self._tts:
            self._tts.shutdown()
        if self._stt:
            self._stt.stop()
        if self._dispatcher:
            self._dispatcher.join(timeout=1)
            self._dispatcher = None
        self._set_health("tts", "unavailable")
        self._set_health("stt", "unavailable")


# Module-level singleton -- this is what other files should import.
speech = SpeechService()
