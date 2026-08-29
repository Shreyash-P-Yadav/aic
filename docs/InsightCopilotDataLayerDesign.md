# Insight Copilot — Data Generation & Intake Design

**Accenture Innovation Challenge 2026 · Round 2 · BusinessIntelligence.ai**
Companion to *InsightCopilot-v2-Final-Architecture.md*. Covers everything upstream of Stage 1.
Status: **design for review — no code yet.** Optimised for accuracy and defensibility, not build speed.

---

## 0. The governing principle

> **The synthetic data is not a backdrop for the demo. It is the instrument that proves the engine works.**

Three consequences follow, and every decision in this document derives from one of them:

1. **Every capability we claim must have a defect in the data that exercises it.** If the engine claims to reconcile different refresh cadences, the data must *have* different refresh cadences. If it claims to abstain on stale feeds, a feed must actually go stale. A clean dataset proves nothing — it makes an untested system look finished. We therefore design the **pathologies first** (§7) and the happy path second.

2. **Ground truth must be causal, not observational.** The single thing synthetic data can give us that no real dataset can is the answer to *"what would revenue have been if the outage had not happened?"* That counterfactual is what turns our confidence score from an assertion into a measured probability (§9). It is the reason we simulate rather than download a Kaggle dataset.

3. **The data must be defensibly realistic, and we must be able to prove it.** Not "it looks plausible on a chart" but a test suite asserting that elasticities, seasonality amplitudes, service levels, return rates and noise structure sit inside published ranges for this industry (§12). When a judge asks "is this realistic?", the answer is a green test run, not an opinion.

A fourth principle governs intake specifically:

4. **Data arrives; it is not present.** A real BI system never sees a complete table. It sees files landing at 02:07, a weekly drop that is four hours late, a supply extract covering the day before yesterday, and a marketing file that quietly revises numbers it sent a week ago. The prototype must be built against *arrival*, not against a finished warehouse — because every hard part of the brief (freshness, restatement, reconciliation, abstention on stale data) lives in the arrival process (§10).

---

## 1. The world: Meridian Consumer Brands

A fictional but tightly specified company. Specificity is not decoration — every parameter below becomes a constant in the generator, and vagueness here becomes incoherence in the data.

> **Meridian Consumer Brands (MCB)** — an India-based home & personal care company, founded 2016, ~₹850 crore annual net revenue (~US $100 M), selling 150 active SKUs across 6 categories through 4 channels into 5 regions, fulfilled from 4 distribution centres. Hybrid D2C-and-retail: roughly 40 % of revenue through its own website and quick-commerce, 60 % through marketplaces and modern trade.

**Why this archetype.** It is the smallest world in which all three headline KPIs are simultaneously meaningful and genuinely coupled: price–volume–mix decomposition needs real prices and real mix shift; marketing ROAS needs channel-level spend with lagged effect; fill rate needs physical inventory and DCs. It also gives us honest seasonality (Diwali, summer, monsoon), honest external data (competitor pricing, category panels, weather), and it is the kind of company that would plausibly *buy* this product — which matters for the business case. A bank or a SaaS business would weaken the price–volume–mix half of the attribution ladder.

### 1.1 Dimensional structure

| Dimension | Members | Notes |
|---|---|---|
| **Category** | 6 — Haircare, Skincare, Bodycare, Home Fragrance, Surface Care, Baby | Different seasonality shapes and elasticities |
| **Product / SKU** | 150 active, ~180 lifetime (incl. discontinued + 3 launched in-window) | Product master is a slowly-changing dimension |
| **Region** | North, West, South, East, Central | Weather and festival timing differ |
| **Channel** | D2C web, Quick-commerce, Marketplace, Modern trade | Very different margin, latency, data quality |
| **Warehouse / DC** | DC-North, DC-West, DC-South, DC-East | Maps to region, with cross-serving during outages |
| **Campaign** | ~40 concurrent, ~350 lifetime | Campaign IDs are reused across years (a planted defect) |
| **Customer segment** | New / Repeat / Subscription | Used for mix analysis, not a headline dimension |

Cube cardinality at daily grain: 150 × 5 × 4 = 3,000 combinations, of which ~35 % are active on a given day (~1,050 rows/day). Over 36 months → **≈ 1.15 M fact rows**. Comfortable for DuckDB, large enough that the Adtributor search is a real search rather than a lookup.

### 1.2 Time span and calendars

- **History:** 36 months, 1 Sep 2023 → 31 Aug 2026. Three full annual cycles is the minimum for honest yearly seasonality plus a clean calibration window that excludes the demo scenarios.
- **Demo "today":** a configurable `SIM_TODAY`, default late March 2026, leaving five months of post-scenario data for backtesting.
- **Canonical timezone:** Asia/Kolkata (IST). One source deliberately stamps UTC (§7, defect P9).
- **Fiscal calendar:** April–March (Indian FY). Weekly KPIs use ISO weeks. The fiscal/ISO mismatch is real and is what makes the "inconsistent calendars" complexity concrete rather than rhetorical.
- **Movable festivals:** Diwali, Holi, Eid, Onam, Raksha Bandhan, Pongal shift year to year. **Do not hard-code dates** — populate from the `holidays` Python package (India), then hand-tag each as demand-relevant or not. Hard-coded festival dates are a silent realism bug and a credibility risk if a judge checks one.
- **Monsoon onset** by region, varying ±10 days year to year — drives Home Fragrance and Surface Care demand and gives us a non-calendar seasonal driver.

### 1.3 Governed KPI set

Five governed KPIs plus two masked measures, matching the contracts already drafted:

| KPI | Grain | Cadence | Primary source | Role |
|---|---|---|---|---|
| `net_revenue` | date × sku × region × channel | daily | OMS | Tier-1 headline |
| `unit_volume` | date × sku × region × channel | daily | OMS | Driver + KPI |
| `order_fill_rate` | date × warehouse × sku | daily, **T+2 latency** | WMS | Leading indicator of revenue |
| `marketing_spend` | iso_week × campaign × channel | weekly, **restated 14 d** | MarTech | Driver + KPI |
| `blended_roas` | iso_week × channel | weekly | MarTech ⋈ OMS | Cross-source ratio metric |
| `gross_margin_pct` | date × sku × region | daily | OMS ⋈ ERP | **Column-masked** for RSM role |
| `returns_rate` | date × sku × channel | daily, 7–21 d lag | OMS | Secondary; long natural lag |

This satisfies the brief's "3–5 connected KPIs across 2–3 sources with different grains or refresh cadences" with room to spare, and the connections are real: fill rate drives volume drives revenue; spend drives volume with a lag; revenue and spend jointly define ROAS.

---

## 2. Data availability assumption register

This is the answer to *"what data would a company like this actually have, and what could it get from the web?"* Each row states what we assume, how a real company would access it, and — importantly — **what is realistically wrong with it**. These assumptions get stated openly in the proposal; judges reward teams who model access friction instead of assuming a clean warehouse.

