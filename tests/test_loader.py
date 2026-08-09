"""Testes do loader: arquivo obrigatório vs opcional, JSON malformado, e carga
end-to-end dos dois fixtures sintéticos publicados no repo (data/bad-state,
data/good-state).
"""

from __future__ import annotations

import json

import pytest

from obsgov.loader import LoaderError, load_inventory

FIXTURES = "data"


def test_missing_directory_raises() -> None:
    with pytest.raises(LoaderError, match="não é um diretório"):
        load_inventory("does/not/exist")


def test_missing_required_file_raises(tmp_path) -> None:
    (tmp_path / "service-catalog.json").write_text("[]", encoding="utf-8")
    with pytest.raises(LoaderError, match="fonte obrigatória ausente"):
        load_inventory(tmp_path)


def test_malformed_json_raises(tmp_path) -> None:
    for name in ("service-catalog.json", "slo.json", "alerts.json", "runbooks.json"):
        (tmp_path / name).write_text("[]", encoding="utf-8")
    (tmp_path / "service-catalog.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(LoaderError, match="JSON malformado"):
        load_inventory(tmp_path)


def test_optional_change_log_defaults_to_empty(tmp_path) -> None:
    for name, content in (
        ("service-catalog.json", []),
        ("slo.json", []),
        ("alerts.json", []),
        ("runbooks.json", []),
    ):
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    inv = load_inventory(tmp_path)
    assert inv.problems == ()
    assert inv.trace_id_correlation_verified is False


def test_loads_bad_state_fixture() -> None:
    inv = load_inventory(f"{FIXTURES}/bad-state")
    assert len(inv.services) == 3
    assert inv.trace_id_correlation_verified is False
    assert any(s.name == "app-tier-node" for s in inv.services)


def test_loads_good_state_fixture() -> None:
    inv = load_inventory(f"{FIXTURES}/good-state")
    assert len(inv.services) == 3
    assert inv.trace_id_correlation_verified is True
    assert all(slo.error_budget.consequence for slo in inv.slos)
