# Contribuindo

## O que roda antes de qualquer coisa

```bash
make install   # extras de dev e os hooks de pre-commit
make check     # sanitize, lint e testes, na mesma ordem do CI
```

Se `make check` passa local, o CI não vai reprovar por algo que você poderia ter visto em
segundos. Gate que só existe no YAML da esteira transforma o ciclo de correção em uma
espera de minutos por tentativa.

## A contribuição mais útil

**Um controle novo com probe automatizado.** A regra que governa o catálogo é dura de
propósito: se um controle não pode ser verificado automaticamente, ele não entra. Um
controle "avaliado por inspeção" transformaria este projeto exatamente no documento de
aderência que ele existe para substituir.

Um controle novo é:

1. Uma função `_xxx_nnn(inv: Inventory) -> tuple[bool | None, str]` em
   `src/obsgov/evaluator.py`. Devolve `True` (pass), `False` (fail) ou `None`
   (pré-requisito não satisfeito, vira `SKIP`). A string de evidência é obrigatória,
   inclusive no `SKIP`: um skip que não diz por que é um skip inútil.
2. Uma entrada em `CONTROLS` com id, severidade, prática, objetivo COBIT, título e
   remediação.
3. Teste com caso de pass, caso de fail e, onde faz sentido, caso de skip.
4. `python3 tools/gen_controls_doc.py` para regenerar `docs/controls.md`. Existe teste que
   falha se o doc divergir do catálogo.

Escolha da severidade, que não é detalhe: `MUST` tem poder de travar a prática no nível 1
pela regra de teto. Marcar como `MUST` algo que é boa prática mas não é essencial faz o
score reprovar quem não merece, e o time aprende a ignorar o gate.

## Regras que o CI aplica

- **Zero dependência de runtime.** O pacote instalado depende só da standard library
  ([ADR-0001](docs/adr/ADR-0001-zero-runtime-dependencies.md)). Dependência de dev é
  livre. Um PR que adiciona dependência de runtime precisa de um ADR justificando.
- **Nada de contexto corporativo.** Nome de host interno, instance id, account id, IP
  privado, CNPJ e CPF são bloqueados por duas engines independentes. Todo dado é
  sintético e narrado como padrão de arquitetura genérico.
- **Cobertura com ratchet.** O piso em `.coverage-floor` só sobe. Um PR que derruba a
  cobertura abaixo do piso falha.
- **Conventional commit.** O tipo (`feat`, `fix`, `docs`, `chore`, `refactor`, `test`)
  fica em inglês porque é contrato da convenção; a descrição vai em português.
- **Commit assinado.** `main` exige. Histórico linear: `rebase`, não `merge`.

## Idioma

Prosa em português brasileiro. Termo técnico consagrado fica em inglês, sem tradução
forçada: SLI, SLO, error budget, burn rate, runbook, postmortem, `trace_id`, watchdog,
gate, probe, finding, waiver, drift.

Identificador de código, id de controle (`OBS-001`), código de framework (`DSS02`) e valor
de enum que é contrato de saída (`PASS`, `FAIL`, `SKIP`, `WAIVED`) ficam como estão.

## Decisão de projeto

Mudança de desenho vai em ADR, com a alternativa descartada e o motivo. ADR é imutável:
uma decisão que muda gera um ADR novo que substitui o anterior, não uma edição do antigo.
Um ADR reescrito perde a única coisa que o torna útil, que é registrar o que se pensava no
momento da decisão.

## O que provavelmente não vai ser aceito

- Framework no frontend ou no servidor web, sem um ADR que refute o
  [ADR-0002](docs/adr/ADR-0002-dashboard-na-stdlib.md).
- Controle sem probe automatizado.
- Alegação de conformidade ITIL ou COBIT. A linguagem é "mapeia para" e "avaliado contra o
  objetivo", nunca "está em conformidade com". Ver [NOTICE.md](NOTICE.md).
- Dado de sistema real, mesmo anonimizado. O gate de sanitização vai barrar, e a decisão
  por trás dele não é negociável.
