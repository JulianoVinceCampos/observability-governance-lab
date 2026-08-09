"""Um teste por branch pass/fail/skip de cada controle, mais a regra de teto.

Convenção: todo controle MUST tem um caso de pass, um de fail e (onde faz sentido) um
de skip. O teste da regra de teto é o que mais importa: é o mecanismo que impede o
score de maturidade de virar propaganda.
"""

from __future__ import annotations

import dataclasses
from datetime import date

from obsgov.evaluator import (
    CONTROLS,
    Severity,
    Verdict,
    Waiver,
    evaluate,
    overall_maturity,
    score_all,
    score_practice,
)
from obsgov.model import (
    ChangeRecord,
    CollectorAttribute,
    Inventory,
    MetricCardinalityBudget,
    ProblemRecord,
    RetentionPolicy,
    WatchdogRecord,
)
from tests.conftest import make_alert, make_runbook, make_service, make_slo


def _result(inv: Inventory, control_id: str) -> Verdict:
    results = evaluate(inv)
    match = next(r for r in results if r.control_id == control_id)
    return match.verdict


def test_catalog_has_30_controls_with_expected_severity_mix() -> None:
    # Trava o número real do catálogo para que uma edição futura tenha de ser
    # deliberada, não acidental.
    assert len(CONTROLS) == 30
    musts = sum(1 for c in CONTROLS if c.severity == Severity.MUST)
    shoulds = sum(1 for c in CONTROLS if c.severity == Severity.SHOULD)
    mays = sum(1 for c in CONTROLS if c.severity == Severity.MAY)
    assert (musts, shoulds, mays) == (16, 12, 2)


def test_empty_inventory_skips_everything_with_no_precondition(empty_inventory: Inventory) -> None:
    results = evaluate(empty_inventory)
    # Dois controles não têm pré-requisito para dar skip, porque um pipeline não medido
    # é em si a falha, não ausência de dado: BCP-001 (nenhum watchdog) e OBS-004
    # (nenhuma correlação de trace_id verificada, default False). Todos os outros
    # precisam de ao menos um serviço/SLO/alerta declarado para ter o que checar.
    non_skip = {r.control_id for r in results if r.verdict != Verdict.SKIP}
    assert non_skip == {"BCP-001", "OBS-004"}
    assert all(r.verdict == Verdict.FAIL for r in results if r.control_id in non_skip)


class TestObsControls:
    def test_obs_001_pass_and_fail(self) -> None:
        good = Inventory(services=(make_service(signals=("a", "b", "c", "d")),))
        bad = Inventory(services=(make_service(signals=("a", "b")),))
        assert _result(good, "OBS-001") == Verdict.PASS
        assert _result(bad, "OBS-001") == Verdict.FAIL

    def test_obs_002_dead_metric_fails(self) -> None:
        bad = Inventory(services=(make_service(signals=("UNVERIFIED_METRIC.x",)),))
        good = Inventory(services=(make_service(signals=("real.metric",)),))
        assert _result(bad, "OBS-002") == Verdict.FAIL
        assert _result(good, "OBS-002") == Verdict.PASS

    def test_obs_003_orphan_alert_metric(self) -> None:
        inv = Inventory(
            services=(make_service(signals=("known.metric",)),),
            alerts=(make_alert(metric="unknown.metric"),),
        )
        assert _result(inv, "OBS-003") == Verdict.FAIL

    def test_obs_004_requires_verified_correlation(self) -> None:
        assert _result(Inventory(trace_id_correlation_verified=False), "OBS-004") == Verdict.FAIL
        assert _result(Inventory(trace_id_correlation_verified=True), "OBS-004") == Verdict.PASS

    def test_obs_005_log_pipeline_missing_context(self) -> None:
        bad = Inventory(collector_attributes=(CollectorAttribute("service.name", True),))
        good = Inventory(
            collector_attributes=(
                CollectorAttribute("trace_id", True),
                CollectorAttribute("span_id", True),
            )
        )
        assert _result(bad, "OBS-005") == Verdict.FAIL
        assert _result(good, "OBS-005") == Verdict.PASS

    def test_obs_006_unbounded_cardinality(self) -> None:
        bad = Inventory(cardinality_budgets=(MetricCardinalityBudget("m", None),))
        good = Inventory(cardinality_budgets=(MetricCardinalityBudget("m", 500),))
        assert _result(bad, "OBS-006") == Verdict.FAIL
        assert _result(good, "OBS-006") == Verdict.PASS

    def test_obs_007_non_semantic_attribute(self) -> None:
        bad = Inventory(collector_attributes=(CollectorAttribute("message", False),))
        good = Inventory(collector_attributes=(CollectorAttribute("service.name", True),))
        assert _result(bad, "OBS-007") == Verdict.FAIL
        assert _result(good, "OBS-007") == Verdict.PASS