### 2.1 Internal systems

| # | System | Realistic access | Grain | Cadence / latency | History | Quality | Realistic limitations we model |
|---|---|---|---|---|---|---|---|
| I1 | **OMS / order management** (Shopify-plus-ERP style) | Nightly export from a read replica; never query prod | Order line | Daily, lands ~02:00 IST, T+1 | 36 mo | High | Timing cut-off at midnight; cancellations post-date orders; occasional duplicate export |
| I2 | **WMS / supply chain** | Nightly flat-file extract from a vendor-hosted WMS | Warehouse × SKU × day | Daily but **T+2**; occasionally T+3 | 18–36 mo | Medium | Extract job fails silently some nights → gap days; no backfill unless requested |
| I3 | **MarTech aggregator** (ad platforms rolled up) | Weekly SFTP/Parquet drop from an agency or aggregator | Campaign × channel × ISO week | Weekly Mon ~06:00 IST | **12 mo only** | Medium-low | Platform attribution restates for 14 days; retention window caps history; campaign IDs reused |
| I4 | **ERP / Finance** | Monthly close (authoritative) + daily provisional feed | Category × region × month | Monthly, +5 business days | 36 mo+ | High but late | Finance net revenue ≠ ops net revenue by definition (returns timing, shipping treatment) |
| I5 | **Support / CRM tickets** | API, near-real-time | Ticket | Continuous, minutes | 24 mo | Medium | Free text, **contains PII**, inconsistent tagging, agent shorthand |
| I6 | **PIM / product master** | DB table, event-driven | SKU | Irregular | Full | Medium | **Updated late** — new SKUs transact before the master knows them → `UNKNOWN` members |
| I7 | **Inventory snapshots** | Daily snapshot table | DC × SKU | Daily T+1 | 24 mo | Medium | Snapshot, not ledger — cannot reconstruct intra-day |
| I8 | **Pricing / promo calendar** | Spreadsheets + a planning tool; partially manual | SKU × region × period | Ad hoc, human-entered | 24 mo | **Low** | Late entry, missing end-dates, free-text notes — the classic "the business knows but the data doesn't" gap |
| I9 | **HR / staffing rosters** | HRIS export | DC × shift | Weekly | 12 mo | Medium | *Declared but not built* — a driver we name and do not use |

### 2.2 External / web sources

| # | Source | Realistic access | Grain | Cadence / latency | History | Realistic limitations we model |
|---|---|---|---|---|---|---|
| E1 | **Competitor price panel** | Paid scraping vendor (DIY scraping breaks ToS and rate limits) | Competitor × SKU-match × week | Weekly, 3-day lag | **14 mo only** — you only have data from when you started buying it | **~60 % SKU coverage**; fuzzy product matching with a confidence score (~85 % match rate); silent gaps when a listing is delisted |
| E2 | **Category market panel** (Nielsen/Kantar-style) | Syndicated subscription | Category × region × month | Monthly, **6-week lag** | 36 mo | Coarse grain only — cannot drill to SKU; revised once |
| E3 | **Weather** | Public/commercial API | Region × day | Daily, reliable | 36 mo | Gridded to region centroid — a real approximation |
| E4 | **Holiday & festival calendar** | `holidays` library + manual tagging | Date | Static | Full | Movable dates; regional variation (Onam is South-only) |
| E5 | **News / PR feed** | RSS + a news API | Article | Event-driven | 24 mo | **Syndication duplicates** (one press release, six outlets); publish date ≠ effective date |
| E6 | **Marketplace reviews** | Marketplace API / vendor | Review | Daily | 24 mo | Noisy, **PII-bearing**, review-bombing, sentiment ≠ fact |
| E7 | **Logistics / port advisories** | Public advisories, RSS | Region | Irregular | — | *Declared but not built* |

### 2.3 Three honest constraints that shape the design

1. **External data has shorter history than internal data.** Competitor prices start 14 months in, the market panel is 6 weeks stale. So any model using them has a shorter usable window than one that does not — and the confidence engine must *know* that. This single realistic fact creates genuine analytical tension and almost no competing team will model it.
2. **External data arrives coarser than the decision.** The market panel is category × region × month; the decision is SKU × week. Downscaling is an assumption, not a fact, and must be flagged as such in the evidence bundle.
3. **Entity resolution is uncertain.** A competitor's "Botanical Hair Oil 200 ml" matching *our* SKU is a probabilistic join with a confidence score, not a key. That score propagates into evidence confidence (`c5`) — exactly the `EntityLinkConf` term the Round 1 spec called for.

### 2.4 Build tiering

Do not build all sixteen. Recommended scope given "accuracy over speed":

- **Build at full fidelity (5):** I1 OMS · I2 WMS · I3 MarTech · I5 Support tickets · E1 Competitor prices
- **Build lightweight (4):** I6 PIM · I7 Inventory · E3 Weather · E4 Holidays
- **Build as corpus only (2):** E5 News · I8 Pricing/promo notes (these are documents, not tables)
- **Declare in the register, do not build (5):** I4 ERP · I9 HR · E2 Market panel · E6 Reviews · E7 Advisories — *named in the proposal as the production design, explicitly out of prototype scope*

That is **11 real feeds against a brief that asks for 2–3** — enough to be obviously serious without becoming an integration project. The register carries the rest, which is how a real architect answers "what about finance data?" without building it.

---

## 3. Generation architecture — nine layers

The generator is a **structural simulation of a business**, not a statistical sampler. Each layer consumes the layer above and knows nothing of the layers below. This separation is what makes ground truth possible: the truth lives in layers 1–3, and every defect lives in layers 4–5, so we always know exactly what the answer was before the data got messy.

```
L0  CALENDAR & EXOGENOUS WORLD
    dates · fiscal/ISO calendars · festivals (movable) · monsoon onset · weather
    competitor actions · category market index · macro drift
                          │  (pure inputs — depend on nothing)
                          ▼
L1  LATENT TRUTH — "the physics"
    true base demand per SKU×region×channel · true elasticities · true adstock
    parameters · true seasonal shape · structural noise (AR(1), heteroscedastic)
                          │  ← this is what NO real company can observe
                          ▼
L2  BUSINESS DECISIONS — partly endogenous
    pricing & promo calendar · marketing budget allocation · replenishment policy
    production plan · assortment changes · new product launches
                          │  ← decisions RESPOND to demand → realistic confounding
                          ▼
L3  PHYSICAL OUTCOMES
    orders · stockouts · shipments · returns · cancellations · inventory positions
                          │  ← the true, complete, perfectly-known business reality
                          ▼
L4  SOURCE-SYSTEM PROJECTION
    the SAME truth viewed through 11 systems, each with its own grain, cadence,
    latency, definitions and blind spots — and each disagreeing with the others
    in ways a real reconciliation would find
                          ▼
L5  DEFECT INJECTION
    the pathology catalog (§7): lateness, restatement, duplication, schema drift,
    unit changes, timezone bugs, null spikes, definitional change, missing periods
                          ▼
L6  UNSTRUCTURED CORPUS
    generated FROM the event ledger so documents are causally consistent with the
    numbers — tickets, memos, campaign briefs, supplier mail, news, reviews
                          ▼
L7  GROUND-TRUTH LEDGER          ◄── counterfactual re-runs of L1–L3
    the true causal contribution of every planted event (§9)
                          ▼
L8  LIVE INTAKE HARNESS
    sim clock · landing zone · arrival schedules · watchers (§10)
```

