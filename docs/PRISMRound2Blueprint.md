# PRISM — a KPI Intelligence-to-Action Engine

**Accenture Innovation Challenge 2026 · Round 2 · Track 3: BusinessIntelligence.ai**
**Document type:** Technical Business Proposal + Prototype Execution Plan
**Prepared by:** Team [name] · Principal AI Architect / Lead Data Scientist perspective

> **PRISM** — *PRioritised Insight & Semantic Metrics.* A prism splits white light into its component wavelengths; PRISM splits a KPI movement into its component drivers — deterministically, with confidence intervals — and only then lets a language model tell the story.

---

## 0. Executive Summary

PRISM is a **hybrid intelligence-to-action engine** built on one non-negotiable principle: **every number is computed; no number is generated.**

- A **deterministic core** (Python / NumPy / SciPy / statsmodels over DuckDB) performs detection, decomposition, econometric driver estimation, confidence scoring, and action selection. It is built specifically for the statistical realities of business time series — **autocorrelation and heteroscedasticity** — using STL + AR-innovation anomaly detection, CUSUM changepoints, exact Bennet price–volume–mix decomposition, and dynamic regression with **Newey–West (HAC) robust inference** cross-checked against **SARIMAX-with-exogenous-regressors**.
- A **governed semantic layer** of YAML **KPI contracts** is the single gateway to data: every query — human-initiated or LLM-initiated — is compiled from a contract, which also carries definitions, drivers, materiality thresholds, lineage, and row/column/domain access policy.
- The **LLM layer is deliberately narrow**: intent parsing, contextual retrieval, persona-specific narrative synthesis, and feedback classification. A **deterministic numeric verifier** checks every number in every generated narrative against the computed evidence bundle; failures trigger regeneration or fall back to a template renderer. The LLM can therefore *never* be the source of quantitative truth — by architecture, not by prompt-engineering hope.
- The engine **abstains as a designed behavior**: a calibrated composite confidence score with hard gates produces a first-class "insight withheld" artifact that states what is known, what is missing, and when it will retry.
- Everything is instrumented: **latency, model calls, token usage, and cost-per-insight** are logged per pipeline stage and surfaced in the demo UI.

The prototype simulates a consumer-products business with **3 source systems** (daily SalesOps DB, weekly restated MarTech exports, 48-hour-lagged Supply Chain extracts), **5 governed metrics (3 headline KPIs + 2 contract-governed driver metrics)**, **4 roles/personas**, and **four scripted scenarios** that map one-to-one onto the brief's minimum expectations: a multi-factor revenue drop with planted ground truth, a low-confidence abstention, a sparse-history product launch, and a role-based entitlement demonstration.

**Why we win:** most teams will demo an LLM that talks about charts. PRISM demos a system that *recovers planted ground truth to within measurable tolerance, proves it with diagnostics, prices every insight in rupees and milliseconds, and knows when to shut up.*

---

## 1. Problem Framing & Business Case

### 1.1 The problem, precisely

When a KPI moves, organizations pay three costs:

1. **Time-to-explanation.** A material revenue movement typically triggers days of analyst triage across ERP, CRM, marketing, and supply systems that disagree on definitions, calendars, and grain. The explanation arrives after the decision window has closed.
2. **Narrative risk.** The loudest plausible story wins. Without quantified attribution, organizations act on anecdote ("it must be the price change") while the true driver (a warehouse outage compounding a lagged marketing cut) goes unaddressed.
3. **Action latency.** Even correct explanations stall because they are not connected to *who owns the lever*, what it is expected to recover, and how success will be monitored.

Dashboards show *what*; they structurally cannot show *why* or *what to do*. Generic "chat with your data" copilots fail in the enterprise for the exact reasons this brief enumerates: they hallucinate numbers, ignore entitlements, cannot calibrate confidence, and treat every user identically.

### 1.2 Target users (prototype personas)

| Persona | Needs | Depth | Channel |
|---|---|---|---|
| **CFO / Exec** | Impact in ₹, top drivers, decisions awaiting sign-off, confidence | 4–6 sentences | Weekly digest + workspace card |
| **Regional Sales Manager (RSM)** | *Their region's* movements, operational actions they own | Region-scoped, action-first | Daily alert + workspace |
| **Analyst** | Full method: coefficients, CIs, diagnostics, lineage, residuals | Complete evidence bundle | Workspace + notebook export |
| **Restricted user (intern)** | — (entitlement demo: denied with reason + request-access path) | — | — |

### 1.3 Value case (what we will claim in the pitch)

- **Time-to-explanation:** days → minutes (proactive insight published ≤ 30 s after data lands; conversational answer ≤ 8–12 s p95).
- **Explanation quality:** attribution recovered within ±20 % relative error of planted ground truth on the eval suite; ≥ 89 % of movement explained in the flagship scenario.
- **Trust:** 100 % numeric fidelity (every number in every narrative traceable to a computed value); calibrated confidence (reliability curve shown, not asserted); honest abstention.
- **Unit economics:** ≈ **$0.02 (≈ ₹1.7) per fully narrated insight** at prototype model prices, with a costed scale projection (§9).
- **Product KPIs we would track in pilot:** alert precision/recall vs. analyst adjudication, expected calibration error, % narratives accepted without edit, actions initiated per insight, cost per insight.

### 1.4 Positioning

Platform copilots (Databricks Genie, Snowflake Cortex Analyst, Power BI Copilot) answer *ad-hoc questions*. PRISM's differentiation is the **closed loop**: proactive materiality-gated detection → econometric attribution → decision-rights-aware action → monitoring plan → feedback learning, with abstention and per-insight cost accounting. The semantic contract is the durable asset: it makes the engine portable across platforms (§3.4).

---

## 2. Design Principles & Trade-off Analysis

Step-by-step, the reasoning that fixed the architecture:

**P1 — Separation of truth and talk.** Quantitative truth is produced only by deterministic code paths (SQL, NumPy, statsmodels). Language models touch language: intent, retrieval ranking, narration, feedback classification. Enforced by (a) a query compiler the LLM cannot bypass, (b) a post-generation numeric verifier, (c) a template fallback that needs no LLM at all.

**P2 — Contracts before queries.** No component — including the LLM intent parser — composes free SQL. Intents reference a KPI contract; the compiler emits SQL from the contract with the caller's row filters and column masks applied. This one mechanism simultaneously solves definitional consistency, entitlement enforcement, lineage, and prompt-injection-to-SQL risk.

**P3 — Econometrics first, ML as challenger.** Driver identification uses interpretable statistical models with *valid inference under autocorrelation and heteroscedasticity* — because business series are autocorrelated (momentum, weekly cycles) and heteroscedastic (promo/holiday variance clustering), and naive OLS/z-scores produce confidently wrong answers there. A gradient-boosting challenger is a stretch goal for nonlinearity detection, never the primary explainer (SHAP attributions carry no confidence intervals and conflate correlation with causation).

**P4 — Confidence is computed, not vibes.** The confidence score is a function of measured quantities: freshness vs. SLA, DQ pass rate, residual diagnostics (Ljung-Box, Breusch–Pagan), CI widths, explanation coverage, cross-method agreement. Abstention is a hard-gated, first-class output.

**P5 — Actions are retrieved from a governed catalog, never invented.** The engine recommends only actions whose preconditions hold, in the brief's exact structure: *driver → controllable lever → action → expected impact → owner → confidence → monitoring plan*. Decision rights live in the contract (e.g., price changes are "recommend review to Pricing Committee," never "change price").

**P6 — Everything metered.** Every stage logs wall-time, model, tokens, cache status, and cost into a run ledger. The telemetry page *is part of the demo*.

### 2.1 Key trade-offs considered

