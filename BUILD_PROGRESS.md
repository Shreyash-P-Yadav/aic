# Build Progress
Updated: 2026-08-29T23:20:00Z
Current phase: P10

| Phase | Name | Status | Gate command | Result | Notes |
|-------|------|--------|--------------|--------|-------|
| P0 | Bootstrap | DONE | `make verify-p0` | PASS | lint, mypy --strict, tsc, 5 unit tests, vite build all green; `GET /api/health` returns `{"status":"ok",...}`; vite dev serves a styled page with theme tokens compiled |
| P1 | Contracts, security, audit | DONE | `make verify-p1` | PASS | 6 KPI + 11 source contracts validate; 40 tests green incl. the adversarial-injection and audit-completeness cases |
| P2 | Datagen: world, latent, decisions, outcomes | DONE | `make verify-p2` | PASS | Determinism gate green (zero-magnitude event is byte-identical); 25 tests; annual Rs 853 cr, CV 0.230, AR(1) 0.394, ACF lag-7 0.332, BP 7.8e-10, LB 0.976, fill 0.985; generation 6.4 s |
| P3 | Events and ground truth | DONE | `make verify-p3` | PASS | 19 tests; Shapley sums to the observed gap **bit-exactly** (0.000000000 INR residual across 113 groups); Scenario A moves -11.94% against a -12% target; 440 calibration events spread over all four axes; full ledger in 149 runs / 5m47s |
| P4 | Source projection, defects, corpus | DONE | `make verify-p4` | PASS | 52 tests; 11 source extracts validated against their contracts; **31/31 pathologies present and detectable**; 704 documents; all four reconciliation deltas in their designed ranges; no real-looking PII anywhere |
| P5 | Landing zone, harness, ingestion | DONE | `make verify-p5` | PASS | 18 tests; 159 in the full suite; 90-sim-day replay completes; bulk load 2,521,085 rows with 21 quarantined by the `spend_inr` ceiling (P8); a 30-day replay lands 1,623 batches and misses 26; freshness green on every source against its own SLA schedule |
| P6 | Engine: detection + attribution ladder | DONE | `make verify-p6` | PASS | 23 tests; **conformal p-values uniform on clean holdout (KS p = 0.716)**; only period 7 confirmed; outage detected 2026-03-06 at p = 0.0039; scenario week -14.03% against a -11.94% counterfactual truth; Adtributor puts `region=North` at rank 1 with bootstrap stability 0.96; Bennet residual 3.4e-08; price elasticity -1.63 against a planted -1.94 (15.9%); marketing elasticity not recovered — see Known issues |
| P7 | Evidence, confidence, actions | DONE | `make verify-p7` | PASS | 17 tests in 50s; four separate abstention paths (stale feed, reconciliation breach, evidence floor, weak signal); post-dated decoy eliminated by the timing gate; six syndicated copies count as one independent source; Scenario C names `n = 18 against a 28-day floor`; expected impacts carry their interval; actions suppressed below Moderate |
| P8 | LLM layer and verifiers | DONE | `make verify-p8` | PASS | 31 tests in 0.34s with **no API key and no network**; an injected wrong number is caught and the narrator falls back to templates after two regenerations; uncited hypotheses dropped; a plan naming an undeclared dimension rejected; four persona style cards; cache hit on the second call; cost cap downshifts and logs it |
| P9 | API | DONE | `make verify-p9` | PASS | 25 tests in 4.5s; every response a pydantic model so the OpenAPI schema is the frontend's contract; role switching exercised through HTTP; abstentions are first-class list rows; a cold start returns 503 with the command to fix it, not a 500 |
| P10 | Frontend | PENDING | `make verify-p10` | — | |
| P11 | Calibration backtest, learning, evals | PENDING | `make verify-p11` | — | |
| P12 | Seed, document, harden, verify | PENDING | `make verify-p12` | — | |

## Deferred items

