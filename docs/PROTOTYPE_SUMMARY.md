# Insight Copilot — plain-language summary

*Written to be turned into a business proposal. Everything marked **WORKING** was run
and seen on screen. Everything under "Not built yet" is honestly not there.*

> **Important, and it must appear on any slide that shows a number:** all data is
> simulated. "Meridian Consumer Brands" is a made-up company. No figure describes a
> real business. This was deliberate — we needed to know the true answer to every
> question in order to prove the system gets it right.

---

## 1. The problem, in one line

A business tracks dozens of numbers. When one moves, finding out **why** takes an
analyst days — and by the time they answer, the moment has passed.

## 2. What we built, in one line

A system that watches business numbers, spots real movements, works out **why** they
happened using statistics, explains it in plain English for each job role — and
**refuses to answer when it isn't sure**.

## 3. The one idea that makes it different

**The maths decides. The AI only writes the sentence.**

Most AI analytics tools let the AI look at data and describe what it "sees". That is
how you get confident, well-written, wrong answers.

Here the AI is never allowed to produce a number. Every figure comes from a database
query or a statistical model. The AI is handed the finished numbers and asked only to
turn them into a readable sentence. Then a separate checker pulls every number back out
of that sentence and matches it against the computed figures. If a number doesn't
match, the sentence is thrown away and rewritten.

**In our test runs: 34 out of 34 numbers across four different job roles matched.
Zero invented figures.**

## 4. How it works — five steps

1. **Data arrives messily, on purpose.** Eleven different feeds — orders, warehouse,
   marketing, weather, news, support tickets — each on its own schedule, some late,
   some incomplete, some correcting themselves later. Just like real life.
2. **It gets cleaned, and nothing is thrown away.** Bad rows are set aside with a
   reason attached, never silently deleted.
3. **A statistical model predicts what should have happened.** Then it compares that
   to what actually happened.
4. **If the gap is real, it works out why** — in three steps: *where* (which region,
   channel, category), *what kind* (price, volume, or product-mix), and *why* (which
   business drivers moved). It also searches news and internal documents for a
   supporting explanation.
5. **It scores its own confidence** from six separate measurements, and decides whether
   to speak, hedge, or stay silent.

## 5. What is working today — the demo

### WORKING — the main screen
A live status strip showing all eleven data feeds and whether each arrived on time. Below
it, the insights the system decided were worth reporting — typically two cards, each with
the movement, the impact **in that KPI's own unit** (rupees for revenue, a count for unit
volume), which segment led it, a confidence badge, and a two-month sparkline.
*(screenshot: feed)*

### WORKING — the detail screen: the flagship story
A warehouse failure in North India, deliberately hidden among a marketing cut, a price
rise, and a misleading competitor news story dated *after* the event.

The system correctly finds North, worth ₹-1.00 crore, with 96% stability. It shows:
- **A chart** of what actually happened against what should have happened, with the
  judged period shaded
- **The three-step explanation**, each step openable
- **Six confidence signals** as bars, with the weakest one named
- **Where every number came from** — which feed, which method, how fresh
- **The misleading news story rejected**, because it was published after the drop began

*(screenshot: insight detail)*

### WORKING — it refuses to answer when it can't
**This is now demonstrable live, and it is the strongest thing in the demo.**

On the Admin screen, "Break a feed" pauses the order system and runs the simulated clock
forward until that feed has genuinely gone stale. What a viewer sees:

- The `oms_orders` tile turns **red**. The other **ten feeds stay green** — they kept
  delivering normally.
- Both insights change from a published explanation to an **abstention**: *"Not
  attributed — a required source…"*
- "Restore a feed" brings it back, and the insights return. So it can be shown twice.

**Why this matters:** the system still had ten working feeds. It could have written a
confident paragraph from those. It refused. Most analytics tools cannot do this, because
guessing always looks better in a demo than declining.

The system has four separate triggers for declining — a stale required feed, two sources
that disagree, no supporting evidence, or a signal too weak to trust — all covered by
seventeen automated tests.

### WORKING — it stays quiet when it should
Three KPIs are scanned each run. Typically two produce a card and the third produces
nothing, because its movement — while real and statistically clean — sits below that
contract's business floor. Silence is an output, and the run log says which KPI was
skipped and why. A "too little history" rule is also enforced in code and tested,
though it has no visible card in the current demo data.

### WORKING — a live control that re-runs the world
On the Admin screen, "Inject event" replays the simulated world through a planted
warehouse failure. 595 data batches physically land and are processed, and the simulated
clock moves. This is not an animation — the pipeline genuinely runs.

### WORKING — five job roles see genuinely different data
Switch from CFO to Regional Manager and other regions' data physically disappears, and
profit columns show as MASKED. This is not a hidden screen element — the restriction is
built into the database query itself, below the AI, so it cannot be talked around.
*(screenshot: role switch + audit)*

### WORKING — four writing styles for four audiences
The same computed facts, written for a CFO, an analyst, a regional manager, or a
marketing lead. Same numbers, different emphasis.

### WORKING — full audit trail
Every query, who ran it, under which role, what it returned. **A refusal is logged as
carefully as an answer.**

