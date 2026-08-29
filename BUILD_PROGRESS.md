# Build Progress
Updated: 2026-08-29T01:12:34Z
Current phase: P1

| Phase | Name | Status | Gate command | Result | Notes |
|-------|------|--------|--------------|--------|-------|
| P0 | Bootstrap | DONE | `make verify-p0` | PASS | lint, mypy --strict, tsc, 5 unit tests, vite build all green; `GET /api/health` returns `{"status":"ok",...}`; vite dev serves a styled page with theme tokens compiled |
| P1 | Contracts, security, audit | PENDING | `make verify-p1` | — | |
| P2 | Datagen: world, latent, decisions, outcomes | PENDING | `make verify-p2` | — | |
| P3 | Events and ground truth | PENDING | `make verify-p3` | — | |
| P4 | Source projection, defects, corpus | PENDING | `make verify-p4` | — | |
| P5 | Landing zone, harness, ingestion | PENDING | `make verify-p5` | — | |
| P6 | Engine: detection + attribution ladder | PENDING | `make verify-p6` | — | |
| P7 | Evidence, confidence, actions | PENDING | `make verify-p7` | — | |
| P8 | LLM layer and verifiers | PENDING | `make verify-p8` | — | |
| P9 | API | PENDING | `make verify-p9` | — | |
| P10 | Frontend | PENDING | `make verify-p10` | — | |
| P11 | Calibration backtest, learning, evals | PENDING | `make verify-p11` | — | |
| P12 | Seed, document, harden, verify | PENDING | `make verify-p12` | — | |

## Deferred items

(none yet)

## Known issues

(none)

## Decisions taken

- **P0 — pytest/ruff config moved to repo root** (`pytest.ini`, `ruff.toml`) rather
  than `backend/pyproject.toml`. Pytest resolves its rootdir from the common ancestor
  of its arguments; with tests in `tests/` and the package in `backend/src`, the
  backend-local config was silently not loaded (observed: `asyncio_mode` stayed
  `strict` despite being set to `auto`). One root config for both trees removes the
  ambiguity. mypy config stays in `backend/pyproject.toml` because mypy is invoked
  from that directory.
- **P0 — ruff scoped to `backend/src tests`.** Ruff 0.16 formats Python inside
  markdown fences, and `ruff format .` rewrote the design documents in `docs/`.
  Those are authoritative inputs, not source. `extend-exclude` plus explicit paths.
- **P0 — Vite scaffold pinned down from its defaults.** `npm create vite` produced
  React 19 / Vite 8 / oxlint. The build prompt pins React 18, and specifies
  eslint + prettier, so `package.json` was rewritten to the pinned stack
  (React 18.3, Vite 5.4, TypeScript 5.5, Tailwind 3.4, eslint 8 + typescript-eslint 7).
- **P0 — `artifacts/` is tracked, not gitignored.** The build prompt's `.gitignore`
  list does not mention it, and `artifacts/eval_report.md` plus the screenshots are
  named deliverables in the definition of done. Generated *data* (`data/`,
  `landing/`, `*.duckdb`, `*.parquet`) is ignored as specified.
- **P0 — `pyarrow` and `websockets` added to dependencies.** Not in the prompt's
  pinned list but required by it: parquet output (`data/ledger.parquet`, source
  extracts) needs an Arrow engine, and the `WS /ws/events` endpoint needs a
  websocket implementation. Both are transitive-adjacent to already-pinned
  packages (pandas, uvicorn[standard]) rather than new capability.

## Phase plans

### P1 plan (next)

1. `contracts/models.py` — pydantic models for the KPI contract (per PRISM §4.1–4.3)
   and the source contract (per DataLayer §5.1). Split across files if over 400 lines.
2. `contracts/kpi/*.yaml` — `net_revenue`, `unit_volume`, `order_fill_rate`,
   `marketing_spend`, `blended_roas`, `gross_margin_pct` (masked measure).
3. `contracts/source/*.yaml` — the 11 built sources from DataLayer §2.4.
4. `contracts/registry.py` + `loader.py`; `make validate-contracts` CLI.
5. `security/identity.py` — `Identity`, `Role`, `SessionContext`; roles `cfo`,
   `rsm_north`, `analyst`, `marketing_lead`, `intern`.
6. `security/compiler.py` — `ContractSQLCompiler`, the only path to data.
   Parameterised SQL only; filter *values* never reach the SQL string.
7. `security/audit.py` — `AuditLog`, a row per compile and per execution.
8. Tests: `tests/unit/test_contracts.py`, `tests/unit/test_compiler.py`, including
   the adversarial injection test and the audit-completeness test.
