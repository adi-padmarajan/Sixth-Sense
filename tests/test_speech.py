"""Device-free checks for the speech package (fakes only: no models, no audio)."""

import json
import threading
import time

import pytest

from speech import Command, Priority, SpeechConfig, SpeechService
from speech.fakes import FakeSTT, FakeTTS


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.002)
    return True


@pytest.fixture
def service():
    svc = SpeechService()
    yield svc
    svc.shutdown()


# -- TTS queue --------------------------------------------------------------

def test_priority_order_and_fifo_within_priority():
    tts = FakeTTS()
    tts.speak("low", Priority.LOW)
    tts.speak("normal-1", Priority.NORMAL)
    tts.speak("normal-2", Priority.NORMAL)
    tts.speak("high", Priority.HIGH)
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["high", "normal-1", "normal-2", "low"]
    tts.shutdown()


def test_interrupt_cuts_current_and_drops_lower_priority():
    tts = FakeTTS(play_seconds=0.3)
    tts.start()
    tts.speak("ambient", Priority.LOW)
    assert wait_for(lambda: "ambient" in tts.spoken)
    tts.speak("queued-low", Priority.LOW)
    tts.speak("queued-normal", Priority.NORMAL)
    tts.speak("alert", Priority.HIGH, interrupt=True)
    assert tts.wait_idle(1.0)
    assert "ambient" not in tts.completed          # cut off mid-play
    assert tts.spoken == ["ambient", "alert"]      # lower-priority backlog dropped
    assert tts.completed == ["alert"]
    tts.shutdown()


def test_interrupt_keeps_queued_items_of_equal_or_higher_priority():
    tts = FakeTTS(play_seconds=0.05)
    tts.speak("first-high", Priority.HIGH)
    tts.speak("normal", Priority.NORMAL)
    tts.speak("alert", Priority.NORMAL, interrupt=True)
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["first-high", "normal", "alert"]
    tts.shutdown()


def test_cancel_all_stops_playback_and_empties_queue():
    tts = FakeTTS(play_seconds=0.3, dedup_window_seconds=0)
    tts.start()
    tts.speak("a")
    tts.speak("b")
    assert wait_for(lambda: "a" in tts.spoken)
    tts.cancel_all()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["a"]
    assert tts.completed == []
    tts.shutdown()


def test_expired_items_are_not_spoken():
    tts = FakeTTS()
    tts.speak("stale scene", Priority.LOW, ttl_seconds=0.01)
    tts.speak("fresh")
    time.sleep(0.03)
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["fresh"]
    tts.shutdown()


def test_bounded_queue_evicts_lowest_priority():
    tts = FakeTTS(max_queue=2)
    tts.speak("low", Priority.LOW)
    tts.speak("normal", Priority.NORMAL)
    tts.speak("high", Priority.HIGH)   # queue full: evicts "low"
    tts.speak("low-2", Priority.LOW)   # lower than everything: evicted itself
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["high", "normal"]
    tts.shutdown()


def test_playback_failure_reports_fault_and_keeps_worker_alive():
    faults = []
    tts = FakeTTS(fail_on="boom", on_fault=faults.append)
    tts.start()
    tts.speak("boom")
    tts.speak("after")
    assert tts.wait_idle(2.0)
    assert tts.spoken == ["after"]
    assert faults and faults[0].startswith("playback_failed")
    assert tts.fault_reason == faults[0]
    tts.shutdown()


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_repeated_text_is_suppressed_within_window():
    clock = FakeClock()
    tts = FakeTTS(dedup_window_seconds=2.0, clock=clock)
    assert tts.speak("obstacle ahead") is True
    assert tts.speak("obstacle ahead") is False          # repeat, suppressed
    clock.t += 1.9
    assert tts.speak("obstacle ahead") is False          # still inside window
    clock.t += 0.2
    assert tts.speak("obstacle ahead") is True           # window elapsed
    assert tts.speak("different text") is True
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["obstacle ahead", "obstacle ahead", "different text"]
    tts.shutdown()


