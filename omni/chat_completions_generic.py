#!/usr/bin/env python3
"""Generic direct yibuapi OpenAI-compatible Chat Completions sample."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from yibu_http import DEFAULT_BASE_URL, chat_completion, require_api_key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="从 yibuapi /v1/models 获取的精确模型 ID")
    parser.add_argument("--prompt", default="请用一句话介绍你自己。")
    parser.add_argument("--system")
    parser.add_argument("--purpose", default="example_generic_chat_completion")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--audit-log", type=Path)
    args = parser.parse_args()

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})
    text, _response, record = chat_completion(
        api_key=require_api_key(),
        model=args.model,
        messages=messages,
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


if __name__ == "__main__":
    raise SystemExit(main())
