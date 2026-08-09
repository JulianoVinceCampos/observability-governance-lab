# ADR-0001: Zero dependência de runtime

- **Status:** aceito
- **Data:** 2026-08-07

## Contexto

A implementação óbvia usaria `pydantic` para os schemas das cinco fontes declaradas e
`click` para a CLI. Os dois são bibliotecas boas, e o próprio plano deste projeto citava
`pydantic` como primeira escolha.

Mas considere onde o gate de fato precisa rodar: como o primeiro job de um pipeline de
CI (`sanitize` e este avaliador rodam antes da instalação de dependência, de propósito,
ver `tools/sanitize_scan.py`), e potencialmente numa máquina isolada ou bastion durante
uma auditoria. Um gate que depende de um pacote resolver é um gate com um modo de falha
que ninguém quer: "a checagem de compliance não rodou porque o pip deu timeout".

## Decisão

O pacote instalado depende só da standard library:

- Os cinco modelos de fonte declarada são `@dataclass(frozen=True, slots=True)` simples
  em vez de `pydantic.BaseModel`. A validação acontece em `obsgov.loader`, não na
  camada de modelo: `LoaderError` para arquivo obrigatório ausente ou JSON malformado,
  degradação silenciosa para tupla vazia no único arquivo opcional.
- A CLI é `argparse`.
- O relatório é f-strings e `json.dumps`, porque dois dos três formatos de saída
  (markdown, SARIF) são texto, não templates com lógica.

Dependências de dev e CI (pytest, pytest-cov, ruff) são livres. Elas nunca vão dentro
do pacote instalado.

## Consequências

**Bom.** `pip install -e .` (ou nem isso, porque `PYTHONPATH=src python -m obsgov.cli`
funciona direto de um clone) não precisa de nada além de Python 3.11+. A superfície de
SCA é só tooling de dev. Todo dataclass é diretamente serializável para JSON via
`dataclasses.asdict`, o que mantém o gerador de relatório trivial.

**Ruim.** Sem mensagens de erro de validação no estilo `pydantic`. Um campo malformado
só levanta um `KeyError`/`TypeError` simples do acesso a dict do loader, encapsulado em
`LoaderError` no nível do arquivo, não no nível do campo. Aceitável por agora: isso é um
gate para CI, não um formulário voltado ao público, e os dois fixtures publicados
exercitam todo campo.

**Revisitar se** o schema de fonte declarada crescer o suficiente para a validação de
campo manual no loader virar seu próprio fardo de manutenção, ou se este projeto ganhar
um dashboard web de verdade (planejado como marco seguinte) que precisaria de FastAPI
de qualquer forma. Nesse ponto pydantic para de ser dependência extra e passa a ser
uma que já estaria sendo paga.
