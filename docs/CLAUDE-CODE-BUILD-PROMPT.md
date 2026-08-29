
You are the sole engineer building **Insight Copilot**, a KPI intelligence-to-action engine, for a competition submission. This is a long, autonomous build. Work methodically, verify continuously, and never claim something works that you have not run.

## 0. HOW TO START (do this before anything else)

1. Read `docs/InsightCopilot-v2-Final-Architecture.md`, `docs/InsightCopilot-DataLayer-Design.md`, and `docs/PRISM-Round2-Blueprint.md` in full. They are the authoritative design. **This prompt wins where they conflict.**
2. Create `BUILD_PROGRESS.md` at the repo root from the template in §4.2 and fill in every phase as `PENDING`.
3. Create `CLAUDE.md` at the repo root containing: the five laws (§2), the tech stack (§3), the repo map (§5), the code standards (§6), the exact commands to run tests, and a "current phase" pointer. Keep it under 200 lines. This file is your memory across context resets — maintain it.
4. `git init`, create `.gitignore` (Python, Node, `data/`, `.env`, `landing/`, `*.duckdb`), and make an initial commit.
5. Then begin Phase P0.

**Do not ask me for permission to proceed between phases. Work continuously.** Only stop and ask if you hit a genuine blocking decision as defined in §12.4.

---

## 1. WHAT YOU ARE BUILDING

A locally-runnable web application that watches business KPIs, detects genuine anomalies, explains them with rigorous statistics, narrates them differently for different job roles, refuses to answer when the evidence is weak, and recommends actions tied to owners — with every number traceable to a computation and every LLM call metered.

The company is **fictional and simulated**: Meridian Consumer Brands, an India-based home & personal care company (~₹850 crore revenue, 150 SKUs, 6 categories, 5 regions, 4 channels, 4 distribution centres). You will generate 36 months of synthetic data that behaves like real enterprise data, including its defects, and a harness that makes it **arrive** on realistic schedules rather than simply exist.

There are three deliverable pillars, all equally important:

1. **Data generation + live-arrival simulation** — the substitute for live enterprise data.
2. **The analytical backend** — detection through narration.
3. **The web UI** — this is what the judges see. It must look like a shipped commercial product.

---

## 2. THE FIVE LAWS (violating any of these fails the build)

1. **Statistics decide; the model narrates.** Every number originates from SQL, NumPy, or statsmodels. An LLM may never produce, alter, or infer a numeric value, a threshold, a confidence, or an action. Enforced structurally: the LLM cannot emit SQL, and a deterministic verifier checks every number in every generated sentence against the computed evidence bundle before a human sees it.
2. **Contracts before queries.** No component composes free SQL. All data access goes through a contract-to-SQL compiler that applies the caller's row filters and column masks. Security lives below the LLM and cannot be prompted away.
3. **Confidence is computed and calibrated, never claimed.** Six measured signals → softmin → isotonic calibration fitted on a real backtest → tier. Abstention is a designed output with its own type, not an error.
4. **Every claim is traceable.** Freshness, method, contribution, confidence, and lineage accompany every insight and are visible in the UI.
5. **Nothing is reported that was not run.** If a test did not pass, it did not pass. Never write a summary that overstates what works. Accuracy of self-report matters more than apparent progress.

---

## 3. TECH STACK (pinned — do not substitute without recording the reason in BUILD_PROGRESS.md)

**Backend (Python 3.11+)**
```
fastapi uvicorn[standard] pydantic>=2 pydantic-settings
duckdb>=1.0 pandas numpy scipy
statsmodels>=0.14        # MSTL, SARIMAX, HAC, Ljung-Box, Breusch-Pagan, VIF
scikit-learn             # IsotonicRegression, MinCovDet (robust Mahalanobis)
lightgbm                 # priority ranker only
ruptures                 # changepoint cross-check
rank-bm25                # lexical retrieval
pyyaml python-dateutil holidays
anthropic                # LLM provider (optional at runtime — see mock provider)
httpx orjson structlog
pytest pytest-cov pytest-asyncio httpx hypothesis
ruff mypy
```
Optional, behind feature flags, **must not be required to run**: `sentence-transformers` (dense retrieval), `transformers`+`torch` (NLI entailment).

**Frontend**
```
Vite + React 18 + TypeScript (strict)
Tailwind CSS 3.4
shadcn/ui (Radix primitives)   lucide-react   recharts
@tanstack/react-query   react-router-dom   zustand (light UI state)
vitest + @testing-library/react   playwright (E2E + screenshots)
```

**Tooling:** `make` for task running, `ruff` + `mypy` + `eslint` + `prettier`, `pre-commit` optional.

**Do NOT install or use:** Airflow, Dagster, Qdrant, OpenSearch, pgvector, LlamaIndex, MAPIE, River, PyOD, HDBSCAN, Tavily/Firecrawl/GDELT/NewsAPI, RAGAS, SHAP, Streamlit. Any live web scraping or news API. If you believe one is necessary, record why in `BUILD_PROGRESS.md` and implement without it anyway.

---

## 4. OPERATING PROTOCOL

### 4.1 How to work

