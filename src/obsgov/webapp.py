"""Dashboard HTTP do avaliador, só com a standard library.

Por que `http.server` e não FastAPI: o ADR-0001 diz que o pacote instalado depende só
da standard library, porque o gate roda antes de qualquer instalação no CI. Um dashboard
é motivo para revisitar essa decisão, não para abandoná-la. Ver ADR-0002. Toda a camada
web aqui é `http.server`, `json`, `hmac` e `secrets`, então instalar o pacote continua
não trazendo nada.

Formato do módulo, de propósito:

- Funções puras montam todo payload e toda decisão de auth. Recebem dado e devolvem
  dado, então cada branch é testável sem abrir socket.
- `Handler` é uma casca fina que mapeia requisição para uma dessas funções. Não guarda
  lógica que valha testar duas vezes.
- Os dois inventários são carregados e avaliados uma vez, no startup, e ficam em
  `AppState`. O fixture não muda enquanto o processo vive.
- O editor de cenário é a exceção que precisa avaliar sob demanda, e por isso recebe o
  inventário inteiro no corpo da requisição em vez de mutar o estado do processo. Duas
  abas abertas não interferem uma na outra.

Auth é cookie assinado, checado no servidor. A credencial é um portão de demonstração,
não controle de segurança, porque o dado é sintético e read-only. Mas a checagem é
server-side de qualquer forma, porque portão validado em JavaScript não é portão.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from obsgov import __version__
from obsgov.evaluator import (
    CONTROLS,
    ControlResult,
    PracticeScore,
    Severity,
    Verdict,
    evaluate,
    overall_maturity,
    score_all,
)
from obsgov.loader import LoaderError, load_inventory
from obsgov.model import Inventory
from obsgov.report import dump_json, dump_sarif, to_markdown

WEB_ROOT = Path(__file__).resolve().parent / "web"

SESSION_COOKIE = "obsgov_session"
SESSION_TTL_SECONDS = 28_800  # oito horas: um dia de trabalho, depois re-autentica
_SESSION_PARTS = 3  # user.expiry.signature
DEFAULT_USER = "julianovincedecampos"
DEFAULT_PASSWORD = "observability-governance-lab"
MAX_BODY_BYTES = 256 * 1024  # o editor de cenário manda o inventário inteiro

# Endpoints alcançáveis sem sessão. Health tem que responder para o probe do container
# antes de alguém logar; login seria deadlock de outra forma.
PUBLIC_API = frozenset({"/api/health", "/api/login", "/api/session"})

# Nome de estado -> diretório do fixture. Explícito para que nenhum caminho seja montado
# a partir de entrada de rede.
STATES: dict[str, str] = {"bad-state": "bad-state", "good-state": "good-state"}


# --------------------------------------------------------------------------------------
# estado
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Credentials:
    user: str
    password: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Credentials:
        source = env if env is not None else dict(os.environ)
        return cls(
            user=source.get("OBSGOV_USER") or DEFAULT_USER,
            password=source.get("OBSGOV_PASSWORD") or DEFAULT_PASSWORD,
        )


@dataclass(frozen=True, slots=True)
class StateEval:
    """Um inventário carregado e já avaliado."""

    name: str
    inventory: Inventory
    results: tuple[ControlResult, ...]
    scores: tuple[PracticeScore, ...]


@dataclass(slots=True)
class AppState:
    """Tudo que uma requisição precisa, computado uma vez."""

    evaluations: dict[str, StateEval]
    credentials: Credentials
    secret: bytes
    data_root: str

    def get(self, name: str) -> StateEval | None:
        return self.evaluations.get(name)


def build_state(
    data_root: Path,
    *,
    credentials: Credentials | None = None,
    secret: bytes | None = None,
) -> AppState:
    """Carrega e avalia cada fixture uma vez, e congela no estado da aplicação."""
    evaluations: dict[str, StateEval] = {}
    for name, folder in STATES.items():
        path = data_root / folder
        if not path.is_dir():
            continue
        inventory = load_inventory(path)
        results = evaluate(inventory)
        evaluations[name] = StateEval(name, inventory, results, score_all(results))

    if not evaluations:
        raise ValueError(f"nenhum fixture encontrado em {data_root}")

    return AppState(
        evaluations=evaluations,
        credentials=credentials or Credentials.from_env(),
        # Segredo por processo significa que sessão não sobrevive a restart. É a troca
        # certa para um demo stateless: nada compartilhado para vazar, nada para rodar.
        secret=secret or secrets.token_bytes(32),
        data_root=str(data_root),
    )


# --------------------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------------------


def credentials_ok(credentials: Credentials, user: str, password: str) -> bool:
    """Comparação de tempo constante nos dois campos, então timing não diz nada útil."""
    user_ok = hmac.compare_digest(credentials.user.encode(), user.encode())
    password_ok = hmac.compare_digest(credentials.password.encode(), password.encode())
    return user_ok and password_ok


def _sign(secret: bytes, payload: str) -> str:
    digest = hmac.new(secret, payload.encode("utf-8"), sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def make_session(secret: bytes, user: str, *, now: float | None = None) -> str:
    """`user.expiry.signature`, urlsafe. Nenhum material secreto no cookie."""
    expiry = int((now if now is not None else time.time()) + SESSION_TTL_SECONDS)
    payload = f"{user}.{expiry}"
    return f"{payload}.{_sign(secret, payload)}"


def read_session(secret: bytes, token: str | None, *, now: float | None = None) -> str | None:
    """Devolve o usuário de um token válido, ou None. Falha fechado em qualquer anomalia."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != _SESSION_PARTS:
        return None
    user, raw_expiry, signature = parts
    if not hmac.compare_digest(_sign(secret, f"{user}.{raw_expiry}"), signature):
        return None
    try:
        expiry = int(raw_expiry)
    except ValueError:
        return None
    if expiry < (now if now is not None else time.time()):
        return None
    return user