**Determinism contract:** the entire stack is a pure function of `(seed, world_config, event_set)`. Two runs with the same inputs produce byte-identical outputs. This is non-negotiable — it underpins ground truth, reproducible evals, and a demo that behaves the same in rehearsal and on stage.

---

## 4. The latent process (L1) — specification

### 4.1 Demand equation

For SKU `s`, region `r`, channel `c`, day `t`:

```
demand[s,r,c,t] =  base[s,r,c]
                 × trend[s,t]                      # slow growth/decline, per-SKU lifecycle
                 × dow[c,t]                        # day-of-week, CHANNEL-specific
                 × annual[cat(s),r,t]              # category × region annual shape
                 × festival[r,t]                   # movable, with pre-build and post-lull
                 × weather_effect[cat(s),r,t]      # monsoon/heat sensitivity by category
                 × (price[s,r,c,t] / ref_price[s]) ^ ε[cat(s)]        # own-price elasticity
                 × (comp_price_idx[s,r,t]) ^ ε_cross[cat(s)]          # cross-price
                 × (1 + β[c] · adstock[r,c,t])                        # marketing lift
                 × promo_lift[s,r,c,t]             # non-price promo (bundles, visibility)
                 × availability[s,r,c,t]           # ← from L3 inventory, ≤ 1
                 × exp(u[t] + v[s,r,c,t])          # structured noise, see 4.2
```

Notes that matter:

- **Multiplicative, not additive.** A weekend dip is −20 % of level, not a fixed number of units. This is why the engine models `log(y)`, and the data must be built the same way or the modelling choice looks arbitrary.
- **`dow` is channel-specific.** Quick-commerce peaks on weekends and evenings; modern trade is weekday-heavy. This gives the mix dimension real behaviour and makes channel mix-shift a genuine driver.
- **Festivals have pre-build and post-lull**, not a single spike: demand rises for ~10 days before Diwali and falls below baseline for ~7 days after. A naive seasonal model that treats a festival as a one-day dummy will mis-forecast the lull — which is exactly the kind of thing that should produce a *false* anomaly if handled badly, and does not if handled well. **This is a deliberate trap for our own detector, and passing it is a demo point.**
- **`availability` is a feedback path from L3.** Demand is censored by supply: a stockout does not merely reduce sales, it also shifts some demand to substitute SKUs (a leakage parameter) and some is lost entirely. Substitution is what makes the mix term move during the outage scenario.

### 4.2 Noise structure — deliberately hostile to naive methods

```
u[t]      = φ · u[t−1] + σ[t] · η[t]           φ ≈ 0.35        # company-wide AR(1) shock
σ[t]      = σ₀ · (1 + 0.6·promo[t]) · dow_vol[c,t] · (1 + 0.4·festival_window[t])
v[s,r,c,t] ~ lognormal idiosyncratic, variance inversely related to base volume
```

Two properties are planted on purpose, because the whole analytical design in the architecture document is justified by them:

- **Autocorrelation (φ ≈ 0.35).** Makes a plain z-score on residuals understate variance and over-flag. Justifies AR whitening before scoring.
- **Heteroscedasticity.** Variance clusters around promos, festivals and weekends. Justifies EWMA/day-of-week variance scaling, and makes Breusch–Pagan reject in the flagship scenario — which is why we invoke Newey–West. *The diagnostic that appears in the demo is real, not decorative.*

Small SKUs additionally get **near-Poisson counting noise** so at least one series is genuinely intermittent (a Croston case for the adaptation matrix), and one SKU is deliberately slow-moving with many zero days.

### 4.3 Parameter realism table

Values are chosen to sit inside published ranges for consumer packaged goods. **Verify and cite these before quoting them in the pitch** — the discipline is the same as with the calibration numbers: an unsourced benchmark that a judge knows to be wrong costs more than it gains.

| Parameter | Value used | Plausible range | Basis |
|---|---|---|---|
| Own-price elasticity (brand level, by category) | −1.4 to −2.6 | −0.5 to −4 | CPG brand-level meta-analyses (Bijmolt et al. 2005 report a mean near −2.6) |
| Cross-price elasticity vs competitors | +0.3 to +0.8 | 0 to +1.5 | Category-dependent |
| Short-run advertising elasticity | 0.08 to 0.18 | 0.01 to 0.3 | Advertising-elasticity meta-analyses (Sethuraman et al. 2011 report ≈ 0.12 short-run) |
| Digital adstock half-life | 5–10 days | 2 days – 3 weeks | Shorter for performance channels, longer for brand |
| Baseline fill rate | 95–98 % | 92–99 % | Typical CPG service-level targets |
| Return rate (home & personal care) | 2–5 % | 1–8 % | Far below apparel; category-appropriate |
| Promo lift (price promo) | 1.4× – 2.6× | 1.2× – 5× | Depth-dependent |
| Weekly seasonality amplitude | ±15–30 % | ±10–40 % | Channel-dependent |
| Diwali-window uplift | 1.6× – 2.2× | — | With ~10-day pre-build and ~7-day post-lull |
| Daily revenue CV (national) | 0.18 – 0.25 | — | Sanity band for aggregate volatility |

### 4.4 Endogeneity — the part most teams will get wrong

If marketing spend is exogenous random noise, a regression recovers its elasticity trivially and the econometrics in our architecture is theatre. **Real budgets respond to performance**, which creates simultaneity and biases naive estimates upward. We plant this deliberately:

```
spend[c, w] = planned_budget[c, quarter(w)]                       # set quarterly, EXOGENOUS
            × (1 + κ · (revenue[w−1] / target[w−1] − 1))          # tactical response, κ ≈ 0.3
            × seasonal_media_multiplier[w]
            × exp(noise)
price/promo decisions   respond to inventory cover and competitor moves
replenishment           responds to a demand forecast (which is itself wrong in realistic ways)
```

Three payoffs from this one design choice:

1. **The problem becomes real.** Naive OLS will recover an inflated marketing elasticity. Our DAG-driven specification, event-study identification and quarterly-plan variation recover something close to truth. Because we know the true value, we can *show both numbers side by side*.
2. **It gives us an identification strategy to talk about.** The quarterly planned budget is set months ahead for reasons unrelated to this week's demand — quasi-exogenous variation we can lean on, and a genuine answer when a judge asks "how do you know that's causal and not just correlated?"
3. **It creates a killer eval line:** *"True marketing elasticity 0.15. Naive OLS says 0.28 — biased up 87 %. Our specification says 0.16 [0.10, 0.22]. Here is the code."* That single comparison does more for credibility than any amount of architecture prose.

