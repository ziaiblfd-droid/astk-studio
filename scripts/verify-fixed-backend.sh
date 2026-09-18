#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${ASTK_BACKEND_URL:-}"
if [[ -z "$BASE_URL" ]]; then
  echo "usage: ASTK_BACKEND_URL=https://astk.example.com $0" >&2
  exit 2
fi
BASE_URL="${BASE_URL%/}"

echo "== health =="
curl -fsS --max-time 15 "$BASE_URL/api/health"
echo

echo "== template =="
curl -fsS --max-time 15 "$BASE_URL/api/templates/samples.csv" | head -n 2

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/quant/sample_a" "$TMP_DIR/quant/sample_b"
printf 'Name\tLength\tEffectiveLength\tTPM\tNumReads\nTX1\t1000\t800\t12.5\t10\n' >"$TMP_DIR/quant/sample_a/quant.sf"
printf 'Name\tLength\tEffectiveLength\tTPM\tNumReads\nTX1\t1000\t800\t13.5\t11\n' >"$TMP_DIR/quant/sample_b/quant.sf"
cat >"$TMP_DIR/samples.csv" <<'EOF'
group,condition,name,path,replicate
verify_vs_control,ctrl,sample_a,quant/sample_a/quant.sf,1
verify_vs_control,case,sample_b,quant/sample_b/quant.sf,1
EOF
(
  cd "$TMP_DIR"
  zip -q -r quant.zip quant
)

echo "== upload =="
response="$(curl -fsS --max-time 120 \
  -F 'config={"species":"Mus musculus · mm10","data_source":"Salmon quant.sf · transcript TPM","design":"两组比较","comparison_mode":"baseline","event_type":"ALL","method":"empirical","p_value":0.05,"abs_dpsi":0.1}' \
  -F "files=@$TMP_DIR/quant.zip;type=application/zip" \
  -F "files=@$TMP_DIR/samples.csv;type=text/csv" \
  "$BASE_URL/api/jobs")"
printf '%s\n' "$response"
job_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

echo "job_id=$job_id"
echo "Poll with: curl -fsS $BASE_URL/api/jobs/$job_id"
