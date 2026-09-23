#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${ASTK_STUDIO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TOKEN="${ASTK_CLOUDFLARE_TUNNEL_TOKEN:-}"
TOKEN_FILE="${ASTK_CLOUDFLARE_TUNNEL_TOKEN_FILE:-$HOME/.config/astk/cloudflare-tunnel.token}"
PUBLIC_URL="${ASTK_PUBLIC_BACKEND_URL:-}"
LOG_FILE="${ASTK_NAMED_TUNNEL_LOG:-$APP_DIR/data/cloudflared-named.log}"
PID_FILE="${ASTK_NAMED_TUNNEL_PID:-$APP_DIR/data/cloudflared-named.pid}"
URL_FILE="${ASTK_NAMED_TUNNEL_URL_FILE:-$APP_DIR/data/cloudflared-named.url}"
CLOUDFLARED="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"
HEALTH_TIMEOUT="${ASTK_NAMED_TUNNEL_HEALTH_TIMEOUT:-45}"
VERIFY_PUBLIC="${ASTK_NAMED_TUNNEL_VERIFY_PUBLIC:-0}"

mkdir -p "$(dirname "$LOG_FILE")"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Named tunnel already running with PID $(cat "$PID_FILE")"
  exit 0
fi

if [[ -z "$TOKEN" && -f "$TOKEN_FILE" ]]; then
  TOKEN="$(head -n 1 "$TOKEN_FILE" | tr -d '\r\n')"
fi

[[ -n "$TOKEN" ]] || {
  echo "ASTK_CLOUDFLARE_TUNNEL_TOKEN or $TOKEN_FILE is required." >&2
  exit 2
}
[[ -x "$CLOUDFLARED" ]] || {
  echo "cloudflared is not executable at $CLOUDFLARED" >&2
  exit 2
}

if [[ -n "$PUBLIC_URL" && "$VERIFY_PUBLIC" == "1" ]]; then
  PUBLIC_URL="${PUBLIC_URL%/}"
  printf '%s\n' "$PUBLIC_URL" >"$URL_FILE"
fi

nohup env TUNNEL_TOKEN="$TOKEN" "$CLOUDFLARED" \
  tunnel --no-autoupdate --metrics 127.0.0.1:20242 run \
  >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 30); do
  if grep -q 'Registered tunnel connection' "$LOG_FILE" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "named tunnel exited before connecting" >&2
    tail -n 80 "$LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

if ! grep -q 'Registered tunnel connection' "$LOG_FILE" 2>/dev/null; then
  echo "named tunnel did not register within 30 seconds" >&2
  tail -n 80 "$LOG_FILE" >&2
  exit 1
fi

if [[ -n "$PUBLIC_URL" ]]; then
  for _ in $(seq 1 "$HEALTH_TIMEOUT"); do
    if curl -fsS --max-time 10 "$PUBLIC_URL/api/health" >/dev/null 2>&1; then
      echo "$PUBLIC_URL"
      exit 0
    fi
    sleep 1
  done
  echo "named tunnel connected, but $PUBLIC_URL/api/health did not become healthy" >&2
  exit 1
fi

if [[ -n "$PUBLIC_URL" ]]; then
  echo "$PUBLIC_URL"
else
  echo "Named tunnel connected with PID $(cat "$PID_FILE")."
fi
