#!/usr/bin/env bash
set -euo pipefail

cd /home/rin/onset-and-frames/src/onsets-and-frames
export CUDA_VISIBLE_DEVICES=0

MAESTRO_PATH=${MAESTRO_PATH:-/mlnas/rin/datasets/MAESTRO}
MAESTRO_METADATA_FILENAME=${MAESTRO_METADATA_FILENAME:-maestro-v3.0.0.json}

exec taskset -c 0-39 python train.py with train_on=MAESTRO \
  "maestro_path=$MAESTRO_PATH" \
  "maestro_metadata_filename=$MAESTRO_METADATA_FILENAME" "$@"
