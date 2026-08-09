#!/usr/bin/env python3
"""Ratchet de cobertura: o piso só sobe.

Lê a cobertura de linha atual do coverage.xml, compara com `.coverage-floor`, e ou eleva
o piso ou reprova o build. Limiar fixo apodrece: as pessoas aprendem a viver logo acima
dele. Um ratchet transforma cobertura em porta de mão única.

    python3 tools/coverage_ratchet.py                 # só checa
    python3 tools/coverage_ratchet.py --update        # eleva o piso quando melhorou

Exit 0 ok, 1 regressão, 2 erro de uso.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOOR_FILE = ROOT / ".coverage-floor"
REPORT = ROOT / "coverage.xml"
# A medição de cobertura oscila em frações entre execuções e versões de Python.
TOLERANCE = 0.5


def read_floor() -> float:
    if not FLOOR_FILE.exists():
        return 0.0
    raw = FLOOR_FILE.read_text(encoding="utf-8").strip()
    return float(raw) if raw else 0.0


def read_coverage(report: Path) -> float:
    # Justificativa: a única entrada é o coverage.xml produzido pelo nosso próprio job de
    # CI no step anterior do mesmo runner. Não vem do usuário e não cruza fronteira de
    # confiança, então a classe de XXE que a regra protege não se aplica aqui. Trazer
    # defusedxml adicionaria dependência a um repo cujo ponto é não ter nenhuma.
    # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
    root = ET.parse(report).getroot()
    rate = root.get("line-rate")
    if rate is None:
        raise ValueError("coverage.xml não tem o atributo line-rate")
    return float(rate) * 100


def main() -> int:
    parser = argparse.ArgumentParser(description="Ratchet de cobertura.")
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--update", action="store_true", help="eleva o piso se melhorou")
    args = parser.parse_args()

    if not args.report.exists():
        print(f"erro: relatório de cobertura não encontrado: {args.report}")
        return 2

    floor = read_floor()
    current = read_coverage(args.report)
    print(f"cobertura: {current:.2f}%  piso: {floor:.2f}%")

    if current + TOLERANCE < floor:
        print(f"REGRESSÃO: cobertura caiu {floor - current:.2f} pontos abaixo do piso")
        return 1

    if current > floor + TOLERANCE:
        if args.update:
            FLOOR_FILE.write_text(f"{current:.2f}\n", encoding="utf-8")
            print(f"piso elevado para {current:.2f}%")
        else:
            print(f"piso pode subir para {current:.2f}% (rode com --update)")
    else:
        print("piso mantido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
