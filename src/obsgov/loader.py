"""Carrega um :class:`obsgov.model.Inventory` a partir de um diretório de fontes JSON declaradas.

Cinco arquivos, os mesmos nomes que o plano usa:

    service-catalog.json
    slo.json
    alerts.json
    runbooks.json
    change-log.json   (opcional: problems/changes/watchdogs/retention/collector)

Um arquivo opcional ausente degrada para uma tupla vazia, não um erro: um repo que
ainda não declarou problemas é um finding para o avaliador (o PRB-001 não tem contra o
que checar), não um crash do loader. Um arquivo *obrigatório* ausente é um
:class:`LoaderError`, porque "sem catálogo de serviço" é uma falha diferente de
"nenhum serviço declarado".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

REQUIRED_FILES = ("service-catalog.json", "slo.json", "alerts.json", "runbooks.json")
OPTIONAL_FILE = "change-log.json"


class LoaderError(ValueError):
    """Uma fonte declarada está ausente, ilegível ou malformada."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LoaderError(f"fonte obrigatória ausente: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LoaderError(f"JSON malformado em {path}: {exc}") from exc


def _services(raw: list[dict]) -> tuple[ServiceEntry, ...]:
    return tuple(
        ServiceEntry(
            name=r["name"],
            tier=r["tier"],
            owner=r["owner"],
            depends_on=tuple(r.get("depends_on", ())),
            signals=tuple(r.get("signals", ())),
        )
        for r in raw
    )


def _slos(raw: list[dict]) -> tuple[SLO, ...]:
    out = []
    for r in raw:
        budget = r.get("error_budget", {}) or {}
        out.append(
            SLO(
                service=r["service"],
                sli_name=r["sli_name"],
                sli_metric=r["sli_metric"],
                target_pct=float(r["target_pct"]),
                window_days=int(r["window_days"]),
                owner=r.get("owner", ""),
                review_cadence_days=int(r.get("review_cadence_days", 0)),
                error_budget=ErrorBudgetPolicy(consequence=budget.get("consequence", "")),
                burn_rate_alert=bool(r.get("burn_rate_alert", False)),
                evidence_ref=r.get("evidence_ref", ""),
                consumer_measured=bool(r.get("consumer_measured", False)),
            )
        )
    return tuple(out)


def _alerts(raw: list[dict]) -> tuple[AlertRule, ...]:
    return tuple(
        AlertRule(
            id=r["id"],
            service=r["service"],
            metric=r["metric"],
            severity=r.get("severity", ""),
            runbook_ref=r.get("runbook_ref", ""),
            owner=r.get("owner", ""),
        )
        for r in raw
    )


def _runbooks(raw: list[dict]) -> tuple[RunbookEntry, ...]:
    return tuple(
        RunbookEntry(
            id=r["id"],
            title=r.get("title", r["id"]),
            resolves=tuple(r.get("resolves", ())),
            last_tested_days_ago=r.get("last_tested_days_ago"),
            test_window_days=int(r.get("test_window_days", 90)),
        )
        for r in raw
    )


def _problems(raw: list[dict]) -> tuple[ProblemRecord, ...]:
    return tuple(
        ProblemRecord(
            signature=r["signature"],
            incident_refs=tuple(r.get("incident_refs", ())),
            workaround=r.get("workaround", ""),
            postmortem_ref=r.get("postmortem_ref", ""),
        )
        for r in raw
    )


def _changes(raw: list[dict]) -> tuple[ChangeRecord, ...]:
    return tuple(
        ChangeRecord(
            service=r["service"],
            deploy_marker_emitted=bool(r.get("deploy_marker_emitted", False)),
            rollback_signal=r.get("rollback_signal", ""),
            verification_window_hours=r.get("verification_window_hours"),
        )
        for r in raw
    )


def _watchdogs(raw: list[dict]) -> tuple[WatchdogRecord, ...]:
    return tuple(
        WatchdogRecord(
            name=r["name"],
            monitors=tuple(r.get("monitors", ())),
            heartbeat_interval_minutes=r.get("heartbeat_interval_minutes"),
        )
        for r in raw
    )


def _retention(raw: list[dict]) -> tuple[RetentionPolicy, ...]:
    return tuple(
        RetentionPolicy(signal=r["signal"], retention_days=int(r["retention_days"])) for r in raw
    )


def _collector_attrs(raw: list[dict]) -> tuple[CollectorAttribute, ...]:
    return tuple(
        CollectorAttribute(name=r["name"], otel_semantic=bool(r.get("otel_semantic", False)))
        for r in raw
    )


def _cardinality(raw: list[dict]) -> tuple[MetricCardinalityBudget, ...]:
    return tuple(
        MetricCardinalityBudget(metric=r["metric"], max_series=r.get("max_series")) for r in raw
    )


def load_inventory(directory: str | Path) -> Inventory:
    """Carrega e monta as cinco fontes declaradas em um único :class:`Inventory`."""
    base = Path(directory)
    if not base.is_dir():
        raise LoaderError(f"não é um diretório: {base}")

    for required in REQUIRED_FILES:
        if not (base / required).is_file():
            raise LoaderError(f"fonte obrigatória ausente: {base / required}")

    services = _services(_read_json(base / "service-catalog.json"))
    slos = _slos(_read_json(base / "slo.json"))
    alerts = _alerts(_read_json(base / "alerts.json"))
    runbooks = _runbooks(_read_json(base / "runbooks.json"))

    extra: dict[str, Any] = {}
    optional_path = base / OPTIONAL_FILE
    if optional_path.is_file():
        extra = _read_json(optional_path)

    return Inventory(
        services=services,
        slos=slos,
        alerts=alerts,
        runbooks=runbooks,
        problems=_problems(extra.get("problems", [])),
        changes=_changes(extra.get("changes", [])),
        watchdogs=_watchdogs(extra.get("watchdogs", [])),
        retention=_retention(extra.get("retention", [])),
        collector_attributes=_collector_attrs(extra.get("collector_attributes", [])),
        cardinality_budgets=_cardinality(extra.get("cardinality_budgets", [])),
        trace_id_correlation_verified=bool(extra.get("trace_id_correlation_verified", False)),
        maturity_history=tuple(extra.get("maturity_history", [])),
    )
