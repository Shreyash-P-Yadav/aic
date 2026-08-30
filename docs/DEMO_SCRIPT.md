# Demo script — only what actually works

**Every step below was run against the live application and checked.** Anything that
does not work is in the "Do not click" list at the end, with what to say instead.

> Replaces an earlier version of this file that described things the build does not do.
> Two were found by testing every step: the **Break a feed** control produces no visible
> change, and the **Inject event** control returned a server error on every click. The
> second is fixed. The first is not, and is listed as future work rather than demoed.

Runs about 7 minutes.

---

## Before you start

```
.venv\Scripts\python -m insight_copilot.cli demo     (Windows)
make demo                                            (Mac / Linux)
```

Wait for all four lines. If the second one is missing, stop — nothing else will work.

```
OK    world loaded and 30 sim-days replayed: 1623 batches, 80,954 rows
OK    scenario run: net_revenue -41.46% on 2026-03-06 at p = 0.0026; tier Moderate
OK    narrative cache pre-warmed: 4 narrative(s) cached in 10 ms
OK    serving on http://127.0.0.1:8000 — all data is simulated
```

Second terminal → `npm run dev` in `frontend` → open <http://localhost:5173>.
Leave the role on **CFO** and the persona on **analyst**.

---

## 0 · Frame it — 30 seconds

**Say:** "This watches business numbers, works out why they moved, and refuses to answer
when it can't tell. Every number on screen was computed by SQL or a statistical model.
The AI only writes the sentence — and a separate checker verifies every number in that
sentence against the computation before you see it."

**Then, once, clearly:** "All of this data is simulated. Meridian is a fictional
company. That was deliberate — it's the only way we can know the true answer and prove
the system found it."

**On screen:** the Feed. Eleven green source tiles. One insight card.

---

## 1 · The feed — 30 seconds

**Point at the sources strip.** Eleven feeds — orders, warehouse, marketing, weather,
news, support tickets — each on its own schedule. Green means *the drop that was due has
arrived*, measured against that feed's own contract, not a wall clock.

**Point at the card:** `net_revenue`, **−41.46%**, **₹−1.00 cr**, led by
**region=North**, tier **Moderate**, with a sparkline of the last two months.

**Say:** "One insight. Not a dashboard of forty tiles — the system decided this was the
only thing worth reporting."

---

## 2 · The insight — 2 minutes 30 · **this is the demo**

**Click the card.**

### The narrative
**Point at the grey line under it:** *"12 number(s) checked against the evidence bundle,
0 unsupported."*

**Say:** "That is the whole product in one line. The AI wrote that paragraph, and every
figure in it was pulled back out and matched against the computation. If one hadn't
matched, the paragraph would have been thrown away and rewritten."

### The chart
**Point at the two lines.** Blue is what happened, orange dashed is what should have
happened. They track each other, then blue falls away.

**Point at the shaded band.** "That period was held out of the model's training. So the
orange line there is a genuine prediction, not a line fitted through the thing it's
judging."

**Click "Table view."** "Every chart here can be read as numbers. A chart you can't check
is a chart you have to trust."  → **click back to Chart view.**

### The ladder — click each rung
- **Where** — `region=North`, **51%** of the gap, bootstrap win rate **96%**. The others
  sit at 1–2%. "Below 90% it's a shortlist entry, never a named cause."
- **What kind** — the waterfall. Price **−₹9.3 lakh**, volume **+₹2.26 cr**, mix
  **+₹23.4 lakh**. "These sum to the change between the two windows *exactly* — that's
  arithmetic, not a fit. And it's anchored on the previous week, which is a different
  comparison from the headline. The caption says so."
- **Why** — three drivers with confidence intervals: fill rate **0.349**, price index
  **0.929**, marketing **0.066**. "Two different statistical methods are run and their
  disagreement is reported rather than hidden."
- **What event** — six supporting documents, all **tier 1** ops incidents naming
  DC-North conveyor failures.

**The best moment in the demo — point at "rejected by timing gate": 4 documents.**

**Say:** "Four documents scored well on relevance and were thrown out because they were
dated *after* the drop began. A document that appeared afterwards cannot be the cause.
Most retrieval systems would have quoted them."

---

## 3 · Confidence and provenance — 1 minute

**Point at the right rail.** Six measured signals: detection 96%, attribution 66%,
statistics 73%, data trust 100%, evidence 98%, narrative 100%.

**Say:** "Combined with a softmin, not an average. An average lets five good signals hide
one bad one. This sits near the *weakest* — here, attribution at 66%."

**Point at "0.84 (uncalibrated)".**

**Say — and do not skip this:** "That word is the most honest thing on the screen. We
built the machinery to prove the confidence score is reliable, ran it over 416 test
events, and it showed the score could not reliably separate right answers from wrong
ones. So we refused to use it. It says *uncalibrated* because that is true. We know why
and we know the fix — it's in the report."

