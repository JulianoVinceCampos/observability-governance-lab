/* Frontend do observability-governance-lab. Sem framework, sem CDN, sem build step.
   O demo público não carrega script de terceiro.

   Formato: um objeto `state` pequeno, funções de render que devolvem string de HTML, e
   um render() que troca o innerHTML da view. Sem framework de reatividade porque não há
   estado suficiente para justificar um: o dado vem do servidor já avaliado.

   Toda interpolação de texto vindo de dado passa por esc(). O dataset é sintético e
   local, mas o editor de cenário aceita entrada do usuário e devolve para a tela, então
   escapar não é opcional.

   Navegação em seis camadas, na ordem em que a pergunta de conformidade aparece:
   1 Situação (passa ou não passa), 2 Diagnóstico (por que), 3 Remediação (o que fazer),
   4 Cobertura (onde não se está olhando), 5 Simulação (e se), 6 Evidência (a prova).
   Comparar-dois-estados e Editor-de-cenário viraram abas dentro da camada 5: as duas
   respondem "o que muda se", e forçar a decidir entre elas sem contexto dobrava o custo
   de entender a tela. */

"use strict";

const VERDICTS = ["PASS", "FAIL", "WAIVED", "SKIP"];

/* Glifo por verdict. Cor nunca carrega significado sozinha: quem não distingue verde de
   vermelho ainda lê o glifo e o rótulo. */
const GLYPH = { PASS: "\u2713", FAIL: "\u2715", WAIVED: "\u2248", SKIP: "\u2013" };

const VERDICT_HELP = {
  PASS: "o controle respondeu e passou",
  FAIL: "exige ação",
  WAIVED: "risco aceito, com dono e validade",
  SKIP: "pré-requisito não satisfeito, nunca conta como aprovação",
};

const state = {
  view: "situation",
  stateName: "bad-state",
  simTab: "compare",
  data: {},
  filters: { q: "", verdicts: new Set(), severities: new Set() },
  scenario: null,
  scenarioBaseline: null,
};

/* ------------------------------------------------------------------ utilidades */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    showGate();
    throw new Error("sessão expirada");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function verdictBadge(verdict) {
  return `<span class="verdict v-${esc(verdict)}" title="${esc(VERDICT_HELP[verdict] || "")}">
    <span class="glyph" aria-hidden="true">${GLYPH[verdict] || ""}</span>${esc(verdict)}</span>`;
}

function sevBadge(severity) {
  return `<span class="sev sev-${esc(severity)}">${esc(severity)}</span>`;
}

function countsRow(counts) {
  return VERDICTS
    .filter((v) => (counts?.[v] || 0) > 0)
    .map((v) => `<span class="verdict v-${v}">
        <span class="glyph" aria-hidden="true">${GLYPH[v]}</span>${counts[v]} ${v}</span>`)
    .join("");
}

function maturityScale(level) {
  const steps = [];
  for (let i = 1; i <= 5; i += 1) {
    steps.push(`<span class="mat-step ${i <= level ? "on" : ""}"></span>`);
  }
  return `<div class="mat-scale" role="img" aria-label="nível ${level} de 5">${steps.join("")}</div>`;
}

function practiceLabel(name) {
  return name.replace(/-/g, " ");
}

function stepTag(number, label) {
  return `<span class="step-tag"><span class="step-num" aria-hidden="true">${number}</span>${esc(label)}</span>`;
}

/* --------------------------------------------------------- camada 1: Situação */

/* A primeira tela responde a única pergunta que importa antes de qualquer detalhe:
   este inventário passa no gate de CI ou não. O veredito vem em texto grande, os
   controles causadores vêm nomeados e clicáveis, e só depois disso aparece qualquer
   número decomposto. Quem chega na demo por 30 segundos sai sabendo o que travou. */