| Decision | Chosen | Alternatives | Why chosen / cost accepted |
|---|---|---|---|
| Platform | **Custom Python stack** (DuckDB, statsmodels, FastAPI, Streamlit) | Databricks / Fabric / Snowflake native | Judges must *see the mechanism*; custom keeps the LLM boundary explicit, zero licensing friction, fully reproducible on a laptop. Cost: we rebuild plumbing → mitigated by a thin warehouse adapter (DuckDB ↔ Snowflake/Databricks SQL) for the production path. |
| Warehouse | **DuckDB** (embedded, columnar) | Postgres, SQLite | Real SQL + window functions, zero infra, fast on 1–5 M rows. Postgres adds realism but not evaluative value in Round 2. |
| Driver inference | **SARIMAX-with-exogenous (primary) + OLS with Newey–West HAC (robustness cross-check)** | OLS only; XGBoost+SHAP; Bayesian structural TS | SARIMAX models the error autocorrelation (efficient estimates); HAC-OLS is assumption-light (consistent SEs under both autocorrelation and heteroscedasticity). Agreement between the two feeds the confidence score; disagreement lowers it. BSTS/CausalImpact noted as production upgrade. |
| Anomaly detection | **STL + AR innovations + EWMA variance + CUSUM** | Prophet, Isolation Forest, plain z-score | Plain z-scores on autocorrelated residuals understate variance → false alerts; innovations from a fitted AR model are approximately white, and EWMA/day-of-week variance handles heteroscedastic volatility. Fully explainable to a skeptical judge. |
| Attribution algebra | **Bennet (arithmetic-mean-weight) PVM decomposition** | Laspeyres/Paasche, LMDI | Bennet is exact, additive, symmetric (order-independent) — no residual "interaction" bucket to hand-wave. |
| LLM usage | **Small model for intent/feedback; mid model for narrative; temperature 0; JSON-schema outputs; semantic cache** | One large model everywhere; fine-tuning | Cost and latency discipline; fine-tuning rejected for prototype (no volume, hurts auditability). Local Ollama fallback removes demo-day network risk. |
| UI | **Streamlit workspace over FastAPI service** | React SPA | Ship in days, not weeks; FastAPI keeps clean typed endpoints so a React front can be added later without rework. |
| Feedback learning | **Parameter/prior updates + few-shot exemplars + eval gates** | RLHF / fine-tune loop | Right-sized, auditable, demonstrable within the round. |

---

## 3. Architecture Blueprint

### 3.1 End-to-end data flow

```
┌──────────────────────────── SOURCE SYSTEMS (simulated, deliberately heterogeneous) ───────────────────────────┐
│  S1 SalesOps DB           S2 MarTech Export             S3 SupplyChain ERP          S4 Context Store          │
│  daily @ 02:00 IST        weekly Mon @ 06:00 IST        daily, 48 h latency         promo/price memos,        │
│  SKU×region×channel       campaign×channel grain        warehouse×SKU grain         ops incidents, holiday    │
│  24 mo history, high DQ   12 mo, 14-day restatements    18 mo, occasional gaps      calendar (documents)      │
└───────┬───────────────────────┬────────────────────────────┬───────────────────────────┬─────────────────────┘
        ▼                       ▼                            ▼                           ▼
┌──────────────────────────────────────────────────────────────────────────┐   ┌──────────────────────┐
│ L1  INGESTION & CONFORMANCE (Python + DuckDB — deterministic)            │   │ Retrieval index      │
│  bronze (raw, watermarked) → silver (conformed calendar spine, conformed │   │ (BM25 + embeddings   │
│  dims: date/product/region/channel) → gold (contract-grain KPI marts)    │   │  over context docs)  │
│  • Freshness tracker (per-source SLA vs last_loaded_at)                  │   └──────────┬───────────┘
│  • DQ gates (volume, nulls, ranges, cross-source reconciliation)         │              │
└───────────────────────────────┬──────────────────────────────────────────┘              │
                                ▼                                                         │
┌──────────────────────────────────────────────────────────────────────────┐              │
│ L2  SEMANTIC LAYER — KPI CONTRACT REGISTRY (YAML → pydantic)             │              │
│  definitions · calculations · grain/calendar · driver DAG · materiality  │              │
│  thresholds · lineage · access policy (RBAC/RLS/masks) · sparse policy   │              │
│  ► CONTRACT-TO-SQL COMPILER = the ONLY query gateway (applies row        │              │
│    filters + column masks from caller identity; logs to audit)           │              │
└───────────────────────────────┬──────────────────────────────────────────┘              │
                                ▼                                                         │
┌──────────────────────────────────────────────────────────────────────────┐              │
│ L3  ANALYTICAL ENGINE (NumPy/SciPy/statsmodels — deterministic)          │              │
│  A. Detect      STL + AR-innovation z + EWMA variance + CUSUM + BH-FDR   │              │
│  B. Materiality statistical gate AND business-impact gate → priority     │              │
│  C. Decompose   Bennet PVM + dimensional contribution scan               │              │
│  D. Drivers     SARIMAX-exog (primary) ⟷ OLS + Newey–West HAC (check),  │              │
│                 adstock transforms, elasticities, full diagnostics       │              │
│  E. Baselines   forecasts, counterfactuals, sparse-history EB pooling    │              │
│  F. Confidence  composite score + hard gates → publish / hedge / ABSTAIN │              │
│  G. Actions     rule-matched from governed catalog (levers, owners,      │              │
│                 decision rights, expected impact, monitoring plan)       │              │
│  ══► INSIGHT EVIDENCE BUNDLE (typed JSON: the single source of truth)    │              │
└───────────────────────────────┬──────────────────────────────────────────┘              │
                                ▼                                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ L4  LLM ORCHESTRATION LAYER (the ONLY layer where LLMs run)                                      │
│  1. Intent parser (small model): NL → intent JSON validated against contract registry            │
│  2. Contextual retrieval: hybrid BM25+embedding search over context docs; LLM relevance ranking  │
│  3. Narrative synthesizer (mid model): evidence bundle + persona card → cited narrative          │
│     ► DETERMINISTIC NUMERIC VERIFIER: every number in draft must match bundle (± rounding)       │
│       fail → regenerate (max 2) → fail → TEMPLATE RENDERER (no-LLM fallback)                     │
│  4. Feedback interpreter (small model): free-text feedback → structured labels                   │
│  Router: model tiering · prompt caching · semantic cache keyed (intent, data watermark) · budgets│
└───────────────────────────────┬──────────────────────────────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ L5  EXPERIENCE & GOVERNANCE (FastAPI + Streamlit)                                                │
│  Decision workspace: prioritized insight feed · conversational panel · EVIDENCE DRAWER           │
│  (freshness, method, contribution, confidence, lineage per insight) · telemetry page             │
│  RBAC login (CFO / RSM / Analyst / Intern) · audit log · feedback capture → learning loop (§8)   │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Two operating modes share the same L2→L4 spine:

- **Proactive mode** (scheduled after each source refresh): scan all contract KPIs → detect → attribute → publish prioritized insight cards. No intent parsing needed (skips one LLM call — cheaper).
- **Conversational mode** ("Why did North revenue drop last week?"): intent parse → contract-compiled queries → same analytical modules on the requested slice → narrative.

### 3.2 The analytical engine in detail (the econometric core)

All modules operate on contract-grain series pulled through the compiler. Notation: `y_t` is the KPI at time `t`.

**A. Detection — built for autocorrelated, heteroscedastic series.**

1. **STL decomposition** (`statsmodels.tsa.STL`, robust=True): `y_t = T_t + S_t + R_t` (trend, weekly+annual seasonality via double STL, remainder).
2. **Whiten the remainder.** Business-series remainders are *not* white noise (Ljung–Box routinely rejects). Fit AR(p) on `R_t` (p by AIC, p ≤ 7); the **one-step-ahead innovations** `e_t = R_t − R̂_t|t−1` are approximately white if the fit is adequate (verified by Ljung–Box on `e_t`; if it still rejects, escalate to full SARIMA and lower `statistical_confidence`).
3. **Heteroscedasticity-aware scaling.** Standardize innovations with a time-varying scale: `σ̂²_t = λ·σ̂²_{t−1} + (1−λ)·e²_{t−1}` (EWMA, λ=0.94, RiskMetrics-style), floored by a day-of-week-stratified MAD (promo/weekend variance clustering). Score: `z_t = e_t / σ̂_t`.
4. **Decision rules.** Point anomaly: `|z_t| ≥ 3` with **Benjamini–Hochberg FDR control (q=0.05)** across the daily KPI×segment scan (we test many series; uncorrected thresholds guarantee false alarms). Level shift / slow drift: **CUSUM** (and PELT changepoint as cross-check) with a persistence requirement (≥ 3 days) so one bad day ≠ regime change.
5. **Materiality gate (both required).** Statistical trigger AND business impact: `impact = Σ_window (y_t − ŷ_t^cf)` vs. the contract's `min_abs_impact_inr` / `min_pct_move`, where `ŷ^cf` is the counterfactual baseline (module E). Priority = f(₹ impact, KPI tier, persistence, downstream-KPI centrality in the driver DAG).

**B. Decomposition — exact algebra before any estimation.**

- **Bennet price–volume–mix**: for segments `i`, `ΔR = Σ_i [ Δp_i · (q_i⁰+q_i¹)/2 + Δq_i · (p_i⁰+p_i¹)/2 ]` — additive, symmetric, no leftover interaction term. Volume is further split into within-segment volume vs. **mix** (share-shift) effects.
- **Dimensional contribution scan** (Adtributor-style): for each contract dimension, each member's share of Δ vs. its expected share; surprise scored, concentration detected ("North region = 79 % of the gap").
- Output: a contribution table with exact arithmetic — this alone answers "how much," before any model answers "why."

**C. Driver estimation — rigorous inference for the "why."**

- **Specification.** Dynamic regression on the log scale: `log y_t = α + Σ_k β_k · x_{k,t} + γ'·calendar_t + δ·t + u_t`, where `x_k` includes: `log(price_index_t)` (⇒ β = elasticity), **adstocked marketing** `A_t = spend_t + λ_ad·A_{t−1}` with `λ_ad = 0.5^(1/half_life)` (half-life from contract prior, profiled over a small grid), fill-rate (contract lag window), holiday/promo dummies, Fourier seasonal terms.
- **Estimation & inference, two ways (deliberately):**
  - *Primary:* **SARIMAX with exogenous regressors** — models `u_t`'s autocorrelation explicitly → efficient estimates and honest CIs.
  - *Robustness check:* **OLS with Newey–West HAC standard errors**, lag `L = ⌊4(T/100)^{2/9}⌋` — consistent inference under remaining autocorrelation *and* heteroscedasticity with minimal assumptions.
  - Coefficient agreement between the two (sign + magnitude within tolerance) feeds `evidence_agreement`; divergence lowers confidence and surfaces both estimates to the analyst persona.
