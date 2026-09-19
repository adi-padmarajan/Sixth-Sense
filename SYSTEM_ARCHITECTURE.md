# Sixth-Sense — Software Architecture (YOLO + Vosk/Piper + OMNI)

> Scope: the companion-host software only — local vision (YOLO), local voice
> I/O (Vosk STT, Piper TTS), and the cloud OMNI multimodal assistant.
> Proximity sensors, haptics, and firmware are a separate local path and are
> deliberately **not** described here.
>
> Status legend used throughout: **[exists]** = in the repo today,
> **[planned]** = agreed design, not yet written.

## 1. One-paragraph summary

The wearer says a wake phrase, then asks a question ("what's in front of me?").
Vosk (offline, grammar-limited) catches the wake phrase; the next few seconds
of microphone audio are recorded. That audio, the current camera frame, and
YOLO's structured detection list are sent in **one** request to an OMNI model
(`qwen3.5-omni-flash` via the yibuapi OpenAI-compatible endpoint; Gemini Live
is a stretch option). The model returns a short text answer, which
is played through the existing priority-aware speech queue. If the network is
down, the assistant reports itself unavailable; YOLO preview and local speech
keep running.

## 2. Components

| Component | Location | Status | Role |
| --- | --- | --- | --- |
| YOLO tracker | `computer-vision/track_distances.py` | [exists] | Ultralytics tracking on camera `0` with the local Objects365 checkpoint; annotated preview; object-to-object **pixel** distances |
| Scene state | `computer-vision/scene_state.py` | [exists] | Thread-safe latest original frame + detections + monotonic result-receipt timestamp; immutable snapshots, freshness filtering, and reset |
| Vosk STT | `speech/stt.py` | [exists] | Offline recognizer restricted to `configs/grammar.json` (words validated against the model at startup); background mic thread; fires `on_command(text, recognized_at, source_mode)` |
| Piper TTS | `speech/tts.py` | [exists] | Offline synthesis with `LOW / NORMAL / HIGH` priority queue and interrupt |
| SpeechService | `speech/service.py` | [exists] | Singleton facade: `speech.on(cmd, handler(Command))`, `speech.speak(text, priority)`; mutes the mic while the speaker plays (echo guard); optional wake-phrase arming; per-subsystem health |
| SpeechConfig | `speech/config.py`, `configs/speech.json` | [exists] | Validated, versioned settings: model paths, devices, timing, queue limits, wake phrase |
| Question recorder | `speech/` (extension) | [planned] | After a wake phrase, capture ~3 s of raw mic audio for the assistant instead of feeding it to Vosk |
| yibu HTTP transport | `omni/yibu_http.py` | [exists] | `build_omni_messages(prompt, image=Path, audio=Path, system=…)` → OpenAI-style content parts (text, `image_url` data-URL, `input_audio` data-URL); `chat_completion(...)` POSTs to `https://yibuapi.com/v1/chat/completions` with `httpx` (`trust_env=False`, **300 s timeout**), returns `(text, response_json, audit_record)`, audits every call; `extract_text()` flattens the reply |
| Call audit ledger | `omni/yibu_audit.py`, `omni/artifacts/yibu_api_calls.jsonl` | [exists] | `require_env_api_key("YIBU_API_KEY")` (raises `SystemExit` if unset/non-ASCII); `append_audit_record()` appends one JSON line per call — model, key suffix, purpose, transport, ok/status, latency, normalized tokens (missing = `null`, never 0); no prompt/response bodies are stored |
| Usage summariser | `omni/summarize_usage.py`, `omni/artifacts/summary/` | [exists] | Offline; turns the ledger into `usage_summary.json` + CSV grouped by model/key/purpose |
| Model entry scripts | `omni/qwen35_omni_flash.py`, `qwen35_omni_plus.py`, `chat_completions_generic.py` | [exists] | CLI wrappers over `yibu_http.run_omni_cli` / `chat_completion` (`--prompt --image --audio`); manual smoke tests only, not imported by the app |
| Streaming entry scripts | `omni/qwen35_omni_plus_realtime.py` (OpenAI Realtime WS), `omni/gemini31_flash_live.py` (Gemini Live WS) | [exists] | Text-prompt demos over `websockets` (`proxy=None`); Gemini returns audio, text comes from `outputAudioTranscription`. **Not on the demo path** — stretch goal only |
| Package tests | `omni/tests/test_examples.py` | [exists] | Key-free unit tests for message shape, usage normalisation, ledger summary (`cd omni && python -m unittest discover -s tests`) |
| OMNI client | `omni/client.py` | [planned] | Thin in-process wrapper over `yibu_http.chat_completion`: accepts **bytes** (JPEG, WAV) not paths, overrides the 300 s timeout with a bounded one, converts `SystemExit`/`httpx` errors into a typed `AssistantUnavailable`, sets `purpose="sixth_sense_scene"` for the ledger |
| Scene request builder | `omni/scene.py` | [planned] | Reads `SceneState` once, encodes the frame, formats detections via `to_text`, builds the system prompt, calls the client, hands the text to `speech.speak` |
| OMNI fake | `omni/fake.py` | [planned] | Same interface as `client.py`, canned answer, no network — for tests and the offline demo (`OMNI_FAKE=1`) |
| Orchestrator | `main.py` (new, top level) | [planned] | Starts everything, registers handlers, owns shutdown |

