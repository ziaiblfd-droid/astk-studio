#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${ASTK_STUDIO_DIR:-$HOME/astk-studio}"
START_SCRIPT="$APP_DIR/scripts/start-public-tunnel.sh"
LOG_FILE="${ASTK_TUNNEL_LOG:-$APP_DIR/data/cloudflared.log}"
PID_FILE="${ASTK_TUNNEL_PID:-$APP_DIR/data/cloudflared.pid}"
URL_FILE="${ASTK_TUNNEL_URL_FILE:-$APP_DIR/data/cloudflared.url}"
CHECK_INTERVAL="${ASTK_TUNNEL_CHECK_INTERVAL:-30}"

mkdir -p "$(dirname "$LOG_FILE")"

while true; do
  url=""
  if [[ -f "$URL_FILE" ]]; then
    url="$(head -n 1 "$URL_FILE")"
  fi

  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null && [[ -n "$url" ]]; then
    if curl -fsS --max-time 10 "$url/api/health" >/dev/null 2>&1; then
      sleep "$CHECK_INTERVAL"
      continue
    fi
  fi

  if [[ -f "$PID_FILE" ]]; then
    old_pid="$(cat "$PID_FILE")"
    kill "$old_pid" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi

  new_url="$("$START_SCRIPT" 2>>"$LOG_FILE" || true)"
  if [[ -n "$new_url" ]]; then
    printf '%s\n' "$new_url" >"$URL_FILE"
    printf '[%s] public tunnel: %s\n' "$(date -u +%FT%TZ)" "$new_url" >>"$LOG_FILE"
  fi

  sleep "$CHECK_INTERVAL"
done
