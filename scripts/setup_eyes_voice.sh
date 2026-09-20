#!/usr/bin/env bash
# One-shot setup for the Eyes & Voice companion host (Linux Pi or dev
# laptop): creates a venv, installs Python dependencies, and fetches the
# speech models. Safe to re-run. Does NOT touch the QNX Spidey Sense Pi --
# that device runs firmware/ (C, built with the QNX SDP), never Python.
# See docs/DEPLOYMENT.md for the full two-device deployment guide.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${SIXTH_SENSE_VENV:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "== sixth-sense: Eyes & Voice setup =="
echo "Repository root: $REPO_ROOT"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN not found on PATH. Install Python 3.11+ first." >&2
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "Using $PYTHON_BIN ($PY_VERSION)"

if [ ! -d "$VENV_DIR" ]; then
  echo "-- creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "-- reusing existing virtual environment at $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "-- upgrading pip"
python -m pip install --upgrade pip

echo "-- installing requirements.txt"
python -m pip install -r requirements.txt

echo "-- fetching speech models (Piper + Vosk, ~100 MB total; skips files that already exist)"
bash scripts/fetch_models.sh

echo
echo "== dependency-only checks (no camera/mic opened) =="
python - <<'PYEOF'
import importlib
import sys

# Import-only checks: confirms the packages installed correctly for this
# interpreter. This does NOT open a camera or microphone and does NOT
# prove real hardware (camera index 0, an input device, a speaker) is
# present -- that still needs a manual check on the actual device.
modules = ["cv2", "ultralytics", "numpy", "sounddevice", "vosk", "httpx", "websockets"]
missing = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append((name, str(exc)))

if missing:
    print("MISSING/BROKEN:")
    for name, err in missing:
        print(f"  {name}: {err}")
    sys.exit(1)
print("All required Python packages import cleanly.")
PYEOF

echo
echo "-- checking for piper-tts / vosk executables/models that main.py expects"
[ -f "speech/models/en_US-lessac-medium.onnx" ] && echo "  Piper voice: present" || echo "  Piper voice: MISSING"
[ -d "speech/models/vosk-model-small-en-us-0.15" ] && echo "  Vosk model: present" || echo "  Vosk model: MISSING"
[ -f "computer-vision/yolo26n-objv1-150.pt" ] && echo "  YOLO checkpoint: present" || echo "  YOLO checkpoint: MISSING (should be committed to the repo)"

cat <<EOF

== Setup complete ==
Activate this environment in new shells with:
    source $VENV_DIR/bin/activate

Run the demo (see README.md "Run it" and docs/DEPLOYMENT.md for details):
    python main.py                # cloud off
    OMNI_FAKE=1 python main.py    # canned assistant answers, real camera/mic/speaker

Run the offline test suite:
    env -u YIBU_API_KEY python -m pytest tests omni/tests computer-vision/Tests -q

Camera, microphone, and speaker availability were NOT verified by this
script -- confirm those on the actual device (README.md "Getting started",
scripts/check_capture.py for the microphone).
EOF
