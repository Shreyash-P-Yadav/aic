# Build Progress
Updated: 2026-08-29T02:05:14Z
Current phase: P3

| Phase | Name | Status | Gate command | Result | Notes |
|-------|------|--------|--------------|--------|-------|
| P0 | Bootstrap | DONE | `make verify-p0` | PASS | lint, mypy --strict, tsc, 5 unit tests, vite build all green; `GET /api/health` returns `{"status":"ok",...}`; vite dev serves a styled page with theme tokens compiled |
| P1 | Contracts, security, audit | DONE | `make verify-p1` | PASS | 6 KPI + 11 source contracts validate; 40 tests green incl. the adversarial-injection and audit-completeness cases |
| P2 | Datagen: world, latent, decisions, outcomes | DONE | `make verify-p2` | PASS | Determinism gate green (zero-magnitude event is byte-identical); 25 tests; annual Rs 853 cr, CV 0.230, AR(1) 0.394, ACF lag-7 0.332, BP 7.8e-10, LB 0.976, fill 0.985; generation 6.4 s |
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
- **P2 — `simulate.py` split into six modules to stay under the 400-line limit.**
  It first came in at 638 lines. Split into `simulate.py` (360), `state.py` (129),
  `precompute.py` (113), `latent/demand.py` (91), `outcomes/fulfilment.py` (82) and
  `outcomes/returns.py` (44); each extracted piece is a pure function taking explicit
  inputs rather than reading `self`. The panel checksum is byte-identical before and
  after, which is the evidence that the refactor changed nothing.
- **P2 — vector draws instead of scalar draws, still content-addressed.** A
  Generator construction per scalar draw would be ~1.15 M constructions per run
  (~17 s, and the calibration corpus in P11 needs hundreds of runs). Instead a
  content key addresses a whole *cell* and the draw is a vector spanning the entire
  horizon, indexed by day offset from a fixed epoch. This is still content-addressed
  — the index is a date, not a consumption order — and the determinism test enforces
  it. Two rules keep it honest and are documented in `seeds.py`: the vector always
  spans the whole history (a windowed run slices, never re-draws), and a key is never
  reused for two quantities.
- **P2 — `demand_scale`, a single fitted calibration constant.** The simulated
  business must land on its stated Rs 850 cr scale. `demand_scale` is fitted once and
  stored in `config.yaml`; it multiplies national demand and nothing else. It is a
  stored constant rather than an auto-fit *because a counterfactual re-run must use
  the same scale as the factual run* — re-fitting per run would let removing an event
  change the scale and contaminate every ground-truth number. The P2 gate asserts the
  resulting revenue stays within 10% of target, so drift cannot go unnoticed.
- **P2 — media elasticities re-scaled to sum to 0.143.** As first written, the six
  per-channel elasticities summed to 0.75. The demand equation applies every
  channel's adstock term simultaneously, so the *sum* is what a blended marketing
  elasticity measures — 0.75 is five times the published short-run range and it made
  daily revenue CV 0.40. Rescaled so the total sits at 0.143, inside the 0.08-0.18
  band and consistent with the `net_revenue` contract's 0.15 +/- 0.10 prior.
- **P2 — a shared national weekly cycle was added.** With only channel-specific
  day-of-week shapes, modern trade (weekday-heavy) and quick-commerce (weekend-heavy)
  very nearly cancelled at national level: weekly amplitude was +/-5% and the ACF had
  no lag-7 peak at all. A business with no weekly structure is not realistic and
  would leave the detector's period discovery with nothing to find. Channel shapes
  are now deviations from a shared national cycle.
- **P2 — media channels were all collinear; fixed in three places.** The
  `test_the_collinear_media_pair_actually_moves_together` test caught that *every*
  media pair correlated at ~0.88, not just the planted one — a shared quarterly drift
  draw, a shared daily pacing vector, and a large shared seasonal multiplier. Each is
  now per-channel, plus an independent per-channel AR(1) budget wobble. The planted
  pair is modelled properly as **one agency team planning both budgets off one plan**
  (they share a plan key inside the window, so they share their quarterly revision
  and seasonal phase), rather than as a correlated shock bolted onto independent
  plans. Result: the pair correlates 0.80 inside its window against a 0.13 median
  elsewhere, which is a pathology the VIF gate can actually isolate.
- **P2 — units are whole numbers via unbiased stochastic rounding.** Orders are
  counts. Plain rounding would erase every slow-moving SKU (0.4 expected units a day
  rounds to zero every day); stochastic rounding preserves the mean exactly and
  produces genuine runs of zero days. This is what makes the intermittent series a
  real Croston case, and it is why transaction amounts follow Benford (measured MAD
  0.0006).
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

### P3 plan (next)

1. `datagen/events/models.py` — the event schema from DataLayer §8 (event_id, type,
   scope, window, magnitude, detectability, evidence spec, ground_truth spec,
   demo_role), and `ledger.py` to load and index it.
2. `datagen/events/scenarios/*.yaml` — the four hand-authored scenarios:
   **A** WH-North outage + paid-social cut + Category-A price rise, week of 9 Mar
   2026, target ~ -12% weekly net revenue; **B** MarTech 9 days stale + 18%
   reconciliation break; **C** Aurora X day-18 dip inside the pooled launch band;
   **D** entitlement (no special data — exercised through the compiler).
3. `datagen/events/ambient.py` — routine background events so the detector has
   realistic non-events to ignore.
4. `datagen/events/calibration_gen.py` — the stochastic generator, >= 400 events
   spread over magnitude, segment concentration, evidence availability and data
   condition. Scenario events tagged so they can be excluded from the calibration fit.
5. `datagen/events/overlay_from_ledger.py` — turn ledger events into `DayEffects`.
6. `datagen/truth/` — `counterfactual.py` (windowed re-simulation, event window
   +/-60 days, warm-started) and `shapley.py` (2^n subsets for overlapping events,
   n=3 -> 8 runs). Record BOTH total effect (with operational feedback) and direct
   effect. Write `data/ledger.parquet`.
7. `tests/statistical/test_p3_truth.py` — the gate: Shapley contributions for
   Scenario A sum to the observed gap within 1%; Scenario A's aggregate movement is
   within 1pp of -12%; >= 400 calibration events with the intended spread; scenario
   events are excludable from calibration fitting.

### P2 plan (done)

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