function renderSituation(d) {
  const capped = d.practices.filter((p) => p.ceiling_control);
  const gatePass = d.musts_failed.length === 0;
  const culprits = d.practices.filter((p) => p.ceiling_control);

  return `
  <div class="page-head">
    ${stepTag(1, "Situação")}
    <h1>Este inventário passa no gate?</h1>
    <p>A primeira pergunta que importa, respondida antes de qualquer detalhe. O gate de
       CI usa exatamente este critério: <code>obsgov validate</code> sai com código 1 se
       qualquer controle <strong>MUST</strong> reprovar.</p>
  </div>

  <div class="verdict-banner ${gatePass ? "pass" : "fail"}">
    <div class="verdict-banner-icon" aria-hidden="true">${gatePass ? GLYPH.PASS : GLYPH.FAIL}</div>
    <div>
      <p class="verdict-banner-title">
        ${gatePass ? "Gate passa" : `Gate reprova: ${d.musts_failed.length} controle(s) MUST em FAIL`}
      </p>
      <p class="verdict-banner-sub">
        ${gatePass
          ? `Maturidade geral ${esc(d.overall_maturity)} de 5, sobre o inventário `
          : `${capped.length} prática(s) travada(s) no nível 1 pela regra de teto, sobre o inventário `}
        <code>${esc(d.state)}</code>.
      </p>
    </div>
    ${!gatePass ? `<div class="verdict-banner-cta">
      <button type="button" class="btn btn-primary" data-goto="controls">Ver remediação</button>
    </div>` : ""}
  </div>

  <div class="situation-grid">
    <div class="kpi kpi-hero">
      <div class="kpi-label">Maturidade geral</div>
      <div class="kpi-value">${esc(d.overall_maturity)}<small> / 5</small></div>
      <div class="kpi-foot">média dos ${d.practices.length} níveis de prática</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Controles avaliados</div>
      <div class="kpi-value">${d.total_controls}</div>
      <div class="kpi-foot counts">${countsRow(d.counts)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Práticas travadas</div>
      <div class="kpi-value" style="color:${capped.length ? "var(--fail)" : "var(--pass)"}">
        ${capped.length}</div>
      <div class="kpi-foot">de ${d.practices.length}, pela regra de teto</div>
    </div>
  </div>

  ${culprits.length ? `
  <div class="section">
    <h2>O que está travando</h2>
    <p class="section-hint">Cada prática abaixo está limitada ao nível 1 por um único
       controle MUST reprovado, não importa quantos outros controles dela passem. Clique
       para ver a evidência.</p>
    <div class="culprit-list">
      ${culprits.map((p) => `
        <button type="button" class="culprit" data-open-control="${esc(p.ceiling_control)}">
          <span class="culprit-id">${esc(p.ceiling_control)}</span>
          <span class="culprit-body">
            <span class="culprit-title">trava ${esc(practiceLabel(p.practice))} no nível 1</span>
            <span class="culprit-practice">nível atual ${p.level} de 5</span>
          </span>
          <span class="culprit-arrow" aria-hidden="true">&rarr;</span>
        </button>`).join("")}
    </div>
  </div>` : `
  <div class="section">
    <div class="notice">
      <strong>Nenhum MUST reprovado.</strong> O gate passa. Veja o diagnóstico completo
      por prática na camada 2, ou simule o que quebra o gate na camada 5.
    </div>
  </div>`}`;
}

/* --------------------------------------------------------- camada 2: Diagnóstico */

function renderScorecard(d) {
  const capped = d.practices.filter((p) => p.ceiling_control);
  const skipTotal = d.counts.SKIP || 0;

  return `
  <div class="page-head">
    ${stepTag(2, "Diagnóstico")}
    <h1>Maturidade por prática</h1>
    <p>Nível de cada prática ITIL, medida contra o inventário declarado
       <code>${esc(d.state)}</code>. Onde uma prática está travada, o controle
       obrigatório responsável aparece nomeado.</p>
  </div>

  ${skipTotal > 0 ? `
  <div class="section" style="margin-top:0">
    <div class="notice">
      <strong>${skipTotal} controle(s) em SKIP não contam como aprovação.</strong>
      Um SKIP significa que o pré-requisito do controle não foi satisfeito, então não há
      o que checar ainda. Somar skip com pass é o jeito mais comum de um score de
      maturidade mentir, e por isso os dois aparecem separados aqui.
    </div>
  </div>` : ""}

  <div class="section" style="margin-top:22px">
    <p class="section-hint">A escala vai de 0 (nem declaração existe) a 5 (o próprio
       catálogo de controle é revisado por evidência). Um único MUST reprovado limita a
       prática ao nível 1, independente de quantos SHOULD e MAY passem.</p>

    <div class="practice-list">
      ${d.practices.map((p) => `
        <article class="practice ${p.ceiling_control ? "capped" : (p.level >= 3 ? "clean" : "")}">
          <div class="practice-name">
            ${esc(practiceLabel(p.practice))}
            <span class="practice-cobit">${esc((state.data.cobitByPractice?.[p.practice] || []).join(" "))}</span>
          </div>
          <div class="practice-meta counts">${countsRow(p.counts)}</div>
          <div class="practice-level">
            <span class="level-num" style="color:var(--lvl-${p.level})">${p.level}</span>
            <span class="level-of">/ 5</span>
            ${maturityScale(p.level)}
          </div>
          ${p.ceiling_control ? `
          <p class="ceiling-note">
            <span aria-hidden="true">&#9888;</span>
            <span>Travada no nível 1 por <strong>${esc(p.ceiling_control)}</strong>, um
            controle MUST reprovado. Os outros controles desta prática não elevam o nível
            enquanto ele não for resolvido ou receber um waiver com dono e validade.</span>
          </p>` : ""}
        </article>`).join("")}
    </div>
  </div>

  <div class="section">
    <div class="legend" aria-hidden="false">
      ${VERDICTS.map((v) => `<span class="legend-item">${verdictBadge(v)}
        <span>${esc(VERDICT_HELP[v])}</span></span>`).join("")}
    </div>
  </div>`;
}

