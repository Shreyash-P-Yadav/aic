# Insight Copilot v2 — Critique, Merge Decision, and Final Build Architecture

**Accenture Innovation Challenge 2026 · Round 2 · BusinessIntelligence.ai**
Supersedes: *PRISM Round 2 Blueprint* (R2 draft) and *Insight Copilot Final Model Specification v4* (R1)
Status: **awaiting team confirmation → then hand to Claude Code for implementation**

---

## 0. Verdict, up front

**Is there anything in the Round 1 document worth taking? Yes — a great deal.** Roughly 60 % of its analytical content is stronger than what the Round 2 draft specified, and three of its ideas are the difference between a good submission and a winning one.

But the two documents fail in **opposite, complementary directions**, which is the whole reason merging them works:

| | Insight Copilot v4 (R1) | PRISM (R2 draft) |
|---|---|---|
| **Strong at** | Detection rigour, dimensional search, confidence calibration, evidence discipline, learning loop | Governance, semantic contracts, econometric driver estimation, personas, security, telemetry, cost |
| **Weak at** | *Everything the brief lists as a minimum expectation* — contracts, RBAC, personas, telemetry, cadence/grain reconciliation, price-volume-mix | Detection is naïve (fixed z-threshold), attribution search underspecified, confidence uncalibrated, no faithfulness check beyond numbers |
| **Buildability** | Unbuildable as written (~20 heavyweight dependencies, live web search, streaming infra) | Buildable in ~3 weeks |

The merge is not a compromise — the two attribution philosophies answer *different questions* and stack into a four-layer ladder no competing team will have (§4.1). The R1 calibration idea combined with the R2 synthetic-ground-truth simulator produces the single most defensible artifact in the whole submission: **a measured reliability table** instead of a claimed confidence score (§4.4).

**Naming recommendation:** keep **Insight Copilot** as the product name. If the same panel sees you again, continuity reads as maturity; a rename reads as a restart. "PRISM" becomes the internal codename for the engine, or is dropped entirely.

---

## 1. Critique of *Insight Copilot Final Model Specification v4*

### 1.1 What is genuinely strong (and better than our R2 draft)

**Conformal prediction for detection.** Ranking today's residual against a clean calibration window to get a distribution-free false-alarm rate is materially better than our fixed `z ≥ 3` rule. Business residuals are fat-tailed and skewed; a Gaussian z-threshold silently mis-states the false-alarm rate exactly when it matters. It also fixes an incoherence in our own draft — we said "z ≥ 3 **and** Benjamini–Hochberg FDR," but BH consumes *p-values*, not z-scores. Conformal p-values make that pipeline correct rather than approximately correct. **This is a real upgrade and it is cheap (~50 lines).**

**Seasonality discovery instead of assumption.** "Periodogram confirmed by ACF, never assumed, so a 29-day billing cadence is absorbed into the seasonal component instead of leaking into the residual as a fake anomaly" is a sharper observation than our draft's hard-coded weekly + annual STL. MSTL handles the multi-cycle case natively. **Adopt.**

**Adtributor-family dimensional search with an explicit scoring function.** Our draft hand-waved "Adtributor-style contribution scan." The R1 doc actually specifies it: `EP_s = Δ_s/Δ_total`, `Surprise_s = JS(p_s ‖ q_s)`, `score = EP × Surprise`, with per-dimension scoring, top-K pruning, combination search among survivors, a cumulative-EP Pareto rule for multi-cause reporting, minimum-observation gating, and Simpson's-paradox checks on nested segments. That is a specification you can hand to an engineer. **Adopt wholesale.**

**Bootstrap stability of the attribution.** Re-running the segment search over ~100 resamples and reporting the win-rate — *"a cause that is not reproducible is not reported as a cause"* — is the best single idea in the document. It costs almost nothing to implement, it directly attacks the failure mode judges will probe ("how do you know that segment isn't noise?"), and it produces a number that feeds confidence honestly. **Adopt. This is a headline feature.**

**Isotonic calibration of the confidence score.** Our draft said calibration would be "evaluated, not asserted" and showed a reliability curve. The R1 doc goes further and *fits the map*: isotonic regression on historical (raw score, was-it-correct) pairs from rolling-origin backtesting, with tier boundaries read off the calibration curve rather than hand-picked. The per-tier backtest table — *High 91 % confirmed, Moderate 68 %, Low 41 %* — converts "we have confidence tiers" into "our confidence means something, here is the evidence." **Adopt. This is the strongest trust artifact available to us.**

**The `min()` aggregation argument.** *"Averaging would let strong detection paper over thin evidence — exactly the failure mode being designed against."* This is correct and it is a better default than our weighted geometric mean. The doc's own hedge (soften to a p-norm in production so one noisy signal cannot dominate) is the right resolution. **Adopt as softmin.**

**Entailment checking of generated sentences against their citations.** Our draft's numeric verifier catches fabricated *numbers*. It does not catch a fabricated *causal claim* built from correct numbers — "revenue fell because the outage reduced fill rate" when the evidence supports only co-occurrence. An NLI entailment check over cited documents closes that hole. **Adopt (with a cheaper fallback path, §3).**

**Timing consistency as an elimination rule.** "A cause that lands after its effect is eliminated," checked against each driver's known lag profile, is a clean deterministic filter that removes a whole class of plausible-but-impossible hypotheses. Our draft had lag windows in the contracts but never used them as a *gate*. **Adopt.**

**Evidence corroboration via noisy-OR over independent sources, with dedup at ingestion.** *"Forty tickets from forty customers are forty signals; one article syndicated across six sites is one — which is precisely why deduplication happens at ingestion, not here."* Correct reasoning, well expressed. Also **"counts over sentiment"**: factual claims rest on countable signals, model-inferred sentiment is colour only. **Adopt in light form.**

**The severity gate as cost architecture.** Framing the gate as *"cheap things run always, expensive things run rarely — this is what makes the system affordable across hundreds of KPIs"* is a better articulation of our materiality gate, and it converts a governance feature into an economics feature. Combined with a stated LLM-call budget it is quotable in the pitch. **Adopt the framing.**

**The adaptation matrix.** The what-changes / what-stays table across short history, weekly KPIs, no dimensional breakdown, no unstructured data, intermittent series, count KPIs, regime breaks, and high cardinality — plus the by-industry paragraph — is exactly the answer to "does this generalise?" It costs one table and pre-empts an obvious judging question. **Adopt.**

**Learned priority ranker (GBDT on analyst verdicts).** A gradient-boosted ranker trained on "real issue or false alarm?" is a safe, legitimate use of traditional ML — it prioritises, it never produces a quantitative claim — and it makes the learning loop *visible*. It also lets us tick "traditional ML" in the brief's method inventory with a straight face. **Adopt.**

