# Catálogo de controles

Gerado a partir de `src/obsgov/evaluator.py::CONTROLS`. Rode `python3 tools/gen_controls_doc.py` depois de editar o catálogo, não edite a tabela abaixo à mão.

Ver [NOTICE.md](../NOTICE.md): identificadores de objetivo COBIT são usados só como ponto de referência público. Todo título e toda string de remediação é redação própria.

**30 controles** em 7 práticas, mapeados para 9 objetivos COBIT 2019.

| ID | Severidade | Prática | COBIT | Título | Remediação |
|---|---|---|---|---|---|
| `OBS-001` | MUST | monitoring-and-event-management | DSS01 | serviço crítico declara os 4 golden signals | declarar sinais de latência/tráfego/erro/saturação para todo serviço tier=critical |
| `OBS-002` | MUST | monitoring-and-event-management | DSS01, MEA01 | todo sinal declarado resolve para uma métrica real | remover ou corrigir nomes de sinal que não resolvem no backend |
| `OBS-003` | MUST | monitoring-and-event-management | DSS01 | nenhum alerta referencia métrica/atributo morto | apontar a regra de alerta para uma métrica que de fato é emitida |
| `OBS-004` | MUST | monitoring-and-event-management | DSS01 | trace_id correlaciona trace, log e métrica | conectar a correlação trace/log (ex.: dd.logs.injection ou propagação de contexto OTel) |
| `OBS-005` | MUST | monitoring-and-event-management | DSS01 | pipeline de log carrega trace_id/span_id | injetar trace_id/span_id no contexto de log, não só texto livre |
| `OBS-006` | SHOULD | monitoring-and-event-management | DSS01 | orçamento de cardinalidade de métrica declarado | definir um orçamento de max-series por métrica de alta cardinalidade |
| `OBS-007` | SHOULD | monitoring-and-event-management | DSS01 | atributos de recurso seguem convenções semânticas do OTel | renomear atributos para bater com as convenções semânticas do OTel |
| `SLO-001` | MUST | service-level-management | APO09 | todo serviço crítico tem um SLO | definir ao menos um SLO (SLI, alvo, janela) por serviço crítico |
| `SLO-002` | MUST | service-level-management | APO09 | todo SLO tem dono e cadência de revisão | atribuir um dono e uma cadência de revisão ao SLO |
| `SLO-003` | MUST | service-level-management | APO09, MEA01 | o error budget de todo SLO tem consequência | declarar o que de fato acontece quando o error budget se esgota |
| `SLO-004` | SHOULD | service-level-management | APO09 | alerta de burn-rate, não limiar fixo | configurar alerta de burn-rate multi-janela para o SLO |
| `SLO-005` | SHOULD | service-level-management | APO09 | SLO rastreia a uma evidência | vincular o SLO ao histórico de incidente ou jornada de usuário de origem |
| `SLO-006` | MAY | service-level-management | APO09 | SLI medido da perspectiva do consumidor | adicionar uma medição do lado do consumidor onde for viável |
| `INC-001` | MUST | incident-management | DSS02 | todo alerta de paging tem runbook que resolve | anexar uma referência de runbook que de fato resolve o alerta |
| `INC-002` | MUST | incident-management | DSS02 | todo runbook foi testado dentro da janela | retestar o runbook e atualizar last_tested_days_ago |
| `INC-003` | MUST | incident-management | DSS02 | classificação de severidade está completa | atribuir severidade a toda regra de alerta |
| `INC-004` | SHOULD | incident-management | DSS02 | nenhum alerta órfão | atribuir dono a toda regra de alerta |
| `INC-005` | SHOULD | incident-management | DSS02 | razão de ruído de alerta medida | instrumentar a razão reconhecido-vs-ignorado por alerta |
| `PRB-001` | MUST | problem-management | DSS03 | assinatura de incidente recorrente tem registro de problema | abrir um registro de problema para a assinatura recorrente |
| `PRB-002` | SHOULD | problem-management | DSS03 | todo problema documenta um workaround | documentar o workaround do erro conhecido |
| `PRB-003` | SHOULD | problem-management | DSS03 | todo problema vincula um postmortem | vincular o postmortem do(s) incidente(s) de origem do problema |
| `CHG-001` | MUST | change-enablement | BAI06 | mudança emite marcador de deploy | emitir um marcador de deploy na timeline de telemetria |
| `CHG-002` | MUST | change-enablement | BAI06, BAI10 | mudança declara seu sinal de rollback | declarar qual SLI/métrica detecta essa mudança falhando |
| `CHG-003` | SHOULD | change-enablement | BAI06 | janela de verificação pós-mudança declarada | declarar uma janela de verificação com checagem automática de burn |
| `CHG-004` | SHOULD | change-enablement | BAI06 | catálogo confere com a realidade implantada | reconciliar o catálogo de serviço contra um probe de deploy vivo |
| `CSI-001` | SHOULD | continual-improvement | MEA01, APO11 | maturidade registrada como tendência, não ponto único | rodar o avaliador repetidamente e manter o histórico |
| `CSI-002` | MUST | continual-improvement | MEA01, APO11 | gaps anteriores fechados ou com waiver | fechar o gap ou registrar um waiver com dono e validade |
| `CSI-003` | MAY | continual-improvement | APO11 | mudanças no catálogo de controle são revisadas | exigir revisão em mudanças no próprio catálogo de controle |
| `BCP-001` | MUST | service-continuity | DSS04 | o pipeline de observabilidade é vigiado por algo | adicionar um heartbeat/dead-man switch vigiando o próprio pipeline |
| `BCP-002` | SHOULD | service-continuity | DSS04 | retenção de telemetria atende a janela de auditoria | estender a retenção do sinal abaixo do piso de 90 dias |