### `omni/` packaging note

`omni/` is currently the vendor's **flat sample package**: modules import each
other as top-level names (`from yibu_http import …`), it carries its own
`requirements.txt` (`httpx`, `websockets`), its own `.venv`, and expects to be
run from inside the directory. There is no `omni/__init__.py`. Before
`main.py` can `import omni.client`, either add `__init__.py` and switch the
vendor modules to relative imports, or have `client.py` insert `omni/` onto
`sys.path`. The former is preferred; keep the vendor CLIs runnable either way.

## 3. Top-level diagram

```mermaid
flowchart LR
    subgraph HOST["Companion host (laptop / SBC) — all local unless marked"]
        direction LR

        CAM[("Camera 0")]
        MIC[("Microphone")]
        SPK[("Speaker")]

        subgraph CV["computer-vision/"]
            YOLO["YOLO tracker<br/>track_distances.py<br/><b>[exists]</b>"]
            STATE["SceneState<br/>latest frame · detections · timestamp<br/><b>[exists]</b>"]
            PREVIEW["Annotated preview window<br/><b>[exists]</b>"]
        end

        subgraph SP["speech/"]
            VOSK["Vosk STT<br/>grammar-limited, offline<br/><b>[exists]</b>"]
            REC["Question recorder<br/>~3 s raw audio after wake<br/><b>[planned]</b>"]
            SVC["SpeechService<br/>on() / speak() / echo guard<br/><b>[exists]</b>"]
            PIPER["Piper TTS<br/>priority queue, offline<br/><b>[exists]</b>"]
        end

        subgraph OM["omni/"]
            BUILD["Scene request builder<br/>omni/scene.py<br/><b>[planned]</b>"]
            CLIENT["OMNI client<br/>omni/client.py<br/>bytes in · bounded timeout<br/><b>[planned]</b>"]
            FAKE["Fake client<br/>omni/fake.py<br/><b>[planned]</b>"]
            HTTP["yibu_http.py<br/>build_omni_messages · chat_completion<br/>httpx · trust_env=False<br/><b>[exists]</b>"]
            AUDIT["yibu_audit.py<br/>YIBU_API_KEY · append_audit_record<br/><b>[exists]</b>"]
            LEDGER[("artifacts/<br/>yibu_api_calls.jsonl<br/><b>[exists]</b>")]
            CLI["Vendor CLIs<br/>qwen35_omni_flash.py · *_realtime.py · gemini31_flash_live.py<br/><b>[exists] · manual use only</b>"]
        end

        ORCH["Orchestrator main.py<br/><b>[planned]</b>"]
    end

    CLOUD[["yibuapi.com/v1/chat/completions<br/>qwen3.5-omni-flash<br/><b>cloud — opt-in</b>"]]
    CLOUDWS[["yibuapi.com realtime / gemini live WS<br/><b>stretch — not on demo path</b>"]]

    CAM --> YOLO
    YOLO --> PREVIEW
    YOLO -- "every frame" --> STATE

    MIC --> VOSK
    VOSK -- "wake phrase<br/>(e.g. 'describe')" --> SVC
    SVC -- "handler" --> REC
    MIC -. "raw audio<br/>while recording" .-> REC

    REC -- "question audio (WAV bytes)" --> BUILD
    STATE -- "frame + detections<br/>(read once, with age)" --> BUILD
    BUILD --> CLIENT
    CLIENT -- "messages" --> HTTP
    HTTP <-- "HTTPS POST" --> CLOUD
    HTTP -- "every call<br/>(ok or error)" --> AUDIT --> LEDGER
    HTTP -- "answer text" --> CLIENT
    CLIENT -- "text" --> SVC
    FAKE -. "same interface" .-> SVC
    CLI -.-> HTTP
    CLI <-.-> CLOUDWS
    SVC --> PIPER --> SPK

    ORCH -. "starts / stops / wires" .-> YOLO
    ORCH -.-> SVC
    ORCH -.-> CLIENT
```

