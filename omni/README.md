# yibuapi Direct Call and Token Archiving Samples

This directory is a Python package inside the sixth-sense repo; run all commands from the repository root.

This set of samples has no built-in key, does not read key files from the repository, and does not use a proxy. Credentials are only read from the process environment variable `YIBU_API_KEY`.

## Installation

From the repo root, in the project venv (`httpx` and `websockets` are listed in the top-level `requirements.txt`):

```bash
python -m pip install -r requirements.txt
export YIBU_API_KEY='fill in within the current shell, do not write into code'
```

## Model Entry Points

```bash
# Qwen3.5 Omni Flash: HTTP Chat Completions
python -m omni.qwen35_omni_flash --prompt 'Hello, introduce yourself in one sentence'

# Qwen3.5 Omni Plus: HTTP Chat Completions
python -m omni.qwen35_omni_plus --prompt 'Hello, introduce yourself in one sentence'

# Qwen3.5 Omni Plus Realtime: WebSocket
python -m omni.qwen35_omni_plus_realtime --prompt 'Hello, introduce yourself in one sentence'

# Gemini 3.1 Flash Live: Gemini Live WebSocket
python -m omni.gemini31_flash_live --prompt 'Answer briefly: which country is Beijing the capital of?'

# Other generic OpenAI-compatible models
python -m omni.chat_completions_generic --model 'exact model ID' --prompt 'Hello'
```

The Qwen HTTP Omni samples also support local images or audio:

```bash
python -m omni.qwen35_omni_flash --prompt 'Describe the image' --image /path/example.jpg
python -m omni.qwen35_omni_plus --prompt 'Transcribe and summarize the audio' --audio /path/example.wav
```

Gemini Live natively returns audio; the script outputs text via `outputAudioTranscription`. Use `--audio-out reply.pcm` to save the raw audio bytes.

## Token Auditing and Summarization

Each successful or failed call automatically appends a record to `artifacts/yibu_api_calls.jsonl`; there is no need to run a separate audit. Records do not store the full key, prompt, or model body text.

You can also specify a persistent ledger location:

```bash
export YIBU_AUDIT_LOG=/path/yibu_api_calls.jsonl
```

Summarize manually after the task is complete:

```bash
python -m omni.summarize_usage
```

By default this generates:

```text
artifacts/summary/usage_summary.json
artifacts/summary/usage_by_model_key_purpose.csv
```

Supports usage fields from OpenAI Chat Completions, OpenAI Realtime, and Gemini Live. When the upstream does not return usage, it stays `null` and increments the missing count — unknown consumption must never be treated as 0.

## No-Proxy Guarantee

- HTTP: `httpx.Client(..., trust_env=False)`
- WebSocket: `websockets.connect(..., proxy=None)`

As a result, `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` are never read.

## Offline Testing

```bash
python -m unittest discover -s omni/tests -t . -v
python -m compileall -q omni
```
