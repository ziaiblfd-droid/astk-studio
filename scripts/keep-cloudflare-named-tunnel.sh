#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${ASTK_STUDIO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PUBLIC_URL="${ASTK_PUBLIC_BACKEND_URL:-}"
PID_FILE="${ASTK_NAMED_TUNNEL_PID:-$APP_DIR/data/cloudflared-named.pid}"
CHECK_INTERVAL="${ASTK_NAMED_TUNNEL_CHECK_INTERVAL:-30}"
START_SCRIPT="${ASTK_NAMED_TUNNEL_START_SCRIPT:-$APP_DIR/scripts/start-cloudflare-named-tunnel.sh}"
READY_URL="${ASTK_NAMED_TUNNEL_READY_URL:-http://127.0.0.1:20242/ready}"
MAX_READY_FAILURES="${ASTK_NAMED_TUNNEL_READY_FAILURES:-3}"

[[ -n "$PUBLIC_URL" ]] || {
  echo "ASTK_PUBLIC_BACKEND_URL is required." >&2
  exit 2
}
[[ -f "$START_SCRIPT" ]] || {
  echo "start script is missing: $START_SCRIPT" >&2
  exit 2
}

ready_failures=0
while true; do
  healthy=0
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    if curl -fsS --max-time 5 "$READY_URL" >/dev/null 2>&1; then
      healthy=1
    fi
  fi

  if [[ "$healthy" -eq 1 ]]; then
    ready_failures=0
    sleep "$CHECK_INTERVAL"
    continue
  fi

  ready_failures=$((ready_failures + 1))
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null && \
     [[ "$ready_failures" -lt "$MAX_READY_FAILURES" ]]; then
    sleep "$CHECK_INTERVAL"
    continue
  fi
  ready_failures=0
  if [[ -f "$PID_FILE" ]]; then
    old_pid="$(cat "$PID_FILE")"
    kill "$old_pid" 2>/dev/null || true
    sleep 2
  fi

  bash "$START_SCRIPT" || true
  sleep "$CHECK_INTERVAL"
done
