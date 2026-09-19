"""
Piper-based text-to-speech with a priority queue, so urgent (e.g. haptic-
critical) announcements can interrupt lower-priority narration instead of
waiting behind it.

NOTE ON THE PIPER API: piper-tts's Python surface has shifted across
releases. This wraps PiperVoice.synthesize_stream_raw(), which is the
current streaming API as of piper-tts 1.x. Check `pip show piper-tts`
and the project README/examples against your installed version before
relying on this in a demo -- if the method name differs, only
`_synthesize_and_play()` below needs to change; the queueing, threading,
and interrupt logic are independent of the exact Piper call.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

import numpy as np
import sounddevice as sd
from piper import PiperVoice


class Priority(IntEnum):
    LOW = 0     # ambient scene narration -- fine to wait or get dropped
    NORMAL = 1  # command confirmations, status
    HIGH = 2    # obstacle warnings -- interrupts anything lower priority


@dataclass(order=True)
class _SpeechItem:
    sort_key: int
    text: str = field(compare=False)


class PiperTTS:
    def __init__(
        self,
        model_path: str,
        config_path: Optional[str] = None,
        samplerate: Optional[int] = None,
        device: Optional[int] = None,
    ):
        self.voice = PiperVoice.load(model_path, config_path=config_path)
        # Piper voices carry their own sample rate in the config; fall back
        # to a caller-supplied value only if that isn't available.
        self.samplerate = getattr(getattr(self.voice, "config", None), "sample_rate", None) or samplerate or 22050
        self.device = device

        self._queue: "queue.PriorityQueue[_SpeechItem]" = queue.PriorityQueue()
        self._stop_current = threading.Event()
        self._shutdown = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def speak(self, text: str, priority: Priority = Priority.NORMAL, interrupt: bool = False):
        """Queue text for speech.

        Higher `priority` values are spoken first. If `interrupt` is set,
        whatever is currently playing is cut off immediately and any
        queued items of lower priority than this one are dropped -- use
        this for time-critical alerts (e.g. an obstacle warning), not for
        routine narration.
        """
        if interrupt:
            self._stop_current.set()
            self._drop_below(priority)
        # PriorityQueue pops the smallest item first, so store the negative
        # priority to make HIGH come out before LOW.
        self._queue.put(_SpeechItem(sort_key=-int(priority), text=text))

    def _drop_below(self, priority: Priority):
        keep = []
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if -item.sort_key >= int(priority):
                keep.append(item)
        for item in keep:
            self._queue.put(item)

    def _run(self):
        while not self._shutdown.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._stop_current.clear()
            self._synthesize_and_play(item.text)

    def _synthesize_and_play(self, text: str):
        stream = sd.OutputStream(
            samplerate=self.samplerate, channels=1, dtype="int16", device=self.device
        )
        stream.start()
        try:
            for audio_bytes in self.voice.synthesize_stream_raw(text):
                if self._stop_current.is_set():
                    break
                samples = np.frombuffer(audio_bytes, dtype=np.int16)
                stream.write(samples)
        finally:
            stream.stop()
            stream.close()

    def shutdown(self):
        self._shutdown.set()
        self._stop_current.set()
        self._worker.join(timeout=1)