"""Ponto de entrada de linha de comando: ``obsgov validate | score | report``.

Os três subcomandos compartilham o mesmo pipeline (load -> evaluate -> score) e
diferem só no que imprimem e no exit code que usam. ``validate`` é o feito para um
gate de CI: sai com 1 se qualquer controle de severidade MUST reprovar, então um PR
que remove uma referência de runbook de fato quebra o build.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from obsgov.evaluator import Severity, Verdict, evaluate, score_all
from obsgov.loader import LoaderError, load_inventory
from obsgov.report import dump_json, dump_sarif, to_markdown


def _load_waivers(path: str | None) -> tuple:
    from obsgov.evaluator import Waiver

    if not path:
        return ()
    import json

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        Waiver(
            control_id=w["control_id"],
            reason=w["reason"],
            owner=w["owner"],
            expires=date.fromisoformat(w["expires"]),
        )
        for w in raw
    )


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        inv = load_inventory(args.inventory)
    except LoaderError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    waivers = _load_waivers(args.waivers)
    results = evaluate(inv, waivers=waivers)
    failed_musts = [r for r in results if r.severity == Severity.MUST and r.verdict == Verdict.FAIL]

    for r in results:
        marker = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip", "WAIVED": "waiv"}[r.verdict.value]
        print(f"[{marker}] {r.control_id:10} {r.evidence}")

    if failed_musts:
        print(
            f"\n{len(failed_musts)} controle(s) MUST reprovado(s). Gate não passa.", file=sys.stderr
        )
        return 1
    print("\nTodos os controles MUST passam.")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    try:
        inv = load_inventory(args.inventory)
    except LoaderError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    waivers = _load_waivers(args.waivers)
    results = evaluate(inv, waivers=waivers)
    scores = score_all(results)

    from obsgov.evaluator import overall_maturity

    print(f"maturidade geral: {overall_maturity(scores)} / 5\n")
    for s in scores:
        ceiling = f"  <- travado por {s.ceiling_control}" if s.ceiling_control else ""
        print(f"  {s.practice:32} nível {s.level}{ceiling}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from obsgov.webapp import serve

    return serve(Path(args.data), host=args.host, port=args.port)


def cmd_report(args: argparse.Namespace) -> int:
    try:
        inv = load_inventory(args.inventory)
    except LoaderError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    waivers = _load_waivers(args.waivers)
    results = evaluate(inv, waivers=waivers)
    scores = score_all(results)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(to_markdown(results, scores), encoding="utf-8")
    (out_dir / "report.json").write_text(dump_json(results, scores), encoding="utf-8")
    (out_dir / "report.sarif").write_text(dump_sarif(results), encoding="utf-8")
    print(f"escrito {out_dir}/report.md, report.json, report.sarif")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="obsgov", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn, help_text in (
        (
            "validate",
            cmd_validate,
            "roda o gate de severidade MUST (sai com 1 se algum MUST reprovar)",
        ),
        ("score", cmd_score, "imprime o nível de maturidade por prática"),
        ("report", cmd_report, "escreve report.md / report.json / report.sarif"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("inventory", help="diretório com as cinco fontes declaradas")
        p.add_argument("--waivers", default=None, help="caminho para um arquivo waivers.json")
        if name == "report":
            p.add_argument("--out", default="out", help="diretório de saída (padrão: out)")
        p.set_defaults(func=fn)

    # `serve` recebe a raiz de data/, não um inventário: o dashboard compara os dois
    # estados, então precisa dos dois carregados.
    srv = sub.add_parser("serve", help="sobe o dashboard web read-only")
    srv.add_argument("data", nargs="?", default="data", help="raiz com os fixtures (padrão: data)")
    srv.add_argument("--host", default="127.0.0.1", help="host de bind (padrão: 127.0.0.1)")
    srv.add_argument(
        "--port",
        type=int,
        # A plataforma de deploy injeta PORT. Fixar um número aqui criaria uma segunda
        # fonte de verdade com o render.yaml.
        default=int(os.environ.get("PORT", "8000")),
        help="porta (padrão: PORT do ambiente, ou 8000)",
    )
    srv.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