/* ---------------------------------------------------------- camada 3: Remediação */

function renderControls(rows) {
  const f = state.filters;
  const visible = rows.filter((r) => {
    if (f.verdicts.size && !f.verdicts.has(r.verdict)) return false;
    if (f.severities.size && !f.severities.has(r.severity)) return false;
    if (!f.q) return true;
    const hay = `${r.id} ${r.title} ${r.practice} ${r.cobit.join(" ")} ${r.evidence}`.toLowerCase();
    return hay.includes(f.q.toLowerCase());
  });

  return `
  <div class="page-head">
    ${stepTag(3, "Remediação")}
    <h1>Controles</h1>
    <p>Cada linha é um controle com verificação automatizada. Clique para ver a evidência
       crua que o motor coletou e a remediação sugerida.</p>
  </div>

  <div class="toolbar">
    <label class="sr-only" for="ctl-search">Buscar controle</label>
    <input id="ctl-search" type="search" placeholder="Buscar por id, título, prática, objetivo ou evidência"
           value="${esc(f.q)}">
    <div class="filters" role="group" aria-label="Filtrar por verdict">
      ${VERDICTS.map((v) => `<button type="button" class="chip" data-verdict="${v}"
        aria-pressed="${f.verdicts.has(v)}">${v}</button>`).join("")}
    </div>
    <div class="filters" role="group" aria-label="Filtrar por severidade">
      ${["MUST", "SHOULD", "MAY"].map((s) => `<button type="button" class="chip" data-severity="${s}"
        aria-pressed="${f.severities.has(s)}">${s}</button>`).join("")}
    </div>
  </div>

  <p class="section-hint">${visible.length} de ${rows.length} controle(s)</p>

  <div class="table-wrap">
    <table>
      <caption class="sr-only">Controles avaliados, com severidade, verdict e evidência</caption>
      <thead>
        <tr>
          <th scope="col">ID</th>
          <th scope="col">Sev</th>
          <th scope="col">Controle</th>
          <th scope="col">Prática</th>
          <th scope="col">COBIT</th>
          <th scope="col">Verdict</th>
          <th scope="col">Evidência</th>
        </tr>
      </thead>
      <tbody>
        ${visible.length ? visible.map((r) => `
          <tr class="row-click ${r.verdict === "FAIL" ? "is-fail" : ""}" data-id="${esc(r.id)}"
              tabindex="0" role="button" aria-label="Detalhe do controle ${esc(r.id)}">
            <td class="cid">${esc(r.id)}</td>
            <td>${sevBadge(r.severity)}</td>
            <td>${esc(r.title)}</td>
            <td class="muted">${esc(practiceLabel(r.practice))}</td>
            <td class="mono muted">${esc(r.cobit.join(", "))}</td>
            <td>${verdictBadge(r.verdict)}</td>
            <td class="evidence">${esc(r.evidence)}</td>
          </tr>`).join("") : `
          <tr><td colspan="7" class="empty">Nenhum controle bate com o filtro atual.</td></tr>`}
      </tbody>
    </table>
  </div>`;
}

/* ------------------------------------------------------------ camada 4: Cobertura */

