#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${ASTK_STUDIO_DIR:-$HOME/astk-studio}"
CONDA_ENV="${ASTK_CONDA_ENV:-astk}"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"

source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"
cd "$APP_DIR"

export ASTK_HOST="${ASTK_HOST:-127.0.0.1}"
export ASTK_PORT="${ASTK_PORT:-4173}"
export ASTK_TRUST_PROXY="${ASTK_TRUST_PROXY:-0}"
export ASTK_STUDIO_DIR="$APP_DIR"
export ASTK_DATA_ROOT="${ASTK_DATA_ROOT:-$HOME/astk-web/data}"
export ASTK_EXECUTION_MODE="command"
export ASTK_ENGINE="${ASTK_ENGINE:-auto}"
export ASTK_RUNNER_COMMAND="bash $APP_DIR/scripts/run-astk-job.sh {job_dir}"
export ASTK_MM10_GTF="${ASTK_MM10_GTF:-/home/yushiye/project/gencode.vM25.annotation.gtf}"
export ASTK_REQUIRE_EQUAL_REPLICATES="${ASTK_REQUIRE_EQUAL_REPLICATES:-1}"
export ASTK_WORKERS="${ASTK_WORKERS:-3}"
export ASTK_MAX_CONCURRENT_JOBS="${ASTK_MAX_CONCURRENT_JOBS:-3}"
export ASTK_SEQUENCE_WORKERS="${ASTK_SEQUENCE_WORKERS:-8}"
export ASTK_JOB_TIMEOUT="${ASTK_JOB_TIMEOUT:-21600}"
export ASTK_RETENTION_DAYS="${ASTK_RETENTION_DAYS:-1}"
export PYTHONPATH="$APP_DIR"
mkdir -p "$ASTK_DATA_ROOT/jobs"

exec python3 backend/server.py