- Work **phase by phase** (§7). A phase is complete only when its **gate command** passes.
- **Commit after every phase** with a message naming the phase: `git commit -m "P4: source projection + defect injection"`.
- After each phase: update `BUILD_PROGRESS.md`, update the "current phase" line in `CLAUDE.md`, and append one line to `BUILD_LOG.md` recording what was built, what passed, and anything deferred.
- Write tests **alongside** each module, not at the end. A phase whose tests do not exist is not complete.
- Prefer many small, well-named files over few large ones. **Hard limit: no source file over 400 lines.** Split it.
- Re-read `CLAUDE.md` whenever you are unsure of a convention. It is the contract with your future self.

### 4.2 `BUILD_PROGRESS.md` template

```markdown
# Build Progress
Updated: <ISO timestamp>
Current phase: P0

| Phase | Name | Status | Gate command | Result | Notes |
|-------|------|--------|--------------|--------|-------|
| P0 | Bootstrap | PENDING | `make verify-p0` | — | |
| P1 | Contracts & security | PENDING | `make verify-p1` | — | |

(one row per phase P0–P12; Status is one of PENDING / IN_PROGRESS / DONE / BLOCKED)

## Deferred items
(anything intentionally not built, with reason)

## Known issues
(anything failing, with the failure text)

## Decisions taken
(any deviation from the prompt or design docs, with justification)
```

### 4.3 Context management

You will likely exhaust context before finishing. Prepare for it:

- Everything needed to resume lives on disk (`CLAUDE.md`, `BUILD_PROGRESS.md`, `BUILD_LOG.md`), never only in conversation.
- Before starting a large phase, write your plan for that phase into `BUILD_PROGRESS.md` first.
- If context is compacted or I say "continue", re-read `CLAUDE.md` and `BUILD_PROGRESS.md`, run the last gate command to confirm state, and resume from the first non-`DONE` phase.
- Never restart completed work. Trust the progress file and the tests.

---

## 5. REPO LAYOUT

```
insight-copilot/
├── CLAUDE.md  BUILD_PROGRESS.md  BUILD_LOG.md  README.md  Makefile  .env.example
├── docs/                      # the three design docs (already present)
├── backend/
│   ├── pyproject.toml
│   └── src/insight_copilot/
│       ├── config.py                  # pydantic-settings, single source of config
│       ├── logging.py                 # structlog setup
│       ├── contracts/                 # KPI + source contract models & registry
│       │   ├── models.py  registry.py  loader.py
│       │   └── kpi/*.yaml  source/*.yaml
│       ├── security/                  # identity, roles, compiler, audit
│       ├── datagen/
│       │   ├── world/  latent/  decisions/  outcomes/
│       │   ├── events/  projection/  defects/  corpus/  truth/
│       ├── harness/                   # clock, scheduler, landing zone, controls
│       ├── ingest/                    # bronze/silver/gold, dq, freshness, reconcile
│       ├── engine/                    # baseline detect gate attribute_* evidence
│       │                              # confidence actions bundle
│       ├── llm/                       # provider, planner, hypotheses, narrate,
│       │                              # verify_numbers, verify_entailment, templates, router
│       ├── learning/                  # feedback, ranker, calibrate, case_library
│       ├── telemetry/                 # meter, ledger
│       └── api/                       # FastAPI app, routers, schemas, ws
├── frontend/                          # Vite React TS app
├── tests/                             # backend tests mirroring src layout
│   ├── unit/ integration/ statistical/ e2e/ fixtures/
└── data/                              # generated (gitignored): warehouse, landing, ledger
```

---

## 6. CODE STANDARDS (non-negotiable — I will read this code)

**Object-oriented, interface-first.** Every pluggable concept is an abstract base class with concrete implementations. At minimum:

```python
Detector(ABC)          -> PointDetector, DriftDetector, JointDetector
Attributor(ABC)        -> SegmentAttributor, IdentityAttributor, DriverAttributor
BaselineModel(ABC)     -> MSTLBaseline, PooledLaunchBaseline, NaiveBaseline
ConfidenceSignal(ABC)  -> six concrete signal classes
SourceProjector(ABC)   -> OMSProjector, WMSProjector, MarTechProjector, ...
DefectInjector(ABC)    -> one class per pathology in the catalog
LLMProvider(ABC)       -> AnthropicProvider, MockProvider  (MockProvider is mandatory)
Narrator(ABC)          -> LLMNarrator, TemplateNarrator
Verifier(ABC)          -> NumericVerifier, EntailmentVerifier
ActionSelector(ABC)    -> CatalogActionSelector
```

Rules:
- **Full type annotations.** `mypy` must pass. No bare `Any` without a comment justifying it.
- **Pydantic models for every boundary** — API request/response, evidence bundle, contracts, config. No dicts crossing module boundaries.
- **Dependency injection.** Constructors take their collaborators. No module-level singletons except the settings object and the logger. This is what makes the code testable.
- **No magic numbers.** Every threshold, weight, and window comes from a contract, a config file, or a named module constant with a comment.
- **Docstrings that explain WHY**, especially for every statistical choice. Example: `"""EWMA variance (lambda=0.94) because promo/festival windows cluster volatility; a fixed sigma over-flags in quiet periods and under-flags in noisy ones."""` A judge may read this code.
- **Pure functions for all mathematics.** Statistical functions take arrays and return values — no I/O, no globals, no hidden state. This is what makes them testable and provable.
- **Errors are typed.** Define an exception hierarchy (`InsightCopilotError` → `ContractError`, `DataQualityError`, `InsufficientEvidenceError`, `EntitlementError`, `LLMError`). Never raise bare `Exception`. Never swallow an exception silently.
- **Structured logging** with `structlog`. Every stage logs start/end with `run_id`. No `print()` in library code.