def test_high_priority_and_interrupt_bypass_dedup():
    clock = FakeClock()
    tts = FakeTTS(dedup_window_seconds=2.0, clock=clock)
    assert tts.speak("alert", Priority.HIGH) is True
    assert tts.speak("alert", Priority.HIGH) is True
    assert tts.speak("now", Priority.NORMAL, interrupt=True) is True
    assert tts.speak("now", Priority.NORMAL, interrupt=True) is True
    assert tts.speak("now") is False                     # plain repeat still suppressed
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["alert", "alert", "now", "now"]
    tts.shutdown()


def test_dedup_can_be_disabled():
    tts = FakeTTS(dedup_window_seconds=0)
    assert tts.speak("x") and tts.speak("x")
    tts.start()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["x", "x"]
    tts.shutdown()


# -- Service: dispatch --------------------------------------------------------

def test_handler_runs_off_the_recognition_thread(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    seen = {}
    done = threading.Event()

    def handler(cmd):
        seen["thread"] = threading.current_thread().name
        seen["cmd"] = cmd
        done.set()

    service.on("mute", handler)
    t0 = time.monotonic()
    assert stt.inject("mute")
    assert done.wait(1.0)
    assert seen["thread"] == "speech-dispatch"
    assert seen["thread"] != threading.current_thread().name
    cmd = seen["cmd"]
    assert isinstance(cmd, Command)
    assert cmd.text == "mute" and cmd.seq == 0 and cmd.source_mode == "simulated"
    assert t0 <= cmd.recognized_at <= cmd.dispatched_at
    assert 0 <= cmd.age_seconds < 1.0
    with pytest.raises(Exception):
        cmd.text = "changed"  # frozen


def test_command_matching_is_case_insensitive_and_supports_multiple_handlers(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    calls = []
    service.on("Volume Up", lambda cmd: calls.append("a"))
    service.on("volume up", lambda cmd: calls.append("b"))
    stt.inject("VOLUME UP")
    assert wait_for(lambda: len(calls) == 2)
    assert sorted(calls) == ["a", "b"]


def test_stale_command_is_dropped(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt, config=SpeechConfig(max_command_age_seconds=0.5))
    calls = []
    service.on("stop", lambda cmd: calls.append(1))
    stt.inject("stop", recognized_at=time.monotonic() - 5.0)
    stt.inject("stop")  # fresh one still goes through
    assert wait_for(lambda: len(calls) == 1)
    time.sleep(0.05)
    assert calls == [1]


def test_unmatched_utterance_and_raising_handler_do_not_break_dispatch(service, caplog):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    calls = []
    caplog.set_level("INFO", logger="speech.service")

    def bad(cmd):
        raise ValueError("handler bug")

    service.on("describe", bad)
    service.on("mute", lambda cmd: calls.append(1))
    stt.inject("[unk]")
    stt.inject("volume up [unk]")
    stt.inject("describe")
    stt.inject("mute")
    assert wait_for(lambda: calls == [1])
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("speech: not_understood") for m in messages)
    assert any("unmatched utterance 'volume up [unk]'" in m for m in messages)
    assert not any("unmatched utterance '[unk]'" in m for m in messages)


def test_slow_handler_does_not_block_recognition(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    release = threading.Event()
    service.on("describe", lambda cmd: release.wait())
    stt.inject("describe")
    t0 = time.monotonic()
    assert stt.inject("mute")   # returns immediately; STT thread is not blocked
    assert time.monotonic() - t0 < 0.1
    release.set()


# -- Service: echo guard and health ------------------------------------------

def test_mic_is_muted_during_speech_and_for_echo_guard_after(service):
    stt = FakeSTT()
    tts = FakeTTS(play_seconds=0.1)
    service.attach(tts=tts, stt=stt, config=SpeechConfig(echo_guard_seconds=0.1))
    service.speak("hello")
    assert wait_for(lambda: stt.muted)
    assert not stt.inject("mute")            # dropped at source while speaking
    assert tts.wait_idle(1.0)
    assert stt.muted                          # still muted in the echo tail
    assert wait_for(lambda: not stt.muted, timeout=0.5)
    assert stt.resets == 1                    # recognizer reset requested on unmute
    assert stt.inject("mute")


def test_back_to_back_speech_keeps_mic_muted_between_items(service):
    stt = FakeSTT()
    tts = FakeTTS(play_seconds=0.05)
    service.attach(tts=tts, stt=stt, config=SpeechConfig(echo_guard_seconds=0.2))
    service.speak("one")
    service.speak("two")
    assert tts.wait_idle(1.0)
    assert stt.resets == 0                    # guard timer was cancelled by item two
    assert wait_for(lambda: not stt.muted, timeout=0.5)
    assert stt.resets == 1


def test_stop_speaking_cancels_queue(service):
    tts = FakeTTS(play_seconds=0.3)
    service.attach(tts=tts, stt=FakeSTT())
    service.speak("a")
    service.speak("b")
    assert wait_for(lambda: "a" in tts.spoken)
    service.stop_speaking()
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["a"] and tts.completed == []


def test_health_reflects_attached_backends_and_faults(service):
    assert service.health == {"tts": "unavailable", "stt": "unavailable"}
    assert service.speak("nothing to play") is False

    stt = FakeSTT()
    tts = FakeTTS(fail_on="boom")
    assert service.attach(tts=tts, stt=stt) == {"tts": "ready", "stt": "ready"}

    stt.fail("mic_lost")
    assert service.health["stt"] == "fault"
    assert service.health_reason["stt"] == "mic_lost"

    service.speak("boom")
    assert wait_for(lambda: service.health["tts"] == "fault", timeout=2.0)
    assert service.health_reason["tts"].startswith("playback_failed")


def test_tts_only_service_degrades_gracefully(service):
    tts = FakeTTS()
    health = service.attach(tts=tts, stt=None)
    assert health == {"tts": "ready", "stt": "unavailable"}
    assert service.speak("still talking") is True
    assert tts.wait_idle(1.0)
    assert tts.spoken == ["still talking"]


def test_stt_start_failure_keeps_tts_running(service):
    class BrokenSTT(FakeSTT):
        def start(self):
            raise OSError("no input device")

    tts = FakeTTS()
    health = service.attach(tts=tts, stt=BrokenSTT())
    assert health["tts"] == "ready"
    assert health["stt"] == "fault"
    assert service.health_reason["stt"].startswith("start_failed")
    assert service.speak("ok") is True


def test_unsupported_grammar_phrases_surface_as_partial_health(service):
    stt = FakeSTT(unsupported_phrases=["unmute"])
    health = service.attach(tts=FakeTTS(), stt=stt)
    assert health["stt"] == "partial"
    assert "unmute" in service.health_reason["stt"]


def test_source_mode_is_carried_from_backend_to_handler(service):
    stt = FakeSTT(source_mode="replay")
    service.attach(tts=FakeTTS(), stt=stt)
    seen = []
    service.on("describe", lambda cmd: seen.append(cmd.source_mode))
    stt.inject("describe")
    assert wait_for(lambda: seen == ["replay"])
    with pytest.raises(ValueError):
        FakeSTT(source_mode="live")  # fakes may not claim to be live


def test_invalid_source_mode_is_rejected(service):
    service.attach(tts=FakeTTS(), stt=FakeSTT())
    calls = []
    service.on("mute", lambda cmd: calls.append(cmd))
    service._on_recognized("mute", time.monotonic(), "bogus")
    service._on_recognized("mute", time.monotonic(), "simulated")
    assert wait_for(lambda: len(calls) == 1)
    time.sleep(0.05)
    assert len(calls) == 1


# -- Service: wake phrase -----------------------------------------------------

def test_wake_phrase_gates_commands_within_window(service):
    stt = FakeSTT(source_mode="replay")
    service.attach(tts=FakeTTS(), stt=stt, config=SpeechConfig(wake_phrase="Hey Headband", wake_window_seconds=5.0))
    calls = []
    service.on("describe", lambda cmd: calls.append(("describe", cmd.recognized_at)))
    service.on("hey headband", lambda cmd: calls.append(("wake", cmd.recognized_at)))
    t = time.monotonic()
    assert not service.is_armed(t)
    stt.inject("describe", recognized_at=t)              # rejected: not armed
    stt.inject("hey headband", recognized_at=t + 0.1)    # arms until t+5.1
    stt.inject("describe", recognized_at=t + 2.0)        # ok
    stt.inject("describe", recognized_at=t + 4.0)        # ok: window, not one-shot
    stt.inject("describe", recognized_at=t + 5.2)        # rejected: expired
    assert wait_for(lambda: len(calls) == 3)
    time.sleep(0.05)
    assert [c[0] for c in calls] == ["wake", "describe", "describe"]
    assert service.is_armed(t + 5.0) and not service.is_armed(t + 5.2)


def test_always_on_commands_bypass_wake_phrase(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt, config=SpeechConfig(wake_phrase="hey headband", always_on_commands=["stop speaking"]))
    calls = []
    service.on("stop speaking", lambda cmd: calls.append("stop"))
    service.on("mute", lambda cmd: calls.append("mute"))
    stt.inject("mute")
    stt.inject("stop speaking")
    assert wait_for(lambda: calls == ["stop"])
    time.sleep(0.05)
    assert calls == ["stop"]


def test_no_wake_phrase_means_always_armed(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    assert service.is_armed()
    calls = []
    service.on("mute", lambda cmd: calls.append(1))
    stt.inject("mute")
    assert wait_for(lambda: calls == [1])


# -- Config -------------------------------------------------------------------

def test_config_loads_repo_file_and_resolves_relative_paths():
    cfg = SpeechConfig.load("configs/speech.json", require_models=False)
    assert cfg.schema_version == 1
    assert cfg.grammar and "stop speaking" in cfg.grammar
    assert cfg.tts_model_path.endswith("speech/models/en_US-lessac-medium.onnx")
    assert cfg.always_on_commands == ("stop speaking",)
    assert set(cfg.always_on_commands) <= set(cfg.grammar)


def test_config_rejects_bad_values(tmp_path):
    def write(**overrides):
        data = {"schema_version": 1, "grammar": ["mute", "stop speaking"]}
        data.update(overrides)
        path = tmp_path / "speech.json"
        path.write_text(json.dumps(data))
        return str(path)

    with pytest.raises(ValueError, match="schema_version"):
        SpeechConfig.load(write(schema_version=2), require_models=False)
    with pytest.raises(ValueError, match="unknown key"):
        SpeechConfig.load(write(bogus=1), require_models=False)
    with pytest.raises(ValueError, match="blocksize"):
        SpeechConfig.load(write(blocksize=-1), require_models=False)
    with pytest.raises(ValueError, match="echo_guard_seconds"):
        SpeechConfig.load(write(echo_guard_seconds="fast"), require_models=False)
    with pytest.raises(ValueError, match="wake_phrase"):
        SpeechConfig.load(write(wake_phrase="hey headband"), require_models=False)
    with pytest.raises(ValueError, match="always_on_commands"):
        SpeechConfig.load(write(always_on_commands=["halt"]), require_models=False)
    with pytest.raises(ValueError, match="duplicate"):
        SpeechConfig.load(write(grammar=["mute", "Mute", "stop speaking"]), require_models=False)
    with pytest.raises(ValueError, match="does not exist"):
        SpeechConfig.load(write(tts_model_path="nope.onnx", stt_model_path="nope"), require_models=True)
    with pytest.raises(ValueError, match="required for a real backend"):
        SpeechConfig.load(write(), require_models=True)


def test_config_normalises_phrases_and_is_frozen():
    cfg = SpeechConfig(grammar=["Mute ", "Stop Speaking"], wake_phrase=" MUTE ")
    assert cfg.grammar == ("mute", "stop speaking")
    assert cfg.wake_phrase == "mute"
    with pytest.raises(Exception):
        cfg.blocksize = 1
    assert cfg.replace(blocksize=8000).blocksize == 8000


def test_configure_requires_model_paths(service):
    with pytest.raises(ValueError, match="required for a real backend"):
        service.configure(SpeechConfig())
    assert service.health == {"tts": "unavailable", "stt": "unavailable"}
