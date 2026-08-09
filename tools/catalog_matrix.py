#!/usr/bin/env python3
"""Imprime a matriz prática x severidade usada na tabela-resumo do README.

PYTHONPATH=src python3 tools/catalog_matrix.py
"""

from __future__ import annotations

from collections import Counter

from obsgov.evaluator import CONTROLS


def main() -> None:
    by_practice: dict[str, Counter] = {}
    cobit_by_practice: dict[str, set[str]] = {}
    for c in CONTROLS:
        by_practice.setdefault(c.practice, Counter())[c.severity.value] += 1
        cobit_by_practice.setdefault(c.practice, set()).update(c.cobit)

    print(f"{'Prática':34} {'COBIT':16} MUST SHOULD MAY")
    for practice, counts in by_practice.items():
        cobit = ", ".join(sorted(cobit_by_practice[practice]))
        print(f"{practice:34} {cobit:16} {counts['MUST']:4} {counts['SHOULD']:6} {counts['MAY']:3}")


if __name__ == "__main__":
    main()
