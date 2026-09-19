"""
SpeechService: the one access point other parts of the project should use
for speech I/O. Sensor fusion, haptics, and the orchestrator should import
`speech` from here and never touch tts.py / stt.py directly -- that's what
lets the backend, transport, or even the OS underneath this module change
later without touching the rest of the codebase.

Example, from any other module:

    from speech.service import speech, Priority

    speech.speak("obstacle close, front left", priority=Priority.HIGH, interrupt=True)
    speech.on("mute", lambda: haptics.set_muted(True))
    speech.on("volume up", lambda: audio.change_volume(+10))

If subsystems later end up split across processes or languages (e.g. a
QNX process reading sonar sensors and this module running on a companion
Linux board), keep this class's public methods the same and add a thin
transport in front of it -- see `_maybe_start_ipc_server()` below for the
extension point. Don't build that until you actually need it.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from .tts import PiperTTS, Priority
from .stt import VoskSTT

__all__ = ["SpeechService", "Priority", "speech"]


class SpeechService:
    def __init__(self):
        self._tts: Optional[PiperTTS] = None
        self._stt: Optional[VoskSTT] = None
        self._handlers: Dict[str, List[Callable[[], None]]] = defaultdict(list)
        # How long to keep the mic muted after TTS playback ends, to cover
        # speaker/room echo tail and mic latency before we trust input again.
        self._echo_guard_seconds = 0.3
        self._unmute_timer: Optional[threading.Timer] = None

    def configure(
        self,
        tts_model_path: str,
        tts_config_path: Optional[str],
        stt_model_path: str,
        grammar: List[str],
        tts_device: Optional[int] = None,
        stt_device: Optional[int] = None,
        echo_guard_seconds: float = 0.3,
    ):
        """Call this once at startup with your model paths and command
        grammar. Kept separate from __init__ so `speech` can be imported
        anywhere as a singleton before models are actually loaded."""
        self._echo_guard_seconds = echo_guard_seconds
        self._stt = VoskSTT(
            stt_model_path, grammar, device=stt_device, on_command=self._dispatch
        )
        # Mute the mic for the duration of TTS playback (plus a short tail)
        # so the STT never mistakes our own voice output for a command.
        self._tts = PiperTTS(
            tts_model_path,
            tts_config_path,
            device=tts_device,
            on_speak_start=self._on_speak_start,
            on_speak_end=self._on_speak_end,
        )
        self._stt.start()

    def _on_speak_start(self):
        if self._unmute_timer:
            self._unmute_timer.cancel()
        if self._stt:
            self._stt.set_muted(True)

    def _on_speak_end(self):
        if self._unmute_timer:
            self._unmute_timer.cancel()
        self._unmute_timer = threading.Timer(self._echo_guard_seconds, self._unmute_stt)
        self._unmute_timer.daemon = True
        self._unmute_timer.start()

    def _unmute_stt(self):
        if self._stt:
            self._stt.set_muted(False)

    def speak(self, text: str, priority: Priority = Priority.NORMAL, interrupt: bool = False):
        if not self._tts:
            raise RuntimeError("SpeechService.configure() has not been called yet")
        self._tts.speak(text, priority=priority, interrupt=interrupt)

    def on(self, command: str, handler: Callable[[], None]):
        """Register a callback for a recognized grammar word/phrase.
        `command` must match an entry in the grammar list passed to configure()."""
        self._handlers[command.lower()].append(handler)

    def _dispatch(self, text: str):
        for handler in self._handlers.get(text.lower(), []):
            handler()

    def shutdown(self):
        if self._unmute_timer:
            self._unmute_timer.cancel()
        if self._tts:
            self._tts.shutdown()
        if self._stt:
            self._stt.stop()

    def _maybe_start_ipc_server(self, socket_path: str = "/tmp/echoband_speech.sock"):
        """
        Extension point, not yet implemented on purpose: if sensors/haptics
        end up living in a different process or language than this module
        (e.g. a QNX C process talking to a Linux Python process), expose
        speak()/on() over a local Unix socket as newline-delimited JSON,
        e.g. {"cmd": "speak", "text": "...", "priority": 2}. Leave this
        alone until you actually know your process/board split -- adding
        it speculatively just adds a moving part to debug this weekend.
        """
        raise NotImplementedError


# Module-level singleton -- this is what other files should import.
speech = SpeechService()