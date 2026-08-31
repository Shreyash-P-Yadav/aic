# Demo script — only what actually works

**Every step below was run against the live application and checked.** Anything that
does not work is in the "Do not click" list at the end, with what to say instead.

> An earlier version of this file described things the build did not do. Testing every
> step found two: **Inject event** returned a server error on every click, and **Break a
> feed** produced no visible change. **Both are now fixed**, and the refusal path they
> gate is the strongest thing in the demo. Everything below has been run and checked.

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

**Point at the cards.** Two of them:
- `net_revenue` **−41.46%**, **₹−99.7 lakh**, led by **region=North**, tier **Moderate**
- `unit_volume` **−40.20%**, **−21,082 units**, led by **region=North**, tier **Low**

**Say:** "Two insights, not a dashboard of forty tiles. Three KPIs were scanned; the
third moved too, and the system said nothing about it because it was below that
contract's business floor. Silence is an output."

**Worth noting if a judge is technical:** the second card reads *units*, not rupees. The
system knows each KPI's unit — an earlier build rendered a unit count as "₹−21,082" and
the number verifier rejected the sentence, which is how it was caught.

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

## 3b · **The refusal** — 1 minute 30 · *the second-best moment in the demo*

**Click Admin → Break a feed.** It reads `oms_orders` — the order system, which both
KPIs on the feed depend on.

**Say before clicking:** "Every control tells you what it will do before it does it.
This one pauses the order feed and runs the simulated clock forward until it has
actually gone stale."

**Click Run.** Takes a few seconds.

**Expect, verbatim in shape:**
```
oms_orders paused; 1 simulated day(s) later it is red while 10 of 11 feeds stay green
(53 batches landed from the others). re-scanned: unit_volume abstained/Insufficient,
net_revenue abstained/Insufficient
```

**Click Feed.** The `oms_orders` tile is **red**. The other ten are still green — they
kept delivering. And both cards have changed from a published insight to an
**abstention**: *"Not attributed — a required source…"*

**Say:** "One feed went down. The system had ten other feeds still arriving and it could
have written a confident paragraph from those. It refused. That is a designed output
with its own type, not an error — and it is the behaviour most analytics tools cannot
produce, because guessing always looks better in a demo."

**Click a card** to show what an abstention says: what was asked, which check failed,
and what would have to arrive for an answer to become possible.

**Then click Admin → Restore a feed → Run.** The feed goes green and both insights
return. **Say:** "And it recovers on its own, so you can watch it twice."

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

**Click Telemetry.** Insights metered, mean cost per insight, model calls, cache hit
rate — each call attributed to the insight it was made for.

**Click Trust.** The backtest: 25 metrics with targets and verdicts, the reliability
curve, and the per-tier table. **Four read FAIL.** Say so: "This is the screen where the
system grades itself, and it is not flattering. That is the point — a report that only
showed wins would not be a report."

---

## 8 · Close — 30 seconds

**Say:** "Four things. The maths decides and the AI narrates — structurally, not as a
policy. Security sits below the AI and can't be prompted away. Confidence is measured,
and when it didn't earn its keep we said so instead of showing a number. And the
evaluation report lists what failed alongside what passed, because a report that only
shows wins isn't a report."

---

# The rest of the app, and what to say about it

None of these is on the main path, and none of them is broken. If a judge clicks one or
asks about it, the honest answer is short and it is below.

| Screen / control | What actually happens | What to say |
|---|---|---|
| **Trust** | Shows the full backtest: 25 metrics with verdicts, the reliability curve, the per-tier table. Four metrics read FAIL. | **Show this screen.** The FAILs are the honesty story — see section 3 and the wording there. |
| **Feed → Abstained filter** | Empty *until* you break a feed. After the refusal demo it holds both cards. | Use it during section 3b, not before. |
| **Telemetry cost** | Shows a real per-insight figure (about ₹1.08) priced from actual token counts. | "Offline the calls are free, so that's what the same work would cost at list rates — modelled from real usage, not a bill." |
| **Admin → advance the clock** | Works, and is a full replay: every drop due in the window lands, freshness is re-measured, the engine re-runs. Forward only. | Only click it if you have a reason to — it changes the date every other screen is measured against, so a 30-day jump invalidates the numbers you just showed. |
| **Actions** | Shows nothing proposed and a "Considered and not proposed" list with two reasons. | **Worth showing.** "One action fails a precondition the data contradicts. The other is priced with the price elasticity we actually estimated, and that estimate says a promotion here loses money — so we don't recommend it. The catalog's intuition doesn't get to overrule the arithmetic." |

**Two of the four scenarios are now live on screen** — the multi-cause movement
(section 2) and the refusal (section 3b). The other two are real but quieter: "too small
to matter" is the third KPI that produced no card, and "too little history" is enforced
in code and covered by tests but has no visible card in this run.

---

# What to say about what's next

All true, all forward-looking, none claimed as present.

1. **Earn the calibration.** Our test data plants events too close together, so no single
   week has one clear cause. Regenerating it with proper spacing should make the
   confidence score meaningful — and then the Trust screen fills in and more insights
   clear the bar at which actions are proposed.
2. **Live intake view.** Data & sources re-polls every ten seconds and says so; it was
   designed to be pushed batches as they land, which is a different thing.
3. **The two missing marts.** Two action preconditions (`days_cover`,
   `cross_serve_headroom_pct`) cannot be evaluated because nothing computes them yet, so
   the actions that need them are withheld. That is the guard behaving correctly, and it
   is also a gap: those marts are buildable from data we already hold.
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
| Sources show a negative age | The controls travel the clock; harmless, and cleared by `demo-reset` |
| Anything differs from this script | `demo-reset && demo` — state from an earlier run |
