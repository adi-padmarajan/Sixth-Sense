#!/usr/bin/env python3
"""Create archive-ready JSON/CSV summaries from a yibu call ledger."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yibu_audit import DEFAULT_AUDIT_LOG


FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize(log_path: Path) -> dict[str, Any]:
    rows_by_call_id: dict[str, dict[str, Any]] = {}
    duplicate_rows = 0
    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        call_id = str(row.get("call_id") or "")
        if not call_id:
            raise ValueError(f"line {line_number}: missing call_id")
        if call_id in rows_by_call_id:
            duplicate_rows += 1
            if row != rows_by_call_id[call_id]:
                raise ValueError(f"conflicting duplicate call_id: {call_id}")
            continue
        rows_by_call_id[call_id] = row

    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "ok": 0,
            "failed": 0,
            "usage_missing_calls": 0,
            **{field: 0 for field in FIELDS},
            **{f"{field}_missing_calls": 0 for field in FIELDS},
        }
    )
    for row in rows_by_call_id.values():
        key = (
            str(row.get("model") or "[missing]"),
            str(row.get("key_suffix") or "[missing]"),
            str(row.get("purpose") or "[missing]"),
        )
        group = groups[key]
        group["calls"] += 1
        group["ok" if row.get("ok") else "failed"] += 1
        if not row.get("usage_reported"):
            group["usage_missing_calls"] += 1
        for field in FIELDS:
            value = row.get(field)
            if value is None:
                group[f"{field}_missing_calls"] += 1
            else:
                group[field] += int(value)

    group_rows = [
        {"model": key[0], "key_suffix": key[1], "purpose": key[2], **value}
        for key, value in sorted(groups.items())
    ]
    totals = {
        "calls": sum(item["calls"] for item in group_rows),
        "ok": sum(item["ok"] for item in group_rows),
        "failed": sum(item["failed"] for item in group_rows),
        "usage_missing_calls": sum(item["usage_missing_calls"] for item in group_rows),
        **{field: sum(item[field] for item in group_rows) for field in FIELDS},
        **{
            f"{field}_missing_calls": sum(item[f"{field}_missing_calls"] for item in group_rows)
            for field in FIELDS
        },
    }
    return {
        "schema_version": "yibu_usage_summary_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(log_path.resolve()),
            "bytes": log_path.stat().st_size,
            "sha256": file_sha256(log_path),
            "unique_call_ids": len(rows_by_call_id),
            "duplicate_rows_ignored": duplicate_rows,
        },
        "accounting_note": "Missing token values are unknown, not zero; totals only sum reported values.",
        "totals": totals,
        "groups": group_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=DEFAULT_AUDIT_LOG)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent / "artifacts" / "summary")
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit(f"audit log does not exist: {args.log}")
    result = summarize(args.log)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "usage_summary.json"
    csv_path = args.out_dir / "usage_by_model_key_purpose.csv"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    group_rows = result["groups"]
    fieldnames = list(group_rows[0]) if group_rows else ["model", "key_suffix", "purpose"]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(group_rows)
    print(json.dumps({"json": str(json_path), "csv": str(csv_path), "totals": result["totals"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