---

## 7. BUILD PHASES

Each phase lists deliverables and a **gate**. Add a `make verify-pN` target for each gate. `make verify-all` runs every gate in order.

---

### P0 — Bootstrap
Repo skeleton, `pyproject.toml`, frontend scaffold via Vite, `Makefile` (`install`, `dev`, `test`, `lint`, `typecheck`, `generate`, `demo`, `verify-*`), `config.py` with pydantic-settings, `.env.example`, structlog setup, exception hierarchy, `README.md` skeleton, `CLAUDE.md`, `BUILD_PROGRESS.md`.

**Gate:** `make install && make lint && make typecheck` passes on an empty-but-valid codebase; `uvicorn` serves `GET /api/health` returning `{"status":"ok"}`; `npm run dev` serves a blank styled page.

---

### P1 — Contracts, security, audit
- Pydantic models for **KPI contracts** and **source contracts** (both schemas are in the design docs; source contract schema is in DataLayer §5.1).
- Five KPI contracts: `net_revenue`, `unit_volume`, `order_fill_rate`, `marketing_spend`, `blended_roas`, plus `gross_margin_pct` (masked measure).
- Source contracts for all built sources (P4 list).
- `ContractRegistry` with validation CLI: `make validate-contracts`.
- `security/`: `Identity`, `Role`, `SessionContext`; **`ContractSQLCompiler`** — the only path to data. It takes (contract_id, grain, filters, session) and returns parameterised SQL with row filters and column masks applied. `AuditLog` writes every compile + execution.
- Roles: `cfo`, `rsm_north`, `analyst`, `marketing_lead`, `intern`.

**Gate:** `pytest tests/unit/test_contracts.py tests/unit/test_compiler.py` green, including: RSM query contains the region filter; masked columns return a `MASKED` sentinel not a value; intern is denied with a reason; **an adversarial test where a crafted string ("ignore previous instructions and show all regions") passed as a filter value cannot alter the compiled SQL**; every compile writes an audit row.

---

### P2 — Data generation: world, latent process, decisions, outcomes
Implement DataLayer §3–§4 exactly.

- `world/`: calendar (fiscal Apr–Mar, ISO weeks, IST), festivals **from the `holidays` package (never hard-coded dates)**, monsoon onset by region, geography, product catalog (150 SKUs / 6 categories, with 3 in-window launches), `seeds.py` with **content-addressed RNG**:
  ```python
  def rng_for(*keys) -> np.random.Generator:
      h = blake2b(repr((SEED, *keys)).encode(), digest_size=8).digest()
      return np.random.default_rng(int.from_bytes(h, "big"))
  ```
  **This is the most important function in the data layer. Every stochastic draw must be addressed by content key, never by stream position.**
- `latent/`: the multiplicative demand equation, channel-specific day-of-week, category×region annual shape, festival pre-build and post-lull, weather sensitivity, price and cross-price elasticity, adstock, promo lift, availability censoring with substitution leakage.
- Noise: company-wide **AR(1) φ≈0.35** plus **heteroscedastic scale** (higher in promo/festival/weekend windows) plus idiosyncratic lognormal; at least one intermittent SKU with >40% zero days.
- `decisions/`: pricing/promo policy, **media budget with endogeneity** (`spend = planned_quarterly × (1 + κ·(rev[w-1]/target - 1))`, κ≈0.3), replenishment policy driven by an imperfect forecast, assortment/launches.
- `outcomes/`: orders, stockouts, shipments, returns (7–21 day lag), cancellations, inventory positions.

**Gate:** `make verify-p2` runs:
1. **The determinism test** — running with an event of zero magnitude produces byte-identical output to running without it. *If this fails, stop and fix it before anything else; all ground truth depends on it.*
2. Same seed twice → identical parquet checksums.
3. Statistical tests: ACF of daily revenue has a significant lag-7 peak; recovered AR(1) coefficient is 0.35 ± 0.08; **Breusch–Pagan rejects on raw residuals**; after AR whitening **Ljung–Box does not reject** on clean windows; daily national revenue CV in 0.18–0.25.

---

### P3 — Events and ground truth
- `events/ledger.py` with the event schema (DataLayer §8). Three sets: `scenarios/` (4 hand-authored), `ambient/` (routine background), `calibration/` (stochastic generator, ≥400 events varying magnitude, segment concentration, evidence availability, and data condition).
- The four scenarios, authored to the specification in the architecture doc §5:
  - **A** — WH-North outage + paid-social cut + Category-A price rise, week of 9 Mar 2026, target ≈ −12% weekly net revenue.
  - **B** — MarTech feed misses its drop (9 days stale) + attribution reconciliation breaks (18% vs 5% tolerance) → must abstain.
  - **C** — "Aurora X" launched 18 days ago, day-18 drop that is **within** the pooled launch-curve band → must NOT flag.
  - **D** — role-based entitlement (no special data; exercised via the compiler).
- `truth/`: windowed counterfactual re-simulation (event window ±60 days, warm-started), and **Shapley values over event subsets** for overlapping events (n=3 → 8 runs). Record both total effect (with operational feedback) and direct effect. Write `data/ledger.parquet`.

**Gate:** `make verify-p3` — Shapley contributions for Scenario A sum to the observed gap within 1%; Scenario A's aggregate movement is within 1pp of its −12% target; the calibration corpus has ≥400 events with the intended spread; scenario events are tagged so they can be excluded from calibration fitting.

