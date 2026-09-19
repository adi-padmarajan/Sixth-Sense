"""Summarize host JSON-lines timings; no devices, imports with side effects, or network.

Percentiles use linear interpolation between sorted observations. A speech-start
value is the first PCM-write handoff, not physical speaker onset. Missing values
stay absent and have their own per-field count; they are never replaced by zero.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys

FIELDS = ('capture_ms', 'assistant_ms', 'total_ms', 'speech_started_ms')


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def percentile(values, percent):
    values = sorted(values)
    rank = (len(values) - 1) * percent / 100
    low, high = math.floor(rank), math.ceil(rank)
    return values[low] + (values[high] - values[low]) * (rank - low)


def summarize(lines):
    completed, starts = [], {}
    skipped = 0
    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue  # main logs also contain ordinary local backend messages
        if not isinstance(record, dict):
            continue
        event = record.get('event')
        if event == 'speech_started' and valid_number(record.get('speech_started_ms')):
            if isinstance(record.get('session_id'), str) and type(record.get('seq')) is int:
                starts[(record['session_id'], record['seq'])] = record['speech_started_ms']
        elif event == 'question_completed':
            if not isinstance(record.get('status'), str) or not valid_number(record.get('capture_ms')):
                skipped += 1
                continue
            completed.append(record)

    groups = defaultdict(list)
    for record in completed:
        if isinstance(record.get('session_id'), str) and type(record.get('seq')) is int:
            start = starts.get((record['session_id'], record['seq']))
            if start is not None:
                record['speech_started_ms'] = start
        kind = 'describe' if record['capture_ms'] > 0 else 'direct_question'
        groups[(record['status'], kind)].append(record)
    output = []
    for (status, kind), records in sorted(groups.items()):
        metrics = {}
        for field in FIELDS:
            values = [r[field] for r in records if valid_number(r.get(field))]
            metrics[field] = dict(count=len(values),
                                  p50=percentile(values, 50) if values else None,
                                  p95=percentile(values, 95) if values else None,
                                  max=max(values) if values else None)
        output.append(dict(status=status, kind=kind, count=len(records), metrics=metrics))
    return dict(count=len(completed), skipped_invalid_questions=skipped,
                percentile_method='linear interpolation', groups=output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', nargs='?', default='-', help='Log file, or - / omitted for stdin')
    args = parser.parse_args(argv)
    if args.log == '-':
        result = summarize(sys.stdin)
    else:
        with Path(args.log).open(encoding='utf-8') as stream:
            result = summarize(stream)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