**Precedent / case library for recommendations.** "Retrieves past anomalies with confirmed causes and what resolved them; only reasons fresh where no precedent exists." Our draft's static YAML action catalog is weaker. Precedent lookup makes the feedback loop pay off *in the output*, which is where judges can see it. **Adopt.**

**Dual-date extraction on documents.** Publish date *and* effective date, with the worked example of a March-announced, July-effective regulation. Small, sharp, cheap. **Adopt as a field.**

### 1.2 Where it overclaims or would break

**The dependency list is a literature review, not a build plan.** Airflow/Dagster · unstructured.io · datasketch · Presidio · spaCy · dateparser · sentence-transformers BGE-M3 · Qdrant/pgvector · OpenSearch · LlamaIndex · MAPIE · River · PyOD · ruptures · HDBSCAN · XGBoost · cross-encoder rerankers · Tavily/Exa/Firecrawl · GDELT/NewsAPI · DeBERTa-v3-MNLI · RAGAS. That is ~20 heavyweight components for a hackathon prototype. Each is individually defensible; together they are three months of integration work and a demo that fails on a network hiccup. **This is the document's central flaw** — it optimises for looking rigorous rather than for shipping. Round 2 is judged on a *working prototype*.

**Live web search and news feeds are a liability here, not an asset.** Our demo runs on synthetic enterprise data about products that do not exist. There is no real news about them. A live track adds nondeterminism, latency, API keys, and demo-day failure modes in exchange for nothing observable. **Cut it**; keep the *pre-indexed corpus* idea, which is the genuinely good half of that section.

**Isolation Forest for joint detection is over-reach at this data volume.** With a handful of KPIs and ~2 years of history, IF is unstable and hard to explain. The document itself offers robust Mahalanobis as "the zero-training fallback" — that should be the primary. **Downgrade.**

**Conformal validity is asserted a little too cleanly.** Split conformal guarantees hold under *exchangeability*, which time series violate by construction (autocorrelation, drift). The honest framing is that we use a rolling clean-window conformal p-value as a *distribution-free calibrated score* and validate its false-alarm rate empirically against the backtest, or adopt an adaptive variant. A statistically literate judge will ask this. **Adopt the method, fix the claim** (§4.2).

**The headline reliability numbers are presented as if measured.** "High 91 % confirmed, Moderate 68 %, Low 41 %" appears in a section titled *Evaluation* with no statement that these are illustrative. If we repeat that unlabelled and a judge asks "measured on what?", the answer must not be "it was a placeholder." In v2 those cells are **populated by our own backtest or explicitly labelled as targets** (§4.4, §6.3).

**"Three LLM calls total" is slightly rhetorical.** It is three per *investigated anomaly*, in a purely proactive system with no conversational mode and one narration style. Round 2 explicitly asks for persona-specific narratives and "who's asking" — so the real budget is higher and needs stating honestly (§4.5). The constraint is still worth keeping; it just needs an accurate number.

**"Nothing is deleted, only retrieved" sits awkwardly beside PII masking and retention policy.** Minor, but a governance-minded judge may notice. v2 states it as *"nothing relevant is discarded at ingestion; retention and masking are policy-controlled."*

### 1.3 The bigger problem: it answers about half the brief

The R1 document is an excellent **root-cause engine** and almost entirely silent on **the enterprise reality the Round 2 brief is actually about**. Scored against the ten minimum prototype expectations:

| Minimum expectation | R1 v4 | R2 draft | Merged v2 |
|---|---|---|---|
| 3–5 connected KPIs, 2–3 sources, different grains/cadences | ✗ (single-series framing; no cadence/grain/restatement handling) | ✓ | ✓ |
| Semantic / KPI contract (defs, calcs, drivers, thresholds, lineage, access) | ✗ **absent entirely** | ✓ | ✓ |
| ≥ 2 personas with different narratives/actions | ✗ (one voice, modulated by confidence tier only) | ✓ | ✓ |
| Multi-factor movement with known drivers | ~ (finds *segments*, not *driver types*) | ✓ | ✓✓ |
| Low-confidence abstention | ✓ (evidence-based only) | ✓ (data-quality based) | ✓✓ both paths |
| Sparse-history / new KPI | ~ (mentioned in adaptation matrix) | ✓ (EB pooling, contract policy) | ✓ |
| Role-based security / entitlement | ✗ **absent entirely** | ✓ | ✓ |
| Evidence: freshness, method, contribution, confidence, lineage | ~ (method + confidence strong; **no freshness, no lineage**) | ✓ | ✓✓ |
| LLM vs non-LLM breakdown | ✓ (strong) | ✓ (strong) | ✓ |
| Runtime telemetry (latency, calls, tokens, cost) | ✗ (cost discussed, never measured) | ✓ | ✓ |

Two further analytical gaps matter more than they look:

1. **No price–volume–mix decomposition.** Adtributor tells you *North region, SKU-7* carried the drop. It cannot tell you whether the drop was **price or volume or mix** — and for a *business* KPI engine that is half the question a CFO asks. Bennet decomposition answers it by arithmetic identity, with nothing to hallucinate.
2. **No econometric driver estimation, therefore no elasticities, therefore no quantified expected impact.** Without a regression layer the system can say "the stockout coincided" but never "each 1 pp of fill-rate costs 0.47 pp of revenue (95 % CI 0.31–0.63), so expediting recovers ≈ ₹52 lakh ± 11 lakh." The brief demands actions with **expected impact**; an attribution-only engine has to guess at that number, which is precisely the thing we have promised the LLM will never do.

**Net assessment:** the R1 document is stronger than the team seems to think — the ideas are real, correctly sourced, and several are better than what we drafted. Its faults are scope inflation, a missing governance half, and a few claims stated more confidently than the method licenses. All three are fixable by merging rather than choosing.

---

## 2. Disposition of every R1 idea

`ADOPT` = take as specified · `ADAPT` = take the idea, change the implementation · `REJECT` = leave out, with reason.
Build cost is engineer-days for one person who has the rest of the scaffold in place.