Keep κ moderate (≈ 0.3). Too strong and the parameter becomes unidentifiable, which is a different and less useful demo.

### 4.5 Deliberate analytical traps

Planted because an engine that survives them is demonstrably better than one that was never tested:

| Trap | What it looks like | What it tests |
|---|---|---|
| **Simpson's paradox** | National `gross_margin_pct` flat; premium mix up, within-segment margin down in both segments | Adtributor's nested-segment reversal check |
| **Correlated media channels** | Paid social and display budgets move together (ρ ≈ 0.8) for two quarters | VIF gate → grouped attribution rather than false precision |
| **Legitimate outlier** | A one-off ₹1.2 cr institutional bulk order on a single day | Must be flagged as a data event, *not* narrated as a trend |
| **Post-festival lull** | Sharp legitimate drop 3 days after Diwali | Seasonality handling; a naive detector fires, ours must not |
| **Red-herring event** | A dramatic competitor launch that post-dates the revenue drop by 4 days | The timing gate |
| **Silent unit change** | One source switches paise → rupees mid-history | Schema/unit drift detection; catastrophic if missed |
| **Regime break** | A permanent price-list revision shifting level ~6 % | Changepoint handling; calibration window exclusion |
| **Confounded pair** | A price rise and a promo end on the same day | Whether attribution separates them or honestly reports them jointly |

---

## 5. Source projection (L4) — one truth, eleven disagreeing views

Layer 3 holds the complete, perfectly-known business reality. No system sees it. Each source is a **lossy projection** with its own definitions, and the disagreements between them are where the brief's "reconciles data and business context across heterogeneous sources" actually lives.

**Designed disagreements** (each one is a reconciliation check the pipeline must handle):

| Disagreement | Cause | Magnitude | Consumed by |
|---|---|---|---|
| OMS net revenue ≠ ERP net revenue | ERP recognises on invoice, excludes shipping; OMS on order | 1–3 % | Definitional reconciliation; contract versioning |
| MarTech attributed revenue ≠ OMS order-linked revenue | Platform attribution windows, view-through, cross-device | 5–15 % normally, **18 % in Scenario B** | `blended_roas` hard gate |
| WMS units shipped ≠ OMS units sold | Midnight cut-off, partial shipments, T+2 view | 0.5–2 % | Freshness-aware joins |
| Inventory snapshot ≠ implied position | Snapshot timing, shrinkage, in-transit | 1–4 % | Fill-rate driver quality |
| Competitor panel price ≠ actual shelf price | Scrape timing, regional variation, match error | 2–8 % where matched, **40 % unmatched** | Entity-link confidence in evidence |

The engine is *expected* to live with the normal-range disagreements and to **abstain** when one exceeds its contract tolerance. That is the whole point of Scenario B.

### 5.1 The source contract

A sibling to the KPI contract, and a genuinely new artifact for this submission. The KPI contract governs *meaning*; the source contract governs *arrival*. Ingestion is driven entirely by these files — there is no hand-written loader per source.

```yaml
# sources/martech_weekly.yaml
source_id: martech_weekly
system: "Ad platform aggregator (agency-managed export)"
owner: marketing-analytics
transport: sftp_drop                 # sftp_drop | s3_prefix | api_pull | db_replica | file_watch
format: parquet
landing_path: "landing/martech_weekly/week={iso_week}/"

arrival:
  cron: "0 6 * * MON"                # weekly, Monday 06:00
  tz: Asia/Kolkata
  jitter_minutes: 40                 # real feeds are never punctual
  failure_probability: 0.02          # sometimes it just does not come
latency_sla_hours: 8                 # after which freshness goes amber, then red

covers:
  grain: [iso_week, campaign_id, channel]
  period: previous_iso_week

restatement:
  expected: true
  window_days: 14                    # re-sends the last two weeks, revised
  policy: supersede_by_batch         # newer batch for the same period wins

schema:
  version: 2
  columns:
    iso_week:                {type: string, pk: true}
    campaign_id:             {type: string, pk: true}
    channel:                 {type: string, pk: true, allowed: [paid_social, search, display, affiliate, influencer, ctv]}
    spend_inr:               {type: decimal, min: 0, max: 50000000, null_frac_max: 0.0}
    impressions:             {type: bigint, min: 0}
    clicks:                  {type: bigint, min: 0}
    attributed_revenue_inr:  {type: decimal, min: 0, null_frac_max: 0.02}
  drift_policy: quarantine_and_alert  # unknown/renamed column never silently ignored

watermark: iso_week
idempotency: [batch_id, row_hash]

expectations:
  row_count: {min: 200, max: 2000}
  clicks_le_impressions: true
  spend_zero_with_positive_clicks: {max_frac: 0.01}

reconciliation:
  - against: oms_orders
    measure: attributed_revenue_inr
    tolerance_pct: 5.0
    window: iso_week
    on_breach: block_attribution      # detect and describe, but do NOT attribute drivers

history_available_months: 12
known_issues: [missed_week, attribution_lag, campaign_id_reuse, currency_unit_change_2025_02]
classification: internal_marketing
```

Every source gets one. The ingestion engine reads these and needs no per-source code — which is both better engineering and a strong thing to show a judge: *"adding a twelfth source is a YAML file, not a sprint."*

---

## 6. Unstructured corpus (L6)

The evidence layer is only as good as the corpus, and a corpus of generic filler proves nothing. Ours is **generated from the event ledger**, so every document is causally consistent with the numbers — and, critically, the *absence* of documents is designed too.

### 6.1 Document types (~600–800 documents over 36 months)

| Type | Volume | Source | Carries |
|---|---|---|---|
| Ops incident tickets | ~180 | I5 | Timestamps, DC, severity, resolution; **PII** |
| Customer support tickets | ~40 k rows, ~3 k with rich text | I5 | "item unavailable", damage, delivery; **PII** |
| Pricing / promo memos | ~90 | I8 | **Effective date ≠ publish date**; free-text conditions |
| Campaign briefs & change notes | ~120 | I3/I8 | Budget shifts, creative refresh, pause decisions |
| Supplier / logistics emails | ~70 | I8 | Inbound delays, allocation, partial commitments |
| News & PR articles | ~140 | E5 | Competitor launches, category news, **syndicated duplicates** |
| Internal weekly business reviews | ~150 | I8 | Human interpretation — sometimes *wrong*, deliberately |
| Marketplace reviews | ~2 k | E6 | Sentiment noise; a few factual availability complaints |

### 6.2 The rules that make the corpus useful

