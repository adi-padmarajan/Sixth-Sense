#!/usr/bin/env python3
"""Shared direct HTTP client for yibuapi OpenAI-compatible endpoints."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from yibu_audit import append_audit_record, require_env_api_key


DEFAULT_BASE_URL = "https://yibuapi.com/v1"


def require_api_key() -> str:
    return require_env_api_key("YIBU_API_KEY")


def _data_url(path: Path, fallback_mime: str) -> str:
    mime = mimetypes.guess_type(path.name)[0] or fallback_mime
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_omni_messages(
    prompt: str,
    *,
    image: Path | None = None,
    audio: Path | None = None,
    system: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image:
        content.append({"type": "image_url", "image_url": {"url": _data_url(image, "image/jpeg")}})
    if audio:
        # This is the shape used by the existing successful yibu Qwen Omni calls.
        content.append(
            {
                "type": "input_audio",
                "input_audio": {"data": _data_url(audio, "audio/wav"), "format": audio.suffix.lstrip(".") or "wav"},
            }
        )
    messages.append({"role": "user", "content": content})
    return messages


def extract_text(response_json: Mapping[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        return "".join(
            str(item.get("text") or "") for item in content if isinstance(item, Mapping)
        )
    return str(content or "")


def chat_completion(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    purpose: str,
    base_url: str = DEFAULT_BASE_URL,
    max_tokens: int = 256,
    temperature: float = 0.2,
    audit_log: str | Path | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    started = time.monotonic()
    status: int | None = None
    response_json: dict[str, Any] = {}
    try:
        # trust_env=False is intentional: HTTP(S)_PROXY/ALL_PROXY are ignored.
        with httpx.Client(timeout=300.0, trust_env=False) as client:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        status = response.status_code
        try:
            value = response.json()
            response_json = value if isinstance(value, dict) else {"response_type": type(value).__name__}
        except ValueError:
            response_json = {}
        response.raise_for_status()
        record = append_audit_record(
            model=model,
            api_key=api_key,
            endpoint=endpoint,
            purpose=purpose,
            transport="http",
            ok=True,
            status_code=status,
            latency_s=time.monotonic() - started,
            response_json=response_json,
            audit_log=audit_log,
        )
        return extract_text(response_json), response_json, record
    except Exception as exc:
        append_audit_record(
            model=model,
            api_key=api_key,
            endpoint=endpoint,
            purpose=purpose,
            transport="http",
            ok=False,
            status_code=status,
            latency_s=time.monotonic() - started,
            response_json=response_json,
            error=f"{type(exc).__name__}: {exc}",
            audit_log=audit_log,
        )
        raise


def run_omni_cli(default_model: str, default_purpose: str) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="请用一句话介绍你自己。")
    parser.add_argument("--image", type=Path, help="可选，本地图片")
    parser.add_argument("--audio", type=Path, help="可选，本地音频")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--purpose", default=default_purpose)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--audit-log", type=Path)
    args = parser.parse_args()
    text, _response, record = chat_completion(
        api_key=require_api_key(),
        model=args.model,
        messages=build_omni_messages(args.prompt, image=args.image, audio=args.audio),
        purpose=args.purpose,
        base_url=args.base_url,
        max_tokens=args.max_tokens,
        audit_log=args.audit_log,
    )
    print(text)
    print(json.dumps({"call_id": record["call_id"], "usage": {
        "input_tokens": record["input_tokens"],
        "output_tokens": record["output_tokens"],
        "total_tokens": record["total_tokens"],
    }}, ensure_ascii=False))
    return 0
