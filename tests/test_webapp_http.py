"""Teste de integração do servidor: sobe de verdade e bate nas rotas por HTTP.

Os testes de `test_webapp.py` cobrem as funções puras. Este cobre a casca: cookie de
sessão indo e voltando por header, HEAD sem corpo, Content-Length presente, headers de
hardening, arquivo estático servido, download com Content-Disposition, e o 401 de quem
não tem sessão. É o que o container health check exercita em produção.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path

import pytest

from obsgov.webapp import AppState, Credentials, build_state, make_server

DATA = Path("data")
USER = "demo"
PASSWORD = "senha"


@pytest.fixture(scope="module")
def server() -> Iterator[tuple[str, AppState]]:
    state = build_state(
        DATA,
        credentials=Credentials(user=USER, password=PASSWORD),
        secret=b"segredo-de-teste-http",
    )
    # Porta 0: o SO escolhe uma livre, então rodar a suíte em paralelo não colide.
    httpd = make_server(state, host="127.0.0.1", port=0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}", state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    cookie: str | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


def login(base: str) -> str:
    status, _, headers = request(
        base, "/api/login", method="POST", body={"user": USER, "password": PASSWORD}
    )
    assert status == HTTPStatus.OK
    raw = headers["Set-Cookie"]
    return raw.split(";", 1)[0]


class TestSemSessao:
    def test_health_responde(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, body, headers = request(base, "/api/health")
        assert status == HTTPStatus.OK
        assert json.loads(body)["status"] == "ok"
        assert "Content-Length" in headers

    def test_endpoint_protegido_devolve_401(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, _, _ = request(base, "/api/state/bad-state/scorecard")
        assert status == HTTPStatus.UNAUTHORIZED

    def test_export_sem_sessao_devolve_401(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, _, _ = request(base, "/export/good-state/md")
        assert status == HTTPStatus.UNAUTHORIZED

    def test_login_com_senha_errada(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, _, _ = request(
            base, "/api/login", method="POST", body={"user": USER, "password": "x"}
        )
        assert status == HTTPStatus.UNAUTHORIZED

    def test_headers_de_hardening_presentes(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        _, _, headers = request(base, "/api/health")
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"


class TestArquivoEstatico:
    @pytest.mark.parametrize(
        ("path", "esperado"),
        [
            ("/", "text/html"),
            ("/index.html", "text/html"),
            ("/app.js", "text/javascript"),
            ("/styles.css", "text/css"),
        ],
    )
    def test_serve_o_bundle(self, server: tuple[str, AppState], path: str, esperado: str) -> None:
        base, _ = server
        status, body, headers = request(base, path)
        assert status == HTTPStatus.OK
        assert esperado in headers["Content-Type"]
        assert len(body) > 0
        assert headers["Content-Length"] == str(len(body))

    def test_caminho_inexistente_devolve_404(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, _, _ = request(base, "/nao-existe.txt")
        assert status == HTTPStatus.NOT_FOUND

    def test_head_nao_devolve_corpo(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, body, headers = request(base, "/api/health", method="HEAD")
        assert status == HTTPStatus.OK
        assert body == b""
        # O Content-Length continua anunciando o tamanho que um GET devolveria.
        assert int(headers["Content-Length"]) > 0


class TestComSessao:
    def test_fluxo_de_login_e_sessao(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        cookie = login(base)
        status, body, _ = request(base, "/api/session", cookie=cookie)
        assert status == HTTPStatus.OK
        payload = json.loads(body)
        assert payload["authenticated"] is True
        assert payload["user"] == USER

    def test_scorecard_dos_dois_estados(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        cookie = login(base)
        for estado in ("bad-state", "good-state"):
            status, body, _ = request(base, f"/api/state/{estado}/scorecard", cookie=cookie)
            assert status == HTTPStatus.OK
            payload = json.loads(body)
            assert payload["state"] == estado
            assert payload["total_controls"] == 30

    def test_compare_disponivel(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        cookie = login(base)
        status, body, _ = request(base, "/api/compare", cookie=cookie)
        assert status == HTTPStatus.OK
        payload = json.loads(body)
        assert payload["available"] is True
        assert payload["after"]["overall_maturity"] > payload["before"]["overall_maturity"]

    def test_evaluate_aceita_inventario_do_proprio_endpoint(
        self, server: tuple[str, AppState]
    ) -> None:
        """Ida e volta pelo HTTP: o que /inventory devolve, /evaluate aceita."""
        base, _ = server
        cookie = login(base)
        status, body, _ = request(base, "/api/state/good-state/inventory", cookie=cookie)
        assert status == HTTPStatus.OK
        inventario = json.loads(body)

        status, body, _ = request(
            base, "/api/evaluate", method="POST", body=inventario, cookie=cookie
        )
        assert status == HTTPStatus.OK
        assert json.loads(body)["ok"] is True

    @pytest.mark.parametrize("fmt", ["md", "json", "sarif"])
    def test_export_baixa_com_content_disposition(
        self, server: tuple[str, AppState], fmt: str
    ) -> None:
        base, _ = server
        cookie = login(base)
        status, body, headers = request(base, f"/export/good-state/{fmt}", cookie=cookie)
        assert status == HTTPStatus.OK
        assert f"report-good-state.{fmt}" in headers["Content-Disposition"]
        assert len(body) > 0

    def test_export_com_formato_invalido(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        cookie = login(base)
        status, _, _ = request(base, "/export/good-state/pdf", cookie=cookie)
        assert status == HTTPStatus.NOT_FOUND

    def test_logout_invalida_a_sessao(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        cookie = login(base)
        status, _, headers = request(base, "/api/logout", method="POST", body={}, cookie=cookie)
        assert status == HTTPStatus.OK
        assert "Max-Age=0" in headers["Set-Cookie"]

    def test_cookie_forjado_nao_autentica(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        status, body, _ = request(
            base, "/api/session", cookie="obsgov_session=demo.99999999999.forjado"
        )
        assert status == HTTPStatus.OK
        assert json.loads(body)["authenticated"] is False

    def test_post_fora_da_api_devolve_404(self, server: tuple[str, AppState]) -> None:
        base, _ = server
        cookie = login(base)
        status, _, _ = request(base, "/qualquer", method="POST", body={}, cookie=cookie)
        assert status == HTTPStatus.NOT_FOUND
