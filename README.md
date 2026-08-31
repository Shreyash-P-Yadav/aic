# Insight Copilot

A KPI intelligence-to-action engine. It watches business KPIs, detects genuine
anomalies, explains them with rigorous statistics, narrates them differently for
different job roles, **refuses to answer when the evidence is weak**, and recommends
actions tied to owners — with every number traceable to a computation and every
model call metered.

> **All data in this repository is simulated.** The company — Meridian Consumer
> Brands, an India-based home & personal care business, ~₹850 cr, 150 SKUs, 6
> categories, 5 regions, 4 channels, 4 DCs — is fictional, and so are its products,
> customers, campaigns, incidents and documents. Every person named in the corpus is
> invented, every email address is `@example.com`, and no figure the application
> displays describes a real business.

## The principle

**Statistics decide; the model narrates.** Every number originates from SQL, NumPy, or
statsmodels. A language model may never produce, alter, or infer a numeric value, a
threshold, a confidence, or an action — and this is enforced structurally rather than
by prompt: the LLM cannot emit SQL, all data access goes through a contract-to-SQL
compiler that applies the caller's row filters and column masks, and a deterministic
verifier re-extracts every number from every generated sentence and checks it against
the computed evidence bundle before a human sees it.

## Architecture

```
                       ┌──────────────────────────────────────────┐
   simulated world     │  datagen/   world · latent · decisions   │  all synthetic
   (deterministic      │             outcomes · events · corpus   │  seeded, replayable
    from one seed)     └────────────────┬─────────────────────────┘
                                        │  projection + defect injection
                                        ▼
                       ┌──────────────────────────────────────────┐
   arrival simulation  │  harness/   clock · cron · landing zone  │  late, partial,
                       │             quirks · restatements        │  restated, broken
                       └────────────────┬─────────────────────────┘
                                        │  manifest per batch
                                        ▼
                       ┌──────────────────────────────────────────┐
   intake              │  ingest/    bronze → dq → conform →      │  quarantine,
                       │             silver → gold · freshness    │  never drop
                       └────────────────┬─────────────────────────┘
                                        │
                       ╔════════════════▼═════════════════════════╗
   ── the security     ║  contracts/ + security/                  ║  row filters and
      boundary ──      ║  ContractSQLCompiler · AuditLog          ║  column masks live
                       ╚════════════════╤═════════════════════════╝  BELOW the LLM
                                        │  parameterised SQL only
                                        ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  engine/   the statistics. Nothing below this line is ever model-generated. │
   │                                                                            │
   │  detect      periodogram → MSTL / regression baseline → AR whitening →     │
   │              conformal p-values → Benjamini-Hochberg → CUSUM → Mahalanobis │
   │  attribute   1. WHERE  Adtributor (EP × Jensen-Shannon surprise),          │
   │                        bootstrap stability, Simpson's-paradox check        │
   │              2. KIND   Bennet price / volume / mix — an exact identity     │
   │              3. WHY    SARIMAX vs OLS + Newey-West HAC, VIF grouping,      │
   │                        DAG-based regressor admissibility (no mediators)    │
   │  evidence    BM25 with dual dates → contract timing gate → noisy-OR        │
   │              corroboration, syndication-deduplicated                       │
   │  confidence  six measured signals → softmin(p = −4) → isotonic calibration │
   │              → tier, with hard gates that force abstention                 │
   │  actions     governed catalogue; preconditions evaluated, never assumed    │
   └────────────────────────────────┬───────────────────────────────────────────┘
                                    │  InsightEvidenceBundle — every number, with lineage
                                    ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  llm/   four call sites, and a verifier after each one that emits text      │
   │  planner (allowlist-validated) · hypotheses (cite-or-drop) ·                │
   │  narrate (persona style cards) · classify_feedback (offline, batched)       │
   │  verify_numbers (deterministic, Indian formats) · verify_entailment       │
   └────────────────────────────────┬───────────────────────────────────────────┘
                                    ▼
              api/ (FastAPI, pydantic at every boundary)  →  frontend/ (React + TS)
                                    │
              learning/ feedback · ranker · case library  ←  evals/ backtest · report
```

