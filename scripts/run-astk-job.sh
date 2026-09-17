#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: run-astk-job.sh JOB_DIR" >&2
  exit 2
fi

JOB_DIR="$(cd "$1" && pwd)"
APP_DIR="${ASTK_STUDIO_DIR:-$HOME/astk-studio}"

cd "$APP_DIR"
python3 -m backend.execute_astk "$JOB_DIR"
