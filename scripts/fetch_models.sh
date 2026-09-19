#!/usr/bin/env bash
# Downloads a small Piper voice and the small Vosk English model into
# speech/models/. Re-run safely -- skips files that already exist.
set -euo pipefail

MODELS_DIR="$(dirname "$0")/../speech/models"
mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

# Piper voice (medium-quality US English, ~60MB) -- swap for a smaller
# "low" quality voice if you need faster synthesis on constrained hardware.
if [ ! -f en_US-lessac-medium.onnx ]; then
  curl -L -o en_US-lessac-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
  curl -L -o en_US-lessac-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
fi

# Vosk small English model (~40MB) -- plenty for grammar-limited recognition.
if [ ! -d vosk-model-small-en-us-0.15 ]; then
  curl -L -o vosk-small.zip \
    https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  unzip vosk-small.zip
  rm vosk-small.zip
fi

echo "Models ready in $MODELS_DIR"