#!/usr/bin/env bash
# CPU-only install: venv, CPU torch (no CUDA wheels), requirements, MediaPipe pose models, data bundle.
# Safe to re-run: each step skips what is already there.
# Run:  bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
RELEASE=https://github.com/seraphimlabs-dev/brodie-starter/releases/download/data-2026-10-09
PARTS=(part1_models_recordings part3_bank_puck)

command -v uv >/dev/null || { echo "uv not found: install it first (https://docs.astral.sh/uv/)"; exit 1; }

echo "[1/4] venv"
[ -x "$PY" ] || uv venv --python 3.12 .venv

echo "[2/4] python packages (torch from the CPU index)"
uv pip install --python "$PY" torch torchvision --index-url https://download.pytorch.org/whl/cpu
uv pip install --python "$PY" -r requirements.txt

echo "[3/4] MediaPipe pose models"
mkdir -p models
for m in lite full heavy; do
    f=models/pose_landmarker_$m.task
    [ -s "$f" ] || curl -sSfL -o "$f" "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_$m/float16/latest/pose_landmarker_$m.task"
done

echo "[4/4] data bundle"
if [ -f data/models/clf_pose.pt ] && [ -f data/cues_audio_gemini/manifest.json ]; then
    echo "  already unpacked"
else
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    for p in "${PARTS[@]}"; do
        t=rtcoach_starter_${p}_2026-10-09.tgz
        echo "  $t"
        curl -sSfL -o "$tmp/$t" "$RELEASE/$t"
        tar xzf "$tmp/$t"
    done
fi

ls data/models/clf_pose.pt data/models/trigger_lr.json data/cues_audio_gemini/manifest.json models/pose_landmarker_full.task >/dev/null
echo "done. check it with:"
echo "  $PY -m facetime.replay_local --video data/tmp/mac_handoff/crops/run3.mp4 --plan \"squats:10,pushups:8,jumping jacks:20,lunges:10\" --fast --events data/tmp/run3.events.jsonl"