| # | R1 idea | Disposition | Change / reason | Cost |
|---|---|---|---|---|
| 1 | Conformal p-value for detection | **ADOPT** | Hand-roll (~50 lines) instead of MAPIE; claim framed as empirically-validated, not guaranteed | 0.5 d |
| 2 | MSTL + periodogram/ACF seasonality discovery | **ADOPT** | statsmodels MSTL + scipy periodogram | 0.5 d |
| 3 | Robust z on median/MAD residual | **ADAPT** | Kept as the *fallback* when the conformal window is too short | — |
| 4 | Tabular CUSUM for drift | **ADOPT** | As specified (k = 0.5, h = 4–5) | 0.5 d |
| 5 | Isolation Forest for joint detection | **ADAPT** | Robust Mahalanobis on the joint residual vector as primary; IF dropped — unstable at our data volume | 0.5 d |
| 6 | Benjamini–Hochberg FDR | **ADOPT** | Now correctly applied to conformal p-values | 0.2 d |
| 7 | Severity gate framed as cost architecture | **ADOPT** | Merged with our materiality gate (statistical **and** business floor) | — |
| 8 | Adtributor EP × JS-surprise search | **ADOPT** | Full spec: per-dim scoring, top-K prune, ≤ 2-dim combinations, min-obs gate, Simpson check | 2 d |
| 9 | Cumulative-EP Pareto multi-cause rule | **ADOPT** | Smallest non-overlapping set covering 80–90 % of Δ, cap 4 | 0.3 d |
| 10 | Bootstrap attribution stability (~100 resamples) | **ADOPT** | Headline feature; feeds confidence signal `c2` | 0.5 d |
| 11 | Pre-indexed corpus, dedup → PII → dual-date on entry | **ADOPT** | MinHash → simple hash+shingle dedup; Presidio → regex/spaCy-lite masking | 1 d |
| 12 | Hybrid dense + BM25 retrieval | **ADAPT** | `rank_bm25` + `sentence-transformers` in-process; **no Qdrant/OpenSearch** (corpus is ~500 docs) | 0.5 d |
| 13 | Cross-encoder rerank | **ADAPT** | Optional; LLM rerank in the same call as the query planner when the cross-encoder is not installed | 0.3 d |
| 14 | Live web/news track (Tavily/Firecrawl/GDELT) | **REJECT** | Nondeterministic, no real news about synthetic products, demo-day network risk, zero observable gain | — |
| 15 | LLM call 1 = typed query planner over structured facts only | **ADOPT** | Excellent security property (nothing confidential leaves); keep the domain allowlist validation | 0.5 d |
| 16 | EvidenceConf = w·rerank + w·source-tier + w·entity-link + w·extraction | **ADOPT** | Weights in config, tuned by the learning loop | 0.5 d |
| 17 | Noisy-OR corroboration across independent sources | **ADOPT** | With ingestion-time dedup as the independence guard | 0.3 d |
| 18 | "Counts over sentiment" rule | **ADOPT** | Free — a prompt + scoring rule | — |
| 19 | Sufficiency check → abstain rather than lower the bar | **ADOPT** | Becomes one of two abstention paths (the other is data-trust) | — |
| 20 | LLM call 2 = causal hypotheses, cite-or-drop | **ADOPT** | Hypotheses are *proposals*; they never set numbers | 0.5 d |
| 21 | Timing gate (cause must precede effect within lag profile) | **ADOPT** | Reads `lag_days` from the KPI contract — ties the two documents together neatly | 0.3 d |
| 22 | NLI entailment check on generated causal sentences | **ADOPT** | DeBERTa-v3-MNLI-small on CPU; fallback = small-model LLM judge; fallback-of-fallback = numeric verifier only, tier capped at Moderate | 1 d |
| 23 | LLM call 3 = recommendations from a case library | **ADOPT** | Precedent lookup + our governed action catalog with decision rights | 1 d |
| 24 | Confidence tier constrains narration language | **ADOPT** | High → direct causal phrasing; Moderate → hedged; Low → ranked hypotheses; Insufficient → no causal claim | 0.3 d |
| 25 | Five confidence signals, no LLM in the engine | **ADAPT** | Extended to **six** — R1 has no data-trust signal, which is where half the brief's complexity lives | 1 d |
| 26 | `min()` aggregation | **ADAPT** | Softmin (p-norm, p = −4) + hard gates; strict min kept as a config flag | 0.2 d |
| 27 | Isotonic calibration on rolling-origin backtest | **ADOPT** | Fitted for real against simulator ground truth; Platt fallback when n < 100 | 1 d |
| 28 | Per-tier backtest table as the trust artifact | **ADOPT** | Populated by our own run, or explicitly labelled as a target | — |
| 29 | Abstention as a designed path, not an error | **ADOPT** | Already in our draft; R1's framing is better, use it | — |
| 30 | Learning loop with 4 sinks | **ADOPT** | Extended to 5 (adds the calibration set) | 1 d |
| 31 | GBDT priority ranker on analyst verdicts | **ADOPT** | LightGBM; gated behind a minimum label count, staleness monitor reverts to statistics-only | 1 d |
| 32 | HDBSCAN offline cluster discovery for new segments | **REJECT** | Roadmap item in R1 too; no demo value in three weeks | — |
| 33 | SHAP as roadmap alternative | **REJECT** | We have a regression layer with real CIs; SHAP would weaken, not strengthen, the attribution story | — |
| 34 | River / true streaming | **REJECT** | Batch-on-refresh matches the brief's cadence framing; streaming is a Phase-2 line | — |
| 35 | Airflow / Dagster orchestration | **ADAPT** | A ~100-line Python scheduler + CLI; orchestration is not what is being judged | — |
| 36 | Adaptation matrix (graceful degradation) | **ADOPT** | Extended with our contract-driven sparse-history policy | — |
| 37 | Croston/TSB, Poisson/NB intervals for count & intermittent KPIs | **ADAPT** | Documented in the adaptation matrix; implemented only if a demo KPI needs it | — |
| 38 | Minimum-history floor (≈ 2 cycles) gating claims | **ADOPT** | Merged with the contract's `min_history` / graduation thresholds | — |
| 39 | Case library as precedent + calibration source | **ADOPT** | One table, two consumers | — |
| 40 | Public demo datasets (M5, Olist, Rossmann) | **ADAPT** | Keep the **structural simulator** as primary (we need counterfactual ground truth for calibration, which real data cannot give); optionally overlay Olist for corpus realism | — |

**Rejected outright: 4 of 40.** Everything else survives in some form. The R1 document was not wrong; it was unscoped.

---

## 3. What changes, relative to the R2 draft

So the team can see the delta at a glance — everything else in the R2 draft (contracts, RBAC compiler, personas, telemetry, business case, roadmap) carries over unchanged.