- **Diagnostics reported, not hidden** (all feed the confidence score): Ljung–Box (residual autocorrelation), **Breusch–Pagan / White** (heteroscedasticity → justifies HAC), Durbin–Watson, VIF (collinearity — collinear spend channels are attributed as a *group* with a note, never falsely separated), out-of-sample MAPE on a holdout tail.
- **Causal discipline.** The contract's driver DAG defines admissible regressors per estimand — e.g., when estimating marketing→revenue *total* effect, volume is a mediator and is **excluded** (conditioning on it would block the effect). Discrete events (price change, outage) additionally get an **event-study / interrupted-time-series** estimate using unaffected regions as controls where available. Placebo refutations (shift the event date; effect should vanish) are a stretch goal, flagged in §6.3.
- **Reconciling B and C:** identity decomposition fixes the arithmetic split (price/volume/mix); the regression attributes the *volume* component to its causes (availability, marketing, price-elasticity response, seasonality residual). Attribution table = algebra layer + econometric layer + unexplained remainder (honestly labeled).

**D. Baselines, counterfactuals, sparse history.**

- Counterfactual `ŷ^cf` = model prediction with anomalous drivers held at baseline paths; impact intervals from forecast-error variance.
- **Sparse-history policy (contract-driven):** below `min_history` (e.g., 28 daily points), no STL/SARIMAX. Instead **empirical-Bayes pooling**: expected path = category launch-curve (median trajectory over the last N comparable launches, aligned on launch day) × the new product's observed early-velocity ratio; uncertainty band from cross-launch quantiles, inflated for `n`. Only guardrail (band-breach) checks are allowed; full stats unlock at graduation thresholds. The engine says *why* it is less sensitive (§5.3).

**E. Confidence & abstention.**

```
confidence = Π_k pillar_k ^ w_k        (weighted geometric mean, Σw = 1)

pillar                    measured from
─────────────────────────────────────────────────────────────────────
data_confidence           freshness vs SLA, DQ pass rate, coverage,
                          restatement-window exposure
statistical_confidence    diagnostics p-values, CI widths, VIF,
                          holdout MAPE, n vs min_history
explanation_coverage      |explained Δ| / |total Δ|
evidence_agreement        SARIMAX↔HAC agreement, decomposition↔regression
                          consistency, cross-source reconciliation
```

Hard gates override the composite: any pillar < 0.35, or freshness SLA breach on a required source, forces **ABSTAIN**. Bands: ≥ 0.75 publish with actions · 0.50–0.75 publish hedged, alternative hypotheses, no auto-actions · < 0.50 abstain with a structured "what's missing + when we retry" artifact. Calibration is *evaluated* (reliability curve vs. eval-suite correctness, §6.5), not asserted.

**F. Action recommender.** Deterministic matcher over a YAML **action catalog**: entries keyed by driver, with preconditions (checked against live data), constraints, expected-impact formulas parameterized by the *estimated* elasticities/recovery rates with CIs, owner from the contract's decision-rights matrix, and a monitoring plan (KPI, checkpoint dates, success threshold, auto-follow-up). Output exactly as the brief specifies: **driver → controllable lever → action → expected impact → owner → confidence → monitoring plan**. The LLM may rephrase; it cannot add, drop, or renumber actions.

### 3.3 The LLM / non-LLM boundary — explicit map

| # | Pipeline step | Engine | Why this engine | Failure containment |
|---|---|---|---|---|
| 1 | Ingestion, conformance, calendar/grain alignment | SQL + Python | Determinism, replayability, audit | DQ gates quarantine bad loads |
| 2 | Freshness & data-quality scoring | Python rules | Objective, thresholded | Feeds hard abstention gate |
| 3 | KPI calculation & every data query | **Contract-to-SQL compiler** | One definition of truth; RBAC enforced in-query | LLM cannot emit SQL, only contract references |
| 4 | Anomaly detection & changepoints | statsmodels / NumPy | Valid under autocorrelation & heteroscedasticity | FDR control; persistence rules |
| 5 | Materiality & prioritization | Business rules from contract | Governance owns thresholds | Thresholds editable without code |
| 6 | PVM & contribution decomposition | NumPy (exact algebra) | Arithmetic identity — nothing to hallucinate | Sums checked to equal total Δ |
| 7 | Driver estimation, elasticities, counterfactuals | statsmodels (SARIMAX + HAC-OLS) | Honest CIs, diagnostics | Dual-method agreement scored |
| 8 | Confidence scoring & abstention | Deterministic formula | Reproducible, calibratable | Hard gates non-overridable by LLM |
| 9 | Action selection | Rule engine over catalog | Decision rights, safety | Closed world: catalog-only |
| 10 | Intent parsing (NL → intent JSON) | **LLM (small)** | Language flexibility | JSON-schema validation; unknown KPI → clarify |
| 11 | Context retrieval & relevance ranking | BM25+embeddings; **LLM re-rank** | Semantic matching of memos/incidents | Snippets quoted verbatim with doc IDs |
| 12 | Narrative synthesis per persona | **LLM (mid)** | Fluent, audience-tuned prose | **Numeric verifier** + citation check + template fallback |
| 13 | Post-narrative numeric fact-check | Deterministic (regex + normalization vs bundle) | Enforcement of P1 | Regenerate ≤ 2, else template |
| 14 | Feedback classification | **LLM (small)** | Cheap NLU | Human-visible labels; corrections stored raw |
| 15 | Learning-loop parameter updates | Deterministic jobs + eval gates | Auditability | Golden-set regression must pass |

**One-line summary for the judges:** *rows 10, 11 (partially), 12, 14 are the only LLM rows — and row 13 exists so that row 12 can never lie about a number.*

### 3.4 Capability classification (per the brief's requirement)

| Capability | Classification |
|---|---|
| Ingestion, semantic contracts, compiler, analytical engine, confidence, actions, verifier, telemetry, UI | **Custom-built** (Python OSS: DuckDB, statsmodels, pydantic, FastAPI, Streamlit) |
| LLM inference (Anthropic/OpenAI API; Ollama local fallback) | **Externally integrated** |
| Embeddings/BM25 retrieval (sentence-transformers / rank-bm25) | **Custom-built on OSS** |
| Production path: swap DuckDB adapter for Snowflake/Databricks SQL; contracts → dbt Semantic Layer / Unity Catalog metadata; RLS → warehouse-native policies | **Configured / native** (future phase, §11) |

---

## 4. The KPI Semantic Contract

One YAML file per governed metric, validated by a pydantic schema (`contracts/schema.py`), versioned in git. Contracts are **executable governance**: the compiler builds SQL from `calculation` + caller entitlements from `access`; the engine reads `drivers`, `materiality`, `confidence_policy`, `sparse_history_policy`; the UI renders `lineage` and `definition`. The three headline KPIs below deliberately differ in **cadence (daily / weekly / daily-with-48 h-lag), grain, and quality profile**, and are **connected** through the driver DAG (`fill_rate` and `marketing_spend` are upstream drivers of `net_revenue`). Two supporting metrics (`unit_volume`, `marketing_spend`) get slim contracts of the same shape (omitted here for space, included in the repo).

### 4.1 Contract 1 — Net Revenue (daily, high-quality source)

