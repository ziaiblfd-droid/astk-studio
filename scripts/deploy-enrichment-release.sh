#!/usr/bin/env bash
# Install a validated enrichment release without modifying the previous checkout.
set -euo pipefail
STAGE="$(realpath "${1:?staging directory required}")"
RELEASE_ID="${2:?release identifier required}"
[[ "$RELEASE_ID" =~ ^[a-zA-Z0-9-]+$ ]] || { echo "Invalid release identifier" >&2; exit 2; }
BASE="$HOME/astk-web"
CURRENT="$BASE/current"
PREVIOUS="$(readlink -f "$CURRENT")"
TARGET="$BASE/releases/$RELEASE_ID"
PY="$HOME/miniconda3/envs/astk/bin/python"
UNIT="astk-studio.service"
[[ "$PREVIOUS" == "$BASE/releases/"* && -f "$PREVIOUS/backend/server.py" ]] || exit 2
[[ ! -e "$TARGET" ]] || { echo "Release already exists" >&2; exit 2; }

idle() {
  curl -fsS --max-time 10 http://127.0.0.1:4173/api/health | "$PY" -c 'import json,sys; h=json.load(sys.stdin); q=h["queue"]; print(q); sys.exit(0 if h["status"] == "ok" and all(q[k] == 0 for k in ("running","queued","inflight")) else 1)'
}
idle || { echo "Backend is busy; no deployment performed" >&2; exit 3; }
mkdir -p "$TARGET"
rsync -a --exclude=data --exclude=__pycache__ --exclude='*.pyc' --exclude=.git --exclude=.wrangler --exclude=_backups "$PREVIOUS/" "$TARGET/"
for file in backend/server.py backend/downstream.py index.html downstream.js downstream.css i18n.js; do
  [[ -f "$STAGE/$file" ]] || exit 2
  cp "$STAGE/$file" "$TARGET/$file"
done
mkdir -p "$TARGET/tests"
cp "$STAGE"/tests/test_*.py "$TARGET/tests/"
ln -s "$BASE/data" "$TARGET/data"
(cd "$TARGET" && "$PY" -m py_compile backend/server.py backend/downstream.py && "$PY" -m unittest discover -s tests -q)
STATE="$BASE/deployments/$RELEASE_ID"
mkdir -p "$STATE"
printf '%s\n' "$PREVIOUS" > "$STATE/previous-release"
printf '%s\n' "$TARGET" > "$STATE/target-release"
idle || { echo "Backend became busy; validated release staged only" >&2; exit 3; }
restore_on_failure() {
  local code="$?"
  if [[ "$code" != 0 ]]; then
    systemctl --user stop "$UNIT" || true
    if [[ "$(readlink -f "$CURRENT")" != "$PREVIOUS" ]]; then
      ln -s "$PREVIOUS" "$BASE/current-recovery-$RELEASE_ID"
      mv -Tf "$BASE/current-recovery-$RELEASE_ID" "$CURRENT"
    fi
    systemctl --user start "$UNIT" || true
  fi
}
trap restore_on_failure EXIT
trap 'exit 130' INT TERM
systemctl --user stop "$UNIT"
# A request may arrive between the health check and shutdown. Restore service
# without changing releases if any persistent job state is still active.
if ! "$PY" - "$BASE/data/jobs" <<'PY'
import json,sys
from pathlib import Path
active=[]
for path in Path(sys.argv[1]).glob('*/job.json'):
    job=json.loads(path.read_text())
    if job.get('status') in {'running','queued'}:
        active.append(job.get('id',path.parent.name))
print('Active persistent jobs:',active)
sys.exit(bool(active))
PY
then
  systemctl --user start "$UNIT"
  echo "Submission raced with shutdown; old release restored" >&2
  trap - EXIT INT TERM
  exit 3
fi
switch_to() {
  ln -s "$1" "$BASE/current-next-$RELEASE_ID"
  mv -Tf "$BASE/current-next-$RELEASE_ID" "$CURRENT"
}
healthy() {
  for _ in $(seq 1 30); do
    curl -fsS --max-time 3 http://127.0.0.1:4173/api/health && return 0
    sleep 1
  done
  return 1
}
switch_to "$TARGET"
if ! systemctl --user start "$UNIT" || ! healthy; then
  systemctl --user stop "$UNIT" || true
  switch_to "$PREVIOUS"
  systemctl --user start "$UNIT"
  healthy || true
  echo "Deployment failed; previous release restored" >&2
  exit 1
fi
trap - EXIT INT TERM
printf '\nPrevious: %s\nCurrent: %s\nState: %s\n' "$PREVIOUS" "$TARGET" "$STATE"
systemctl --user show "$UNIT" -p ActiveState -p MainPID