def cookie_value(header: str | None, name: str) -> str | None:
    """Leitor mínimo de cookie: o parser da stdlib é leniente de formas desnecessárias."""
    if not header:
        return None
    for chunk in header.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == name:
            return value or None
    return None


# --------------------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------------------

_CONTROL_BY_ID = {c.id: c for c in CONTROLS}


def _control_payload(r: ControlResult) -> dict[str, Any]:
    control = _CONTROL_BY_ID.get(r.control_id)
    return {
        "id": r.control_id,
        "title": control.title if control else r.control_id,
        "severity": r.severity.value,
        "practice": r.practice,
        "cobit": list(r.cobit),
        "verdict": r.verdict.value,
        "evidence": r.evidence,
        "remediation": r.remediation,
    }


def _counts(results: tuple[ControlResult, ...]) -> dict[str, int]:
    return {v.value: sum(1 for r in results if r.verdict == v) for v in Verdict}


def scorecard_payload(ev: StateEval) -> dict[str, Any]:
    """A home. Maturidade por prática, com o controle de teto nomeado onde existe."""
    practices = []
    for s in ev.scores:
        mine = [r for r in ev.results if r.practice == s.practice]
        practices.append(
            {
                "practice": s.practice,
                "level": s.level,
                "ceiling_control": s.ceiling_control,
                "counts": s.counts or _counts(tuple(mine)),
                "total": len(mine),
            }
        )
    return {
        "state": ev.name,
        "overall_maturity": overall_maturity(ev.scores),
        "practices": practices,
        "counts": _counts(ev.results),
        "total_controls": len(ev.results),
        "musts_failed": [
            r.control_id
            for r in ev.results
            if r.severity == Severity.MUST and r.verdict == Verdict.FAIL
        ],
    }


def controls_payload(ev: StateEval) -> list[dict[str, Any]]:
    return [_control_payload(r) for r in ev.results]


def control_detail(ev: StateEval, control_id: str) -> dict[str, Any] | None:
    match = next((r for r in ev.results if r.control_id == control_id), None)
    if match is None:
        return None
    detail = _control_payload(match)
    detail["practice_level"] = next(
        (s.level for s in ev.scores if s.practice == match.practice), None
    )
    detail["caps_practice"] = any(
        s.practice == match.practice and s.ceiling_control == match.control_id for s in ev.scores
    )
    return detail


def matrix_payload(ev: StateEval) -> dict[str, Any]:
    """Heatmap prática x objetivo COBIT. Célula vazia é informação, não lacuna de dado."""
    practices = sorted({r.practice for r in ev.results})
    objectives = sorted({o for r in ev.results for o in r.cobit})
    cells: dict[str, dict[str, Any]] = {}
    for practice in practices:
        row: dict[str, Any] = {}
        for objective in objectives:
            hits = [r for r in ev.results if r.practice == practice and objective in r.cobit]
            if not hits:
                row[objective] = None
                continue
            row[objective] = {
                "total": len(hits),
                "ids": [r.control_id for r in hits],
                "counts": _counts(tuple(hits)),
                "worst": _worst_verdict(hits),
            }
        cells[practice] = row
    return {"state": ev.name, "practices": practices, "objectives": objectives, "cells": cells}