```yaml
# contracts/net_revenue.yaml
contract_version: "1.2.0"
kpi:
  id: net_revenue
  name: "Net Revenue"
  tier: 1                                  # materiality weighting & alert priority
  business_owner: "CFO Office"
  data_steward: "analytics-eng"
  description: >
    Recognised product revenue net of returns and discounts,
    excluding taxes and shipping. Currency: INR.

definition:
  base_grain: [date, product_sku, region, channel]
  default_reporting_grain: [date]
  calendar: fiscal_apr_mar                 # Indian FY; ISO weeks for weekly rollups
  unit: INR
  aggregation: sum                         # additive across all dims
  null_policy: "no sales row = 0 revenue; unknown dim member -> 'UNKNOWN' + DQ flag"

calculation:
  measure_sql: "SUM(units * unit_price_net) - SUM(returns_value)"
  source_view: gold.fct_revenue_daily
  derived_submetrics:
    asp:         "SUM(units * unit_price_net) / NULLIF(SUM(units),0)"
    unit_volume: "SUM(units)"

sources:
  - source_id: salesops_db
    system: "SalesOps transactional DB (simulated Postgres)"
    refresh_cadence: "daily 02:00 IST"
    expected_latency_hours: 4
    history_months: 24
    quality_tier: high
    restatement_window_days: 0

lineage:
  - {step: land,    from: salesops_db.orders,      to: bronze.orders_raw,      transform: loaders/sales.py}
  - {step: land,    from: salesops_db.returns,     to: bronze.returns_raw,     transform: loaders/sales.py}
  - {step: conform, from: bronze.orders_raw,       to: silver.sales_conformed, transform: sql/t_sales_conform.sql}
  - {step: mart,    from: silver.sales_conformed,  to: gold.fct_revenue_daily, transform: sql/t_fct_revenue.sql}

drivers:
  identity:                                # exact Bennet decomposition roles
    - {id: asp,    role: price}
    - {id: volume, role: quantity}
    - {id: mix,    role: mix, over: [product_sku, region]}
  exogenous:                               # econometrically estimated
    - id: fill_rate
      kpi_ref: order_fill_rate             # cross-contract edge (leading indicator)
      direction: positive
      lag_days: [0, 7]
      controllable: true
      lever: replenishment
      elasticity_prior: {mean: 0.5, sd: 0.2}   # pp revenue per pp fill-rate
    - id: marketing_adstock
      kpi_ref: marketing_spend
      direction: positive
      lag_days: [0, 21]
      adstock_half_life_days: 7
      controllable: true
      lever: media_budget
      elasticity_prior: {mean: 0.15, sd: 0.10}
    - id: price_index
      direction: negative
      controllable: true
      lever: pricing
      elasticity_prior: {mean: -0.8, sd: 0.3}
    - {id: holiday_promo_calendar, direction: contextual, controllable: false}
    - {id: competitor_price_index, direction: contextual, controllable: false, coverage: partial}

materiality:
  statistical:
    method: stl_ar_innovation
    z_threshold: 3.0
    fdr_q: 0.05
    shift_persistence_days: 3
  business:
    min_abs_impact_inr: 1000000            # ₹10 lakh vs counterfactual
    min_pct_move: 2.0
  priority_formula: "abs(impact_inr) * tier_weight * persistence_factor"

confidence_policy:
  min_history_days_full_stats: 28
  abstain_below: 0.50
  hedge_below: 0.75
  hard_gates: {any_pillar_min: 0.35, required_sources_fresh: true}

access:
  classification: internal_financial
  roles:
    cfo:            {rows: all, columns: all}
    analyst_full:   {rows: all, columns: all}
    rsm:            {rows: "region = :user_region",
                     columns: {mask: [margin_pct, discount_depth]},
                     national_headline: summary_only}
    marketing_lead: {rows: all, columns: {mask: [margin_pct]}}
    intern:         {deny: true, reason: "Tier-1 financial KPI — request access from data_steward"}
  audit: {log_queries: true, log_narratives: true, retention_days: 365}

actions_ref: catalogs/actions_revenue.yaml
monitoring:
  freshness_sla_hours: 30
  drift_checks: {input_psi_monthly: 0.2, coefficient_stability_refit_days: 30}
sparse_history_policy:
  method: hierarchical_pool
  pool_by: [category, region]
  guardrail_only_below_n: 28
  graduation: {full_stats_n: 28, weekly_seasonality_n: 56}
```

### 4.2 Contract 2 — Blended ROAS (weekly, cross-source, restated)

```yaml
# contracts/blended_roas.yaml
contract_version: "1.1.0"
kpi:
  id: blended_roas
  name: "Blended Marketing ROAS"
  tier: 2
  business_owner: "CMO Office"
  data_steward: "marketing-analytics"
  description: "Marketing-attributed net revenue per unit of marketing spend, blended across channels."

definition:
  base_grain: [iso_week, channel]
  default_reporting_grain: [iso_week]
  calendar: iso_week
  unit: ratio
  aggregation: weighted            # ratio metric: aggregate numerator & denominator separately
  ratio_of: {numerator: attributed_net_revenue, denominator: marketing_spend}
  null_policy: "missing spend week -> KPI undefined for week (never imputed silently); DQ flag"

calculation:
  measure_sql: "SUM(attributed_revenue_inr) / NULLIF(SUM(spend_inr),0)"
  source_view: gold.fct_marketing_weekly

sources:
  - source_id: martech_export
    system: "MarTech platform weekly CSV/Parquet drop (simulated API export)"
    refresh_cadence: "weekly Mon 06:00 IST"
    expected_latency_hours: 8
    history_months: 12
    quality_tier: medium
    restatement_window_days: 14          # last 2 weeks revised on each drop
    known_issues: [occasional_missed_week, attribution_lag]
  - source_id: salesops_db               # numerator cross-check
    role: reconciliation
    tolerance_pct: 5.0                   # attributed vs order-linked revenue

lineage:
  - {step: land,    from: martech_export.weekly_files, to: bronze.martech_raw,       transform: loaders/martech.py}
  - {step: conform, from: bronze.martech_raw,          to: silver.spend_conformed,   transform: sql/t_spend_conform.sql}
  - {step: blend,   from: [silver.spend_conformed, silver.sales_conformed],
                    to: gold.fct_marketing_weekly,     transform: sql/t_fct_marketing.sql}

drivers:
  identity:
    - {id: attributed_revenue, role: numerator}
    - {id: spend,              role: denominator}
    - {id: channel_mix,        role: mix, over: [channel]}
  exogenous:
    - {id: creative_refresh_flag, direction: contextual, controllable: true, lever: creative_ops}
    - {id: cpm_index,             direction: negative,   controllable: false}
    - {id: promo_calendar,        direction: contextual, controllable: false}

materiality:
  statistical: {method: stl_ar_innovation, z_threshold: 2.5, fdr_q: 0.05, shift_persistence_weeks: 2}
  business:    {min_pct_move: 10.0, min_spend_at_risk_inr: 500000}

confidence_policy:
  min_history_weeks_full_stats: 12
  abstain_below: 0.50
  hard_gates:
    any_pillar_min: 0.35
    required_sources_fresh: true
    reconciliation_within_tolerance: true      # numerator cross-check must pass
    no_open_restatement_on_flagged_weeks: true # movements inside restatement window
                                               # can be described but not attributed

access:
  classification: internal_marketing
  roles:
    cfo:            {rows: all, columns: all}
    marketing_lead: {rows: all, columns: all}
    analyst_full:   {rows: all, columns: all}
    rsm:            {deny: true, reason: "Marketing domain entitlement required"}
    intern:         {deny: true, reason: "Marketing domain entitlement required"}
  audit: {log_queries: true, log_narratives: true, retention_days: 365}

actions_ref: catalogs/actions_marketing.yaml
monitoring: {freshness_sla_hours: 56, drift_checks: {input_psi_monthly: 0.25}}
sparse_history_policy: {method: channel_pool, guardrail_only_below_n: 8}
```

### 4.3 Contract 3 — Order Fill Rate (daily, 48 h lag, leading indicator)

