#!/usr/bin/env python3
"""Regenera docs/controls.md direto do catálogo CONTROLS.

Mantém o doc sem divergir do código, mesma disciplina do número gerado no README do
postmortem-miner: a fonte da verdade é o catálogo, não prosa que alguém esqueceu de
atualizar.

    PYTHONPATH=src python3 tools/gen_controls_doc.py
"""

from __future__ import annotations

from pathlib import Path

from obsgov.evaluator import CONTROLS

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    lines = [
        "# Catálogo de controles",
        "",
        "Gerado a partir de `src/obsgov/evaluator.py::CONTROLS`. Rode "
        "`python3 tools/gen_controls_doc.py` depois de editar o catálogo, não edite a "
        "tabela abaixo à mão.",
        "",
        "Ver [NOTICE.md](../NOTICE.md): identificadores de objetivo COBIT são usados só "
        "como ponto de referência público. Todo título e toda string de remediação é "
        "redação própria.",
        "",
        f"**{len(CONTROLS)} controles** em "
        f"{len({c.practice for c in CONTROLS})} práticas, mapeados para "
        f"{len({o for c in CONTROLS for o in c.cobit})} objetivos COBIT 2019.",
        "",
        "| ID | Severidade | Prática | COBIT | Título | Remediação |",
        "|---|---|---|---|---|---|",
    ]
    for c in CONTROLS:
        cobit = ", ".join(c.cobit)
        row = (
            f"| `{c.id}` | {c.severity.value} | {c.practice} | {cobit} | "
            f"{c.title} | {c.remediation} |"
        )
        lines.append(row)

    (ROOT / "docs" / "controls.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"escrito docs/controls.md ({len(CONTROLS)} controles)")


if __name__ == "__main__":
    main()
