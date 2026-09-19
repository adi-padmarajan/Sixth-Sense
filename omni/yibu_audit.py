#!/usr/bin/env python3
"""Append-only token accounting for yibuapi examples.

Only a four-character API-key suffix is retained. Request content, response
content, and the complete API key are deliberately excluded from the ledger.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_AUDIT_LOG = Path(__file__).resolve().parent / "artifacts" / "yibu_api_calls.jsonl"


def require_env_api_key(name: str = "YIBU_API_KEY") -> str:
    """Load a printable single-token key without ever displaying its value."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"请先设置环境变量 {name}。")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise SystemExit(f"环境变量 {name} 不是纯 ASCII 单行凭据；请勿把带说明文字的整行传入。")
    return value


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_usage(response_json: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize OpenAI HTTP/Realtime and Gemini Live token fields.

    Missing usage remains ``None``. It must not be silently treated as zero.
    """
    data: Mapping[str, Any] = response_json or {}
    candidates: list[Any] = [data.get("usage"), data.get("usageMetadata")]
    response = data.get("response")
    if isinstance(response, Mapping):
        candidates.extend([response.get("usage"), response.get("usageMetadata")])
    usage = next((item for item in candidates if isinstance(item, Mapping)), {})

    input_tokens = _integer(usage.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _integer(usage.get("promptTokenCount"))
    if input_tokens is None:
        input_tokens = _integer(usage.get("inputTokenCount"))
    if input_tokens is None:
        input_tokens = _integer(usage.get("input_tokens"))

    output_tokens = _integer(usage.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _integer(usage.get("responseTokenCount"))
    if output_tokens is None:
        output_tokens = _integer(usage.get("outputTokenCount"))
    if output_tokens is None:
        output_tokens = _integer(usage.get("output_tokens"))

    total_tokens = _integer(usage.get("total_tokens"))
    if total_tokens is None:
        total_tokens = _integer(usage.get("totalTokenCount"))
    derived_total = False
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
        derived_total = True

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "usage_reported": bool(usage),
        "total_tokens_derived": derived_total,
        "usage_raw": dict(usage),
    }


def key_suffix(api_key: str) -> str:
    value = str(api_key or "").strip()
    return "[missing]" if not value else "..." + value[-4:]


def append_audit_record(
    *,
    model: str,
    api_key: str,
    endpoint: str,
    purpose: str,
    transport: str,
    ok: bool,
    latency_s: float,
    response_json: Mapping[str, Any] | None = None,
    status_code: int | None = None,
    error: str | None = None,
    call_id: str | None = None,
    audit_log: str | Path | None = None,
) -> dict[str, Any]:
    usage = normalize_usage(response_json)
    record: dict[str, Any] = {
        "schema_version": "yibu_call_audit_v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "timestamp_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "call_id": call_id or uuid.uuid4().hex,
        "provider": "yibuapi",
        "model": str(model),
        "key_suffix": key_suffix(api_key),
        "purpose": str(purpose),
        "transport": str(transport),
        "endpoint": str(endpoint),
        "ok": bool(ok),
        "status_code": status_code,
        "latency_s": round(float(latency_s), 4),
        **usage,
    }
    if error:
        error_text = str(error)
        if api_key:
            error_text = error_text.replace(str(api_key), "[REDACTED]")
        record["error"] = error_text[:2000]

    path = Path(audit_log or os.environ.get("YIBU_AUDIT_LOG") or DEFAULT_AUDIT_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return record