```yaml
# contracts/order_fill_rate.yaml
contract_version: "1.0.2"
kpi:
  id: order_fill_rate
  name: "Order Fill Rate"
  tier: 2
  business_owner: "COO Office"
  data_steward: "supply-analytics"
  description: "Units shipped complete & on time / units ordered. Leading driver of net_revenue."

definition:
  base_grain: [date, warehouse, product_sku]
  default_reporting_grain: [date, region]      # warehouse -> region via conformed dim
  calendar: gregorian
  unit: percent
  aggregation: weighted                        # weighted by units ordered
  ratio_of: {numerator: units_shipped_ok, denominator: units_ordered}
  null_policy: "no orders -> undefined (excluded from aggregates)"

calculation:
  measure_sql: "SUM(units_shipped_ok) / NULLIF(SUM(units_ordered),0)"
  source_view: gold.fct_fulfillment_daily

sources:
  - source_id: supply_erp_extract
    system: "SupplyChain ERP nightly extract (simulated)"
    refresh_cadence: "daily 05:00 IST"
    expected_latency_hours: 48                 # data for day T lands T+2
    history_months: 18
    quality_tier: medium
    known_issues: [occasional_gap_days]

lineage:
  - {step: land,    from: supply_erp_extract.shipments, to: bronze.shipments_raw,       transform: loaders/supply.py}
  - {step: conform, from: bronze.shipments_raw,         to: silver.fulfillment_conformed, transform: sql/t_fulfill_conform.sql}
  - {step: mart,    from: silver.fulfillment_conformed, to: gold.fct_fulfillment_daily,  transform: sql/t_fct_fulfillment.sql}

drivers:
  downstream_of: []                            # root cause territory
  feeds: [{kpi_ref: net_revenue, lag_days: [0, 7]}]   # cross-contract DAG edge
  exogenous:
    - {id: inventory_days_cover, direction: positive, controllable: true,  lever: replenishment}
    - {id: warehouse_incidents,  direction: negative, controllable: true,  lever: ops_escalation, source: context_store}
    - {id: inbound_delay_days,   direction: negative, controllable: false}

materiality:
  statistical: {method: stl_ar_innovation, z_threshold: 3.0, fdr_q: 0.05, shift_persistence_days: 2}
  business:    {min_abs_move_pp: 3.0, escalate_if_below_pct: 90.0}

confidence_policy:
  min_history_days_full_stats: 28
  abstain_below: 0.50
  hard_gates: {any_pillar_min: 0.35, lag_awareness: "insights labeled 'as of T-2' when latency binds"}

access:
  classification: internal_operations
  roles:
    cfo:          {rows: all, columns: all}
    analyst_full: {rows: all, columns: all}
    rsm:          {rows: "region = :user_region", columns: all}
    intern:       {rows: all, columns: {mask: [supplier_name]}, note: "aggregate views only"}
  audit: {log_queries: true, log_narratives: true, retention_days: 365}

actions_ref: catalogs/actions_supply.yaml
monitoring: {freshness_sla_hours: 72, drift_checks: {input_psi_monthly: 0.2}}
sparse_history_policy: {method: warehouse_pool, guardrail_only_below_n: 28}
```

### 4.4 Persona style cards & action catalog (excerpts)

```yaml
# personas/cfo.yaml
persona: cfo
tone: "board-ready, impact-first, no method jargon"
max_length_sentences: 6
must_include: [inr_impact, top_drivers_max_3, confidence_band, decisions_awaiting_signoff]
number_format: "₹ lakh/crore, one decimal"
channel: [workspace_card, weekly_email_digest]
action_visibility: "only actions requiring exec decision rights"

# personas/analyst.yaml
persona: analyst
tone: "technical, complete, reproducible"
must_include: [method_spec, coefficients_with_ci, diagnostics_table,
               decomposition_table, lineage_links, unexplained_share]
channel: [workspace_full, notebook_export]
action_visibility: all
```

```yaml
# catalogs/actions_revenue.yaml (excerpt)
- action_id: expedite_replenishment
  trigger_driver: fill_rate
  lever: replenishment
  preconditions:
    - "stockout_confirmed == true"
    - "alt_dc_inventory_units >= 0.6 * lost_units_estimate"
  action: "Expedite transfer of affected SKUs from alternate DC; prioritise top lost-revenue SKUs"
  expected_impact_formula: "recovery_rate * lost_revenue_estimate"   # recovery_rate: est. 0.6 [0.45,0.75]
  owner: supply_ops_lead
  approval_required_above_inr: 2000000        # decision right: CFO sign-off
  monitoring_plan: {kpi: order_fill_rate, target: ">= 95%", checkpoints_days: [3, 7, 14], auto_followup: true}

- action_id: restore_media_baseline
  trigger_driver: marketing_adstock
  lever: media_budget
  preconditions: ["spend_vs_baseline_pct <= -25", "roas_last4w >= breakeven"]
  action: "Restore paid-social spend to trailing-8-week baseline"
  expected_impact_formula: "spend_gap * marketing_elasticity"        # CI propagated from regression
  owner: marketing_lead
  monitoring_plan: {kpi: net_revenue, lag_note: "expect effect with 1–2 wk adstock lag", checkpoints_days: [7, 14, 21]}

- action_id: price_review
  trigger_driver: price_index
  lever: pricing
  action: "Convene pricing review with observed elasticity evidence (recommend-only: engine holds no pricing decision rights)"
  owner: pricing_committee
  monitoring_plan: {kpi: [net_revenue, unit_volume], checkpoints_days: [14, 28]}
```

---

## 5. Scenario Walkthroughs

Each scenario below is a **scripted demo asset**: the synthetic-data generator plants the ground truth (§6.2), the pipeline trace shows exactly which module fires and why, and the narratives are the target outputs the prototype must reproduce. All numbers are internally consistent and become golden-test fixtures.

### 5.1 Scenario A — Multi-factor KPI movement (the centerpiece)

**Planted ground truth (week of Mon 9 Mar 2026, Net Revenue):**

| Planted event | Start | Mechanism in simulator |
|---|---|---|
| Warehouse WH-North conveyor outage | 6 Mar | Fill rate North 96.2 % → 81.4 % on top-3 SKUs |
| Paid-social spend cut −40 % | 24 Feb | Hits demand with 7-day-half-life adstock lag |
| Price +6 % on Category A (≈45 % of revenue) | 1 Mar | Elasticity −0.8 applied in demand model |
| (Background) mid-March seasonality mildly positive | — | Makes the drop *more* anomalous, not less |

**Pipeline trace (proactive mode, after the 02:00 sales load):**

1. **Detect.** Daily innovations go negative from 6 Mar; weekly rollup: actual ₹60.8 M vs counterfactual ₹69.4 M → **gap −₹8.6 M (−12.4 %)**. Innovation z = −4.2 (BH-adjusted p < 0.001, survives FDR across the 3 KPI × 4 region scan); **CUSUM confirms a level shift dated 6 Mar** with 4-day persistence → not a one-day blip.
2. **Materiality.** Statistical gate ✓; business gate ✓ (|−₹8.6 M| ≫ ₹10 lakh threshold); Tier-1 KPI, high persistence → **Priority P1 (Critical)**.
3. **Freshness/DQ.** SalesOps fresh (loaded 02:07); Supply data lagged 48 h as per SLA (labeled "as of 13 Mar"); MarTech inside restatement window but flagged weeks not implicated → `data_confidence = 0.92`.
4. **Decompose (exact algebra).** Bennet PVM + regional scan: North region carries **79 %** of the gap; top-3 SKUs identified; gross price effect +2.7 pp; volume −14.6 pp; mix −0.4 pp (sums to −12.4 pp with rounding, checked programmatically).
5. **Driver estimation.** SARIMAX-exog on log revenue: fill-rate coefficient ⇒ **each 1 pp fill-rate loss ≈ 0.47 pp weekly revenue (95 % CI 0.31–0.63)** → 14.8 pp × 0.47 ≈ −7.0 pp ✓ matches planted effect. Adstocked-spend elasticity 0.15 (CI 0.09–0.21) → 40 % cut, lag-weighted ⇒ −4.0 pp. Price term: gross +2.7 pp, elasticity-induced volume −2.2 pp ⇒ **net +0.5 pp** — price rise is currently *helping*, not hurting. Diagnostics: Ljung–Box p = 0.31 ✓ (residuals whitened), **Breusch–Pagan p = 0.04 → heteroscedasticity present → HAC cross-check invoked**: OLS + Newey–West coefficients agree with SARIMAX within 8 % → `evidence_agreement = 0.86`. VIF max 2.9 ✓.
6. **Attribution table (final):**

   | Driver | Contribution | ₹ | Method |
   |---|---|---|---|
   | Fill rate (WH-North outage) | **−7.1 pp** | −₹4.93 M | SARIMAX + event study (control: unaffected regions) |
   | Marketing adstock (24 Feb cut) | **−4.0 pp** | −₹2.78 M | SARIMAX, adstock λ from profile fit |
   | Net price effect (+6 % Cat A) | **+0.5 pp** | +₹0.35 M | Bennet + elasticity |
   | Mix shift | −0.4 pp | −₹0.28 M | Bennet |
   | Unexplained | −1.4 pp | −₹0.97 M | labeled honestly |
   | **Total** | **−12.4 pp** | **−₹8.61 M** | sums verified |

   `explanation_coverage = 0.89`.
7. **Retrieval.** Context store surfaces: ops incident *"WH-N conveyor failure, ticket OPS-2214, 5 Mar 22:40"* [E4]; pricing memo *"Cat A list-price revision eff. 1 Mar"* [E5]; media plan note *"paid-social pause pilot from 24 Feb"* [E6] — quoted verbatim with doc IDs.
8. **Confidence.** data 0.92 · statistical 0.81 · coverage 0.89 · agreement 0.86 → **composite 0.86 → HIGH** → publish with actions.
9. **Actions (catalog-matched).** `expedite_replenishment` (preconditions pass: alternate DC holds 72 % of lost-unit estimate) — expected recovery **₹5.2 M ± 1.1 M over 2 weeks**, owner Supply Ops Lead, **CFO sign-off required (> ₹20 lakh)**, monitoring: fill rate ≥ 95 % by day 7. `restore_media_baseline` — expected **+₹2.1 M with 1–2 wk lag**, owner Marketing Lead. `price_review` — recommend-only, owner Pricing Committee.