function renderMatrix(d) {
  return `
  <div class="page-head">
    ${stepTag(4, "Cobertura")}
    <h1>Matriz ITIL x COBIT</h1>
    <p>Cobertura de práticas ITIL 4 contra objetivos COBIT 2019. A célula mostra o pior
       verdict do cruzamento, porque um FAIL não deve desaparecer numa média.</p>
  </div>

  <div class="notice" style="margin-bottom:18px">
    <strong>Célula hachurada é informação, não falta de dado.</strong> Significa que
    nenhum controle deste catálogo cruza aquela prática com aquele objetivo. Mostrar o
    vazio vale mais que sugerir cobertura total.
  </div>

  <div class="card card-pad">
    <div class="matrix-wrap">
      <table class="matrix">
        <caption class="sr-only">Cobertura de práticas por objetivo COBIT</caption>
        <thead>
          <tr>
            <th scope="col"><span class="sr-only">Prática</span></th>
            ${d.objectives.map((o) => `<th scope="col" class="mono">${esc(o)}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${d.practices.map((p) => `
            <tr>
              <th scope="row">${esc(practiceLabel(p))}</th>
              ${d.objectives.map((o) => {
                const cell = d.cells[p][o];
                if (!cell) {
                  return `<td><div class="cell cell-empty" title="sem controle neste cruzamento">
                    <span aria-hidden="true">&middot;</span>
                    <span class="sr-only">sem controle</span></div></td>`;
                }
                const label = `${cell.total} controle(s), pior verdict ${cell.worst}: ${cell.ids.join(", ")}`;
                return `<td><div class="cell cell-${esc(cell.worst)}" title="${esc(label)}">
                  <span aria-hidden="true">${GLYPH[cell.worst]} ${cell.total}</span>
                  <span class="sr-only">${esc(label)}</span></div></td>`;
              }).join("")}
            </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="legend" style="margin-top:16px">
      ${VERDICTS.map((v) => `<span class="legend-item">
        <span class="cell cell-${v}" style="width:26px;height:18px" aria-hidden="true"></span>
        <span>${v}</span></span>`).join("")}
      <span class="legend-item">
        <span class="cell cell-empty" style="width:26px;height:18px" aria-hidden="true"></span>
        <span>sem controle</span></span>
    </div>
  </div>`;
}

/* ------------------------------------------------------------- camada 5: Simulação */

function renderCompareTab(d) {
  if (!d.available) {
    return `<div class="empty">Os dois fixtures precisam existir para comparar.</div>`;
  }

  const changed = d.controls.filter((c) => c.changed);

  return `
  <div class="card card-pad">
    <div class="compare-head">
      <div>
        <div class="kpi-label">${esc(d.before.state)}</div>
        <div class="kpi-value" style="color:var(--fail)">${esc(d.before.overall_maturity)}<small> / 5</small></div>
        <div class="kpi-foot counts">${countsRow(d.before.counts)}</div>
      </div>
      <div class="compare-arrow" aria-hidden="true">&rarr;</div>
      <div>
        <div class="kpi-label">${esc(d.after.state)}</div>
        <div class="kpi-value" style="color:var(--pass)">${esc(d.after.overall_maturity)}<small> / 5</small></div>
        <div class="kpi-foot counts">${countsRow(d.after.counts)}</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Nível por prática</h2>
    <p class="section-hint">${d.fixed_count} controle(s) saíram de FAIL para PASS.</p>
    <div class="delta-list">
      ${d.practices.map((p) => `
        <div class="delta ${p.after > p.before ? "fixed" : ""}">
          <div><span class="level-num" style="font-size:17px;color:var(--lvl-${p.before})">${p.before}</span>
               <span class="delta-arrow" aria-hidden="true">&rarr;</span>
               <span class="level-num" style="font-size:17px;color:var(--lvl-${p.after})">${p.after}</span></div>
          <div>${esc(practiceLabel(p.practice))}
            ${p.ceiling_before ? `<span class="muted"> (estava travada por ${esc(p.ceiling_before)})</span>` : ""}
          </div>
          <div class="muted">${p.after > p.before ? `+${p.after - p.before}` : "sem mudança"}</div>
        </div>`).join("")}
    </div>
  </div>

  <div class="section">
    <h2>Controles que mudaram</h2>
    <p class="section-hint">${changed.length} de ${d.controls.length} controles mudaram de verdict.</p>
    <div class="delta-list">
      ${changed.map((c) => `
        <div class="delta ${c.fixed ? "fixed" : ""}">
          <div class="cid">${esc(c.id)}</div>
          <div>${esc(c.title)} ${sevBadge(c.severity)}</div>
          <div class="delta-states">
            ${verdictBadge(c.before)}<span class="delta-arrow" aria-hidden="true">&rarr;</span>${verdictBadge(c.after)}
          </div>
        </div>`).join("")}
    </div>
  </div>`;
}

/* Ajustes do editor de cenário. Cada um é uma mutação nomeada sobre o inventário, com o
   controle que ela quebra ou conserta declarado, porque a tela existe para ensinar a
   relação entre a declaração e o verdict. */
const KNOBS = [
  {
    id: "runbook",
    title: "Remover a referência de runbook do alerta que pagina",
    desc: "Deixa um alerta de severidade page sem runbook que o resolva.",
    hits: "INC-001 (MUST)",
    apply: (inv) => {
      const target = inv.alerts.find((a) => a.severity === "page" || a.severity === "critical");
      if (target) target.runbook_ref = "";
    },
  },
  {
    id: "budget",
    title: "Apagar a consequência do error budget",
    desc: "SLO continua declarado, mas nada acontece quando o budget estoura.",
    hits: "SLO-003 (MUST)",
    apply: (inv) => inv.slos.forEach((s) => { s.error_budget.consequence = ""; }),
  },
  {
    id: "trace",
    title: "Desligar a correlação de trace_id",
    desc: "Os três pilares deixam de fechar no mesmo id de request.",
    hits: "OBS-004 (MUST)",
    apply: (inv) => { inv.change_log.trace_id_correlation_verified = false; },
  },
  {
    id: "watchdog",
    title: "Remover o watchdog do pipeline",
    desc: "Ninguém mais vigia o próprio pipeline de observabilidade.",
    hits: "BCP-001 (MUST)",
    apply: (inv) => { inv.change_log.watchdogs = []; },
  },
  {
    id: "owner",
    title: "Deixar um alerta sem dono",
    desc: "Alerta órfão: dispara, mas ninguém é responsável por ele.",
    hits: "INC-004 (SHOULD)",
    apply: (inv) => { if (inv.alerts[0]) inv.alerts[0].owner = ""; },
  },
  {
    id: "stale",
    title: "Envelhecer o teste de todos os runbooks",
    desc: "Runbooks existem, mas nenhum foi testado dentro da janela declarada.",
    hits: "INC-002 (MUST)",
    apply: (inv) => inv.runbooks.forEach((r) => { r.last_tested_days_ago = 400; }),
  },
];

function renderScenarioTab() {
  const sc = state.scenario;
  const base = state.scenarioBaseline;
  const delta = sc && base ? Number((sc.overall_maturity - base.overall_maturity).toFixed(2)) : 0;

  return `
  <div class="notice" style="margin-bottom:16px">
    <strong>Comece marcando "Remover a referência de runbook do alerta que pagina".</strong>
    O <code>INC-001</code> fica vermelho e a prática <em>incident management</em> despenca
    para o nível 1, mesmo com todos os outros controles dela verdes. É a regra de teto, e é
    a razão de este projeto existir.
  </div>

  <div class="editor-grid">
    <div>
      <div class="scenario-actions">
        <button type="button" class="btn" id="scenario-reset">Restaurar o inventário original</button>
        <button type="button" class="btn" id="scenario-all">Marcar todos</button>
      </div>

      <div class="knobs" role="group" aria-label="Mutações do inventário">
        ${KNOBS.map((k) => `
          <label class="knob" for="knob-${k.id}">
            <input type="checkbox" id="knob-${k.id}" data-knob="${k.id}"
                   ${state.knobsOn?.has(k.id) ? "checked" : ""}>
            <span class="knob-body">
              <span class="knob-title">${esc(k.title)}</span>
              <span class="knob-desc">${esc(k.desc)}</span>
              <span class="knob-hits">afeta ${esc(k.hits)}</span>
            </span>
          </label>`).join("")}
      </div>
    </div>

    <div class="live-panel">
      <div class="card card-pad">
        <div class="kpi-label">Maturidade do cenário</div>
        <div class="kpi-value" style="color:var(--lvl-${Math.round(sc?.overall_maturity ?? 0)})">
          ${esc(sc ? sc.overall_maturity : "--")}<small> / 5</small></div>
        <div class="kpi-foot counts">${sc ? countsRow(sc.counts) : ""}</div>

        ${sc && base ? `
        <div class="live-delta ${delta < 0 ? "worse" : (delta > 0 ? "better" : "")}">
          ${delta === 0
            ? `Igual ao inventário original (${esc(base.overall_maturity)}).`
            : `${delta > 0 ? "Subiu" : "Caiu"} ${esc(Math.abs(delta))} ponto(s) em relação ao
               original (${esc(base.overall_maturity)} &rarr; ${esc(sc.overall_maturity)}).`}
        </div>` : ""}

        ${sc ? `
        <div style="margin-top:16px">
          <p class="block-label">Práticas</p>
          <div class="practice-list">
            ${sc.practices.map((p) => `
              <div class="practice ${p.ceiling_control ? "capped" : ""}" style="padding:10px 12px">
                <div class="practice-name" style="font-size:12.5px">${esc(practiceLabel(p.practice))}</div>
                <div class="practice-level" style="min-width:52px">
                  <span class="level-num" style="font-size:18px;color:var(--lvl-${p.level})">${p.level}</span>
                </div>
                ${p.ceiling_control ? `<p class="ceiling-note" style="font-size:11.5px;margin-top:6px">
                  <span aria-hidden="true">&#9888;</span>
                  <span>travada por <strong>${esc(p.ceiling_control)}</strong></span></p>` : ""}
              </div>`).join("")}
          </div>
        </div>` : `<div class="empty">Carregando cenário...</div>`}
      </div>
    </div>
  </div>

  ${sc?.controls ? `
  <div class="section">
    <h2>Controles reprovando neste cenário</h2>
    <div class="delta-list">
      ${sc.controls.filter((c) => c.verdict === "FAIL").map((c) => `
        <div class="delta">
          <div class="cid">${esc(c.id)}</div>
          <div>${esc(c.evidence)}</div>
          <div>${sevBadge(c.severity)} ${verdictBadge(c.verdict)}</div>
        </div>`).join("") || `<div class="empty">Nenhum controle reprovando.</div>`}
    </div>
  </div>` : ""}`;
}

function renderSimulation() {
  return `
  <div class="page-head">
    ${stepTag(5, "Simulação")}
    <h1>O que muda se</h1>
    <p>Duas formas de responder a mesma pergunta: comparar dois inventários já avaliados,
       ou editar um deles ao vivo e ver o verdict se mover na hora.</p>
  </div>

  <div class="sim-tabs" role="tablist" aria-label="Modo de simulação">
    <button type="button" class="sim-tab" role="tab" data-sim="compare"
            aria-selected="${state.simTab === "compare"}">Comparar dois estados</button>
    <button type="button" class="sim-tab" role="tab" data-sim="scenario"
            aria-selected="${state.simTab === "scenario"}">Editor de cenário</button>
  </div>

  <div id="sim-body"></div>`;
}

async function loadSimTab() {
  const host = document.getElementById("sim-body");
  if (!host) return;
  if (state.simTab === "compare") {
    const d = await api("/api/compare");
    host.innerHTML = renderCompareTab(d);
  } else {
    await ensureScenario();
    host.innerHTML = renderScenarioTab();
    wireScenario();
  }
}

function wireSimTabs() {
  document.querySelectorAll(".sim-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.simTab = btn.dataset.sim;
      document.querySelectorAll(".sim-tab").forEach((b) => {
        b.setAttribute("aria-selected", String(b.dataset.sim === state.simTab));
      });
      loadSimTab();
    });
  });
}

