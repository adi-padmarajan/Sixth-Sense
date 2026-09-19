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
    from unittest.mock import Mock
    svc = SpeechService()
    svc.play_listening_tone = Mock()
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


# -- question capture ---------------------------------------------------------

import io
import queue
import wave


def _wav_info(data: bytes):
    w = wave.open(io.BytesIO(data))
    return w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()


def test_capture_question_returns_wav_of_requested_length(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    data = service.capture_question(1.0)
    assert isinstance(data, bytes)
    assert _wav_info(data) == (1, 16000, 2, 16000)
    assert stt.capture_calls == [1.0]


def test_capture_question_refuses_while_muted(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    service._on_speak_start()          # speaker playing -> mic muted at source
    assert service.capture_question(1.0) is None
    assert stt.capture_calls == []
    assert not service.is_capturing


def test_capture_question_reports_failed_capture_as_none(service):
    stt = FakeSTT()
    stt.capture_fails = True
    service.attach(tts=FakeTTS(), stt=stt)
    assert service.capture_question(1.0) is None
    assert stt.capture_calls == []


@pytest.mark.parametrize("seconds", [0, -1.0, 10.01])
def test_capture_question_rejects_out_of_bounds_seconds(service, seconds):
    service.attach(tts=FakeTTS(), stt=FakeSTT())
    with pytest.raises(ValueError):
        service.capture_question(seconds)


def test_capture_question_without_stt_returns_none(service):
    service.attach(tts=FakeTTS())
    assert service.capture_question(1.0) is None
    assert not service.is_capturing


def test_config_validates_question_capture_window(tmp_path):
    cfg = SpeechConfig.load("configs/speech.json", require_models=False)
    assert cfg.question_seconds == 2.0 and cfg.max_capture_seconds == 10.0
    with pytest.raises(ValueError, match="question_seconds"):
        SpeechConfig(question_seconds=12.0, max_capture_seconds=10.0)
    with pytest.raises(ValueError, match="question_seconds"):
        SpeechConfig(question_seconds=0)
    with pytest.raises(ValueError, match="question_seconds"):
        SpeechConfig(question_seconds=-1.0)


# -- VoskSTT capture logic, no vosk / PortAudio -----------------------------
#
# The constructor loads a model and imports sounddevice, so build the object
# with __new__ and set only the state that _audio_callback / capture / set_muted
# touch. If VoskSTT grows more state these tests are the first to notice.

def _bare_vosk_stt(samplerate=16000, blocksize=4000):
    from speech.stt import VoskSTT
    stt = VoskSTT.__new__(VoskSTT)
    stt.samplerate = samplerate
    stt.blocksize = blocksize
    stt.max_capture_seconds = 10.0
    stt._audio_q = queue.Queue(maxsize=20)
    stt._dropped_blocks = 0
    stt._overflows = 0
    stt._running = threading.Event()
    stt._running.set()
    stt._muted = threading.Event()
    stt._reset_pending = threading.Event()
    stt._init_capture_state()
    return stt


class _FakeMic(threading.Thread):
    """Drives _audio_callback with int16 blocks like PortAudio would."""

    def __init__(self, stt, blocks: int, blocksize=4000, interval=0.002, fill=b"\x01\x00"):
        super().__init__(daemon=True)
        self.stt, self.blocks, self.interval = stt, blocks, interval
        self.block = fill * blocksize
        self.delivered = 0

    def run(self):
        for _ in range(self.blocks):
            self.stt._audio_callback(self.block, len(self.block) // 2, None, None)
            self.delivered += 1
            time.sleep(self.interval)


def test_vosk_capture_diverts_exact_sample_count_from_recognizer():
    stt = _bare_vosk_stt()
    mic = _FakeMic(stt, blocks=12)
    result = {}
    t = threading.Thread(target=lambda: result.update(wav=stt.capture(3.0, timeout=2.0)))
    t.start()
    assert wait_for(lambda: stt.is_capturing)
    mic.start(); mic.join(); t.join(2.0)
    assert _wav_info(result["wav"]) == (1, 16000, 2, 48000)
    assert stt._audio_q.qsize() == 0                 # nothing leaked to Vosk
    assert not stt.is_capturing and stt._reset_pending.is_set()
    # Post-capture audio goes back to the recognizer queue.
    stt._audio_callback(mic.block, 4000, None, None)
    assert stt._audio_q.qsize() == 1


def test_vosk_capture_truncates_partial_last_block():
    stt = _bare_vosk_stt()
    mic = _FakeMic(stt, blocks=3)                    # 0.75 s available
    result = {}
    t = threading.Thread(target=lambda: result.update(wav=stt.capture(0.3, timeout=2.0)))
    t.start()
    assert wait_for(lambda: stt.is_capturing)
    mic.start(); mic.join(); t.join(2.0)
    assert _wav_info(result["wav"])[3] == 4800           # not 8000


def test_vosk_capture_is_abandoned_when_muted_mid_capture():
    stt = _bare_vosk_stt()
    result = {}
    t = threading.Thread(target=lambda: result.update(wav=stt.capture(3.0, timeout=2.0)))
    t.start()
    assert wait_for(lambda: stt.is_capturing)
    stt._audio_callback(b"\x01\x00" * 4000, 4000, None, None)
    stt.set_muted(True)                              # HIGH alert started speaking
    t.join(1.0)
    assert not t.is_alive()
    assert result["wav"] is None
    assert not stt.is_capturing and stt._reset_pending.is_set()
    assert stt._audio_q.qsize() == 0


def test_vosk_capture_refuses_to_start_while_muted():
    stt = _bare_vosk_stt()
    stt.set_muted(True)
    assert stt.capture(1.0, timeout=0.2) is None
    assert not stt.is_capturing


def test_vosk_capture_times_out_when_stream_stalls():
    stt = _bare_vosk_stt()
    t0 = time.monotonic()
    assert stt.capture(3.0, timeout=0.2) is None
    assert time.monotonic() - t0 < 1.0
    assert not stt.is_capturing and stt._reset_pending.is_set()


def test_vosk_capture_rejects_concurrent_capture_but_first_completes():
    stt = _bare_vosk_stt()
    result = {}
    t = threading.Thread(target=lambda: result.update(wav=stt.capture(0.5, timeout=2.0)))
    t.start()
    assert wait_for(lambda: stt.is_capturing)
    assert stt.capture(0.5, timeout=0.2) is None    # immediate, no wait
    mic = _FakeMic(stt, blocks=2); mic.start(); mic.join(); t.join(2.0)
    assert _wav_info(result["wav"])[3] == 8000


def test_vosk_capture_bounds_and_not_running():
    stt = _bare_vosk_stt()
    for bad in (0, -1, 10.5):
        with pytest.raises(ValueError):
            stt.capture(bad)
    stt._running.clear()
    assert stt.capture(1.0) is None


@pytest.mark.parametrize('value', [0, 6, True, 1.5])
def test_volume_rejects_invalid_absolute_levels(service, value):
    service.attach(tts=FakeTTS(), stt=FakeSTT())
    with pytest.raises(ValueError):
        service.set_volume(value)


def test_mute_preserves_microphone_and_high_alerts(service):
    tts, stt = FakeTTS(), FakeSTT()
    service.attach(tts=tts, stt=stt, config=SpeechConfig(echo_guard_seconds=0))
    service.set_muted(True)
    assert not stt.muted and stt.started
    assert not service.speak('narration', Priority.LOW)
    assert service.speak('alert', Priority.HIGH)
    assert tts.wait_idle(1)
    assert tts.spoken == ['alert']
    assert wait_for(lambda: not stt.muted)
    service.set_muted(False)
    assert service.speak('sound restored')
    assert tts.wait_idle(1)
    assert tts.spoken[-1] == 'sound restored'


def test_listening_tone_precedes_capture_without_echo_mute(service):
    from unittest.mock import Mock
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    order = []
    service.play_listening_tone = lambda: order.append(('tone', stt.muted, stt.is_capturing))
    capture = stt.capture
    stt.capture = lambda seconds: (order.append(('capture', stt.muted, stt.is_capturing)) or capture(seconds))
    service._on_speak_start = Mock()
    assert service.capture_question(.1).startswith(b'RIFF')
    assert order == [('tone', False, False), ('capture', False, False)]
    service._on_speak_start.assert_not_called()


def test_tone_disabled_and_muted_capture_emit_nothing(service):
    stt = FakeSTT()
    service.attach(stt=stt, config=SpeechConfig(listening_tone=False))
    assert service.capture_question(.1)
    service.play_listening_tone.assert_not_called()
    service.config = SpeechConfig(listening_tone=True)
    stt.set_muted(True)
    assert service.capture_question(.1) is None
    service.play_listening_tone.assert_not_called()


def test_high_alert_during_tone_prevents_capture(service):
    stt = FakeSTT()
    service.attach(stt=stt)
    service.play_listening_tone = lambda: stt.set_muted(True)
    assert service.capture_question(.1) is None
    assert not stt.capture_calls


def test_real_tone_uses_direct_output_stream(monkeypatch):
    from unittest.mock import Mock
    import sounddevice
    from unittest.mock import MagicMock
    output = MagicMock()
    monkeypatch.setattr(sounddevice, 'OutputStream', output)
    service = SpeechService()
    service.play_listening_tone()
    samples = output.return_value.__enter__.return_value.write.call_args.args[0]
    assert len(samples) == 960 and samples.dtype.name == 'float32'
    assert abs(samples).max() <= .08
    assert service._unmute_timer is None


@pytest.mark.parametrize('changes', [{'listening_tone': 'true'}, {'echo_guard_seconds': float('nan')},
                                     {'dedup_window_seconds': float('nan')}, {'wake_window_seconds': float('inf')}])
def test_config_rejects_nonfinite_timing_and_nonbool_tone(changes):
    with pytest.raises(ValueError):
        SpeechConfig(**changes)


def test_speech_callback_after_synthesis_and_pcm_volume(monkeypatch):
    from unittest.mock import Mock
    from types import SimpleNamespace
    import numpy as np
    from speech.tts import PiperTTS, QueuedTTS
    # Exercise real Piper playback code with synthetic PCM and a fake stream.
    tts = PiperTTS.__new__(PiperTTS)
    QueuedTTS.__init__(tts)
    stream = Mock()
    tts._stream = stream
    tts.write_block_samples = 2
    order = []
    def synthesize(text):
        order.append('synthesis')
        yield SimpleNamespace(audio_int16_array=np.array([1000, -1000, 500, -500], dtype=np.int16))
    tts.voice = SimpleNamespace(synthesize=synthesize)
    stream.write.side_effect = lambda _: order.append('write')
    tts.set_volume(2)
    tts.speak('example', on_started=lambda _: order.append('started'))
    tts.start()
    try:
        assert tts.wait_idle(1)
        assert order == ['synthesis', 'started', 'write', 'write']
        np.testing.assert_array_equal(stream.write.call_args_list[0].args[0], [400, -400])
    finally:
        tts.shutdown()


def test_cancel_after_dequeue_cannot_restart_item():
    tts = FakeTTS()
    original_get = tts._queue.get
    popped, release = threading.Event(), threading.Event()
    def paused_get(*args, **kwargs):
        item = original_get(*args, **kwargs)
        popped.set()
        assert release.wait(2)
        return item
    tts._queue.get = paused_get
    tts.speak('must remain cancelled')
    tts.start()
    try:
        assert popped.wait(1)
        tts.cancel_all()
        release.set()
        tts.shutdown()
        assert tts.spoken == []
    finally:
        release.set()
        tts.shutdown()


def test_expired_during_synthesis_never_starts_playback():
    from unittest.mock import Mock
    clock = FakeClock()
    callback = Mock()
    class SlowSynthesis(FakeTTS):
        def _synthesize_and_play(self, text, should_stop):
            clock.now += 2
            super()._synthesize_and_play(text, should_stop)
    tts = SlowSynthesis(clock=clock)
    tts.speak('expired', ttl_seconds=1, on_started=callback)
    tts.start()
    try:
        assert tts.wait_idle(1)
        assert tts.spoken == []
        callback.assert_not_called()
    finally:
        tts.shutdown()


def test_capture_buffer_bounds_oversized_block():
    from speech.stt import _CaptureBuffer
    buf = _CaptureBuffer(32, 3)
    buf.append(bytes(500))
    buf.append(bytes(500))
    assert buf.size == 32 and len(buf.blocks) == 1
    assert len(buf.pcm()) == 32


def test_stopping_stt_abandons_capture_and_requests_reset():
    from unittest.mock import Mock
    stt = _bare_vosk_stt()
    stt._stream, stt._worker = Mock(), None
    stream = stt._stream
    result = {}
    worker = threading.Thread(target=lambda: result.update(wav=stt.capture(3, timeout=2)))
    worker.start()
    assert wait_for(lambda: stt.is_capturing)
    stt.stop()
    worker.join(1)
    assert not worker.is_alive() and result['wav'] is None
    assert stt._reset_pending.is_set()
    stream.close.assert_called_once()


def test_failed_stt_start_closes_allocated_stream():
    from unittest.mock import Mock
    stt = _bare_vosk_stt()
    stt._running.clear()
    stt.device = None
    stream = Mock()
    stream.start.side_effect = RuntimeError('start failure')
    stt._sd = Mock(RawInputStream=Mock(return_value=stream))
    with pytest.raises(RuntimeError):
        stt.start()
    stream.close.assert_called_once()
    assert stt._stream is None and not stt._running.is_set()


def test_capture_discards_queued_precapture_audio():
    stt = _bare_vosk_stt()
    stt._audio_q.put(b'old speech')
    assert stt.capture(.1, timeout=.01) is None
    assert stt._audio_q.empty() and stt._reset_pending.is_set()


def test_shutdown_does_not_create_late_unmute_timer(service):
    service._closing.set()
    service._on_speak_end()
    assert service._unmute_timer is None


def test_dedup_history_bounded_even_for_high_priority():
    tts = FakeTTS()
    for number in range(100):
        tts.speak(f'alert {number}', Priority.HIGH)
    assert len(tts._recent) <= 64
    tts.shutdown()


def test_full_queue_reports_rejected_new_item():
    tts = FakeTTS(max_queue=1)
    assert tts.speak('alert', Priority.HIGH)
    assert not tts.speak('discarded', Priority.LOW)
    tts.shutdown()


def test_speak_end_callback_failure_does_not_kill_worker(caplog):
    from unittest.mock import Mock
    faults = []
    tts = FakeTTS(on_speak_start=Mock(), on_speak_end=Mock(side_effect=RuntimeError('private details')),
                  on_fault=faults.append)
    try:
        tts.speak('first')
        tts.speak('second')
        tts.start()
        assert wait_for(lambda: len(faults) == 2)
        assert tts.spoken == ['first', 'second']
        assert 'reason=on_speak_end_failed' in caplog.text
        assert 'private details' not in caplog.text
    finally:
        tts.shutdown()


def test_recognizer_reset_failure_is_reported_and_retried(caplog):
    from unittest.mock import Mock
    stt = _bare_vosk_stt()
    stt.on_fault = Mock()
    stt.recognizer = Mock()
    stt.recognizer.Reset.side_effect = [RuntimeError('private details'), None]
    stt.recognizer.AcceptWaveform.side_effect = lambda _: (stt._running.clear() or False)
    stt._reset_pending.set()
    stt._audio_q.put(b'first')
    stt._audio_q.put(b'second')
    stt._run()
    assert stt.recognizer.Reset.call_count == 2
    stt.recognizer.AcceptWaveform.assert_called_once_with(b'second')
    stt.on_fault.assert_called_once_with('recognition_failed')
    assert 'reason=recognition_failed' in caplog.text
    assert 'private details' not in caplog.text


def test_stopping_between_capture_check_and_arm_refuses_wait():
    from unittest.mock import Mock
    stt = _bare_vosk_stt()
    stt._drain_audio = Mock(side_effect=stt._running.clear)
    started = time.monotonic()
    assert stt.capture(3) is None
    assert time.monotonic() - started < .5
    assert stt._reset_pending.is_set() and not stt.is_capturing