**Generated narrative — CFO persona (target output):**

> Net Revenue for w/c 9 Mar came in at **₹6.08 Cr — ₹86 lakh (−12.4 %) below the expected ₹6.94 Cr** [E1]. Confidence: **HIGH (0.86)**. Three drivers explain 89 % of the gap: the WH-North conveyor outage cut regional fill rate to 81.4 %, costing **−₹49 lakh** [E2][E4]; the 24 Feb paid-social cut is now landing with its expected two-week lag, **−₹28 lakh** [E3][E6]; the 1 Mar Category-A price increase is *net positive* so far (**+₹3.5 lakh** — volume response within assumed elasticity) [E5]. **Awaiting your sign-off:** expedited replenishment from WH-West, est. recovery **₹52 lakh ± 11 lakh** over two weeks (owner: Supply Ops). Marketing restore is within the CMO's delegation. Full evidence attached.

**Generated narrative — Analyst persona (same bundle, different card):**

> Detection: STL(robust) + AR(2) innovations, z = −4.2, BH-FDR q = 0.05; CUSUM shift dated 6 Mar (persistence 4 d). Attribution: SARIMAX(1,0,1)-exog on log revenue; fill-rate β = 0.47 pp/pp [0.31, 0.63]; adstock elasticity 0.15 [0.09, 0.21], λ = 0.5^(1/7); price elasticity −0.80 [−1.05, −0.55]. Diagnostics: LB p = 0.31 ✓, BP p = 0.04 → HAC(NW, L=4) cross-check: max coefficient divergence 8 % ✓, VIF ≤ 2.9. Event study vs. unaffected regions confirms outage effect (placebo pending). Unexplained residual −1.4 pp. Full decomposition table, residual plots, and lineage: [links]. Flag disagreements via the feedback control — corrections retrain thresholds nightly.

### 5.2 Scenario B — Low confidence → abstention

**Planted degradation (week of 13 Apr 2026, Blended ROAS):** apparent **+22 %** ROAS jump, but (a) MarTech missed its Monday drop — **spend data 9 days stale**, inside the 14-day restatement window; (b) the attribution reconciliation DQ check fails: campaign-attributed revenue vs. order-linked revenue diverges **18 %** (tolerance 5 %); (c) with the stale denominator, Bennet says channel-mix drove the jump while the regression assigns it a *negative* sign — cross-method disagreement (VIF 8.2 on collinear channel spends).

**Pipeline trace:**

1. Detection fires on the +22 % move (z = 3.4) — detection itself is *not* suppressed.
2. Hard gates evaluate: `required_sources_fresh` **FAIL** (9 d > 56 h SLA); `reconciliation_within_tolerance` **FAIL** (18 % > 5 %).
3. Pillars: data 0.31 · statistical 0.55 · coverage 0.61 · agreement 0.40 → composite 0.44; **two hard gates + composite < 0.50 → ABSTAIN** (either alone suffices).
4. Engine emits a structured **Abstention Artifact**: `{observed_move, known_facts, failed_checks[], missing_evidence, retry_trigger, eta}` — and schedules an automatic re-run on the next MarTech load event. **No driver claims, no actions are generated** — the action recommender is gated off.

**Generated narrative — CMO/exec persona:**

> **Insight withheld for Blended ROAS (w/c 13 Apr).** The metric *appears* up 22 %, but the marketing spend feed is 9 days stale and this week's attributed revenue fails reconciliation against order data by 18 % (tolerance 5 %) [E1][E2]. Publishing a driver story now would risk a false narrative — the apparent jump may be a denominator artifact of the pending restatement. **What we do know:** order-linked revenue (the numerator) is fresh and tracking normally [E3]. Next MarTech drop expected tonight 06:00; analysis will auto-rerun and publish by 07:00. — *You can override and view the low-confidence draft; the override is logged.*

**Analyst addendum:** failed-check detail, both conflicting estimates shown side-by-side with the VIF note, and a one-click "notify me on re-run."

*Design point for judges: abstention is not an error state — it has its own UI card, its own artifact schema, an ETA, and an audit trail. The engine also distinguishes "data too weak to attribute" (this case) from "ambiguous question" (intent parser asks a clarifying question instead — shown in the conversational demo).*

### 5.3 Scenario C — Sparse history: newly launched product

**Setup:** Product **"Aurora X"** launched 18 days ago (contract minimum for full stats: 28). Day-18 (a Monday) revenue ₹4.12 lakh, **−31 % day-over-day** — a naive detector would scream.

**Pipeline trace:**

1. Contract's `sparse_history_policy` intercepts: n = 18 < 28 → **STL/SARIMAX path disabled** (cannot estimate weekly seasonality from 2.5 cycles, let alone trend). This routing decision is itself logged and shown.
2. **Empirical-Bayes pooled baseline:** median launch curve from the last 12 Category-B launches, aligned on launch day, scaled by Aurora's week-1 velocity ratio (**1.42×** category median); 80 % band from cross-launch quantiles, inflated for n = 18.
3. Day-18 expected band: **₹3.80 L – ₹6.40 L** → actual ₹4.12 L is **inside the band**. Supporting evidence: 9 of 12 comparable launches show a days-15–20 dip (launch-promo expiry pattern); category Monday index = **0.78×**; cross-sectional check — Aurora's other regions moved in the same proportion (coherent, not a local failure).
4. Verdict: **no anomaly — expected launch dynamics.** Confidence **0.61 (MEDIUM)** with the uncertainty driver named explicitly (`n=18`, pooled prior). Guardrail monitoring continues; graduation: full stats at day 28, weekly-seasonality modeling at day 56.

**Generated narrative — RSM persona:**

> Aurora X posted ₹4.12 L on Monday, down 31 % from Sunday. **This is within the expected range** [₹3.8 L–₹6.4 L] for day 18 of a Category-B launch: 9 of the last 12 comparable launches dipped in days 15–20 as launch promos expire, Mondays run at 0.78× weekly average, and all regions moved proportionally [E1–E3]. Aurora is still tracking **1.42×** the category launch curve. Confidence is MEDIUM (0.61) — with only 18 days of history the engine is deliberately less sensitive here; standard anomaly detection switches on at day 28. **Action:** none required; guardrail monitoring continues with a scheduled day-28 review.

*Design point: the engine demonstrates restraint with a reasoned baseline — the opposite failure mode (alert-spamming a launch team) is what erodes trust fastest.*

### 5.4 Scenario D — Role-based security & entitlement (brief minimum)

**Same question, three users — "Why did revenue drop last week?":**

| User | What the compiler does | What they see |
|---|---|---|
| CFO | No filters | Full national picture (Scenario A card) |
| RSM-North (`:user_region = North`) | Injects `region='North'` row filter; masks `margin_pct`, `discount_depth`; national figure summary-only | North-scoped decomposition (their outage, their actions); asks "what was the margin impact?" → *"Margin detail is masked for your role [policy: internal_financial]; your data steward can grant access"* |
| Intern | Contract `deny` rule | Refusal with reason + request-access path; **the denial itself is logged** |

Additionally, RSM asking about **Blended ROAS** hits the *domain* entitlement (`rsm: deny` in contract 2) — demonstrating row-, column- **and** domain-level control from the same policy block. The audit log shows, for each interaction: user, role, intent JSON, compiled SQL hash, contract version, rows returned, model calls, narrative ID — the auditability story in one screen.

---

## 6. Prototype Build Plan

### 6.1 Stack & repository layout

**Stack:** Python 3.11 · DuckDB (warehouse) · pandas/NumPy/SciPy · statsmodels (STL, SARIMAX, HAC, diagnostics) · ruptures (changepoints) · pydantic v2 (contracts, bundles, intents) · rank-bm25 + sentence-transformers (retrieval) · FastAPI (services) · Streamlit (workspace) · pytest (evals) · LLM: Anthropic or OpenAI API via a thin provider-agnostic client, **Ollama (llama3.1-8b) as offline fallback**.