/* --------------------------------------------------------------- camada 6: Evidência */

function renderExport() {
  const formats = [
    { fmt: "md", name: "Markdown", desc: "O relatório para um humano ler no PR ou anexar num parecer." },
    { fmt: "json", name: "JSON", desc: "O par legível por máquina, e a origem do maturity_history da próxima execução." },
    { fmt: "sarif", name: "SARIF", desc: "Sobe para a aba Security do GitHub, onde cada gap aparece como finding." },
  ];

  return `
  <div class="page-head">
    ${stepTag(6, "Evidência")}
    <h1>Pacote de evidência</h1>
    <p>O artefato que se entrega a um auditor: verdict por controle, evidência coletada e
       remediação, no formato que o destinatário consome.</p>
  </div>

  <div class="export-grid">
    ${formats.map((f) => `
      <div class="export-card">
        <h3>${esc(f.name)}</h3>
        <p>${esc(f.desc)}</p>
        <a class="btn btn-primary" href="/export/${esc(state.stateName)}/${esc(f.fmt)}"
           download>Baixar report.${esc(f.fmt)}</a>
      </div>`).join("")}
  </div>

  <div class="section">
    <div class="notice">
      <strong>O relatório é gerado da mesma avaliação que a tela mostra.</strong> Não há
      segunda fonte de verdade: a CLI, o dashboard e o arquivo exportado saem do mesmo
      <code>evaluate()</code>, então divergir entre eles é impossível por construção.
    </div>
  </div>

  <div class="section">
    <h2>Reproduzir sem o dashboard</h2>
    <div class="block mono" style="white-space:pre-wrap">obsgov validate data/${esc(state.stateName)}
obsgov score    data/${esc(state.stateName)}
obsgov report   data/${esc(state.stateName)} --out out/${esc(state.stateName)}</div>
    <p class="section-hint">O subcomando <code>validate</code> sai com código 1 se
       qualquer controle MUST reprovar, que é o contrato do qual um gate de CI depende.</p>
  </div>`;
}

