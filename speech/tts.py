"""
Text-to-speech with a priority queue, so urgent announcements can interrupt
lower-priority narration instead of waiting behind it.

`QueuedTTS` owns the queue, worker thread, interrupt/cancel logic, expiry,
and fault reporting. It knows nothing about audio libraries -- subclasses
implement `_synthesize_and_play()`. `PiperTTS` is the real backend;
`speech.fakes.FakeTTS` is the device-free one used by tests.
"""

from __future__ import annotations

import itertools
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)


class Priority(IntEnum):
    LOW = 0     # ambient scene narration -- fine to wait or get dropped
    NORMAL = 1  # command confirmations, status
    HIGH = 2    # obstacle warnings -- interrupts anything lower priority


@dataclass(order=True)
class _SpeechItem:
    # PriorityQueue pops the smallest item first, so sort_key is the
    # negated priority. `seq` breaks ties so equal-priority items are
    # spoken in the order they were queued (heapq alone isn't stable).
    sort_key: int
    seq: int
    text: str = field(compare=False)
    expires_at: Optional[float] = field(compare=False, default=None)
    on_started: Optional[Callable[[float], None]] = field(compare=False, default=None)
    is_valid: Optional[Callable[[], bool]] = field(compare=False, default=None)
    bypass_mute: bool = field(compare=False, default=False)
    generation: int = field(compare=False, default=0)

    @property
    def priority(self) -> int:
        return -self.sort_key