```
prism/
├── contracts/            # KPI YAML contracts + schema.py (pydantic) + validation CLI
├── personas/             # persona style cards (YAML)
├── catalogs/             # action catalogs (YAML)
├── datagen/
│   ├── world.py          # structural demand simulator (the "world model")
│   ├── scenarios/        # multi_factor.yaml, abstention.yaml, sparse_launch.yaml, distractors.yaml
│   ├── exporters.py      # source-system warts: weekly aggregation, restatements, 48h lag, gaps
│   └── ground_truth.py   # counterfactual replays -> ground-truth ledger (eval targets)
├── ingest/               # bronze/silver/gold loaders + SQL transforms + freshness tracker
├── quality/              # DQ checks (volume, nulls, ranges, reconciliation) -> dq_results
├── engine/
│   ├── detect.py         # STL + AR innovations + EWMA scale + CUSUM/PELT + BH-FDR
│   ├── decompose.py      # Bennet PVM + dimensional contribution scan (sum-checked)
│   ├── drivers.py        # SARIMAX-exog + OLS-HAC cross-check, adstock, event study, diagnostics
│   ├── baseline.py       # forecasts, counterfactuals, EB launch-curve pooling
│   ├── confidence.py     # pillar computation, gates, composite, abstention artifact
│   ├── actions.py        # catalog matcher (preconditions, impact formulas, decision rights)
│   └── bundle.py         # InsightEvidenceBundle assembler (typed, serialized, hashed)
├── llm/
│   ├── intent.py         # NL -> intent JSON (schema-validated; clarify on ambiguity)
│   ├── retrieve.py       # hybrid BM25+embedding store over context docs
│   ├── narrate.py        # persona synthesis + NUMERIC VERIFIER + template fallback
│   └── router.py         # model tiers, prompt cache, semantic cache, token budgets
├── security/
│   ├── rbac.py           # identities, roles, session context
│   └── compiler.py       # contract -> SQL (row filters, masks, audit hooks)  [THE gateway]
├── api/                  # FastAPI: /insights /ask /feedback /telemetry /admin
├── ui/                   # Streamlit: feed, chat, evidence drawer, telemetry, role switcher
├── telemetry/            # stage timers, token/cost meters, run_ledger writer
├── evals/                # golden fixtures + metrics (attribution error, calibration, fidelity)
└── demo/                 # seeded demo script, pre-warmed caches, reset command
```

### 6.2 Synthetic data strategy — a structural simulator, not random noise

The demo's credibility rests on **recovering planted truth**, so the generator is a small structural model of the business (this is also the pitch's secret weapon: we can *prove* attribution accuracy).

**Latent demand model** (per SKU s, region r, day t):

```
demand[s,r,t] = base[s,r]
              · (1+g)^t                          # mild trend
              · dow[t] · annual[t] · holiday[t]  # calendar structure
              · (price[s,t]/ref_price[s])^ε      # constant-elasticity price response (ε≈−0.8)
              · (1 + β·adstock(spend[r,t]))      # marketing lift, λ_ad = 0.5^(1/7)
              · avail[s,r,t]                     # fill-rate penalty from inventory sim
              · exp(u[t]),  u[t] = φ·u[t-1] + σ[t]·η[t],  η~N(0,1)     # ★ AR(1) noise, φ=0.35
                σ[t] = σ0 · (1 + 0.5·promo[t]) · dow_vol[t]            # ★ heteroscedastic vol
```

★ We **deliberately inject autocorrelation and heteroscedasticity** so the choice of AR-innovation detection and HAC/SARIMAX inference is *visibly justified* in diagnostics — the Breusch–Pagan rejection in Scenario A is planted, honest, and explainable.

