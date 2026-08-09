.DEFAULT_GOAL := help
PY ?= python3

.PHONY: help install check lint fmt test cov sanitize report clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras and the pre-commit hooks
	$(PY) -m pip install -e ".[dev]"
	pre-commit install --install-hooks

check: sanitize lint test ## Everything CI runs, in the same order CI runs it

sanitize: ## Block corporate context (runs first in CI for a reason)
	$(PY) tools/sanitize_scan.py

lint: ## Ruff check + format verification
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt: ## Apply formatting and safe fixes
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

test: ## Test suite
	$(PY) -m pytest

cov: ## Test suite with coverage
	$(PY) -m pytest --cov --cov-report=xml --cov-report=term-missing

report: ## Avalia os dois fixtures e escreve out/{bad,good}-state/report.{md,json,sarif}
	$(PY) -m obsgov.cli report data/bad-state --out out/bad-state
	$(PY) -m obsgov.cli report data/good-state --out out/good-state
	@echo "escrito out/bad-state/ e out/good-state/"

serve: ## Sobe o dashboard em http://127.0.0.1:8000
	$(PY) -m obsgov.cli serve data

clean: ## Remove build and test artefacts
	rm -rf out dist build .pytest_cache .ruff_cache htmlcov coverage.xml .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