class QueuedTTS:
    """Priority-queued speech worker. Subclass and implement
    `_synthesize_and_play(text, should_stop)`.

    Thread model: `speak()` / `cancel_all()` may be called from any thread.
    `_synthesize_and_play` runs on the single worker thread, as do the
    `on_speak_start` / `on_speak_end` / `on_fault` callbacks.
    """

    def __init__(
        self,
        on_speak_start: Optional[Callable[[], None]] = None,
        on_speak_end: Optional[Callable[[], None]] = None,
        on_fault: Optional[Callable[[str], None]] = None,
        max_queue: int = 16,
        dedup_window_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        # Fired around each item's playback so a caller (SpeechService) can
        # mute the STT mic while the speaker is active. Kept as plain
        # callbacks so this module doesn't need to know stt.py exists.
        self.on_speak_start = on_speak_start
        self.on_speak_end = on_speak_end
        # Fired when playback of an item fails. The worker keeps running;
        # this exists so the caller can surface degraded health.
        self.on_fault = on_fault
        self.fault_reason: Optional[str] = None

        self._max_queue = max_queue
        # Identical text queued again within this window is suppressed
        # (unless HIGH or interrupting) so a chatty caller can't stack up
        # "obstacle ahead" ten times. 0 disables.
        self._dedup_window = dedup_window_seconds
        self._recent: Dict[str, float] = {}
        self._clock = clock
        self._queue: "queue.PriorityQueue[_SpeechItem]" = queue.PriorityQueue()
        self._seq = itertools.count()
        # Guards queue mutation from speak()/cancel_all() and the
        # interrupt bookkeeping below.
        self._lock = threading.Lock()
        self._stop_current = threading.Event()
        # Set by an interrupting speak(): any item popped afterwards with a
        # lower priority than this is discarded. Closes the window where
        # the worker has already popped a low-priority item but hasn't
        # started playing it, so `_drop_below` couldn't see it.
        self._interrupt_floor: Optional[int] = None
        self._current: Optional[_SpeechItem] = None
        self._shutdown = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._volume_level = 5  # absolute host-local gain, 1..5 (5 = full scale, the
        # pre-volume-control loudness); never a mic setting
        self._muted = False
        self._generation = 0
        self._started_current = False

    # -- public API ---------------------------------------------------------

    def start(self):
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._run, name="tts-worker", daemon=True)
        self._worker.start()

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
        """Queue text for speech. Return whether this queue accepted the item.
        Muted, expired, duplicate, shutdown or evicted items return False.

        Higher `priority` values are spoken first. If `interrupt` is set,
        whatever is currently playing is cut off and any queued items of
        lower priority than this one are dropped -- use this for
        time-critical alerts, not for routine narration.

        `ttl_seconds` discards the item if it hasn't started playing by
        then; use it for scene descriptions that go stale. `on_started(at)`
        receives monotonic first-PCM-submission time after synthesis, once.
        `is_valid()` is polled before/between audio blocks for session expiry.
        `bypass_mute` is reserved for audible host audio-control confirmations.
        """
        if ttl_seconds is not None and (not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            return False
        now = self._clock()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        item = _SpeechItem(
            sort_key=-int(priority), seq=next(self._seq), text=text, expires_at=expires_at,
            on_started=on_started, is_valid=is_valid, bypass_mute=bypass_mute,
        )
        with self._lock:
            if self._shutdown.is_set() or (self._muted and priority < Priority.HIGH and not bypass_mute):
                return False
            item.generation = self._generation
            if not bypass_mute and self._is_repeat(text, now, priority, interrupt):
                log.info("tts: suppressed repeat %r (within %.1fs)", text, self._dedup_window)
                return False
            if interrupt:
                self._stop_current.set()
                self._interrupt_floor = int(priority)
                self._drop_below(priority)
            return self._put_bounded(item)

    @property
    def volume_level(self) -> int:
        return self._volume_level

    @property
    def muted(self) -> bool:
        return self._muted

    def set_volume(self, level: int) -> int:
        if type(level) is not int or not 1 <= level <= 5:
            raise ValueError("volume level must be an integer in 1..5")
        with self._lock:
            self._volume_level = level
        return level

    def set_muted(self, muted: bool) -> None:
        if type(muted) is not bool:
            raise ValueError("muted must be boolean")
        with self._lock:
            self._muted = muted
            if muted:
                if self._current is not None and self._current.priority < Priority.HIGH:
                    self._stop_current.set()
                self._drop_below(Priority.HIGH)

    def cancel_all(self):
        """Cut off current playback and drop everything queued."""
        with self._lock:
            self._generation += 1
            self._stop_current.set()
            self._interrupt_floor = None
            dropped = self._drain()
        if dropped:
            log.info("tts: cancelled %d queued item(s)", len(dropped))

    @property
    def busy(self) -> bool:
        return self._current is not None or not self._queue.empty()

    def wait_idle(self, timeout: float) -> bool:
        """Block until nothing is queued or playing. Returns False on timeout."""
        deadline = time.monotonic() + timeout
        while self.busy:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        return True

    def shutdown(self):
        self._shutdown.set()
        self.cancel_all()
        if self._worker is not None:
            self._worker.join(timeout=2)

    # -- subclass hook --------------------------------------------------------

    def _synthesize_and_play(self, text: str, should_stop: Callable[[], bool]):
        """Synthesize and play `text`. Poll `should_stop()` between small
        blocks of audio and return early when it is true."""
        raise NotImplementedError

    def _on_worker_exit(self):
        """Called once on the worker thread as it shuts down; release
        audio resources here."""

    def _playback_started(self) -> bool:
        """First audio-write handoff after synthesis, not physical speaker onset."""
        item = self._current
        if item is None or self._should_stop():
            return False
        if not self._started_current:
            if item.expires_at is not None and self._clock() >= item.expires_at:
                return False
            self._started_current = True
            if item.on_started:
                try:
                    item.on_started(self._clock())
                except Exception:
                    log.warning("speech_callback_failed reason=on_started_failed")
        return True

    def _should_stop(self) -> bool:
        item = self._current
        return (self._shutdown.is_set() or self._stop_current.is_set()
                or item is None or item.generation != self._generation
                or (self._muted and item.priority < Priority.HIGH and not item.bypass_mute)
                or (item.is_valid is not None and not item.is_valid()))

    # -- internals ------------------------------------------------------------

    def _is_repeat(self, text: str, now: float, priority: Priority, interrupt: bool) -> bool:
        """Dedup bookkeeping; call with `_lock` held."""
        if self._dedup_window <= 0:
            return False
        last = self._recent.get(text)
        if (priority < Priority.HIGH and not interrupt
                and last is not None and now - last < self._dedup_window):
            return True
        self._recent[text] = now
        if len(self._recent) > 64:
            cutoff = now - self._dedup_window
            self._recent = {t: at for t, at in self._recent.items() if at >= cutoff}
            while len(self._recent) > 64:
                self._recent.pop(next(iter(self._recent)))
        return False

    def _drain(self) -> List[_SpeechItem]:
        items = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                return items

    def _drop_below(self, priority: Priority):
        for item in self._drain():
            if item.priority >= int(priority):
                self._queue.put(item)
            else:
                log.info("tts: dropped queued %r (priority %d < %d)", item.text, item.priority, int(priority))

    def _put_bounded(self, item: _SpeechItem):
        if self._queue.qsize() < self._max_queue:
            self._queue.put(item)
            return True
        # Queue full: keep the highest-priority / oldest items, drop the
        # single lowest-priority newest one (which may be the new item).
        items = self._drain()
        items.append(item)
        items.sort()
        dropped = items.pop()
        for keep in items:
            self._queue.put(keep)
        log.warning("tts: queue full (%d); dropped %r", self._max_queue, dropped.text)
        return dropped is not item

    def _run(self):
        try:
            self._loop()
        finally:
            try:
                self._on_worker_exit()
            except Exception:  # noqa: BLE001
                log.warning("tts_cleanup_failed reason=worker_exit_failed")

    def _loop(self):
        while not self._shutdown.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            with self._lock:
                floor = self._interrupt_floor
                self._interrupt_floor = None
                self._stop_current.clear()
                if item.generation != self._generation or self._shutdown.is_set():
                    continue
                if floor is not None and item.priority < floor:
                    log.info("tts: dropped %r (popped during interrupt)", item.text)
                    continue
                if item.expires_at is not None and self._clock() >= item.expires_at:
                    log.info("tts: dropped %r (expired before playback)", item.text)
                    continue
                self._current = item
                self._started_current = False

            guarded = False
            try:
                if self._should_stop():
                    continue
                if self.on_speak_start:
                    self.on_speak_start()
                    guarded = True
                self._synthesize_and_play(item.text, self._should_stop)
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                log.warning("tts_fault reason=playback_failed error=%s", type(exc).__name__)
                self._report_fault("playback_failed")
                # Avoid spinning if the audio device is gone for good.
                self._shutdown.wait(0.5)
            finally:
                self._current = None
                if guarded and self.on_speak_end:
                    try:
                        self.on_speak_end()
                    except Exception:
                        log.warning("tts_callback_failed reason=on_speak_end_failed")
                        self._report_fault("on_speak_end_failed")

    def _report_fault(self, reason: str):
        self.fault_reason = reason
        if self.on_fault:
            try:
                self.on_fault(reason)
            except Exception:  # noqa: BLE001
                log.warning("tts_callback_failed reason=on_fault_failed")


class PiperTTS(QueuedTTS):
    """Piper (ONNX) synthesis played through sounddevice."""

    def __init__(
        self,
        model_path: str,
        config_path: Optional[str] = None,
        samplerate: Optional[int] = None,
        device: Optional[int] = None,
        on_speak_start: Optional[Callable[[], None]] = None,
        on_speak_end: Optional[Callable[[], None]] = None,
        on_fault: Optional[Callable[[str], None]] = None,
        write_block_samples: int = 1024,
        max_queue: int = 16,
        dedup_window_seconds: float = 2.0,
    ):
        # Imported here so the package (and its fakes/tests) can be used on
        # machines without piper or PortAudio installed.
        import sounddevice as sd
        from piper import PiperVoice

        super().__init__(
            on_speak_start=on_speak_start,
            on_speak_end=on_speak_end,
            on_fault=on_fault,
            max_queue=max_queue,
            dedup_window_seconds=dedup_window_seconds,
        )
        self._sd = sd
        self._stream = None  # opened lazily on the worker thread, reused across utterances
        self.voice = PiperVoice.load(model_path, config_path=config_path)
        # Piper voices carry their own sample rate in the config; fall back
        # to a caller-supplied value only if that isn't available.
        self.samplerate = getattr(getattr(self.voice, "config", None), "sample_rate", None) or samplerate or 22050
        self.device = device
        # Audio is written in blocks this size so an interrupt lands within
        # ~write_block_samples / samplerate seconds instead of waiting for
        # the whole sentence Piper hands back.
        self.write_block_samples = write_block_samples

    def _open_stream(self):
        if self._stream is None:
            self._stream = self._sd.OutputStream(
                samplerate=self.samplerate, channels=1, dtype="int16", device=self.device
            )
        return self._stream

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                log.warning("tts_cleanup_failed reason=stream_close_failed")

    def _synthesize_and_play(self, text: str, should_stop: Callable[[], bool]):
        # One OutputStream lives across utterances (opening the device is
        # the slow part); it is started/stopped per utterance so a normal
        # end drains buffered audio before on_speak_end fires. Any error
        # drops the stream so the next utterance reopens the device.
        try:
            stream = self._open_stream()
            stream.start()
        except Exception:
            self._close_stream()
            raise
        stopped_early = False
        try:
            # voice.synthesize() yields one AudioChunk per sentence, not raw
            # bytes -- pull the int16 samples off it before writing.
            for audio_chunk in self.voice.synthesize(text):
                samples = audio_chunk.audio_int16_array
                for start in range(0, len(samples), self.write_block_samples):
                    if should_stop() or not self._playback_started():
                        stopped_early = True
                        return
                    block = samples[start : start + self.write_block_samples]
                    stream.write((block.astype("float32") * (self.volume_level / 5)).astype("int16"))
        except Exception:
            self._close_stream()
            raise
        finally:
            if self._stream is not None:
                try:
                    if stopped_early:
                        stream.abort()  # don't drain what's buffered
                    else:
                        stream.stop()   # waits for buffered audio to finish
                except Exception:  # noqa: BLE001
                    log.warning("tts_cleanup_failed reason=stream_stop_failed")
                    self._close_stream()

    def _on_worker_exit(self):
        self._close_stream()