### Modalities (for the OMNI Live challenge)

| Modality | Where it enters | Where it is used |
| --- | --- | --- |
| Vision / video | Camera → YOLO → `SceneState` | Frame **and** detection list sent to OMNI; YOLO preview shown live |
| Speech / audio | Mic → Vosk (wake) → recorder (question) | Question audio sent to OMNI; answer spoken via Piper or OMNI's own audio |
| Language | OMNI reasoning over audio + image + detection text | Short grounded description returned to the wearer |

## 4. Sequence — "What's in front of me?"

```mermaid
sequenceDiagram
    autonumber
    participant W as Wearer
    participant V as Vosk STT
    participant S as SpeechService
    participant R as Question recorder
    participant ST as SceneState
    participant O as omni.scene + omni.client
    participant H as omni.yibu_http
    participant C as yibuapi (cloud)
    participant P as Piper TTS

    Note over ST: YOLO loop updates ST every frame (independent of this flow)

    W->>V: "describe"  (wake phrase, in grammar)
    V->>S: on_command("describe")
    S->>R: start recording (mic bypasses Vosk)
    W->>R: "what's in front of me?"  (~3 s)
    R->>O: question audio (PCM 16 kHz)
    O->>ST: read(max_age_s) → SceneSnapshot or None
    alt snapshot absent or older than maximum age
        O->>P: speak("Camera view is unavailable", NORMAL)
    else fresh frame
        O->>H: build_omni_messages(text, image, audio, system)
        H->>C: POST /v1/chat/completions (qwen3.5-omni-flash)
        alt reply within omni_timeout_s
            C-->>H: text answer + usage
            H->>H: append_audit_record(ok) → ledger
            H-->>O: text
            O->>S: speak(answer, LOW)
            S->>P: enqueue (HIGH haptic alerts may interrupt)
            P-->>W: "A chair is visible on the left of the camera view."
        else timeout / network error
            H->>H: append_audit_record(ok=false) → ledger
            O->>S: speak("Scene assistant unavailable", NORMAL)
        end
    end
    S->>V: unmute after echo guard
```

Rules baked into this flow:

- The wake phrase is the **only** thing Vosk must recognise; the actual
  question is open-vocabulary and handled by OMNI.
- `SceneState` is read **once** per question, with its age. A frame older
  than the configured maximum is treated as "camera unavailable", never
  described.
- Assistant answers are queued at `Priority.LOW`; any `HIGH` alert from the
  haptic path interrupts them (already supported by `PiperTTS.speak(interrupt=True)`).
- The mic is muted while the speaker plays (existing echo guard), so the
  assistant's own voice cannot re-trigger the wake phrase.