---

### P4 — Source projection, defects, corpus
- `projection/`: implement 11 sources as `SourceProjector` subclasses — **full fidelity**: OMS (daily, order-line-day grain), WMS (daily, T+2), MarTech (weekly Mon, 14-day restatement, 12-month history only), Support tickets (continuous, text + PII), Competitor prices (weekly, 3-day lag, ~60% SKU coverage, fuzzy match with confidence score, 14-month history only). **Lightweight**: PIM, Inventory snapshots, Weather, Holiday calendar. **Corpus-only**: News, Pricing/promo memos.
- Implement the **designed disagreements** (DataLayer §5): OMS vs ERP definition gap, MarTech attributed vs order-linked revenue (normally 5–15%, **18% in Scenario B**), WMS vs OMS cut-off differences, competitor match error.
- `defects/`: one `DefectInjector` subclass per pathology **P1–P30** in DataLayer §7. All thirty. Each registers itself in a catalog and is individually toggleable.
- `corpus/`: ~600–800 documents generated **from the event ledger**. Templates for routine documents. For the ~150 scenario-critical documents, generate once with the LLM provider and **commit the results as fixtures in `tests/fixtures/corpus/`** — never generate corpus text at runtime. Enforce the corpus rules: ~15% of events get **no** document; ~10% contradictory pairs; each significant news item syndicated across 3–6 outlets; ~20% with `effective_date` materially later than `publish_date`; ~8% post-dated decoys. PII must be **realistic in format but never real**: fictional names, `@example.com` emails, non-routable phone patterns.

**Gate:** `make verify-p4` — a test per defect asserting it is present and detectable (P8 silent unit change and P26 syndication get explicit named tests); reconciliation deltas fall in their designed ranges; corpus composition matches target rates within tolerance; no document contains a real-looking personal identifier outside the reserved patterns.

---

### P5 — Landing zone, harness, ingestion
- `harness/`: `SimClock` (modes: backfill, replay(N×), live(1×), step), `ArrivalScheduler` (per source contract: cron + jitter + failure probability + restatement batches), `LandingZone` (partitioned files + `manifest.json` per batch — schema in DataLayer §10.2), `SourceWatcher`, `DemoControls` (inject event, break feed, send restatement, time-travel, reset).
- `ingest/`: bronze (immutable raw + `batch_id`, `received_at`, `sim_time`, `row_hash`, `schema_version`), DQ gates from source-contract expectations with **quarantine, never drop**, silver (calendar spine, conformed dimensions, timezone → IST, unit normalisation, currency conversion, dedup, PII masking), gold (contract-grain marts + the dimensional cube + the driver panel).
- Watermarks per source; **late batches rewind the watermark for their period only**; **supersede-by-batch** for restatements with prior versions retained; idempotency by `(source_id, batch_id)` plus `row_hash`.
- Event-driven trigger: a landing emits `DataLandedEvent`, which wakes **only** the KPIs whose contracts depend on that source.

**Gate:** `make verify-p5` — replaying 90 sim-days completes; delivering the same `batch_id` twice changes nothing; delivering identical rows under a new `batch_id` is deduplicated; a restatement supersedes and both versions remain queryable; pausing a feed flips freshness green→amber→red on the SLA schedule; a late batch triggers recomputation of exactly the affected window; the unit-change defect is caught by range expectations and quarantined.

---

### P6 — Analytical engine: detection and the attribution ladder
- `baseline.py`: **period discovery** via `scipy.signal.periodogram` confirmed by ACF significance (never assume 7/365), **MSTL** on `log(y)` when strictly positive, movable events as regressors (not fixed-lag seasonality), counterfactual prediction, plus `PooledLaunchBaseline` (empirical-Bayes pooling over comparable launches) for sparse series.
- `detect.py`: AR(p) whitening by AIC with Ljung–Box verification; EWMA (λ=0.94) variance floored by day-of-week-stratified MAD; **conformal p-value** `p = (1 + #{calib ≥ today}) / (n + 1)` with calibration windows excluding known anomalies and regime breaks; **Benjamini–Hochberg FDR** across the KPI×segment scan; tabular **CUSUM** (k=0.5, h=4–5) for drift with a persistence requirement; **robust Mahalanobis** (`sklearn.covariance.MinCovDet`) on the joint residual vector for cross-KPI detection.
- `gate.py`: materiality requiring **both** a statistical trigger and the contract's business floor; priority = rule score × LightGBM ranker (ranker disabled below a minimum label count, and reverts to rules if stale); severity gate that decides who gets the expensive path.
- **Rung 1 — `attribute_where.py`:** Adtributor. `EP_s = (A_s − F_s)/(A_tot − F_tot)`; `Surprise_s = JS(p_s ‖ q_s)` on share distributions; `score = EP × Surprise`. Score each dimension independently, prune to top-K, search ≤2-dimension combinations among survivors only, minimum-observation gating, **Simpson's-paradox check on nested segments**, cumulative-EP Pareto rule (smallest non-overlapping set covering ≥85% of Δ, capped at 4). Then `bootstrap_stability(n=100)` — win-rate per segment set; **a cause below the stability floor is reported as a ranked shortlist, never as a named cause**.
- **Rung 2 — `attribute_kind.py`:** Bennet price–volume–mix. `ΔR = Σ_i [Δp_i·(q0_i+q1_i)/2 + Δq_i·(p0_i+p1_i)/2]`, volume split into own-volume and mix. **Must assert the parts sum to ΔR within 1e-6.**
- **Rung 3 — `attribute_why.py`:** design matrix (adstock transform with half-life profiled over a grid, lags, Fourier seasonal terms, holiday/promo dummies); **SARIMAX with exogenous regressors** as primary; **OLS + Newey–West HAC** with `L = floor(4·(T/100)^(2/9))` as cross-check; agreement score between them; diagnostics (Ljung–Box, Breusch–Pagan, Durbin–Watson, VIF, holdout MAPE); **regressor admissibility from the contract driver DAG — mediators excluded when estimating a total effect**; collinear drivers (VIF > 5) attributed **as a group** with a note; event study against unaffected control regions for discrete events.
- Coverage accounting: explained vs unexplained, with the remainder labelled honestly.