/* -------------------------------------------------------------------- detalhe */

async function openDrawer(controlId) {
  const detail = await api(`/api/state/${encodeURIComponent(state.stateName)}/controls/${encodeURIComponent(controlId)}`);

  document.getElementById("drawer-badges").innerHTML =
    `${sevBadge(detail.severity)} ${verdictBadge(detail.verdict)}
     <span class="sev">${esc(detail.cobit.join(", "))}</span>`;
  document.getElementById("drawer-title").textContent = `${detail.id} ${detail.title}`;

  document.getElementById("drawer-body").innerHTML = `
    <dl class="kv">
      <dt>Prática ITIL</dt><dd>${esc(practiceLabel(detail.practice))}</dd>
      <dt>Objetivo COBIT</dt><dd class="mono">${esc(detail.cobit.join(", "))}</dd>
      <dt>Severidade</dt><dd>${esc(detail.severity)}${detail.severity === "MUST"
        ? " (tem poder de travar a prática no nível 1)" : ""}</dd>
      <dt>Nível da prática</dt><dd>${esc(detail.practice_level ?? "--")} / 5</dd>
    </dl>

    ${detail.caps_practice ? `
    <p class="ceiling-note" style="margin-bottom:16px">
      <span aria-hidden="true">&#9888;</span>
      <span>Este é o controle que está travando a prática
      <strong>${esc(practiceLabel(detail.practice))}</strong> no nível 1.</span>
    </p>` : ""}

    <p class="block-label">Evidência coletada</p>
    <div class="block evidence-block">${esc(detail.evidence)}</div>

    ${detail.remediation ? `
      <p class="block-label">Remediação sugerida</p>
      <div class="block remediation-block">${esc(detail.remediation)}</div>` : ""}

    <p class="block-label">Como este controle é verificado</p>
    <div class="block">
      O controle é uma função pura <code>Inventory -&gt; Verdict</code> em
      <code>src/obsgov/evaluator.py</code>. Não há verificação por inspeção manual neste
      catálogo: se um controle não pode ser checado automaticamente, ele não entra.
    </div>`;

  document.getElementById("drawer-backdrop").hidden = false;
  document.getElementById("drawer").hidden = false;
  document.getElementById("drawer-close").focus();
}

