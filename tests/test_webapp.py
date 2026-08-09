"""Testes do dashboard: auth, roteamento e formato dos payloads.

Toda decisão do webapp vive em função pura, então nenhum teste aqui abre socket. O que
precisa de servidor de verdade é o health check do container.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

import pytest

from obsgov.webapp import (
    AppState,
    Credentials,
    build_state,
    compare_payload,
    controls_payload,
    cookie_value,
    credentials_ok,
    evaluate_scenario,
    export_route,
    handle_get,
    handle_post,
    inventory_payload,
    make_session,
    matrix_payload,
    read_session,
    scorecard_payload,
    static_file,
)

DATA = Path("data")


@pytest.fixture
def app_state() -> AppState:
    return build_state(
        DATA,
        credentials=Credentials(user="demo", password="senha"),
        secret=b"segredo-de-teste-fixo",
    )


class TestAuth:
    def test_credentials_ok_exige_os_dois_campos(self) -> None:
        creds = Credentials(user="demo", password="senha")
        assert credentials_ok(creds, "demo", "senha")
        assert not credentials_ok(creds, "demo", "errada")
        assert not credentials_ok(creds, "outro", "senha")

    def test_sessao_ida_e_volta(self) -> None:
        secret = b"s"
        token = make_session(secret, "demo")
        assert read_session(secret, token) == "demo"

    def test_sessao_com_segredo_diferente_nao_valida(self) -> None:
        token = make_session(b"um", "demo")
        assert read_session(b"outro", token) is None

    def test_sessao_expirada_nao_valida(self) -> None:
        secret = b"s"
        token = make_session(secret, "demo", now=0)
        assert read_session(secret, token, now=10**12) is None

    def test_token_malformado_falha_fechado(self) -> None:
        secret = b"s"
        assert read_session(secret, None) is None
        assert read_session(secret, "") is None
        assert read_session(secret, "sem-pontos") is None
        assert read_session(secret, "a.b") is None
        assert read_session(secret, "demo.nao-numero.assinatura") is None

    def test_cookie_value_le_o_par_certo(self) -> None:
        header = "outro=1; obsgov_session=abc; mais=2"
        assert cookie_value(header, "obsgov_session") == "abc"
        assert cookie_value(header, "ausente") is None
        assert cookie_value(None, "obsgov_session") is None


class TestRoteamentoGet:
    def test_health_e_publico(self, app_state: AppState) -> None:
        status, payload = handle_get(app_state, "/api/health", None)
        assert status == HTTPStatus.OK
        assert payload["status"] == "ok"

    def test_session_e_publico(self, app_state: AppState) -> None:
        status, payload = handle_get(app_state, "/api/session", None)
        assert status == HTTPStatus.OK
        assert payload["authenticated"] is False

    def test_endpoint_protegido_exige_sessao(self, app_state: AppState) -> None:
        status, _ = handle_get(app_state, "/api/state/bad-state/scorecard", None)
        assert status == HTTPStatus.UNAUTHORIZED

    def test_scorecard_com_sessao(self, app_state: AppState) -> None:
        status, payload = handle_get(app_state, "/api/state/bad-state/scorecard", "demo")
        assert status == HTTPStatus.OK
        assert payload["state"] == "bad-state"
        assert payload["total_controls"] == 30

    def test_catalogo_e_estados(self, app_state: AppState) -> None:
        status, states = handle_get(app_state, "/api/states", "demo")
        assert status == HTTPStatus.OK
        assert states["states"] == ["bad-state", "good-state"]

        status, catalog = handle_get(app_state, "/api/catalog", "demo")
        assert status == HTTPStatus.OK
        assert len(catalog) == 30

    def test_estado_desconhecido_da_404(self, app_state: AppState) -> None:
        status, _ = handle_get(app_state, "/api/state/nao-existe/scorecard", "demo")
        assert status == HTTPStatus.NOT_FOUND

    def test_view_desconhecida_da_404(self, app_state: AppState) -> None:
        status, _ = handle_get(app_state, "/api/state/bad-state/nada", "demo")
        assert status == HTTPStatus.NOT_FOUND

    def test_detalhe_de_controle(self, app_state: AppState) -> None:
        status, payload = handle_get(app_state, "/api/state/bad-state/controls/OBS-004", "demo")
        assert status == HTTPStatus.OK
        assert payload["id"] == "OBS-004"
        assert payload["verdict"] == "FAIL"

    def test_detalhe_de_controle_inexistente(self, app_state: AppState) -> None:
        status, _ = handle_get(app_state, "/api/state/bad-state/controls/NAO-001", "demo")
        assert status == HTTPStatus.NOT_FOUND

    def test_endpoint_inexistente(self, app_state: AppState) -> None:
        status, _ = handle_get(app_state, "/api/nada", "demo")
        assert status == HTTPStatus.NOT_FOUND


class TestRoteamentoPost:
    def test_login_com_credencial_valida_devolve_sessao(self, app_state: AppState) -> None:
        status, payload, session = handle_post(
            app_state, "/api/login", {"user": "demo", "password": "senha"}, None
        )
        assert status == HTTPStatus.OK
        assert payload["authenticated"] is True
        assert read_session(app_state.secret, session) == "demo"

    def test_login_com_credencial_invalida(self, app_state: AppState) -> None:
        status, _, session = handle_post(
            app_state, "/api/login", {"user": "demo", "password": "errada"}, None
        )
        assert status == HTTPStatus.UNAUTHORIZED
        assert session is None

    def test_logout_limpa_o_cookie(self, app_state: AppState) -> None:
        status, _, session = handle_post(app_state, "/api/logout", {}, "demo")
        assert status == HTTPStatus.OK
        assert session == ""

    def test_evaluate_exige_sessao(self, app_state: AppState) -> None:
        status, _, _ = handle_post(app_state, "/api/evaluate", {}, None)
        assert status == HTTPStatus.UNAUTHORIZED

    def test_post_desconhecido(self, app_state: AppState) -> None:
        status, _, _ = handle_post(app_state, "/api/nada", {}, "demo")
        assert status == HTTPStatus.NOT_FOUND


class TestPayloads:
    def test_scorecard_nomeia_o_controle_de_teto(self, app_state: AppState) -> None:
        d = scorecard_payload(app_state.get("bad-state"))
        capped = [p for p in d["practices"] if p["ceiling_control"]]
        assert capped, "bad-state deveria ter prática travada"
        assert all(p["level"] == 1 for p in capped)

    def test_scorecard_separa_skip_de_pass(self, app_state: AppState) -> None:
        d = scorecard_payload(app_state.get("bad-state"))
        assert "SKIP" in d["counts"]
        assert "PASS" in d["counts"]
        assert d["counts"]["SKIP"] > 0

    def test_controls_payload_tem_titulo_do_catalogo(self, app_state: AppState) -> None:
        rows = controls_payload(app_state.get("good-state"))
        assert len(rows) == 30
        assert all(r["title"] for r in rows)

    def test_matriz_marca_celula_vazia_como_none(self, app_state: AppState) -> None:
        d = matrix_payload(app_state.get("bad-state"))
        cells = [d["cells"][p][o] for p in d["practices"] for o in d["objectives"]]
        assert any(c is None for c in cells), "deveria haver cruzamento sem controle"
        assert any(c is not None for c in cells)

    def test_matriz_usa_o_pior_verdict_da_celula(self, app_state: AppState) -> None:
        d = matrix_payload(app_state.get("bad-state"))
        preenchidas = [
            d["cells"][p][o]
            for p in d["practices"]
            for o in d["objectives"]
            if d["cells"][p][o] is not None
        ]
        assert any(c["worst"] == "FAIL" for c in preenchidas)

    def test_compare_mede_a_progressao(self, app_state: AppState) -> None:
        d = compare_payload(app_state)
        assert d["available"] is True
        assert d["after"]["overall_maturity"] > d["before"]["overall_maturity"]
        assert d["fixed_count"] > 0

    def test_inventory_payload_ida_e_volta_pelo_evaluate(self, app_state: AppState) -> None:
        """O que a tela recebe tem que ser aceito de volta pelo /api/evaluate.

        É o contrato do editor de cenário: o inventário sai serializado, o navegador
        muta, e volta. Se os dois formatos divergirem, a tela quebra em produção e não
        no teste.
        """
        payload = inventory_payload(app_state.get("good-state"))
        result = evaluate_scenario(payload)
        assert result["ok"] is True
        assert (
            result["overall_maturity"]
            == scorecard_payload(app_state.get("good-state"))["overall_maturity"]
        )


class TestEditorDeCenario:
    def test_remover_runbook_trava_incident_management(self, app_state: AppState) -> None:
        """A interação canônica da demo, garantida por teste."""
        payload = inventory_payload(app_state.get("good-state"))
        antes = evaluate_scenario(payload)
        nivel_antes = next(
            p["level"] for p in antes["practices"] if p["practice"] == "incident-management"
        )
        assert nivel_antes >= 3

        for alerta in payload["alerts"]:
            if alerta["severity"] in {"page", "critical"}:
                alerta["runbook_ref"] = ""

        depois = evaluate_scenario(payload)
        pratica = next(p for p in depois["practices"] if p["practice"] == "incident-management")
        assert pratica["level"] == 1
        assert pratica["ceiling_control"] == "INC-001"

    def test_inventario_invalido_devolve_erro_em_vez_de_estourar(self) -> None:
        result = evaluate_scenario({"services": [{"sem": "campos"}]})
        assert result["ok"] is False
        assert "inválido" in result["error"]

    def test_inventario_vazio_e_valido(self) -> None:
        result = evaluate_scenario({})
        assert result["ok"] is True


class TestStaticEExport:
    def test_static_resolve_o_bundle(self) -> None:
        for path in ("", "/", "/index.html", "/app.js", "/styles.css"):
            resolved = static_file(path)
            assert resolved is not None, path
            assert resolved[0].is_file()

    def test_static_nao_monta_caminho_a_partir_da_url(self) -> None:
        """Não há travessia a barrar porque não há caminho a montar."""
        for path in ("/../pyproject.toml", "/web/../../etc/passwd", "/qualquer.txt"):
            assert static_file(path) is None

    def test_export_nos_tres_formatos(self, app_state: AppState) -> None:
        for fmt in ("md", "json", "sarif"):
            resolved = export_route(app_state, f"/export/good-state/{fmt}")
            assert resolved is not None, fmt
            content, _, filename = resolved
            assert content
            assert filename.endswith(fmt)

    def test_export_com_formato_ou_estado_invalido(self, app_state: AppState) -> None:
        assert export_route(app_state, "/export/good-state/pdf") is None
        assert export_route(app_state, "/export/nao-existe/md") is None
        assert export_route(app_state, "/outra-coisa") is None


class TestBuildState:
    def test_carrega_os_dois_fixtures(self, app_state: AppState) -> None:
        assert sorted(app_state.evaluations) == ["bad-state", "good-state"]

    def test_diretorio_sem_fixture_estoura(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="nenhum fixture"):
            build_state(tmp_path)

    def test_credenciais_vem_do_ambiente(self) -> None:
        creds = Credentials.from_env({"OBSGOV_USER": "u", "OBSGOV_PASSWORD": "p"})
        assert creds.user == "u"
        assert creds.password == "p"

    def test_credenciais_tem_default(self) -> None:
        creds = Credentials.from_env({})
        assert creds.user
        assert creds.password
