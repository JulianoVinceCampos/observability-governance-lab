## O que muda e por quê

<!-- O problema antes da solução. Se for controle novo, diga que gap real ele pega. -->

## Como verificar

<!-- O comando que prova. `make check` é o mínimo; se mexeu em controle, cole a saída
     do `obsgov validate` nos dois fixtures. -->

```
```

## Checklist

- [ ] `make check` passa local (sanitize, lint, testes)
- [ ] Cobertura não caiu abaixo do piso em `.coverage-floor`
- [ ] Nenhum dado real: todo fixture é sintético e narrado como padrão de arquitetura
- [ ] Commit assinado, histórico linear

Se mexeu no catálogo de controles:

- [ ] O controle tem probe automatizado (controle sem probe não entra)
- [ ] Tem caso de teste de pass, de fail e, onde faz sentido, de skip
- [ ] A severidade foi escolhida com critério: `MUST` trava a prática no nível 1
- [ ] `python3 tools/gen_controls_doc.py` rodado, `docs/controls.md` atualizado

Se mudou desenho:

- [ ] ADR novo em `docs/adr/`, com a alternativa descartada e o motivo
- [ ] Se contraria um ADR existente, o novo diz qual substitui (ADR não é editado)