Two directions are worth reading off that diagram. **Down** the left edge: every number
crosses the security boundary as parameterised SQL a contract authorised. **Up** from
the engine: the LLM receives a finished evidence bundle and returns prose, which is
then checked against that same bundle. There is no path by which a model call
influences a figure.

## Quick start

```bash
make install          # python venv + npm install
make demo             # generate, backfill, ingest, run, pre-warm, serve
```

Then open <http://127.0.0.1:8000> for the API and, in another shell, `make dev` for the
UI on <http://localhost:5173>.

The application runs **entirely offline with no API key**: `LLM_PROVIDER=mock` is the
default, and a zero-LLM template narrator exists for every persona and every confidence
tier. Copy `.env.example` to `.env` only if you want to change something.

## Make targets

| Target | What it does |
|---|---|
| `make install` | Create `.venv`, install the backend editable with dev extras, `npm install` |
| `make lint` | ruff check + ruff format --check; eslint + prettier |
| `make typecheck` | `mypy --strict` on the backend; `tsc -b` on the frontend |
| `make test` | pytest + vitest |
| `make dev` | Backend (:8000) and frontend (:5173) together |
| `make build` | Production frontend build |
| `make generate` | Generate the simulated world, events, source extracts and corpus |
| `make generate-truth` | Counterfactual ground truth for every planted event (~6 min) |
| `make backfill` | Bulk historical load: one wide extract per source, every mart built |
| `make replay` | `DAYS=30` — backfill to *N* days ago, then replay those days as live arrivals |
| `make demo` | One command: load, backfill, replay, run the scenario, pre-warm, serve |
| `make demo-reset` | Remove derived state so the next `make demo` starts clean |
| `make backtest` | Replay the truth ledger, fit calibration, write `artifacts/eval_report.md` |
| `make validate-contracts` | Validate every KPI and source contract |
| `make verify-pN` | The gate for build phase *N* |
| `make verify-all` | Every gate, in order |

## The four scenarios

Run `make demo`, then follow `docs/DEMO_SCRIPT.md` for the exact clicks. In short:

| # | What it shows | Where to see it | The right answer |
|---|---|---|---|
| **A** | **The flagship.** A DC-North pick-capacity failure in March 2026, with a media cut and a price rise in the same window and a post-dated competitor decoy. | Feed → the `net_revenue` card → Insight detail | The ladder separates them: North is named, the decoy is rejected by the timing gate because it is dated *after* the effect. |
| **B** | **Abstention.** The MarTech feed goes dark. | Admin → **Break a feed** → `martech_weekly` → Run, then Feed | Freshness walks green → amber → red on that contract's own SLA, `c4` collapses, and the engine **declines to attribute** rather than attributing to what it can still see. |
| **C** | **Restraint.** An 18-day-old product launch. | Admin → **Inject event** → `EV-2026-0311-AURORA-LAUNCH-PROMO` → Run | The history floor is not met, so the right output is *not to fire*. |
| **D** | **The distractor.** A movement that is real, statistically clean, and below the contract's business floor. | Feed | Silence. Statistical significance is not materiality. |

## Switching role

The role selector in the top bar changes the **data**, not the label. Row filters and
column masks are applied by the contract compiler, below the API and below the LLM, so
switching to *Regional Sales Manager — North* removes other regions' rows from the SQL
itself and masks margin and discount columns — there is no client-side filter to
bypass. The **Audit** screen shows the compiled statement and its outcome for every
query, and a refusal is logged as carefully as a result.

| Role | Scope |
|---|---|
| CFO | Board-ready impact view. Full national scope, no masks. |
| Analyst | Full method access: coefficients, diagnostics, lineage, residuals. |
| Marketing Lead | Full marketing domain; margin columns masked. |
| Regional Sales Manager — North | Region-scoped rows; margin and discount masked; no marketing domain. |
| Intern | Denied on financial and marketing KPIs; aggregate operational views only. |

## Demo controls

**Admin** carries four controls, and each says what it will do before it does it. All
four re-run the engine afterwards, because a control that changes the world without
re-running the engine changes nothing anyone can see:

