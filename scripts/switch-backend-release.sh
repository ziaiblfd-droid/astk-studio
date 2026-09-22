#!/usr/bin/env bash
set -euo pipefail

RELEASE_DIR="${ASTK_RELEASE_DIR:-}"
PORT="${ASTK_PORT:-4173}"
STATE_ROOT="${ASTK_DEPLOY_STATE_ROOT:-$HOME/astk-web/deployments}"
STOP_TIMEOUT="${ASTK_STOP_TIMEOUT:-20}"
HEALTH_TIMEOUT="${ASTK_HEALTH_TIMEOUT:-45}"
ROLLBACK_ON_FAILURE="${ASTK_ROLLBACK_ON_FAILURE:-1}"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
CONDA_BIN="${ASTK_CONDA_BIN:-$CONDA_BASE/envs/astk/bin}"
ASTK_MM10_GTF="${ASTK_MM10_GTF:-/home/yushiye/project/gencode.vM25.annotation.gtf}"
ASTK_MM10_FASTA="${ASTK_MM10_FASTA:-/home/yushiye/project/GRCm38.primary_assembly.genome.fa}"

die() {
  echo "error: $*" >&2
  exit 1
}

if [[ -z "$RELEASE_DIR" ]]; then
  echo "usage: ASTK_RELEASE_DIR=/path/to/release $0" >&2
  exit 2
fi

RELEASE_DIR="$(cd "$RELEASE_DIR" && pwd)"
[[ -f "$RELEASE_DIR/backend/server.py" ]] || die "backend/server.py is missing from $RELEASE_DIR"
[[ -f "$RELEASE_DIR/scripts/run-conda-server.sh" ]] || die "scripts/run-conda-server.sh is missing from $RELEASE_DIR"
[[ -f "$RELEASE_DIR/scripts/run-astk-job.sh" ]] || die "scripts/run-astk-job.sh is missing from $RELEASE_DIR"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "ASTK_PORT must be numeric"

mkdir -p "$STATE_ROOT"
STATE_DIR="$(mktemp -d "$STATE_ROOT/switch-${PORT}-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
printf '%s\n' "$RELEASE_DIR" >"$STATE_DIR/release-dir"
printf '%s\n' "$PORT" >"$STATE_DIR/port"

listener_pid() {
  local port="$1"
  ss -ltnpH "sport = :$port" 2>/dev/null \
    | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
    | head -n 1
}

stop_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  kill -TERM "$pid" 2>/dev/null || return 0
  for _ in $(seq 1 "$STOP_TIMEOUT"); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_health() {
  local pid="$1"
  for _ in $(seq 1 "$HEALTH_TIMEOUT"); do
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    if curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_backend() {
  local app_dir="$1"
  local log_file="$2"
  local pid_file="$3"

  mkdir -p "$(dirname "$log_file")"
  (
    cd "$app_dir"
    export PATH="$CONDA_BIN:$PATH"
    export ASTK_STUDIO_DIR="$app_dir"
    export ASTK_DATA_ROOT="${ASTK_DATA_ROOT:-$HOME/astk-web/data}"
    export ASTK_PORT="$PORT"
    export ASTK_HOST="127.0.0.1"
    export ASTK_EXECUTION_MODE="command"
    export ASTK_ENGINE="${ASTK_ENGINE:-auto}"
    export ASTK_RUNNER_COMMAND="bash $app_dir/scripts/run-astk-job.sh {job_dir}"
    export ASTK_MM10_GTF
    export ASTK_MM10_FASTA
    export ASTK_TRUST_PROXY="1"
    export ASTK_REQUIRE_EQUAL_REPLICATES="0"
    export ASTK_WORKERS="10"
    export ASTK_MAX_CONCURRENT_JOBS="10"
    export ASTK_JOB_TIMEOUT="21600"
    export ASTK_MAX_UPLOAD_BYTES="536870912"
    export ASTK_RETENTION_DAYS="1"
    export ASTK_CLEANUP_INTERVAL="3600"
    export PYTHONPATH="$app_dir"
    mkdir -p "$ASTK_DATA_ROOT/jobs"
    unset ASTK_RECOVER_JOBS
    unset ASTK_RELEASE_DIR
    nohup bash "$app_dir/scripts/run-conda-server.sh" >>"$log_file" 2>&1 &
    printf '%s\n' "$!" >"$pid_file"
  )
}

old_pid="$(listener_pid "$PORT" || true)"
old_cwd=""
old_log=""
if [[ -n "$old_pid" ]]; then
  old_cwd="$(readlink -f "/proc/$old_pid/cwd" 2>/dev/null || true)"
  old_log="$(readlink -f "/proc/$old_pid/fd/1" 2>/dev/null || true)"
  printf '%s\n' "$old_pid" >"$STATE_DIR/previous.pid"
  printf '%s\n' "$old_cwd" >"$STATE_DIR/previous.cwd"
  printf '%s\n' "$old_log" >"$STATE_DIR/previous.log"
  tr '\0' '\n' <"/proc/$old_pid/environ" | grep '^ASTK_' | sort >"$STATE_DIR/previous.env" || true
  echo "Stopping PID $old_pid from $old_cwd"
  stop_pid "$old_pid" || die "PID $old_pid did not stop within ${STOP_TIMEOUT}s"
fi

if [[ -n "$(listener_pid "$PORT" || true)" ]]; then
  die "port $PORT is still occupied after stopping the previous listener"
fi

new_log="${ASTK_SERVICE_LOG:-$RELEASE_DIR/data/formal-${PORT}.log}"
new_pid_file="$STATE_DIR/target.pid"
start_backend "$RELEASE_DIR" "$new_log" "$new_pid_file"
new_pid="$(cat "$new_pid_file")"
printf '%s\n' "$new_pid" >"$STATE_DIR/target.pid"

if wait_for_health "$new_pid"; then
  echo "Switched port $PORT to $RELEASE_DIR"
  echo "PID: $new_pid"
  echo "Log: $new_log"
  echo "State: $STATE_DIR"
  curl -fsS --max-time 10 "http://127.0.0.1:$PORT/api/health"
  echo
  exit 0
fi

echo "New release failed its health check on port $PORT." >&2
tail -n 80 "$new_log" >&2 || true
stop_pid "$new_pid" || true

if [[ "$ROLLBACK_ON_FAILURE" != "1" || -z "$old_pid" || -z "$old_cwd" ]]; then
  die "no automatic rollback was possible; deployment state is $STATE_DIR"
fi

[[ -f "$old_cwd/scripts/run-conda-server.sh" ]] || die "previous release cannot be restarted automatically; state is $STATE_DIR"
rollback_pid_file="$STATE_DIR/rollback.pid"
rollback_log="${old_log:-$old_cwd/data/server.log}"
start_backend "$old_cwd" "$rollback_log" "$rollback_pid_file"
rollback_pid="$(cat "$rollback_pid_file")"

if wait_for_health "$rollback_pid"; then
  echo "Rolled back port $PORT to $old_cwd" >&2
  echo "Rollback PID: $rollback_pid" >&2
  echo "State: $STATE_DIR" >&2
  exit 1
fi

die "rollback also failed; deployment state is $STATE_DIR"
