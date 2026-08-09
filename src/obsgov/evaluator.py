"""Motor de avaliação: registro de controles, verdicts e o scorer de maturidade.

Regras de desenho que importam mais que o código (ver plano, seção 3.3/3.4):

  * Um controle é uma função pura ``Inventory -> Verdict``. Nenhum controle altera o
    inventário nem fala com um probe diretamente no M1. Probes são coisa do M2 e devem
    popular o inventário *antes* da avaliação, não ser chamados no meio do check. Isso
    mantém todo controle puro e trivialmente testável.
  * ``SKIP`` não é ``PASS``. Um controle com pré-requisito não satisfeito (ex.: nenhum
    serviço crítico declarado) é marcado como skip com um motivo, e skips são
    reportados separados dos passes. Juntar os dois é o jeito mais comum de um score de
    maturidade mentir.
  * A regra de teto vive em :func:`score_practice`, não espalhada pelos controles: um
    MUST reprovado trava a prática no nível 1, não importa quantos SHOULD/MAY passem.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum

from obsgov.model import Inventory

# Os nomes de prática ITIL 4 usados aqui são rótulos próprios para agrupar controles;
# ver NOTICE.md. Nenhum texto normativo do ITIL é reproduzido.
Practice = str
CobitObjective = str

RECURRING_INCIDENT_THRESHOLD = 3
"""Quantos incidentes vinculados tornam uma assinatura 'recorrente' para o PRB-001."""

MIN_RUNS_FOR_TREND = 2
"""Quantas entradas anteriores em maturity_history o CSI-001 exige para chamar de tendência."""

AUDIT_RETENTION_FLOOR_DAYS = 90
"""Retenção mínima de telemetria que o BCP-002 exige."""

GOLDEN_SIGNAL_COUNT = 4
"""Latência, tráfego, erro, saturação: os quatro que o OBS-001 exige."""

REQUIRED_LOG_CONTEXT_FIELDS = 2
"""trace_id + span_id: o par que o OBS-005 exige no pipeline de log."""


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    WAIVED = "WAIVED"


class Severity(str, Enum):
    MUST = "MUST"
    SHOULD = "SHOULD"
    MAY = "MAY"


@dataclass(frozen=True, slots=True)
class Waiver:
    control_id: str
    reason: str
    owner: str
    expires: date


@dataclass(frozen=True, slots=True)
class ControlResult:
    control_id: str
    severity: Severity
    practice: Practice
    cobit: tuple[CobitObjective, ...]
    verdict: Verdict
    evidence: str
    remediation: str = ""


@dataclass(frozen=True, slots=True)
class Control:
    id: str
    severity: Severity
    practice: Practice
    cobit: tuple[CobitObjective, ...]
    title: str
    remediation: str
    check: Callable[[Inventory], tuple[bool | None, str]]
    """``check`` devolve ``(outcome, evidence)``.

    ``outcome`` é ``True`` (pass), ``False`` (fail), ou ``None`` (pré-requisito não
    satisfeito -> SKIP). ``evidence`` é sempre uma string curta e legível. Até um
    SKIP precisa dizer *por quê*.
    """


def _now() -> datetime:
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------------- OBS ---


def _obs_001(inv: Inventory) -> tuple[bool | None, str]:
    critical = inv.critical_services()
    if not critical:
        return None, "nenhum serviço tier=critical declarado"
    missing = [s.name for s in critical if len(s.signals) < GOLDEN_SIGNAL_COUNT]
    if missing:
        return False, f"faltam >=4 golden signals para: {', '.join(missing)}"
    return True, f"todos os {len(critical)} serviço(s) crítico(s) declaram >=4 sinais"


def _obs_002(inv: Inventory) -> tuple[bool | None, str]:
    """Um sinal 'resolve' se for um nome de métrica declarado e não-vazio.

    O M1 não tem backend vivo para consultar (isso é o probe do M2). Aqui um sinal só
    conta como resolvido se não for o sentinela ``UNVERIFIED_METRIC`` usado pelos
    fixtures para representar um nome morto/inconsultável, a mesma disciplina de "só
    entra o que responde" do catálogo de métricas real que inspirou este projeto.
    """
    dead = [
        (s.name, sig)
        for s in inv.services
        for sig in s.signals
        if sig.startswith("UNVERIFIED_METRIC")
    ]
    if not inv.services:
        return None, "nenhum serviço declarado"
    if dead:
        sample = ", ".join(f"{svc}:{sig}" for svc, sig in dead[:3])
        return False, f"{len(dead)} sinal(is) não resolvem para nada, ex.: {sample}"
    return True, "todo sinal declarado resolve para um nome de métrica real"


def _obs_003(inv: Inventory) -> tuple[bool | None, str]:
    known_metrics = {sig for s in inv.services for sig in s.signals} | {
        slo.sli_metric for slo in inv.slos
    }
    if not inv.alerts:
        return None, "nenhuma regra de alerta declarada"
    orphans = [a.id for a in inv.alerts if a.metric not in known_metrics]
    if orphans:
        return False, f"alerta(s) referenciam métrica desconhecida: {', '.join(orphans)}"
    return True, f"todos os {len(inv.alerts)} alerta(s) referenciam uma métrica declarada"


def _obs_004(inv: Inventory) -> tuple[bool | None, str]:
    if inv.trace_id_correlation_verified:
        return (
            True,
            "trace_id correlaciona trace, log e métrica para a mesma request "
            "(verificado por probe)",
        )
    return (
        False,
        "sem correlação verificada de trace_id entre os três pilares (probe do M2 pendente)",
    )


def _obs_005(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.collector_attributes:
        return None, "nenhum atributo de collector declarado"
    trace_ctx = {a.name for a in inv.collector_attributes if a.name in {"trace_id", "span_id"}}
    if len(trace_ctx) < REQUIRED_LOG_CONTEXT_FIELDS:
        missing = {"trace_id", "span_id"} - trace_ctx
        return False, f"pipeline de log sem campo(s) de contexto: {', '.join(sorted(missing))}"
    return True, "pipeline de log carrega trace_id e span_id"


def _obs_006(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.cardinality_budgets:
        return None, "nenhum orçamento de cardinalidade declarado"
    unbounded = [b.metric for b in inv.cardinality_budgets if b.max_series is None]
    if unbounded:
        return False, f"métrica(s) sem orçamento de cardinalidade: {', '.join(unbounded)}"
    return (
        True,
        f"todas as {len(inv.cardinality_budgets)} métrica(s) têm orçamento de cardinalidade",
    )


def _obs_007(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.collector_attributes:
        return None, "nenhum atributo de collector declarado"
    non_semantic = [a.name for a in inv.collector_attributes if not a.otel_semantic]
    if non_semantic:
        return False, f"atributo(s) fora da convenção semântica: {', '.join(non_semantic)}"
    return True, "todos os atributos declarados seguem as convenções semânticas do OTel"


# --------------------------------------------------------------------------- SLO ---


def _slo_001(inv: Inventory) -> tuple[bool | None, str]:
    critical = inv.critical_services()
    if not critical:
        return None, "nenhum serviço tier=critical declarado"
    missing = [s.name for s in critical if not inv.slos_for(s.name)]
    if missing:
        return False, f"nenhum SLO declarado para serviço(s) crítico(s): {', '.join(missing)}"
    return True, f"todos os {len(critical)} serviço(s) crítico(s) têm >=1 SLO"


def _slo_002(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.slos:
        return None, "nenhum SLO declarado"
    bad = [s.sli_name for s in inv.slos if not s.owner or s.review_cadence_days <= 0]
    if bad:
        return False, f"SLO(s) sem dono ou cadência de revisão: {', '.join(bad)}"
    return True, f"todos os {len(inv.slos)} SLO(s) têm dono e cadência de revisão"


def _slo_003(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.slos:
        return None, "nenhum SLO declarado"
    bad = [s.sli_name for s in inv.slos if not s.error_budget.consequence.strip()]
    if bad:
        return False, f"SLO(s) sem consequência de error budget declarada: {', '.join(bad)}"
    return True, f"todos os {len(inv.slos)} SLO(s) declaram consequência de error budget"


def _slo_004(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.slos:
        return None, "nenhum SLO declarado"
    missing = [s.sli_name for s in inv.slos if not s.burn_rate_alert]
    if missing:
        return False, f"SLO(s) sem alerta de burn-rate multi-janela: {', '.join(missing)}"
    return True, f"todos os {len(inv.slos)} SLO(s) têm alerta de burn-rate"


def _slo_005(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.slos:
        return None, "nenhum SLO declarado"
    missing = [s.sli_name for s in inv.slos if not s.evidence_ref.strip()]
    if missing:
        return False, f"SLO(s) sem referência de evidência: {', '.join(missing)}"
    return True, f"todos os {len(inv.slos)} SLO(s) rastreiam a um incidente/jornada de referência"


def _slo_006(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.slos:
        return None, "nenhum SLO declarado"
    n = sum(1 for s in inv.slos if s.consumer_measured)
    if n == 0:
        return False, "nenhum SLO medido da perspectiva do consumidor"
    return True, f"{n}/{len(inv.slos)} SLO(s) medidos da perspectiva do consumidor"


# --------------------------------------------------------------------------- INC ---


def _inc_001(inv: Inventory) -> tuple[bool | None, str]:
    paging = [a for a in inv.alerts if a.severity in {"page", "critical"}]
    if not paging:
        return None, "nenhum alerta de paging declarado"
    unresolved = [a.id for a in paging if not inv.runbook_by_id(a.runbook_ref)]
    if unresolved:
        return False, f"alerta(s) de paging sem runbook que resolva: {', '.join(unresolved)}"
    return True, f"todos os {len(paging)} alerta(s) de paging referenciam um runbook que os resolve"


def _inc_002(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.runbooks:
        return None, "nenhum runbook declarado"
    stale = [
        r.id
        for r in inv.runbooks
        if r.last_tested_days_ago is None or r.last_tested_days_ago > r.test_window_days
    ]
    if stale:
        return False, f"runbook(s) testado(s) fora da janela declarada: {', '.join(stale)}"
    return True, f"todos os {len(inv.runbooks)} runbook(s) testados dentro da janela declarada"


def _inc_003(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.alerts:
        return None, "nenhuma regra de alerta declarada"
    missing = [a.id for a in inv.alerts if not a.severity]
    if missing:
        return False, f"alerta(s) sem classificação de severidade: {', '.join(missing)}"
    return True, f"todos os {len(inv.alerts)} alerta(s) têm severidade"


def _inc_004(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.alerts:
        return None, "nenhuma regra de alerta declarada"
    orphans = [a.id for a in inv.alerts if not a.owner]
    if orphans:
        return False, f"alerta(s) órfão(s) (sem dono): {', '.join(orphans)}"
    return True, f"todos os {len(inv.alerts)} alerta(s) têm dono"


def _inc_005(inv: Inventory) -> tuple[bool | None, str]:  # noqa: ARG001 - adiado para o M2, exige probe vivo
    return (
        None,
        "razão de ruído exige histórico real de paging, não avaliado só com estado declarado",
    )


# --------------------------------------------------------------------------- PRB ---


def _prb_001(inv: Inventory) -> tuple[bool | None, str]:
    recurring = [p for p in inv.problems if len(p.incident_refs) >= RECURRING_INCIDENT_THRESHOLD]
    if not recurring:
        return None, "nenhuma assinatura com >=3 incidentes registrados"
    return True, f"{len(recurring)} assinatura(s) recorrente(s) têm registro de problema"


def _prb_002(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.problems:
        return None, "nenhum registro de problema declarado"
    missing = [p.signature for p in inv.problems if not p.workaround.strip()]
    if missing:
        return False, f"problema(s) sem workaround documentado: {', '.join(missing)}"
    return True, f"todos os {len(inv.problems)} problema(s) documentam um workaround"


def _prb_003(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.problems:
        return None, "nenhum registro de problema declarado"
    missing = [p.signature for p in inv.problems if not p.postmortem_ref.strip()]
    if missing:
        return False, f"problema(s) sem postmortem vinculado: {', '.join(missing)}"
    return True, f"todos os {len(inv.problems)} problema(s) vinculam um postmortem"


# --------------------------------------------------------------------------- CHG ---


def _chg_001(inv: Inventory) -> tuple[bool | None, str]:
    critical_names = {s.name for s in inv.critical_services()}
    relevant = [c for c in inv.changes if c.service in critical_names]
    if not relevant:
        return None, "nenhum registro de mudança para serviço crítico"
    missing = [c.service for c in relevant if not c.deploy_marker_emitted]
    if missing:
        return False, f"mudança(s) sem marcador de deploy na timeline: {', '.join(missing)}"
    return True, f"todas as {len(relevant)} mudança(s) emitem marcador de deploy"


def _chg_002(inv: Inventory) -> tuple[bool | None, str]:
    critical_names = {s.name for s in inv.critical_services()}
    relevant = [c for c in inv.changes if c.service in critical_names]
    if not relevant:
        return None, "nenhum registro de mudança para serviço crítico"
    missing = [c.service for c in relevant if not c.rollback_signal.strip()]
    if missing:
        return False, f"mudança(s) sem sinal de rollback declarado: {', '.join(missing)}"
    return True, f"todas as {len(relevant)} mudança(s) declaram sinal de rollback"


def _chg_003(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.changes:
        return None, "nenhum registro de mudança declarado"
    missing = [c.service for c in inv.changes if not c.verification_window_hours]
    if missing:
        return False, f"mudança(s) sem janela de verificação pós-mudança: {', '.join(missing)}"
    return True, f"todas as {len(inv.changes)} mudança(s) declaram janela de verificação"


def _chg_004(inv: Inventory) -> tuple[bool | None, str]:  # noqa: ARG001 - adiado para o M2, exige probe vivo
    return None, "checagem de drift exige probe de deploy vivo, adiada para o M2"


# --------------------------------------------------------------------------- CSI ---


def _csi_001(inv: Inventory) -> tuple[bool | None, str]:
    if len(inv.maturity_history) < MIN_RUNS_FOR_TREND:
        return None, "menos de 2 execuções anteriores registradas"
    return (
        True,
        f"{len(inv.maturity_history)} execução(ões) anterior(es) registradas como tendência",
    )


def _csi_002(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.maturity_history:
        return None, "nenhuma execução anterior registrada"
    last = inv.maturity_history[-1]
    open_gaps = last.get("open_gaps", [])
    unwaived = [g for g in open_gaps if not g.get("waiver")]
    if unwaived:
        ids = ", ".join(g.get("control_id", "?") for g in unwaived)
        return False, f"gap(s) anterior(es) nem fechado(s) nem com waiver: {ids}"
    return True, "todo gap anterior está fechado ou tem waiver válido"


def _csi_003(inv: Inventory) -> tuple[bool | None, str]:  # noqa: ARG001 - controle de processo, não de dado
    return (
        None,
        "revisão de mudança no catálogo é controle de processo do repo, "
        "não avaliado no estado declarado",
    )


# --------------------------------------------------------------------------- BCP ---


def _bcp_001(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.watchdogs:
        return False, "nenhum watchdog/heartbeat vigia o próprio pipeline de observabilidade"
    missing = [w.name for w in inv.watchdogs if not w.heartbeat_interval_minutes]
    if missing:
        return False, f"watchdog(s) sem intervalo de heartbeat: {', '.join(missing)}"
    return True, f"{len(inv.watchdogs)} watchdog(s) com heartbeat declarado"


def _bcp_002(inv: Inventory) -> tuple[bool | None, str]:
    if not inv.retention:
        return None, "nenhuma política de retenção declarada"
    too_short = [r.signal for r in inv.retention if r.retention_days < AUDIT_RETENTION_FLOOR_DAYS]
    if too_short:
        return (
            False,
            f"sinal(is) retido(s) abaixo do piso de auditoria de 90 dias: {', '.join(too_short)}",
        )
    return True, f"todos os {len(inv.retention)} sinal(is) retidos por >= 90 dias"


CONTROLS: tuple[Control, ...] = (
    Control(
        "OBS-001",
        Severity.MUST,
        "monitoring-and-event-management",
        ("DSS01",),
        "serviço crítico declara os 4 golden signals",
        "declarar sinais de latência/tráfego/erro/saturação para todo serviço tier=critical",
        _obs_001,
    ),
    Control(
        "OBS-002",
        Severity.MUST,
        "monitoring-and-event-management",
        ("DSS01", "MEA01"),
        "todo sinal declarado resolve para uma métrica real",
        "remover ou corrigir nomes de sinal que não resolvem no backend",
        _obs_002,
    ),
    Control(
        "OBS-003",
        Severity.MUST,
        "monitoring-and-event-management",
        ("DSS01",),
        "nenhum alerta referencia métrica/atributo morto",
        "apontar a regra de alerta para uma métrica que de fato é emitida",
        _obs_003,
    ),
    Control(
        "OBS-004",
        Severity.MUST,
        "monitoring-and-event-management",
        ("DSS01",),
        "trace_id correlaciona trace, log e métrica",
        "conectar a correlação trace/log (ex.: dd.logs.injection ou propagação de contexto OTel)",
        _obs_004,
    ),
    Control(
        "OBS-005",
        Severity.MUST,
        "monitoring-and-event-management",
        ("DSS01",),
        "pipeline de log carrega trace_id/span_id",
        "injetar trace_id/span_id no contexto de log, não só texto livre",
        _obs_005,
    ),
    Control(
        "OBS-006",
        Severity.SHOULD,
        "monitoring-and-event-management",
        ("DSS01",),
        "orçamento de cardinalidade de métrica declarado",
        "definir um orçamento de max-series por métrica de alta cardinalidade",
        _obs_006,
    ),
    Control(
        "OBS-007",
        Severity.SHOULD,
        "monitoring-and-event-management",
        ("DSS01",),
        "atributos de recurso seguem convenções semânticas do OTel",
        "renomear atributos para bater com as convenções semânticas do OTel",
        _obs_007,
    ),
    Control(
        "SLO-001",
        Severity.MUST,
        "service-level-management",
        ("APO09",),
        "todo serviço crítico tem um SLO",
        "definir ao menos um SLO (SLI, alvo, janela) por serviço crítico",
        _slo_001,
    ),
    Control(
        "SLO-002",
        Severity.MUST,
        "service-level-management",
        ("APO09",),
        "todo SLO tem dono e cadência de revisão",
        "atribuir um dono e uma cadência de revisão ao SLO",
        _slo_002,
    ),
    Control(
        "SLO-003",
        Severity.MUST,
        "service-level-management",
        ("APO09", "MEA01"),
        "o error budget de todo SLO tem consequência",
        "declarar o que de fato acontece quando o error budget se esgota",
        _slo_003,
    ),
    Control(
        "SLO-004",
        Severity.SHOULD,
        "service-level-management",
        ("APO09",),
        "alerta de burn-rate, não limiar fixo",
        "configurar alerta de burn-rate multi-janela para o SLO",
        _slo_004,
    ),
    Control(
        "SLO-005",
        Severity.SHOULD,
        "service-level-management",
        ("APO09",),
        "SLO rastreia a uma evidência",
        "vincular o SLO ao histórico de incidente ou jornada de usuário de origem",
        _slo_005,
    ),
    Control(
        "SLO-006",
        Severity.MAY,
        "service-level-management",
        ("APO09",),
        "SLI medido da perspectiva do consumidor",
        "adicionar uma medição do lado do consumidor onde for viável",
        _slo_006,
    ),
    Control(
        "INC-001",
        Severity.MUST,
        "incident-management",
        ("DSS02",),
        "todo alerta de paging tem runbook que resolve",
        "anexar uma referência de runbook que de fato resolve o alerta",
        _inc_001,
    ),
    Control(
        "INC-002",
        Severity.MUST,
        "incident-management",
        ("DSS02",),
        "todo runbook foi testado dentro da janela",
        "retestar o runbook e atualizar last_tested_days_ago",
        _inc_002,
    ),
    Control(
        "INC-003",
        Severity.MUST,
        "incident-management",
        ("DSS02",),
        "classificação de severidade está completa",
        "atribuir severidade a toda regra de alerta",
        _inc_003,
    ),
    Control(
        "INC-004",
        Severity.SHOULD,
        "incident-management",
        ("DSS02",),
        "nenhum alerta órfão",
        "atribuir dono a toda regra de alerta",
        _inc_004,
    ),
    Control(
        "INC-005",
        Severity.SHOULD,
        "incident-management",
        ("DSS02",),
        "razão de ruído de alerta medida",
        "instrumentar a razão reconhecido-vs-ignorado por alerta",
        _inc_005,
    ),
    Control(
        "PRB-001",
        Severity.MUST,
        "problem-management",
        ("DSS03",),
        "assinatura de incidente recorrente tem registro de problema",
        "abrir um registro de problema para a assinatura recorrente",
        _prb_001,
    ),
    Control(
        "PRB-002",
        Severity.SHOULD,
        "problem-management",
        ("DSS03",),
        "todo problema documenta um workaround",
        "documentar o workaround do erro conhecido",
        _prb_002,
    ),
    Control(
        "PRB-003",
        Severity.SHOULD,
        "problem-management",
        ("DSS03",),
        "todo problema vincula um postmortem",
        "vincular o postmortem do(s) incidente(s) de origem do problema",
        _prb_003,
    ),
    Control(
        "CHG-001",
        Severity.MUST,
        "change-enablement",
        ("BAI06",),
        "mudança emite marcador de deploy",
        "emitir um marcador de deploy na timeline de telemetria",
        _chg_001,
    ),
    Control(
        "CHG-002",
        Severity.MUST,
        "change-enablement",
        ("BAI06", "BAI10"),
        "mudança declara seu sinal de rollback",
        "declarar qual SLI/métrica detecta essa mudança falhando",
        _chg_002,
    ),
    Control(
        "CHG-003",
        Severity.SHOULD,
        "change-enablement",
        ("BAI06",),
        "janela de verificação pós-mudança declarada",
        "declarar uma janela de verificação com checagem automática de burn",
        _chg_003,
    ),
    Control(
        "CHG-004",
        Severity.SHOULD,
        "change-enablement",
        ("BAI06",),
        "catálogo confere com a realidade implantada",
        "reconciliar o catálogo de serviço contra um probe de deploy vivo",
        _chg_004,
    ),
    Control(
        "CSI-001",
        Severity.SHOULD,
        "continual-improvement",
        ("MEA01", "APO11"),
        "maturidade registrada como tendência, não ponto único",
        "rodar o avaliador repetidamente e manter o histórico",
        _csi_001,
    ),
    Control(
        "CSI-002",
        Severity.MUST,
        "continual-improvement",
        ("MEA01", "APO11"),
        "gaps anteriores fechados ou com waiver",
        "fechar o gap ou registrar um waiver com dono e validade",
        _csi_002,
    ),
    Control(
        "CSI-003",
        Severity.MAY,
        "continual-improvement",
        ("APO11",),
        "mudanças no catálogo de controle são revisadas",
        "exigir revisão em mudanças no próprio catálogo de controle",
        _csi_003,
    ),
    Control(
        "BCP-001",
        Severity.MUST,
        "service-continuity",
        ("DSS04",),
        "o pipeline de observabilidade é vigiado por algo",
        "adicionar um heartbeat/dead-man switch vigiando o próprio pipeline",
        _bcp_001,
    ),
    Control(
        "BCP-002",
        Severity.SHOULD,
        "service-continuity",
        ("DSS04",),
        "retenção de telemetria atende a janela de auditoria",
        "estender a retenção do sinal abaixo do piso de 90 dias",
        _bcp_002,
    ),
)


def _waiver_for(control_id: str, waivers: tuple[Waiver, ...], today: date) -> Waiver | None:
    for w in waivers:
        if w.control_id == control_id and w.expires >= today:
            return w
    return None


def evaluate(
    inv: Inventory, waivers: tuple[Waiver, ...] = (), today: date | None = None
) -> tuple[ControlResult, ...]:
    """Roda todo controle do catálogo contra ``inv``. Puro; sem I/O."""
    today = today or _now().date()
    results = []
    for c in CONTROLS:
        outcome, evidence = c.check(inv)
        if outcome is None:
            verdict = Verdict.SKIP
        elif outcome:
            verdict = Verdict.PASS
        else:
            waiver = _waiver_for(c.id, waivers, today)
            verdict = Verdict.WAIVED if waiver else Verdict.FAIL
            if waiver:
                evidence = (
                    f"{evidence} (waiver de {waiver.owner} até {waiver.expires}: {waiver.reason})"
                )
        results.append(
            ControlResult(
                control_id=c.id,
                severity=c.severity,
                practice=c.practice,
                cobit=c.cobit,
                verdict=verdict,
                evidence=evidence,
                remediation="" if verdict == Verdict.PASS else c.remediation,
            )
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class PracticeScore:
    practice: Practice
    level: int
    ceiling_control: str = ""
    """O controle MUST que travou esta prática no nível 1, se houver."""
    counts: dict[str, int] = None  # type: ignore[assignment]


def score_practice(results: tuple[ControlResult, ...], practice: Practice) -> PracticeScore:
    """Pontua uma prática, 0-5, aplicando a regra de teto.

    Regra de teto: um único MUST reprovado trava a prática no nível 1, não importa
    quantos controles SHOULD/MAY passem. Isso é deliberado e testado. Ver
    ``test_evaluator.py::TestCeilingRule``. Sem isso, 20 passes cosméticos podem
    esconder um MUST reprovado e o score vira propaganda.
    """
    mine = tuple(r for r in results if r.practice == practice)
    counts = {v.value: sum(1 for r in mine if r.verdict == v) for v in Verdict}

    if not mine or all(r.verdict == Verdict.SKIP for r in mine):
        return PracticeScore(practice, level=0, counts=counts)

    failed_musts = [r for r in mine if r.severity == Severity.MUST and r.verdict == Verdict.FAIL]
    if failed_musts:
        return PracticeScore(
            practice, level=1, ceiling_control=failed_musts[0].control_id, counts=counts
        )

    musts = [r for r in mine if r.severity == Severity.MUST]
    musts_ok = all(r.verdict in {Verdict.PASS, Verdict.WAIVED, Verdict.SKIP} for r in musts)
    if not musts_ok:
        return PracticeScore(practice, level=1, counts=counts)

    shoulds = [r for r in mine if r.severity == Severity.SHOULD]
    shoulds_ok = all(r.verdict in {Verdict.PASS, Verdict.WAIVED, Verdict.SKIP} for r in shoulds)
    if not shoulds_ok:
        return PracticeScore(practice, level=2, counts=counts)

    # Nível 3: MUST+SHOULD limpos e verificados via CI. Neste repo, "avaliado por este
    # motor" já implica verificação automatizada, então o nível 3 é o piso uma vez que
    # as duas severidades estão limpas.
    level = 3
    mays = [r for r in mine if r.severity == Severity.MAY]
    if all(r.verdict in {Verdict.PASS, Verdict.WAIVED, Verdict.SKIP} for r in mays) and mays:
        level = 4
    return PracticeScore(practice, level=level, counts=counts)


def score_all(results: tuple[ControlResult, ...]) -> tuple[PracticeScore, ...]:
    practices = sorted({r.practice for r in results})
    return tuple(score_practice(results, p) for p in practices)


def overall_maturity(scores: tuple[PracticeScore, ...]) -> float:
    if not scores:
        return 0.0
    return round(sum(s.level for s in scores) / len(scores), 2)