| Area | R2 draft said | v2 says | Why |
|---|---|---|---|
| Baseline | STL with assumed weekly + annual | **MSTL with periodogram/ACF-discovered periods** | Avoids KPI-specific cycles leaking into the residual as fake anomalies |
| Detection score | EWMA-scaled z, threshold 3 | **Conformal p-value on AR-whitened, EWMA-scaled innovations** | Distribution-free; makes the BH-FDR step mathematically coherent |
| Joint/cross-KPI | not specified | **Robust Mahalanobis on the joint residual vector** | Early warning; a combination breaks before any single number does |
| "Where" attribution | "Adtributor-style scan" (hand-waved) | **Full Adtributor: EP × JS-surprise, top-K prune, ≤2-dim search, Pareto multi-cause, Simpson check** | Was the vaguest part of the draft |
| Attribution robustness | none | **Bootstrap win-rate over 100 resamples; unstable causes are not named** | Directly answers "how do you know it's not noise?" |
| Confidence signals | 4 pillars | **6 signals** (adds attribution stability, evidence+timing, faithfulness; keeps data-trust which R1 lacks) | Union of both documents |
| Aggregation | weighted geometric mean | **softmin (p-norm) + hard gates** | Strong detection must not paper over thin evidence |
| Calibration | reliability curve shown | **isotonic regression fitted on backtest → calibrated probability → tier boundaries read off the curve** | Turns a score into a probability with a measured track record |
| Hypothesis filtering | none | **timing gate** (cause must precede effect within contract lag profile) | Kills impossible hypotheses deterministically |
| Narrative verification | numeric verifier | **numeric verifier + NLI entailment, and the result feeds back as a confidence signal** | Catches unsupported causal language, not just wrong numbers |
| Recommendations | static YAML catalog | **precedent from case library + catalog, with decision rights** | Makes the learning loop visible in the output |
| Prioritisation | rule-based priority formula | **+ LightGBM ranker on analyst verdicts, gated by label count** | Adds legitimate traditional ML; attacks alert fatigue |
| Generality story | roadmap section | **+ adaptation matrix (what changes / what stays)** | Pre-empts the "does it generalise?" question |
| Corpus | small doc store | **pre-indexed with dedup → PII mask → dual-date (publish + effective)** | An effective date cannot be extracted from a document never ingested |

---

## 4. Final architecture — Insight Copilot v2

### 4.0 One-paragraph statement of the system

Insight Copilot continuously watches governed KPIs defined by machine-readable **semantic contracts**. A deterministic always-on layer learns each KPI's seasonal shape and flags genuine breaks with a distribution-free false-alarm rate. Anomalies that pass a **statistical and business** materiality gate — and are ranked important by a model trained on analysts' own verdicts — are promoted to an expensive investigation path. There, a **four-layer attribution ladder** establishes *where* in the business the movement sits, *what kind* of movement it is, *why* it happened, and *what event* explains it. A confidence engine with **no LLM in it** scores six measured signals, calibrates the result against a backtested track record, and either publishes, hedges, or **abstains**. Language models are used in exactly four places — planning evidence queries, proposing causal hypotheses that must cite documents, rendering persona-specific narratives, and reading analyst feedback — and every number they emit is checked against the computed evidence bundle before a human sees it.

### 4.1 The attribution ladder — the headline of the design

This is the merge's central idea. Four questions, four methods, four different guarantees, assembled into one accounting that sums to the observed gap.

```
   QUESTION            METHOD                                    GUARANTEE
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 1. WHERE?      Adtributor over region × product × channel      Ranked + bootstrap │
│    which slice EP × JS-surprise, Pareto multi-cause             stability-scored  │
│    of the                                                                          │
│    business?   → "North region, top-3 SKUs = 79% of the gap"                      │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 2. WHAT KIND?  Bennet price–volume–mix decomposition           EXACT — arithmetic │
│    price, or   ΔR = Σ[Δp·(q₀+q₁)/2 + Δq·(p₀+p₁)/2]              identity, additive,│
│    volume, or  volume further split into own-volume vs mix      order-independent  │
│    mix?        → "price +2.7pp, volume −14.6pp, mix −0.4pp"                       │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 3. WHY?        SARIMAX-exog (primary) ⟷ OLS + Newey–West HAC    Coefficients with │
│    which       adstock, lags, elasticities, event study         CIs + diagnostics; │
│    causal      → "1pp fill-rate = 0.47pp revenue [0.31, 0.63]"  dual-method        │
│    drivers?       so the outage = −7.1pp = −₹4.93M               agreement scored   │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 4. WHAT EVENT? Pre-indexed retrieval + timing gate +            Cited, corroborated│
│    what human  noisy-OR corroboration + LLM hypothesis          across independent │
│    story?      → "OPS-2214: WH-N conveyor failure, 5 Mar 22:40"  sources; cite-or- │
│                                                                  drop enforced     │
└──────────────────────────────────────────────────────────────────────────────────┘
        ⇓
   ACCOUNTING: layer-2 identity fixes the split; layer-3 explains the volume term;
   whatever remains is reported as "unexplained", never absorbed silently.
```

Neither source document had all four. R1 had 1 and 4. The R2 draft had 2 and 3. **Having all four, with an accounting that reconciles them, is the technical claim we make in the pitch.**

### 4.2 Stage specification

```
STAGE 0 · ALWAYS-ON (deterministic, runs on every refresh, cheap)
  ingest → bronze/silver/gold · conformed calendar & dims · freshness tracker · DQ gates
  contracts loaded & validated · baselines: period discovery → MSTL → event regressors
  corpus: dedup → PII mask → dual-date extraction → entity link → hybrid index
  ── nothing here costs an LLM call ──

STAGE 1 · DETECT & CONFIRM (deterministic)
  residual → AR(p) whitening → EWMA/day-of-week scale → conformal p-value
  point (conformal) · drift (CUSUM) · joint (robust Mahalanobis on residual vector)
  BH-FDR across the KPI × segment scan
  ▸ MATERIALITY GATE: statistical (FDR-passed) AND business (contract ₹/pp floor)
  ▸ PRIORITY: rule score × LightGBM ranker (gated on ≥ N analyst labels)
  ▸ SEVERITY GATE ── below it: logged, visible, no investigation, no LLM spend

STAGE 2 · ATTRIBUTE (deterministic — the ladder, layers 1–3)
  WHERE  adtributor(cube) → bootstrap_stability(100 resamples) → Pareto cause set
  KIND   bennet_pvm() → price / own-volume / mix, asserted to sum to ΔR
  WHY    build_design() → SARIMAX-exog ⟷ OLS+HAC → coefficients, CIs, diagnostics
         event_study() for discrete events vs unaffected controls
  ▸ coverage = |explained Δ| / |total Δ|, remainder labelled

STAGE 3 · EVIDENCE (retrieval + LLM calls 1–2)
  ① LLM QUERY PLANNER — receives structured facts only (KPI, segments, window,
    direction, magnitude); no documents, no confidential values. Returns typed
    search plan validated against a domain allowlist.
  retrieve (dense + BM25 over pre-indexed corpus, dual-date aware) → rerank
  EvidenceConf = w₁·rerank + w₂·source_tier + w₃·entity_link + w₄·extraction
  corroboration = noisy-OR over *independent* sources (dedup guarantees independence)
  ▸ TIMING GATE: eliminate any candidate whose date post-dates the effect,
    or falls outside the driver's contract lag_days profile
  ② LLM HYPOTHESIS PROPOSER — proposes causal links, must cite bundle documents;
    uncited claims dropped before scoring. Proposes only; sets no numbers.
  ▸ SUFFICIENCY CHECK: nothing clears the evidence floor → abstain path

STAGE 4 · DECIDE & EXPLAIN
  CONFIDENCE ENGINE (no LLM) — six signals → softmin → isotonic → probability → tier
  ▸ HARD GATES → ABSTAIN (data-trust path or evidence-sufficiency path)
  ACTIONS — case-library precedent + governed catalog; preconditions checked;
            expected impact from *estimated* elasticities with CIs; owner from
            contract decision rights; monitoring plan attached
  ③ LLM NARRATOR (per persona, lazy + cached) — tier-constrained language
  ▸ NUMERIC VERIFIER (deterministic) + NLI ENTAILMENT → signal c6
    → if c6 lowers the tier, re-render at the lower tier; on repeat failure,
      TEMPLATE RENDERER (zero-LLM path, always available)

STAGE 5 · DELIVER & GOVERN
  workspace feed · conversational panel · evidence drawer · telemetry page
  RBAC enforced in the contract→SQL compiler (below the LLM, unbypassable)
  audit log: user, role, intent, SQL hash, contract version, model calls, narrative id

LEARNING LOOP (offline, nightly, 5 sinks, all gated by the golden eval suite)
  analyst verdict ─┬─→ priority ranker (LightGBM)
                   ├─→ attribution tuning (dimension weights, min-obs)
                   ├─→ evidence source-tier weights & rerank
                   ├─→ case library (precedent for future recommendations)
                   └─→ calibration set (refits isotonic map & tier boundaries)
```

