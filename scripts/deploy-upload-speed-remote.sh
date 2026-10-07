#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?project root required}"
STAGE="${2:?staging directory required}"
case "$STAGE" in
  "$ROOT"/.deploy-upload-speed-*) ;;
  *) echo "Refusing unexpected staging path: $STAGE" >&2; exit 2 ;;
esac
trap 'rm -rf -- "$STAGE"' EXIT

LIVE="$(readlink -f "$ROOT/current")"
case "$LIVE" in
  "$ROOT"/releases/*) ;;
  *) echo "Refusing unexpected active release: $LIVE" >&2; exit 2 ;;
esac

CONF_DIR="$HOME/.config/systemd/user/astk-studio.service.d"
CONF="$CONF_DIR/90-upload-speed.conf"
[[ -f "$STAGE/90-upload-speed.conf" ]] || {
  echo "Upload speed drop-in is missing." >&2
  exit 1
}
[[ -f "$STAGE/backend/server.py" && -f "$STAGE/backend/upload_store.py" ]] || {
  echo "Updated backend upload modules are missing." >&2
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
import json
import pathlib
import sys
import time

root = pathlib.Path(sys.argv[1])
now = time.time()
active = []
for path in root.glob("UPL-*"):
    try:
        metadata = json.loads((path / "upload.json").read_text())
        age = now - path.stat().st_mtime
        expected = sum(int(item.get("chunks", 0)) for item in metadata.get("files", []))
        received = len(list((path / "parts").glob("*.part")))
    except (OSError, ValueError, TypeError):
        continue
    if age < 30 or (age < 3600 and received < expected):
        active.append((path.name, round(age), received, expected))
if active:
    raise SystemExit(f"Refusing service restart with active upload sessions: {active}")
PY
}

check_idle
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$ROOT/deployments/upload-speed-$STAMP"
mkdir -p "$BACKUP"
printf '%s\n' "drop-in absent before deployment" >"$BACKUP/previous-state.txt"
systemctl --user cat astk-studio >"$BACKUP/astk-studio.service.txt"
cp "$LIVE/backend/server.py" "$LIVE/backend/upload_store.py" "$BACKUP/"

rollback() {
  install -m 0644 "$BACKUP/server.py" "$LIVE/backend/server.py"
  install -m 0644 "$BACKUP/upload_store.py" "$LIVE/backend/upload_store.py"
  rm -f -- "$CONF"
  systemctl --user daemon-reload || true
  systemctl --user restart astk-studio || true
}
trap 'rollback; rm -rf -- "$STAGE"' ERR

install -m 0644 "$STAGE/backend/server.py" "$LIVE/backend/server.py"
install -m 0644 "$STAGE/backend/upload_store.py" "$LIVE/backend/upload_store.py"
mkdir -p "$CONF_DIR"
install -m 0644 "$STAGE/90-upload-speed.conf" "$CONF"
systemctl --user daemon-reload
systemctl --user restart astk-studio

for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:4173/api/health >"$BACKUP/health.json"; then
    PID="$(systemctl --user show astk-studio -p MainPID --value)"
    if tr '\0' '\n' <"/proc/$PID/environ" | grep -qx 'ASTK_UPLOAD_CHUNK_BYTES=524288' \
      && tr '\0' '\n' <"/proc/$PID/environ" | grep -qx 'ASTK_UPLOAD_RETENTION_SECONDS=43200' \
      && tr '\0' '\n' <"/proc/$PID/environ" | grep -qx 'ASTK_RETENTION_DAYS=0.5'; then
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