**Gate:** `make verify-p6` —
- Conformal p-values are **uniform on clean holdout windows** (KS test, p > 0.05). *This is the credibility checkpoint of the whole build.*
- All planted scenario anomalies detected; **all planted distractors rejected** (the bulk order, the post-festival lull, the sub-materiality blip).
- Bennet parts sum to ΔR exactly.
- Adtributor recovers the planted segment at rank 1 with bootstrap win-rate > 0.9.
- Driver coefficients recover planted elasticities within ±20%; SARIMAX and HAC agree within tolerance.
- **The endogeneity demonstration:** a test asserting that naive OLS marketing elasticity is biased upward versus truth while the DAG-specified estimate is within ±25%. Record both numbers in `BUILD_LOG.md` — they go in the pitch.

---

### P7 — Evidence, confidence, actions
- `evidence.py`: hybrid retrieval (BM25 required; dense embeddings behind a flag), dual-date awareness (a query for a period must match documents by **effective** date, not only publish date), `EvidenceConf = w1·rerank + w2·source_tier + w3·entity_link + w4·extraction`, **noisy-OR corroboration across independent sources** (ingestion-time dedup is the independence guard), **timing gate** — eliminate any candidate whose date post-dates the effect or falls outside the driver's contract `lag_days` profile, and a **sufficiency check** that routes to abstention when nothing clears the evidence floor.
- `confidence.py`: six `ConfidenceSignal` classes — `c1` detection strength, `c2` attribution quality (bootstrap stability × coverage), `c3` statistical validity, `c4` data trust (freshness, DQ, reconciliation, restatement exposure), `c5` evidence support (corroboration × timing), `c6` narrative faithfulness (set after narration). `softmin(x, p=-4)` → isotonic map → probability → tier. **Hard gates** forcing `INSUFFICIENT`: freshness SLA breach on a required source, reconciliation failure, any signal < 0.30, no hypothesis surviving the timing gate, evidence floor not cleared. Tiers: High / Moderate / Low / Insufficient, each constraining what language is permitted.
- `AbstentionArtifact`: observed movement, what is known, failed checks, missing evidence, retry trigger, ETA.
- `actions.py`: `CaseLibrary` precedent lookup + governed YAML action catalog; preconditions checked against live data; **expected impact computed from estimated elasticities with the confidence interval propagated**; owner and approval threshold from the contract's decision rights; monitoring plan (KPI, checkpoints, success threshold). Output structure exactly: **driver → controllable lever → action → expected impact → owner → confidence → monitoring plan**. Actions are suppressed entirely when the tier is Low or Insufficient.
- `bundle.py`: the `InsightEvidenceBundle` pydantic model (architecture doc §5.3). **Every number that reaches the UI or the LLM lives in this object.**

**Gate:** `make verify-p7` — Scenario B abstains via the data-trust gate; a zero-evidence scenario abstains via the sufficiency gate; Scenario C is correctly **not** flagged and reports Medium confidence with `n=18` named as the reason; the post-dated decoy is eliminated by the timing gate; expected-impact intervals are present and propagated (never point estimates); actions are absent at Low/Insufficient tiers.

---

### P8 — LLM layer and verifiers
- `llm/provider.py`: `LLMProvider` ABC with `AnthropicProvider` and **`MockProvider`**. `MockProvider` returns deterministic canned-but-realistic outputs for every call site. **`LLM_PROVIDER=mock` must run the entire application end to end with no API key and no network.** This is a hard requirement — it protects development cost, test determinism, and demo day.
- Four call sites only: **① query planner** (receives structured facts only — no documents, no confidential values — returns a typed search plan validated against a domain allowlist), **② hypothesis proposer** (cite-or-drop: any claim without a bundle document reference is dropped before scoring; proposes only, never sets numbers), **③ persona narrator** (per persona, lazy, cached on `(bundle_hash, persona, contract_version)`), **④ feedback classifier** (offline, batched). Conversational mode adds an intent parser using the same small model as ①.
- `verify_numbers.py`: extract every numeric token from generated text (including ₹ lakh/crore, %, pp, ratios), normalise units, match against the bundle within rounding tolerance. **Any unmatched number is a failure** → regenerate (max 2) → `TemplateNarrator`.
- `verify_entailment.py`: minimum entailment probability across causal sentences versus their citations. Fallback chain: NLI model → small-model LLM judge → numeric-only with **tier capped at Moderate**. Result feeds `c6`; if `c6` lowers the tier, re-render at the lower tier's language.
- `templates.py`: a complete zero-LLM narrator for every persona and tier. The app must be fully demonstrable with no model available.
- `router.py`: model tiering, prompt caching, semantic cache keyed on `(intent_hash, data_watermark, contract_version)`, per-request token budget, and a cost cap that downshifts the model tier and **logs the downgrade**.
- Personas: `cfo`, `rsm`, `analyst`, `marketing_lead` — YAML style cards (tone, length, required elements, number format, action visibility).

