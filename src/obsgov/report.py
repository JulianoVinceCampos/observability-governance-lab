"""Renderiza os resultados da avaliação em markdown, JSON ou SARIF.

Markdown é para um humano lendo o PR. JSON é o par legível por máquina (e é dele que
``maturity_history`` é alimentado). SARIF é o que transforma um FAIL em finding na aba
Security do GitHub. A maioria das ferramentas de compliance nunca faz isso, e vale a
pena porque muda *onde* o gap aparece para quem lê.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from obsgov.evaluator import ControlResult, PracticeScore, Verdict, overall_maturity

SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)


def to_json(results: tuple[ControlResult, ...], scores: tuple[PracticeScore, ...]) -> dict:
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "overall_maturity": overall_maturity(scores),
        "practices": [
            {
                "practice": s.practice,
                "level": s.level,
                "ceiling_control": s.ceiling_control,
                "counts": s.counts,
            }
            for s in scores
        ],
        "controls": [
            {
                "id": r.control_id,
                "severity": r.severity.value,
                "practice": r.practice,
                "cobit": list(r.cobit),
                "verdict": r.verdict.value,
                "evidence": r.evidence,
                "remediation": r.remediation,
            }
            for r in results
        ],
    }


def to_markdown(results: tuple[ControlResult, ...], scores: tuple[PracticeScore, ...]) -> str:
    lines = [
        "# Relatório de governança de observabilidade",
        "",
        f"**Maturidade geral: {overall_maturity(scores)} / 5**",
        "",
        "## Maturidade por prática",
        "",
        "| Prática | Nível | Controle de teto | PASS | FAIL | WAIVED | SKIP |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        c = s.counts or {}
        lines.append(
            f"| {s.practice} | {s.level} | {s.ceiling_control or '-'} | "
            f"{c.get('PASS', 0)} | {c.get('FAIL', 0)} | {c.get('WAIVED', 0)} | {c.get('SKIP', 0)} |"
        )

    lines += [
        "",
        "## Controles",
        "",
        "| ID | Severidade | Verdict | Evidência | Remediação |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        remediation = r.remediation or "-"
        row = (
            f"| `{r.control_id}` | {r.severity.value} | **{r.verdict.value}** | "
            f"{r.evidence} | {remediation} |"
        )
        lines.append(row)

    failed = [r for r in results if r.verdict == Verdict.FAIL]
    if failed:
        lines += ["", "## Gaps abertos", ""]
        for r in failed:
            lines.append(f"- **{r.control_id}** ({r.severity.value}, {r.practice}): {r.evidence}")
            lines.append(f"  - remediação: {r.remediation}")

    return "\n".join(lines) + "\n"


def to_sarif(results: tuple[ControlResult, ...]) -> dict:
    rules = [
        {
            "id": r.control_id,
            "shortDescription": {"text": r.evidence[:120]},
            "properties": {
                "severity": r.severity.value,
                "practice": r.practice,
                "cobit": list(r.cobit),
            },
        }
        for r in results
    ]
    findings = [
        {
            "ruleId": r.control_id,
            "level": "error" if r.severity.value == "MUST" else "warning",
            "message": {"text": f"{r.evidence} | remediação: {r.remediation}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": "service-catalog.json"},
                        "region": {"startLine": 1},
                    }
                }
            ],
        }
        for r in results
        if r.verdict == Verdict.FAIL
    ]
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "obsgov",
                        "informationUri": "https://github.com/JulianoVinceCampos/observability-governance-lab",
                        "rules": rules,
                    }
                },
                "results": findings,
            }
        ],
    }


def dump_json(results: tuple[ControlResult, ...], scores: tuple[PracticeScore, ...]) -> str:
    return json.dumps(to_json(results, scores), indent=2, ensure_ascii=False)


def dump_sarif(results: tuple[ControlResult, ...]) -> str:
    return json.dumps(to_sarif(results), indent=2, ensure_ascii=False)
