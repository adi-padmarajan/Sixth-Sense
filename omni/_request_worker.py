"""Private disposable vendor worker. Its parent owns the durable audit record."""
from __future__ import annotations

import json
import sys

import httpx

from . import yibu_http
from .yibu_audit import normalize_usage


SENTENCE_END = (".", "!", "?", "。", "！", "？")


def trim_truncated(text: str, response_json) -> str:
    """Drop a trailing half sentence when the model hit max_tokens.

    Speaking a clause that stops mid-word sounds like a fault. If the reply
    contains at least one complete sentence, keep only the complete ones;
    otherwise return it unchanged rather than saying nothing.
    """
    try:
        finish = (response_json.get("choices") or [{}])[0].get("finish_reason")
    except (AttributeError, IndexError, TypeError):
        finish = None
    if finish != "length":
        return text
    stripped = text.rstrip()
    if stripped.endswith(SENTENCE_END):
        return stripped
    cut = max(stripped.rfind(mark) for mark in SENTENCE_END)
    return stripped[:cut + 1] if cut > 0 else text


def execute(request):
    """Run the vendor function and retain only safe accounting fields.

    Redirect the vendor audit callback in this isolated process: the parent
    persists exactly one record even if it kills us before vendor cleanup runs.
    No change to vendor APIs or other processes; restore the callback for tests.
    """
    accounting = {}

    def capture_audit(**fields):
        usage = normalize_usage(fields.get("response_json"))
        accounting["status_code"] = fields.get("status_code")
        accounting["usage"] = {
            "prompt_tokens": usage["input_tokens"],
            "completion_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
        } if usage["usage_reported"] else {}
        return {}  # vendor's third return value is not used by the application

    original = yibu_http.append_audit_record
    yibu_http.append_audit_record = capture_audit
    try:
        text, response_json, _ = yibu_http.chat_completion(**request)
        if not text.strip():
            return dict(accounting, ok=False, reason="empty_response")
        return dict(accounting, ok=True, text=trim_truncated(text, response_json)[:4096])
    except httpx.TimeoutException:
        return dict(accounting, ok=False, reason="network_timeout")
    except httpx.HTTPStatusError:
        return dict(accounting, ok=False, reason="http_error")
    except httpx.HTTPError:
        return dict(accounting, ok=False, reason="network_error")
    except Exception:
        # Never send exception messages: they may contain request data or keys.
        return dict(accounting, ok=False, reason="request_failed")
    finally:
        yibu_http.append_audit_record = original


def main():
    request = json.load(sys.stdin)
    json.dump(execute(request), sys.stdout)


if __name__ == "__main__":
    main()
