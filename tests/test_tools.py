"""Testes das ferramentas de gate.

Os gates barram todo commit. Gate não testado é teatro: se o ratchet aceitar qualquer
número ou o sanitize deixar passar um identificador real, ninguém descobre até o dano
estar feito. Então eles são testados como código de produção.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import coverage_ratchet
import sanitize_scan


def write_report(path: Path, rate: float) -> Path:
    report = path / "coverage.xml"
    report.write_text(
        f'<?xml version="1.0"?><coverage line-rate="{rate}"></coverage>', encoding="utf-8"
    )
    return report


class TestCoverageRatchet:
    def test_le_a_cobertura_do_xml(self, tmp_path: Path) -> None:
        report = write_report(tmp_path, 0.9712)
        assert coverage_ratchet.read_coverage(report) == pytest.approx(97.12)

    def test_xml_sem_line_rate_estoura(self, tmp_path: Path) -> None:
        report = tmp_path / "coverage.xml"
        report.write_text('<?xml version="1.0"?><coverage></coverage>', encoding="utf-8")
        with pytest.raises(ValueError, match="line-rate"):
            coverage_ratchet.read_coverage(report)

    def test_relatorio_ausente_devolve_2(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["ratchet", "--report", str(tmp_path / "nao-existe.xml")])
        assert coverage_ratchet.main() == 2

    def test_regressao_abaixo_do_piso_reprova(self, tmp_path: Path, monkeypatch) -> None:
        floor = tmp_path / ".coverage-floor"
        floor.write_text("97.00\n", encoding="utf-8")
        monkeypatch.setattr(coverage_ratchet, "FLOOR_FILE", floor)
        report = write_report(tmp_path, 0.80)
        monkeypatch.setattr("sys.argv", ["ratchet", "--report", str(report)])
        assert coverage_ratchet.main() == 1

    def test_dentro_da_tolerancia_passa(self, tmp_path: Path, monkeypatch) -> None:
        """Oscilação de fração entre execuções não pode reprovar o build."""
        floor = tmp_path / ".coverage-floor"
        floor.write_text("97.00\n", encoding="utf-8")
        monkeypatch.setattr(coverage_ratchet, "FLOOR_FILE", floor)
        report = write_report(tmp_path, 0.9680)  # 96.80, dentro da tolerância de 0.5
        monkeypatch.setattr("sys.argv", ["ratchet", "--report", str(report)])
        assert coverage_ratchet.main() == 0

    def test_update_eleva_o_piso(self, tmp_path: Path, monkeypatch) -> None:
        floor = tmp_path / ".coverage-floor"
        floor.write_text("90.00\n", encoding="utf-8")
        monkeypatch.setattr(coverage_ratchet, "FLOOR_FILE", floor)
        report = write_report(tmp_path, 0.9750)
        monkeypatch.setattr("sys.argv", ["ratchet", "--report", str(report), "--update"])
        assert coverage_ratchet.main() == 0
        assert float(floor.read_text().strip()) == pytest.approx(97.50)

    def test_sem_update_nao_toca_o_piso(self, tmp_path: Path, monkeypatch) -> None:
        floor = tmp_path / ".coverage-floor"
        floor.write_text("90.00\n", encoding="utf-8")
        monkeypatch.setattr(coverage_ratchet, "FLOOR_FILE", floor)
        report = write_report(tmp_path, 0.9750)
        monkeypatch.setattr("sys.argv", ["ratchet", "--report", str(report)])
        assert coverage_ratchet.main() == 0
        assert float(floor.read_text().strip()) == pytest.approx(90.00)

    def test_piso_ausente_vale_zero(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(coverage_ratchet, "FLOOR_FILE", tmp_path / "nao-existe")
        assert coverage_ratchet.read_floor() == 0.0


class TestSanitizeScan:
    """O gate que protege o irreversível. Cada regra tem um caso que ela precisa pegar."""

    @pytest.mark.parametrize(
        ("conteudo", "regra"),
        [
            ("host = 'i-0abc123def456789a'", "aws-instance-id"),
            ("account = '123456789012'", "aws-account-id"),
            ("url = 'https://app.crdc.com.br/x'", "corp-domain"),
            ("doc = '12.345.678/9012-34'", "brazilian-tax-id"),
            ("ip = '10.0.0.150'", "private-ip"),
            ("host = 'wildfly-3'", "internal-hostname"),
        ],
    )
    def test_pega_cada_classe_de_vazamento(self, tmp_path: Path, conteudo: str, regra: str) -> None:
        alvo = tmp_path / "vazamento.py"
        alvo.write_text(conteudo, encoding="utf-8")
        findings = sanitize_scan.scan([alvo])
        assert findings, f"a regra {regra} deveria ter pego: {conteudo}"
        assert any(
            f[2] == regra for f in findings
        ), f"esperava {regra}, veio {[f[2] for f in findings]}"

    @pytest.mark.parametrize(
        "conteudo",
        [
            "account = '000000000000'",
            "host = 'i-0EXAMPLE'",
            "ip = '203.0.113.42'",
            "ip = '198.51.100.7'",
            "ip = '192.0.2.1'",
            "url = 'https://example.com/x'",
            "local = '127.0.0.1'",
        ],
    )
    def test_placeholder_documentado_nao_dispara(self, tmp_path: Path, conteudo: str) -> None:
        alvo = tmp_path / "ok.py"
        alvo.write_text(conteudo, encoding="utf-8")
        assert sanitize_scan.scan([alvo]) == []

    def test_marcador_sanitize_ok_libera_a_linha(self, tmp_path: Path) -> None:
        alvo = tmp_path / "waiver.py"
        alvo.write_text("account = '123456789012'  # sanitize-ok exemplo de doc", encoding="utf-8")
        assert sanitize_scan.scan([alvo]) == []

    def test_o_repo_passa_no_proprio_gate_sem_waiver(self) -> None:
        """Se este teste falha, há vazamento no repo agora."""
        assert sanitize_scan.scan([sanitize_scan.ROOT]) == []

    def test_caminho_inexistente_devolve_2(self) -> None:
        assert sanitize_scan.main(["sanitize", "/nao/existe/mesmo"]) == 2

    def test_repo_limpo_devolve_0(self) -> None:
        assert sanitize_scan.main(["sanitize"]) == 0
