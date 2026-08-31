# Handover

**All data in this repository is simulated.** Meridian Consumer Brands is a fictional
company. No figure anywhere in this repository, this document included, describes a real
business.

Read this before demoing. Where a number appears below it was measured by a command in
this repository, and the command's real output is pasted in `BUILD_LOG.md` under the
phase that produced it. Where something did not work, it says so.

---

## What was built

Thirteen phases, P0 through P12, each with a gate that had to pass before the next
began. The system is:

- **A simulated business** — three years of daily operations for a ₹850 cr Indian home
  & personal care company, generated from a structural model (latent demand, pricing
  and media decisions that respond to it, outcomes, and events) rather than sampled
  from a distribution. Deterministic from one seed.
- **A counterfactual truth ledger** — every planted event re-simulated with itself
  removed, so its true contribution in rupees is known exactly. 445 events; the Shapley
  decomposition sums to the observed gap to **0.000000000 INR** across 113 groups.
- **Eleven source feeds** projected out of that world with realistic defects — late
  arrivals, restatements, schema drift, duplicate keys, unit changes, silent gaps —
  landing on a schedule driven by each source's own contract cron.
- **An intake layer** — bronze → data quality → conform → silver → gold, quarantining
  rather than dropping, idempotent by `(source_id, batch_id)` and row hash, with
  per-period watermarks that can rewind.
- **An analytical engine** — conformal anomaly detection over a parametric regression
  baseline, then a three-rung attribution ladder (Adtributor for *where*, Bennet for
  *what kind*, SARIMAX vs OLS-HAC for *why*), evidence retrieval with a contract-driven
  timing gate, and a six-signal confidence score with designed abstention.
- **A four-call-site LLM layer** with a deterministic number verifier, cite-or-drop
  hypotheses, an allowlist-validated planner, and a mandatory offline mock.
- **A FastAPI service and a React UI** — eight screens, five roles, four personas,
  provenance toggle, and four live demo controls.
- **A learning loop and an eval suite** — feedback store, gated LightGBM ranker, case
  library, and a backtest that replays 416 ledger events through the real engine.

Everything runs **offline with no API key**. `LLM_PROVIDER=mock` is the default and the
whole product is demonstrable with the model switched off.

## Gate results

| Phase | Gate | Result | The number that matters |
|---|---|---|---|
| P0 | `make verify-p0` | PASS | lint, `mypy --strict`, `tsc`, 5 tests, vite build |
| P1 | `make verify-p1` | PASS | 6 KPI + 11 source contracts validate; 40 tests including adversarial injection into every user-supplied field |
| P2 | `make verify-p2` | PASS | ₹853 cr annual; CV 0.230; AR(1) 0.394; ACF lag-7 0.332; determinism byte-identical |
| P3 | `make verify-p3` | PASS | Shapley residual **0.000000000 INR** over 113 groups; Scenario A lands −11.94% against a −12% target |
| P4 | `make verify-p4` | PASS | **31/31 planted pathologies present and detectable**; 704 documents; no real-looking PII |
| P5 | `make verify-p5` | PASS | 2,521,085 rows loaded, 21 quarantined by the `spend_inr` ceiling; a 30-day replay lands 1,623 batches and misses 26 |
| P6 | `make verify-p6` | PASS | **conformal p-values uniform on a clean holdout, KS p = 0.716**; outage detected 2026-03-06 at p = 0.0039; Bennet residual 3.4e-08; price elasticity −1.63 against a planted −1.94 |
| P7 | `make verify-p7` | PASS | four distinct abstention paths; the post-dated decoy is eliminated by the timing gate; six syndicated copies count as one source |
| P8 | `make verify-p8` | PASS | 31 tests in 0.34 s with **no API key and no network**; an injected wrong number is caught and the narrator falls back |
| P9 | `make verify-p9` | PASS | 25 tests; a cold start returns 503 with the command that fixes it |
| P10 | `make verify-p10` | PASS | 7 vitest + 6 Playwright (a seventh was added in P12); 32 screenshots reviewed by eye, one grid defect found and fixed |
| P11 | `make verify-p11` | **PASS with four recorded shortfalls** | 416 events replayed; ECE 0.118 (target 0.10), share MRE 0.817 (0.20), precision lift 0.919 (1.0), recall on loud events 0.471 (0.70) |
| P12 | `make verify-p12` | PASS | all linters and typecheckers clean; 11 hardening tests; `make demo` rebuilds from a wiped warehouse in one command; nine defects found and fixed, including a **false pass in the number verifier** |

Full backend suite: **300 tests, all passing**. `mypy --strict` clean over 189 source
files. `ruff`, `eslint`, `prettier`, `tsc` clean.

The eval report is `artifacts/eval_report.md`. It leads with what failed.

**One caveat on `verify-all`, stated plainly:** it was run in order against a live
`make demo`, and it went green from P0 to P12. It was **not** run in the same pass as a
full `make generate` + `make generate-truth`, because regenerating the counterfactual
ledger is a ~6-minute rebuild of state that was already correct. Every individual gate
was run for real and its output is in `BUILD_LOG.md`.

