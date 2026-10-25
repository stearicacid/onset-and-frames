#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/eval/org.sh MODEL_FILE [DATASET [GROUP]] [evaluate.py options...]" >&2
  echo "Example: bash scripts/eval/org.sh src/onsets-and-frames/runs/transcriber-261023-112532/model-180000.pt" >&2
  echo "Example: bash scripts/eval/org.sh MODEL_FILE MAPS" >&2
  exit 2
fi

MODEL_FILE=$1
shift
if [[ "$MODEL_FILE" != /* ]]; then
  MODEL_FILE="$REPO_ROOT/$MODEL_FILE"
fi
if [[ ! -f "$MODEL_FILE" ]]; then
  echo "Model checkpoint not found: $MODEL_FILE" >&2
  exit 2
fi

DATASET=MAESTRO
if [[ $# -gt 0 && "$1" != --* ]]; then
  DATASET=$1
  shift
fi

DATASET_GROUP=
if [[ "$DATASET" == "MAESTRO" ]]; then
  DATASET_GROUP=test
  if [[ $# -gt 0 && "$1" != --* ]]; then
    DATASET_GROUP=$1
    shift
  fi
elif [[ $# -gt 0 && "$1" != --* ]]; then
  DATASET_GROUP=$1
  shift
fi

MAESTRO_PATH=${MAESTRO_PATH:-/mlnas/rin/datasets/MAESTRO}
MAESTRO_METADATA_FILENAME=${MAESTRO_METADATA_FILENAME:-maestro-v3.0.0.json}
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-2}
CPU_CORES=${CPU_CORES:-0-39}

cd "$REPO_ROOT/src/onsets-and-frames"

EVAL_ARGS=("$MODEL_FILE" "$DATASET")
if [[ -n "$DATASET_GROUP" ]]; then
  EVAL_ARGS+=("$DATASET_GROUP")
fi
EVAL_ARGS+=(--maestro-path "$MAESTRO_PATH"
  --maestro-metadata-filename "$MAESTRO_METADATA_FILENAME" "$@")

exec taskset -c "$CPU_CORES" python evaluate.py "${EVAL_ARGS[@]}"
