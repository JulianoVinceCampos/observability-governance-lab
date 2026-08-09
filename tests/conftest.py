"""Shared fixtures: minimal builders for each dataclass, so control tests stay short."""

from __future__ import annotations

import pytest

from obsgov.model import (
    SLO,
    AlertRule,
    ChangeRecord,
    CollectorAttribute,
    ErrorBudgetPolicy,
    Inventory,
    MetricCardinalityBudget,
    ProblemRecord,
    RetentionPolicy,
    RunbookEntry,
    ServiceEntry,
    WatchdogRecord,
)


def make_service(
    name: str = "svc", tier: str = "critical", signals: tuple[str, ...] = (), **kw
) -> ServiceEntry:
    return ServiceEntry(name=name, tier=tier, owner=kw.pop("owner", "team"), signals=signals, **kw)


def make_slo(service: str = "svc", consequence: str = "page the owner", **kw) -> SLO:
    return SLO(
        service=service,
        sli_name=kw.pop("sli_name", "availability"),
        sli_metric=kw.pop("sli_metric", "svc.errors_total"),
        target_pct=kw.pop("target_pct", 99.9),
        window_days=kw.pop("window_days", 30),
        owner=kw.pop("owner", "team"),
        review_cadence_days=kw.pop("review_cadence_days", 30),
        error_budget=ErrorBudgetPolicy(consequence=consequence),
        burn_rate_alert=kw.pop("burn_rate_alert", True),
        evidence_ref=kw.pop("evidence_ref", "incident:ref"),
        consumer_measured=kw.pop("consumer_measured", False),
    )


def make_alert(
    id_: str = "ALR-1", service: str = "svc", metric: str = "svc.errors_total", **kw
) -> AlertRule:
    return AlertRule(
        id=id_,
        service=service,
        metric=metric,
        severity=kw.pop("severity", "page"),
        runbook_ref=kw.pop("runbook_ref", "RB-1"),
        owner=kw.pop("owner", "team"),
    )


def make_runbook(id_: str = "RB-1", resolves: tuple[str, ...] = ("ALR-1",), **kw) -> RunbookEntry:
    return RunbookEntry(
        id=id_,
        title=kw.pop("title", id_),
        resolves=resolves,
        last_tested_days_ago=kw.pop("last_tested_days_ago", 10),
        test_window_days=kw.pop("test_window_days", 90),
    )


@pytest.fixture
def empty_inventory() -> Inventory:
    return Inventory()


@pytest.fixture
def minimal_good_inventory() -> Inventory:
    """One critical service with everything a MUST control wants to see passing."""
    return Inventory(
        services=(
            make_service(
                "svc",
                signals=(
                    "svc.latency_ms",
                    "svc.requests_total",
                    "svc.errors_total",
                    "svc.pool_active",
                ),
            ),
        ),
        slos=(make_slo("svc"),),
        alerts=(make_alert("ALR-1", "svc", "svc.errors_total"),),
        runbooks=(make_runbook("RB-1", ("ALR-1",)),),
        problems=(
            ProblemRecord(
                signature="sig",
                incident_refs=("I1", "I2", "I3"),
                workaround="wa",
                postmortem_ref="pm",
            ),
        ),
        changes=(
            ChangeRecord(
                service="svc",
                deploy_marker_emitted=True,
                rollback_signal="alert X",
                verification_window_hours=1,
            ),
        ),
        watchdogs=(
            WatchdogRecord(name="wd", monitors=("collector",), heartbeat_interval_minutes=5),
        ),
        retention=(RetentionPolicy(signal="svc.errors_total", retention_days=180),),
        collector_attributes=(
            CollectorAttribute("service.name", True),
            CollectorAttribute("trace_id", True),
            CollectorAttribute("span_id", True),
        ),
        cardinality_budgets=(MetricCardinalityBudget("svc.latency_ms", 500),),
        trace_id_correlation_verified=True,
    )