**A clean clone was verified separately**, and it works: `git clone` of this branch into
an empty directory, then `make install` (exit 0, npm deprecation warnings only), then
`make demo` — **6m 23s** to serving, producing byte-for-byte the same result as the
working copy (1,623 batches, 80,954 rows, `net_revenue -41.46%` at p = 0.0026, tier
Moderate). That doubles as a determinism check across directories.

**Disk:** budget **2 GB**. Measured on that clean clone — `.venv` 859 MB, `data/` after
`make demo` 418 MB, `frontend/node_modules` 235 MB, plus ~250 MB for the truth ledger.

## What failed, with the measured numbers

Four eval targets are missed. None was dropped, re-weighted or re-targeted to produce a
pass — and one target was *tightened* mid-phase when it turned out to be meaningless.

| Metric | Target | Measured | n |
|---|---:|---:|---:|
| Expected calibration error | ≤ 0.10 | **0.1179** | 102 |
| Attribution share mean relative error | ≤ 0.20 | **0.8168** | 114 |
| Detection precision lift over chance | ≥ 1.0 | **0.9194** | 70 |
| Recall on high-detectability events | ≥ 0.70 | **0.4709** | 172 |

**All four have one root cause, and it is the calibration corpus rather than the
engine.** 440 events are planted across 939 days, so 61% of scanned days fall inside
some event window and about eight events are live on any covered day. Three consequences,
each measured:

1. A detector flagging days at random would score 0.61 precision on that corpus. The
   original 0.50 absolute target was therefore being reported as a PASS at 0.557 —
   *below chance*. Grading the lift instead turns it into the FAIL it always was.
2. No window has one clean dominant cause, so top-cause accuracy tops out at **30.9%**
   against a 20% chance rate. Real signal, but only 1.5× chance.
3. With attribution that noisy, the composite confidence score cannot rank correct calls
   above incorrect ones — holdout **AUC 0.531**. The isotonic map fitted on it collapses
   towards a constant at the base rate, and ECE of 0.118 is what a near-constant
   predictor scores when the base rate drifts between the two halves of the split.

The share MRE additionally compares two things that are not quite the same: the estimated
share of the **net** gap against the ledger's share of planted **magnitude**. The
estimator is close to unbiased — median ratio of estimate to truth **0.89**, median
relative error **0.344** — but the mean is dominated by windows where segments move in
opposite directions and the net denominator collapses. Both numbers are in the report;
the flattering one is not reported alone.

**What was done about it instead of tuning:** the fitted calibration map is measured and
**deliberately not adopted**. A discrimination floor (`MIN_DISCRIMINATION_AUC = 0.55`)
makes non-adoption an explicit, reported decision, the contract's own tier bands stay in
force, and the system continues to describe itself as *uncalibrated* — which is the true
statement. Deriving tier boundaries from that curve would have made High and Moderate
unreachable and silenced the product on the strength of a curve that measured nothing.

## Known issues

1. **The blended marketing elasticity level is not recovered.** Naive 0.0217,
   DAG-specified 0.0662, planted 0.1430 (n = 131 whole weeks). The *improvement* passes
   as a graded metric — 1.58× closer, against a 1.5× target — and the level is recorded
   here rather than tuned. The cause is identification, not code: media budget is a
   share of revenue on a quarterly plan, so log spend is near-collinear with the seasonal
   controls that must be included, and the six channel adstocks correlate 0.81–0.96.
   Three specifications were tried and all attenuate. This is the aggregate
   marketing-mix identification problem the architecture document warns about, arriving
   exactly where it warns it will.
2. **`Central` region appears on only 42% of days** in `gold.fct_revenue_daily` against
   a 12% population weight. Central is the one region with no home DC and is served
   entirely by cross-serving, so its assortment is thinner by construction — but 42% is
   lower than that alone explains. National revenue validates at ₹853 cr and every
   realism test passes, so aggregates are unaffected. Region-sliced work should read this
   first.
3. **An `UNKNOWN` category bucket reaches attribution.** Unmapped SKUs are 0.17% of
   revenue but can surface as a top segment in quiet windows, where the net gap in
   Adtributor's denominator is near zero. It is correct behaviour for the algorithm and
   only half-right for a product; the materiality floor suppresses it before publication,
   so it is visible mainly inside the backtest, and wherever it *is* shown it now carries
   an `unmapped` label explaining what the bucket means. Escalating it as a DQ finding
   is still outstanding — see "the three things I would fix first".
4. ~~**The `intern` role's policy on `unit_volume` will not compile.**~~ **Fixed.** The
   contract declared a row filter on `:user_region`, a binding the intern role never
   supplies, so the compiler failed closed and the intern was denied by accident rather
   than by decision. The grant now matches its sibling operational contract
   (`order_fill_rate`): `rows: all`. `check_referential_integrity` rejects the whole
   class now, so `make validate-contracts` catches it at authoring time rather than at
   query time. Entitlement leakage was and remains **0**; policies that will not compile
   is now **0** as well.

