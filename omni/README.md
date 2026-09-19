# yibuapi Direct Call and Token Archiving Samples

This directory is a Python package inside the sixth-sense repo; run all commands from the repository root.

## Application-facing assistant

`client.py` wraps the vendor transport. `scene.py` reads one CV snapshot, encodes
its original BGR frame to JPEG in memory, attaches detection text and source/age,
and returns a frozen `AssistantResult`. It does not load YOLO or open a camera.
`fake.py` provides an explicit offline client with the same `complete()` interface.
No imports initiate requests or load models. The existing vendor CLIs are unchanged.

```python
from omni.client import ClientConfig, OmniClient
from omni.scene import describe_scene

client = OmniClient()  # cloud disabled by default, even if a key is present
# state is the shared SceneState already updated by the CV loop.
result = describe_scene(state, client, wav=None, max_age_s=0.5)
print(result.status, result.reason, result.text)
```

To enable cloud requests intentionally, construct
`OmniClient(ClientConfig(cloud_enabled=True, timeout_s=5.0, audit_log=...))` and
set `YIBU_API_KEY` in the environment. Missing/invalid credentials return
`unavailable/not_configured`; they do not exit the application. The direct
`complete(prompt, jpeg_bytes, wav_bytes=None)` interface uses `MediaBytes` and
the vendor `chat_completion` internally. There are no media temp files.

Results contain `status` (`success` or `unavailable`), user-facing `text`, an
optional machine-readable `reason`, and optional audit `call_id`. Scene results
also carry `expires_at` (same monotonic clock as SceneState) and `source_mode`.
Unavailable reasons include disabled cloud, missing configuration, invalid input,
busy, deadline, network/HTTP errors, empty response, failed auditing, and absent,
expired, or reset scene evidence. No exception message or request body is logged.

### Deadline, freshness, and auditing

- Each client allows one request at a time; concurrent calls return `busy` without
  queuing. Run scene requests on an assistant worker, never the camera/UI loop
  or speech dispatcher.
- `_request_worker.py` runs the synchronous vendor call in a disposable subprocess.
  One monotonic budget covers preparation, startup, pipe transfer, and response.
  On expiry the parent kills and reaps the child; stalled or trickling responses
  cannot leave a background HTTP thread running. Ordinary OS scheduling, process
  cleanup, and local audit-file I/O add overhead: this is not a real-time guarantee.
- HTTPX's operation timeout is also set, but is not the overall deadline mechanism.
- The worker temporarily redirects the vendor audit callback **inside its own
  process** to collect only status and numeric token counts. The parent writes one
  record through the unchanged vendor ledger writer, including on deadline expiry.
  Error reasons are fixed codes; prompts, images, audio, reply bodies, and full
  credentials are excluded. The vendor's existing key suffix is retained.
- A killed request may have incurred provider usage; unknown usage remains `null`.
  No request is automatically retried. Failure to write the ledger returns
  `audit_failed` instead of claiming success.
- Scene freshness is checked before/after JPEG encoding and after the response.
  The request budget is capped by that snapshot's remaining lifetime. The default
  0.5 s scene budget is deliberately strict and may reject real cloud calls; tune
  it only after measuring. The synthetic demo explicitly uses 5 s.
- SceneState's `session_generation` invalidates in-flight responses after reset;
  advancing ordinary frame sequence does not change the session. Frame data is
  read only once per request. Age still measures YOLO result receipt, not exposure.
- Empty detections produce a local statement that unrecognized objects may still
  be present. No cloud call is made, and no all-clear is inferred. For nonempty
  scenes the model is prompted to acknowledge uncertainty; this does not prove
  its response is correct or prevent every hallucination/prompt injection.

`describe_and_speak(state, client, speech, ...)` hands the result to the existing
SpeechService at LOW priority for scene descriptions and NORMAL for unavailable
status. The queue TTL is bounded by remaining scene lifetime. A future orchestrator
must cancel queued speech on session reset; the current speech queue does not
support a per-scene generation predicate. Microphone recording, wake-handler
registration, camera startup, and a top-level orchestrator remain future work.

### Run the complete synthetic demo

```bash
env -u YIBU_API_KEY python -m omni.demo
```

This generates a simple chair-like drawing and simulated detections, uses the
fake assistant, and passes its answer through SpeechService/FakeTTS. It opens no
camera/microphone/speaker and makes no network calls. The fake response is canned;
it is not evidence of actual recognition accuracy.

For one deliberate provider integration test after configuring `YIBU_API_KEY`:

```bash
python -m omni.demo --live --audit-log /tmp/sixth-sense-live-check.jsonl
```

This sends **one generated image and prompt**, no personal camera/audio recording,
and still uses fake speech. `cloud_enabled=True` is printed before the request.
It is a billable provider call and remains unverified until run with credentials.

Tests (no network, GPU, model weights, audio devices, or API key):

```bash
env -u YIBU_API_KEY python -m unittest discover -s omni/tests -t . -v
env -u YIBU_API_KEY python -m unittest discover -s computer-vision/Tests -p 'test_*.py' -v
env -u YIBU_API_KEY python -m pytest tests/ -q
```

The real-deadline tests spawn local Python processes that stall or continuously
write output. They use no network sockets. Worker/vendor integration is mocked.

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
