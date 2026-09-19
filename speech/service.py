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

    def configure(
        self,
        tts_model_path: str,
        tts_config_path: Optional[str],
        stt_model_path: str,
        grammar: List[str],
        tts_device: Optional[int] = None,
        stt_device: Optional[int] = None,
    ):
        """Call this once at startup with your model paths and command
        grammar. Kept separate from __init__ so `speech` can be imported
        anywhere as a singleton before models are actually loaded."""
        self._tts = PiperTTS(tts_model_path, tts_config_path, device=tts_device)
        self._stt = VoskSTT(
            stt_model_path, grammar, device=stt_device, on_command=self._dispatch
        )
        self._stt.start()

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