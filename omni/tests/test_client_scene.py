"""Application integration tests: synthetic media, mocked vendor calls, no network."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "computer-vision"))
from scene_state import SceneState
from omni import _request_worker
from omni.client import AssistantResult, ClientConfig, OmniClient
from omni.fake import FakeOmniClient
from omni.scene import AUDIO_QUESTION_PROMPT, TEXT_QUESTION_PREFIX, describe_and_speak, describe_scene


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "calls.jsonl"
        self.config = ClientConfig(cloud_enabled=True, timeout_s=2, audit_log=self.log)
        self.env = patch.dict(os.environ, {"YIBU_API_KEY": "unit-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def fake_process(self, outcome):
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps(outcome).encode(), None)
        process.poll.return_value = 0
        return process

    def test_disabled_never_starts_worker_or_writes_audit(self):
        with patch("omni.client.subprocess.Popen") as spawn:
            result = OmniClient().complete("q", b"jpeg")
        self.assertEqual(result.reason, "cloud_disabled")
        spawn.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_missing_key_returns_result_instead_of_exiting(self):
        with patch.dict(os.environ, {"YIBU_API_KEY": ""}), patch("omni.client.subprocess.Popen") as spawn:
            result = OmniClient(self.config).complete("q", b"jpeg")
        self.assertEqual(result.reason, "not_configured")
        spawn.assert_not_called()

    def test_success_sends_bytes_and_audits_only_metadata(self):
        outcome = dict(ok=True, text="A chair is visible.", status_code=200,
                       usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        process = self.fake_process(outcome)
        with patch("omni.client.subprocess.Popen", return_value=process) as spawn:
            result = OmniClient(self.config).complete("private-prompt", b"secret-jpeg", b"secret-wav")
        self.assertEqual(result.status, "success")
        request = json.loads(process.communicate.call_args_list[0].args[0])
        parts = request["messages"][1]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "image_url", "input_audio"])
        self.assertEqual(base64.b64decode(parts[1]["image_url"]["url"].split(",")[1]), b"secret-jpeg")
        self.assertEqual(parts[2]["input_audio"]["format"], "wav")
        self.assertNotIn("YIBU_API_KEY", spawn.call_args.kwargs["env"])
        ledger = self.log.read_text()
        for secret in ("private-prompt", "secret-jpeg", "secret-wav", "unit-key", "A chair is visible."):
            self.assertNotIn(secret, ledger)
        records = [json.loads(line) for line in ledger.splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["total_tokens"], 3)
        self.assertEqual(records[0]["call_id"], result.call_id)

    def test_malformed_worker_envelope_is_audited_and_reaped(self):
        for outcome in ([], None, 42):
            process = self.fake_process(outcome)
            with patch("omni.client.subprocess.Popen", return_value=process):
                result = OmniClient(self.config).complete("q", b"jpeg")
            self.assertEqual(result.reason, "worker_failed")
            self.assertEqual(process.communicate.call_count, 2)

    def test_network_error_is_unavailable_and_audited(self):
        with patch("omni.client.subprocess.Popen", return_value=self.fake_process(
                dict(ok=False, reason="network_error"))):
            result = OmniClient(self.config).complete("q", b"jpeg")
        self.assertEqual(result.reason, "network_error")
        self.assertFalse(json.loads(self.log.read_text())["ok"])

    def test_busy_does_not_queue(self):
        client = OmniClient(self.config)
        client._busy.acquire()
        try:
            self.assertEqual(client.complete("q", b"jpeg").reason, "busy")
        finally:
            client._busy.release()

    def test_invalid_media_never_starts_process(self):
        with patch("omni.client.subprocess.Popen") as spawn:
            result = OmniClient(self.config).complete("q", b"")
        self.assertEqual(result.reason, "invalid_input")
        spawn.assert_not_called()

    def test_real_stalled_process_is_killed_by_overall_deadline(self):
        # Real process / real pipes, but no HTTP. It ignores the request and
        # would remain blocked for 30 seconds without the parent deadline.
        real_popen = subprocess.Popen
        processes = []

        def stall(*args, **kwargs):
            process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            processes.append(process)
            return process

        client = OmniClient(ClientConfig(cloud_enabled=True, timeout_s=0.25, audit_log=self.log))
        started = time.monotonic()
        with patch("omni.client.subprocess.Popen", side_effect=stall):
            result = client.complete("q", b"jpeg")
        elapsed = time.monotonic() - started
        self.assertEqual(result.reason, "deadline_exceeded")
        self.assertLess(elapsed, 1.5)
        self.assertTrue(all(p.poll() is not None for p in processes))
        records = self.log.read_text().splitlines()
        self.assertEqual(len(records), 1)
        self.assertIsNone(json.loads(records[0])["total_tokens"])

    def test_continuous_worker_output_cannot_extend_deadline(self):
        real_popen = subprocess.Popen
        processes = []

        def trickle(*args, **kwargs):
            code = "import sys,time\nwhile True:\n sys.stdout.write(' '); sys.stdout.flush(); time.sleep(0.01)"
            process = real_popen([sys.executable, "-c", code], **kwargs)
            processes.append(process)
            return process

        client = OmniClient(ClientConfig(cloud_enabled=True, timeout_s=0.25, audit_log=self.log))
        started = time.monotonic()
        with patch("omni.client.subprocess.Popen", side_effect=trickle):
            result = client.complete("q", b"jpeg")
        self.assertEqual(result.reason, "deadline_exceeded")
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(all(p.poll() is not None for p in processes))

    def test_worker_start_failure_is_audited(self):
        with patch("omni.client.subprocess.Popen", side_effect=OSError("private-error")):
            result = OmniClient(self.config).complete("q", b"jpeg")
        self.assertEqual(result.reason, "worker_failed")
        self.assertNotIn("private-error", self.log.read_text())

    def test_audit_failure_is_not_reported_as_success(self):
        with patch("omni.client.subprocess.Popen", return_value=self.fake_process(dict(ok=True, text="chair"))), \
                patch("omni.client.append_audit_record", side_effect=OSError("disk")):
            result = OmniClient(self.config).complete("q", b"jpeg")
        self.assertEqual(result.reason, "audit_failed")

    def test_config_requires_explicit_opt_in_and_valid_budget(self):
        for kwargs in ({"cloud_enabled": "false"}, {"timeout_s": 0}, {"timeout_s": float("nan")},
                       {"base_url": "https://user:secret@example.com"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ClientConfig(**kwargs)


class WorkerTests(unittest.TestCase):
    def request(self):
        return dict(api_key="unit-key", model="test", messages=[], purpose="test", timeout=0.1)

    def test_vendor_success_preserves_accounting_without_writing_child_ledger(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "chair"}}],
                                     "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3,
                                               "extra": "private-body"}}
        response.raise_for_status.return_value = None
        with patch("omni.yibu_http.httpx.Client") as client, \
                patch("omni.yibu_http.append_audit_record") as disk_audit:
            client.return_value.__enter__.return_value.post.return_value = response
            outcome = _request_worker.execute(self.request())
            disk_audit.assert_not_called()
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["usage"]["total_tokens"], 3)
        self.assertNotIn("private-body", json.dumps(outcome))

    def test_length_truncated_reply_is_trimmed_to_last_sentence(self):
        from omni._request_worker import trim_truncated
        cases = [
            ("A chair is on the left. A person is stan", "length", "A chair is on the left."),
            ("A chair is on the left.", "length", "A chair is on the left."),
            ("A chair is on the left and", "length", "A chair is on the left and"),
            ("A chair is on the left. A person is stan", "stop", "A chair is on the left. A person is stan"),
            ("A chair is on the left. A person is stan", None, "A chair is on the left. A person is stan"),
        ]
        for text, finish, expected in cases:
            with self.subTest(text=text, finish=finish):
                body = {"choices": [{"message": {"content": text}, "finish_reason": finish}]}
                self.assertEqual(trim_truncated(text, body), expected)
        self.assertEqual(trim_truncated("x. y", {}), "x. y")
        self.assertEqual(trim_truncated("x. y", {"choices": "bad"}), "x. y")
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "Chair left. Person ri"},
                                                    "finish_reason": "length"}]}
        response.raise_for_status.return_value = None
        with patch("omni.yibu_http.httpx.Client") as client, patch("omni.yibu_http.append_audit_record"):
            client.return_value.__enter__.return_value.post.return_value = response
            outcome = _request_worker.execute(self.request())
        self.assertEqual(outcome["text"], "Chair left.")

    def test_vendor_errors_are_sanitized(self):
        for exc, reason in ((httpx.ReadTimeout("private-frame"), "network_timeout"),
                            (httpx.ConnectError("unit-key"), "network_error"),
                            (ValueError("secret-wav"), "request_failed")):
            with self.subTest(reason=reason), patch("omni.yibu_http.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.side_effect = exc
                outcome = _request_worker.execute(self.request())
            self.assertEqual(outcome["reason"], reason)
            self.assertNotIn(str(exc), json.dumps(outcome))

    def test_http_failure_and_empty_response(self):
        response = Mock(status_code=503)
        response.json.return_value = {}
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "private-error", request=httpx.Request("POST", "https://example.invalid"),
            response=httpx.Response(503))
        with patch("omni.yibu_http.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response
            self.assertEqual(_request_worker.execute(self.request())["reason"], "http_error")
            response.status_code = 200
            response.raise_for_status.side_effect = None
            self.assertEqual(_request_worker.execute(self.request())["reason"], "empty_response")


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.clock = lambda: self.now
        self.state = SceneState(clock=self.clock)
        self.frame = np.zeros((12, 30, 3), dtype=np.uint8)
        self.frame[:] = (0, 0, 255)
        self.frame[6:] = (180, 180, 180)
        self.boxes = SimpleNamespace(xyxy=np.array([[1., 1., 5., 9.]]), cls=np.array([7]),
                                     conf=np.array([0.71]), id=None)
        self.state.update(self.frame, self.boxes, {7: "chair"}, "simulated")

    def describe(self, client, **kwargs):
        return describe_scene(self.state, client, clock=self.clock, **kwargs)

    def test_original_jpeg_evidence_age_and_single_read(self):
        client = Mock(config=ClientConfig(timeout_s=6))
        client.complete.return_value = AssistantResult("success", "A chair on the left.")
        self.now += 0.08
        with patch.object(self.state, "read", wraps=self.state.read) as read:
            result = self.describe(client, wav=b"wav")
        read.assert_called_once_with(max_age_s=0.5)
        self.assertEqual(result.status, "success")
        prompt, jpeg, wav = client.complete.call_args.args
        self.assertIn("Detected (age 80 ms): chair left 0.71", prompt)
        self.assertIn("Source: simulated", prompt)
        self.assertNotIn("px", prompt)
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, self.frame.shape)
        self.assertGreater(decoded[0, 0, 2], 240)  # BGR red survives encoding
        self.assertEqual(wav, b"wav")
        self.assertTrue(prompt.endswith(AUDIO_QUESTION_PROMPT))
        self.assertNotIn(TEXT_QUESTION_PREFIX, prompt)

    def test_missing_and_stale_never_call_client(self):
        client = Mock()
        self.now += 1
        self.assertEqual(self.describe(client).status, "unavailable")
        self.state.reset()
        self.assertEqual(self.describe(client).status, "unavailable")
        client.complete.assert_not_called()

    def test_encoding_can_expire_the_same_frame(self):
        original = cv2.imencode

        def slow_encode(*args):
            self.now += 1
            return original(*args)

        client = Mock()
        with patch("cv2.imencode", side_effect=slow_encode):
            result = self.describe(client)
        self.assertEqual(result.reason, "stale_scene")
        client.complete.assert_not_called()

    def test_late_answer_is_discarded(self):
        def late(*args, **kwargs):
            self.now += 6.01
            return AssistantResult("success", "Old answer", call_id="late-call")
        speech = Mock()
        result = describe_and_speak(self.state, Mock(config=None, complete=late), speech, clock=self.clock)
        self.assertEqual(result.reason, "stale_scene")
        self.assertEqual(result.call_id, "late-call")
        self.assertEqual(result.source_mode, "simulated")
        speech.speak.assert_not_called()

    def test_session_reset_discards_in_flight_answer(self):
        def restarted(*args, **kwargs):
            self.state.reset()
            self.state.update(self.frame, self.boxes, {7: "chair"}, "simulated")
            return AssistantResult("success", "Old session answer")
        speech = Mock()
        result = describe_and_speak(self.state, Mock(config=None, complete=restarted), speech, clock=self.clock)
        self.assertEqual(result.reason, "stale_scene")
        speech.speak.assert_not_called()

    def test_speech_queue_ttl_is_remaining_scene_lifetime(self):
        self.now += 0.4
        speech = Mock()
        result = describe_and_speak(self.state, FakeOmniClient(), speech, clock=self.clock)
        self.assertEqual(result.source_mode, "simulated")
        self.assertAlmostEqual(speech.speak.call_args.kwargs["ttl_seconds"], 5.6)

    def test_empty_detections_do_not_become_all_clear(self):
        self.state.update(self.frame, None, {}, "simulated")
        client = FakeOmniClient()
        result = self.describe(client)
        self.assertEqual(result.status, "success")
        self.assertEqual(client.calls, 1)
        self.assertIn("Detected (age 0 ms): none", client.last_call["prompt"])
        self.assertIn("Empty detections do not establish that the area is clear", client.last_call["prompt"])

    def test_answer_budget_is_separate_and_capped_by_client(self):
        self.now += 0.4
        client = FakeOmniClient()
        result = self.describe(client, answer_within_s=4)
        self.assertAlmostEqual(client.last_call["timeout_s"], 3.6)
        self.assertEqual(result.expires_at, 14)
        client.config = ClientConfig(timeout_s=2)
        self.describe(client, answer_within_s=4)
        self.assertEqual(client.last_call["timeout_s"], 2)

    def test_seconds_long_response_is_accepted_with_remaining_speech_ttl(self):
        def slow(*args, **kwargs):
            self.assertAlmostEqual(kwargs["timeout_s"], 5.6)
            self.now += 4
            return AssistantResult("success", "A chair.")
        self.now += 0.4
        speech = Mock()
        result = describe_and_speak(self.state, Mock(config=None, complete=slow), speech, clock=self.clock)
        self.assertEqual(result.status, "success")
        self.assertAlmostEqual(speech.speak.call_args.kwargs["ttl_seconds"], 1.6)

    def test_text_question_keeps_prefix_and_no_audio(self):
        client = FakeOmniClient()
        self.describe(client, prompt="Which objects are visible?")
        self.assertTrue(client.last_call["prompt"].endswith(TEXT_QUESTION_PREFIX + "Which objects are visible?"))
        self.assertNotIn(AUDIO_QUESTION_PROMPT, client.last_call["prompt"])
        self.assertIsNone(client.last_call["wav"])

    def test_audio_wording_is_explicit_about_the_wearer(self):
        self.assertEqual(AUDIO_QUESTION_PROMPT, "The audio is the wearer's spoken question. "
                         "Answer it in one short sentence using only the image and the detection list.")
        self.assertEqual(TEXT_QUESTION_PREFIX, "Question: ")

    def test_invalid_freshness_windows(self):
        for kwargs in ({"max_age_s": 0}, {"max_age_s": float("nan")},
                       {"max_age_s": float("inf")}, {"answer_within_s": 0},
                       {"answer_within_s": float("nan")}, {"answer_within_s": float("inf")},
                       {"max_age_s": 2, "answer_within_s": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.describe(FakeOmniClient(), **kwargs)

    def test_input_at_exact_freshness_boundary_can_be_sent(self):
        self.now += 0.5
        self.assertEqual(self.describe(FakeOmniClient()).status, "success")

    def test_encoding_failure_is_structured(self):
        with patch("cv2.imencode", return_value=(False, None)):
            self.assertEqual(self.describe(Mock()).reason, "encoding_failed")

    def test_complete_synthetic_flow_with_fake_speech(self):
        from speech import Priority, SpeechService
        from speech.fakes import FakeTTS
        speech = SpeechService()
        tts = FakeTTS()
        try:
            speech.attach(tts=tts)
            result = describe_and_speak(self.state, FakeOmniClient(), speech, clock=self.clock)
            self.assertEqual(result.status, "success")
            self.assertTrue(tts.wait_idle(1))
            self.assertEqual(tts.spoken, [result.text])
        finally:
            speech.shutdown()

    def test_network_failure_flows_to_speech_status(self):
        speech = Mock()
        result = describe_and_speak(self.state, FakeOmniClient(reason="network_error"),
                                    speech, clock=self.clock)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(speech.speak.call_args.args[0], "Scene assistant unavailable")


if __name__ == "__main__":
    unittest.main()


class QualityAndHandoffTests(unittest.TestCase):
    setUp = SceneTests.setUp
    describe = SceneTests.describe
    def test_low_quality_never_encodes_or_calls_cloud(self):
        for value, quality in [(0, 'too_dark'), (255, 'too_bright'), (128, 'low_contrast')]:
            self.state.update(np.full_like(self.frame, value), self.boxes, {7: 'chair'}, 'simulated')
            self.assertEqual(self.state.read().quality, quality)
            client, speech = Mock(), Mock()
            with patch('cv2.imencode') as encode:
                result = describe_and_speak(self.state, client, speech, clock=self.clock)
            self.assertEqual(result.reason, 'low_quality')
            self.assertEqual(result.text, 'Camera view is unavailable')
            self.assertEqual(result.source_mode, 'simulated')
            client.complete.assert_not_called()
            encode.assert_not_called()

    def test_reset_between_response_and_handoff_is_silent(self):
        result = self.describe(FakeOmniClient())
        self.state.reset()
        speech = Mock()
        with patch('omni.scene.describe_scene', return_value=result):
            result = describe_and_speak(self.state, Mock(), speech, clock=self.clock)
        self.assertEqual(result.reason, 'stale_scene')
        speech.speak.assert_not_called()

    def test_nan_or_negative_handoff_ttl_never_enqueues(self):
        for expiry in (float('nan'), float('inf'), 9.0, 10.0):
            result = AssistantResult('success', 'old', expires_at=expiry)
            speech = Mock()
            with patch('omni.scene.describe_scene', return_value=result):
                outcome = describe_and_speak(self.state, Mock(), speech, clock=self.clock)
            self.assertEqual(outcome.reason, 'stale_scene')
            speech.speak.assert_not_called()

    def test_expiry_during_playback_does_not_cut_speech(self):
        speech = Mock()
        result = describe_and_speak(self.state, FakeOmniClient(), speech, clock=self.clock)
        self.assertEqual(result.status, 'success')
        is_valid = speech.speak.call_args.kwargs['is_valid']
        self.assertTrue(is_valid())
        self.now = result.expires_at + 30  # window elapses while Piper is still talking
        self.assertTrue(is_valid(), 'time expiry must not stop an answer mid-sentence')
        self.state.reset()
        self.assertFalse(is_valid(), 'a camera session reset still cancels')

    def test_queued_answer_invalidated_on_reset(self):
        from speech.fakes import FakeTTS
        tts = FakeTTS()
        result = describe_and_speak(self.state, FakeOmniClient(), tts, clock=self.clock)
        self.assertEqual(result.status, 'success')
        self.state.reset()
        tts.start()
        try:
            self.assertTrue(tts.wait_idle(1))
            self.assertEqual(tts.spoken, [])
        finally:
            tts.shutdown()