class TestSloControls:
    def test_slo_001_missing_slo_for_critical_service(self) -> None:
        inv = Inventory(services=(make_service("svc"),))
        assert _result(inv, "SLO-001") == Verdict.FAIL

    def test_slo_002_missing_owner_or_cadence(self) -> None:
        bad = Inventory(slos=(make_slo(owner="", review_cadence_days=0),))
        assert _result(bad, "SLO-002") == Verdict.FAIL

    def test_slo_003_missing_error_budget_consequence(self) -> None:
        bad = Inventory(slos=(make_slo(consequence=""),))
        good = Inventory(slos=(make_slo(consequence="freeze deploys"),))
        assert _result(bad, "SLO-003") == Verdict.FAIL
        assert _result(good, "SLO-003") == Verdict.PASS

    def test_slo_004_missing_burn_rate(self) -> None:
        bad = Inventory(slos=(make_slo(burn_rate_alert=False),))
        assert _result(bad, "SLO-004") == Verdict.FAIL

    def test_slo_005_missing_evidence_ref(self) -> None:
        bad = Inventory(slos=(make_slo(evidence_ref=""),))
        assert _result(bad, "SLO-005") == Verdict.FAIL

    def test_slo_006_no_consumer_measured_slo(self) -> None:
        bad = Inventory(slos=(make_slo(consumer_measured=False),))
        good = Inventory(slos=(make_slo(consumer_measured=True),))
        assert _result(bad, "SLO-006") == Verdict.FAIL
        assert _result(good, "SLO-006") == Verdict.PASS


class TestIncControls:
    def test_inc_001_paging_alert_without_resolving_runbook(self) -> None:
        bad = Inventory(alerts=(make_alert(severity="page", runbook_ref=""),))
        good = Inventory(
            alerts=(make_alert(severity="page", runbook_ref="RB-1"),),
            runbooks=(make_runbook("RB-1", ("ALR-1",)),),
        )
        assert _result(bad, "INC-001") == Verdict.FAIL
        assert _result(good, "INC-001") == Verdict.PASS

    def test_inc_002_runbook_tested_outside_window(self) -> None:
        bad = Inventory(runbooks=(make_runbook(last_tested_days_ago=200, test_window_days=90),))
        good = Inventory(runbooks=(make_runbook(last_tested_days_ago=10, test_window_days=90),))
        assert _result(bad, "INC-002") == Verdict.FAIL
        assert _result(good, "INC-002") == Verdict.PASS

    def test_inc_002_never_tested_is_a_fail_not_a_crash(self) -> None:
        inv = Inventory(runbooks=(make_runbook(last_tested_days_ago=None),))
        assert _result(inv, "INC-002") == Verdict.FAIL

    def test_inc_003_missing_severity(self) -> None:
        bad = Inventory(alerts=(make_alert(severity=""),))
        assert _result(bad, "INC-003") == Verdict.FAIL

    def test_inc_004_orphaned_alert(self) -> None:
        bad = Inventory(alerts=(make_alert(owner=""),))
        assert _result(bad, "INC-004") == Verdict.FAIL

    def test_inc_005_always_skips_on_declared_state(self) -> None:
        inv = Inventory(alerts=(make_alert(),))
        assert _result(inv, "INC-005") == Verdict.SKIP


