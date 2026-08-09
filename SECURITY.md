# Política de segurança

## Reportar vulnerabilidade

Abra um [security advisory privado](https://github.com/JulianoVinceCampos/observability-governance-lab/security/advisories/new).
Não abra issue pública para vulnerabilidade.

Respondo em até 5 dias úteis. Este é um projeto pessoal, não um produto com SLA.

## O que este projeto é, e o que não é

O dashboard é uma instância de demonstração **read-only sobre dataset sintético**. O
portão de login existe para que a instância pública não fique aberta a indexação, não
para proteger dado sensível: não há dado sensível.

A credencial padrão está no README de propósito. Se você montar este projeto sobre um
inventário real, troque `OBSGOV_USER` e `OBSGOV_PASSWORD` e trate o serviço como interno.

## Camadas de defesa

O que existe, e a razão de cada uma:

**Sanitização de contexto corporativo.** `tools/sanitize_scan.py` bloqueia instance id de
AWS, account id de 12 dígitos, CNPJ e CPF, IP privado e nome de host interno. Roda como
primeira etapa no pre-commit e como primeiro job do CI, antes do lint. A ordem é
deliberada: uma violação de estilo se corrige com um commit, um identificador vazado em
histórico público é permanente.

**Duas engines para a mesma intenção.** As mesmas regras existem em
`.semgrep/no-corp-leak.yml`. Um bug em uma das duas não desliga o gate em silêncio.

**Secret scan em todo o histórico.** `gitleaks` roda com `fetch-depth: 0`, porque secret
em commit antigo continua sendo secret.

**Superfície de dependência mínima.** O pacote instalado não tem dependência de runtime
(ADR-0001), então a superfície de SCA é só tooling de desenvolvimento.

**Sem caminho montado a partir de entrada de rede.** O bundle web é um dicionário
explícito de URL para arquivo. Não existe travessia de diretório a barrar porque não
existe caminho a construir.

**Sessão assinada no servidor.** HMAC-SHA256 sobre `user.expiry`, comparação de tempo
constante na credencial, cookie `HttpOnly` e `SameSite=Strict`, segredo por processo. Um
portão validado em JavaScript não seria portão.

**Headers de hardening em toda resposta.** `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.

**Zero script de terceiro no frontend.** Sem framework, sem CDN. Um demo público que
carrega script de terceiro entrega o visitante para o terceiro.

## Limitações conhecidas, declaradas

- `ThreadingHTTPServer` não é servidor de produção. Ele atende um demo read-only e não
  foi endurecido para carga ou abuso.
- A validação de request é manual. O endpoint de cenário aceita um inventário arbitrário
  e devolve erro genérico em vez de detalhe por campo. Trade-off registrado no ADR-0002.
- Não há rate limit. A instância pública depende do limite da plataforma de hospedagem.
