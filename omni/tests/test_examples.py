from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from summarize_usage import summarize
from yibu_audit import append_audit_record, normalize_usage, require_env_api_key
from yibu_http import build_omni_messages, extract_text


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
