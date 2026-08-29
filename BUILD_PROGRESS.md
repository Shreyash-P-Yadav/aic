# Build Progress
Updated: 2026-08-29T01:27:35Z
Current phase: P2

| Phase | Name | Status | Gate command | Result | Notes |
|-------|------|--------|--------------|--------|-------|
| P0 | Bootstrap | DONE | `make verify-p0` | PASS | lint, mypy --strict, tsc, 5 unit tests, vite build all green; `GET /api/health` returns `{"status":"ok",...}`; vite dev serves a styled page with theme tokens compiled |
| P1 | Contracts, security, audit | DONE | `make verify-p1` | PASS | 6 KPI + 11 source contracts validate; 40 tests green incl. the adversarial-injection and audit-completeness cases |
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

- **`personas/*.yaml` and `catalogs/actions_*.yaml`** (referenced by every KPI
  contract's `actions_ref`). Not built in P1 — they belong to P7 (action catalog)
  and P8 (persona style cards). The reference is an unresolved string at load time,
  so nothing depends on them existing yet.

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
- **P1 — KPI contract models split across three modules.** `models.py` reached 452
  lines, over the 400-line hard limit. Split into `common.py` (shared strict-model
  base, identifier allowlist, SQL-fragment check), `models.py` (structure: grain,
  calculation, lineage, driver DAG) and `governance.py` (materiality, confidence
  policy, access, monitoring, sparse-history policy).
- **P1 — the compiler denies unlisted roles by default.** The design docs enumerate
  each role explicitly in every contract, so a missing entry is ambiguous. Treating
  it as a grant would make adding a role to the system silently grant it access to
  every contract; treating it as a denial makes access a deliberate act. Covered by
  `test_an_unlisted_role_is_denied_by_default`.
- **P1 — masked measures are never computed.** Rather than selecting the value and
  overwriting it, the compiler emits `'MASKED' AS x` in place of the expression, so
  the underlying columns (e.g. `unit_cost`) do not appear in the SQL at all. A
  masked value therefore cannot leak through a query plan, an error message, or an
  intermediate result.
- **P1 — `gross_margin_pct` sources `pim_products`, not an ERP feed.** The design
  doc derives it from OMS ⋈ ERP, but ERP is on the "declare, do not build" list
  (DataLayer §2.4) while the build prompt requires source contracts for built
  sources only. Standard cost comes from the product master instead, which also
  makes the late-PIM-update defect (P13) visible in this KPI as a cost-coverage gap.
- **P1 — an `_ALLOWED_BINDINGS` allowlist on row-filter templates.** A contract row
  filter may only reference `user_region`, `user_warehouse` or `user_channel`. A
  typo like `:user_regionn` now fails at compile time instead of binding nothing
  and returning every row.
- **P0 — `pyarrow` and `websockets` added to dependencies.** Not in the prompt's
  pinned list but required by it: parquet output (`data/ledger.parquet`, source
  extracts) needs an Arrow engine, and the `WS /ws/events` endpoint needs a
  websocket implementation. Both are transitive-adjacent to already-pinned
  packages (pandas, uvicorn[standard]) rather than new capability.

## Phase plans

### P2 plan (next)

Implement DataLayer §3–§4. Order matters: D1's determinism gate blocks everything.

1. `datagen/world/seeds.py` — **`rng_for(*keys)`, content-addressed RNG. This lands
   first and nothing proceeds until the zero-magnitude-event test passes
   byte-identically.** Every stochastic draw in the whole data layer is addressed by
   a stable content key, never by stream position.
2. `datagen/world/` — `config.yaml` (the Meridian world constants), `calendar.py`
   (fiscal Apr–Mar, ISO weeks, IST, festivals **from the `holidays` package**,
   monsoon onset by region ±10 days), `geography.py` (5 regions, 4 DCs with
   cross-serving), `catalog.py` (150 SKUs / 6 categories, 3 in-window launches,
   ~180 lifetime including discontinued).
3. `datagen/latent/` — the multiplicative demand equation (DataLayer §4.1):
   channel-specific day-of-week, category×region annual shape, festival pre-build
   and post-lull, weather sensitivity, own- and cross-price elasticity, adstock,
   promo lift, availability censoring with substitution leakage.
4. `datagen/latent/noise.py` — company-wide AR(1) φ≈0.35, heteroscedastic scale
   (higher in promo/festival/weekend windows), idiosyncratic lognormal, near-Poisson
   counting noise for small SKUs, and at least one SKU with >40% zero days.
5. `datagen/decisions/` — pricing/promo policy, media budget **with endogeneity**
   (`spend = planned_quarterly × (1 + κ·(rev[w−1]/target − 1))`, κ≈0.3),
   replenishment driven by an imperfect forecast, assortment and launches.
6. `datagen/outcomes/` — orders, stockouts, shipments, returns (7–21 day lag),
   cancellations, inventory positions.
7. `tests/statistical/test_p2_world.py` — the gate: determinism first, then same-seed
   checksums, then ACF lag-7, AR(1) recovery 0.35±0.08, Breusch–Pagan rejects raw,
   Ljung–Box does not reject after whitening, daily national revenue CV 0.18–0.25.

### P1 plan (done)

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
