# Insight Copilot — the seven-minute demo

> Every figure below comes from a simulation. Meridian Consumer Brands is a fictional
> company. Say this out loud once at the start; it is the first thing an evaluator
> needs to know and the last thing they should have to ask.

## Before you start

```bash
make demo-reset       # optional; only if a previous run left state behind
make demo             # loads the world, backfills, replays 30 days, runs the
                      # scenario, pre-warms every persona's narrative, serves :8000
make dev-frontend     # in a second shell — UI on http://localhost:5173
```

Wait for these four lines. If any is missing, stop and read it rather than clicking on.

```
OK    world loaded and 30 sim-days replayed: … batches, … rows
OK    scenario run: net_revenue −41.46% on 2026-03-06 at p = 0.0026; tier Moderate
OK    narrative cache pre-warmed: 4 narrative(s) cached in … ms
OK    serving on http://127.0.0.1:8000 — all data is simulated
```

Open <http://localhost:5173>. Leave the role on **CFO** and the persona on **analyst**.

---

## 0 · The frame — 30 seconds

**Say:** "This watches KPIs, decides what is worth saying, and refuses when it cannot
tell. Every number on the screen was computed by SQL or statsmodels. The language model
only writes the sentence, and a verifier checks the sentence's numbers against the
computation before you see it."

**Screen:** the Feed. The top bar shows the simulated clock, the role selector, the
persona selector, and a **Provenance** toggle. Below it, the **Sources** strip: eleven
tiles, each green.

**Point at:** the caption on the sources strip — *"Green means the drop that was due has
arrived."* Freshness is measured against each contract's own SLA, not a wall clock.

---

## 1 · Scenario A, the flagship — 2 minutes

**Click:** the `net_revenue` card in the Feed.

**Expect:** the insight detail. A headline of **−41.46%** against the counterfactual, a
tier chip reading **Moderate**, and beneath it the attribution ladder — four rungs, one
open at a time, starting on *Where*.

**Say, walking down the ladder:**

- **Where.** Adtributor scores every segment by explanatory power times a Jensen-Shannon
  surprise term, then bootstraps the ranking. The bootstrap stability is on screen — a
  segment that wins fewer than 90% of resamples is a shortlist entry, not a named cause.
- **Kind.** Click **What kind**. The Bennet decomposition splits the movement into
  price, own-volume and mix. **Point at:** the waterfall, and at its caption — it is
  anchored on *the previous window*, not on the counterfactual, because that is the
  comparison this rung actually makes. The three parts sum to the change between those
  two windows exactly; that is an arithmetic identity and it is property-tested, not
  asserted.
- **Why.** Click **Why**. Two estimators are fitted — SARIMAX with exogenous regressors, and OLS with
  Newey-West standard errors — and their *disagreement* is reported rather than resolved
  by picking a favourite.

**Click:** **Provenance on** in the top bar.

**Expect:** every figure gains its method, its freshness, and its lineage. **Say:** "This
is the fourth law. A claim you cannot trace is a claim you should not act on."

- **Event.** Click **What event** for the documents that survived the timing gate.

**Point at:** the evidence list, and specifically the rejected document. A competitor
press release sits in the corpus dated *after* the effect began. The timing gate rejects
it on the contract's declared lag profile, so it never reaches the narrative — the decoy
is planted precisely to see whether a system will grab it.

---

## 2 · Confidence, and why it is not a vibe — 1 minute

**Click:** the confidence chip, or scroll to the **Confidence** panel.

**Expect:** six measured signals — detection strength, attribution quality, statistical
validity, data trust, evidence support, narrative faithfulness — combined by a
softmin at *p* = −4, then a calibration step, then a tier.

**Say:** "Softmin, not a mean. A weighted average lets five good signals hide one bad
one; softmin lets the weakest signal dominate, which is what you actually want from a
confidence number."

**Point at:** the word **uncalibrated** beside the score. **Say:** "The isotonic map was
fitted on a 416-event backtest and then *not adopted*, because its holdout discrimination
was 0.531 — chance. The system says uncalibrated because that is the true statement.
`artifacts/eval_report.md` has the whole table, including what failed."

**Click:** **Trust** in the nav. The calibration state and its reason are on screen.

---

## 3 · Scenario B, abstention — 1 minute 30

**Click:** **Admin** → the **Break a feed** card. It already reads `martech_weekly`.

**Say, before clicking Run:** "Each control tells you what it will do before it does it.
This one pauses a source. Freshness will then decay on that contract's own SLA schedule."

**Click:** **Run**.

**Click:** **Feed**.

**Expect:** the `martech_weekly` tile walks green → amber → red. As it does, `c4` — data
trust — collapses, and the marketing insight moves from publishing to hedging to an
**abstention card** with its own type: what was asked, what was missing, and what would
have to arrive for an answer to become possible.

**Say:** "That is not an error state. Abstention is a designed output. The alternative —
attributing the movement to whatever data is still arriving — is how these systems lie."

---

## 4 · Scenario C, restraint — 45 seconds

**Click:** **Admin** → **Inject event** → confirm `EV-2026-0311-AURORA-LAUNCH-PROMO` →
**Run**.

**Expect:** no published insight for the launch. The Feed's **Abstained** filter shows it
with the reason: an 18-day history against the contract's minimum for full statistics.

**Say:** "Eighteen days of history cannot support a seasonal decomposition. The right
answer is not to fire. A system that always has an answer is a system that is sometimes
guessing."

---

## 5 · Scenario D, the distractor, and entitlements — 1 minute

**Say:** "There is a fourth movement in this window that is real and statistically
clean, and the system says nothing about it, because it is below the contract's business
floor. Statistical significance is not materiality."

**Click:** the role selector → **Regional Sales Manager — North**.

**Expect:** the data changes, not just the label. Other regions' rows are gone and margin
and discount columns read `MASKED`.

**Click:** **Audit**.

**Expect:** the compiled statement for that query, its role, its outcome and its row
count. **Say:** "The filter is in the SQL, applied by the contract compiler below the
API and below the model. There is nothing to bypass on the client. And a refusal is
audited as carefully as a result."

**Click:** the role selector → **Intern**, then **Feed**. The financial KPIs are denied
outright, and the denial is a typed response, not an empty screen.

---

## 6 · Close — 30 seconds

**Click:** **Telemetry**.

**Expect:** cost per insight, cache hit rate, and any model downgrades, all metered.

**Say, to close:** "Four things to take away. Statistics decide and the model narrates,
structurally. Security is below the LLM and cannot be prompted away. Confidence is
measured and calibrated — and when the calibration does not earn its keep, the system
says so rather than claiming it. And the eval report in `artifacts/` lists what failed
along with what passed, because a report that only shows successes is not a report."

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Feed is empty, API returns 503 | no warehouse loaded | `make demo` (or `make backfill`) |
| Sources strip all red | the simulated clock is ahead of the last batch | `make replay DAYS=30` |
| A panel spins | the API is not up on :8000 | check the `make demo` shell |
| A narrative reads like a template | the provider is unavailable; the fallback is working | expected offline — `LLM_PROVIDER=mock` is the default |
| Screens differ from this script | derived state from an earlier run | `make demo-reset && make demo` |
