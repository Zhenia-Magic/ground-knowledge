#!/usr/bin/env bash
# Clean-clone smoke test — everything a reviewer needs, zero setup, stdlib only.
# Mirrors the CI `test` + `smoke` jobs. Run from a fresh clone:
#     bash scripts/smoke.sh
#
# Each check is its own statement (not `check && echo`): under `set -e` a command on the
# left of `&&` is exempt from the errexit trap, which would silently swallow a failing gate.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/6  unit tests (stdlib only, no dependencies) =="
python3 -m unittest discover -s tests -t .

echo "== 2/6  schema + cross-reference validation (every case) =="
for c in cases/*.kb.json; do
  python3 cli.py validate "$c" >/dev/null
  echo "  ok  $c"
done

echo "== 3/6  strict benchmark + checked-in result freshness =="
python3 eval/run_benchmark.py --require-live-baseline --check-results >/dev/null
echo "  benchmark PASS"

echo "== 4/6  support-edge migration completeness =="
python3 scripts/migrate_edge_admissions.py --check >/dev/null
echo "  edge admissions current"

echo "== 5/6  generated source-inventory freshness =="
python3 scripts/source_inventory.py --check >/dev/null
echo "  source inventory current"

echo "== 6/6  one-command demo (per-case collapse + benchmark) =="
python3 cli.py demo >/dev/null
echo "  demo ok"

echo
echo "SMOKE OK — clone is healthy."
