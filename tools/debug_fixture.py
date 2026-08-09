#!/usr/bin/env python3
"""Debug ad-hoc: imprime verdict+evidência de todo controle contra um fixture.

PYTHONPATH=src python3 tools/debug_fixture.py data/bad-state
"""

from __future__ import annotations

import sys
from collections import Counter

from obsgov.evaluator import CONTROLS, evaluate, score_all
from obsgov.loader import load_inventory


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--catalog":
        print(f"total de controles: {len(CONTROLS)}")
        print(f"por severidade: {dict(Counter(c.severity.value for c in CONTROLS))}")
        print(f"por prática: {dict(Counter(c.practice for c in CONTROLS))}")
        return

    state = sys.argv[1] if len(sys.argv) > 1 else "data/bad-state"
    inv = load_inventory(state)
    results = evaluate(inv)
    for r in results:
        print(f"{r.control_id:10} {r.verdict.value:6} {r.evidence}")
    print()
    for s in score_all(results):
        print(f"{s.practice:32} nível {s.level}  ceiling={s.ceiling_control or '-'}")


if __name__ == "__main__":
    main()