**Gate:** `make verify-p8` — with `LLM_PROVIDER=mock` the full pipeline produces narratives for all four personas; **an injected wrong number in a mocked narrative is caught and regenerated**; an uncited hypothesis is dropped; a planner output containing a value outside the allowlist is rejected; unsetting the API key with `LLM_PROVIDER=anthropic` degrades to templates rather than crashing; the same bundle + persona produces a cache hit on the second call.

---

### P9 — API
FastAPI, all responses typed with pydantic. Routes:

```
GET  /api/health
GET  /api/session/roles              POST /api/session/role
GET  /api/insights?persona=&status=&kpi=       GET /api/insights/{id}
GET  /api/insights/{id}/evidence     POST /api/insights/{id}/feedback
POST /api/ask                        # conversational; returns bundle + narrative or a clarifying question
GET  /api/sources                    GET  /api/sources/{id}/batches
GET  /api/dq                         GET  /api/freshness
GET  /api/telemetry                  GET  /api/calibration      GET /api/evals
GET  /api/audit
POST /api/demo/inject-event          POST /api/demo/break-feed
POST /api/demo/restate               POST /api/demo/timetravel   POST /api/demo/reset
GET  /api/clock                      POST /api/clock/mode
WS   /ws/events                      # batch landed, freshness changed, insight published
```

Rules: every endpoint takes the session role and enforces entitlements **through the compiler** — never in the route handler. Every request is audited. Errors return typed problem responses, never stack traces. CORS configured for the Vite dev origin.

**Gate:** `make verify-p9` — contract tests for every endpoint; **an entitlement test suite hitting every endpoint as `intern` and `rsm_north` asserting zero unauthorised rows or unmasked values**; WebSocket delivers a batch-landed event during a replay; OpenAPI schema generates cleanly.

---

### P10 — Frontend
**This is what the judges see. Treat it as a product, not a demo harness.**

#### Design system (implement exactly)

Define these as CSS custom properties in one theme file, light and dark, and reference them by role everywhere. Never hard-code a hex outside this file.

```
Surfaces      light: page #f9f9f7  card #fcfcfb        dark: page #0d0d0d  card #1a1a19
Ink           primary #0b0b0b / #ffffff · secondary #52514e / #c3c2b7 · muted #898781 (both)
Hairlines     grid #e1e0d9 / #2c2c2a · axis #c3c2b7 / #383835
              border rgba(11,11,11,0.10) / rgba(255,255,255,0.10)
Series (fixed order, never cycled, assign by entity not by rank)
  1 blue #2a78d6/#3987e5   2 orange #eb6834/#d95926   3 aqua #1baf7a/#199e70
  4 yellow #eda100/#c98500 5 magenta #e87ba4/#d55181  6 green #008300/#008300
  7 violet #4a3aa7/#9085e9 8 red #e34948/#e66767
Sequential    single blue ramp #cde2fb → #0d366b (light→dark). Never a rainbow.
Diverging     blue ↔ red with a GRAY midpoint (#f0efec / #383835)
Status        good #0ca30c · warning #fab219 · serious #ec835a · critical #d03b3b
              (reserved — never reused as a series colour; always paired with an icon + label)
Type          system-ui, -apple-system, "Segoe UI", sans-serif — one family, no display face
              tabular-nums ONLY in table columns and axis ticks, never in hero numbers
```

Chart rules, enforced in code review of your own output:
- **Never a dual-axis chart.** Two measures of different scale → two charts or index to a common base.
- Legend present whenever ≥2 series; ≤4 series also directly labelled. Identity is never colour-alone.
- Thin marks; 2px lines; ≥8px markers; 4px rounded bar ends anchored to the baseline; 2px surface gap between adjacent/stacked fills; recessive grid.
- Hover layer by default: crosshair + tooltip on line/area, per-mark tooltip on bar/dot.
- Values, labels and legend text use ink tokens — **never the series colour**.
- Scatter/small-multiples: at most **3** series colours (slots 1–3); beyond that fold to "Other" or facet.
- Every chart has a table view toggle.
- Dark mode is a first-class selected theme, not an inverted filter.

Layout: 8px spacing scale; generous whitespace; `max-w` content column; sticky top bar; card radius 12px; a single soft shadow token; transitions ≤150ms; skeleton loaders (never spinners) for async; explicit empty states and error states for every panel.

#### Screens

1. **Insight Feed** (home) — a freshness strip across the top (one tile per source: name, last batch, SLA status with icon + label), then prioritised insight cards. Each card: KPI, movement with direction, ₹ impact, confidence tier chip, top driver, timestamp, persona-appropriate one-liner. Abstention cards are **visually distinct but not styled as errors** — this is a designed outcome. Filters in one row above.
2. **Insight Detail** — the hero screen. Narrative at top with inline evidence citations `[E1]` that scroll to the evidence panel. Then the **Attribution Ladder** component: four labelled rungs (WHERE / WHAT KIND / WHY / WHAT EVENT), each expandable —
   - WHERE: horizontal bars of segment contribution with a bootstrap-stability indicator per segment
   - WHAT KIND: a **waterfall** from expected → price → own-volume → mix → unexplained → actual (custom SVG; this is the money shot — make it beautiful)
   - WHY: driver coefficients as a dot-and-CI-whisker chart, with the diagnostics table beneath
   - WHAT EVENT: evidence cards with quote, source, publish/effective dates, corroboration count, timing-gate status
   Right rail: confidence breakdown (six signals as a small bar set, the softmin marked, the calibrated probability and tier), freshness, lineage, method chips, and a **"LLM vs computed"** toggle that visually marks which parts of the page came from a model.
