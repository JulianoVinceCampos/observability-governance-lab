# ADR-0002: O dashboard também é standard library

- **Status:** aceito
- **Data:** 2026-08-09
- **Relação:** revisita o [ADR-0001](ADR-0001-zero-runtime-dependencies.md), não o substitui

## Contexto

O ADR-0001 fixou zero dependência de runtime porque o gate roda como primeiro job de CI,
antes de qualquer instalação. Um dashboard web é exatamente o tipo de requisito que
costuma derrubar essa decisão: FastAPI mais Uvicorn resolveriam o problema em menos
código, com validação de request de graça e documentação de API automática.

A pergunta então não é "FastAPI é bom" (é), mas "o que se perde ao adicioná-lo aqui".

Três coisas concretas:

1. O `pip install` do pacote passaria a trazer FastAPI, Uvicorn, Pydantic, Starlette e as
   dependências transitivas delas. O gate de compliance carregaria uma árvore de
   dependência para servir HTML que ele não precisa quando roda como gate.
2. A superfície de SCA sairia de "só tooling de dev" para "runtime com dezenas de pacotes",
   num projeto cujo assunto é justamente controle e auditabilidade. Seria incoerente.
3. A imagem do container ganharia uma etapa de resolução de dependência, e com ela a
   possibilidade de o build falhar por causa de índice de pacote indisponível.

O contra-argumento honesto: `http.server` não é servidor de produção. Ele não tem
worker, não tem timeout configurável por rota, e o `ThreadingHTTPServer` cria uma thread
por conexão.

## Decisão

A camada web usa `http.server`, `json`, `hmac` e `secrets`. Nada mais.

O que isso exigiu de trabalho explícito, e que um framework daria de graça:

- **HTTP/1.1 declarado.** O default do `BaseHTTPRequestHandler` é HTTP/1.0, que fecha a
  conexão a cada resposta. Atrás de um proxy que reusa a conexão upstream isso
  dessincroniza o par requisição/resposta, e o proxy passa a servir a resposta anterior
  para a requisição seguinte. Toda resposta carrega `Content-Length`, que é o que o
  HTTP/1.1 exige para manter a conexão viva com segurança.
- **Corpo drenado antes de rotear.** Responder 404 sem ler o corpo deixa bytes na
  conexão, e com keep-alive eles viram a próxima linha de request. Corpo acima do teto
  fecha a conexão em vez de dessincronizar.
- **`do_HEAD` implementado.** Sem isso a stdlib devolve 501 para HEAD, e verificador de
  link e alguns proxies sondam com HEAD.
- **Sessão assinada à mão.** `user.expiry.signature` com HMAC-SHA256, cookie `HttpOnly`
  e `SameSite=Strict`, comparação de tempo constante na credencial. Segredo por processo,
  então sessão não sobrevive a restart, que é a troca certa para um demo stateless.
- **Roteamento estático por dicionário explícito.** O bundle é um conjunto fixo de três
  arquivos, mapeado URL para (nome, content-type). Não há caminho montado a partir de
  entrada de rede, então não há travessia de diretório a barrar: a classe de bug não
  existe em vez de ser mitigada.

O frontend é HTML, CSS e JavaScript puro, sem build step e sem CDN. Um demo público que
carrega script de terceiro entrega o visitante para o terceiro.

## Consequências

**Bom.** `pip install` continua trazendo nada. A imagem do container não tem etapa de
resolução de dependência. O demo funciona sem rede além da própria página. A camada web
inteira é testável sem abrir socket, porque toda decisão vive em função pura, e o teste
de integração sobe o servidor em porta 0 para cobrir a casca.

**Ruim.** Escrevi à mão o que um framework entrega pronto, e cada item da lista acima é
um bug que eu poderia ter cometido. A validação de request é manual: o endpoint do editor
de cenário aceita um inventário arbitrário e devolve `{"ok": false, "error": ...}` em vez
de um 422 com detalhe por campo. `ThreadingHTTPServer` não aguenta carga real, e não
precisa: é uma instância de demonstração read-only sobre dado sintético.

**Revisitar se** o dashboard passar a aceitar escrita de verdade, precisar de mais de um
worker, ou se o projeto ganhar uma API pública consumida por terceiro. Nesse ponto o
custo da validação manual passa a ser maior que o custo da dependência, e aí FastAPI
entra com justificativa, não por conveniência.
