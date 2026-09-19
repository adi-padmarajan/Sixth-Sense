"""Offline synthetic logs only; none of these numbers are device measurements."""
import json
from pathlib import Path
import subprocess
import sys

from scripts.summarize_latency import summarize

FIXTURE = Path(__file__).parent / 'fixtures' / 'latency.jsonl'


def test_latency_groups_percentiles_and_missing_values():
    with FIXTURE.open() as stream:
        result = summarize(stream)
    assert result['count'] == 5
    groups = {(g['status'], g['kind']): g for g in result['groups']}
    assert len(groups) == 4
    direct = groups['success', 'direct_question']
    assert direct['metrics']['total_ms'] == {'count': 2, 'p50': 150, 'p95': 195, 'max': 200}
    assert direct['metrics']['speech_started_ms'] == {'count': 2, 'p50': 200, 'p95': 245, 'max': 250}
    unavailable = groups['unavailable', 'describe']
    assert unavailable['metrics']['assistant_ms'] == {'count': 0, 'p50': None, 'p95': None, 'max': None}


def test_latency_cli_file_and_stdin_are_identical():
    cmd = [sys.executable, 'scripts/summarize_latency.py']
    file_result = subprocess.run(cmd + [str(FIXTURE)], capture_output=True, text=True, check=True)
    stdin_result = subprocess.run(cmd, input=FIXTURE.read_text(), capture_output=True, text=True, check=True)
    assert json.loads(file_result.stdout) == json.loads(stdin_result.stdout)


def test_invalid_values_never_become_zero_or_nan():
    rows = [
        {'event': 'question_completed', 'status': 'success', 'capture_ms': -1},
        {'event': 'question_completed', 'status': 'success', 'capture_ms': 0, 'total_ms': float('nan'), 'assistant_ms': True},
        {'event': 'question_completed', 'status': 'success', 'capture_ms': float('inf')},
    ]
    result = summarize(map(json.dumps, rows))
    assert result['skipped_invalid_questions'] == 2
    assert result['groups'][0]['metrics']['total_ms']['count'] == 0
    assert result['groups'][0]['metrics']['assistant_ms']['count'] == 0
    json.dumps(result, allow_nan=False)


def test_empty_log_has_no_fabricated_timings():
    assert summarize([])['groups'] == []