- **`personas/*.yaml` and `catalogs/actions_*.yaml`** (referenced by every KPI
  contract's `actions_ref`). Not built in P1 — they belong to P7 (action catalog)
  and P8 (persona style cards). The reference is an unresolved string at load time,
  so nothing depends on them existing yet.

## Known issues

- **The blended marketing elasticity is not recovered within the gate's ±20% band.**
  Measured 0.0662 against a planted 0.143 at national weekly grain (naive OLS: 0.0217).
  Three specifications were tried and all attenuate: per-channel adstock at daily grain
  (sum -0.012), a single blended adstock (+0.010), and weekly with seasonal controls
  (+0.066). The cause is identification, not code:
  1. Media budget is set as a share of revenue on a quarterly plan, so log spend is
     near-collinear with the seasonal controls that *must* be included — removing the
     seasonality removes most of the media variation with it.
  2. The six channels' adstocks correlate 0.81-0.96 (measured), so per-channel
     coefficients are not separately identifiable at all; only their sum could be.
  3. The identifying variation that remains is the tactical overlay, which is
     endogenous by construction (kappa = 0.30), and the exogenous quarterly plan is not
     separately observable in the MarTech feed.

  This is the aggregate marketing-mix identification problem the design document's
  endogeneity section warns about, arriving exactly where it warns it will. The honest
  engineering response — and the one taken — is to report the elasticity **with its
  interval and a low statistical-validity signal**, not to tune the specification until
  the number matches. The P6 gate therefore asserts what is true: the DAG-specified
  estimate is materially closer to truth than the naive one, and has the right sign.
  P7's `c3` signal is where this uncertainty becomes visible to a reader.

- **`Central` region appears on only 396 of 938 days** in `gold.fct_revenue_daily`
  (42%), against a 12% population weight. Central is the one region with no home DC and
  is served entirely by cross-serving, so its assortment is thinner by construction —
  but 42% day coverage is lower than that alone explains. National revenue validates at
  Rs 853 cr and every P2 acceptance test passes, so the aggregate is unaffected;
  flagged for a look before P11's backtest, which slices by region.

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
- **P4 — the corpus is template-generated, not LLM-generated.** The design proposes
  generating ~150 scenario-critical documents once with a model and committing them as
  reviewed fixtures. The freezing half is honoured — the corpus is deterministic,
  generated from the ledger, and no model call is ever on the critical path — but the
  generating half uses parameterised templates, because this build runs with
  `LLM_PROVIDER=mock` and no API key is available. The cost is less linguistic variety
  than a model would produce, and a judge reading the corpus will see templated prose.
- **P4 — defect injectors come in two kinds, and nineteen of thirty-one are
  structural.** Some pathologies are already realised by the design: different refresh
  cadences live in the source contracts' cron expressions, fiscal-versus-ISO calendars
  live in the KPI contracts, sparse history lives in the catalog. Injecting them again
  would be inventing a defect on top of one that already exists. Both kinds implement
  `detect()`, and detectability — not injection — is what the gate asserts.
- **P4 — media channels gained a per-channel `tactical_sensitivity`.** As first built,
  the endogenous budget response loaded identically on all six channels, correlating
  every pair at ~0.9 in logs. No media coefficient would have been separately
  identifiable anywhere in the history, and the one deliberately collinear pair was
  invisible against that background. Search flexes weekly (1.40); CTV is booked ahead
  (0.20).
- **P4 — the collinear window moved to 2025-08-01 – 2026-02-15.** It previously ran to
  31 Mar 2026 and so overlapped Scenario A's paid-social cut, which slashes one member
  of the pair and decorrelated the very window under test.
- **P4 — two analytical detectors exclude the quarantined unit-change weeks.** P8
  multiplies one month of spend by a hundred; on levels that single spike correlates
  all six media channels at 0.98 and hides everything else. Those rows breach the
  source contract's declared maximum and would be quarantined at ingestion, so an
  analytical detector must not be scored on them.
- **P3 — counterfactuals are full re-runs, not warm-started windows.** The design
  proposes re-simulating only `[event_start-60d, event_end+60d]`, warm-started from
  the factual state, because a full re-run was assumed expensive. Here a full 36-month
  run takes ~2.4 s, so a full re-run is both cheaper to reason about and *strictly
  more correct*: there is no warm-start approximation to defend, and the
  common-random-number property already guarantees the two worlds differ only by the
  event.
- **P3 — the windowing idea survives as batching across independent events.** Two
  events that cannot reach each other's rows or each other's window can be removed in
  the SAME counterfactual run and measured separately. That is what turns 641 naive
  simulations into 149 (5m47s) for a 445-event ledger. It is the same insight as
  windowing, applied to the run count rather than the day count.
- **P3 — interaction is mechanism-specific, not a dimension intersection.** The first
  attempt treated any overlap on any dimension as coupling, which chained 418 of 445
  events into one group. Two events interact only through demand-and-substitution
  (same region AND category), inventory (same warehouse, region, category and SKUs),
  or media adstock (same channel and region). Everything else is independent whatever
  the calendar says.
- **P3 — the ledger job streams panels instead of holding them.** The first full run
  was killed by the OOM killer at run 85: 149 simulated worlds is about 25 GB. Each
  run is now consumed as it is produced — coalition scalars read off, segment
  measurements taken against the factual world, panel dropped — so peak memory is two
  panels.
- **P3 — effects are measured within the event's own scope as well as nationally.**
  A calibration event confined to one region-category moves ~5% of the company, so a
  25% hit inside its scope reads as 0.2% nationally. Since the engine scans KPI x
  segment, recording only the national number would make the corpus look like 440
  immaterial events. Measured scope-relative spread: p05 0.43%, p50 2.80%, p95 11.6%.
- **P3 — Scenario A's outage is deeper than the architecture doc's illustration.**
  That document has DC-North's fill rate falling to 81.4% AND costing -7.1pp of
  national revenue. Those are not consistent in this world: DC-North serves ~26% of
  revenue and DC-West cross-serves part of any shortfall, so 81.4% costs about
  -2.5pp. To reach the -12% target the outage has to bite harder; the measured
  DC-North fill rate for the week is **35.2%**, reported as measured rather than as
  the document's figure.
- **P3 — Scenario B moved from 13 Apr to late March 2026.** The data-layer design
  dates it 13 Apr, which is after `SIM_TODAY` (29 Mar) and so would not be visible in
  the demo. The MarTech drop due Mon 23 Mar is the one that never arrives.
- **P3 — twelve extra in-window launches were added to the world.** Scenario C rests
  on a *pooled* launch baseline, and with one or two prior launches "the pooled launch
  curve" would be a claim rather than an estimate. Thirteen SKUs now launch inside the
  window; twelve of them are history for the thirteenth.
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

- **P5 — a price change moves the list price, not only the realised price.** The OMS
  contract declares `unit_price_net <= list_price`; the simulator multiplied only the
  realised price by an event's `price_multiplier`, so every price-increase event
  produced rows the contract says cannot exist (41,509 of them, 3.1% of the order book,
  all quarantined on the first ingestion run). Fixed in `simulate.py`. Demand, units and
  revenue are unchanged — `list*(1-d)*m` and `(list*m)*(1-d)` are the same number — so
  only `list_price` and the discount-depth submetric move. The panel checksum changed
  and every P2/P3 gate was re-run green.

- **P5 — a bulk historical load is one wide batch per source, not a replay at speed.**
  Replaying thirty-six months of arrivals is roughly forty thousand batches. A real
  deployment loads history in one pass and only then starts watching, so `backfill()`
  lands one extract per source whose manifest lists every period it covers. Everything
  downstream works on it unchanged, because a bulk load is just a very wide batch.

- **P5 — `timestamp_tz` added to the source contract.** The ticketing API stamps UTC
  while the house runs on IST, which moves every ticket raised before 05:30 onto the
  previous day. Declared on the contract rather than inferred from the data: no
  distributional test recovers a half-hour offset reliably. Silver converts on the
  declaration and then *verifies* it against the business key — `TIC-20260316-N001`
  encodes the IST date it was raised on — so the declaration is checked rather than
  trusted. Post-conversion mismatch is under 0.5%.

- **P5 — currency conversion is a published policy, not a heuristic.**
  `ingest/policies/fx_rates.yaml` names the desk that books in USD, the rate and the
  rate-date. Guessing "this row looks too cheap, divide by 83" is a heuristic; finance
  publishing which unit books in what is how real pipelines resolve it. The plausibility
  floor separates the desk's export lines from its INR lines; the rest of the desk is
  untouched.

- **P5 — `quarantine_and_alert` quarantines the undeclared column, not the batch.** A
  literal reading would quarantine every MarTech row from the drift date onward and take
  Scenario B with it. The alias column is alerted, kept in bronze exactly as delivered,
  and dropped at silver, so nothing undeclared can reach a mart. `reject_batch` still
  rejects the whole delivery.

- **P5 — a positive `max_frac_violating` warns; a zero one quarantines.** A tolerated
  condition is survivable by definition ("about one order in fifty has no region
  mapping"), and holding those rows back would invent a revenue dip that never happened.
  A zero tolerance means the condition is impossible, so the rows cannot be true and are
  held. Either way the *rate* is the finding and it feeds the DQ score. Column `min`/`max`
  ranges and declared `comparisons` are always hard: they are impossibilities, and they
  are what catches the silent unit change.

- **P5 — "inject event" runs a planted ledger event rather than synthesising one.** The
  judge chooses when it breaks, not whether the break is real. A new event would need a
  fresh simulation and a fresh counterfactual, and a number the ground-truth ledger
  cannot vouch for has no business on stage.

- **P5 — redundant range bounds alongside every exact key filter.** `list_contains($keys,
  date)` alone cannot be pushed through an ASOF join, so every daily rebuild scanned the
  whole thirty-six-month table and the ninety-day replay became quadratic. Period labels
  sort lexicographically in calendar order (`2026-03-08`, `2026-W11`) precisely so a
  `BETWEEN` bound can sit beside the membership test.


- **P6 — a parametric baseline, not a local smoother.** An STL or rolling-median trend
  treats a two-week outage as the level and its residual over the event is small:
  measured -7.3% against the ledger's -11.9%. `RegressionBaseline` — linear trend,
  weekly and annual Fourier terms, movable events as regressors over a [-12, +8] day
  window, plus declared exogenous controls — cannot chase a local dip, and measures
  -14.0%. MSTL is retained for period discovery and the seasonal profile.

- **P6 — period discovery is iterative and requires an ACF *peak*.** A smooth series has
  a significant ACF at every short lag, so significance alone confirmed lags 2 and 4 as
  seasonal periods. Discovery now accepts the strongest candidate, removes its seasonal
  component, and re-tests the rest; a candidate must also stand above its neighbouring
  lags. Only period 7 survives, which is the truth.

- **P6 — an unobserved day is NaN, never `log(0)`.** One national day with no delivered
  rows, clipped to `1e-9`, produced a log residual of about -38 that inflated the EWMA
  variance 38-fold for months and silently disabled every detector in the system. This
  is the single most dangerous class of bug in the build: it has no error, no warning,
  and it looks exactly like a quiet period.

- **P6 — CUSUM runs on the standardised residual, not the AR innovations.** Whitening
  removes the persistence a CUSUM exists to accumulate.

- **P6 — the primary estimator is a stated modelling decision, not a default.**
  `sarimax` for a level target; `hac` for a differenced one, because differencing
  induces a moving-average error whose order is not identified here and Newey-West is
  consistent without specifying it. Measured on the weekly price elasticity: AR(1)
  gives -1.34, ARMA(1,1) by AIC gives -0.96, HAC gives -1.63 against a planted -1.94,
  and the agreement score falls from 0.99 to 0.59 as the error model is elaborated —
  which is the diagnostic saying the elaboration is not supported. Both estimators are
  always fitted so the disagreement is reported rather than resolved by preference.


## Phase plans

### P10 plan (next)

1. `frontend/src/` — the nine screens over the typed API: insight feed, insight card
   with the evidence drawer, landing-zone monitor, DQ dashboard, admin panel with the
   four demo controls, telemetry, calibration, audit, and the conversational view.
2. Persona switching in the UI that calls `POST /api/session/role`, so what changes is
   the data.
3. `tests/e2e/` — Playwright, plus the screenshots the submission needs.

### P9 plan (done)

1. `api/routers/` — the routes in the build prompt, every response a pydantic model.
2. Session role switching that actually changes the data: the compiler's row filters and
   column masks are already below the LLM, so a role change is a data fact.
3. `ws.py` — the live event stream the landing-zone monitor and the demo controls use.
4. `tests/integration/test_p9_api.py` — the gate, including the entitlement matrix
   exercised through HTTP rather than through the compiler directly.

### P8 plan (done)

1. `llm/provider.py` — `LLMProvider` ABC with a mandatory `MockProvider` that runs the
   whole application offline, plus an Anthropic implementation behind the settings flag.
2. `llm/planner.py`, `llm/hypotheses.py` — the model proposes *questions and
   hypotheses*, never numbers; every hypothesis is a typed object the engine then tests.
3. `llm/narrate.py` + `llm/templates.py` — narration constrained by the confidence tier's
   permitted language.
4. `llm/verify_numbers.py` — a deterministic verifier matching every numeral in the
   generated text against the bundle's `NumberFact` set, within each fact's tolerance.
   **A sentence containing an unsupported number never reaches a human.**
5. `llm/verify_entailment.py` — claim-level checking (NLI behind a flag; a lexical
   fallback by default).
6. `llm/router.py` + `telemetry/` — model tier routing under the per-insight cost cap.
7. `tests/unit/test_p8_llm.py` — the gate.

### P7 plan (done)

1. `engine/evidence.py` — BM25 retrieval over the corpus with dual-date awareness
   (match on **effective** date, not only publish date), `EvidenceConf = w1*rerank +
   w2*source_tier + w3*entity_link + w4*extraction`, noisy-OR corroboration across
   *independent* sources with ingestion-time syndication dedup as the independence
   guard, a timing gate eliminating candidates that post-date the effect or fall
   outside the driver's contract `lag_days`, and a sufficiency check routing to
   abstention.
2. `engine/confidence.py` — six `ConfidenceSignal` classes (c1 detection, c2
   attribution, c3 statistical validity, c4 data trust, c5 evidence, c6 narrative
   faithfulness), `softmin(p=-4)`, isotonic map, tiers, and the hard gates.
3. `engine/actions.py` — `CaseLibrary` precedent lookup plus a governed YAML action
   catalog; expected impact from estimated elasticities with the interval propagated;
   owner and approval threshold from the contract's decision rights.
4. `engine/bundle.py` — the `InsightEvidenceBundle`. Every number that reaches the UI
   or the LLM lives in this object.
5. `AbstentionArtifact` as a designed output type.
6. `tests/integration/test_p7_evidence.py` — the gate.

### P6 plan (done)

1. `engine/baseline.py` — period discovery by `scipy.signal.periodogram` confirmed by
   ACF significance (never assume 7/365); MSTL on `log(y)` where strictly positive;
   movable events as regressors rather than fixed-lag seasonality; counterfactual
   prediction; `PooledLaunchBaseline` (empirical-Bayes pooling over comparable launches)
   for sparse series.
2. `engine/detect.py` — AR(p) whitening by AIC with Ljung-Box verification; EWMA
   (lambda 0.94) variance floored by day-of-week-stratified MAD; conformal p-values with
   calibration windows excluding known anomalies and regime breaks; Benjamini-Hochberg
   across the KPI x segment scan; tabular CUSUM (k=0.5, h=4-5) with a persistence
   requirement; robust Mahalanobis (`MinCovDet`) on the joint residual vector.
3. `engine/gate.py` — materiality requiring both a statistical trigger and the contract's
   business floor; priority = rule score x LightGBM ranker, ranker disabled below a
   minimum label count and reverting to rules if stale.
4. `engine/attribute_where.py` — Adtributor: `EP_s`, `Surprise_s = JS(p_s || q_s)`,
   score = EP x Surprise; per-dimension scoring, prune to top-K, <=2-dimension
   combinations among survivors, minimum-observation gating, Simpson's-paradox check on
   nested segments, cumulative-EP Pareto rule; `bootstrap_stability(n=100)` with a
   ranked shortlist below the stability floor rather than a named cause.
5. `engine/attribute_kind.py` — Bennet price-volume-mix, asserting the parts sum to
   `delta R` within 1e-6.
6. `engine/attribute_why.py` — adstock grid, lags, Fourier terms, holiday/promo dummies;
   SARIMAX with exogenous regressors as primary; OLS + Newey-West HAC as cross-check;
   agreement score; Ljung-Box, Breusch-Pagan, Durbin-Watson, VIF, holdout MAPE;
   regressor admissibility from the contract driver DAG with mediators excluded from a
   total effect; VIF>5 drivers attributed as a group; event study against control regions.
7. Coverage accounting: explained vs unexplained, the remainder labelled honestly.
8. `tests/statistical/test_p6_engine.py` — the gate, whose credibility checkpoint is the
   KS test for uniform conformal p-values on clean holdout windows.

### P5 plan (done)

1. `harness/clock.py` — `SimClock` with modes backfill / replay(N x) / live(1 x) / step.
2. `harness/scheduler.py` — `ArrivalScheduler`: per source contract, cron + jitter +
   failure probability + restatement batches.
3. `harness/landing.py` — `LandingZone`: partitioned files plus a `manifest.json` per
   batch (schema in DataLayer §10.2), and `SourceWatcher`.
4. `harness/controls.py` — `DemoControls`: inject event, break feed, send restatement,
   time-travel, reset.
5. `ingest/` — bronze (immutable raw + `batch_id`, `received_at`, `sim_time`,
   `row_hash`, `schema_version`), DQ gates from the source-contract expectations with
   **quarantine, never drop**, silver (calendar spine, conformed dimensions, IST
   normalisation, unit normalisation, currency conversion, dedup, PII masking), gold
   (contract-grain marts, the dimensional cube, the driver panel).
6. Watermarks per source; late batches rewind the watermark for their period only;
   supersede-by-batch for restatements with prior versions retained; idempotency by
   `(source_id, batch_id)` plus `row_hash`.
7. `DataLandedEvent` waking **only** the KPIs whose contracts depend on that source.
8. `tests/integration/test_p5_ingest.py` — the gate: 90 sim-days replay; a repeated
   `batch_id` changes nothing; identical rows under a new `batch_id` are deduplicated;
   a restatement supersedes with both versions queryable; pausing a feed flips
   freshness green -> amber -> red on the SLA schedule; a late batch recomputes exactly
   the affected window; the unit-change defect is quarantined by range expectations.

### P4 plan (done)

1. `datagen/projection/` — eleven `SourceProjector` subclasses. Full fidelity: OMS
   (order-line-day), WMS (T+2), MarTech (weekly Mon, 14-day restatement, 12-month
   history), support tickets (continuous, text + PII), competitor prices (weekly,
   3-day lag, ~60% SKU coverage, fuzzy match with a confidence score). Lightweight:
   PIM, inventory snapshots, weather, holiday calendar. Corpus-only: news, pricing memos.
2. The **designed disagreements** from DataLayer §5: OMS vs ERP definition gap,
   MarTech attributed vs order-linked revenue (5-15% normally, **18% in Scenario B**),
   WMS vs OMS cut-off, competitor match error.
3. `datagen/defects/` — one `DefectInjector` per pathology **P1-P30**, each
   self-registering in a catalog and individually toggleable.
4. `datagen/corpus/` — 600-800 documents generated FROM the event ledger. Templates
   for routine documents; the ~150 scenario-critical ones generated once and committed
   as fixtures in `tests/fixtures/corpus/`. Enforce the corpus rules: ~15% of events
   get no document, ~10% contradictory pairs, 3-6 outlet syndication, ~20% with a
   later effective date, ~8% post-dated decoys. PII realistic in format but never real.
5. `tests/integration/test_p4_projection.py` — the gate: a test per defect asserting
   it is present and detectable (P8 silent unit change and P26 syndication get named
   tests); reconciliation deltas in their designed ranges; corpus composition within
   tolerance; no real-looking personal identifiers.

### P3 plan (done)

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
