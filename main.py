"""Camera preview, local speech, and one assistant question at a time.

Run from the repository root. Cloud access is off unless configured or --cloud
is supplied; OMNI_FAKE=1 selects canned answers with real camera/speech.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from omni.client import AssistantResult, OmniClient
from omni.config import AssistantConfig
from omni.fake import FakeOmniClient
from omni.scene import describe_and_speak
from speech import Command, Priority, SpeechConfig, SpeechService, speech


log = logging.getLogger("sixth_sense.orchestrator")


def log_event(session_id, event, *, level=logging.INFO, **fields):
    """JSON lines contain metadata only, never questions, media or credentials."""
    log.log(level, json.dumps(dict(session_id=session_id, event=event, **fields)))


def check_grammar(speech_cfg: SpeechConfig, cfg: AssistantConfig):
    for command in (cfg.describe_command, cfg.direct_question_command):
        if command not in speech_cfg.grammar:
            raise ValueError(f"assistant command {command!r} is missing from the speech grammar")


class Orchestrator:
    def __init__(self, speech: SpeechService, speech_cfg: SpeechConfig,
                 cfg: AssistantConfig, state, client, *, session_id: str | None = None):
        check_grammar(speech_cfg, cfg)
        self.speech, self.speech_cfg, self.cfg = speech, speech_cfg, cfg
        self.state, self.client = state, client
        self.session_id = session_id or uuid.uuid4().hex
        self.cloud_state = "fake" if isinstance(client, FakeOmniClient) else (
            "on" if client.config.cloud_enabled else "off")
        self._busy = threading.Lock()
        self._lifecycle = threading.Lock()
        self._closing = threading.Event()
        self._worker: threading.Thread | None = None
        speech.on(cfg.describe_command, lambda cmd: self.start_question(cmd, capture=True))
        speech.on(cfg.direct_question_command, lambda cmd: self.start_question(cmd, capture=False))
        speech.on("device status", lambda cmd: self.say_status())
        speech.on("stop speaking", lambda cmd: speech.stop_speaking())

    @property
    def question_in_flight(self):
        return self._busy.locked()

    def start_question(self, cmd: Command, capture: bool):
        # No mic/cloud work on the dispatcher; no queue of questions.
        with self._lifecycle:
            if self._closing.is_set():
                return
            if not self._busy.acquire(blocking=False):
                log_event(self.session_id, "question_dropped", reason="busy", seq=cmd.seq)
                return
            try:
                self._worker = threading.Thread(target=self._run_question, args=(cmd, capture),
                                                daemon=True, name="assistant")
                self._worker.start()
            except Exception:
                self._worker = None
                self._busy.release()
                raise

    def speak(self, text, priority=Priority.NORMAL, **kwargs):
        # The scene helper uses this handoff so a late worker cannot enqueue
        # speech after shutdown has started, even if the 2-second join expired.
        with self._lifecycle:
            if self._closing.is_set():
                return False
            return self.speech.speak(text, priority=priority, **kwargs)

    def _run_question(self, cmd: Command, capture: bool):
        t0 = time.monotonic()
        capture_end = t0
        assistant_start = None
        result = AssistantResult.unavailable("closing")
        try:
            if self._closing.is_set():
                return
            wav = self.speech.capture_question(self.speech_cfg.question_seconds) if capture else None
            capture_end = time.monotonic()
            if self._closing.is_set():
                return
            if capture and wav is None:
                result = AssistantResult("unavailable", "I could not hear the question", "capture_failed")
                self.speak(result.text, Priority.NORMAL, ttl_seconds=2)
                return
            assistant_start = time.monotonic()
            result = describe_and_speak(
                self.state, self.client, self, wav=wav, prompt=self.cfg.direct_question_prompt,
                max_age_s=self.cfg.max_scene_age_ms / 1000,
                answer_within_s=self.cfg.answer_within_ms / 1000,
                jpeg_width=self.cfg.frame_jpeg_width,
            )
        except Exception:
            # Backend failures must not strand the lock or log media-bearing exceptions.
            result = AssistantResult.unavailable("worker_failed")
            self.speak(result.text, Priority.NORMAL, ttl_seconds=2)
        finally:
            ended = time.monotonic()
            if self._closing.is_set():
                result = replace(result, status="unavailable", reason="closing")
            try:
                log_event(
                    self.session_id, "question_completed", seq=cmd.seq,
                    source_mode=result.source_mode, status=result.status, reason=result.reason,
                    call_id=result.call_id, capture_ms=round((capture_end - t0) * 1000, 3) if capture else 0.0,
                    assistant_ms=round((ended - assistant_start) * 1000, 3) if assistant_start else 0.0,
                    total_ms=round((ended - cmd.recognized_at) * 1000, 3),
                )
            finally:
                self._busy.release()

    def say_status(self):
        health = self.speech.health
        listening = health.get("stt", "unavailable")
        if listening not in ("ready", "partial"):
            listening = "unavailable"
        camera = "live" if self.state.read(self.cfg.max_scene_age_ms / 1000) is not None else "unavailable"
        question = "in flight" if self.question_in_flight else "idle"
        self.speak(f"Speech {health.get('tts', 'unavailable')}, listening {listening}, "
                   f"cloud {self.cloud_state}, camera {camera}, question {question}.",
                   Priority.NORMAL, ttl_seconds=5)

    def close(self):
        with self._lifecycle:
            self._closing.set()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", action="store_true", help="Enable cloud requests (requires YIBU_API_KEY)")
    parser.add_argument("--source", type=Path, help="Replay an image/video instead of camera 0")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    session_id = uuid.uuid4().hex

    def startup(step, result="ok", **fields):
        log_event(session_id, "startup", step=step, result=result, **fields)

    orch = state = None
    try:
        speech_cfg = SpeechConfig.load("configs/speech.json")
        startup("speech_config")
        cfg = AssistantConfig.load("configs/assistant.json")
        startup("assistant_config")
        check_grammar(speech_cfg, cfg)
        startup("grammar")
        fake = os.environ.get("OMNI_FAKE") == "1"
        enabled = args.cloud or cfg.cloud_enabled
        client = FakeOmniClient() if fake else OmniClient(cfg.client_config(cloud_enabled=enabled))
        cloud_state = "fake" if fake else "on" if enabled else "off"
        startup("client", cloud_state=cloud_state)
        if enabled and not fake and not os.environ.get("YIBU_API_KEY"):
            log_event(session_id, "startup", level=logging.WARNING, step="credentials",
                      result="warning", reason="not_configured")
        health = speech.configure(speech_cfg)
        startup("speech", result="ready" if all(v == "ready" for v in health.values()) else "partial",
                health=health)
        # Same explicit entry-point bridge as omni.demo; never import YOLO in tests.
        sys.path.insert(0, str(Path(__file__).resolve().parent / "computer-vision"))
        from scene_state import SceneState

        state = SceneState()
        startup("scene_state")
        orch = Orchestrator(speech, speech_cfg, cfg, state, client, session_id=session_id)
        startup("handlers")
        speech.speak(f"system ready. cloud {cloud_state}.", Priority.NORMAL)
        startup("ready", cloud_state=cloud_state)
        import track_distances

        if args.source is not None:
            track_distances.SOURCE = str(args.source)
        startup("preview", cloud_state=cloud_state,
                source_mode="live" if isinstance(track_distances.SOURCE, int) else "replay")
        track_distances.main(state)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError):
        log_event(session_id, "startup", level=logging.ERROR, step="initialization",
                  result="failed", reason="invalid_config_or_resource")
        raise
    finally:
        if orch is not None:
            orch.close()
        speech.shutdown()
        if state is not None:
            state.reset()
        log_event(session_id, "shutdown", result="complete")


if __name__ == "__main__":
    raise SystemExit(main())