def _worst_verdict(results: list[ControlResult]) -> str:
    """FAIL domina, depois WAIVED, depois PASS. SKIP nunca some numa célula verde."""
    order = (Verdict.FAIL, Verdict.WAIVED, Verdict.SKIP, Verdict.PASS)
    present = {r.verdict for r in results}
    for verdict in order:
        if verdict in present:
            return verdict.value
    return Verdict.SKIP.value


def compare_payload(state: AppState) -> dict[str, Any]:
    """bad-state contra good-state, com o delta por controle. É o print do README."""
    bad = state.get("bad-state")
    good = state.get("good-state")
    if bad is None or good is None:
        return {"available": False}

    good_by_id = {r.control_id: r for r in good.results}
    rows = []
    for before in bad.results:
        after = good_by_id.get(before.control_id)
        if after is None:
            continue
        rows.append(
            {
                "id": before.control_id,
                "title": _CONTROL_BY_ID[before.control_id].title,
                "severity": before.severity.value,
                "practice": before.practice,
                "before": before.verdict.value,
                "after": after.verdict.value,
                "changed": before.verdict != after.verdict,
                "fixed": before.verdict == Verdict.FAIL and after.verdict == Verdict.PASS,
            }
        )

    return {
        "available": True,
        "before": {
            "state": bad.name,
            "overall_maturity": overall_maturity(bad.scores),
            "counts": _counts(bad.results),
        },
        "after": {
            "state": good.name,
            "overall_maturity": overall_maturity(good.scores),
            "counts": _counts(good.results),
        },
        "practices": [
            {
                "practice": s.practice,
                "before": s.level,
                "after": next((g.level for g in good.scores if g.practice == s.practice), None),
                "ceiling_before": s.ceiling_control,
            }
            for s in bad.scores
        ],
        "controls": rows,
        "fixed_count": sum(1 for r in rows if r["fixed"]),
    }


def catalog_payload() -> list[dict[str, Any]]:
    """O catálogo em si, sem avaliação. Alimenta o editor de cenário e a documentação."""
    return [
        {
            "id": c.id,
            "title": c.title,
            "severity": c.severity.value,
            "practice": c.practice,
            "cobit": list(c.cobit),
            "remediation": c.remediation,
        }
        for c in CONTROLS
    ]


def inventory_payload(ev: StateEval) -> dict[str, Any]:
    """O inventário declarado, no formato que o editor de cenário edita e devolve."""
    inv = ev.inventory
    return {
        "state": ev.name,
        "services": [
            {
                "name": s.name,
                "tier": s.tier,
                "owner": s.owner,
                "depends_on": list(s.depends_on),
                "signals": list(s.signals),
            }
            for s in inv.services
        ],
        "slos": [
            {
                "service": s.service,
                "sli_name": s.sli_name,
                "sli_metric": s.sli_metric,
                "target_pct": s.target_pct,
                "window_days": s.window_days,
                "owner": s.owner,
                "review_cadence_days": s.review_cadence_days,
                "error_budget": {"consequence": s.error_budget.consequence},
                "burn_rate_alert": s.burn_rate_alert,
                "evidence_ref": s.evidence_ref,
                "consumer_measured": s.consumer_measured,
            }
            for s in inv.slos
        ],
        "alerts": [
            {
                "id": a.id,
                "service": a.service,
                "metric": a.metric,
                "severity": a.severity,
                "runbook_ref": a.runbook_ref,
                "owner": a.owner,
            }
            for a in inv.alerts
        ],
        "runbooks": [
            {
                "id": r.id,
                "title": r.title,
                "resolves": list(r.resolves),
                "last_tested_days_ago": r.last_tested_days_ago,
                "test_window_days": r.test_window_days,
            }
            for r in inv.runbooks
        ],
        "change_log": {
            "problems": [
                {
                    "signature": p.signature,
                    "incident_refs": list(p.incident_refs),
                    "workaround": p.workaround,
                    "postmortem_ref": p.postmortem_ref,
                }
                for p in inv.problems
            ],
            "changes": [
                {
                    "service": c.service,
                    "deploy_marker_emitted": c.deploy_marker_emitted,
                    "rollback_signal": c.rollback_signal,
                    "verification_window_hours": c.verification_window_hours,
                }
                for c in inv.changes
            ],
            "watchdogs": [
                {
                    "name": w.name,
                    "monitors": list(w.monitors),
                    "heartbeat_interval_minutes": w.heartbeat_interval_minutes,
                }
                for w in inv.watchdogs
            ],
            "retention": [
                {"signal": r.signal, "retention_days": r.retention_days} for r in inv.retention
            ],
            "collector_attributes": [
                {"name": a.name, "otel_semantic": a.otel_semantic} for a in inv.collector_attributes
            ],
            "cardinality_budgets": [
                {"metric": b.metric, "max_series": b.max_series} for b in inv.cardinality_budgets
            ],
            "trace_id_correlation_verified": inv.trace_id_correlation_verified,
            "maturity_history": list(inv.maturity_history),
        },
    }


