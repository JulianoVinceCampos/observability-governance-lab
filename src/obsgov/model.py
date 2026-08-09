"""Modelo de dados das cinco fontes declaradas.

Tudo aqui é um ``dataclass`` simples. Sem pydantic, sem yaml: as fontes declaradas são
JSON (ver ADR-0001), e JSON desserializa direto para esses formatos com a standard
library. A validação vive em :mod:`obsgov.loader`, não no modelo, então o modelo
continua trivialmente serializável para o gerador de relatório.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Tier = str  # "critical" | "standard" | "experimental"
Severity = str  # "MUST" | "SHOULD" | "MAY", reusado para controles e incidentes


@dataclass(frozen=True, slots=True)
class ServiceEntry:
    """Uma linha do catálogo de serviço."""

    name: str
    tier: Tier
    owner: str
    depends_on: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    """Nomes de métrica que este serviço declara como seus quatro golden signals."""


@dataclass(frozen=True, slots=True)
class ErrorBudgetPolicy:
    consequence: str
    """O que de fato acontece quando o budget se esgota. String vazia = não declarado."""


@dataclass(frozen=True, slots=True)
class SLO:
    service: str
    sli_name: str
    sli_metric: str
    target_pct: float
    window_days: int
    owner: str
    review_cadence_days: int
    error_budget: ErrorBudgetPolicy
    burn_rate_alert: bool = False
    evidence_ref: str = ""
    """Referência ao incidente/postmortem de onde este SLO foi derivado. Vazio = sem rastro."""
    consumer_measured: bool = False


@dataclass(frozen=True, slots=True)
class AlertRule:
    id: str
    service: str
    metric: str
    severity: str
    runbook_ref: str = ""
    owner: str = ""


@dataclass(frozen=True, slots=True)
class RunbookEntry:
    id: str
    title: str
    resolves: tuple[str, ...]
    """IDs de alerta que este runbook deve resolver."""
    last_tested_days_ago: int | None
    test_window_days: int


@dataclass(frozen=True, slots=True)
class ProblemRecord:
    signature: str
    incident_refs: tuple[str, ...]
    workaround: str = ""
    postmortem_ref: str = ""


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    service: str
    deploy_marker_emitted: bool
    rollback_signal: str = ""
    """Qual SLI/métrica detecta essa mudança falhando. Vazio = não declarado."""
    verification_window_hours: int | None = None


@dataclass(frozen=True, slots=True)
class WatchdogRecord:
    """Quem vigia o próprio pipeline de observabilidade (controle BCP-001)."""

    name: str
    monitors: tuple[str, ...]
    heartbeat_interval_minutes: int | None


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    signal: str
    retention_days: int


@dataclass(frozen=True, slots=True)
class CollectorAttribute:
    """Um atributo de recurso que a config do OTel Collector declara emitir."""

    name: str
    otel_semantic: bool


@dataclass(frozen=True, slots=True)
class MetricCardinalityBudget:
    metric: str
    max_series: int | None
    """None significa "nenhum orçamento declarado": um finding para o OBS-006, não um crash."""


@dataclass(frozen=True, slots=True)
class Inventory:
    """O estado declarado completo, montado a partir das cinco fontes."""

    services: tuple[ServiceEntry, ...] = ()
    slos: tuple[SLO, ...] = ()
    alerts: tuple[AlertRule, ...] = ()
    runbooks: tuple[RunbookEntry, ...] = ()
    problems: tuple[ProblemRecord, ...] = ()
    changes: tuple[ChangeRecord, ...] = ()
    watchdogs: tuple[WatchdogRecord, ...] = ()
    retention: tuple[RetentionPolicy, ...] = ()
    collector_attributes: tuple[CollectorAttribute, ...] = ()
    cardinality_budgets: tuple[MetricCardinalityBudget, ...] = ()
    trace_id_correlation_verified: bool = False
    """Definido por um probe vivo no M2. No M1 vem direto do fixture."""
    maturity_history: tuple[dict, ...] = field(default_factory=tuple)
    """Scores de execuções anteriores, da mais antiga pra mais nova. Alimenta o CSI-001.
    Vazio na primeira execução."""

    def critical_services(self) -> tuple[ServiceEntry, ...]:
        return tuple(s for s in self.services if s.tier == "critical")

    def slos_for(self, service: str) -> tuple[SLO, ...]:
        return tuple(s for s in self.slos if s.service == service)

    def alerts_for(self, service: str) -> tuple[AlertRule, ...]:
        return tuple(a for a in self.alerts if a.service == service)

    def runbook_by_id(self, runbook_id: str) -> RunbookEntry | None:
        return next((r for r in self.runbooks if r.id == runbook_id), None)