### 4.3 Method inventory — the brief's "when and why" table

| Method class | Where used | Why this and not something else |
|---|---|---|
| **SQL / deterministic logic** | Every data access via the contract compiler; KPI math; RBAC row filters and masks | One definition of truth; entitlements enforced below the LLM so no prompt can bypass them |
| **Business rules** | Materiality floors, severity gate, timing gate, action preconditions, decision rights | Governance must be editable by the business without a code change |
| **Statistics** | MSTL, AR whitening, conformal p, CUSUM, Mahalanobis, BH-FDR, bootstrap, JS-divergence | Valid inference under autocorrelation and heteroscedasticity; distribution-free where possible |
| **Exact algebra** | Bennet price–volume–mix | An identity cannot be wrong — the strongest possible guarantee, so use it wherever it applies |
| **Econometrics** | SARIMAX-exog, OLS + Newey–West HAC, adstock, elasticities, event study | Produces coefficients *with confidence intervals* — required to quantify expected impact of actions |
| **Traditional ML** | LightGBM priority ranker | Prioritisation only. Deliberately never used to produce a quantitative business claim |
| **Causal inference** | Event study vs unaffected controls; DAG-driven regressor admissibility (mediators excluded); placebo shifts | Distinguishes "coincided with" from "explains"; the DAG stops us conditioning away the effect we are measuring |
| **Retrieval** | Pre-indexed hybrid search, dual-date, corroboration | External/human context that no numeric table contains |
| **NLI (small transformer)** | Entailment check of generated causal sentences vs citations | Catches unsupported *language* — the failure the numeric verifier cannot see |
| **LLM** | Query planning · hypothesis proposal · persona narration · feedback reading | Language tasks only. Never the source of a number, a threshold, a confidence, or an action |

### 4.4 The confidence engine (full specification)

**No language model participates in this component.** LLM self-reported confidence tracks fluency, not probability.

**Six signals, each measured:**

| Signal | Computed from | Normalisation |
|---|---|---|
| `c1` detection strength | Conformal p-value vs alert threshold α | `1 − p/α`, clipped to [0,1] |
| `c2` attribution quality | Bootstrap win-rate × explanation coverage | product of two [0,1] quantities |
| `c3` statistical validity | Ljung–Box, Breusch–Pagan, VIF, CI width relative to estimate, holdout MAPE, n vs `min_history` | penalised product, each term in [0,1] |
| `c4` data trust | Freshness vs SLA, DQ pass rate, cross-source reconciliation, restatement-window exposure | weighted product |
| `c5` evidence support | Noisy-OR corroboration over independent sources × timing-consistency density | product |
| `c6` narrative faithfulness | min(numeric-verifier pass, min NLI entailment probability across causal sentences) | direct |

**Aggregation, calibration, tiering:**

```python
raw   = softmin(c1..c6, p=-4)          # ≈ min, but one noisy signal cannot dominate absolutely
prob  = isotonic_map(raw)              # fitted on (raw, was_it_correct) from rolling-origin backtest
tier  = tier_from(prob)                # boundaries READ OFF the calibration curve, never hand-picked
```

**Hard gates override the score entirely** (any one forces `INSUFFICIENT`): a required source breaches its freshness SLA · cross-source reconciliation fails · any signal < 0.30 · no hypothesis survives the timing gate · nothing clears the evidence floor.

**Tier → what the system is allowed to say:**

| Tier | Language permitted | Actions |
|---|---|---|
| High | Direct causal phrasing | Full recommendations with owners |
| Moderate | Hedged phrasing, alternatives shown | Recommendations flagged for review |
| Low | Ranked hypotheses, no assertion | No auto-actions; investigation prompts only |
| Insufficient | **No causal claim at all** — abstention artifact: what is known, what failed, what is missing, retry ETA | None |

**Why this is the strongest part of the submission.** R1 wanted a calibrated confidence but had no ground truth to calibrate against — real business data rarely tells you whether an explanation was *correct*. Our structural simulator generates counterfactual ground truth for every planted event (§5.2 of the R2 draft), so we can run the full pipeline over **several hundred labelled synthetic anomalies**, collect `(raw_score, was_the_top_cause_right)` pairs, and fit the isotonic map *for real*. The output is the per-tier backtest table:

> *"When Insight Copilot says High, it is right 9X % of the time. Moderate, 6X %. Low, 4X %. Here is the reliability curve, here is the expected calibration error, and here is the code that produced them."*

**Honesty requirement (non-negotiable in the pitch):** those numbers are measured **on simulated data**, which validates the *mechanism*, not the real-world rates. We say that out loud. A judge who catches an unlabelled synthetic number will discount everything else; a team that volunteers the caveat gains the credibility back with interest. Same discipline applies to the conformal guarantee: exchangeability does not strictly hold for time series, so we present the conformal p as a distribution-free score whose false-alarm rate we **validate empirically in the backtest**, not as a theorem.

### 4.5 LLM boundary and call budget

**Four call sites, in order of appearance:**