## Deferred

- **Regenerating the calibration corpus with isolated event windows** — roughly 150
  events with mandatory clean gaps, so a window has one dominant cause and the
  confidence score has something to discriminate. This is the fix for all four failing
  eval targets. It is a change to the *generator*, and it costs a ~6-minute world
  regeneration plus a full re-backfill, so it was recorded rather than attempted at the
  end of the build.
- **Kendall τ on top-3 drivers** is implemented and unit-tested in `evals/metrics.py`
  but is not wired into the report: the ledger records a top region and a top category
  per event, not a ranked driver list, so there is no three-item answer key to correlate
  against. Reporting a τ computed against an answer key that does not exist would be
  worse than not reporting one.
- **The LightGBM priority ranker never trains in the demo**, by design — there are no
  analyst labels in a fresh install, and the label floor is 60. The gating, the staleness
  monitor and the reordering are covered by tests that seed a corpus; the demo shows the
  rules path and says so.
- **Cost per insight reports $0.0000** because the mock provider is free. The meter,
  the cap and the downshift are exercised by the P8 tests, but the demo cannot show a
  real spend figure without an API key.

## The three things I would fix first

1. **Regenerate the calibration corpus with isolated windows.** Everything the
   confidence layer claims rests on a backtest, and right now that backtest cannot
   distinguish a good attribution from a lucky one. This is the single change that would
   turn four FAILs into a real calibration curve, and it would let the tier boundaries
   actually be derived from the data rather than falling back to the contract.
2. **Give the driver regression a second identification strategy.** The quarterly media
   plan is set months ahead for reasons unrelated to this week's demand and is *already
   in the generator* — it is exactly the instrument this problem needs, and it is not
   currently exposed through any source feed. Surfacing it would move the marketing
   elasticity from "the right sign and 1.58× closer" to a number worth quoting.
3. **Route the `UNKNOWN` bucket to the data-quality surface as well as the ladder.**
   Partly done: an `UNKNOWN` member is now labelled `unmapped` wherever it is shown,
   with an explanation on hover, so it no longer reads as a broken join. What is *not*
   done is escalating it — a segment whose membership is "we could not map these SKUs"
   is a data problem someone should be told about, not only a cause someone should read.
   It should raise a DQ finding in parallel.

   Note the earlier plan here was to remove it from attribution entirely. That would be
   wrong: the simulated world plants a product launch that genuinely transacts as
   `UNKNOWN` for over a week before its SKUs reach the product master, so suppressing
   the bucket would hide a real movement rather than clean up a spurious one. Labelling
   plus escalating is the correct shape; suppression is not.

## Strongest and weakest

**Strongest — the honesty machinery.** The number verifier is deterministic, runs on
every generated sentence, understands Indian numeric formats, and has caught real
fabrications during this build: a narrator emitting `63.10%` against a real 62% passed
verification until the tolerance bug was found and fixed; every persona template was
silently failing its own verifier on the confidence figure until a `NumberFact` was added
for it; and in P12 the eval suite caught the verifier itself having a **false pass** — a
relative tolerance cannot express a fixed rendering precision, so the same faithful
two-decimal rounding verified when the value was large and failed when it was small.
That last one is the most reassuring finding in the build, because the thing that caught
it was the measurement layer doing its job on the layer above it. The abstention paths are four genuinely distinct ones, not four branches of one.
And the eval suite reports what failed at the top of the page.

**Also strong — the security boundary.** Row filters and column masks are applied by the
contract compiler, below the API and below the LLM. Entitlement leakage measured **0**
across every role × every contract, checked by inspecting the compiled SQL rather than
the result set, because that is where the guarantee lives. A denied role raises before
any query runs, and refusals are audited as carefully as results.

**Weakest — the calibration.** It is the part of the system that makes the loudest claim
("confidence is computed and calibrated, never claimed") and it is the part the data
cannot currently support. The machinery is all there and correct — temporal split, the
demo scenarios excluded from the fit, isotonic regression, boundaries derived by
inverting the curve, per-tier and per-bin counts — and it is fed by a corpus too densely
planted for any of it to bite. The build's response was to refuse to adopt the curve and
say so, which is the right call, but it means a judge asking "so how well calibrated is
it?" gets the honest answer *"not demonstrated on this corpus, and here is exactly why"*
rather than a number.

**Also weak — driver attribution at national grain.** Rung 3 works, both estimators
agree on price, and the diagnostics are real. But the one driver a marketing audience
will ask about is the one this world cannot identify at the grain the demo shows, and no
amount of specification care fixes that from the demand side alone.

## Where to look

| Question | File |
|---|---|
| How do I run it? | `README.md` |
| How do I demo it? | `docs/DEMO_SCRIPT.md` — seven minutes, click by click |
| What did each gate actually print? | `BUILD_LOG.md` |
| What is deferred and what is broken? | `BUILD_PROGRESS.md` |
| What are the measured numbers? | `artifacts/eval_report.md` and `.json` |
| Why is this statistic done this way? | the module docstring — every statistical choice carries its reasoning |