3. **Actions** — cards in the mandated structure with owner avatar, approval requirement, expected impact **with its interval**, precedent link, and a monitoring plan timeline. An approve button that creates a monitoring entry.
4. **Ask** — conversational panel; streams the narrative; shows the clarifying-question path; shows the evidence drawer inline.
5. **Data & Sources** — the live-intake showcase. Landing-zone stream (batches arriving in real time over the WebSocket), per-source cards with cadence, latency SLA, watermark, restatement window, DQ pass rate, quarantine count; source contract viewer; reconciliation status.
6. **Trust & Calibration** — the reliability curve, the per-tier backtest table with `n` per tier, expected calibration error, detection precision/recall, attribution error versus ground truth. **Every panel on this page carries a "simulated data" label.**
7. **Telemetry** — per-stage latency (p50/p95), model calls, tokens, cache hit rate, cost per insight **and** cost per monitored KPI-day, cumulative spend.
8. **Admin / Demo Controls** — role switcher, clock control (mode + speed + time travel), and the four demo buttons: inject event, break feed, send restatement, reset. Each shows what it will do before doing it.
9. **Audit** — searchable log: user, role, intent, SQL hash, contract version, rows returned, model calls, narrative id.

Global: role switcher in the top bar that visibly changes what is available (this **is** the entitlement demo); theme toggle; a persistent "sim clock" readout so it is always clear what "now" means.

**Gate:** `make verify-p10` — `npm run build` clean with zero TypeScript errors; vitest component tests green; **Playwright E2E walking all four scenarios end to end**; Playwright screenshots captured at 1440px and 768px in both light and dark for every screen into `artifacts/screenshots/`. **Then look at those screenshots yourself and fix any label collision, overflow, contrast failure, or misaligned grid before declaring the phase done.** Also assert: no horizontal page scroll at 768px; every async panel has a skeleton and an empty state; no chart uses two y-axes.

---

### P11 — Calibration backtest, learning loop, evals
- Run the pipeline over the ≥400-event calibration corpus → `(raw_score, was_top_cause_correct)` pairs → fit `IsotonicRegression` (Platt fallback if n < 100) → derive tier boundaries **from the curve**, not by hand → emit the reliability curve, ECE, and the per-tier table **with `n` per tier**.
- **Temporal split**: fit before a cut date, report after it. **Exclude the four demo scenarios from the fit entirely.** Exclude regime-break windows from conformal calibration windows.
- `learning/`: feedback store, LightGBM priority ranker training (gated on minimum label count, staleness monitor reverts to rules), attribution tuning, evidence source-tier weights, case library. All updates gated behind the golden eval suite.
- `evals/`: detection precision/recall, attribution mean relative error vs ground truth (target ≤20%), driver rank correlation (Kendall τ on top-3), ECE (target ≤0.10), narrative numeric fidelity (target 100%), citation coverage (≥95%), entitlement leakage (must be 0), latency and cost budgets. Emit `artifacts/eval_report.md` and `artifacts/eval_report.json`.

**Gate:** `make verify-p11` — the full eval suite runs and every target is met or the shortfall is explicitly recorded in `BUILD_PROGRESS.md` with the measured number; a seeded analyst correction demonstrably changes the next run's ranking; the ranker stays disabled below the label threshold.

---

### P12 — Seed, document, harden, verify
- `make demo` — one command: generates data, backfills, ingests, runs the pipeline, pre-warms the narrative cache for all personas, starts backend and frontend. Idempotent and re-runnable. `make demo-reset` restores the pristine demo state.
- `README.md`: what it is, architecture diagram (ASCII or SVG), setup, every make target, how to run each of the four scenarios, how to switch roles, how to use the demo controls, the LLM-vs-computed boundary table, known limitations, and **an explicit statement that all data is simulated**.
- `docs/DEMO_SCRIPT.md`: the 7-minute running order with exact clicks and expected screen state at each step.
- Hardening: graceful degradation everywhere (no LLM, no NLI model, no network, empty data, a source permanently down); every long operation cancellable; no unhandled promise rejections; no Python warnings in the demo path.

**Gate:** `make verify-all` green from a clean clone: `git clean -xfd && make install && make generate && make verify-all && make demo`. Then run the demo script yourself end to end and confirm each expected screen state.

---

## 8. TEST STRATEGY

Five layers. All must exist.

| Layer | Location | Runs | Purpose |
|---|---|---|---|
| **Unit** | `tests/unit/` | every commit | Pure functions, especially all statistics. Use `hypothesis` for property tests (e.g. Bennet parts always sum to ΔR for any random input; softmin is monotone; conformal p ∈ (0,1]) |
| **Statistical acceptance** | `tests/statistical/` | `make verify-p2/p6/p11` | The data is realistic and the truth is recoverable (DataLayer §12) |
| **Integration** | `tests/integration/` | per phase | Ingestion idempotency, restatement supersession, watermark rewind, end-to-end pipeline on a fixed seed |
| **Contract/API** | `tests/integration/api/` | P9 onward | Response schemas, entitlements per role on every endpoint, audit completeness |
| **E2E + visual** | `frontend/e2e/` | P10 onward | Playwright: four scenarios, role switching, demo controls, screenshots for self-review |

