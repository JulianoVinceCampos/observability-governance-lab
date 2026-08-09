.DEFAULT_GOAL := help
PY ?= python3

.PHONY: help install check lint fmt test cov sanitize docs report serve clean

help: ## Mostra esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Instala o pacote com extras de dev e os hooks de pre-commit
	$(PY) -m pip install -e ".[dev]"
	pre-commit install --install-hooks

check: sanitize lint test ## Tudo que o CI roda, na mesma ordem que ele roda

sanitize: ## Bloqueia contexto corporativo (roda primeiro no CI por um motivo)
	$(PY) tools/sanitize_scan.py

lint: ## ruff check e verificação de formatação
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt: ## Aplica formatação e correções seguras
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

test: ## Suíte de testes
	$(PY) -m pytest

cov: ## Testes com cobertura e a checagem do ratchet
	$(PY) -m pytest --cov --cov-report=xml --cov-report=term-missing
	$(PY) tools/coverage_ratchet.py

docs: ## Regenera docs/controls.md a partir do catálogo
	PYTHONPATH=src $(PY) tools/gen_controls_doc.py

report: ## Avalia os dois fixtures e escreve out/{bad,good}-state/report.{md,json,sarif}
	$(PY) -m obsgov.cli report data/bad-state --out out/bad-state
	$(PY) -m obsgov.cli report data/good-state --out out/good-state
	@echo "escrito out/bad-state/ e out/good-state/"

serve: ## Sobe o dashboard em http://127.0.0.1:8000
	$(PY) -m obsgov.cli serve data

clean: ## Remove artefatos de build e de teste
	rm -rf out dist build .pytest_cache .ruff_cache htmlcov coverage.xml .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