1. **Causal consistency.** A document referencing an outage exists only if the outage is in the event ledger, and its timestamps agree with it.
2. **Deliberate evidence gaps.** **~15 % of planted events get no document at all.** These are the cases where attribution is statistically strong but externally uncorroborated — exactly the cases where confidence should fall and, sometimes, the engine should abstain. Without this, the sufficiency check is never exercised.
3. **Contradiction.** ~10 % of events get two documents that disagree (ops ticket says "resolved 06:00", supplier mail next day says "still constrained"). Tests `evidence_agreement` and hedged language.
4. **Syndication.** Each significant news item is duplicated across 3–6 outlets with rewritten headlines and near-identical bodies. If dedup fails, noisy-OR treats one story as six independent confirmations and confidence is inflated — the exact failure the Round 1 spec warned about. **This is the test for it.**
5. **Dual dates.** ~20 % of memos and news carry an effective date materially later than the publish date (a price revision announced in February, effective 1 April). If we index only by publish date, the April anomaly cannot find its own cause.
6. **Post-dated red herrings.** ~8 % of events get a dramatic, topically-relevant document dated *after* the effect. The timing gate must eliminate them.
7. **Realistic PII, never real.** Names from a fictional-name generator; emails at `example.com`; phone numbers in a reserved/non-routable pattern; order IDs in our own format. Masking is then demonstrated at ingestion — and nothing in the repo resembles a real person's data, which matters both ethically and if this repo is ever shared.
8. **Human error.** A handful of weekly-review documents contain confidently wrong explanations ("the drop is clearly seasonal"). Good material for the demo: the engine's evidence disagrees with the human narrative, and it says so.

### 6.3 How to generate them

**Hybrid, and frozen.** Templates with slot-filling for the high-volume routine documents (support tickets, reviews, routine notes) — deterministic, free, reproducible. For the ~150 documents that carry scenario weight (incident reports, pricing memos, campaign briefs, news), **generate once with an LLM, review by hand, and commit them to the repo as fixtures.** Never generate corpus text at demo time: it costs money, introduces nondeterminism, and puts an API call on the critical path of a rehearsed demo.

---

## 7. Pathology catalog (L5)

The heart of the design. Each row: a complexity named in the brief → the concrete defect we plant → the component it exercises → where it shows up in the demo. **If a row has no demo moment, we still plant it — silent robustness is worth more than it costs. If a brief complexity has no row, we have a gap.**

| # | Brief complexity | Planted defect | Exercises | Demo moment |
|---|---|---|---|---|
| P1 | Different refresh cadences | Daily / weekly / T+2 / monthly feeds | Freshness tracker, arrival scheduler | Landing-zone monitor |
| P2 | Different grains | SKU-day vs campaign-week vs category-month | Contract compiler, grain alignment | Evidence drawer lineage |
| P3 | Restatement | MarTech revises last 14 days each drop | Watermark rewind, supersede-by-batch | Scenario B |
| P4 | Late arrival | WMS T+2, sometimes T+3 | Lag-aware labelling ("as of T−2") | Scenario A card |
| P5 | Missing period | One MarTech week never arrives | Freshness hard gate | **Scenario B abstention** |
| P6a | Duplicate delivery | Same batch_id sent twice | Idempotency by batch registry | Ingestion log |
| P6b | Silent duplication | Same rows, new batch_id | Dedup by row_hash | Ingestion log |
| P7 | Schema drift | `spend_inr` → `spend_amount` at a known date | Drift detection → quarantine | Admin panel |
| P8 | **Silent unit change** | Paise → rupees in one feed, Feb 2025 | Range expectations catch a 100× jump | Admin panel — the scariest one |
| P9 | Timezone mismatch | One source stamps UTC | Timezone normalisation at silver | Boundary-day reconciliation |
| P10 | Definitional change | `net_revenue` stops including shipping, Jan 2025 | **Contract versioning** | Governance story |
| P11 | Currency | A small export unit reports USD | FX conversion with rate-date policy | Silver transform |
| P12 | Null spike | Region mapping breaks for 3 days | DQ null-fraction gate | DQ dashboard |
| P13 | Unknown members | New SKUs transact before PIM update | `UNKNOWN` bucket + flag | Scenario C |
| P14 | Hierarchy change | Two regions merge mid-history (restructure) | Slowly-changing dimension handling | Analyst view |
| P15 | Partial coverage | Competitor panel covers ~60 % of SKUs | Coverage-aware confidence | Confidence breakdown |
| P16 | Fuzzy entity match | Competitor SKU match at ~85 %, scored | `EntityLinkConf` in evidence | Evidence drawer |
| P17 | Short external history | Competitor data starts 14 mo in | Window selection, model eligibility | Analyst view |
| P18 | Fiscal vs ISO calendars | FY Apr–Mar vs ISO weeks | Calendar spine | Contract |
| P19 | Sparse history | "Aurora X" launched 18 days ago | EB pooling, sparse policy | **Scenario C** |
| P20 | Intermittent series | A slow SKU with many zero days | Croston path in adaptation matrix | Adaptation table |
| P21 | Legitimate outlier | One-off bulk institutional order | Materiality vs anomaly distinction | Specificity demo |
| P22 | Regime break | Permanent price-list revision | Changepoint; calibration exclusion | Backtest |
| P23 | Simpson's paradox | Margin flat, segments diverging | Nested-segment reversal check | Analyst view |
| P24 | Collinear drivers | Social + display move together | VIF gate → grouped attribution | Scenario A diagnostics |
| P25 | Endogeneity | Spend responds to prior-week revenue | DAG specification, identification | **Naive-vs-ours eval** |
| P26 | Syndicated duplicates | One press release, six outlets | MinHash-style dedup at ingestion | Evidence corroboration |
| P27 | PII in text | Names, emails, phones in tickets | Masking before indexing | Governance story |
| P28 | Contradictory evidence | Ticket vs supplier email disagree | Evidence agreement, hedged tier | Moderate-tier example |
| P29 | Post-dated red herring | Competitor launch 4 days after the drop | Timing gate | Scenario A |
| P30 | Clean control period | A stretch with nothing wrong | False-positive rate measurement | Backtest |

Thirty defects against ten brief complexities. **Every complexity the brief names is physically present in the data**, which is the claim we want to be able to make out loud.

---

## 8. The event ledger

Everything interesting in the world is an **event** with an explicit, machine-readable definition. Events are the input to the simulator, the seed for the corpus, and the key for ground truth.

```yaml
- event_id: EV-2026-0311
  type: warehouse_outage                # price_change | promo | media_shift | outage |
                                        # supplier_delay | launch | competitor_action |
                                        # bulk_order | regime_break | data_incident
  scope: {warehouse: DC-North, skus: [SKU-0031, SKU-0044, SKU-0102]}
  window: {start: 2026-03-06T22:40+05:30, end: 2026-03-12T09:00+05:30}
  magnitude: {fill_rate_floor: 0.814, substitution_leak: 0.35}
  detectability: high                   # controls how visible it should be
  evidence:
    documents: 3                        # 0 = deliberate evidence gap
    contradiction: false
    syndication: 1
    post_dated_decoy: true
  ground_truth: {compute: true, method: shapley_within_window}
  demo_role: scenario_A_primary
```