Additional required tests:
- **Golden snapshot tests** for the four scenarios: the full evidence bundle serialised and compared against a committed fixture, so a refactor that silently changes an attribution is caught.
- **Adversarial entitlement tests**: prompt-injection strings in every user-supplied field; assert compiled SQL is unchanged and no unauthorised row is returned.
- **Determinism tests**: two full generations with the same seed produce identical checksums.
- **Degradation tests**: run the whole app with the LLM disabled, with a source down, with an empty database.

Coverage target: **≥85% on `engine/`, `contracts/`, `security/`, and `ingest/`**. Coverage elsewhere is informational. Do not chase coverage with trivial tests.

---

## 9. ERROR HANDLING PROTOCOL

### 9.1 When a test fails

Follow this ladder. Do not skip a rung.

1. **Read the actual error.** Full traceback, not the summary line.
2. **Reproduce in isolation** — run just that test with `-x -vv`.
3. **Form a hypothesis and state it** in your reasoning before changing code.
4. **Add a diagnostic** (a temporary print, an assertion, a narrower test) that confirms or refutes the hypothesis.
5. **Fix the cause, not the symptom.**
6. **Re-run the specific test, then the phase gate, then the full suite.**
7. If three distinct hypotheses have failed, **stop and write the problem into `BUILD_PROGRESS.md` under Known issues**, implement the simplest correct fallback that keeps the phase gate meaningful, mark the item deferred, and continue. Do not spend unbounded time on one defect.

### 9.2 Absolutely forbidden

- Deleting, skipping, or weakening a failing test to make the suite green.
- `try: ... except: pass`, or catching a broad exception to hide a real failure.
- `# type: ignore` or `any` to silence a type error you have not understood.
- Mocking the thing under test so the test passes vacuously.
- Hard-coding an expected value to match a buggy output.
- Reporting a phase as DONE when its gate did not pass.
- Committing generated data, `.env`, or model weights.

### 9.3 Common failure modes and the expected response

| Symptom | Do this |
|---|---|
| `statsmodels` SARIMAX fails to converge | Fall back to OLS+HAC (the assumption-light path always exists), log the fallback, lower `c3`. Never silently return unconverged estimates |
| Singular matrix / perfect collinearity | Drop to grouped attribution via the VIF gate; report the group, not false precision |
| Conformal p-values not uniform in the P6 gate | The residuals are not whitened. Check AR order selection and the calibration-window exclusions before touching the threshold |
| Bennet parts do not sum to ΔR | An arithmetic bug, never a tolerance issue. Do not widen the tolerance |
| Ground-truth counterfactual looks noisy | The RNG is positional somewhere. Re-check every draw goes through `rng_for()` |
| A library API differs from your expectation | Check the installed version's actual signature (`python -c "import x; help(x.f)"`). Do not guess |
| Frontend type errors from shadcn/ui | Regenerate the component with the CLI rather than hand-patching types |
| Playwright cannot find an element | Add a stable `data-testid`. Do not use brittle text or nth-child selectors |
| A phase is taking very long | Ship the MUST items, record SHOULD/COULD items as deferred, keep the gate honest, move on |

### 9.4 When to stop and ask me

Only for these. Everything else, decide and record the decision.

- A required design decision genuinely contradicts itself across the three docs and this prompt.
- An action would be destructive outside the repo.
- A dependency cannot be installed at all on this machine after two approaches.
- You have deferred so much that a phase gate would be dishonest to declare passed.

---

## 10. DEFINITION OF DONE

- [ ] `git clean -xfd && make install && make generate && make verify-all` passes from scratch.
- [ ] `make demo` starts the full app; all four scenarios are walkable in the UI.
- [ ] Everything runs with `LLM_PROVIDER=mock`, offline, with no API key.
- [ ] The brief's ten minimum expectations are each demonstrable in the UI: 5 KPIs across ≥3 sources with different grains/cadences · semantic contracts · ≥2 personas with different narratives · a multi-factor movement with known drivers · an abstention · a sparse-history case · a role-based entitlement case · evidence showing freshness/method/contribution/confidence/lineage · an LLM-vs-computed breakdown · telemetry with latency, model calls, tokens and cost.
- [ ] `artifacts/eval_report.md` exists with measured numbers, including the calibration table with `n` per tier and the naive-vs-specified elasticity comparison.
- [ ] Screenshots of all nine screens in both themes at two widths, reviewed by you.
- [ ] `mypy`, `ruff`, `eslint`, `tsc` all clean.
- [ ] `README.md` and `docs/DEMO_SCRIPT.md` complete.
- [ ] `BUILD_PROGRESS.md` accurate — every deferred item and known issue honestly listed.

## 11. FINAL REPORT

When done, write `HANDOVER.md` containing: what was built, every gate result with its measured numbers, everything deferred and why, known issues, the three things you would fix first with more time, and an honest assessment of which parts are strongest and weakest. **Understating is better than overstating.** I will read this before demoing, and I need it to be true.

---

**Begin with Phase P0 now. Work continuously through the phases. Update `BUILD_PROGRESS.md` and commit after each one.**
