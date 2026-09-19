"""Orchestrator tests: synthetic pixels, fake speech, no devices or network."""
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from main import Orchestrator
from omni.config import AssistantConfig
from omni.fake import FakeOmniClient
from speech import Priority, SpeechConfig, SpeechService
from speech.fakes import FakeSTT, FakeTTS
from test_speech import wait_for

# Same entry-point bridge as omni.demo; importing SceneState opens no devices.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "computer-vision"))
from scene_state import SceneState


class BlockedClient(FakeOmniClient):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, *args, **kwargs):
        result = super().complete(*args, **kwargs)
        self.entered.set()
        assert self.release.wait(3), "test did not release the assistant"
        return result


@pytest.fixture
def build(caplog):
    caplog.set_level("INFO", logger="sixth_sense.orchestrator")
    instances = []

    def make(*, client=None, stt=None, populated=True, detections=True, source_mode="simulated"):
        cfg = AssistantConfig.load("configs/assistant.json")
        speech_cfg = SpeechConfig.load("configs/speech.json", require_models=False).replace(echo_guard_seconds=0)
        service = SpeechService()
        service.play_listening_tone = Mock()
        tts, stt = FakeTTS(), stt or FakeSTT()
        service.attach(tts=tts, stt=stt, config=speech_cfg)
        service.speak = Mock(wraps=service.speak)
        service.stop_speaking = Mock(wraps=service.stop_speaking)
        client = client or FakeOmniClient()
        state = SceneState()
        frame = np.full((240, 320, 3), 64, dtype=np.uint8)
        frame[120:] = 192
        boxes = SimpleNamespace(xyxy=np.array([[26., 36., 99., 214.]]), cls=np.array([0]),
                                conf=np.array([0.71]), id=None) if detections else None
        if populated:
            state.update(frame, boxes, {0: "chair"}, source_mode)
        orch = Orchestrator(service, speech_cfg, cfg, state, client, session_id="test-session")
        item = SimpleNamespace(orch=orch, service=service, stt=stt, tts=tts, client=client,
                               state=state, cfg=cfg, speech_cfg=speech_cfg)
        instances.append(item)
        return item

    yield make
    for item in instances:
        if isinstance(item.client, BlockedClient):
            item.client.release.set()
        item.orch.close()
        item.service.shutdown()
        item.state.reset()


def events(caplog, event):
    records = [json.loads(r.getMessage()) for r in caplog.records
               if r.name == "sixth_sense.orchestrator"]
    return [record for record in records if record["event"] == event]


def test_describe_captures_and_speaks_with_latency_log(build, caplog):
    item = build()
    assert item.stt.inject("describe")
    assert wait_for(lambda: item.tts.spoken == [item.client.text])
    assert wait_for(lambda: events(caplog, "question_completed"))
    assert item.stt.capture_calls == [3.0]
    assert item.client.last_call["wav"].startswith(b"RIFF")
    record = events(caplog, "question_completed")[0]
    assert record["status"] == "success" and record["source_mode"] == "simulated"
    assert record["total_ms"] >= record["capture_ms"] >= 0
    assert record["assistant_ms"] >= 0
    assert record["session_id"] == "test-session" and record["seq"] == 0
    assert "prompt" not in record and "wav" not in record and "jpeg" not in record
    assert item.service.speak.call_args.kwargs["priority"] == Priority.LOW


def test_direct_question_skips_capture_and_preserves_prompt(build):
    item = build(source_mode="replay")
    assert item.stt.inject("what's in front of me")
    assert wait_for(lambda: item.tts.spoken == [item.client.text])
    assert item.stt.capture_calls == []
    assert item.cfg.direct_question_prompt in item.client.last_call["prompt"]
    assert "Source: replay" in item.client.last_call["prompt"]
    assert item.client.last_call["wav"] is None


def test_capture_failure_never_calls_client(build, caplog):
    item = build()
    item.stt.capture_fails = True
    item.stt.inject("describe")
    assert wait_for(lambda: item.tts.spoken == ["I could not hear the question"])
    assert wait_for(lambda: events(caplog, "question_completed"))
    assert item.client.calls == 0
    assert events(caplog, "question_completed")[0]["reason"] == "capture_failed"
    assert item.service.speak.call_args.kwargs["ttl_seconds"] == 2


def test_busy_question_during_request_acknowledges_without_capture(build, caplog):
    client = BlockedClient()
    item = build(client=client)
    item.stt.inject("describe")
    assert client.entered.wait(1)
    item.stt.inject("describe")
    assert wait_for(lambda: events(caplog, "question_dropped"))
    assert wait_for(lambda: item.tts.spoken == ["Still answering."])
    assert item.stt.capture_calls == [3.0]
    assert client.calls == 1
    dropped = events(caplog, "question_dropped")[0]
    assert dropped["reason"] == "busy" and dropped["seq"] == 1
    client.release.set()
    assert wait_for(lambda: not item.orch.question_in_flight)
    assert item.tts.wait_idle(1)
    assert item.tts.spoken == ["Still answering.", client.text]


