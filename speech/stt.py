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
        self._stream: Optional[sd.RawInputStream] = None
        self._worker: Optional[threading.Thread] = None

    def _audio_callback(self, indata, frames, time_info, status):
        self._audio_q.put(bytes(indata))

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