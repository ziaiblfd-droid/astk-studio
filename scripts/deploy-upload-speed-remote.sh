#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?project root required}"
STAGE="${2:?staging directory required}"
case "$STAGE" in
  "$ROOT"/.deploy-upload-speed-*) ;;
  *) echo "Refusing unexpected staging path: $STAGE" >&2; exit 2 ;;
esac
trap 'rm -rf -- "$STAGE"' EXIT

CONF_DIR="$HOME/.config/systemd/user/astk-studio.service.d"
CONF="$CONF_DIR/90-upload-speed.conf"
[[ -f "$STAGE/90-upload-speed.conf" ]] || {
  echo "Upload speed drop-in is missing." >&2
  exit 1
}
[[ ! -e "$CONF" ]] || {
  echo "Upload speed drop-in already exists; refusing to overwrite it." >&2
  exit 1
}
[[ "$(systemctl --user is-active astk-studio)" == "active" ]] || {
  echo "astk-studio is not active." >&2
  exit 1
}

check_idle() {
  local health
  health="$(curl -fsS --max-time 5 http://127.0.0.1:4173/api/health)"
  HEALTH_JSON="$health" python3 - <<'PY'
import json
import os

queue = json.loads(os.environ["HEALTH_JSON"])["queue"]
if queue.get("running") or queue.get("queued") or queue.get("inflight"):
    raise SystemExit(f"Refusing service restart with active jobs: {queue}")
PY
  python3 - "$ROOT/data/uploads" <<'PY'
import pathlib
import sys
import time

root = pathlib.Path(sys.argv[1])
recent = [
    path.name
    for path in root.glob("UPL-*")
    if time.time() - path.stat().st_mtime < 3600
]
if recent:
    raise SystemExit(f"Refusing service restart with recent upload sessions: {recent}")
PY
}

check_idle
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$ROOT/deployments/upload-speed-$STAMP"
mkdir -p "$BACKUP"
printf '%s\n' "drop-in absent before deployment" >"$BACKUP/previous-state.txt"
systemctl --user cat astk-studio >"$BACKUP/astk-studio.service.txt"

rollback() {
  rm -f -- "$CONF"
  systemctl --user daemon-reload || true
  systemctl --user restart astk-studio || true
}
trap 'rollback; rm -rf -- "$STAGE"' ERR

mkdir -p "$CONF_DIR"
install -m 0644 "$STAGE/90-upload-speed.conf" "$CONF"
systemctl --user daemon-reload
systemctl --user restart astk-studio

for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:4173/api/health >"$BACKUP/health.json"; then
    PID="$(systemctl --user show astk-studio -p MainPID --value)"
    if tr '\0' '\n' <"/proc/$PID/environ" | grep -qx 'ASTK_UPLOAD_CHUNK_BYTES=524288'; then
      check_idle
      echo "Upload chunk configuration deployed and verified."
      echo "Backup: $BACKUP"
      exit 0
    fi
  fi
  sleep 2
done

echo "Upload configuration health check failed; restoring previous service state." >&2
rollback
trap 'rm -rf -- "$STAGE"' ERR
exit 1