| Call | Model tier | Input | Output | Guard |
|---|---|---|---|---|
| ① Query planner | small | Structured facts only — no documents, no confidential values | Typed search plan | Schema + domain allowlist |
| ② Hypothesis proposer | mid | Attribution results + retrieved bundle | Cited causal hypotheses | Cite-or-drop; timing gate; sets no numbers |
| ③ Persona narrator | mid | Evidence bundle + persona card + tier | Narrative | Numeric verifier + NLI + template fallback |
| ④ Feedback reader | small | Analyst free text | Structured labels | Offline, batched; human-visible |

*(Conversational mode adds an intent-parser call; it is the same small model as ①.)*

**Budget:** **3 LLM calls per investigated anomaly**, plus **1 per additional persona actually viewed** (lazy-rendered, cached on `(bundle_hash, persona, contract_version)`). The severity gate means only a small fraction of detections are ever investigated — so the honest headline metric is *two* numbers, both on the telemetry page:

- **cost per investigated insight** ≈ $0.03–0.04 (first persona), ~$0.016 per extra persona, ~$0 on cache hit
- **cost per monitored KPI-day** — the number that actually determines whether this scales to hundreds of KPIs

**Zero-LLM path exists end to end.** If every model call fails, the system still detects, attributes, scores confidence, selects actions, and renders a template narrative. The demo cannot hard-fail on a network outage — and that fact is itself a design argument worth stating.

### 4.6 Governance, security, adaptation

Contracts, the RBAC-enforcing SQL compiler, row/column/domain policy, audit logging, personas, and telemetry carry over unchanged from the R2 draft (§4, §6.4, §7 there). One addition from R1: **PII masking and deduplication happen at corpus ingestion**, before anything is indexed — so sensitive strings never enter the retrieval store, rather than being filtered at query time.

**Adaptation matrix — what changes, what stays:**

| Situation | What changes | What stays |
|---|---|---|
| Short history (new product/market) | Contract's sparse policy: pooled launch-curve baseline, guardrail-only checks, tier capped | Everything downstream of detection |
| Weekly / monthly KPIs | CUSUM becomes primary; wider conformal windows | Full pipeline; tiers especially valuable |
| No dimensional breakdown | Ladder layer 1 degrades to correlated-KPI analysis; tier capped at Moderate | Layers 2–4, evidence, narration |
| No unstructured corpus | Layer 4 degrades to event-calendar enrichment; external-cause claims capped | Layers 1–3 at full strength |
| Intermittent / sparse series | Croston/TSB baselines or Poisson bands instead of Gaussian residuals | Everything downstream of detection |
| Count / rate KPIs | Poisson or negative-binomial intervals; no log transform | All other stages |
| Regime break (shock, M&A) | Changepoint-aware refit; excluded regime dropped from calibration windows | Conformal calibration resumes once clean |
| Very high cardinality | Detect at aggregate level, attribute top-down; raise min-obs gates | Identical scoring maths at every level |

---

## 5. Implementation plan — ready for Claude Code

### 5.1 Dependencies (deliberately minimal, all pip-installable, all CPU)

```
python 3.11
duckdb>=1.0            pandas  numpy  scipy
statsmodels>=0.14      # MSTL, SARIMAX, HAC, Ljung-Box, Breusch-Pagan, VIF
scikit-learn           # IsotonicRegression, robust covariance (Mahalanobis)
lightgbm               # priority ranker only
pydantic>=2  pyyaml
rank-bm25              sentence-transformers   # in-process retrieval, ~90MB model
transformers torch --index-url cpu             # NLI entailment (optional, see fallback)
fastapi uvicorn        streamlit  plotly
anthropic  # or openai — behind a provider-agnostic client
pytest  pytest-cov
```

**Explicitly NOT used** (and why, so Claude Code does not reach for them): Airflow/Dagster (a 100-line scheduler suffices), Qdrant/OpenSearch/pgvector (~500-doc corpus fits in memory), LlamaIndex (thin wrapper we do not need), MAPIE (conformal is 50 lines and clearer hand-rolled), River/PyOD/HDBSCAN (out of scope), Tavily/Firecrawl/GDELT (no live web), RAGAS (our own eval harness), SHAP (regression gives us CIs instead).

### 5.2 Repository layout

```
insight_copilot/
├── contracts/          schema.py · net_revenue.yaml · blended_roas.yaml
│                       order_fill_rate.yaml · unit_volume.yaml · marketing_spend.yaml
├── personas/           cfo.yaml · rsm.yaml · analyst.yaml · marketing_lead.yaml
├── catalogs/           actions_revenue.yaml · actions_marketing.yaml · actions_supply.yaml
├── datagen/            world.py · inventory.py · marketing.py · exporters.py
│                       ground_truth.py · scenarios/*.yaml · corpus_gen.py
├── ingest/             loaders.py · transforms/*.sql · freshness.py · dq.py
├── corpus/             dedup.py · pii.py · dates.py · entities.py · index.py
├── engine/
│   ├── baseline.py     discover_seasonality · fit_baseline · counterfactual
│   ├── detect.py       whiten · conformal_pvalue · cusum · mahalanobis · bh_fdr
│   ├── gate.py         materiality · priority (rules + LightGBM) · severity
│   ├── attribute_where.py   adtributor · bootstrap_stability · pareto_causes · simpson_check
│   ├── attribute_kind.py    bennet_pvm
│   ├── attribute_why.py     build_design · estimate_drivers · event_study · diagnostics
│   ├── evidence.py     evidence_conf · noisy_or · timing_gate · sufficiency
│   ├── confidence.py   signals · softmin · isotonic · tier · abstention_artifact
│   ├── actions.py      precedent_lookup · catalog_match · expected_impact · monitoring_plan
│   └── bundle.py       InsightEvidenceBundle (the single typed hand-off object)
├── llm/                client.py · planner.py · hypotheses.py · narrate.py
│                       verify_numbers.py · verify_entailment.py · templates.py · router.py
├── security/           rbac.py · compiler.py · audit.py
├── learning/           feedback.py · ranker_train.py · calibrate.py · case_library.py
├── api/                main.py (FastAPI)
├── ui/                 app.py (Streamlit) · components/*
├── telemetry/          meter.py · ledger.py
├── evals/              fixtures/ · test_*.py · backtest.py · report.py
└── cli.py              seed · run · demo · backtest · validate
```

### 5.3 The one object everything hinges on

Build this first. Every stage writes into it; the LLM layer reads only from it; the verifier checks narratives against it; the UI renders it.