function closeDrawer() {
  document.getElementById("drawer-backdrop").hidden = true;
  document.getElementById("drawer").hidden = true;
}

/* ------------------------------------------------------------------ topbar de contexto */

/* Barra de contexto sempre visível, independente da view atual. Antes o veredito e a
   maturidade só existiam dentro da tela de Scorecard, então trocar de tela perdia a
   referência de "estou avaliando o quê, e está passando?". */
async function refreshTopbar() {
  const host = document.getElementById("topbar-status");
  if (!host) return;
  try {
    const d = await api(`/api/state/${encodeURIComponent(state.stateName)}/scorecard`);
    const gatePass = d.musts_failed.length === 0;
    host.innerHTML = `
      <span class="topbar-gate ${gatePass ? "pass" : "fail"}">
        <span aria-hidden="true">${gatePass ? GLYPH.PASS : GLYPH.FAIL}</span>
        gate ${gatePass ? "passa" : "reprova"}
      </span>
      <span class="topbar-maturity">maturidade <b>${esc(d.overall_maturity)}</b> / 5</span>`;
  } catch {
    host.innerHTML = "";
  }
}

/* ---------------------------------------------------------------- orquestração */

async function loadView() {
  const host = document.getElementById("view");
  host.setAttribute("aria-busy", "true");

  try {
    if (state.view === "situation") {
      const d = await api(`/api/state/${encodeURIComponent(state.stateName)}/scorecard`);
      host.innerHTML = renderSituation(d);
      wireSituation();
    } else if (state.view === "scorecard") {
      const d = await api(`/api/state/${encodeURIComponent(state.stateName)}/scorecard`);
      host.innerHTML = renderScorecard(d);
    } else if (state.view === "controls") {
      const rows = await api(`/api/state/${encodeURIComponent(state.stateName)}/controls`);
      state.data.controls = rows;
      host.innerHTML = renderControls(rows);
      wireControls();
    } else if (state.view === "matrix") {
      const d = await api(`/api/state/${encodeURIComponent(state.stateName)}/matrix`);
      host.innerHTML = renderMatrix(d);
    } else if (state.view === "simulation") {
      host.innerHTML = renderSimulation();
      wireSimTabs();
      await loadSimTab();
    } else if (state.view === "export") {
      host.innerHTML = renderExport();
    }
  } catch (err) {
    host.innerHTML = `<div class="form-error">Falha ao carregar: ${esc(err.message)}</div>`;
  } finally {
    host.setAttribute("aria-busy", "false");
  }

  refreshTopbar();
}

function wireSituation() {
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.goto));
  });
  document.querySelectorAll("[data-open-control]").forEach((btn) => {
    btn.addEventListener("click", () => openDrawer(btn.dataset.openControl));
  });
}