- **Inject event** — jumps the simulated clock to two days before a planted ledger
  event and replays through it. The break is real; a counterfactual in the ground-truth
  ledger can vouch for what it should have cost.
- **Break a feed** — pauses a source, then runs the clock forward until it has actually
  gone stale. Freshness decays on *that contract's own SLA schedule*, not on a UI timer,
  and the engine moves from publishing to hedging to abstaining as `c4` degrades.
- **Restore a feed** — lets a paused source deliver again, so the refusal can be shown
  more than once without restarting the application.
- **Advance the clock** — replays forward by whole days: every drop due in the window
  lands in order and freshness is re-measured against each contract's own SLA. Forward
  only. Backwards would mean wiping the warehouse and reloading it, because the marts
  already hold rows for days that would not have happened yet.

## What the LLM does and does not do

| | Produced by | Verified by |
|---|---|---|
| KPI values, deltas, counterfactuals | DuckDB via the contract compiler | reconciliation against a second source |
| Anomaly p-values, FDR decisions | conformal + Benjamini-Hochberg (NumPy/SciPy) | KS-uniformity test on the calibration set |
| Segment contributions, shares | Adtributor + bootstrap (NumPy) | Simpson's-paradox check; stability floor |
| Price / volume / mix split | Bennet indicator (exact identity) | the parts sum to Δ to 1e-6, property-tested |
| Driver coefficients and intervals | SARIMAX / OLS-HAC (statsmodels) | two estimators; their disagreement is reported |
| Confidence, tier, abstention | six measured signals → softmin → isotonic | backtested; reported uncalibrated until fitted |
| Recommended actions | governed catalogue, preconditions evaluated, impact priced from the estimated elasticity | an unevaluable precondition suppresses the action; so does an expected impact that would widen the gap |
| **Query plans** | LLM proposes an **intent**, never SQL | allowlist validation against the contract |
| **Candidate hypotheses** | LLM | cite-or-drop against the bundle's own documents |
| **Narrative prose** | LLM, from a finished bundle | every number re-extracted and matched; every causal claim entailment-checked |
| **Feedback labels** | LLM, offline and batched | deterministic rule fallback with no model at all |

## Known limitations

These are measured, not estimated. `artifacts/eval_report.md` carries the full table
with counts, and `BUILD_PROGRESS.md` records each one with its cause.

- **The blended marketing elasticity is recovered at 0.066 against a planted 0.143.**
  This is an identification problem, not a code defect: media budget is set as a share
  of revenue on a quarterly plan, so log spend is near-collinear with the seasonal
  controls that must be included, and the six channel adstocks correlate 0.81–0.96. The
  DAG-specified estimate is three times closer to truth than the naive one and has the
  right sign; the uncertainty is reported through the `c3` signal rather than tuned away.
- **The confidence score does not discriminate on the calibration corpus** (holdout
  AUC 0.531), so the fitted isotonic map is **measured and deliberately not adopted**.
  The system continues to describe itself as uncalibrated, which is the true statement,
  rather than deriving tier bands from a curve that measured nothing.
- **Detection precision is at chance on this corpus** (lift 0.92) and recall on
  high-detectability events is 0.47 against a 0.70 target. Both follow from the corpus
  being planted very densely — 61% of scanned days lie inside some event window, and
  about eight events are live on a covered day.
- **`Central` region appears on only 42% of days** in the revenue mart against a 12%
  population weight. National revenue validates at ₹853 cr and every realism test
  passes, so aggregates are unaffected, but region-sliced work should read this first.

## Documentation

- `docs/DEMO_SCRIPT.md` — the seven-minute running order, click by click
- `docs/CLAUDE-CODE-BUILD-PROMPT.md` — the build specification (authoritative)
- `docs/InsightCopilotv2FinalArchitecture.md` — the analytical architecture
- `docs/InsightCopilotDataLayerDesign.md` — data generation and intake design
- `docs/PRISMRound2Blueprint.md` — the governance, contract and persona design
- `BUILD_PROGRESS.md` — what is built, what is deferred, every known issue
- `BUILD_LOG.md` — each phase's actual gate output, pasted verbatim
