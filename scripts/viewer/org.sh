#!/usr/bin/env bash
set -euo pipefail

# Viewer専用ポートを使う。既存Composeで公開済みの9875番には触れない。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN=${PYTHON_BIN:-"$REPO_ROOT/.venv/bin/python"}
export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/src/onsets-and-frames${PYTHONPATH:+:$PYTHONPATH}"

cd "$REPO_ROOT"
exec "$PYTHON_BIN" -m viewer.server --host 0.0.0.0 --port "${VIEWER_PORT:-8765}"
