#!/usr/bin/env bash
# Clean-clone smoke test — everything a reviewer needs, zero setup, stdlib only.
# Mirrors the CI `test` + `smoke` jobs. Run from a fresh clone:
#     bash scripts/smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/4  unit tests (stdlib only, no dependencies) =="
python3 -m unittest discover -s tests -t .

echo "== 2/4  schema + cross-reference validation (every case) =="
for c in cases/*.kb.json; do
  python3 cli.py validate "$c" >/dev/null && echo "  ok  $c"
done

echo "== 3/4  strict benchmark (recall · collapse · adversarial · baseline hashes) =="
python3 eval/run_benchmark.py --require-live-baseline >/dev/null && echo "  benchmark PASS"

echo "== 4/4  one-command demo (per-case collapse + benchmark) =="
python3 cli.py demo >/dev/null && echo "  demo ok"

echo
echo "SMOKE OK — clone is healthy."
