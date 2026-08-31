"""The delivery-side eval sections: narration fidelity, entitlements, budget.

Separated from :mod:`insight_copilot.evals.sections` because they measure a different
kind of claim. Those sections ask whether the statistics are right; these ask whether
what reached the reader matched them, whether a role saw only its own rows, and what
the whole run cost. A failure here is not a modelling error — it is a promise broken
between the maths and the screen.
"""

from __future__ import annotations

from insight_copilot.evals.checks import LeakageFinding, NarrationScore
from insight_copilot.evals.models import EvalSection, Measurement
from insight_copilot.evals.targets import (
    CITATION_COVERAGE_TARGET,
    COST_PER_INSIGHT_TARGET_USD,
    ENTITLEMENT_LEAKAGE_TARGET,
    LATENCY_TARGET_MS,
    NUMERIC_FIDELITY_TARGET,
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
                detail="; ".join(score.unsupported)
                or "every numeral in every narrative matched a computed fact",
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
