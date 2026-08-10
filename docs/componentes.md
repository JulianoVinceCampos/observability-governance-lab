# Componentes

Os componentes, um diagrama por pergunta, e o que cada aresta garante.

## Visão de container

```mermaid
flowchart TB
    subgraph decl["Fonte declarada, versionada e read-only"]
        JSON[("5 arquivos JSON<br/>service-catalog, slo, alerts<br/>runbooks, change-log")]
    end

    subgraph pkg["Pacote obsgov, zero dependência de runtime"]
        LOADER["loader<br/>JSON para Inventory<br/>LoaderError em fonte quebrada"]
        MODEL["model<br/>dataclasses frozen"]
        EVAL["evaluator<br/>CONTROLS, evaluate e score"]
        REPORT["report<br/>markdown, JSON, SARIF"]
        CLI["cli<br/>validate, score, report, serve"]
        WEBAPP["webapp<br/>http.server e hmac"]
    end

    subgraph web["Bundle web, sem build step e sem CDN"]
        HTML["index.html"]
        JS["app.js"]
        CSS["styles.css"]
    end

    subgraph consumidores["Quem consome"]
        CI["gate de CI<br/>exit code é o contrato"]
        HUMANO["avaliador humano<br/>navegador"]
        AUDITOR["auditor<br/>pacote de evidência"]
    end

    JSON --> LOADER
    LOADER --> MODEL
    MODEL --> EVAL
    EVAL --> REPORT
    CLI --> LOADER
    CLI --> EVAL
    CLI --> REPORT
    CLI --> WEBAPP
    WEBAPP --> EVAL
    WEBAPP --> HTML
    HTML --> JS
    HTML --> CSS
    CLI --> CI
    HTML --> HUMANO
    REPORT --> AUDITOR
```

O que cada aresta garante:

- `loader -> model`: uma fonte obrigatória ausente ou JSON malformado vira `LoaderError`
  no nível do arquivo, não um `KeyError` no meio da avaliação. O arquivo opcional ausente
  degrada para tupla vazia, porque "ainda não declarei problema" é um finding para o
  avaliador, não um crash.
- `model -> evaluator`: o `Inventory` é `frozen`, então nenhum controle consegue alterar o
  estado que outro controle vai ler. A ordem de execução não muda o resultado.
- `webapp -> evaluator`: a mesma função `evaluate()` que a CLI usa. Não há segunda
  implementação, então dashboard e gate não podem divergir.
- `cli -> CI`: o exit code é o contrato. `validate` sai com 1 se qualquer MUST reprovar.

## Fluxo do dashboard

```mermaid
sequenceDiagram
    autonumber
    participant B as navegador
    participant H as Handler
    participant A as AppState
    participant E as evaluator

    Note over A: no startup os dois fixtures são<br/>carregados e avaliados uma vez
    B->>H: POST /api/login
    H->>H: compare_digest nos dois campos
    H-->>B: Set-Cookie HttpOnly SameSite=Strict<br/>user.expiry.signature
    B->>H: GET /api/state/bad-state/scorecard
    H->>A: lê avaliação já em memória
    A-->>H: ControlResult + PracticeScore
    H-->>B: JSON

    Note over B,E: no editor de cenário a avaliação é sob demanda,<br/>sem tocar o estado do processo
    B->>H: GET /api/state/good-state/inventory
    H-->>B: inventário serializado
    B->>B: aplica a mutação escolhida
    B->>H: POST /api/evaluate com o inventário no corpo
    H->>E: evaluate(Inventory montado do corpo)
    E-->>H: verdict novo
    H-->>B: scorecard do cenário
```

O editor de cenário recebe o inventário no corpo da requisição em vez de mutar o estado
do servidor. Duas consequências: o fixture em disco nunca é alterado, e duas abas abertas
não interferem uma na outra.

## Onde vive cada decisão

| Pergunta | Arquivo | Nota |
|---|---|---|
| O que é um controle | `evaluator.py`, tupla `CONTROLS` | 30 entradas, cada uma com id, severidade, prática, objetivo COBIT, título, remediação e função de check |
| Como um nível é calculado | `evaluator.py`, `score_practice` | a regra de teto vive aqui, não espalhada pelos controles |
| O que é um verdict | `evaluator.py`, enum `Verdict` | `PASS`, `FAIL`, `SKIP`, `WAIVED`. O valor do enum é contrato de saída, então não é traduzido |
| Como uma fonte é lida | `loader.py` | validação no nível do arquivo, não do campo. Ver ADR-0001 |
| Como o relatório é gerado | `report.py` | três formatos da mesma avaliação |
| Como a sessão é assinada | `webapp.py`, `make_session` | HMAC-SHA256, segredo por processo. Ver ADR-0002 |
| O que a tela mostra | `web/app.js` | funções de render que devolvem string, sem framework de reatividade |
| O sistema de cor | `web/styles.css`, bloco `:root` | tokens, e o comentário no topo explica por que SKIP é tracejado |

## Links

- [ADR-0001](adr/ADR-0001-zero-runtime-dependencies.md): por que zero dependência de runtime
- [ADR-0002](adr/ADR-0002-dashboard-na-stdlib.md): por que o dashboard também é standard library
- [controls.md](controls.md): o catálogo completo, gerado do código
