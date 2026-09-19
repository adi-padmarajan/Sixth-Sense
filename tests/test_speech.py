"""Device-free checks for the speech package (fakes only: no models, no audio)."""

import threading
import time

import pytest

from speech import Priority, SpeechService
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
    tts = FakeTTS(play_seconds=0.3)
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


# -- Service: dispatch --------------------------------------------------------

def test_handler_runs_off_the_recognition_thread(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    seen = {}
    done = threading.Event()

    def handler():
        seen["thread"] = threading.current_thread().name
        done.set()

    service.on("mute", handler)
    assert stt.inject("mute")
    assert done.wait(1.0)
    assert seen["thread"] == "speech-dispatch"
    assert seen["thread"] != threading.current_thread().name


def test_command_matching_is_case_insensitive_and_supports_multiple_handlers(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    calls = []
    service.on("Volume Up", lambda: calls.append("a"))
    service.on("volume up", lambda: calls.append("b"))
    stt.inject("VOLUME UP")
    assert wait_for(lambda: len(calls) == 2)
    assert sorted(calls) == ["a", "b"]


def test_stale_command_is_dropped(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt, max_command_age_seconds=0.5)
    calls = []
    service.on("stop", lambda: calls.append(1))
    stt.inject("stop", recognized_at=time.monotonic() - 5.0)
    stt.inject("stop")  # fresh one still goes through
    assert wait_for(lambda: len(calls) == 1)
    time.sleep(0.05)
    assert calls == [1]


def test_unmatched_utterance_and_raising_handler_do_not_break_dispatch(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    calls = []

    def bad():
        raise ValueError("handler bug")

    service.on("describe", bad)
    service.on("mute", lambda: calls.append(1))
    stt.inject("[unk]")
    stt.inject("volume up [unk]")
    stt.inject("describe")
    stt.inject("mute")
    assert wait_for(lambda: calls == [1])


def test_slow_handler_does_not_block_recognition(service):
    stt = FakeSTT()
    service.attach(tts=FakeTTS(), stt=stt)
    release = threading.Event()
    service.on("describe", release.wait)
    stt.inject("describe")
    t0 = time.monotonic()
    assert stt.inject("mute")   # returns immediately; STT thread is not blocked
    assert time.monotonic() - t0 < 0.1
    release.set()


# -- Service: echo guard and health ------------------------------------------

def test_mic_is_muted_during_speech_and_for_echo_guard_after(service):
    stt = FakeSTT()
    tts = FakeTTS(play_seconds=0.1)
    service.attach(tts=tts, stt=stt, echo_guard_seconds=0.1)
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
    service.attach(tts=tts, stt=stt, echo_guard_seconds=0.2)
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
