"""
Vosk speech-to-text constrained to a fixed command grammar.

Restricting Vosk to a known word/phrase list (instead of open-vocabulary
recognition) makes it faster and much more reliable for a small, fixed
command set -- exactly the "volume up / mute / describe" style commands
this project needs, and well suited to embedded hardware.

Runs mic capture + recognition on a background thread and calls
`on_command(text)` whenever a full utterance matches something in the
grammar.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Callable, Iterable, Optional

import sounddevice as sd
from vosk import KaldiRecognizer, Model


class VoskSTT:
    def __init__(
        self,
        model_path: str,
        grammar: Iterable[str],
        samplerate: int = 16000,
        device: Optional[int] = None,
        on_command: Optional[Callable[[str], None]] = None,
    ):
        self.model = Model(model_path)
        self.samplerate = samplerate
        self.device = device
        self.on_command = on_command

        grammar_list = list(grammar) + ["[unk]"]
        self.recognizer = KaldiRecognizer(self.model, samplerate, json.dumps(grammar_list))
        self.recognizer.SetWords(True)

        self._audio_q: "queue.Queue[bytes]" = queue.Queue()
        self._running = threading.Event()
        self._muted = threading.Event()
        self._stream: Optional[sd.RawInputStream] = None
        self._worker: Optional[threading.Thread] = None

    def _audio_callback(self, indata, frames, time_info, status):
        if self._muted.is_set():
            # Dropped at the source (not just skipped downstream) so mic
            # audio captured while the speaker is talking never queues up
            # and gets processed as a command once we unmute.
            return
        self._audio_q.put(bytes(indata))

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
            # comes next.
            self.recognizer.Reset()

    def start(self):
        self._running.set()
        self._stream = sd.RawInputStream(
            samplerate=self.samplerate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self):
        while self._running.is_set():
            try:
                data = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                text = result.get("text", "").strip()
                if text and self.on_command:
                    self.on_command(text)

    def stop(self):
        self._running.clear()
        if self._stream:
            self._stream.stop()
            self._stream.close()
        if self._worker:
            self._worker.join(timeout=1)