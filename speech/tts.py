"""
Piper-based text-to-speech with a priority queue, so urgent (e.g. haptic-
critical) announcements can interrupt lower-priority narration instead of
waiting behind it.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

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
        on_speak_start: Optional[Callable[[], None]] = None,
        on_speak_end: Optional[Callable[[], None]] = None,
    ):
        self.voice = PiperVoice.load(model_path, config_path=config_path)
        # Piper voices carry their own sample rate in the config; fall back
        # to a caller-supplied value only if that isn't available.
        self.samplerate = getattr(getattr(self.voice, "config", None), "sample_rate", None) or samplerate or 22050
        self.device = device
        # Fired around each item's playback so a caller (SpeechService) can
        # mute the STT mic while the speaker is active, to stop it hearing
        # its own output. Kept as plain callbacks so tts.py doesn't need to
        # know stt.py exists.
        self.on_speak_start = on_speak_start
        self.on_speak_end = on_speak_end

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
            if self.on_speak_start:
                self.on_speak_start()
            try:
                self._synthesize_and_play(item.text)
            finally:
                if self.on_speak_end:
                    self.on_speak_end()

    def _synthesize_and_play(self, text: str):
        stream = sd.OutputStream(
            samplerate=self.samplerate, channels=1, dtype="int16", device=self.device
        )
        stream.start()
        try:
            # voice.synthesize() yields one AudioChunk per sentence, not raw
            # bytes -- pull the int16 samples off it before writing.
            for audio_chunk in self.voice.synthesize(text):
                if self._stop_current.is_set():
                    break
                stream.write(audio_chunk.audio_int16_array)
        finally:
            stream.stop()
            stream.close()

    def shutdown(self):
        self._shutdown.set()
        self._stop_current.set()
        self._worker.join(timeout=1)