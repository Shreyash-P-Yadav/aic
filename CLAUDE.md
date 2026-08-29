# Insight Copilot — build memory

A KPI intelligence-to-action engine for a fictional company, **Meridian Consumer
Brands** (India, home & personal care, ~₹850 cr, 150 SKUs, 6 categories, 5 regions,
4 channels, 4 DCs). **All data is simulated.**

Authoritative spec: `docs/CLAUDE-CODE-BUILD-PROMPT.md` (wins on conflict), then
`docs/InsightCopilotv2FinalArchitecture.md`, `docs/InsightCopilotDataLayerDesign.md`,
`docs/PRISMRound2Blueprint.md`.

## Current phase

**P6 — Analytical engine: detection and the attribution ladder.** P0–P5 are DONE.
State of every phase: `BUILD_PROGRESS.md`.
History: `BUILD_LOG.md`. Never mark a phase DONE without pasting its real gate
output into `BUILD_LOG.md`.

## The five laws

1. **Statistics decide; the model narrates.** Every number originates from SQL,
   NumPy, or statsmodels. An LLM may never produce, alter, or infer a numeric value,
   threshold, confidence, or action. The LLM cannot emit SQL, and a deterministic
   verifier checks every number in every generated sentence against the evidence
   bundle before a human sees it.
2. **Contracts before queries.** No component composes free SQL. All data access
   goes through the contract-to-SQL compiler, which applies the caller's row filters
   and column masks. Security lives below the LLM and cannot be prompted away.
3. **Confidence is computed and calibrated, never claimed.** Six measured signals →
   softmin(p=−4) → isotonic calibration fitted on a real backtest → tier. Abstention
   is a designed output with its own type.
4. **Every claim is traceable.** Freshness, method, contribution, confidence and
   lineage accompany every insight and are visible in the UI.
5. **Nothing is reported that was not run.** If a test did not pass, it did not
   pass. Accuracy of self-report matters more than apparent progress.

## Tech stack (pinned — record any substitution in BUILD_PROGRESS.md)

**Backend** Python 3.11 · fastapi · uvicorn · pydantic v2 + pydantic-settings ·
duckdb · pandas · numpy · scipy · statsmodels (MSTL, SARIMAX, HAC, Ljung-Box,
Breusch-Pagan, VIF) · scikit-learn (IsotonicRegression, MinCovDet) · lightgbm
(priority ranker only) · ruptures · rank-bm25 · pyyaml · python-dateutil · holidays ·
anthropic · httpx · orjson · structlog · pytest(+cov, asyncio) · hypothesis · ruff · mypy.
Optional behind flags, never required: sentence-transformers, transformers+torch.

**Frontend** Vite · React 18 · TypeScript strict · Tailwind 3.4 · shadcn/ui (Radix) ·
lucide-react · recharts · @tanstack/react-query · react-router-dom · zustand ·
vitest + @testing-library/react · playwright.

**Never install:** Airflow, Dagster, Qdrant, OpenSearch, pgvector, LlamaIndex, MAPIE,
River, PyOD, HDBSCAN, Tavily/Firecrawl/GDELT/NewsAPI, RAGAS, SHAP, Streamlit, or any
live web scraping / news API.

## Repo map

```
CLAUDE.md BUILD_PROGRESS.md BUILD_LOG.md README.md Makefile ruff.toml pytest.ini .env.example
docs/                     the four design documents
backend/pyproject.toml    backend package + mypy config
backend/src/insight_copilot/
  config.py logging.py errors.py cli.py
  contracts/  models registry loader + kpi/*.yaml source/*.yaml
  security/   Identity Role SessionContext ContractSQLCompiler AuditLog
  datagen/    world/ latent/ decisions/ outcomes/ events/ projection/ defects/ corpus/ truth/
  harness/    clock cron periods scheduler slicer quirks manifest formats
              landing (LandingZone + SourceWatcher) replay controls factory
  ingest/     warehouse registry bronze dq dq_store expectations conform silver
              gold panel freshness reconcile runner policies masking models
  engine/     baseline detect gate attribute_where attribute_kind attribute_why
              evidence confidence actions bundle
  llm/        provider planner hypotheses narrate verify_numbers verify_entailment
              templates router
  learning/   feedback ranker calibrate case_library
  telemetry/  meter ledger
  api/        app.py routers/ schemas.py errors.py ws.py
frontend/                 Vite React TS app
tests/                    unit/ integration/ statistical/ e2e/ fixtures/
data/                     generated, gitignored (warehouse, landing, ledger)
artifacts/                eval_report.md/.json, screenshots/
```

## Code standards (non-negotiable)

- **Object-oriented, interface-first.** ABCs with concrete implementations for:
  `Detector`, `Attributor`, `BaselineModel`, `ConfidenceSignal`, `SourceProjector`,
  `DefectInjector`, `LLMProvider` (`MockProvider` mandatory), `Narrator`, `Verifier`,
  `ActionSelector`.
- **Full type annotations.** `mypy --strict` must pass. No bare `Any` without a
  comment justifying it. Never `# type: ignore` to silence something not understood.
- **Pydantic models at every boundary.** No dicts crossing module boundaries.
- **Dependency injection.** Constructors take their collaborators. The only
  module-level singletons are `get_settings()` and the logger.
- **No magic numbers.** Every threshold, weight and window comes from a contract, a
  config file, or a named module constant with a comment.
- **Docstrings explain WHY**, especially every statistical choice. A judge reads this.
- **Pure functions for all mathematics.** Arrays in, values out. No I/O, no globals.
- **Errors are typed** (`InsightCopilotError` → `ContractError`, `DataQualityError`,
  `InsufficientEvidenceError`, `EntitlementError`, `LLMError`, …). Never raise or
  catch bare `Exception`; never swallow one.
- **structlog only.** Every stage logs start/end with `run_id`. No `print()` in
  library code.
- **Hard limit: no source file over 400 lines.** Split it.
- Write tests alongside each module, not at the end.

## Commands

```
make install          venv + npm install            make lint        ruff + eslint + prettier
make typecheck        mypy --strict + tsc           make test        pytest + vitest
make dev              backend :8000 + frontend :5173
make generate         build the simulated world     make demo        full one-command demo
make backfill         bulk historical load          make replay      DAYS=30 live arrivals
make generate-truth   counterfactual ground truth (~6 min) -> data/ledger.parquet
make validate-contracts
make verify-pN        the gate for phase N          make verify-all  every gate in order
```

Backend tests run from the repo root (`pytest.ini` sets `pythonpath=backend/src`).
`LLM_PROVIDER=mock` is the default and must run everything offline with no API key.

## Working rules

- A phase is complete only when its `make verify-pN` gate passes for real.
- Commit after every phase: `git commit -m "P4: source projection + defect injection"`.
- After each phase update `BUILD_PROGRESS.md`, this file's "Current phase", and
  append a line to `BUILD_LOG.md`.
- Never delete, skip, or weaken a failing test to get green. Never hard-code an
  expected value to match a buggy output. Never widen a tolerance that is an
  arithmetic identity.
- If three hypotheses fail on one defect: record it under Known issues in
  `BUILD_PROGRESS.md`, implement the simplest correct fallback that keeps the gate
  meaningful, mark it deferred, and move on.
- Branch: `claude/build-prompt-phase-0-78vgpn`.