class TestPrbControls:
    def test_prb_001_recurring_signature_without_problem_record(self) -> None:
        # PRB-001 only ever fires True when a qualifying problem exists; absence of any
        # recurring signature is a SKIP, not a FAIL, because there is nothing to open yet.
        assert _result(Inventory(), "PRB-001") == Verdict.SKIP
        good = Inventory(problems=(ProblemRecord("sig", ("I1", "I2", "I3")),))
        assert _result(good, "PRB-001") == Verdict.PASS

    def test_prb_002_missing_workaround(self) -> None:
        bad = Inventory(problems=(ProblemRecord("sig", ("I1",), workaround=""),))
        assert _result(bad, "PRB-002") == Verdict.FAIL

    def test_prb_003_missing_postmortem_ref(self) -> None:
        bad = Inventory(problems=(ProblemRecord("sig", ("I1",), postmortem_ref=""),))
        assert _result(bad, "PRB-003") == Verdict.FAIL


class TestChgControls:
    def test_chg_001_no_deploy_marker(self) -> None:
        inv = Inventory(
            services=(make_service("svc"),),
            changes=(ChangeRecord(service="svc", deploy_marker_emitted=False),),
        )
        assert _result(inv, "CHG-001") == Verdict.FAIL

    def test_chg_002_no_rollback_signal(self) -> None:
        inv = Inventory(
            services=(make_service("svc"),),
            changes=(ChangeRecord(service="svc", deploy_marker_emitted=True, rollback_signal=""),),
        )
        assert _result(inv, "CHG-002") == Verdict.FAIL

    def test_chg_003_no_verification_window(self) -> None:
        inv = Inventory(
            changes=(
                ChangeRecord(
                    service="svc", deploy_marker_emitted=True, verification_window_hours=None
                ),
            )
        )
        assert _result(inv, "CHG-003") == Verdict.FAIL

    def test_chg_004_always_skips_in_m1(self) -> None:
        assert _result(Inventory(), "CHG-004") == Verdict.SKIP


class TestCsiControls:
    def test_csi_001_needs_two_prior_runs(self) -> None:
        assert _result(Inventory(maturity_history=({"level": 2},)), "CSI-001") == Verdict.SKIP
        good = Inventory(maturity_history=({"level": 2}, {"level": 3}))
        assert _result(good, "CSI-001") == Verdict.PASS

    def test_csi_002_unwaived_prior_gap(self) -> None:
        bad = Inventory(
            maturity_history=({"open_gaps": [{"control_id": "OBS-001", "waiver": None}]},)
        )
        good = Inventory(maturity_history=({"open_gaps": []},))
        assert _result(bad, "CSI-002") == Verdict.FAIL
        assert _result(good, "CSI-002") == Verdict.PASS

    def test_csi_003_always_skips_in_m1(self) -> None:
        assert _result(Inventory(), "CSI-003") == Verdict.SKIP


class TestBcpControls:
    def test_bcp_001_no_watchdog_is_a_fail_not_a_skip(self) -> None:
        assert _result(Inventory(), "BCP-001") == Verdict.FAIL

    def test_bcp_001_watchdog_without_heartbeat(self) -> None:
        bad = Inventory(watchdogs=(WatchdogRecord("wd", (), None),))
        assert _result(bad, "BCP-001") == Verdict.FAIL

    def test_bcp_002_retention_below_audit_floor(self) -> None:
        bad = Inventory(retention=(RetentionPolicy("m", 30),))
        good = Inventory(retention=(RetentionPolicy("m", 180),))
        assert _result(bad, "BCP-002") == Verdict.FAIL
        assert _result(good, "BCP-002") == Verdict.PASS


