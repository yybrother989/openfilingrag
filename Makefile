.PHONY: install ingest-sample edgar-pull api demo test lint format clean help

TICKER ?= AAPL
TYPES  ?= 10-K
LIMIT  ?= 1

PY ?= python
PIP ?= pip

help:
	@echo "OpenFilingRAG — common commands"
	@echo ""
	@echo "  make install        Install Python deps (editable, with dev extras)"
	@echo "  make ingest-sample  Ingest any filing dropped into data/sample_filings/"
	@echo "  make edgar-pull TICKER=AAPL TYPES=10-K LIMIT=1   Pull + ingest from SEC EDGAR (no key)"
	@echo "  make api            Run FastAPI on :8000 (uvicorn --reload)"
	@echo "  make demo           Run Next.js demo on :3000"
	@echo "  make test           Run pytest in mock mode"
	@echo "  make lint           Run ruff + mypy"
	@echo "  make format         Run black + ruff --fix"
	@echo ""
	@echo "Database is hosted on Supabase. To bootstrap a fresh project run"
	@echo "app/db/migrations/001_init.sql via the Supabase SQL editor or CLI."
	@echo "See README.md → Database for details."

install:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

ingest-sample:
	$(PY) -m scripts.ingest_sample

edgar-pull:
	$(PY) -m scripts.edgar_pull $(TICKER) --types $(TYPES) --limit $(LIMIT)

api:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

demo:
	cd frontend && npm install && npm run dev

test:
	pytest -q

lint:
	ruff check app tests
	mypy app

format:
	black app tests scripts
	ruff check --fix app tests

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
