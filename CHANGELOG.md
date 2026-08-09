# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), versão
seguindo [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [0.1.0]

Primeira versão. Motor de conformidade, catálogo de controles, dashboard e esteira.

### Motor

- Catálogo de 30 controles (16 MUST, 12 SHOULD, 2 MAY) cobrindo 7 práticas ITIL 4 e 9
  objetivos COBIT 2019. Cada controle é uma função pura `Inventory -> Verdict`, sem I/O e
  sem efeito colateral, o que torna a avaliação determinística.
- Regra de teto no scorer: um único controle MUST reprovado limita a prática ao nível 1,
  independente de quantos SHOULD e MAY passem, e o controle causador é nomeado na saída.
- `SKIP` nunca conta como `PASS`, e todo skip carrega o motivo do pré-requisito não
  satisfeito.
- Waiver com dono e validade obrigatórios. Waiver expirado volta a reprovar.
- Loader das cinco fontes declaradas, com `LoaderError` no nível do arquivo para fonte
  obrigatória ausente ou JSON malformado.

### Interface

- CLI `obsgov` com `validate` (gate de CI, exit 1 em qualquer MUST reprovado), `score`,
  `report` e `serve`.
- Dashboard web read-only com seis views: scorecard, controles com detalhe de evidência,
  matriz ITIL x COBIT, comparação entre estados, editor de cenário que reavalia ao vivo, e
  download do pacote de evidência.
- Relatório em markdown, JSON e SARIF. O SARIF faz cada gap aparecer como finding na aba
  Security do GitHub.

### Fixtures

- `data/bad-state` e `data/good-state` declaram os mesmos três serviços sintéticos em dois
  estados, com maturidade medida de 1.0 para 2.71. Cada gap do estado ruim vem de um modo
  de falha real de arquitetura, não de quebra aleatória.

### Esteira

- Pipeline em três estágios, com `sanitize` antes de `lint`, porque vazamento em histórico
  público é irreversível e violação de estilo não é.
- Gate de sanitização em duas engines independentes (`tools/sanitize_scan.py` e
  `.semgrep/no-corp-leak.yml`), mais `gitleaks` em todo o histórico.
- Cobertura com ratchet: o piso só sobe.
- SAST com Semgrep e CodeQL, este último bloqueante desde o primeiro commit.
- SBOM CycloneDX e atestação de proveniência em cada build.
- Build do container verificado no CI, incluindo healthcheck e checagem de usuário
  não-root.

### Decisões

- [ADR-0001](docs/adr/ADR-0001-zero-runtime-dependencies.md): zero dependência de runtime.
- [ADR-0002](docs/adr/ADR-0002-dashboard-na-stdlib.md): o dashboard também é standard
  library, com o custo dessa escolha documentado.

[Não lançado]: https://github.com/JulianoVinceCampos/observability-governance-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/JulianoVinceCampos/observability-governance-lab/releases/tag/v0.1.0
