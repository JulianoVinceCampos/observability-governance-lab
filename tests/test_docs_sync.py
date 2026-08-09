"""docs/controls.md é gerado a partir do catálogo (tools/gen_controls_doc.py). Este
teste falha se alguém editar CONTROLS sem regenerar o doc. O doc divergir do código em
silêncio é exatamente o tipo de coisa que este projeto existe para pegar em outro lugar.
"""

from __future__ import annotations

from pathlib import Path

from obsgov.evaluator import CONTROLS


def test_controls_doc_mentions_every_control_id() -> None:
    doc = Path("docs/controls.md").read_text(encoding="utf-8")
    missing = [c.id for c in CONTROLS if f"`{c.id}`" not in doc]
    assert not missing, f"rode `python3 tools/gen_controls_doc.py`, faltando: {missing}"


def test_controls_doc_declares_the_right_total() -> None:
    doc = Path("docs/controls.md").read_text(encoding="utf-8")
    assert f"**{len(CONTROLS)} controles**" in doc
