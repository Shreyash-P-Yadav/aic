# Insight Copilot — evaluation report

_All data in this report is simulated. Meridian Consumer Brands is a fictional company; no figure here describes a real business._

Generated 2026-08-30 01:39 UTC.

**4 of 25 metrics missed their target.** Each is listed below with the measured number; none has been removed, reweighted or re-targeted to produce a pass.

## Corpus

- 416 ledger events replayed
- temporal split at **2025-07-01** — 298 events fitted, 118 held out
- 5 demo-scenario events excluded from the fit entirely

## What failed

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| expected calibration error | 0.118 | 0.100 | 102 | FAIL |
| share mean relative error | 0.817 | 0.200 | 114 | FAIL |
| precision lift over chance | 0.919 | 1.000 | 70 | FAIL |
| recall on high-detectability events | 47.1% | 70.0% | 172 | FAIL |

## Calibration

Fitted on the events before the cut date and measured on those after it. The calibrated score is the probability that the cause the system named is the window's dominant cause.

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| expected calibration error | 0.118 | 0.100 | 102 | FAIL |
| Brier score | 0.226 | — | 102 | — |
| discrimination (AUC) | 0.531 | — | 102 | — |
| observed base rate | 33.3% | — | 102 | — |

## Attribution

Graded against the window's dominant cause, weighted by each concurrent event's own recorded contribution pro-rated to the overlapping days. Claims naming only a channel are ungradeable — the corpus plants no channel mechanism — and are excluded from the denominator, not scored wrong.

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| top-cause accuracy | 30.9% | — | 376 | — |
| share mean relative error | 0.817 | 0.200 | 114 | FAIL |
| share median relative error | 34.4% | — | 114 | — |
| ungradeable claims | 40 | — | 416 | — |

## Detection

A flagged day counts as a true positive when it falls inside any ledger event window; 61% of scanned days are inside one, which is the precision a coin would achieve. An event is recalled when at least one of its days was flagged.

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| precision lift over chance | 0.919 | 1.000 | 70 | FAIL |
| precision | 55.7% | — | 70 | — |
| recall on high-detectability events | 47.1% | 70.0% | 172 | FAIL |
| recall over the whole corpus | 48.8% | — | 416 | — |
| days scanned | 939 | — | 939 | — |

## Endogeneity

Media budget is set as a share of revenue with a tactical overlay that responds to last week's performance, so a naive regression of log units on log adstocked spend is biased by construction. Both estimates are shown against the value planted in the world config.

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| naive elasticity | 0.022 | — | 131 | — |
| DAG-specified elasticity | 0.066 | — | 131 | — |
| planted elasticity | 0.143 | — | 131 | — |
| times closer to truth than naive | 1.578 | 1.500 | 131 | PASS |

## Narrative

Every number in every generated sentence re-extracted and re-checked against the evidence bundle by the deterministic verifier. Citation coverage is measured over PUBLISHED claims: one the cite-or-drop filter rejected never reaches a reader.

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| numeric fidelity | 100.0% | 100.0% | 12 | PASS |
| citation coverage | 100.0% | 95.0% | 2 | PASS |
| cite-or-drop rejection rate | 33.3% | — | 3 | — |
| narratives rendered | 4 | — | 4 | — |

## Entitlements

Every contract compiled for every role; the compiled SQL itself is inspected, because that is where the guarantee lives — a mask absent from the statement cannot be put back downstream.

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| entitlement leakage | 0 | 0 | 1 | PASS |
| policies that will not compile | 1 | — | 1 | — |

## Budgets

| metric | measured | target | n | verdict |
|---|---:|---:|---:|---|
| insight latency | 866 ms | 5,000 ms | 1 | PASS |
| LLM cost per insight | $0.0000 | $0.0500 | 1 | PASS |

## Tiers as measured

Boundaries: contract bands; no fitted reliability curve yet

| Tier | boundary | n | mean score | observed hit rate |
|---|---:|---:|---:|---:|
| High | 0.800 | 0 | 0.000 | 0.0% |
| Moderate | 0.600 | 0 | 0.000 | 0.0% |
| Low | 0.350 | 13 | 0.433 | 30.8% |
| Insufficient | 0.000 | 89 | 0.255 | 33.7% |

## Reliability curve

| bin | n | mean score | observed hit rate | gap |
|---|---:|---:|---:|---:|
| 0.0 to 0.1 | 0 | — | — | — |
| 0.1 to 0.2 | 13 | 0.111 | 0.231 | 0.120 |
| 0.2 to 0.3 | 76 | 0.279 | 0.355 | 0.076 |
| 0.3 to 0.4 | 1 | 0.394 | 1.000 | 0.606 |
| 0.4 to 0.5 | 10 | 0.417 | 0.100 | 0.317 |
| 0.5 to 0.6 | 2 | 0.533 | 1.000 | 0.467 |
| 0.6 to 0.7 | 0 | — | — | — |
| 0.7 to 0.8 | 0 | — | — | — |
| 0.8 to 0.9 | 0 | — | — | — |
| 0.9 to 1.0 | 0 | — | — | — |

## Priority ranker

0 labels, below the 60 floor; using rules

## Notes

- calibration: fitted on 274 events but NOT adopted: holdout discrimination is 0.531, below the 0.55 floor, so the map is a constant at the base rate and the bands derived from it would admit nothing
- calibration map written to /home/user/aic/artifacts/calibration.json
- tier boundaries fall back to the contract's own bands; the system reports itself uncalibrated rather than claiming a calibration it has not earned
