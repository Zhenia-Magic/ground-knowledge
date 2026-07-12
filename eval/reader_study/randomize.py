#!/usr/bin/env python3
"""Generate deterministic, balanced study assignments (stdlib only)."""
import argparse
import csv
import random

CASES = ("covid", "blackholes", "eggs")
ORDERS = ((0, 1, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0), (1, 0, 2), (0, 2, 1))


def assignments(n, seed=20260711):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        order = ORDERS[i % len(ORDERS)]
        block = i // len(ORDERS)
        for sequence, case_i in enumerate(order, 1):
            rows.append({"participant": "P%03d" % (i + 1), "sequence": sequence,
                         "case": CASES[case_i],
                         # Balance within every CASE x SEQUENCE stratum. Condition depends on the
                         # six-order replication block, not on the participant's order row, so
                         # fatigue/sequence cannot masquerade as a treatment effect.
                         "condition": "DR+GK" if (block + case_i) % 2 else "DR"})
    rng.shuffle(rows)  # hide predictable participant blocks in the administrator copy
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--participants", type=int, default=36)
    ap.add_argument("--seed", type=int, default=20260711)
    ap.add_argument("--out", default="assignments.csv")
    args = ap.parse_args(argv)
    rows = assignments(args.participants, args.seed)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=("participant", "sequence", "case", "condition"))
        w.writeheader(); w.writerows(rows)
    print("wrote {} assignment rows ({} participants × {} cases, within-participant crossover) to {}"
          .format(len(rows), args.participants, len(CASES), args.out))


if __name__ == "__main__":
    main()
