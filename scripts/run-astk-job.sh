#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: run-astk-job.sh JOB_DIR" >&2
  exit 2
fi

JOB_DIR="$(cd "$1" && pwd)"
APP_DIR="${ASTK_STUDIO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$APP_DIR"
# ASTK event construction traverses unordered collections. Fix the interpreter
# seed before Python starts so an identical job produces a stable event catalog.
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
python3 -m backend.execute_suppa "$JOB_DIR"
