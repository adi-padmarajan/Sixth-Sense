#!/usr/bin/env python3
"""Gemini 3.1 Flash Live over yibu Gemini Live WebSocket.

The live model returns AUDIO. Text is read from outputAudioTranscription.
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any, Mapping

from websockets.sync.client import connect

from yibu_audit import append_audit_record, require_env_api_key


DEFAULT_MODEL = "gemini-3.1-flash-live-preview"
DEFAULT_ENDPOINT = "wss://yibuapi.com/v1beta/gemini/live"


def gemini_live_call(
    *,
    api_key: str,
    model: str,
    prompt: str,
    purpose: str,
    endpoint: str,
    audit_log: Path | None,
    audio_out: Path | None,
    timeout: float = 60.0,
) -> tuple[str, dict[str, Any]]:
    started = time.monotonic()
    usage: dict[str, Any] = {}
    transcriptions: list[str] = []
    fallback_text: list[str] = []
    audio_chunks: list[bytes] = []
    try:
        # proxy=None prevents discovery/use of HTTP(S)_PROXY and ALL_PROXY.
        with connect(
            endpoint,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            proxy=None,
            open_timeout=min(timeout, 30),
            close_timeout=5,
            max_size=None,
        ) as ws:
            ws.send(json.dumps({
                "setup": {
                    "model": f"models/{model}",
                    "generationConfig": {
                        # This Live model's supported output route is AUDIO.
                        "responseModalities": ["AUDIO"],
                        "temperature": 0.2,
                    },
                    # Readable text arrives through this transcription channel.
                    "outputAudioTranscription": {},
                }
            }, ensure_ascii=False))

            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for setupComplete")
                event = json.loads(ws.recv(timeout=remaining))
                if event.get("error"):
                    raise RuntimeError(f"setup rejected: {event['error']}")
                if "setupComplete" in event:
                    break

            ws.send(json.dumps({
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": prompt}]}],
                    "turnComplete": True,
                }
            }, ensure_ascii=False))

            turn_complete = False
            while not turn_complete:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for turnComplete")
                event = json.loads(ws.recv(timeout=remaining))
                if event.get("error"):
                    raise RuntimeError(f"Live server error: {event['error']}")
                if isinstance(event.get("usageMetadata"), Mapping):
                    usage = dict(event["usageMetadata"])
                server = event.get("serverContent")
                if not isinstance(server, Mapping):
                    continue
                transcription = server.get("outputTranscription")
                if isinstance(transcription, Mapping) and transcription.get("text"):
                    transcriptions.append(str(transcription["text"]))
                model_turn = server.get("modelTurn")
                if isinstance(model_turn, Mapping):
                    for part in model_turn.get("parts") or []:
                        if not isinstance(part, Mapping):
                            continue
                        if part.get("text"):
                            fallback_text.append(str(part["text"]))
                        inline = part.get("inlineData") or part.get("inline_data")
                        if isinstance(inline, Mapping) and inline.get("data"):
                            audio_chunks.append(base64.b64decode(str(inline["data"])))
                turn_complete = bool(server.get("turnComplete"))

        if audio_out and audio_chunks:
            audio_out.parent.mkdir(parents=True, exist_ok=True)
            audio_out.write_bytes(b"".join(audio_chunks))
        record = append_audit_record(
            model=model,
            api_key=api_key,
            endpoint=endpoint,
            purpose=purpose,
            transport="websocket",
            ok=True,
            status_code=101,
            latency_s=time.monotonic() - started,
            response_json={"usageMetadata": usage},
            audit_log=audit_log,
        )
        return "".join(transcriptions).strip() or "\n".join(fallback_text).strip(), record
    except Exception as exc:
        append_audit_record(
            model=model,
            api_key=api_key,
            endpoint=endpoint,
            purpose=purpose,
            transport="websocket",
            ok=False,
            latency_s=time.monotonic() - started,
            response_json={"usageMetadata": usage},
            error=f"{type(exc).__name__}: {exc}",
            audit_log=audit_log,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="请用一句中文简短介绍你自己。")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--purpose", default="example_gemini31_flash_live")
    parser.add_argument("--audit-log", type=Path)
    parser.add_argument("--audio-out", type=Path, help="可选：保存返回的原始音频字节（通常为 PCM）")
    args = parser.parse_args()
    api_key = require_env_api_key()
    text, record = gemini_live_call(
        api_key=api_key,
        model=args.model,
        prompt=args.prompt,
        purpose=args.purpose,
        endpoint=args.endpoint,
        audit_log=args.audit_log,
        audio_out=args.audio_out,
    )
    print(text)
    print(json.dumps({"call_id": record["call_id"], "usage": {
        "input_tokens": record["input_tokens"],
        "output_tokens": record["output_tokens"],
        "total_tokens": record["total_tokens"],
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