**Click "Provenance off" → on.** Every figure gains its method, freshness and lineage.

---

## 4 · Roles are a data fact — 1 minute

**Switch role → Regional Sales Manager — North.**

**Say:** "The data changed, not the label. Other regions are gone and margin columns read
MASKED. That restriction is compiled into the database query, below the API and below
the AI. There is no client-side filter to bypass and no prompt that talks around it."

**Switch → Intern.** Financial KPIs are denied outright — a typed refusal, not a blank
screen.

**Click Audit.** Every query: who ran it, under which role, against which contract, how
many rows came back. **Say:** "A refusal is logged as carefully as an answer."

**Switch back to CFO.**

---

## 5 · Personas — 30 seconds

**Change persona: analyst → CFO → RSM.** Same insight, three renderings.

- Analyst: `10,021,818`
- CFO: `₹1.00 crore`
- RSM: `₹100.2 lakh`

**Say:** "Same computed number, three audiences. The verifier accepts all three because
they're the same value — it understands crore and lakh."

---

## 6 · Live control — 45 seconds

**Click Admin → Inject event → Run.** (`EV-2026-0306-OUTAGE` is pre-filled.)

**Say before clicking:** "Each control tells you what it will do before it does it."

**Expect:** *"EV-2026-0306-OUTAGE (outage) replayed over 2026-03-06..2026-03-12; 595
batches landed"*, and the simulated clock moves.

**Say:** "That re-ran the world through a planted failure. 595 data batches physically
landed and were ingested. This isn't a scripted animation — the pipeline actually ran."

---

## 7 · The plumbing — 30 seconds

**Click Data & sources.** Eleven contracts with cadence, SLA, known failure modes, and a
data-quality table: **100 checks, 99 warnings, 1 quarantine holding 21 rows** of
out-of-range marketing spend.

**Say:** "Bad rows are set aside with a reason, never deleted. Every held row is
countable and explainable."

**Click Telemetry.** Model calls and cache hits, metered per insight.

---

## 8 · Close — 30 seconds

**Say:** "Four things. The maths decides and the AI narrates — structurally, not as a
policy. Security sits below the AI and can't be prompted away. Confidence is measured,
and when it didn't earn its keep we said so instead of showing a number. And the
evaluation report lists what failed alongside what passed, because a report that only
shows wins isn't a report."

---

# Do not click these

Each of these is either empty or does nothing. If a judge asks, the honest answer is
short and it is below.

| Screen / control | What actually happens | What to say |
|---|---|---|
| **Admin → Break a feed** | Returns a confirmation message. **Nothing visibly changes** — the source stays green. Freshness is computed from whether a scheduled drop arrived, and pausing future drops doesn't rewrite the past. | "The refusal path is built and tested — four separate triggers, seventeen tests. It isn't yet wired to this button. That's the next piece of work." |
| **Actions** | Empty: "No action at this confidence tier." Correct behaviour — actions are suppressed below High — but there's nothing to show. | "Actions are deliberately suppressed unless confidence is High. Since we refused to adopt the calibration, nothing reaches that bar yet." |
| **Trust** | Says "Not yet fitted." No curve, no per-tier table. | Say it deliberately — this is your honesty story. See section 3. |
| **Feed → Abstained filter** | Empty. Only one insight exists in the demo run. | Don't open it. |
| **Telemetry cost** | **$0.00** — the offline mock model is free. | "Cost tracking is wired end to end; it reads zero because we're running with no paid model." |

**There is only one insight in the demo.** The other three scenarios — refusal, too
little history, too small to matter — exist and pass their tests, but are not visible as
cards in the UI. Don't promise a judge you'll show them.

---

# What to say about what's next

All true, all forward-looking, none claimed as present.

1. **Wire the refusal path to the UI.** The engine has four abstention triggers and they
   pass seventeen tests. Connecting them to the Break-a-feed control and getting
   freshness to decay on the simulated clock is roughly a day.
2. **Earn the calibration.** Our test data plants events too close together, so no single
   week has one clear cause. Regenerating it with proper spacing should make the
   confidence score meaningful — and then the Trust screen fills in and Actions unlock.
3. **Live intake view.** Data & sources currently refreshes on load; it was designed to
   stream batches as they land.
4. **Connect a real warehouse.** Everything reads through a contract layer, so pointing
   it at real tables is configuration rather than a rebuild. Not yet done.

---

## If it breaks

| Symptom | Fix |
|---|---|
| Feed empty, API 503 | The demo command isn't running or hasn't finished |
| Sources all red | `demo-reset`, then `demo` again |
| Panel spinning | Backend isn't on :8000 — check the first terminal |
| Narrative reads like a template | Expected offline; the AI is off and the fallback is working |
| Anything differs from this script | `demo-reset && demo` — state from an earlier run |
