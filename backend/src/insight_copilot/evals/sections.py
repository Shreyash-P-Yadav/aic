"""The individual eval sections. One function per measured area, so a failing gate
names one thing rather than "the suite".

Targets live in :mod:`insight_copilot.evals.suite` beside the orchestrator that reads
them; this module only measures.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from insight_copilot.engine.calibration import IsotonicCalibrator
from insight_copilot.evals.backtest import BacktestOutcome, BacktestResult
from insight_copilot.evals.checks import LeakageFinding, NarrationScore
from insight_copilot.evals.elasticity import ElasticityComparison
from insight_copilot.evals.metrics import (
    DetectionCounts,
    brier_score,
    expected_calibration_error,
    mean_relative_error,
)
from insight_copilot.evals.models import EvalSection, Measurement
from insight_copilot.evals.tables import days_between, discrimination
from insight_copilot.evals.targets import (
    ATTRIBUTION_MRE_TARGET,
    CHANCE_REGIONS,
    CITATION_COVERAGE_TARGET,
    COST_PER_INSIGHT_TARGET_USD,
    DETECTION_PRECISION_LIFT_TARGET,
    DETECTION_RECALL_TARGET,
    ECE_TARGET,
    ELASTICITY_IMPROVEMENT_TARGET,
    ENTITLEMENT_LEAKAGE_TARGET,
    LATENCY_TARGET_MS,
    MATERIAL_GAP_FLOOR_INR,
    NUMERIC_FIDELITY_TARGET,
)


# ------------------------------------------------------------------- sections --
def calibration_section(
    holdout: list[BacktestOutcome], calibrator: IsotonicCalibrator
) -> EvalSection:
    """ECE and Brier on the held-out events, after the pre-cut fit."""
    rows = [item for item in holdout if item.gradeable]
    if not rows:
        return EvalSection(
            name="Calibration",
            detail="no gradeable holdout events",
            measurements=[
                Measurement(
                    name="expected calibration error", value=float("nan"), target=ECE_TARGET, n=0
                )
            ],
        )
    raw = np.array([item.raw_score for item in rows], dtype=np.float64)
    truth = np.array([float(item.correct) for item in rows], dtype=np.float64)
    calibrated = np.array([calibrator.transform(float(value)) for value in raw])
    base_rate = float(truth.mean())
    auc = discrimination(calibrated, truth)
    return EvalSection(
        name="Calibration",
        detail=(
            "Fitted on the events before the cut date and measured on those after it. "
            "The calibrated score is the probability that the cause the system named is "
            "the window's dominant cause."
        ),
        measurements=[
            Measurement(
                name="expected calibration error",
                value=expected_calibration_error(calibrated, truth),
                target=ECE_TARGET,
                direction="max",
                n=len(rows),
                detail="count-weighted mean gap between predicted and observed hit rate",
            ),
            Measurement(
                name="Brier score",
                value=brier_score(calibrated, truth),
                n=len(rows),
                detail="mean squared error of the probability forecast; informational",
            ),
            Measurement(
                name="discrimination (AUC)",
                value=auc,
                n=len(rows),
                detail=(
                    "probability a correct call outranks an incorrect one. 0.5 is none: "
                    "a well-calibrated score with no discrimination is a constant at the "
                    "base rate, which is honest but uninformative"
                ),
            ),
            Measurement(
                name="observed base rate",
                value=base_rate,
                unit="%",
                n=len(rows),
                detail="how often the named cause was the dominant one, across the holdout",
            ),
        ],
    )


def attribution_section(outcomes: list[BacktestOutcome]) -> EvalSection:
    """Top-cause accuracy against chance, and share error where the gap is material."""
    gradeable = [item for item in outcomes if item.gradeable]
    accuracy = (
        sum(1 for item in gradeable if item.correct) / len(gradeable) if gradeable else float("nan")
    )
    material = [
        item
        for item in gradeable
        if item.correct
        and abs(item.total_delta) >= MATERIAL_GAP_FLOOR_INR
        and np.isfinite(item.estimated_share)
        and np.isfinite(item.true_share)
    ]
    estimated = np.array([item.estimated_share for item in material])
    truth = np.array([item.true_share for item in material])
    mre = mean_relative_error(estimated, truth) if material else float("nan")
    median_error = (
        float(np.median(np.abs(estimated - truth) / np.maximum(np.abs(truth), 1e-9)))
        if material
        else float("nan")
    )
    return EvalSection(
        name="Attribution",
        detail=(
            "Graded against the window's dominant cause, weighted by each concurrent "
            "event's own recorded contribution pro-rated to the overlapping days. "
            "Claims naming only a channel are ungradeable — the corpus plants no "
            "channel mechanism — and are excluded from the denominator, not scored wrong."
        ),
        measurements=[
            Measurement(
                name="top-cause accuracy",
                value=accuracy,
                unit="%",
                n=len(gradeable),
                detail=f"chance on {CHANCE_REGIONS} regions is {1.0 / CHANCE_REGIONS:.0%}",
            ),
            Measurement(
                name="share mean relative error",
                value=mre,
                target=ATTRIBUTION_MRE_TARGET,
                direction="max",
                n=len(material),
                detail=(
                    "estimated share of the NET gap against the ledger's share of planted "
                    "magnitude, on correctly named segments in windows clearing the "
                    "materiality floor. The two denominators are not identical, which is "
                    "stated rather than corrected for"
                ),
            ),
            Measurement(
                name="share median relative error",
                value=median_error,
                unit="%",
                n=len(material),
                detail=(
                    "the same comparison at the median. The mean is dominated by windows "
                    "where segments move in opposite directions, so the NET gap in the "
                    "denominator is far smaller than the gross movement the ledger's "
                    "share is built from; the median shows the typical case"
                ),
            ),
            Measurement(
                name="ungradeable claims",
                value=float(len(outcomes) - len(gradeable)),
                unit="count",
                n=len(outcomes),
                detail="claims naming only a dimension the ledger records no truth for",
            ),
        ],
    )


def detection_section(backtest: BacktestResult) -> EvalSection:
    """Day-level precision and per-event recall of the conformal scan.

    Recall is reported twice. The corpus deliberately plants low-detectability events —
    movements smaller than the noise a real business runs at — and a scan that found
    those would be flagging noise everywhere else. So the *target* is set on
    high-detectability events, the ones a system that claims to detect anything must
    find, and recall over the whole corpus is reported beside it without a target so
    the number is visible rather than quietly excluded.
    """
    event_days = {
        day
        for item in backtest.outcomes
        for day in days_between(item.window_start, item.window_end)
    }
    flagged = set(backtest.detected_days)
    baseline = len(event_days) / max(backtest.scanned_days, 1)
    loud = [item for item in backtest.outcomes if item.detectability == "high"]
    return EvalSection(
        name="Detection",
        detail=(
            "A flagged day counts as a true positive when it falls inside any ledger "
            f"event window; {baseline:.0%} of scanned days are inside one, which is the "
            "precision a coin would achieve. An event is recalled when at least one of "
            "its days was flagged."
        ),
        measurements=[
            Measurement(
                name="precision lift over chance",
                value=_precision(flagged, event_days) / baseline if baseline else float("nan"),
                target=DETECTION_PRECISION_LIFT_TARGET,
                direction="min",
                n=len(flagged),
                detail=(
                    "precision divided by the share of scanned days that lie inside some "
                    "event window. This, not raw precision, is the graded number: with "
                    f"{baseline:.0%} of days inside an event, a fixed precision target "
                    "below that figure would be met by flagging days at random"
                ),
            ),
            Measurement(
                name="precision",
                value=_precision(flagged, event_days),
                unit="%",
                n=len(flagged),
                detail=f"raw, against a {baseline:.0%} chance baseline",
            ),
            Measurement(
                name="recall on high-detectability events",
                value=_recall(loud, flagged),
                target=DETECTION_RECALL_TARGET,
                direction="min",
                unit="%",
                n=len(loud),
            ),
            Measurement(
                name="recall over the whole corpus",
                value=_recall(backtest.outcomes, flagged),
                unit="%",
                n=len(backtest.outcomes),
                detail="includes events planted below the noise floor on purpose",
            ),
            Measurement(
                name="days scanned",
                value=float(backtest.scanned_days),
                unit="count",
                n=backtest.scanned_days,
            ),
        ],
    )


def _precision(flagged: set[dt.date], event_days: set[dt.date]) -> float:
    """Fraction of flagged days that fell inside a real event window."""
    counts = DetectionCounts(
        true_positive=len(flagged & event_days),
        false_positive=len(flagged - event_days),
        false_negative=0,
    )
    return counts.precision


def _recall(outcomes: list[BacktestOutcome], flagged: set[dt.date]) -> float:
    """Fraction of events with at least one flagged day."""
    if not outcomes:
        return float("nan")
    found = sum(
        1 for item in outcomes if flagged & set(days_between(item.window_start, item.window_end))
    )
    return found / len(outcomes)


def elasticity_section(comparison: ElasticityComparison) -> EvalSection:
    """Naive versus DAG-specified marketing elasticity, both beside the planted truth.

    The graded number is the *improvement* — how many times closer specifying the DAG
    gets you — not the level. The level is not recoverable at national weekly grain on
    this world and the report says so plainly rather than grading a number the data
    cannot support; see the marketing-elasticity entry under Known issues.
    """
    return EvalSection(
        name="Endogeneity",
        detail=(
            "Media budget is set as a share of revenue with a tactical overlay that "
            "responds to last week's performance, so a naive regression of log units on "
            "log adstocked spend is biased by construction. Both estimates are shown "
            "against the value planted in the world config."
        ),
        measurements=[
            Measurement(
                name="naive elasticity",
                value=comparison.naive,
                n=comparison.observations,
                detail="log units on log adstocked spend, nothing else — what a ROAS tile does",
            ),
            Measurement(
                name="DAG-specified elasticity",
                value=comparison.dag_specified,
                n=comparison.observations,
                detail=(
                    "with price, fill rate, trend and annual seasonality, Newey-West "
                    "errors, and the mediator (unit volume) deliberately excluded"
                ),
            ),
            Measurement(
                name="planted elasticity",
                value=comparison.truth,
                n=comparison.observations,
                detail="sum of the six per-channel elasticities, read from the world config",
            ),
            Measurement(
                name="times closer to truth than naive",
                value=comparison.improvement,
                target=ELASTICITY_IMPROVEMENT_TARGET,
                direction="min",
                n=comparison.observations,
                detail=(
                    "the graded number. The LEVEL is not recovered within 20% and is "
                    "recorded as a known issue with its measured value"
                ),
            ),
        ],
    )


def narration_section(score: NarrationScore) -> EvalSection:
    """Numeric fidelity and citation coverage over every narrated bundle."""
    return EvalSection(
        name="Narrative",
        detail=(
            "Every number in every generated sentence re-extracted and re-checked "
            "against the evidence bundle by the deterministic verifier. Citation "
            "coverage is measured over PUBLISHED claims: one the cite-or-drop filter "
            "rejected never reaches a reader."
        ),
        measurements=[
            Measurement(
                name="numeric fidelity",
                value=score.numeric_fidelity,
                target=NUMERIC_FIDELITY_TARGET,
                direction="min",
                unit="%",
                n=score.numbers_checked,
            ),
            Measurement(
                name="citation coverage",
                value=score.citation_coverage,
                target=CITATION_COVERAGE_TARGET,
                direction="min",
                unit="%",
                n=score.total_claims,
                detail="published claims resting on a document that is in the bundle",
            ),
            Measurement(
                name="cite-or-drop rejection rate",
                value=score.drop_rate,
                unit="%",
                n=score.total_claims + score.dropped_claims,
                detail=(
                    "proposed claims the filter rejected; informational, but a rate of "
                    "zero would mean the filter is never exercised"
                ),
            ),
            Measurement(
                name="narratives rendered",
                value=float(score.narrated),
                unit="count",
                n=score.narrated,
            ),
        ],
    )


def entitlement_section(findings: list[LeakageFinding]) -> EvalSection:
    """Leakage must be zero. There is no acceptable non-zero value."""
    leaks = [item for item in findings if item.is_leak]
    misconfigured = [item for item in findings if not item.is_leak]
    return EvalSection(
        name="Entitlements",
        detail=(
            "Every contract compiled for every role; the compiled SQL itself is "
            "inspected, because that is where the guarantee lives — a mask absent from "
            "the statement cannot be put back downstream."
        ),
        measurements=[
            Measurement(
                name="entitlement leakage",
                value=float(len(leaks)),
                target=ENTITLEMENT_LEAKAGE_TARGET,
                direction="max",
                unit="count",
                n=1,
                detail="; ".join(f"{item.role}/{item.contract_id}: {item.detail}" for item in leaks)
                or "no compiled statement omitted a declared mask or row filter",
            ),
            Measurement(
                name="policies that will not compile",
                value=float(len(misconfigured)),
                unit="count",
                n=1,
                detail="; ".join(
                    f"{item.role}/{item.contract_id}: {item.detail}" for item in misconfigured
                )
                or "every declared policy compiles",
            ),
        ],
    )


def budget_section(latency_ms: float | None, cost_usd: float | None) -> EvalSection:
    """Latency and cost, measured on the real path or reported unmeasured."""
    return EvalSection(
        name="Budgets",
        measurements=[
            Measurement(
                name="insight latency",
                value=latency_ms if latency_ms is not None else float("nan"),
                target=LATENCY_TARGET_MS,
                direction="max",
                unit="ms",
                n=1 if latency_ms is not None else 0,
            ),
            Measurement(
                name="LLM cost per insight",
                value=cost_usd if cost_usd is not None else float("nan"),
                target=COST_PER_INSIGHT_TARGET_USD,
                direction="max",
                unit="usd",
                n=1 if cost_usd is not None else 0,
            ),
        ],
    )