def test_camera_session_reset_discards_answer_silently(build, caplog):
    client = BlockedClient()
    item = build(client=client)
    item.stt.inject("describe")
    assert client.entered.wait(1)
    item.state.reset()
    client.release.set()
    assert wait_for(lambda: events(caplog, "question_completed"))
    assert item.tts.wait_idle(1)
    assert item.tts.spoken == []
    record = events(caplog, "question_completed")[0]
    assert record["status"] == "unavailable" and record["reason"] == "stale_scene"


def test_missing_camera_still_captures_then_reports_unavailable(build):
    item = build(populated=False)
    item.stt.inject("describe")
    assert wait_for(lambda: item.tts.spoken == ["Camera view is unavailable"])
    assert item.stt.capture_calls == [3.0]
    assert item.client.calls == 0


def test_empty_detections_still_send_frame(build):
    item = build(detections=False)
    item.stt.inject("describe")
    assert wait_for(lambda: item.tts.spoken == [item.client.text])
    assert item.client.calls == 1
    assert "Detected (age " in item.client.last_call["prompt"]
    assert "ms): none" in item.client.last_call["prompt"]


def test_disabled_cloud_status_is_normal_priority(build):
    item = build(client=FakeOmniClient(reason="cloud_disabled"))
    item.stt.inject("describe")
    assert wait_for(lambda: item.tts.spoken == ["Scene assistant unavailable"])
    assert item.service.speak.call_args.kwargs["priority"] == Priority.NORMAL


@pytest.mark.parametrize("populated,camera", [(True, "camera simulated"), (False, "camera unavailable")])
def test_status_reports_listening_fault_and_camera(build, populated, camera):
    item = build(populated=populated)
    item.stt.fail("x")
    item.orch.say_status()
    assert wait_for(lambda: item.tts.spoken)
    status = item.tts.spoken[0].lower()
    assert "listening unavailable" in status and camera in status
    assert "cloud fake" in status and "question idle" in status
    assert "haptic" not in status
    assert item.service.speak.call_args.kwargs["ttl_seconds"] == 5


def test_status_reports_low_quality_camera_like_the_assistant(build):
    item = build(populated=False)
    item.state.update(np.zeros((240, 320, 3), dtype=np.uint8), None, {}, "simulated")
    item.orch.say_status()
    assert wait_for(lambda: item.tts.spoken)
    assert "camera simulated low quality" in item.tts.spoken[0].lower()


def test_handler_returns_promptly_while_capture_is_blocked(build):
    release, entered = threading.Event(), threading.Event()

    class SlowCapture(FakeSTT):
        def capture(self, seconds, **kwargs):
            entered.set()
            assert release.wait(2)
            return super().capture(seconds, **kwargs)

    item = build(stt=SlowCapture())
    timings = []
    original = item.orch.start_question

    def timed(*args, **kwargs):
        started = time.monotonic()
        original(*args, **kwargs)
        timings.append(time.monotonic() - started)

    item.orch.start_question = timed
    try:
        item.stt.inject("describe")
        assert entered.wait(1)
        assert wait_for(lambda: timings)
        assert timings[0] < 0.05
        started = time.monotonic()
        item.stt.inject("stop speaking")
        assert wait_for(lambda: item.service.stop_speaking.called, timeout=0.05)
        assert time.monotonic() - started < 0.05
        assert item.orch.question_in_flight and item.client.calls == 0
    finally:
        release.set()


def test_shutdown_suppresses_answer_and_further_questions(build, caplog):
    client = BlockedClient()
    item = build(client=client)
    item.stt.inject("describe")
    assert client.entered.wait(1)
    # Let the worker return during the bounded join, after closing was set.
    timer = threading.Timer(0.05, client.release.set)
    timer.start()
    try:
        item.orch.close()
    finally:
        timer.join()
    item.stt.inject("describe")
    assert item.tts.wait_idle(1)
    assert item.tts.spoken == [] and client.calls == 1


def test_assistant_config_loads_and_resolves_paths():
    cfg = AssistantConfig.load("configs/assistant.json")
    assert cfg.omni_timeout_s == 6 and cfg.answer_within_ms == 6000
    assert not cfg.cloud_enabled
    assert cfg.audit_log == str(Path("omni/artifacts/yibu_api_calls.jsonl").resolve())
    assert cfg.client_config(cloud_enabled=True).cloud_enabled
    assert cfg.client_config().audit_log == cfg.audit_log
    with pytest.raises(AttributeError):
        cfg.cloud_enabled = True


