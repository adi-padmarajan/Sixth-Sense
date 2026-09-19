"""
Vosk speech-to-text constrained to a fixed command grammar.

Restricting Vosk to a known word/phrase list (instead of open-vocabulary
recognition) makes it faster and much more reliable for a small, fixed
command set -- exactly the "volume up / mute / describe" style commands
this project needs, and well suited to embedded hardware.

Runs mic capture + recognition on a background thread and calls
`on_command(text, recognized_at)` whenever a full utterance matches
something in the grammar. `recognized_at` is `time.monotonic()` at the
end of the utterance so the consumer can reject commands that were
buffered while it was busy. Keep handlers short: the callback runs on the
recognition thread (SpeechService moves dispatch off it).

`speech.fakes.FakeSTT` implements the same surface without a microphone.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

CommandCallback = Callable[[str, float], None]


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

        grammar_list = list(grammar) + ["[unk]"]
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

    def _audio_callback(self, indata, frames, time_info, status):
        # Runs on the PortAudio thread: no logging or blocking here.
        if status:
            self._overflows += 1
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
        else:
            self._muted.clear()
            # Drop any partial utterance state accumulated right up to the
            # mute boundary so we don't splice pre-mute audio onto whatever
            # comes next. Applied by the worker thread.
            self._reset_pending.set()

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
            if self._reset_pending.is_set():
                self._reset_pending.clear()
                self.recognizer.Reset()
            try:
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text and self.on_command:
                        self.on_command(text, time.monotonic())
            except Exception as exc:  # noqa: BLE001 - keep listening
                log.exception("stt: recognition failed")
                self._report_fault(f"recognition_failed: {exc}")
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
                log.exception("stt: on_fault callback raised")

    def stop(self):
        self._running.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._worker is not None:
            self._worker.join(timeout=1)
            self._worker = None
