#!/usr/bin/env bash
set -euo pipefail

# Diagnostic fallback for networks that block cloudflared's UDP/TCP port 7844.
# Prefer a fixed domain with Caddy or Nginx for production.

APP_DIR="${ASTK_STUDIO_DIR:-$HOME/astk-studio}"
LOG_FILE="${ASTK_TUNNEL_LOG:-$APP_DIR/data/cloudflared-http2.log}"
PID_FILE="${ASTK_TUNNEL_PID:-$APP_DIR/data/cloudflared-http2.pid}"
URL_FILE="${ASTK_TUNNEL_URL_FILE:-$APP_DIR/data/cloudflared-http2.url}"
TARGET_URL="${ASTK_TUNNEL_URL:-http://127.0.0.1:4173}"
CLOUDFLARED="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"

mkdir -p "$(dirname "$LOG_FILE")"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "HTTP/2 tunnel already running with PID $(cat "$PID_FILE")"
  exit 0
fi

nohup "$CLOUDFLARED" tunnel --no-autoupdate --protocol http2 --url "$TARGET_URL" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 45); do
  if grep -q 'https://[-a-z0-9]*\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null; then
    url="$(grep -o 'https://[-a-z0-9]*\.trycloudflare\.com' "$LOG_FILE" | head -n 1)"
    printf '%s\n' "$url" >"$URL_FILE"
    printf '%s\n' "$url"
    exit 0
  fi
  sleep 1
done

echo "HTTP/2 tunnel did not publish a URL within 45 seconds" >&2
tail -n 60 "$LOG_FILE" >&2
exit 1
