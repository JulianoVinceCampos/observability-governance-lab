"""Testes da CLI: exit code é o contrato do qual um gate de CI depende."""

from __future__ import annotations

import json

from obsgov.cli import main


def test_validate_fails_on_bad_state(capsys) -> None:
    code = main(["validate", "data/bad-state"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out


def test_validate_passes_on_good_state(capsys) -> None:
    code = main(["validate", "data/good-state"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Todos os controles MUST passam." in out


def test_validate_on_missing_directory_exits_2() -> None:
    assert main(["validate", "does/not/exist"]) == 2


def test_score_prints_a_level_per_practice(capsys) -> None:
    code = main(["score", "data/good-state"])
    out = capsys.readouterr().out
    assert code == 0
    assert "maturidade geral" in out
    assert "monitoring-and-event-management" in out


def test_report_writes_three_files(tmp_path) -> None:
    out_dir = tmp_path / "out"
    code = main(["report", "data/good-state", "--out", str(out_dir)])
    assert code == 0
    for name in ("report.md", "report.json", "report.sarif"):
        assert (out_dir / name).is_file(), name

    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert "overall_maturity" in payload
    assert len(payload["controls"]) == 30

    sarif = json.loads((out_dir / "report.sarif").read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
