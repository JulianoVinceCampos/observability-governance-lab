"""Prova end-to-end de que os fixtures publicados se comportam como o README afirma:
o estado ruim reprova pelos motivos certos, o estado bom limpa todo MUST, e o número de
maturidade de fato se move entre os dois. É este teste que mantém honesta a afirmação
de progressão do README.
"""

from __future__ import annotations

from obsgov.evaluator import Severity, Verdict, evaluate, overall_maturity, score_all
from obsgov.loader import load_inventory


def _load(state: str):
    inv = load_inventory(f"data/{state}")
    results = evaluate(inv)
    scores = score_all(results)
    return results, scores


def test_bad_state_fails_musts_for_the_documented_reasons() -> None:
    results, _ = _load("bad-state")
    failed = {
        r.control_id for r in results if r.severity == Severity.MUST and r.verdict == Verdict.FAIL
    }

    # Cada um destes está quebrado de propósito em data/bad-state/*.json. Ver
    # docs/plans/portfolio-github/09-observability-governance-lab.md section 1.8.
    expected_subset = {
        "OBS-002",  # UNVERIFIED_METRIC sentinel
        "OBS-003",  # alert points at the dead metric
        "OBS-004",  # trace_id_correlation_verified: false
        "OBS-005",  # no trace_id/span_id in collector_attributes
        "SLO-002",  # SLO with no owner/cadence
        "SLO-003",  # SLO with no error-budget consequence
        "INC-001",  # paging alert with no runbook_ref
        "INC-002",  # RB-002 tested 210 days ago against a 90-day window
        "INC-003",  # ALR-003 has no severity
        "CHG-001",  # app-tier-node change has no deploy marker
        "CHG-002",  # app-tier-node change has no rollback signal
        "BCP-001",  # no watchdog declared at all
    }
    missing = expected_subset - failed
    assert not missing, f"expected these MUSTs to fail but they didn't: {missing}"


def test_bad_state_prb_002_fails_on_missing_workaround() -> None:
    results, _ = _load("bad-state")
    prb002 = next(r for r in results if r.control_id == "PRB-002")
    assert prb002.verdict == Verdict.FAIL


def test_bad_state_inc_004_orphaned_alert_should_fails() -> None:
    results, _ = _load("bad-state")
    inc004 = next(r for r in results if r.control_id == "INC-004")
    assert inc004.verdict == Verdict.FAIL


def test_good_state_clears_every_must() -> None:
    results, _ = _load("good-state")
    failed_musts = [r for r in results if r.severity == Severity.MUST and r.verdict == Verdict.FAIL]
    assert failed_musts == [], f"good-state should clear all MUSTs, still failing: {failed_musts}"


def test_maturity_improves_from_bad_to_good() -> None:
    _, bad_scores = _load("bad-state")
    _, good_scores = _load("good-state")
    bad_overall = overall_maturity(bad_scores)
    good_overall = overall_maturity(good_scores)
    assert good_overall > bad_overall, (bad_overall, good_overall)


def test_bad_state_practices_are_capped_at_one_by_a_named_ceiling_control() -> None:
    results, scores = _load("bad-state")
    capped = {s.practice: s.ceiling_control for s in scores if s.level == 1 and s.ceiling_control}
    assert "monitoring-and-event-management" in capped
    assert capped["monitoring-and-event-management"].startswith("OBS-")
