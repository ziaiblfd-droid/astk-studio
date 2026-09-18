#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${ASTK_BACKEND_URL:-}"
if [[ -z "$BASE_URL" ]]; then
  echo "usage: ASTK_BACKEND_URL=https://astk.example.com $0" >&2
  exit 2
fi
BASE_URL="${BASE_URL%/}"
VERIFY_ZIP="${ASTK_VERIFY_ZIP:-}"
VERIFY_CSV="${ASTK_VERIFY_CSV:-}"
VERIFY_SPECIES="${ASTK_VERIFY_SPECIES:-Mus musculus · mm10}"
if [[ -n "$VERIFY_ZIP" || -n "$VERIFY_CSV" ]]; then
  if [[ ! -f "$VERIFY_ZIP" || ! -f "$VERIFY_CSV" ]]; then
    echo "ASTK_VERIFY_ZIP and ASTK_VERIFY_CSV must both point to existing files." >&2
    exit 2
  fi
fi

echo "== health =="
curl -fsS --max-time 15 "$BASE_URL/api/health"
echo

echo "== template =="
curl -fsS --max-time 15 "$BASE_URL/api/templates/samples.csv" | head -n 2

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
upload_zip="$TMP_DIR/quant.zip"
upload_csv="$TMP_DIR/samples.csv"
if [[ -n "$VERIFY_ZIP" ]]; then
  cp "$VERIFY_ZIP" "$upload_zip"
  cp "$VERIFY_CSV" "$upload_csv"
else
  for sample in ctrl_a ctrl_b case_a case_b; do
    mkdir -p "$TMP_DIR/quant/$sample"
    printf 'Name\tLength\tEffectiveLength\tTPM\tNumReads\nTX1\t1000\t800\t12.5\t10\n' >"$TMP_DIR/quant/$sample/quant.sf"
  done
  cat >"$upload_csv" <<'EOF'
group,condition,name,path,replicate
verify_vs_control,ctrl,ctrl_a,quant/ctrl_a/quant.sf,1
verify_vs_control,ctrl,ctrl_b,quant/ctrl_b/quant.sf,2
verify_vs_control,case,case_a,quant/case_a/quant.sf,1
verify_vs_control,case,case_b,quant/case_b/quant.sf,2
EOF
  (
    cd "$TMP_DIR"
    zip -q -r quant.zip quant
  )
fi

echo "== upload =="
config="$(
  VERIFY_SPECIES="$VERIFY_SPECIES" python3 -c \
    'import json, os; print(json.dumps({"species": os.environ["VERIFY_SPECIES"], "data_source": "Salmon quant.sf · transcript TPM", "design": "两组比较", "comparison_mode": "baseline", "event_type": "ALL", "method": "empirical", "p_value": 0.05, "abs_dpsi": 0.1}, ensure_ascii=False))'
)"
response="$(curl -fsS --max-time 120 \
  -F "config=$config" \
  -F "files=@$upload_zip;type=application/zip" \
  -F "files=@$upload_csv;type=text/csv" \
  "$BASE_URL/api/jobs")"
printf '%s\n' "$response"
job_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

echo "job_id=$job_id"
if [[ -z "$VERIFY_ZIP" ]]; then
  echo "Upload smoke check passed. This synthetic probe does not validate transcript IDs against the server reference."
  echo "For full acceptance, rerun with ASTK_VERIFY_ZIP and ASTK_VERIFY_CSV pointing to real test data."
  exit 0
fi

echo "== analysis =="
deadline=$((SECONDS + 21600))
while (( SECONDS < deadline )); do
  job="$(curl -fsS --max-time 20 "$BASE_URL/api/jobs/$job_id")"
  status="$(printf '%s' "$job" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  progress="$(printf '%s' "$job" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("progress", 0))')"
  printf 'status=%s progress=%s%%\n' "$status" "$progress"
  if [[ "$status" == "completed" ]]; then
    curl -fsS --max-time 60 "$BASE_URL/api/jobs/$job_id/results" \
      | python3 -c 'import json,sys; data=json.load(sys.stdin); metrics=data.get("metrics", {}); assert "total_events" in metrics; print("analysis completed:", metrics)'
    exit 0
  fi
  if [[ "$status" == "failed" ]]; then
    printf '%s' "$job" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error") or "analysis failed", file=sys.stderr)'
    exit 1
  fi
  sleep 10
done

echo "analysis did not complete within 6 hours" >&2
exit 1
