#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${ASTK_STUDIO_DIR:-$HOME/astk-studio}"
LOG_FILE="${ASTK_TUNNEL_LOG:-$APP_DIR/data/cloudflared.log}"
PID_FILE="${ASTK_TUNNEL_PID:-$APP_DIR/data/cloudflared.pid}"
TARGET_URL="${ASTK_TUNNEL_URL:-http://127.0.0.1:4173}"
CLOUDFLARED="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"

mkdir -p "$(dirname "$LOG_FILE")"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Tunnel already running with PID $(cat "$PID_FILE")"
  exit 0
fi

nohup "$CLOUDFLARED" tunnel --no-autoupdate --url "$TARGET_URL" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 30); do
  if grep -q 'https://[-a-z0-9]*\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null; then
    url="$(grep -o 'https://[-a-z0-9]*\.trycloudflare\.com' "$LOG_FILE" | head -n 1)"
    printf '%s\n' "$url" >"${ASTK_TUNNEL_URL_FILE:-$APP_DIR/data/cloudflared.url}"
    printf '%s\n' "$url"
    exit 0
  fi
  sleep 1
done

echo "Tunnel did not publish a URL within 30 seconds" >&2
tail -n 40 "$LOG_FILE" >&2
exit 1