class TestWaivers:
    def test_valid_waiver_turns_fail_into_waived(self) -> None:
        inv = Inventory(retention=(RetentionPolicy("m", 30),))
        waiver = Waiver(
            "BCP-002", reason="migration in progress", owner="sre-lead", expires=date(2099, 1, 1)
        )
        results = evaluate(inv, waivers=(waiver,))
        r = next(x for x in results if x.control_id == "BCP-002")
        assert r.verdict == Verdict.WAIVED
        assert "sre-lead" in r.evidence

    def test_expired_waiver_does_not_apply(self) -> None:
        inv = Inventory(retention=(RetentionPolicy("m", 30),))
        waiver = Waiver("BCP-002", reason="stale", owner="sre-lead", expires=date(2000, 1, 1))
        results = evaluate(inv, waivers=(waiver,), today=date(2026, 1, 1))
        r = next(x for x in results if x.control_id == "BCP-002")
        assert r.verdict == Verdict.FAIL


class TestCeilingRule:
    """O mecanismo que impede 25 controles verdes de esconderem um MUST vermelho."""

    def test_25_passes_and_1_must_fail_caps_at_level_1(
        self, minimal_good_inventory: Inventory
    ) -> None:
        # Quebra exatamente um MUST da prática monitoring-and-event-management
        # (OBS-004), deixando todos os outros controles da prática verdes.
        broken = dataclasses.replace(minimal_good_inventory, trace_id_correlation_verified=False)
        results = evaluate(broken)
        practice_results = [r for r in results if r.practice == "monitoring-and-event-management"]
        assert any(
            r.control_id == "OBS-004" and r.verdict == Verdict.FAIL for r in practice_results
        )
        green_count = sum(1 for r in practice_results if r.verdict == Verdict.PASS)
        assert green_count >= 5  # os outros controles OBS continuaram verdes

        score = score_practice(results, "monitoring-and-event-management")
        assert score.level == 1
        assert score.ceiling_control == "OBS-004"

    def test_all_must_pass_and_one_should_fail_caps_at_level_2(
        self, minimal_good_inventory: Inventory
    ) -> None:
        broken = dataclasses.replace(
            minimal_good_inventory,
            cardinality_budgets=(MetricCardinalityBudget("svc.latency_ms", None),),
        )
        results = evaluate(broken)
        score = score_practice(results, "monitoring-and-event-management")
        assert score.level == 2
        assert score.ceiling_control == ""

    def test_fully_clean_practice_reaches_level_3_or_4(
        self, minimal_good_inventory: Inventory
    ) -> None:
        results = evaluate(minimal_good_inventory)
        score = score_practice(results, "monitoring-and-event-management")
        assert score.level >= 3

    def test_practice_with_only_skips_scores_zero(self, empty_inventory: Inventory) -> None:
        results = evaluate(empty_inventory)
        score = score_practice(results, "change-enablement")
        assert score.level == 0


class TestScoreAllAndOverall:
    def test_score_all_covers_every_practice_in_the_catalog(
        self, minimal_good_inventory: Inventory
    ) -> None:
        results = evaluate(minimal_good_inventory)
        scores = score_all(results)
        practices_in_catalog = {c.practice for c in CONTROLS}
        assert {s.practice for s in scores} == practices_in_catalog

    def test_overall_maturity_is_mean_of_practice_levels(
        self, minimal_good_inventory: Inventory
    ) -> None:
        results = evaluate(minimal_good_inventory)
        scores = score_all(results)
        expected = round(sum(s.level for s in scores) / len(scores), 2)
        assert overall_maturity(scores) == expected

    def test_overall_maturity_of_empty_scores_is_zero(self) -> None:
        assert overall_maturity(()) == 0.0