@pytest.mark.parametrize("overrides,match", [
    ({"answer_within_ms": 499}, "answer_within_ms"),
    ({"bogus": 1}, "unknown key"),
    ({"frame_jpeg_width": 0}, "frame_jpeg_width"),
    ({"frame_jpeg_width": -1}, "frame_jpeg_width"),
    ({"frame_jpeg_width": True}, "frame_jpeg_width"),
    ({"max_scene_age_ms": 0}, "max_scene_age_ms"),
    ({"omni_timeout_s": 7}, "omni_timeout_s"),
    ({"omni_timeout_s": float("nan")}, "omni_timeout_s"),
    ({"omni_timeout_s": float("inf")}, "omni_timeout_s"),
    ({"cloud_enabled": "false"}, "cloud_enabled"),
    ({"schema_version": 2}, "schema_version"),
    ({"omni_base_url": "https://user:secret@example.com"}, "base_url"),
])
def test_assistant_config_rejects_invalid_settings(tmp_path, overrides, match):
    path = tmp_path / "assistant.json"
    path.write_text(json.dumps(overrides))
    with pytest.raises(ValueError, match=match):
        AssistantConfig.load(path)


@pytest.mark.parametrize("command", ["describe", "what's in front of me"])
def test_missing_grammar_command_fails_construction(command):
    cfg = AssistantConfig()
    grammar = tuple(c for c in ("describe", "what's in front of me", "stop speaking") if c != command)
    with pytest.raises(ValueError, match=command):
        Orchestrator(SpeechService(), SpeechConfig(grammar=grammar), cfg, SceneState(), FakeOmniClient())


@pytest.mark.parametrize("fake,cloud,cloud_state,interrupt", [
    (False, False, "off", False),
    (False, True, "on", True),
    (True, True, "fake", False),
])
def test_cli_startup_replay_stt_fault_and_cleanup(monkeypatch, caplog, fake, cloud, cloud_state, interrupt, tmp_path):
    import main as app

    caplog.set_level("INFO", logger="sixth_sense.orchestrator")
    speech_cfg = SpeechConfig.load("configs/speech.json", require_models=False)
    service, tts, stt = SpeechService(), FakeTTS(), FakeSTT()
    observed = {}

    def configure(cfg):
        service.attach(tts=tts, stt=stt, config=cfg)
        stt.fail("test_mic_fault")
        return dict(service.health)

    def preview(state, *, preview_status):
        assert preview_status() == cloud_state
        observed["state"] = state
        assert threading.current_thread() is threading.main_thread()
        assert service.health["stt"] == "fault"
        assert stub.SOURCE == str(replay)
        state.update(np.zeros((12, 30, 3), dtype=np.uint8), None, {}, "replay")
        if interrupt:
            raise KeyboardInterrupt

    stub = SimpleNamespace(SOURCE=0, main=preview)
    monkeypatch.setitem(sys.modules, "track_distances", stub)
    monkeypatch.setattr(app, "speech", service)
    monkeypatch.setattr(service, "configure", configure)
    monkeypatch.setattr(app.SpeechConfig, "load", lambda path: speech_cfg)
    monkeypatch.setattr(app.OmniClient, "complete", Mock(side_effect=AssertionError("no network in startup test")))
    monkeypatch.delenv("YIBU_API_KEY", raising=False)
    monkeypatch.setenv("OMNI_FAKE", "1" if fake else "0")
    # A stored cloud setting cannot bypass explicit CLI consent.
    monkeypatch.setattr(app.AssistantConfig, "load", lambda path: AssistantConfig(cloud_enabled=True))
    service.speak = Mock(wraps=service.speak)
    replay = tmp_path / "test-video.mp4"
    replay.touch()
    assert app.main(["--source", str(replay)] + (["--cloud"] if cloud else [])) == 0
    service.speak.assert_called_once_with(f"system ready. cloud {cloud_state}.", Priority.NORMAL)
    assert not stt.started and service.health == {"tts": "unavailable", "stt": "unavailable"}
    assert observed["state"].read() is None
    startup = events(caplog, "startup")
    assert [r["step"] for r in startup if r["result"] != "warning"] == [
        "speech_config", "assistant_config", "grammar", "client", "speech", "scene_state",
        "handlers", "ready", "preview",
    ]
    assert startup[-1]["cloud_state"] == cloud_state and startup[-1]["source_mode"] == "replay"
    warnings = [r for r in startup if r["result"] == "warning"]
    assert bool(warnings) == (cloud and not fake)
    if warnings:
        assert warnings[0]["reason"] == "not_configured"


def test_all_grammar_phrases_have_handlers(build):
    item = build()
    assert set(item.speech_cfg.grammar) <= item.service.handled_commands