```python
class InsightEvidenceBundle(BaseModel):
    run_id: str; contract_version: str; kpi_id: str; window: DateWindow
    # observation
    actual: float; counterfactual: float; gap_abs: float; gap_pct: float
    # detection
    conformal_p: float; fdr_passed: bool; detector: Literal["point","drift","joint"]
    changepoint_date: date | None; persistence_days: int
    # ladder layer 1 — WHERE
    segments: list[SegmentCause]        # dims, EP, surprise, score, bootstrap_win_rate
    # ladder layer 2 — WHAT KIND
    pvm: PVMResult                      # price, own_volume, mix; asserts sum == gap_abs
    # ladder layer 3 — WHY
    drivers: list[DriverContribution]   # name, coef, ci_low, ci_high, contribution_abs,
                                        # contribution_pp, method, agreement
    diagnostics: Diagnostics            # ljung_box_p, breusch_pagan_p, vif_max, holdout_mape, n
    unexplained_abs: float; coverage: float
    # ladder layer 4 — WHAT EVENT
    evidence: list[EvidenceItem]        # doc_id, quote, publish_date, effective_date,
                                        # source_tier, evidence_conf, timing_ok
    hypotheses: list[Hypothesis]        # text, cited_doc_ids, timing_ok, survived
    # decision
    signals: ConfidenceSignals          # c1..c6, raw, calibrated, tier
    abstention: AbstentionArtifact | None
    actions: list[RecommendedAction]    # driver, lever, action, expected_impact_ci,
                                        # owner, approval_required, monitoring_plan, precedent_id
    # governance & ops
    freshness: dict[str, FreshnessInfo]; lineage: list[LineageStep]
    telemetry: RunTelemetry             # per-stage ms, model calls, tokens, cost, cache hits
```

**Rule for Claude Code:** *no module may return a number that does not end up in this bundle, and no narrative may contain a number that is not in it.*

### 5.4 Build order — 10 modules, each with an acceptance test

Hand these to Claude Code one at a time, in order. Each is independently testable; each ends with a green test before the next begins.

| # | Module | Deliverable | Acceptance test |
|---|---|---|---|
| **B1** | Contracts + compiler + RBAC | `contracts/schema.py`, 5 YAML contracts, `security/compiler.py`, `audit.py` | `pytest evals/test_contracts.py` — all contracts validate; compiler emits SQL with the RSM row filter and masked columns; intern query denied with reason; every call lands in the audit table |
| **B2** | Simulator + ground-truth ledger | `datagen/*`, 4 scenario YAMLs, `corpus_gen.py` | Seeded regen is byte-identical; `ledger.parquet` holds the true counterfactual contribution of every planted event; residuals exhibit the planted AR(1) and heteroscedasticity (Ljung–Box and Breusch–Pagan reject on raw residuals) |
| **B3** | Ingest + freshness + DQ | bronze→silver→gold, `freshness.py`, `dq.py` | Gold marts at contract grain; the 48-h supply lag, the weekly restatement, and the missing MarTech week all surface as flags; Scenario B's reconciliation breach is caught |
| **B4** | Baseline + detection | `baseline.py`, `detect.py` | Period discovery finds the planted weekly cycle *and* a deliberately planted 29-day cycle; conformal p-values are uniform on clean holdout windows (KS test, p > 0.05) — **this is the test that proves the detector is calibrated**; all planted anomalies detected, all planted distractors rejected |
| **B5** | Attribution ladder | `attribute_where.py`, `attribute_kind.py`, `attribute_why.py` | PVM sums exactly to ΔR (assert to 1e-6); Adtributor recovers the planted segment as rank 1 with bootstrap win-rate > 0.9; driver coefficients recover planted elasticities within ±20 %; SARIMAX and HAC-OLS agree within tolerance; diagnostics populated |
| **B6** | Corpus + evidence + timing | `corpus/*`, `evidence.py` | Dedup collapses the syndicated-document cluster to one; PII masked pre-index; the dual-date document is retrievable by *effective* date; timing gate eliminates the planted post-dated red-herring event |
| **B7** | Confidence + abstention | `confidence.py`, `learning/calibrate.py`, `evals/backtest.py` | Backtest over ≥ 300 simulated anomalies produces the isotonic map and the per-tier table; ECE ≤ 0.10; Scenario B abstains via the data-trust gate; a zero-evidence case abstains via the sufficiency gate |
| **B8** | LLM layer + verifiers | `llm/*` | Planner output validates against the allowlist and contains no confidential values; hypotheses without citations are dropped; **numeric fidelity 100 %** on goldens; an injected wrong number in a mocked narrative is caught and regenerated; entailment failure demotes the tier; killing the API key still produces a complete template narrative |
| **B9** | Actions + learning loop | `actions.py`, `learning/*` | Actions carry owner, decision-rights approval flag, expected impact **with CI propagated from the regression**, and a monitoring plan; a seeded analyst correction visibly changes the next run's ranking; ranker stays disabled below the label threshold |
| **B10** | API + UI + telemetry | `api/*`, `ui/*`, `telemetry/*` | All four scenarios walkable end-to-end by someone outside the team following the demo script; evidence drawer shows freshness, method, contribution, confidence, lineage; telemetry page shows p50/p95 latency, tokens, cost per insight **and** cost per monitored KPI-day |

**Suggested task prompt shape for Claude Code:**

> "Implement module B5 (`engine/attribute_where.py`) per §4.1–4.2 and §5.3 of `InsightCopilot-v2-Final-Architecture.md`. Signature and semantics are specified there. Write the implementation plus `evals/test_attribute_where.py` covering the acceptance criteria in §5.4 row B5. Use only the dependencies listed in §5.1. Do not add a number to any return value that is not part of `InsightEvidenceBundle`. Run the tests and iterate until green."

### 5.5 Key function signatures (so the implementation does not drift)

