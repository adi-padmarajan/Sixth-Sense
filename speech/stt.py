"""
Vosk speech-to-text constrained to a fixed command grammar.

Restricting Vosk to a known word/phrase list (instead of open-vocabulary
recognition) makes it faster and much more reliable for a small, fixed
command set -- exactly the "volume up / mute / describe" style commands
this project needs, and well suited to embedded hardware.

Runs mic capture + recognition on a background thread and calls
`on_command(text, recognized_at, source_mode)` whenever a full utterance
matches something in the grammar. `recognized_at` is `time.monotonic()`
at the end of the utterance so the consumer can reject commands that were
buffered while it was busy; `source_mode` is always "live" here. Keep handlers short: the callback runs on the
recognition thread (SpeechService moves dispatch off it).

`capture(seconds)` records raw mic audio for the OMNI question path,
bypassing the recogniser (Vosk only knows the grammar phrases). Same
stream, same callback -- a second PortAudio stream on one device is the
failure mode that avoids.

`speech.fakes.FakeSTT` implements the same surface without a microphone.
"""

from __future__ import annotations

import io
import json
import logging
import queue
import threading
import time
import wave
from typing import Callable, Iterable, List, Optional

log = logging.getLogger(__name__)

CommandCallback = Callable[[str, float, str], None]
SOURCE_MODE = "live"
SAMPLE_WIDTH = 2  # RawInputStream dtype="int16", mono


