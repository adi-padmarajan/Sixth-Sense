# yibuapi Sample Code Release Package

This package lives at `omni/` inside the sixth-sense repo and is imported as the `omni` package. Run every command below from the repository root. It provides the following runnable Python samples (`python -m omni.<name>`):

- `qwen35_omni_flash.py`: `qwen3.5-omni-flash` HTTP Chat Completions
- `qwen35_omni_plus.py`: `qwen3.5-omni-plus` HTTP Chat Completions
- `qwen35_omni_plus_realtime.py`: `qwen3.5-omni-plus-realtime` WebSocket
- `gemini31_flash_live.py`: `gemini-3.1-flash-live-preview` Gemini Live WebSocket
- `chat_completions_generic.py`: generic OpenAI-compatible Chat Completions
- `yibu_audit.py`: append-per-call token auditing
- `summarize_usage.py`: JSON/CSV token usage summarization

See the `README.md` inside the package for full installation, invocation, no-proxy setup, and token statistics instructions.

## Security Boundaries

- The package contains no API key; at runtime it only reads the `YIBU_API_KEY` environment variable.
- HTTP explicitly sets `trust_env=False`; WebSocket explicitly sets `proxy=None`.
- Does not include the dev machine's virtual environment, caches, real call ledgers, key suffixes, internal source paths, or historical forecast data.
- Credential values in `.env.example` are empty.

## Verification Status

As of 2026-09-18, minimal real online calls were completed for all five official entry points, each successfully returning content and usage. Historical transient failures and specific call ledgers are not included in the shared package. The package also includes key-free unit tests.

From the repo root, in the project venv:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s omni/tests -t . -v
```