### WORKING — cost tracking, per insight
Every model call is metered against the insight it was made for and priced from the
tokens it actually used. The screen shows insights metered, mean cost per insight in
rupees, model calls and cache hit rate. Running offline the calls are free, so the
figure is what the same work *would* cost at list rates — a modelled number from real
usage, and the screen says so.

### WORKING — a Trust screen with the real backtest
25 measured metrics grouped by area (calibration, attribution, detection, endogeneity,
narrative, entitlements, budgets), each with its target, its sample size and a PASS/FAIL
verdict. Plus the reliability curve — dot size is the number of events in each bin — and
the per-tier table showing observed hit rates, with empty tiers displayed rather than
hidden. **This screen shows four FAILs.** That is deliberate: see section 8.
*(screenshot: trust)*

### WORKING — it runs with no AI provider at all
With the AI switched off, the whole product still works using written templates. The
statistics were never dependent on the AI — this proves it.

## 6. The brief's ten requirements — all ten are demonstrable

| # | Requirement | Status |
|---|---|---|
| 1 | 5+ KPIs across 3+ sources, different speeds | 6 KPIs, 11 sources |
| 2 | Business definitions held as contracts | Yes — 6 KPI + 11 source contracts |
| 3 | 2+ personas with different narratives | 4 personas |
| 4 | A movement with several causes | Scenario A |
| 5 | A refusal to answer | **Live on screen** — break a feed, both insights abstain |
| 6 | A too-little-history case | Enforced in code + tested; no visible card in this data |
| 7 | Role-based data restriction | 5 roles |
| 8 | Evidence: freshness, method, contribution, confidence, lineage | On every insight |
| 9 | Clear split of AI vs computed | The Provenance toggle |
| 10 | Cost and speed tracking | Telemetry screen |

## 7. Numbers we can stand behind

All measured, not estimated.

| What | Result |
|---|---|
| Numbers invented by the AI | **0 out of 34** |
| Data restrictions leaking across roles | **0** |
| Automated tests passing | **300** |
| Deliberate data faults detected | **31 of 31** |
| Price/volume/mix split accuracy | Exact to 8 decimal places |
| Ground-truth accounting error | **₹0.000000000** across 113 event groups |
| Time to produce an insight | Under 1 second |
| Cost per insight | ₹1.08 modelled from real token counts |

## 8. Honest limitations — what we would fix next

We think stating these is a strength. A system that reports its own weaknesses is the
whole point of the product.

**The confidence score is not yet proven reliable.** We built the machinery to prove it,
ran it over 416 test events, and the result was that the score could not reliably tell
right answers from wrong ones. **So we refused to use it** — the system says
"uncalibrated" rather than showing a confidence figure it hasn't earned. We know why:
our test data has too many overlapping events, so no single week has one clear cause.
Fixing it means regenerating the test data with better spacing. *This is roughly one
day of work and is the single highest-value next step.*

**Marketing return-on-spend is only partly measurable.** Marketing budgets in our
simulation respond to sales, which makes the effect genuinely hard to separate — a real
and well-known problem in the industry. Our method gets **1.58× closer to the true
answer than the naive approach**, but not to the exact figure. We report the uncertainty
rather than hiding it.

**Two screens are incomplete:**
- **Admin** has 3 working controls (inject event, break feed, restore feed) and no
  clock control
- **Data & Sources** was meant to stream arrivals live; it currently refreshes on load
- **Trust** now renders the full backtest; what it cannot show is an *adopted*
  calibration curve, because the map did not earn adoption
- **Actions** is empty by design — actions are suppressed below High confidence, and
  nothing reaches High while the calibration is unadopted

**Not yet real-world tested.** Everything runs on simulated data. Connecting a real
warehouse is a configuration change, not a rebuild — but it has not been done.

## 9. Why the simulated data is a strength, not a shortcut

We can prove the system is right. With real data, nobody knows the true cause of a
movement, so nobody can grade the answers. We built a world where we planted every
cause ourselves, then re-ran the entire simulation with each cause removed to compute
exactly what it was worth. **That gives us an answer key** — and it is why we can state
accuracy figures at all instead of just showing a demo that looks convincing.

## 10. What this would be worth in a real business

- **Analyst time.** Days of investigation per movement, replaced by an explanation
  already computed and waiting.
- **Trust.** Every figure traceable to its source and method. An auditor can follow any
  number back to the query that produced it.
- **Safety.** The system refuses rather than guesses. In finance and operations, a wrong
  confident answer costs more than no answer.
- **Governance.** Data restrictions live in the database layer, so an AI cannot be
  tricked into revealing something a person is not allowed to see.

---

## Notes for whoever builds the deck

- Every slide showing a figure needs the **"simulated data"** line.
- Strongest single message: **the AI cannot invent a number — 0 out of 34, verified.**
- Second strongest: **it refuses to answer when it can't be sure** — most competing
  tools cannot do this.
- Do **not** claim the confidence score is calibrated. Claim the opposite, and frame it
  as evidence of honesty. It is our most defensible story.
- Suggested screenshot order: feed → insight detail → chart → confidence panel →
  **abstention (after breaking a feed)** → role switch → audit → telemetry.
- Two of the four scenarios are live on screen: the multi-cause movement and the
  refusal. Say "two demonstrated live, two enforced in code" rather than "four
  demonstrated". `docs/DEMO_SCRIPT.md` has the exact wording.
