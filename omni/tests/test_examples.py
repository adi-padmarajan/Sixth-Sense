from __future__ import annotations

import base64
import json
import mimetypes
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

import httpx

from omni.summarize_usage import summarize
from omni.yibu_audit import append_audit_record, normalize_usage, require_env_api_key
from omni.yibu_http import MediaBytes, build_omni_messages, chat_completion, extract_text


class UsageTests(unittest.TestCase):
    def test_key_rejects_labeled_non_ascii_line(self) -> None:
        with patch.dict("os.environ", {"YIBU_API_KEY": "API密钥：not-a-key"}):
            with self.assertRaises(SystemExit):
                require_env_api_key()

    def test_openai_usage(self) -> None:
        value = normalize_usage({"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}})
        self.assertEqual((value["input_tokens"], value["output_tokens"], value["total_tokens"]), (11, 7, 18))

    def test_gemini_usage(self) -> None:
        value = normalize_usage({"usageMetadata": {"promptTokenCount": 4, "responseTokenCount": 3, "totalTokenCount": 7}})
        self.assertEqual((value["input_tokens"], value["output_tokens"], value["total_tokens"]), (4, 3, 7))

    def test_realtime_nested_usage(self) -> None:
        value = normalize_usage({"type": "response.done", "response": {"usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}}})
        self.assertEqual(value["total_tokens"], 7)

    def test_missing_is_not_zero(self) -> None:
        value = normalize_usage({})
        self.assertIsNone(value["input_tokens"])
        self.assertFalse(value["usage_reported"])


class HttpShapeTests(unittest.TestCase):
    def test_text_only_omni_message(self) -> None:
        messages = build_omni_messages("hello")
        self.assertEqual(messages[0]["content"][0], {"type": "text", "text": "hello"})

    def test_extract_text(self) -> None:
        self.assertEqual(extract_text({"choices": [{"message": {"content": "ok"}}]}), "ok")

    def _successful_response(self) -> Mock:
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        response.raise_for_status.return_value = None
        return response

    def test_timeout_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("omni.yibu_http.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = self._successful_response()
            text, _, _ = chat_completion(
                api_key="unit-key", model="unit-model", messages=build_omni_messages("hello"),
                purpose="unit_test", timeout=1.5, audit_log=Path(directory) / "calls.jsonl",
            )
            client.assert_called_once_with(timeout=1.5, trust_env=False)
            self.assertEqual(text, "ok")

    def test_default_timeout_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("omni.yibu_http.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = self._successful_response()
            text, _, _ = chat_completion(
                api_key="unit-key", model="unit-model", messages=build_omni_messages("hello"),
                purpose="unit_test", audit_log=Path(directory) / "calls.jsonl",
            )
            client.assert_called_once_with(timeout=300.0, trust_env=False)
            self.assertEqual(text, "ok")

    def test_timeout_failure_audited_then_reraised(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("omni.yibu_http.httpx.Client") as client:
            log = Path(directory) / "calls.jsonl"
            client.return_value.__enter__.return_value.post.side_effect = httpx.ReadTimeout("slow")
            with self.assertRaises(httpx.ReadTimeout):
                chat_completion(
                    api_key="unit-key", model="unit-model", messages=build_omni_messages("hello"),
                    purpose="unit_test", timeout=1.5, audit_log=log,
                )
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertIs(record["ok"], False)
            self.assertIn('"ok":false', lines[0])
            self.assertIn("ReadTimeout", record["error"])


class MediaBytesTests(unittest.TestCase):
    def test_image_path_and_bytes_identical(self) -> None:
        data = b"\xff\xd8\xff\xe0FAKEJPEG"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.jpg"
            path.write_bytes(data)
            self.assertEqual(
                build_omni_messages("q", image=path),
                build_omni_messages("q", image=MediaBytes(data, "image/jpeg")),
            )

    def test_audio_path_and_bytes_identical(self) -> None:
        data = b"RIFFFAKEWAV"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "q.wav"
            path.write_bytes(data)
            # Native MIME tables may call WAV audio/x-wav. Preserve that legacy
            # wire value; in-memory callers supply the equivalent MIME and fmt.
            mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
            with self.subTest(mime=mime):
                from_path = build_omni_messages("q", audio=path)
                from_bytes = build_omni_messages("q", audio=MediaBytes(data, mime, fmt="wav"))
                self.assertEqual(from_path, from_bytes)
                for messages in (from_path, from_bytes):
                    self.assertEqual(messages[0]["content"][-1]["input_audio"]["format"], "wav")
                expected_url = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
                self.assertEqual(from_path[0]["content"][-1]["input_audio"]["data"], expected_url)
            # Exercise the requested audio/wav case independently of OS tables.
            with patch("omni.yibu_http.mimetypes.guess_type", return_value=("audio/wav", None)):
                from_path = build_omni_messages("q", audio=path)
                from_bytes = build_omni_messages("q", audio=MediaBytes(data, "audio/wav"))
                self.assertEqual(from_path, from_bytes)
                for messages in (from_path, from_bytes):
                    self.assertEqual(messages[0]["content"][-1]["input_audio"]["format"], "wav")

    def test_audio_format_override(self) -> None:
        messages = build_omni_messages("q", audio=MediaBytes(b"audio", "audio/wav", fmt="pcm16"))
        self.assertEqual(messages[0]["content"][-1]["input_audio"]["format"], "pcm16")

    def test_audio_format_from_mime_subtype(self) -> None:
        messages = build_omni_messages("q", audio=MediaBytes(b"audio", "audio/mpeg"))
        self.assertEqual(messages[0]["content"][-1]["input_audio"]["format"], "mpeg")

    def test_image_data_url_prefix_and_round_trip(self) -> None:
        data = b"\xff\xd8\xff\xe0FAKEJPEG"
        messages = build_omni_messages("q", image=MediaBytes(data, "image/jpeg"))
        url = messages[0]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), data)

    def test_content_order_and_system_message(self) -> None:
        messages = build_omni_messages(
            "q", image=MediaBytes(b"image", "image/jpeg"),
            audio=MediaBytes(b"audio", "audio/wav"), system="Describe the camera view",
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], {"role": "system", "content": "Describe the camera view"})
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(len(messages[1]["content"]), 3)
        self.assertEqual([part["type"] for part in messages[1]["content"]], ["text", "image_url", "input_audio"])

    def test_empty_data_and_bad_mime_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MediaBytes(b"", "image/jpeg")
        for mime in ("", "jpeg"):
            with self.subTest(mime=mime), self.assertRaises(ValueError):
                MediaBytes(b"image", mime)


class ArchiveTests(unittest.TestCase):
    def test_append_and_summarize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.jsonl"
            append_audit_record(
                model="unit-model",
                api_key="not-a-real-key",
                endpoint="https://example.invalid/v1/chat/completions",
                purpose="unit_test",
                transport="http",
                ok=True,
                latency_s=0.1,
                response_json={"usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}},
                audit_log=log,
                call_id="unit-call",
            )
            result = summarize(log)
            self.assertEqual(result["totals"]["total_tokens"], 5)
            self.assertEqual(result["source"]["unique_call_ids"], 1)
            self.assertNotIn("not-a-real-key", log.read_text())

    def test_error_redacts_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.jsonl"
            append_audit_record(
                model="unit-model",
                api_key="secret-unit-key",
                endpoint="https://example.invalid/v1/chat/completions",
                purpose="unit_test",
                transport="http",
                ok=False,
                latency_s=0.1,
                error="server echoed secret-unit-key",
                audit_log=log,
            )
            text = log.read_text()
            self.assertNotIn("secret-unit-key", text)
            self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
