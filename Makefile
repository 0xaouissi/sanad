# Sanad — cross-platform convenience commands.  Usage: make help
#
# test-e2e / test-browser / demo / seed need the live stack and these env vars:
#   HF_HOME, PLAYWRIGHT_BROWSERS_PATH, TESSERACT_CMD, TESSDATA_PREFIX,
#   PYTHONIOENCODING=utf-8   (see docs/development.md)

ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
else
  VENV_PY := .venv/bin/python
endif
PY := backend/$(VENV_PY)
PASSWORD ?= demo-password-1

.DEFAULT_GOAL := help

.PHONY: help install lint test test-unit test-integration test-e2e test-browser \
        dashboard up down logs demo seed heldout

help:
	@echo "Sanad targets:"
	@echo "  install           backend dev+embeddings+browser+ocr extras"
	@echo "  lint              ruff check app tests"
	@echo "  test              unit + integration"
	@echo "  test-unit         offline unit tests (mocked providers)"
	@echo "  test-integration  real PostgreSQL + pgvector (fake embeddings)"
	@echo "  test-e2e          live Ollama + BGE-M3, ar/fr/en"
	@echo "  test-browser      real Chromium widget + dashboard"
	@echo "  dashboard         npm install + build the committed SPA bundle"
	@echo "  up / down         docker compose up -d / down"
	@echo "  logs              docker compose logs -f"
	@echo "  demo              re-record docs/demo-*.gif (live stack)"
	@echo "  seed              seed demo company (PASSWORD=... to override)"
	@echo "  heldout           run the 30 unseen held-out questions"

install:
	cd backend && $(VENV_PY) -m pip install -e ".[dev,embeddings,browser,ocr]"

lint:
	cd backend && $(VENV_PY) -m ruff check app tests

test: test-unit test-integration

test-unit:
	cd backend && $(VENV_PY) -m pytest -q

test-integration:
	cd backend && $(VENV_PY) -m pytest -m integration -q

test-e2e:
	cd backend && $(VENV_PY) -m pytest -m e2e -q

test-browser:
	cd backend && $(VENV_PY) -m pytest tests/e2e/test_widget_browser.py tests/e2e/test_dashboard_browser.py -m e2e -q

dashboard:
	cd dashboard && npm install && npm run build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

demo:
	cd backend && $(VENV_PY) ../scripts/record_demo.py

seed:
	cd backend && $(VENV_PY) -m app.eval.seed --password "$(PASSWORD)"

heldout:
	$(PY) scripts/run_heldout.py