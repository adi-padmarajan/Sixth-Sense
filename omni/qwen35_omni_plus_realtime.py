#!/usr/bin/env python3
"""Historical special route: Qwen3.5 Omni Plus via yibu Realtime WebSocket."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import websockets

from yibu_audit import append_audit_record, require_env_api_key


DEFAULT_MODEL = "qwen3.5-omni-plus-realtime"
DEFAULT_ENDPOINT = "wss://yibuapi.com/v1/realtime"


async def _receive(ws: Any, timeout: float) -> dict[str, Any]:
    value = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
    if not isinstance(value, dict):
        raise RuntimeError("server event is not a JSON object")
    if value.get("type") == "error":
        raise RuntimeError(json.dumps(value.get("error") or value, ensure_ascii=False))
    return value


async def realtime_text_call(
    *,
    api_key: str,
    model: str,
    prompt: str,
    purpose: str,
    endpoint: str,
    audit_log: Path | None,
) -> tuple[str, dict[str, Any]]:
    url = endpoint + ("&" if "?" in endpoint else "?") + urlencode({"model": model})
    started = time.monotonic()
    done_event: dict[str, Any] = {}
    try:
        # proxy=None prevents websockets from discovering HTTP(S)/ALL_PROXY.
        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            proxy=None,
            open_timeout=30,
            close_timeout=5,
            max_size=32 * 1024 * 1024,
        ) as ws:
            created = await _receive(ws, 20)
            if created.get("type") != "session.created":
                raise RuntimeError(f"expected session.created, got {created.get('type')}")
            session_model = str((created.get("session") or {}).get("model") or "")
            if session_model and session_model != model:
                raise RuntimeError(f"requested/session model mismatch: {model!r} != {session_model!r}")

            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "instructions": "Answer the user briefly and directly.",
                    "turn_detection": None,
                },
            }, ensure_ascii=False))
            updated = await _receive(ws, 20)
            if updated.get("type") != "session.updated":
                raise RuntimeError(f"expected session.updated, got {updated.get('type')}")

            await ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            }, ensure_ascii=False))
            await ws.send(json.dumps({"type": "response.create"}))

            deltas: list[str] = []
            while True:
                event = await _receive(ws, 90)
                event_type = str(event.get("type") or "")
                if event_type in ("response.text.delta", "response.audio_transcript.delta"):
                    deltas.append(str(event.get("delta") or ""))
                elif event_type == "response.text.done" and event.get("text"):
                    deltas = [str(event["text"])]
                elif event_type == "response.audio_transcript.done" and not deltas:
                    deltas = [str(event.get("transcript") or "")]
                elif event_type == "response.done":
                    done_event = event
                    break

        record = append_audit_record(
            model=model,
            api_key=api_key,
            endpoint=url,
            purpose=purpose,
            transport="websocket",
            ok=True,
            status_code=101,
            latency_s=time.monotonic() - started,
            response_json=done_event,
            audit_log=audit_log,
        )
        return "".join(deltas).strip(), record
    except Exception as exc:
        append_audit_record(
            model=model,
            api_key=api_key,
            endpoint=url,
            purpose=purpose,
            transport="websocket",
            ok=False,
            latency_s=time.monotonic() - started,
            response_json=done_event,
            error=f"{type(exc).__name__}: {exc}",
            audit_log=audit_log,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="请用一句话介绍你自己。")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--purpose", default="example_qwen35_omni_plus_realtime")
    parser.add_argument("--audit-log", type=Path)
    args = parser.parse_args()
    api_key = require_env_api_key()
    text, record = asyncio.run(realtime_text_call(
        api_key=api_key,
        model=args.model,
        prompt=args.prompt,
        purpose=args.purpose,
        endpoint=args.endpoint,
        audit_log=args.audit_log,
    ))
    print(text)
    print(json.dumps({"call_id": record["call_id"], "usage": {
        "input_tokens": record["input_tokens"],
        "output_tokens": record["output_tokens"],
        "total_tokens": record["total_tokens"],
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
