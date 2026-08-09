#!/usr/bin/env python3
"""Bloqueia contexto corporativo de chegar num commit público.

Adaptado de tools/sanitize_scan.py do postmortem-miner, mesmas regras e mesma
justificativa: este projeto nasceu pensando em sistemas de produção privados, e um
hostname ou account id vazado em histórico git público não pode ser despublicado. Roda
primeiro no CI e no pre-commit, zero dependência para funcionar em máquina limpa.

    python3 tools/sanitize_scan.py            # varre o repo inteiro
    python3 tools/sanitize_scan.py path ...   # varre caminhos específicos

Exit 0 limpo, 1 findings, 2 erro de uso.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SELF_EXEMPT = {"tools/sanitize_scan.py"}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "out",
    "htmlcov",
}
SCAN_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".cfg",
    ".ini",
    ".txt",
    ".sh",
    "",
}

ALLOWLIST = (
    "000000000000",
    "i-0EXAMPLE",
    "example.com",
    "users.noreply.github.com",
    "203.0.113.",
    "198.51.100.",
    "192.0.2.",
    "127.0.0.1",
    "0.0.0.0",
)

RULES: tuple[tuple[str, str, str], ...] = (
    ("aws-instance-id", r"\bi-0[a-f0-9]{8,17}\b", "instance id real da AWS - use i-0EXAMPLE"),
    ("aws-account-id", r"\b\d{12}\b", "account id de 12 dígitos - use 000000000000"),
    (
        "corp-domain",
        r"(?i)\b[a-z0-9-]+\.(?:crdc\.(?:com\.br|me|tools)|globalhitss\.com\.br)\b",
        "domínio corporativo - use example.com",
    ),
    (
        "brazilian-tax-id",
        r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
        "número no formato de CNPJ/CPF - gere um sintético",
    ),
    (
        "private-ip",
        r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b",
        "IP privado - use as faixas do RFC 5737",
    ),
    (
        "internal-hostname",
        r"(?i)\b(?:wildfly-[0-9]|db2_[ac]|formaliza[a-z]*o|escritura[a-z]*o)\b",
        "nome de host/produto interno - descreva o padrão de arquitetura em vez disso",
    ),
)

COMPILED = tuple((name, re.compile(pattern), hint) for name, pattern, hint in RULES)


def _iter_files(targets: list[Path]) -> Iterator[Path]:
    for target in targets:
        if target.is_file():
            yield target
            continue
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in SCAN_SUFFIXES:
                yield path


def _allowlisted(line: str) -> bool:
    if any(token in line for token in ALLOWLIST):
        return True
    return "sanitize-ok" in line


def scan(targets: list[Path]) -> list[tuple[Path, int, str, str, str]]:
    findings: list[tuple[Path, int, str, str, str]] = []
    for path in _iter_files(targets):
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.as_posix()
        if relative in SELF_EXEMPT:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            for name, pattern, hint in COMPILED:
                match = pattern.search(line)
                if match and not _allowlisted(line):
                    findings.append((path, number, name, match.group(0)[:60], hint))
    return findings


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv[1:]] or [ROOT]
    for target in targets:
        if not target.exists():
            print(f"erro: caminho não encontrado: {target}", file=sys.stderr)
            return 2

    findings = scan(targets)
    if not findings:
        print("sanitize: limpo")
        return 0

    print(f"sanitize: {len(findings)} finding(s)\n", file=sys.stderr)
    for path, number, name, snippet, hint in findings:
        location = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path
        print(f"  {location}:{number} [{name}] {snippet!r}\n      {hint}", file=sys.stderr)
    print(
        "\nSe um match é um placeholder deliberado, adicione em ALLOWLIST ou termine a "
        "linha com um comentário `sanitize-ok` explicando o motivo.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