```python
# engine/baseline.py
def discover_seasonality(y: pd.Series, max_period: int = 400) -> list[int]:
    """Periodogram peaks confirmed by ACF significance. Returns [] if none — never assume 7/365."""

def fit_baseline(y, periods, events: pd.DataFrame) -> BaselineFit:
    """MSTL on log(y) when strictly positive and multiplicative, else level.
    Movable events (Diwali, month-end, promos) enter as regressors, NOT as fixed-lag seasonality."""

# engine/detect.py
def whiten(resid: pd.Series, max_p: int = 7) -> tuple[np.ndarray, int]:
    """AR(p) by AIC; return one-step innovations + p. Ljung-Box on output must not reject;
    if it does, escalate to SARIMA and lower c3."""

def conformal_pvalue(score_today: float, calib_scores: np.ndarray) -> float:
    """p = (1 + #{calib >= today}) / (n + 1).  Distribution-free; no Gaussian assumption.
    Calibration window excludes known-anomalous and known-regime-break days."""

def bh_fdr(pvals: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg step-up. Returns boolean reject mask."""

# engine/attribute_where.py
def adtributor(cube, actual_col, forecast_col, dims, top_k=5, max_dims=2,
               min_obs=30, pareto_target=0.85, max_causes=4) -> list[SegmentCause]:
    """EP_s = (A_s - F_s)/(A_tot - F_tot);  Surprise_s = JS(p_s || q_s) on share distributions;
    score = EP * Surprise. Score each dimension independently, prune to top_k, then search
    <=max_dims combinations among survivors only. Report the smallest non-overlapping set whose
    cumulative EP >= pareto_target, capped at max_causes. Check nested segments for Simpson reversal."""

def bootstrap_stability(cube, search_fn, n: int = 100, seed: int = 42) -> dict[str, float]:
    """Fraction of resamples in which each segment set wins. A cause below the stability floor
    is reported as a ranked shortlist, never as a named cause."""

# engine/attribute_kind.py
def bennet_pvm(t0, t1, price_col, qty_col, seg_cols) -> PVMResult:
    """dR = sum_i [ dp_i*(q0_i+q1_i)/2 + dq_i*(p0_i+p1_i)/2 ]; split dq into own-volume vs mix.
    MUST assert price + own_volume + mix == dR within 1e-6."""

# engine/attribute_why.py
def estimate_drivers(y, X, contract) -> DriverFit:
    """Primary: SARIMAX(p,d,q)-exog on log KPI. Cross-check: OLS + Newey-West HAC,
    L = floor(4*(T/100)**(2/9)). Return coefficients with CIs from both, an agreement score,
    and diagnostics (Ljung-Box, Breusch-Pagan, Durbin-Watson, VIF, holdout MAPE).
    Regressor admissibility comes from the contract driver DAG — mediators are EXCLUDED
    when estimating a total effect. Collinear drivers (VIF > 5) are attributed as a GROUP."""

# engine/confidence.py
def softmin(x: np.ndarray, p: float = -4.0) -> float:
    """p-norm softmin: (mean(x**p))**(1/p). Approaches min as p -> -inf."""

def decide(signals: ConfidenceSignals, contract, iso_map) -> ConfidenceVerdict:
    """raw = softmin(c1..c6) -> isotonic -> probability -> tier.
    Hard gates (freshness SLA, reconciliation, any signal < 0.30, no surviving hypothesis,
    evidence floor) force INSUFFICIENT regardless of the score."""

# llm/verify_numbers.py
def verify_numbers(text: str, bundle: InsightEvidenceBundle) -> VerifyReport:
    """Extract every numeric token (incl. ₹ lakh/crore, %, pp), normalise units,
    match against bundle values within rounding tolerance. ANY unmatched number = failure."""

# llm/verify_entailment.py
def entailment_score(sentences: list[str], cited_docs: dict[str, str]) -> float:
    """Min entailment probability across causal sentences vs their citations.
    Fallback chain: DeBERTa-MNLI -> small-model LLM judge -> numeric-only (tier capped Moderate)."""
```

### 5.6 Revised timeline (~3 weeks, one to two builders)

| Days | Modules | Milestone |
|---|---|---|
| 1–3 | B1, B2 | Contracts validate; world generates with ground truth |
| 4–6 | B3, B4 | Data spine live; **conformal calibration test green** (the credibility checkpoint) |
| 7–10 | B5 | Full attribution ladder recovers planted truth |
| 11–12 | B6 | Evidence layer with timing gate |
| 13–14 | B7 | **Backtest → isotonic map → per-tier table** (the trust artifact exists) |
| 15–17 | B8, B9 | LLM layer, verifiers, actions, learning loop |
| 18–20 | B10 | Workspace, telemetry, four scenarios walkable |
| 21 | — | Eval suite green twice from clean regen; demo rehearsed |

**If time compresses:** drop the NLI entailment model (fall back to the small-model judge), the LightGBM ranker (rules-only priority), and the conversational panel (proactive feed only). Keep, in this order of priority: the attribution ladder, the calibration backtest, abstention, contracts + RBAC, telemetry. Those five are what the brief scores.

### 5.7 Demo running order (7 minutes)

1. **The principle** (45 s) — "statistics decide, the model narrates" + the LLM boundary slide.
2. **Scenario A, the ladder** (2 min) — one insight card, then open the evidence drawer and walk *down* the ladder: where (with bootstrap stability) → what kind (PVM sums exactly) → why (coefficients with CIs, point at the Breusch–Pagan flag: "this is why we use HAC") → what event (the cited ticket, timing-gated).
3. **Personas** (45 s) — same bundle, CFO card vs Analyst card; note the numeric verifier count: 14 numbers checked, 0 failures.
4. **Action** (45 s) — approve the replenishment: owner, expected impact **with CI**, precedent from the case library, monitoring plan created.
5. **Abstention** (45 s) — Scenario B; read the card aloud. "It refuses, and it tells you when it will retry."
6. **The trust artifact** (60 s) — the calibration curve and per-tier backtest table. State the synthetic-data caveat yourselves.
7. **Governance + economics** (45 s) — role switch CFO → RSM → intern on one question, audit log line; then the telemetry page: latency, tokens, cost per insight *and* per monitored KPI-day.
8. **Close** (15 s) — the adaptation matrix: "here is what changes and what stays when the next client's data looks nothing like this."

---

## 6. Open decisions for the team to confirm

Answer these five and the plan is executable as written.

1. **Product name** — keep **Insight Copilot** (recommended, for continuity with the R1 panel) or switch to PRISM?
2. **NLI entailment model** — include DeBERTa-MNLI (≈ 400 MB download, CPU inference, ~1 build-day) or ship the small-model-LLM judge fallback only?
3. **LightGBM priority ranker** — build it (adds a genuine traditional-ML component to the method inventory) or stay rules-only and save a day?
4. **Conversational mode** — build the chat panel (needed for the "who's asking" framing and the intent-parser demo) or ship proactive-only and describe conversational as Phase 2?
5. **Data** — pure structural simulator (required for the calibration backtest), or simulator plus an Olist/M5 overlay for corpus realism at the cost of extra plumbing?

My recommendations: **1** keep Insight Copilot · **2** include it, the faithfulness signal is a differentiator · **3** build it, it is one day and it makes the learning loop demonstrable · **4** build it, the brief's persona framing implies pull as well as push · **5** simulator only — the ground truth is the whole point, and Olist adds plumbing without adding evaluative value.

---

*Sources: Adtributor (Bhagwan et al., NSDI 2014) and successors HotSpot (2018), Squeeze (2019) · STL (Cleveland et al., 1990), MSTL (Bandara et al., 2021) · CUSUM (Page, 1954) · conformal prediction (Vovk et al.; note exchangeability caveat for time series) · Benjamini–Hochberg (1995) · Bennet indicator decomposition (1920) · Newey–West (1987, lag rule per Newey–West 1994) · isotonic calibration (Zadrozny & Elkan, 2002) · LightGBM (Ke et al., 2017). All named libraries are open source.*



