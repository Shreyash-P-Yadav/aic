# Insight Copilot — task runner.
# Every phase gate is a `verify-pN` target; `verify-all` runs them in order.

SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
UVICORN := $(VENV)/bin/uvicorn
FRONTEND := frontend
BACKEND := backend

.DEFAULT_GOAL := help
.PHONY: help install install-backend install-frontend clean \
        lint lint-backend lint-frontend format \
        typecheck typecheck-backend typecheck-frontend \
        test test-backend test-frontend \
        dev dev-backend dev-frontend build generate demo demo-reset \
        validate-contracts \
        verify-p0 verify-p1 verify-p2 verify-p3 verify-p4 verify-p5 verify-p6 \
        verify-p7 verify-p8 verify-p9 verify-p10 verify-p11 verify-p12 verify-all

help:  ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- install ----
install: install-backend install-frontend  ## Install backend venv + frontend deps

install-backend:
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip setuptools wheel
	$(PIP) install --quiet -e "$(BACKEND)[dev]"

install-frontend:
	cd $(FRONTEND) && npm install --no-audit --no-fund

clean:  ## Remove build artefacts and generated data (keeps the venv)
	rm -rf data/* artifacts/* $(FRONTEND)/dist .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ------------------------------------------------------------------- lint ----
lint: lint-backend lint-frontend  ## Lint backend and frontend

lint-backend:
	$(RUFF) check $(BACKEND)/src tests
	$(RUFF) format --check $(BACKEND)/src tests

lint-frontend:
	cd $(FRONTEND) && npm run lint && npm run format:check

format:  ## Auto-format both sides
	$(RUFF) format $(BACKEND)/src tests
	$(RUFF) check --fix $(BACKEND)/src tests
	cd $(FRONTEND) && npm run format

# -------------------------------------------------------------- typecheck ----
typecheck: typecheck-backend typecheck-frontend  ## mypy + tsc

typecheck-backend:
	cd $(BACKEND) && ../$(MYPY)

typecheck-frontend:
	cd $(FRONTEND) && npm run typecheck

# ------------------------------------------------------------------- test ----
test: test-backend test-frontend  ## Run all tests

test-backend:
	$(PYTEST)

test-frontend:
	cd $(FRONTEND) && npm run test

# -------------------------------------------------------------------- dev ----
dev-backend:  ## Serve the API with reload
	$(UVICORN) insight_copilot.api.app:app --app-dir $(BACKEND)/src \
	  --host 127.0.0.1 --port 8000 --reload

dev-frontend:  ## Serve the Vite dev server
	cd $(FRONTEND) && npm run dev

dev:  ## Run backend and frontend together
	@$(MAKE) -j2 dev-backend dev-frontend

build:  ## Production frontend build
	cd $(FRONTEND) && npm run build

# ---------------------------------------------------------------- pipeline ----
generate:  ## Generate the simulated world, events, sources and corpus
	$(PY) -m insight_copilot.cli generate

demo:  ## One command: generate, backfill, ingest, run, serve
	$(PY) -m insight_copilot.cli demo

demo-reset:  ## Restore the pristine demo state
	$(PY) -m insight_copilot.cli demo-reset

validate-contracts:  ## Validate every KPI and source contract
	$(PY) -m insight_copilot.cli validate-contracts

# ------------------------------------------------------------------ gates ----
verify-p0:  ## P0 gate: lint, typecheck, health endpoint, frontend build
	$(MAKE) lint
	$(MAKE) typecheck
	$(PYTEST) tests/unit/test_p0_bootstrap.py
	$(MAKE) build

verify-p1:  ## P1 gate: contracts validate; compiler entitlements and audit hold
	$(MAKE) validate-contracts
	$(PYTEST) tests/unit/test_contracts.py tests/unit/test_compiler.py

verify-p2:
	$(PYTEST) tests/statistical/test_p2_world.py

verify-p3:
	$(PYTEST) tests/statistical/test_p3_truth.py

verify-p4:
	$(PYTEST) tests/integration/test_p4_projection.py

verify-p5:
	$(PYTEST) tests/integration/test_p5_ingest.py

verify-p6:
	$(PYTEST) tests/statistical/test_p6_engine.py

verify-p7:
	$(PYTEST) tests/integration/test_p7_confidence.py

verify-p8:
	$(PYTEST) tests/integration/test_p8_llm.py

verify-p9:
	$(PYTEST) tests/integration/api

verify-p10:
	cd $(FRONTEND) && npm run build && npm run test && npm run e2e

verify-p11:
	$(PYTEST) tests/e2e/test_p11_evals.py

verify-p12:
	$(PYTEST) tests/e2e/test_p12_hardening.py

verify-all: verify-p0 verify-p1 verify-p2 verify-p3 verify-p4 verify-p5 verify-p6 \
            verify-p7 verify-p8 verify-p9 verify-p10 verify-p11 verify-p12  ## Every gate, in order
	@echo "All phase gates passed."