function wireControls() {
  const search = document.getElementById("ctl-search");
  if (search) {
    search.addEventListener("input", (e) => {
      state.filters.q = e.target.value;
      const host = document.getElementById("view");
      host.innerHTML = renderControls(state.data.controls);
      wireControls();
      const again = document.getElementById("ctl-search");
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    });
  }

  document.querySelectorAll("[data-verdict]").forEach((btn) => {
    btn.addEventListener("click", () => {
      toggleSet(state.filters.verdicts, btn.dataset.verdict);
      refreshControls();
    });
  });
  document.querySelectorAll("[data-severity]").forEach((btn) => {
    btn.addEventListener("click", () => {
      toggleSet(state.filters.severities, btn.dataset.severity);
      refreshControls();
    });
  });

  document.querySelectorAll("tr.row-click").forEach((row) => {
    const open = () => openDrawer(row.dataset.id);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

function refreshControls() {
  document.getElementById("view").innerHTML = renderControls(state.data.controls);
  wireControls();
}

function toggleSet(set, value) {
  if (set.has(value)) set.delete(value); else set.add(value);
}

async function ensureScenario() {
  if (!state.knobsOn) state.knobsOn = new Set();
  if (!state.scenarioSource) {
    state.scenarioSource = await api(`/api/state/${encodeURIComponent(state.stateName)}/inventory`);
    state.scenarioBaseline = await api("/api/evaluate", {
      method: "POST",
      body: JSON.stringify(state.scenarioSource),
    });
    state.scenario = state.scenarioBaseline;
  }
}

async function applyKnobs() {
  const inv = structuredClone(state.scenarioSource);
  KNOBS.filter((k) => state.knobsOn.has(k.id)).forEach((k) => k.apply(inv));
  state.scenario = await api("/api/evaluate", { method: "POST", body: JSON.stringify(inv) });
  const host = document.getElementById("sim-body");
  if (host) host.innerHTML = renderScenarioTab();
  wireScenario();
}

function wireScenario() {
  document.querySelectorAll("[data-knob]").forEach((box) => {
    box.addEventListener("change", () => {
      toggleSet(state.knobsOn, box.dataset.knob);
      applyKnobs();
    });
  });
  const reset = document.getElementById("scenario-reset");
  if (reset) {
    reset.addEventListener("click", () => { state.knobsOn.clear(); applyKnobs(); });
  }
  const all = document.getElementById("scenario-all");
  if (all) {
    all.addEventListener("click", () => {
      KNOBS.forEach((k) => state.knobsOn.add(k.id));
      applyKnobs();
    });
  }
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((btn) => {
    if (btn.dataset.view === view) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  loadView();
}

function setStateName(name) {
  state.stateName = name;
  state.scenarioSource = null;
  state.scenario = null;
  state.knobsOn = new Set();
  document.querySelectorAll("[data-state]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.state === name));
  });
  loadView();
}

/* ------------------------------------------------------------------- portão */

function showGate() {
  document.getElementById("app").hidden = true;
  document.getElementById("gate").hidden = false;
  document.getElementById("login-user").focus();
}

async function showApp() {
  document.getElementById("gate").hidden = true;
  document.getElementById("app").hidden = false;

  // O mapa prática -> objetivos alimenta o rótulo do scorecard, e vem do catálogo.
  try {
    const catalog = await api("/api/catalog");
    const byPractice = {};
    catalog.forEach((c) => {
      byPractice[c.practice] = byPractice[c.practice] || new Set();
      c.cobit.forEach((o) => byPractice[c.practice].add(o));
    });
    state.data.cobitByPractice = Object.fromEntries(
      Object.entries(byPractice).map(([k, v]) => [k, [...v].sort()]),
    );
  } catch {
    state.data.cobitByPractice = {};
  }

  loadView();
}

function wireShell() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });
  document.querySelectorAll("[data-state]").forEach((btn) => {
    btn.addEventListener("click", () => setStateName(btn.dataset.state));
  });

  document.getElementById("logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    showGate();
  });

  document.getElementById("drawer-close").addEventListener("click", closeDrawer);
  document.getElementById("drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("drawer").hidden) closeDrawer();
  });

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorBox = document.getElementById("login-error");
    errorBox.hidden = true;
    try {
      await api("/api/login", {
        method: "POST",
        body: JSON.stringify({
          user: document.getElementById("login-user").value,
          password: document.getElementById("login-password").value,
        }),
      });
      showApp();
    } catch (err) {
      errorBox.textContent = err.message === "sessão expirada"
        ? "Credencial inválida."
        : `Não foi possível entrar: ${err.message}`;
      errorBox.hidden = false;
    }
  });
}

async function boot() {
  wireShell();
  try {
    const session = await fetch("/api/session").then((r) => r.json());
    if (session.authenticated) showApp(); else showGate();
  } catch {
    showGate();
  }
}

boot();