def evaluate_scenario(body: dict[str, Any]) -> dict[str, Any]:
    """Avalia um inventário vindo do navegador, sem tocar o estado do processo.

    O editor de cenário é a tela que ensina a tese: apaga a referência de runbook de um
    alerta e a prática despenca de nível 3 para 1 pela regra de teto. Para isso o
    inventário precisa vir na requisição, não do disco.
    """
    from obsgov.loader import (
        _alerts,
        _cardinality,
        _changes,
        _collector_attrs,
        _problems,
        _retention,
        _runbooks,
        _services,
        _slos,
        _watchdogs,
    )

    change_log = body.get("change_log") or {}
    try:
        inv = Inventory(
            services=_services(body.get("services", [])),
            slos=_slos(body.get("slos", [])),
            alerts=_alerts(body.get("alerts", [])),
            runbooks=_runbooks(body.get("runbooks", [])),
            problems=_problems(change_log.get("problems", [])),
            changes=_changes(change_log.get("changes", [])),
            watchdogs=_watchdogs(change_log.get("watchdogs", [])),
            retention=_retention(change_log.get("retention", [])),
            collector_attributes=_collector_attrs(change_log.get("collector_attributes", [])),
            cardinality_budgets=_cardinality(change_log.get("cardinality_budgets", [])),
            trace_id_correlation_verified=bool(
                change_log.get("trace_id_correlation_verified", False)
            ),
            maturity_history=tuple(change_log.get("maturity_history", [])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"inventário inválido: {exc}"}

    results = evaluate(inv)
    scores = score_all(results)
    ev = StateEval("cenário", inv, results, scores)
    payload = scorecard_payload(ev)
    payload["ok"] = True
    payload["controls"] = controls_payload(ev)
    return payload


def export_payload(ev: StateEval, fmt: str) -> tuple[str, str] | None:
    """Devolve (conteúdo, content-type) para markdown, json ou sarif."""
    if fmt == "md":
        return to_markdown(ev.results, ev.scores), "text/markdown; charset=utf-8"
    if fmt == "json":
        return dump_json(ev.results, ev.scores), "application/json; charset=utf-8"
    if fmt == "sarif":
        return dump_sarif(ev.results), "application/json; charset=utf-8"
    return None


# --------------------------------------------------------------------------------------
# roteamento
# --------------------------------------------------------------------------------------


def _json_error(status: HTTPStatus, message: str) -> tuple[HTTPStatus, dict[str, Any]]:
    return status, {"error": message}


# Rotas GET que dependem de um estado nomeado. Dict em vez de escada de `if path ==`:
# adicionar uma view é uma linha, e o router fica plano o suficiente para ler.
_STATE_ROUTES: dict[str, Callable[[StateEval], Any]] = {
    "scorecard": scorecard_payload,
    "controls": controls_payload,
    "matrix": matrix_payload,
    "inventory": inventory_payload,
}

_STATE_PREFIX = "/api/state/"


def _handle_state_get(state: AppState, rest: str) -> tuple[HTTPStatus, Any]:
    """Roteia `/api/state/<nome>/<view>`. Separado para o router principal ficar plano."""
    state_name, _, view = rest.partition("/")
    ev = state.get(state_name)
    if ev is None:
        return _json_error(HTTPStatus.NOT_FOUND, "estado desconhecido")

    builder = _STATE_ROUTES.get(view)
    if builder is not None:
        return HTTPStatus.OK, builder(ev)

    if view.startswith("controls/"):
        detail = control_detail(ev, view.removeprefix("controls/"))
        return (
            (HTTPStatus.OK, detail)
            if detail is not None
            else _json_error(HTTPStatus.NOT_FOUND, "controle desconhecido")
        )

    return _json_error(HTTPStatus.NOT_FOUND, "view desconhecida")


def handle_get(state: AppState, path: str, user: str | None) -> tuple[HTTPStatus, Any]:
    """Roteia um GET sob /api. Devolve (status, payload), nunca toca o socket."""
    if path == "/api/health":
        return HTTPStatus.OK, {"status": "ok", "version": __version__}
    if path == "/api/session":
        return HTTPStatus.OK, {"authenticated": user is not None, "user": user}

    if user is None:
        return _json_error(HTTPStatus.UNAUTHORIZED, "autenticação necessária")

    global_routes: dict[str, Callable[[], Any]] = {
        "/api/states": lambda: {"states": sorted(state.evaluations)},
        "/api/catalog": catalog_payload,
        "/api/compare": lambda: compare_payload(state),
    }
    builder = global_routes.get(path)
    if builder is not None:
        return HTTPStatus.OK, builder()

    if path.startswith(_STATE_PREFIX):
        return _handle_state_get(state, path.removeprefix(_STATE_PREFIX))

    return _json_error(HTTPStatus.NOT_FOUND, "endpoint desconhecido")


def handle_post(
    state: AppState, path: str, body: dict[str, Any], user: str | None
) -> tuple[HTTPStatus, Any, str | None]:
    """Roteia um POST. O terceiro elemento é o token de sessão a definir, ou None."""
    if path == "/api/login":
        given_user = str(body.get("user", ""))
        given_password = str(body.get("password", ""))
        if not credentials_ok(state.credentials, given_user, given_password):
            return HTTPStatus.UNAUTHORIZED, {"error": "credencial inválida"}, None
        # A sessão é assinada sobre a credencial configurada, não sobre a string que
        # chegou na requisição. Depois de credentials_ok as duas são iguais, mas assim
        # nada vindo da rede alcança um header Set-Cookie, nem por construção.
        return (
            HTTPStatus.OK,
            {"authenticated": True, "user": state.credentials.user},
            make_session(state.secret, state.credentials.user),
        )

    if path == "/api/logout":
        return HTTPStatus.OK, {"authenticated": False}, ""

    if user is None:
        return HTTPStatus.UNAUTHORIZED, {"error": "autenticação necessária"}, None

    if path == "/api/evaluate":
        return HTTPStatus.OK, evaluate_scenario(body), None

    return HTTPStatus.NOT_FOUND, {"error": "endpoint desconhecido"}, None


_HTML = "text/html; charset=utf-8"

# O bundle é um conjunto fixo de três arquivos, não um diretório para servir. Mapear
# URL -> (nome, content-type) explicitamente elimina a construção de caminho a partir
# de entrada de rede: não há travessia a barrar porque não há caminho a montar.
_STATIC: dict[str, tuple[str, str]] = {
    "": ("index.html", _HTML),
    "/": ("index.html", _HTML),
    "/index.html": ("index.html", _HTML),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def static_file(path: str) -> tuple[Path, str] | None:
    """Resolve uma URL para um arquivo do bundle e seu content-type, ou None."""
    entry = _STATIC.get(path)
    if entry is None:
        return None
    name, content_type = entry
    candidate = WEB_ROOT / name
    if not candidate.is_file():
        return None
    return candidate, content_type


_EXPORT_PREFIX = "/export/"


def export_route(state: AppState, path: str) -> tuple[str, str, str] | None:
    """Resolve /export/<estado>/<fmt> para (conteúdo, content-type, nome do arquivo)."""
    if not path.startswith(_EXPORT_PREFIX):
        return None
    rest = path.removeprefix(_EXPORT_PREFIX)
    state_name, _, fmt = rest.partition("/")
    ev = state.get(state_name)
    if ev is None:
        return None
    resolved = export_payload(ev, fmt)
    if resolved is None:
        return None
    content, content_type = resolved
    return content, content_type, f"report-{state_name}.{fmt}"


# --------------------------------------------------------------------------------------
# servidor
# --------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    """Casca fina. Toda decisão que ela toma vive numa função acima."""

    server_version = f"obsgov/{__version__}"

    # HTTP/1.1 explícito. O default de BaseHTTPRequestHandler é HTTP/1.0, que fecha a
    # conexão a cada resposta; atrás de um proxy que reusa a conexão upstream isso
    # dessincroniza o par requisição/resposta. Toda resposta aqui carrega Content-Length,
    # que é o que HTTP/1.1 exige para manter a conexão viva com segurança.
    protocol_version = "HTTP/1.1"

    # HEAD reusa o caminho do GET e suprime o corpo. A flag é por conexão, e o handler é
    # instanciado por conexão, então não há estado compartilhado entre clientes.
    _body_suppressed = False

    state: AppState

    def log_message(self, _format: str, *args: Any) -> None:
        print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else '?'}")

    # -- helpers ----------------------------------------------------------------

    def _current_user(self) -> str | None:
        token = cookie_value(self.headers.get("Cookie"), SESSION_COOKIE)
        return read_session(self.state.secret, token)

    def _send_json(self, status: HTTPStatus, payload: Any, session: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if session is not None:
            self._send_session_cookie(session)
        self._send_hardening_headers()
        self.end_headers()
        self._write_body(body)

    def _write_body(self, body: bytes) -> None:
        """Escreve o corpo, a menos que a requisição seja HEAD."""
        if not self._body_suppressed:
            self.wfile.write(body)

    def _send_session_cookie(self, session: str) -> None:
        if session:
            cookie = (
                f"{SESSION_COOKIE}={session}; Path=/; HttpOnly; SameSite=Strict; "
                f"Max-Age={SESSION_TTL_SECONDS}"
            )
        else:
            cookie = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        self.send_header("Set-Cookie", cookie)

    def _send_hardening_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            # Recusar sem ler deixaria o corpo na conexão, e com keep-alive o próximo
            # request seria parseado a partir desses bytes. Fecha em vez de
            # dessincronizar.
            self.close_connection = True
            return {}
        try:
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # -- verbos -----------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            status, payload = handle_get(self.state, path, self._current_user())
            self._send_json(status, payload)
            return

        if path.startswith(_EXPORT_PREFIX):
            if self._current_user() is None:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "autenticação necessária"})
                return
            resolved = export_route(self.state, path)
            if resolved is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "export desconhecido"})
                return
            content, content_type, filename = resolved
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self._send_hardening_headers()
            self.end_headers()
            self._write_body(body)
            return

        resolved_static = static_file(path)
        if resolved_static is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "não encontrado"})
            return

        target, content_type = resolved_static
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # O nome do arquivo não carrega hash de conteúdo, então um cache intermediário
        # que guardasse styles.css serviria a folha antiga depois de um deploy. no-cache
        # obriga revalidar; não proíbe cachear, só proíbe servir sem checar.
        self.send_header("Cache-Control", "no-cache")
        self._send_hardening_headers()
        self.end_headers()
        self._write_body(body)

    def do_HEAD(self) -> None:
        # Sem isto o BaseHTTPRequestHandler devolve 501 para HEAD, e monitoração externa,
        # verificador de link e alguns proxies sondam com HEAD em vez de GET.
        self._body_suppressed = True
        try:
            self.do_GET()
        finally:
            self._body_suppressed = False

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        # Drena o corpo antes de decidir a rota. Responder 404 sem ler o corpo deixa
        # bytes na conexão, e com keep-alive eles viram a próxima linha de request.
        body = self._read_body()
        if not path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "não encontrado"})
            return
        status, payload, session = handle_post(self.state, path, body, self._current_user())
        self._send_json(status, payload, session)


def make_server(state: AppState, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer((host, port), handler)


def serve(
    data_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> int:  # pragma: no cover - loop bloqueante, exercitado pelo health check do container
    try:
        state = build_state(data_root)
    except (LoaderError, ValueError) as exc:
        print(f"erro: {exc}")
        return 2

    httpd = make_server(state, host, port)
    estados = ", ".join(
        f"{name} {overall_maturity(ev.scores)}/5" for name, ev in sorted(state.evaluations.items())
    )
    print(
        f"obsgov {__version__} em http://{host}:{port}  "
        f"({len(CONTROLS)} controles, {estados}, usuário {state.credentials.user})"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nparando")
    finally:
        httpd.server_close()
    return 0