Three event *sets* are maintained:

- **`scenarios/`** — the four scripted demo scenarios, hand-authored, stable, never randomised.
- **`calibration/`** — several hundred randomised events for the confidence backtest (§9.3).
- **`ambient/`** — routine background events (normal promos, ordinary campaign changes, minor supplier slips) that make the world feel lived-in and give the detector realistic non-events to ignore.

---

## 9. Ground truth (L7) — the part real data cannot give us

### 9.1 Common random numbers — the detail that silently breaks everything

To compute "what would have happened without event E", we re-run the simulator with E removed and everything else identical. That only works if **removing an event does not perturb any other random draw**. A single sequential RNG stream fails this: remove one event, every subsequent draw shifts, and the "counterfactual" is contaminated by noise differences that look exactly like a causal effect.

The fix is mandatory and must be in the code from day one:

```python
def rng_for(*keys) -> np.random.Generator:
    """Every stochastic draw is addressed by a stable content key, never by stream position."""
    h = blake2b(repr((SEED, *keys)).encode(), digest_size=8).digest()
    return np.random.default_rng(int.from_bytes(h, "big"))

# usage — the key set fully determines the draw
eps = rng_for("demand_noise", sku, region, channel, date).normal()
```

**Acceptance test:** run the simulator with an event that has zero magnitude; the output must be byte-identical to the run without that event. If it is not, the RNG is positional somewhere and every ground-truth number in the submission is wrong. This test goes in first.

### 9.2 Counterfactuals: windowed, and Shapley for interacting events

**Windowed re-simulation.** The process has bounded memory — adstock ~3 weeks, inventory ~6 weeks, AR(1) shock ~2 weeks. So a counterfactual only needs re-simulating over `[event_start − 60d, event_end + 60d]`, warm-started from the identical factual state. Full-history re-runs are unnecessary and would make the calibration corpus unaffordable.

**Shapley over event subsets.** In Scenario A three events overlap (outage, media cut, price rise). One-at-a-time counterfactuals do not sum to the total when events interact — and they *do* interact here, because a stockout suppresses the volume that marketing would otherwise have driven. With `n` events in a window, run all `2^n` subsets (n = 3 → 8 runs, cheap) and compute the **Shapley value** of each event: its average marginal contribution across all orderings.

Two reasons this is the right choice rather than an indulgence:

- It is **exact, additive and order-independent** — the contributions sum to the total movement with no interaction residual to explain away.
- It is **philosophically consistent with the engine's own method.** The Bennet decomposition in the attribution ladder is chosen precisely because it is symmetric and order-independent. Scoring a symmetric estimator against a symmetric ground truth is coherent; scoring it against one-at-a-time deltas would penalise it for interactions it correctly shares out.

Both **total effect** (full re-run, includes operational feedback such as replenishment reacting) and **direct effect** (downstream decisions frozen) are recorded. The engine is scored against **total effect** for business questions ("what did the outage cost us"), since that is what a CFO means.

### 9.3 The calibration corpus — how the reliability table gets built

The isotonic calibration in the confidence engine needs a few hundred labelled cases spanning the whole score range. The four demo scenarios cannot provide that. So a **stochastic event generator** produces **≥ 400 events** across the 36-month history, with controlled variation along the four axes that actually move the confidence score:

| Axis | Sampled over | Purpose |
|---|---|---|
| Magnitude | Just-below-materiality → very large | Spreads `c1` detection strength |
| Segment concentration | Single SKU → diffuse across all regions | Spreads `c2` attribution stability |
| Evidence availability | 0 documents → 5 corroborating documents | Spreads `c5` evidence support |
| Data condition at the time | Clean → stale feed / reconciliation breach | Spreads `c4` data trust |

For each, the ledger records the true cause, true contribution, and true segment. Running the pipeline over all of them yields `(raw_score, was_the_top_cause_correct)` pairs → the isotonic map, the tier boundaries, the reliability curve, expected calibration error, and the per-tier table.

**Hygiene rules, because a mis-built calibration set is worse than none:**

- **Temporal split.** Fit the isotonic map on events before a cut date; report the per-tier table on events after it. Rolling-origin, never in-sample.
- **Scenario events excluded** from the calibration fit entirely — otherwise the demo cases are scored by a map trained on themselves.
- **Regime-break windows excluded** from conformal calibration windows.
- **Report `n` per tier.** A tier with 11 observations does not get a percentage to two decimal places.
- **Say it is synthetic.** Every time. The table validates the *mechanism*; it does not forecast real-world accuracy.

---

## 10. Live intake harness (L8)

This is the half of the request most teams skip, and it is where "reconciles heterogeneous sources with different refresh cadences" stops being a slide and becomes visible behaviour. **The prototype must never read a finished table. It must watch files arrive.**

### 10.1 Components

```
┌─────────────────┐   advances sim time
│    SimClock     │   modes: backfill · replay(N×) · live(1×) · step
└────────┬────────┘
         │ tick
         ▼
┌─────────────────────────────────────────────────────────────┐
│  ArrivalScheduler                                            │
│   for each source contract: next_arrival = cron + jitter     │
│   rolls failure_probability → sometimes nothing arrives      │
│   emits restatement batches inside the restatement window    │
└────────┬────────────────────────────────────────────────────┘
         │ writes
         ▼
┌─────────────────────────────────────────────────────────────┐
│  LANDING ZONE  (partitioned files + manifests, S3-like)      │
│   landing/oms_orders/dt=2026-03-09/batch_….parquet           │
│                                    batch_….manifest.json     │
└────────┬────────────────────────────────────────────────────┘
         │ file appears
         ▼
┌─────────────────────────────────────────────────────────────┐
│  SourceWatcher → IngestionRunner (per source, idempotent)    │
│   bronze → dq gates → silver conform → gold marts            │
│   updates watermarks, freshness, audit                       │
└────────┬────────────────────────────────────────────────────┘
         │ emits DataLandedEvent(source, period, watermark)
         ▼
┌─────────────────────────────────────────────────────────────┐
│  PipelineTrigger — wakes ONLY the KPIs whose contracts       │
│   depend on that source; enqueues detection                  │
└─────────────────────────────────────────────────────────────┘
```

Note the last box: the system is **event-driven, not cron-driven at the analytics layer**. A MarTech drop wakes `blended_roas` and `marketing_spend`; it does not re-scan fill rate. This is both correct engineering and the mechanism behind the cost story — work happens when data changes, not on a timer.

### 10.2 Batch manifest

Every landing writes a sidecar manifest. This is what makes idempotency, restatement and audit tractable:

```json
{"source_id":"martech_weekly","batch_id":"mtw_20260316T0612_a41f",
 "generated_at_sim":"2026-03-16T06:12:00+05:30","received_at":"2026-03-16T06:12:04+05:30",
 "covers":{"grain":"iso_week","periods":["2026-W11","2026-W10","2026-W09"]},
 "is_restatement":true,"supersedes":["mtw_20260309T0604_9c2e"],
 "row_count":847,"checksum":"sha256:…","schema_version":2,
 "producer_note":"weeks W09–W10 revised per platform attribution update"}
```

### 10.3 Operating modes

| Mode | Behaviour | Used for |
|---|---|---|
| **Backfill** | Generate 36 months, load as a bulk historical load exactly as a real deployment would begin | Setup; also demonstrates cold-start |
| **Replay(N×)** | From a go-live date, advance sim time at N× (default 1 day ≈ 2 s). Sources land on their real schedules, late, jittery, occasionally missing | The main demo |
| **Live(1×)** | Wall-clock. Feeds land at true cadence | Long-running exhibit; leave it up between judging slots |
| **Step** | Advance one arrival at a time under manual control | Debugging; also for a judge who wants to inspect each step |

### 10.4 Demo controls — the interactive part

Four buttons on the admin panel turn a scripted demo into something a judge can poke:

1. **Inject event** — fire an outage/price change/media cut *now*. Watch the feed land, the detector fire, the ladder run, the insight card appear ~40 s later. *"You choose when it breaks."*
2. **Break a feed** — pause MarTech. Watch the freshness tile go amber then red, `c4` decay, and the engine move from publishing to hedging to **abstaining**. This makes abstention interactive rather than narrated, and it is the single most persuasive thing in the demo.
3. **Send a restatement** — re-drop last week revised. Watch the figure change, the insight supersede itself, and the audit trail record both versions.
4. **Time-travel** — jump the clock to any date and let the system rebuild state.

The risk to manage: these must be *rehearsed*. An interactive control that misbehaves on stage is worse than no control. Each gets a scripted happy path and a tested reset.

### 10.5 Late, out-of-order and superseding data

The rules the ingestion layer implements, stated once here so they do not get invented ad hoc later:

- **Watermark per source**, advanced only when a period is complete; a late batch for an older period **rewinds** the watermark for that period and triggers recomputation of dependent KPIs for that window only.
- **Supersede-by-batch** for restating sources: newest batch covering a period wins; prior versions are retained (never overwritten) so the audit trail can show what we believed and when.
- **Insights are versioned against watermarks.** An insight computed on data that has since been restated is marked `superseded`, and — if the conclusion changed materially — the system says so rather than silently swapping the number. *"We told you −12.4 % on Monday; the marketing restatement moved it to −11.1 %; the driver ranking is unchanged."* That behaviour is rare in commercial BI tools and is worth showing.
- **Idempotency** by `(source_id, batch_id)` in a batch registry, plus `row_hash` dedup within a period.
- **Quarantine, never drop.** Rows failing expectations go to a quarantine table with the reason; they are visible, countable, and feed the DQ score. Nothing is silently discarded.

---

## 11. Ingestion pipeline (bronze → silver → gold)

| Layer | Contents | Guarantees |
|---|---|---|
| **Bronze** | Raw rows exactly as delivered + `batch_id`, `received_at`, `sim_time`, `source_file`, `row_hash`, `schema_version` | Immutable, append-only, replayable. Never edited. |
| **Silver** | Conformed: calendar spine (every date exists, gaps explicit), conformed dimensions (SKU→category, warehouse→region), **timezone normalised to IST**, **units normalised**, **currency converted at a policy rate-date**, deduplicated, PII masked (text sources) | One row per business key per period, with provenance to bronze |
| **Gold** | Contract-grain marts, one per KPI, plus the dimensional cube for attribution and the pre-joined driver panel for the econometrics | Matches exactly what the KPI contract's `measure_sql` expects |

Cross-cutting, computed at every load and surfaced in the evidence drawer: **freshness** (per source: last successful batch, period covered, SLA status), **DQ results** (per expectation: pass/fail/quarantined counts), **reconciliation results** (per configured check), and a full **audit** row for every load and every query.

**Design rule:** the analytical engine never reads bronze or silver. It reads gold *through the contract compiler*, so entitlements and definitions apply uniformly whether the caller is a scheduled scan, a persona narrative, or an analyst's ad-hoc question.

---

## 12. Realism validation suite

Synthetic data is only as credible as its acceptance tests. This suite runs in CI and is a **demo artifact in its own right** — when a judge asks "is this realistic?", the answer is a test report, not an assurance.

### 12.1 Structural tests (the data has the shape we claim)

| Test | Assertion |
|---|---|
| Weekly seasonality | ACF of daily revenue has a significant peak at lag 7; amplitude within ±10–40 % |
| Annual seasonality | Two-plus full cycles present; festival windows show the designed uplift and post-lull |
| Autocorrelation planted | AR(1) coefficient of the company shock recovers to φ ≈ 0.35 ± 0.08 |
| Heteroscedasticity planted | Breusch–Pagan **rejects** on raw residuals; variance is higher in promo and festival windows |
| Whitening works | After AR(p) whitening, Ljung–Box does **not** reject on clean windows |
| Distribution shape | Daily national revenue right-skewed, CV in 0.18–0.25 |
| Intermittency | At least one SKU with > 40 % zero days (Croston case exists) |
| Benford's law | Leading-digit distribution of transaction amounts follows Benford within tolerance — a genuine signature of naturally-generated monetary data, and a cheap, memorable credibility check |

### 12.2 Recoverability tests (the truth is findable)

| Test | Assertion |
|---|---|
| Price elasticity | Recovered from a clean window within ±20 % of the planted value |
| Marketing elasticity | Recovered within ±25 %; **and the naive-OLS estimate is demonstrably biased upward** (§4.4) |
| Adstock half-life | Profile-likelihood grid recovers the planted half-life within ±2 days |
| Fill-rate coefficient | Recovered within ±20 % |
| Event effects | Shapley ground truth for Scenario A sums to the observed gap within 1 % |
| Distractors | Planted non-events do **not** clear the materiality gate |
| Clean period | False-positive rate over the control window ≤ the configured FDR level |

### 12.3 Domain plausibility tests (a practitioner would recognise this business)

Fill rate 92–99 %; returns 2–5 %; gross margin by category in a set band; D2C share ≈ 40 %; promo lift 1.4×–2.6×; ROAS by channel in a plausible spread; no negative prices, no impossible quantities; channel day-of-week patterns differ in the expected direction.

### 12.4 Defect-presence tests

One test per pathology in §7 — asserting each defect is actually present and detectable. **P8 (silent unit change) and P26 (syndication) get explicit tests**, because those are the two most likely to be quietly lost in a refactor and the two whose absence would most flatter the engine.

---

## 13. Scale, performance, layout

**Volumes** (comfortable for DuckDB on a laptop):