## 5. Threads and blocking

| Thread | Owner | Must never block on |
| --- | --- | --- |
| Main thread | YOLO loop (`model.track(stream=True)` + `cv2.imshow`) | Network, TTS, STT |
| Vosk worker | `VoskSTT._run` | Anything but the audio queue |
| Piper worker | `QueuedTTS._run` | Network |
| Speech dispatcher | `SpeechService._dispatch_loop` runs `speech.on(...)` handlers | Long blocking work -- it delays later commands, though recognition keeps going |
| Sounddevice callbacks | `VoskSTT._audio_callback` / recorder | Anything (real-time audio thread) |
| Assistant thread (per question) | `omni` handler spawned by `SpeechService` dispatch | — this is the only thread allowed to wait on the cloud |

The `speech.on("describe", …)` handler runs on the **speech dispatcher
thread**, not the Vosk worker, so a slow handler no longer freezes
recognition. It should still return promptly — spawn the assistant thread
rather than doing the OMNI call inline — because commands recognized while
a handler is running queue up behind it and are discarded once older than
`max_command_age_seconds` (default 2 s).

## 6. Data passed between components

### `SceneState` (CV → assistant) [exists]

`SceneState` returns a frozen `SceneSnapshot` dataclass, containing frozen
`Detection` dataclasses. Field sketch below (not a serialized transport envelope):

```python
{
  "frame":       np.ndarray,          # original BGR frame, not the annotated one
  "captured_at": float,               # monotonic result read-completion; timing caveat below
  "width": int, "height": int,
  "detections": [
    {"class_id": 42, "class_name": "chair", "conf": 0.71,
     "xyxy": (x0, y0, x1, y1),        # four floats, original-image pixels, top-left origin
     "track_id": 7,                   # or None
     "region": "left"}                # left | center | right, by box-centre x / thirds
  ],
  "source_mode": "live",              # live | replay | simulated
  "sequence": 1                       # +1 per update; first update after reset is 1
}
```

Region thirds are **camera-view** positions ("left of the camera view"), not
wearer-relative directions — the preview is not yet verified for mirroring.
For centre x and width W: left is x < W/3; center is W/3 <= x < 2W/3;
right is x >= 2W/3. Exact boundaries belong to the region on the right.

`update(frame, boxes, names, source_mode)` copies the original BGR pixels into
immutable backing storage and extracts detections using the supplied class map.
The public detection list rejects mutation. Readers get independent array views
over the same read-only pixels; CPython snapshot-reference publication does not
wait for readers. The state retains only its latest publication, with no queue
and no JPEG encoding.

`read(max_age_s=None)` returns the latest snapshot or `None` when empty; with a
limit it also returns `None` if age is strictly greater than the limit. Equality
is fresh. `age_s()` returns the latest age, or `None` when empty. `reset()` clears
evidence and the sequence counter. The tracking loop resets at entry/exit;
automatic mid-stream reconnect detection and tracker reset remain planned.

The clock defaults to `time.monotonic` and can be injected for tests. With the
current minimal tracking integration, `captured_at` is sampled at `update()`
entry, when the loop has read a yielded YOLO result **after inference**. This is
result read-completion, not underlying camera read-completion or exposure time.
Age therefore excludes upstream buffering and inference. Capture timing remains
future work; do not interpret this age as total image latency. Replay uses local
processing time, not the recording's original timestamp.

The assistant should read once with its maximum age and compute text age using
that returned snapshot's `captured_at` and the same clock. A separate `age_s()`
call could observe a newer update. `to_text(detections, age_s)` formats the text
shown below, uses `none` for an empty list, and `age unknown` when age is `None`.
It never interprets empty detections as absence of hazards. The assistant should
recheck that same snapshot's age before sending a delayed request.

### OMNI request (assistant → cloud)

The wire shape is fixed by `yibu_http.build_omni_messages` [exists] and has
been verified against the endpoint for text, text+image, and text+audio
(vendor note, 2026-09-18). Text+image+audio in **one** request is untested.

