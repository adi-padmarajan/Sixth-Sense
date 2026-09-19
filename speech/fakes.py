"""
Device-free stand-ins for the speech backends.

Same surface as `PiperTTS` / `VoskSTT`, no models, no PortAudio. Used by
the test suite and available to the simulator so the rest of the project
can run without a mic or speaker attached.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from .tts import QueuedTTS


class FakeTTS(QueuedTTS):
    """Records what would have been spoken.

    `play_seconds` makes each item take that long to "play", polling the
    stop flag like the real backend, so interrupt behaviour can be tested.
    `fail_on` names a text whose playback raises, to exercise fault paths.
    """

    def __init__(self, play_seconds: float = 0.0, fail_on: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.play_seconds = play_seconds
        self.fail_on = fail_on
        self.spoken: List[str] = []     # started playback
        self.completed: List[str] = []  # finished without interruption

    def _synthesize_and_play(self, text: str, should_stop: Callable[[], bool]):
        if text == self.fail_on:
            raise RuntimeError(f"fake playback failure for {text!r}")
        self.spoken.append(text)
        deadline = time.monotonic() + self.play_seconds
        while time.monotonic() < deadline:
            if should_stop():
                return
            time.sleep(0.002)
        self.completed.append(text)


class FakeSTT:
    """Feeds scripted utterances to `on_command` via `inject()`.

    Mirrors the real backend's drop-at-source behaviour: text injected
    while muted is discarded, and unmuting counts a recognizer reset.
    """

    def __init__(self):
        self.on_command: Optional[Callable[[str, float], None]] = None
        self.on_fault: Optional[Callable[[str], None]] = None
        self.fault_reason: Optional[str] = None
        self.started = False
        self.muted = False
        self.resets = 0
        self.dropped_while_muted: List[str] = []

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def set_muted(self, muted: bool):
        self.muted = muted
        if not muted:
            self.resets += 1

    def inject(self, text: str, recognized_at: Optional[float] = None) -> bool:
        """Simulate a recognized utterance. Returns False if it was
        dropped because the mic is muted or the backend isn't running."""
        if not self.started or self.muted:
            self.dropped_while_muted.append(text)
            return False
        if self.on_command:
            self.on_command(text, time.monotonic() if recognized_at is None else recognized_at)
        return True

    def fail(self, reason: str):
        """Simulate a recognition fault."""
        self.fault_reason = reason
        if self.on_fault:
            self.on_fault(reason)
