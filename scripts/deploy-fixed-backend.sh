#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${ASTK_STUDIO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOMAIN="${ASTK_DOMAIN:-}"
EMAIL="${ASTK_TLS_EMAIL:-}"
ENV_FILE="$APP_DIR/.env"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ASTK currently requires x86_64 because huangshing/astk is amd64-only." >&2
  echo "Use an x86_64 VM, or build and validate an ARM64 ASTK image first." >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || {
  echo "docker is required. Install Docker Engine and the Compose plugin first." >&2
  exit 2
}
docker compose version >/dev/null 2>&1 || {
  echo "docker compose plugin is required." >&2
  exit 2
}

if [[ -z "$DOMAIN" ]]; then
  echo "ASTK_DOMAIN is required, for example ASTK_DOMAIN=astk.example.com" >&2
  exit 2
fi

if [[ -z "$EMAIL" ]]; then
  echo "ASTK_TLS_EMAIL is required for the Caddy certificate." >&2
  exit 2
fi

if [[ ! -f "$APP_DIR/references/mm10/gencode.vM25.annotation.gtf" ]] && \
   [[ ! -f "$APP_DIR/references/hg38/gencode.v44.annotation.gtf" ]]; then
  echo "No supported reference annotation is available." >&2
  echo "Place at least one of the required GTFs under references/ before starting jobs." >&2
  exit 2
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$APP_DIR/backend/config.example.env" "$ENV_FILE"
fi
if ! grep -q '^ASTK_EXECUTION_MODE=' "$ENV_FILE"; then
  printf '\nASTK_EXECUTION_MODE=command\n' >>"$ENV_FILE"
fi
if ! grep -q '^ASTK_TRUST_PROXY=' "$ENV_FILE"; then
  printf 'ASTK_TRUST_PROXY=1\n' >>"$ENV_FILE"
fi

cd "$APP_DIR"
docker compose up --build -d

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:4173/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS --max-time 10 http://127.0.0.1:4173/api/health
echo

CADDYFILE="$APP_DIR/Caddyfile"
if [[ -f "$CADDYFILE" ]] && ! grep -qF "$DOMAIN" "$CADDYFILE"; then
  echo "Existing $CADDYFILE does not contain ASTK_DOMAIN=$DOMAIN." >&2
  echo "Move it aside or update it before deploying." >&2
  exit 2
fi
if [[ ! -f "$CADDYFILE" ]]; then
  cat >"$CADDYFILE" <<EOF
$DOMAIN {
    encode zstd gzip
    request_body {
        max_size 512MB
    }
    reverse_proxy 127.0.0.1:4173 {
        transport http {
            read_timeout 6h
            write_timeout 6h
        }
    }
}
EOF
fi

echo "Caddyfile ready at $CADDYFILE"
echo "Install Caddy if needed, then start it with:"
echo "sudo caddy run --config $CADDYFILE --adapter caddyfile"
echo "Then set Streamlit secret ASTK_BACKEND_URL=https://$DOMAIN"
