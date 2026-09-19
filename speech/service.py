"""
SpeechService: the one access point other parts of the project should use
for speech I/O. Sensor fusion, haptics, and the orchestrator should import
`speech` from here and never touch tts.py / stt.py directly -- that's what
lets the backend, transport, or even the OS underneath this module change
later without touching the rest of the codebase.

Example, from any other module:

    from speech import speech, Priority

    speech.speak("obstacle close, front left", priority=Priority.HIGH, interrupt=True)
    speech.on("mute", lambda: haptics.set_muted(True))
    speech.on("volume up", lambda: audio.change_volume(+10))

Startup wires real backends with `speech.configure(...)`; tests and the
simulator wire fakes with `speech.attach(tts=FakeTTS(), stt=FakeSTT())`.
Either backend may be missing -- `speech.health` reports which side is
`ready`, `fault`, or `unavailable`, and the other keeps working.

Thread model: recognized commands are queued and handlers run on a
dedicated dispatcher thread, never on the recognition thread, so a slow
handler cannot stall listening. Commands older than
`max_command_age_seconds` when they reach the dispatcher are discarded.
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

from .tts import Priority

__all__ = ["SpeechService", "Priority", "speech"]

log = logging.getLogger(__name__)


@dataclass
class _Command:
    seq: int
    text: str
    recognized_at: float  # time.monotonic() at end of utterance


class SpeechService:
    def __init__(self):
        self._tts = None
        self._stt = None
        self._handlers: Dict[str, List[Callable[[], None]]] = defaultdict(list)
        # How long to keep the mic muted after TTS playback ends, to cover
        # speaker/room echo tail and mic latency before we trust input again.
        self._echo_guard_seconds = 0.3
        self._unmute_timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()

        self._max_command_age_seconds = 2.0
        self._commands: "queue.Queue[_Command]" = queue.Queue(maxsize=8)
        self._seq = itertools.count()
        self._dispatcher: Optional[threading.Thread] = None
        self._closing = threading.Event()

        self.health: Dict[str, str] = {"tts": "unavailable", "stt": "unavailable"}
        self.health_reason: Dict[str, Optional[str]] = {"tts": None, "stt": None}

    # -- wiring ---------------------------------------------------------------

    def configure(
        self,
        tts_model_path: str,
        tts_config_path: Optional[str],
        stt_model_path: str,
        grammar: List[str],
        tts_device: Optional[int] = None,
        stt_device: Optional[int] = None,
        echo_guard_seconds: float = 0.3,
        max_command_age_seconds: float = 2.0,
    ) -> Dict[str, str]:
        """Call this once at startup with your model paths and command
        grammar. Kept separate from __init__ so `speech` can be imported
        anywhere as a singleton before models are actually loaded.

        A backend that fails to load is reported in `health` rather than
        raised, so a missing mic doesn't take the speaker down with it.
        Returns the health dict."""
        from .stt import VoskSTT
        from .tts import PiperTTS

        tts = stt = None
        try:
            tts = PiperTTS(tts_model_path, tts_config_path, device=tts_device)
        except Exception as exc:  # noqa: BLE001
            log.exception("speech: failed to load TTS backend")
            self._set_health("tts", "fault", f"load_failed: {exc}")
        try:
            stt = VoskSTT(stt_model_path, grammar, device=stt_device)
        except Exception as exc:  # noqa: BLE001
            log.exception("speech: failed to load STT backend")
            self._set_health("stt", "fault", f"load_failed: {exc}")

        return self.attach(
            tts=tts,
            stt=stt,
            echo_guard_seconds=echo_guard_seconds,
            max_command_age_seconds=max_command_age_seconds,
        )

    def attach(
        self,
        tts=None,
        stt=None,
        echo_guard_seconds: float = 0.3,
        max_command_age_seconds: float = 2.0,
    ) -> Dict[str, str]:
        """Wire already-constructed backends (real or fake) and start them.

        `tts` must provide speak/cancel_all/start/shutdown and the
        on_speak_start/on_speak_end/on_fault attributes (see QueuedTTS);
        `stt` must provide start/stop/set_muted and on_command/on_fault."""
        self._echo_guard_seconds = echo_guard_seconds
        self._max_command_age_seconds = max_command_age_seconds

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
                self._set_health("stt", "ready")
            except Exception as exc:  # noqa: BLE001
                log.exception("speech: failed to start STT")
                self._set_health("stt", "fault", f"start_failed: {exc}")

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
    ) -> bool:
        """Queue `text`. Returns False (and logs) if no TTS is available."""
        if self._tts is None:
            log.warning("speech: TTS unavailable; not speaking %r", text)
            return False
        self._tts.speak(text, priority=priority, interrupt=interrupt, ttl_seconds=ttl_seconds)
        return True

    def stop_speaking(self):
        """Cancel current playback and everything queued."""
        if self._tts is not None:
            self._tts.cancel_all()

    # -- listening ------------------------------------------------------------

    def on(self, command: str, handler: Callable[[], None]):
        """Register a callback for a recognized grammar word/phrase.
        `command` must match an entry in the grammar list passed to configure()."""
        self._handlers[command.lower()].append(handler)

    def _on_recognized(self, text: str, recognized_at: float):
        # Called on the STT thread: enqueue only, never run handlers here.
        cmd = _Command(seq=next(self._seq), text=text, recognized_at=recognized_at)
        try:
            self._commands.put_nowait(cmd)
        except queue.Full:
            log.warning("speech: command queue full; dropped %r", text)

    def _dispatch_loop(self):
        while not self._closing.is_set():
            try:
                cmd = self._commands.get(timeout=0.2)
            except queue.Empty:
                continue
            age = time.monotonic() - cmd.recognized_at
            if age > self._max_command_age_seconds:
                log.warning("speech: dropped stale command %r (age %.2fs, seq %d)", cmd.text, age, cmd.seq)
                continue
            handlers = self._handlers.get(cmd.text.lower(), [])
            if not handlers:
                log.info("speech: unmatched utterance %r (seq %d)", cmd.text, cmd.seq)
                continue
            log.info("speech: command %r (seq %d, age %.2fs)", cmd.text, cmd.seq, age)
            for handler in handlers:
                try:
                    handler()
                except Exception:  # noqa: BLE001
                    log.exception("speech: handler for %r raised", cmd.text)

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