def pcm16_to_wav(pcm: bytes, samplerate: int) -> bytes:
    """Frame raw 16-bit mono PCM as a WAV file in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(samplerate)
        w.writeframes(pcm)
    return buf.getvalue()


class _CaptureBuffer:
    """Accumulates callback blocks until `target_bytes` have arrived.

    `append()` runs on the PortAudio thread: no locks, no logging, no
    unbounded storage; the final byte block may be truncated. `max_blocks`
    bounds the list even if the done signalling has a bug. `abort()` wakes the waiter with
    `aborted` set; the buffer is then discarded.
    """

    __slots__ = ("target_bytes", "max_blocks", "blocks", "size", "done", "aborted")

    def __init__(self, target_bytes: int, max_blocks: int):
        self.target_bytes = target_bytes
        self.max_blocks = max_blocks
        self.blocks: List[bytes] = []
        self.size = 0
        self.done = threading.Event()
        self.aborted = False

    def append(self, data: bytes) -> None:
        if self.done.is_set() or len(self.blocks) >= self.max_blocks:
            return
        data = data[:self.target_bytes - self.size]
        self.blocks.append(data)
        self.size += len(data)
        if self.size >= self.target_bytes:
            self.done.set()

    def abort(self) -> None:
        self.aborted = True
        self.done.set()

    def pcm(self) -> bytes:
        # Truncate the last block so the result is exactly the requested length.
        return b"".join(self.blocks)[: self.target_bytes]


class VoskSTT:
    def __init__(
        self,
        model_path: str,
        grammar: Iterable[str],
        samplerate: int = 16000,
        device: Optional[int] = None,
        on_command: Optional[CommandCallback] = None,
        on_fault: Optional[Callable[[str], None]] = None,
        blocksize: int = 4000,
        max_queue_blocks: int = 20,
        max_capture_seconds: float = 10.0,
    ):
        # Imported here so the package (and its fakes/tests) can be used on
        # machines without vosk or PortAudio installed.
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model

        self._sd = sd
        self.model = Model(model_path)
        self.samplerate = samplerate
        self.device = device
        # blocksize is in samples: 4000 @ 16 kHz = 250 ms of audio per
        # callback, which bounds how long an utterance end waits before
        # Vosk sees it. Provisional; measure against the voice-ack goal.
        self.blocksize = blocksize
        self.on_command = on_command
        self.on_fault = on_fault
        self.fault_reason: Optional[str] = None
        self.max_capture_seconds = max_capture_seconds

        # Vosk silently drops words it doesn't know, which would turn a
        # phrase like "unmute" into nothing. Check every word up front and
        # keep the unsupported phrases out of the grammar so the rest still
        # recognize cleanly; the caller reports them via health.
        self.grammar: List[str] = []
        self.unsupported_phrases: List[str] = []
        for phrase in grammar:
            phrase = phrase.strip().lower()
            if not phrase:
                continue
            missing = [w for w in phrase.split() if self.model.vosk_model_find_word(w) < 0]
            if missing:
                log.warning("stt: grammar phrase %r has out-of-vocabulary word(s) %s; disabled", phrase, missing)
                self.unsupported_phrases.append(phrase)
            else:
                self.grammar.append(phrase)
        if not self.grammar:
            raise ValueError("stt: no grammar phrase is supported by this model")

        grammar_list = self.grammar + ["[unk]"]
        self.recognizer = KaldiRecognizer(self.model, samplerate, json.dumps(grammar_list))
        self.recognizer.SetWords(True)

        # Bounded so a stalled worker can't accumulate minutes of audio
        # that then gets recognized (and acted on) long after it was said.
        self._audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=max_queue_blocks)
        self._dropped_blocks = 0
        self._overflows = 0
        self._running = threading.Event()
        self._muted = threading.Event()
        # KaldiRecognizer is not thread-safe, so Reset() must happen on the
        # worker thread; set_muted() only requests it.
        self._reset_pending = threading.Event()
        self._stream = None
        self._worker: Optional[threading.Thread] = None
        self._init_capture_state()

    def _init_capture_state(self):
        # Question capture (see capture()). The lock serialises callers;
        # the event is what the audio callback checks.
        self._capture_lock = threading.Lock()
        self._capturing = threading.Event()
        self._capture: Optional[_CaptureBuffer] = None

    def _audio_callback(self, indata, frames, time_info, status):
        # Runs on the PortAudio thread: no logging or blocking here.
        if status:
            self._overflows += 1
        if self._capturing.is_set():
            # Question recording: divert to the capture buffer, never to
            # the recogniser. Checked before mute so a mute that lands
            # mid-capture is handled by capture() (abort), not here.
            buf = self._capture
            if buf is not None:
                buf.append(bytes(indata))
            return
        if self._muted.is_set():
            # Dropped at the source (not just skipped downstream) so mic
            # audio captured while the speaker is talking never queues up
            # and gets processed as a command once we unmute.
            return
        try:
            self._audio_q.put_nowait(bytes(indata))
        except queue.Full:
            self._dropped_blocks += 1

    def set_muted(self, muted: bool):
        """Stop (or resume) feeding mic audio to the recognizer.

        Used to keep the TTS output from being picked up by the mic and
        misrecognized as a voice command -- callers should mute while the
        speaker is playing and briefly after (to cover echo/room tail)."""
        if muted:
            self._muted.set()
            # An alert (HIGH TTS) always wins over a question in progress:
            # abandon the capture rather than record our own speaker.
            buf = self._capture
            if buf is not None:
                buf.abort()
        else:
            self._muted.clear()
            # Drop any partial utterance state accumulated right up to the
            # mute boundary so we don't splice pre-mute audio onto whatever
            # comes next. Applied by the worker thread.
            self._reset_pending.set()

    @property
    def is_capturing(self) -> bool:
        return self._capturing.is_set()

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    def capture(self, seconds: float, *, timeout: Optional[float] = None) -> Optional[bytes]:
        """Record `seconds` of raw mic audio, bypassing the recogniser, and
        return it as a 16 kHz mono 16-bit WAV. Blocks the caller for
        ~`seconds`. Returns None if capture could not start (already
        capturing, muted, not running) or did not complete in time (stream
        stalled, or muted mid-capture by a speech alert). Never raises for
        those cases; a bad `seconds` is a caller bug and raises ValueError.

        Duration is enforced by sample count, not wall clock; `timeout`
        (default seconds + 1) is only the safety net for a stalled stream.
        Afterwards the recogniser is reset since its utterance boundary is
        gone. Call from a worker thread, never from a speech handler."""
        if not (0 < seconds <= self.max_capture_seconds):
            raise ValueError(
                f"capture seconds must be in (0, {self.max_capture_seconds}], got {seconds!r}")
        if not self._running.is_set() or self._muted.is_set():
            return None
        if not self._capture_lock.acquire(blocking=False):
            return None
        try:
            frames = int(seconds * self.samplerate)
            self._drain_audio()
            buf = _CaptureBuffer(frames * SAMPLE_WIDTH, frames // self.blocksize + 2)
            self._capture = buf
            self._capturing.set()
            if not self._running.is_set() or self._muted.is_set():
                # Stop or mute landed between the check above and arming the buffer.
                return None
            finished = buf.done.wait(seconds + 1.0 if timeout is None else timeout)
            if not finished or buf.aborted:
                return None
            return pcm16_to_wav(buf.pcm(), self.samplerate)
        finally:
            self._capturing.clear()
            self._capture = None
            self._reset_pending.set()
            self._drain_audio()
            self._capture_lock.release()

    def _drain_audio(self):
        """Discard pre-capture audio so it cannot become delayed commands."""
        while True:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                return

    def start(self):
        if self._running.is_set():
            return
        self._running.set()
        try:
            self._stream = self._sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=self.blocksize,
                dtype="int16",
                channels=1,
                device=self.device,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception:
            self._running.clear()
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    log.warning("stt_cleanup_failed reason=stream_close_failed")
            self._stream = None
            raise
        self._worker = threading.Thread(target=self._run, name="stt-worker", daemon=True)
        self._worker.start()

    def _run(self):
        last_stats_log = time.monotonic()
        while self._running.is_set():
            try:
                data = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._muted.is_set() or self._capturing.is_set():
                continue
            try:
                if self._reset_pending.is_set():
                    self._reset_pending.clear()
                    self.recognizer.Reset()
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text and self.on_command:
                        self.on_command(text, time.monotonic(), SOURCE_MODE)
            except Exception as exc:  # noqa: BLE001 - keep listening
                log.warning("stt_fault reason=recognition_failed error=%s", type(exc).__name__)
                self._report_fault("recognition_failed")
                self._reset_pending.set()

            now = time.monotonic()
            if now - last_stats_log > 5 and (self._dropped_blocks or self._overflows):
                log.warning(
                    "stt: dropped %d audio block(s), %d input overflow(s) in last interval",
                    self._dropped_blocks, self._overflows,
                )
                self._dropped_blocks = self._overflows = 0
                last_stats_log = now

    def _report_fault(self, reason: str):
        self.fault_reason = reason
        if self.on_fault:
            try:
                self.on_fault(reason)
            except Exception:  # noqa: BLE001
                log.warning("stt_callback_failed reason=on_fault_failed")

    def stop(self):
        self._running.clear()
        buf = self._capture
        if buf is not None:
            buf.abort()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                log.warning("stt_cleanup_failed reason=stream_stop_failed")
            finally:
                try:
                    stream.close()
                except Exception:
                    log.warning("stt_cleanup_failed reason=stream_close_failed")
        if self._worker is not None:
            self._worker.join(timeout=1)
            self._worker = None