def test_unknown_grammar_fails_before_opening_devices(monkeypatch):
    import main as app
    cfg = SpeechConfig.load('configs/speech.json', require_models=False)
    monkeypatch.setattr(app.SpeechConfig, 'load', lambda _: cfg.replace(grammar=cfg.grammar + ('new phrase',)))
    configure = Mock()
    monkeypatch.setattr(app.speech, 'configure', configure)
    monkeypatch.setattr(app.speech, 'shutdown', Mock())
    with pytest.raises(ValueError, match='without handlers'):
        app.main([])
    configure.assert_not_called()


@pytest.mark.parametrize('phrase', ['pause feedback', 'resume feedback', 'increase sensitivity', 'decrease sensitivity'])
def test_controller_commands_acknowledge_unsupported(build, caplog, phrase):
    item = build()
    item.stt.inject(phrase)
    assert wait_for(lambda: item.tts.spoken)
    assert item.tts.spoken == ['Haptic controls are not available yet.']
    assert item.service.speak.call_args.kwargs['ttl_seconds'] == 2
    assert item.service.speak.call_args.kwargs['priority'] == Priority.NORMAL
    assert events(caplog, 'command_unsupported')[0]['command'] == phrase
    assert item.client.calls == 0


def test_audio_controls_effective_bounds_mute_and_duplicate(build):
    from speech import Command
    item = build()
    assert item.service.volume_level == 5  # default is full scale
    for seq, phrase, level in [(0, 'volume up', 5), (1, 'volume down', 4),
                              (2, 'volume down', 3), (3, 'volume up', 4),
                              (4, 'mute', 4), (5, 'sound on', 4)]:
        cmd = Command(phrase, seq, time.monotonic(), time.monotonic(), 'simulated')
        item.orch.set_audio(cmd)
        assert item.tts.wait_idle(1)
        assert wait_for(lambda: not item.stt.muted)
        assert item.service.volume_level == level
        assert item.service.muted == (phrase == 'mute')
        item.orch.set_audio(cmd)  # same absolute mutation must not be applied twice
        assert item.service.volume_level == level
    assert any('Volume 4 of 5' in text for text in item.tts.spoken)
    assert 'Sound muted. High priority alerts remain on.' in item.tts.spoken
    assert 'Sound on. Volume 4 of 5.' in item.tts.spoken
    item.service.set_volume(1)
    item.orch.set_audio(Command('volume down', 6, time.monotonic(), time.monotonic(), 'simulated'))
    assert item.service.volume_level == 1


def test_busy_during_capture_remains_silent(build, caplog):
    release, entered = threading.Event(), threading.Event()

    class SlowCapture(FakeSTT):
        def capture(self, seconds, **kwargs):
            entered.set()
            assert release.wait(3)
            return super().capture(seconds, **kwargs)

    item = build(stt=SlowCapture())
    try:
        item.stt.inject('describe')
        assert entered.wait(1)
        item.stt.inject('describe')
        assert wait_for(lambda: events(caplog, 'question_dropped'))
        assert item.tts.spoken == []
        assert not item.stt.muted
        assert item.orch._capturing.is_set()
    finally:
        release.set()


def test_status_after_reset_reports_camera_unavailable(build):
    item = build()
    item.state.reset()
    item.orch.say_status()
    assert wait_for(lambda: item.tts.spoken)
    assert 'camera unavailable' in item.tts.spoken[0]


def test_worker_outliving_join_cannot_touch_state_or_enqueue(build, monkeypatch, caplog):
    client = BlockedClient()
    item = build(client=client)
    item.stt.inject('describe')
    assert client.entered.wait(1)
    # Force the join-timeout path deterministically, then shut down/reset in
    # exactly main() order while the request still owns an old snapshot.
    worker = item.orch._worker
    real_join = worker.join
    monkeypatch.setattr(worker, 'join', Mock())
    item.orch.close()
    worker.join.assert_called_once_with(timeout=2)
    item.service.shutdown()
    item.state.reset()
    monkeypatch.setattr(item.state, 'read', Mock(side_effect=AssertionError('read after close')))
    from unittest.mock import PropertyMock
    monkeypatch.setattr(SceneState, 'session_generation', PropertyMock(side_effect=AssertionError('generation after close')))
    client.release.set()
    real_join(1)
    assert not worker.is_alive()
    assert item.tts.spoken == []
    assert events(caplog, 'question_completed')[-1]['reason'] == 'closing'
    assert not events(caplog, 'question_failed')


def test_speech_start_logged_separately_from_enqueue(build, caplog):
    item = build()
    item.stt.inject("what's in front of me")
    assert wait_for(lambda: events(caplog, 'speech_started'))
    started = events(caplog, 'speech_started')[0]
    assert started['seq'] == 0 and started['session_id'] == 'test-session'
    assert started['speech_started_ms'] >= 0
    assert 'text' not in started