**Supply side:** a simple inventory simulation (reorder points, inbound delays) produces fill rates; scenario events (WH-North outage) override availability. **Marketing side:** channel spend paths with campaign pulses; ROAS emerges from attributed revenue (with a configurable attribution-noise term that Scenario B's reconciliation check catches).

**Source-system warts applied at export (not in the world model):** MarTech → weekly aggregation, 14-day restatement revisions, one missed week; Supply → 48 h lag, two gap days; SalesOps → clean but one duplicate-load day (DQ catch demo). **Distractor events** (a small benign promo, a one-day logistics blip below materiality) are planted so the demo can also show what the engine correctly *ignores* — specificity, not just sensitivity.

**Ground-truth ledger:** for every planted event, `ground_truth.py` re-runs the simulator with the event switched off and records the counterfactual delta → the *true* contribution. Written to `ledger.parquet`, consumed by evals. Everything seeded (`numpy.default_rng(42)`), scenario-configured via YAML, regenerable in < 60 s.

### 6.3 Milestone roadmap (M0–M6, ~3 weeks; MoSCoW-tagged for compression)

| Milestone | Days | Build | Acceptance criteria (demoable artifact) |
|---|---|---|---|
| **M0 Scaffold** (Must) | 1–2 | Repo, DuckDB, contract schema + 3 contracts + validation CLI | `prism contracts validate` green; contracts render in UI stub |
| **M1 World** (Must) | 3–5 | Simulator + scenario configs + exporters + ground-truth ledger | Seeded regen reproduces byte-identical sources; ledger contains true contributions for all planted events |
| **M2 Data spine** (Must) | 6–8 | bronze→silver→gold, freshness tracker, DQ gates, compiler v1 with RBAC | Gold marts at contract grain; Scenario B's reconciliation failure detected; RSM query returns filtered rows |
| **M3 Analytics** (Must) | 9–12 | detect / decompose / drivers / baseline / confidence | **Eval: planted drivers recovered — sign 100 %, top-3 rank order correct (Kendall τ = 1), magnitude within ±20 % rel.**; diagnostics table emitted; abstention fires on Scenario B; sparse policy routes Scenario C |
| **M4 Language** (Must) | 13–15 | bundle assembler, intent parser, retrieval, narrator + verifier + fallback, router/caches | **Numeric fidelity 100 % post-verifier on goldens**; ambiguous question → clarification; cost per insight logged; Ollama fallback works offline |
| **M5 Experience** (Must) | 16–18 | Streamlit workspace (feed, chat, evidence drawer, role switcher), audit log, telemetry page, feedback capture | All four scenarios walkable end-to-end by a non-team member following the demo script |
| **M6 Hardening** (Should) | 19–21 | Eval suite in CI, calibration curve, distractor specificity check, pitch assets, demo dry-runs, cache pre-warm | Full eval suite green twice consecutively from clean regen; 7-min demo rehearsed |
| Stretch (Could) | — | Placebo refutation tests, XGBoost challenger with divergence flag, weekly email digest render, React polish | — |

Compression to ~10 days: cut M6 to a day, drop stretch, Scenario D folded into M2's acceptance demo.

### 6.4 Runtime telemetry design

Every request carries a `run_id`; every stage runs inside an instrumented context manager writing to `run_ledger` (DuckDB):

```
run_ledger(run_id, ts, mode, kpi_id, persona, stage, wall_ms,
           engine,            -- 'sql' | 'stats' | 'llm' | 'rules'
           model, tokens_in, tokens_out, cache_hit, retries,
           cost_usd,          -- from a price table; 0 for non-LLM stages
           outcome)           -- ok | abstained | fallback | error
```

**Per-insight rollup (example, Scenario A proactive run):**

```json
{"run_id":"a41f","latency_ms":{"detect":310,"decompose":95,"drivers":1240,
 "confidence":18,"actions":22,"retrieve":85,"narrate":3420,"verify":40,"total":5230},
 "llm":{"intent":{"skipped":"proactive"},
        "narrate":{"model":"mid-tier","in":3184,"out":447,"cache_hit":false,"retries":0}},
 "cost":{"llm_usd":0.0162,"total_usd":0.0171,"inr_approx":1.5},
 "verifier":{"numbers_checked":14,"failures":0},"outcome":"ok"}
```

**Budgets & SLOs (enforced by the router):** proactive insight ≤ 30 s end-to-end (async, non-blocking); conversational answer ≤ 8–12 s p95 with streamed narrative; per-insight LLM cost cap $0.05 (breach → downshift model tier or fall back to template and *log the downgrade*). The telemetry page shows p50/p95 per stage, token totals, cache hit rate, cost per insight, and cumulative spend — live during the demo.

### 6.5 Evaluation harness (`evals/`, run in CI on every merge)

| Metric | Target | Source of truth |
|---|---|---|
| Detection precision / recall on planted events | 1.0 / 1.0 on goldens; distractors NOT flagged | ground-truth ledger |
| Attribution error: mean abs(est − true)/abs(true) | ≤ 20 % | ledger counterfactuals |
| Driver rank correlation (Kendall τ, top-3) | 1.0 | ledger |
| Confidence calibration (reliability curve, ECE) | ECE ≤ 0.10; abstains iff evidence degraded | scenario matrix incl. degraded variants |
| Narrative numeric fidelity (post-verifier) | 100 % | verifier logs |
| Citation coverage (claims with evidence refs) | ≥ 95 % | narrative linter |
| Entitlement leakage (RSM/intern probes, incl. adversarial "ignore your rules" prompts) | 0 rows | compiler audit log |
| Latency / cost budgets | §6.4 SLOs | run_ledger |

Degraded-variant fixtures (stale feeds, broken reconciliation, tiny n) are generated from the same scenario YAMLs with switches flipped — calibration is tested, not asserted.

---

## 7. Security, Governance & Audit (summary)

Row-, column-, and domain-level control live **in the contract** and are enforced **in the compiler** — below the LLM, so no prompt can bypass them (row 3 of the boundary map). Identities → roles → per-contract policies; masked columns return `MASKED` tokens the narrator renders as policy statements, never values. Sensitive context docs carry ACL tags honored by retrieval. Every query, narrative, override, denial, and model call is written to an append-only audit table keyed by `run_id`, with contract versions pinned — a regulator (or judge) can replay any insight end-to-end. Prompt-injection posture: retrieved snippets are data, not instructions (delimited, never executed as directives); the narrator's tool surface is nil; adversarial probes are part of the eval suite (§6.5).

## 8. Feedback & Learning Loop

Every insight card carries: **agree / disagree / wrong driver / too sensitive / not material** + free text. Stored raw in `feedback`; the small-model classifier structures it. A nightly learning job — always gated by the golden eval suite — applies:

1. **Threshold recalibration:** materiality/z thresholds tuned per KPI from labeled precision (too many "not material" → raise business gate; never below statistical floor).
2. **Driver prior updates:** Bayesian update of elasticity priors and driver-plausibility weights from validated attributions (priors shape ranking/tie-breaks, never override significant contrary evidence).
3. **Persona exemplars:** top-rated narratives become few-shot style exemplars per persona (content still verifier-checked every time).
4. **Drift watch:** monthly PSI on model inputs; rolling coefficient stability on refit; breaches lower `statistical_confidence` and open a review task.

Deliberately excluded at prototype scale: fine-tuning (no volume, weak auditability). The demo shows one full loop: analyst corrects Scenario A's mix attribution → nightly job → the correction visibly reflected next run.

## 9. LLM Economics & Scale Projection

| Stage | Model tier | Typical tokens (in/out) | Cost/call |
|---|---|---|---|
| Intent parse | small | 900 / 120 | ~$0.001 |
| Narrative (per persona) | mid | 3200 / 450 | ~$0.016 |
| Feedback classify | small | 400 / 60 | ~$0.0005 |

Levers, in order of impact: **semantic cache** keyed on (intent hash, data watermark, contract version) — repeated questions between refreshes cost ≈ $0; **prompt caching** of static preambles (contract summary, persona card) — ~60 % input-token reduction on providers that support it; **tiered routing** with budget-triggered downshift; **template fallback** = $0 floor. Prototype demo total: **< $2**. Projection at enterprise scale (10 000 narrated insights + 50 000 conversational queries/month, 35 % cache hit): ≈ **$700–900/month** (≈ ₹60–75 k) — roughly the cost of *one analyst-hour per day* — with per-insight cost visible on the telemetry page. All numeric analytics run on commodity CPU; the marginal cost of an insight is dominated by ~4 000 LLM tokens.

## 10. Risks & Mitigations

| Risk | L×I | Mitigation |
|---|---|---|
| LLM emits malformed JSON / flaky narrative | M×M | Schema validation + retry ≤ 2 + template fallback (demo cannot hard-fail) |
| Demo-day network/API outage | M×H | Ollama local fallback + pre-warmed semantic cache + recorded template renders |
| SARIMAX non-convergence on some slice | M×M | Automatic fallback to OLS+HAC (assumption-light path is always available), logged |
| Scenario looks "too clean" to judges | M×M | Planted distractors the engine correctly ignores; noise, gaps, restatements in-band |
| Collinear drivers → unstable attribution | M×M | VIF gate → grouped attribution + reduced confidence (never false precision) |
| Overrunning the timeline | M×H | MoSCoW milestones; M0–M5 are the demo; M6 is polish |
| Judges probe entitlements or hallucination live | L×H | That *is* the demo — adversarial probes are rehearsed (evals §6.5) |
| Confidence score mistrusted as arbitrary | M×M | Show the reliability curve + pillar breakdown in the evidence drawer |

## 11. Roadmap Beyond the Prototype

**Phase 1 (pilot, 8–12 wks):** swap DuckDB adapter for the client's warehouse (Snowflake/Databricks); contracts mapped onto dbt Semantic Layer / Unity Catalog metadata; RLS delegated to warehouse-native policies; SSO (OIDC); 10–15 KPIs, 2 business domains; shadow-mode alerts adjudicated by analysts to fit thresholds. **Phase 2 (scale):** streaming refresh triggers; knowledge-graph upgrade of the driver DAG; CausalImpact/BSTS for event effects; closed-loop action tracking (did the expedite recover the ₹52 lakh? — auto-verified by the monitoring plan); delivery to Slack/Teams/email digests. **Phase 3 (product):** cross-KPI portfolio views, what-if lever simulation from estimated elasticities, forecast-aware "pre-emptive" insights (flag the movement before month-end lands).

## 12. Traceability Matrix — brief requirement → where addressed

| Brief requirement | Section(s) |
|---|---|
| 1. Detect & prioritise material movements | §3.2-A/B, §5.1 |
| 2. Reconcile heterogeneous data + business context | §3.1 L1, §4 sources/lineage, §5.2 |
| 3. Identify & rank drivers, appropriate methods | §3.2-B/C, §5.1 |
| 4. Persona narratives + traceable evidence | §3.1 L4, §4.4, §5.1 narratives, evidence drawer §3.1 L5 |
| 5. Uncertainty + abstention | §3.2-E, §5.2 |
| 6. Actions: levers, constraints, decision rights | §3.2-F, §4.4 catalog, §5.1 step 9 |
| 7. Learns from feedback | §8 |
| 8. Security, cost, latency, scalability | §7, §6.4, §9 |
| LLM ≠ source of quantitative truth (+ why/when each method) | §3.3 boundary map, verifier §3.1 L4 |
| 3–5 KPIs, 2–3 sources, mixed grain/cadence | §4 (3 headline + 2 supporting; 3 sources + context store) |
| Semantic contract (defs, calcs, drivers, thresholds, lineage, access) | §4.1–4.3 |
| ≥ 2 personas, different narratives/actions | §1.2, §4.4, §5.1 |
| Multi-factor movement w/ known drivers | §5.1 + §6.2 ledger |
| Low-confidence clarify/abstain | §5.2 |
| Sparse-history KPI | §5.3 |
| Role-based entitlement scenario | §5.4 |
| Evidence: freshness, method, contribution, confidence, lineage | Evidence bundle §3.2, drawer §3.1 L5, §5.1 table |
| LLM vs non-LLM breakdown | §3.3 |
| Telemetry: latency, calls, tokens, cost | §6.4, §9 |
| Native / configured / custom / integrated distinction | §3.4 |
| Business proposal (framing, users, case, roadmap, risks) | §1, §10, §11 |

---

## Appendix A — 7-minute demo script (pitch aid)

1. *(60 s)* Problem + principle: "computed, never generated" — show the boundary map slide.
2. *(90 s)* Scenario A live: insight card → open evidence drawer → decomposition table sums to the gap → diagnostics (point at the Breusch–Pagan flag → "this is why HAC") → CFO vs Analyst narrative toggle.
3. *(60 s)* Approve the replenishment action → owner, expected impact CI, monitoring plan created.
4. *(60 s)* Scenario B: the engine refuses to explain ROAS — read the abstention card aloud.
5. *(45 s)* Scenario C: launch dip correctly *not* flagged; show the pooled band.
6. *(45 s)* Role switch: CFO → RSM → intern on the same question; show the audit log line.
7. *(60 s)* Telemetry page: latency, tokens, ₹1.5/insight; eval dashboard: attribution within tolerance, calibration curve, 100 % numeric fidelity.
8. *(30 s)* Roadmap + close: "the semantic contract is the asset; the engine is portable."

## Appendix B — Intent JSON schema (excerpt)

```json
{"type":"object","required":["kpi_id","time_window","comparison"],
 "properties":{
   "kpi_id":{"enum":["net_revenue","blended_roas","order_fill_rate","unit_volume","marketing_spend"]},
   "time_window":{"type":"object","properties":{"start":{"type":"string","format":"date"},
                  "end":{"type":"string","format":"date"},"grain":{"enum":["day","iso_week","month"]}}},
   "dimensions":{"type":"array","items":{"enum":["region","channel","product_sku","category","warehouse"]}},
   "filters":{"type":"object"},
   "comparison":{"enum":["vs_expected","vs_prior_period","vs_prior_year","vs_plan"]},
   "task":{"enum":["explain_movement","status","drilldown","what_should_we_do"]},
   "clarification_needed":{"type":"boolean"},
   "clarifying_question":{"type":"string"}}}
```

*Parser rule: if the utterance is ambiguous (no KPI resolvable, or conflicting windows), set `clarification_needed=true` and ask — never guess. Unknown KPI names are checked against contract aliases before failing.*

---

*Document generated as the Round 2 working blueprint. Currency figures are illustrative (₹); all scenario numbers are internally consistent and double as golden-test fixtures. Rename the system freely — the mechanism is the pitch.*