```python
[
  {"role": "system", "content": "<system prompt>"},
  {"role": "user", "content": [
    {"type": "text",        "text": "Detected (age 80 ms): chair left 0.71, person center 0.82"},
    {"type": "image_url",   "image_url": {"url": "data:image/jpeg;base64,..."}},
    {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64,...", "format": "wav"}},
  ]},
]
```

| Part | Content | Status |
| --- | --- | --- |
| System prompt | "Describe only what is in the camera view, in one short sentence. Use the detection list as ground truth. Never state distances, never say an area is clear, never claim to see behind the wearer. If unsure, say so." | [planned] — passed as `system=` |
| Audio | The recorded question, WAV container, 16 kHz mono PCM | [planned] — `build_omni_messages` currently takes a `Path`; `client.py` must supply a bytes variant (same data-URL encoding) |
| Image | JPEG of the returned `SceneSnapshot.frame` (downscaled, e.g. 640 px wide) | [planned] — same bytes-vs-path caveat |
| Text | `to_text(detections, age_s)` output | [exists] on the CV side |
| Model | `qwen3.5-omni-flash` via `chat_completion(model=…)` | [exists] |
| Timeout | `chat_completion` hardcodes `httpx.Client(timeout=300.0)` | [planned] — `client.py` must pass a bounded timeout (add a parameter rather than editing the vendor default) |
| Ledger | Every call, success or failure, appends to `omni/artifacts/yibu_api_calls.jsonl` with `purpose` | [exists] — set `purpose="sixth_sense_scene"` so demo calls are separable from the vendor examples |

### OMNI response → speech

- Preferred: text answer → `speech.speak(text, Priority.LOW)` (keeps one
  voice, one queue, interruptible by alerts). `chat_completion` already
  returns the flattened text via `extract_text`.
- Alternative: model audio played directly — only available on the Gemini
  Live / Realtime WebSocket paths (`gemini31_flash_live.py --audio-out`),
  which are not on the demo path; must still respect the echo guard and
  `HIGH` interrupts.

## 7. Degraded states

| Condition | Vision preview | Voice commands | Assistant answer |
| --- | --- | --- | --- |
| Normal | live | working | grounded description |
| Network down / API error / timeout | live | working (Vosk + Piper are offline) | "Scene assistant unavailable" |
| Camera disconnected or frame stale | frozen → must be flagged, not shown as current | working | "Camera view is unavailable" |
| No detections on a fresh frame | live | working | OMNI may still describe the image; the prompt forbids "nothing is there / area is clear" |
| `OMNI_FAKE=1` (demo/test switch) | live | working | canned answer from `omni/fake.py`, no network |
| `YIBU_API_KEY` unset | live | working | `require_env_api_key` raises `SystemExit` — `client.py` must catch it at construction and report "assistant not configured" instead of exiting the process |

Demo moment: pull the network mid-run → preview and voice commands keep
working, assistant says it's unavailable, haptics (separate path) continue.

## 8. Changes required in existing code

| File | Change | Why |
| --- | --- | --- |
| `computer-vision/track_distances.py` | [exists] `main(state: SceneState \| None = None)` publishes original frame + all detections before plotting; source mode derives from `SOURCE`; reset at entry and in `finally` | Consumers share the latest evidence without calling OpenCV/YOLO; result-receipt timing limitation documented in §6 |
| `speech/stt.py` | Add a "capture raw audio for N seconds, bypassing the recogniser" mode, or expose the mic stream | Vosk cannot hear open-vocabulary questions |
| `configs/grammar.json` / `configs/speech.json` | Add the chosen wake phrase to the grammar and set `wake_phrase` | Only grammar entries are recognised; the wake phrase must be in the grammar |
| `requirements.txt` | Merge `omni/requirements.txt` (`httpx>=0.27,<1`, `websockets>=15,<17`) into the top-level file so one venv runs the whole host | Today `omni/` has its own `.venv` |
| `omni/` | Add `__init__.py`; switch `from yibu_http import …` to relative imports (or `sys.path` shim in `client.py`) | `main.py` must be able to `import omni.client` |
| `omni/yibu_http.py` | Add optional `timeout` parameter to `chat_completion` (default stays 300 s) and a bytes-accepting path in `build_omni_messages` | Vendor code assumes files and unbounded time |
| env | `YIBU_API_KEY` from environment only (already enforced by `yibu_audit.require_env_api_key`) | Never in code or logs |
| `.gitignore` | Decide whether `omni/artifacts/*.jsonl` stays committed — it records key **suffixes** and per-call latency | Currently committed with 3 vendor-example calls |
| New in `omni/` | `client.py`, `scene.py`, `fake.py` | The assistant layer |
| New `main.py` | Start YOLO, configure `speech`, register `describe` handler, clean shutdown | One orchestrator instead of three separate scripts |