| Asset | Rows | Size |
|---|---|---|
| OMS daily fact | ~1.15 M | ~120 MB parquet |
| WMS fulfilment | ~660 k | ~60 MB |
| MarTech weekly (incl. restatements) | ~45 k | ~5 MB |
| Competitor prices | ~42 k | ~4 MB |
| Support tickets | ~44 k (3 k rich text) | ~30 MB |
| Inventory snapshots | ~660 k | ~50 MB |
| Corpus documents | ~800 | ~6 MB |
| Ground-truth ledger | ~450 events × counterfactual series | ~40 MB |
| **Total** | **≈ 2.6 M rows** | **≈ 320 MB** |

**Performance targets:** full 36-month generation ≤ 90 s · windowed counterfactual ≤ 2 s · full calibration corpus (400 events, windowed) ≤ 20 min as a one-off CI job · replay mode 1 sim-day ≤ 2 s wall.

**Order-level detail** is synthesised only for a recent 90-day window (for realism and any transaction-level drill-down); the rest of history stays at daily aggregate grain. Generating three years of order lines would multiply volume tenfold for no evaluative gain.

```
datagen/
├── world/         config.yaml · calendar.py · geography.py · catalog.py · seeds.py
├── latent/        demand.py · noise.py · elasticities.py
├── decisions/     pricing.py · media.py · replenishment.py · assortment.py
├── outcomes/      orders.py · fulfilment.py · returns.py · inventory.py
├── events/        ledger.py · scenarios/*.yaml · calibration_gen.py · ambient.py
├── projection/    oms.py · wms.py · martech.py · competitor.py · tickets.py · pim.py
├── defects/       catalog.py · injectors.py          # one function per pathology
├── corpus/        templates/ · fixtures/ (LLM-generated, committed) · assemble.py
├── truth/         crn.py · counterfactual.py · shapley.py · ledger_writer.py
├── harness/       clock.py · scheduler.py · landing.py · manifest.py · controls.py
└── validate/      test_structural.py · test_recoverability.py ·
                   test_plausibility.py · test_defects.py
```

---

## 14. Build order for the data layer

Each step ends green before the next begins. Steps D1–D3 are the ones that, if wrong, invalidate everything downstream — so they get disproportionate care.

| # | Step | Output | Gate |
|---|---|---|---|
| **D1** | World config + calendar + catalog + **CRN infrastructure** | `world.yaml`, dimension tables, `rng_for()` | **Zero-magnitude-event test passes byte-identically.** Nothing proceeds until it does |
| **D2** | Latent demand + noise (L1) | Clean demand series | Structural tests §12.1 green: AR(1) recovered, BP rejects, ACF peak at 7 |
| **D3** | Decisions + outcomes (L2–L3) with endogeneity | Orders, inventory, fill rate, returns | Recoverability §12.2: elasticities recover on a clean window; **naive OLS visibly biased** |
| **D4** | Event ledger + scenario authoring | 4 scenarios + ambient events | Scenario A's three events produce the intended ≈ −12 % weekly movement |
| **D5** | Ground truth: windowed counterfactual + Shapley | `ledger.parquet` | Shapley contributions sum to observed gap within 1 % |
| **D6** | Source projection (L4) | 11 source views with designed disagreements | Reconciliation deltas fall in their intended ranges |
| **D7** | Defect injection (L5) | Pathology catalog applied | §12.4: every defect present and detectable |
| **D8** | Corpus (L6) | ~800 docs, fixtures committed | Evidence gaps, contradictions, syndication, dual dates and decoys all present at target rates |
| **D9** | Source contracts + landing zone + manifests | `sources/*.yaml`, populated `landing/` | Contracts validate; manifests well-formed |
| **D10** | Harness: clock, scheduler, watchers, controls | Replay + live modes | 90 sim-days replay end to end; break-a-feed and inject-event controls behave |
| **D11** | Ingestion: bronze/silver/gold, DQ, freshness, reconciliation | Populated warehouse | Duplicate batch is idempotent; restatement supersedes; stale feed flips freshness red |
| **D12** | Calibration corpus generation | ≥ 400 labelled events | Score spread covers [0,1]; temporal split honoured |

**Estimate:** 8–11 working days for one focused builder, or ~6 with two people splitting at D6 (one takes projection/defects/corpus, the other harness/ingestion). That is a large fraction of the schedule — which is the correct allocation, because every claim the engine makes is a claim about this data.

---

## 15. Risks specific to the data layer

| Risk | Why it bites | Mitigation |
|---|---|---|
| **Positional RNG breaks ground truth** | Silent; every attribution-accuracy number becomes fiction | D1 gate test; content-addressed `rng_for()` from the first commit |
| **Data too clean → engine looks untested** | The most common hackathon failure | Pathology catalog is built *before* the happy path; §12.4 asserts defects exist |
| **Data too hostile → nothing is recoverable** | Endogeneity or noise so strong that estimates are meaningless | κ ≈ 0.3 cap; §12.2 recoverability tests are the guardrail in both directions |
| **Simulator complexity overruns the schedule** | Layers 2–3 can expand indefinitely | Freeze L2 decision rules after D3; new realism goes into the defect catalog, not the physics |
| **Calibration corpus too small or in-sample** | The trust artifact collapses under one question | ≥ 400 events, temporal split, `n` reported per tier |
| **Corpus generated at demo time** | Cost, nondeterminism, API on the critical path | Fixtures generated once and committed |
| **Interactive demo control misfires on stage** | Worse than not having it | Each control gets a scripted path, a tested reset, and a rehearsal |
| **Synthetic numbers quoted as real** | Credibility loss that contaminates everything else | Every chart and table carries a "simulated data" label; say it aloud in the pitch |

---

## 16. Decisions to confirm before D1

1. **Company archetype** — Meridian Consumer Brands (India D2C + retail home & personal care) as specified? It is chosen because it makes price–volume–mix, marketing adstock and fill rate all simultaneously meaningful. A different vertical is fine but changes §1–§5 substantially.
2. **Scale** — 150 SKUs × 5 regions × 4 channels × 36 months (~1.15 M fact rows)? Bigger makes the Adtributor search more impressive and everything slower; smaller starts to look like a toy.
3. **Source count** — build 11 feeds (5 full + 4 light + 2 corpus-only) and declare 5 more, against a brief minimum of 2–3? This is the main scope dial in this document.
4. **Calibration corpus size** — 400 events? Below ~250 the per-tier table gets thin; above ~600 the CI job gets slow.
5. **Corpus text** — LLM-generate ~150 scenario documents once and commit them as reviewed fixtures, templates for the rest?
6. **Demo mode** — is replay-with-interactive-controls the primary demo (my recommendation), or a pre-computed static walkthrough with replay as a bonus? The former is far more persuasive and carries live-demo risk.

My recommendations: **1** as specified · **2** as specified · **3** yes — depth here is cheap credibility · **4** 400 · **5** yes · **6** replay primary, with a recorded fallback video and a static path that needs no clock.

---

*All figures in this document describe a simulated company. Parameter ranges cited from CPG marketing-science literature should be verified against the named sources before being quoted in the submission.*