## 9. Configuration knobs (single place, e.g. `configs/assistant.json`)

| Key | Provisional default | Note |
| --- | --- | --- |
| `wake_phrase` | `"describe"` | Must be in `grammar.json` |
| `question_seconds` | `3.0` | Recording window after wake |
| `max_scene_age_ms` | `500` | Older frame ⇒ "camera unavailable"; **measure** before tuning |
| `omni_model` | `qwen3.5-omni-flash` | Request/response over `yibu_http.chat_completion`; switch to `qwen3.5-omni-plus-realtime` / `gemini-3.1-flash-live-preview` only after this works |
| `omni_base_url` | `https://yibuapi.com/v1` | `yibu_http.DEFAULT_BASE_URL` |
| `omni_timeout_s` | `5.0` | Hard cap passed to `httpx.Client`; answer target is ≤ 3 s. Vendor default is 300 s |
| `omni_purpose` | `sixth_sense_scene` | Ledger tag so demo calls can be summarised separately from vendor examples |
| `audit_log` | `omni/artifacts/yibu_api_calls.jsonl` | Or `YIBU_AUDIT_LOG` env var; `summarize_usage.py` reads it |
| `frame_jpeg_width` | `640` | Upload size vs latency |
| `cloud_enabled` | `false` | Must be explicitly turned on; state shown in preview title/log |

## 10. Open decisions

| Decision | Options | Recommendation |
| --- | --- | --- |
| Wake phrase | reuse `describe` vs new "hey sixth sense" | Reuse `describe` for the hackathon — already works |
| Answer voice | Piper (local) vs OMNI audio | Piper — one queue, offline fallback, interruptible |
| Model | Qwen flash (request/response) vs Qwen realtime / Gemini Live (streaming) | Flash first; streaming is a stretch goal. Ledger evidence (text-only prompts, one call each, 2026-09-19): `qwen3.5-omni-flash` HTTP ≈ 0.89–0.99 s, `gemini-3.1-flash-live-preview` WS ≈ 1.90 s. Multimodal payload latency is **unmeasured** |
| Keep pixel-distance overlay? | yes / no | Keep for preview; **do not** send pixel distances to OMNI — they are not ranges |
| Depth estimation | none / add a monocular model | None for the hackathon; camera-to-object range is not available from this pipeline |

## 11. What this architecture does **not** claim

- YOLO does not measure distance from the camera to objects. The on-screen
  numbers are pixel gaps between two objects.
- The assistant can only describe the camera's field of view — never "around
  me" in the 360° sense, never behind the wearer.
- An empty detection list or an unavailable frame is never "the area is clear".
- Latency (wake → first spoken word) is a goal of ≤ 3 s, **unmeasured** until
  the `omni/client.py` + `scene.py` layer exists. The only measured numbers
  are text-only round trips from the vendor examples (~1 s HTTP, ~1.9 s
  Gemini Live); they exclude recording, JPEG/WAV encoding, upload of a
  640 px frame + 3 s of audio, and Piper synthesis.
- The `omni/` ledger records token counts and latency, not correctness. A
  successful call proves the endpoint answered, not that the answer was
  grounded in the frame.
