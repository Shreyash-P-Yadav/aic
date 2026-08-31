"""Turning the analytical results into the bundle's typed facts.

Split from the orchestrator because these are pure mappings — result object in, typed
fact out — and keeping them apart is what lets the orchestrator read as the sequence it
is rather than as three hundred lines of field assignment.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import TYPE_CHECKING

from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.actions import RecommendedAction
from insight_copilot.engine.attribute_where import WhereResult
from insight_copilot.engine.attribute_why import WhyResult
from insight_copilot.engine.bundle import (
    ActionFact,
    ConfidenceFact,
    DriverFact,
    EvidenceFact,
    FreshnessFact,
    LineageStep,
    NumberFact,
    SegmentFact,
)
from insight_copilot.engine.confidence import ConfidenceResult
from insight_copilot.engine.evidence import EvidenceBundle
from insight_copilot.ingest.models import FreshnessStatus

if TYPE_CHECKING:
    from insight_copilot.engine.pipeline import RunInputs


def confidence_fact(result: ConfidenceResult) -> ConfidenceFact:
    return ConfidenceFact(
        signals={item.name: item.value for item in result.signals},
        signal_detail={item.name: item.detail for item in result.signals},
        composite=result.composite,
        calibrated=result.calibrated,
        calibration_fitted=result.calibration_fitted,
        tier=result.tier,
        weakest_signal=result.weakest.name,
        hard_gate_failures=result.hard_gate_failures,
        tier_basis=result.tier_basis,
    )


def numbers_for(inputs: RunInputs, confidence: ConfidenceResult | None = None) -> list[NumberFact]:
    """Every number a sentence about this insight may contain.

    The calibrated confidence is among them. It is a computed number like any other,
    every persona template prints it, and a number a narrator may write that the
    verifier cannot check is exactly the hole the verifier exists to close — a
    template failing its own verifier on a figure the system itself produced.
    """
    detection = inputs.detection
    unit = inputs.contract.definition.unit
    facts = [
        NumberFact(key="observed", value=detection.observed, unit=unit, method="gold mart"),
        NumberFact(
            key="counterfactual",
            value=detection.expected,
            unit=unit,
            method="regression baseline, event window held out",
        ),
        NumberFact(
            key="delta", value=detection.delta, unit=unit, method="observed - counterfactual"
        ),
        NumberFact(
            key="delta_pct", value=detection.delta_pct, unit="pct", method="delta / counterfactual"
        ),
        NumberFact(
            key="p_value", value=detection.p_value, unit="probability", method=detection.method
        ),
    ]
    for name, value in (
        ("price_effect", inputs.price_effect),
        ("volume_effect", inputs.volume_effect),
        ("mix_effect", inputs.mix_effect),
    ):
        if value is not None:
            facts.append(NumberFact(key=name, value=value, unit=unit, method="Bennet indicator"))
    if confidence is not None:
        facts.append(
            NumberFact(
                key="calibrated_confidence",
                value=confidence.calibrated,
                unit="fraction",
                method="softmin of six measured signals, then the calibration map",
            )
        )
        facts.append(
            NumberFact(
                key="composite_confidence",
                value=confidence.composite,
                unit="fraction",
                method="softmin(p=-4) over the six signals",
            )
        )
        facts.extend(
            NumberFact(
                key=f"signal_{item.name}",
                value=item.value,
                unit="fraction",
                method=item.detail,
            )
            for item in confidence.signals
        )
    facts.append(
        NumberFact(
            key="confidence_level",
            value=95.0,
            unit="pct",
            method="the interval convention every estimate here is reported at",
        )
    )
    if inputs.where and inputs.where.top is not None:
        facts.append(
            NumberFact(
                key="top_segment_ep",
                value=inputs.where.top.explanatory_power,
                unit="fraction",
                method="Adtributor explanatory power",
            )
        )
        facts.append(
            NumberFact(
                key="top_segment_stability",
                value=inputs.where.top.stability,
                unit="fraction",
                method="bootstrap win rate over 100 resamples",
            )
        )
    if inputs.why is not None:
        facts.append(
            NumberFact(
                key="explained_fraction",
                value=inputs.why.explained_fraction,
                unit="fraction",
                method="share of variation the model accounts for",
            )
        )
        facts.append(
            NumberFact(
                key="unexplained_fraction",
                value=inputs.why.unexplained_fraction,
                unit="fraction",
                method="the remainder, labelled honestly",
            )
        )
        for estimate in inputs.why.estimates:
            facts.extend(
                [
                    NumberFact(
                        key=f"{estimate.driver_id}_coefficient",
                        value=estimate.coefficient,
                        unit="elasticity",
                        method="driver regression",
                    ),
                    NumberFact(
                        key=f"{estimate.driver_id}_low",
                        value=estimate.confidence_interval[0],
                        unit="elasticity",
                        method="95% interval",
                    ),
                    NumberFact(
                        key=f"{estimate.driver_id}_high",
                        value=estimate.confidence_interval[1],
                        unit="elasticity",
                        method="95% interval",
                    ),
                    NumberFact(
                        key=f"{estimate.driver_id}_agreement",
                        value=estimate.agreement,
                        unit="fraction",
                        method="agreement between the two estimators",
                    ),
                ]
            )
    return facts


def action_numbers(actions: Sequence[RecommendedAction], unit: str) -> list[NumberFact]:
    """Narratable facts for each proposed action's priced impact.

    Without these the recommendation sentence quotes three figures — the central impact
    and both ends of its interval — that the verifier cannot match to anything, so a
    faithful sentence is rejected as unsupported and the narrator falls back to the very
    template it was already rendering. Every number a sentence may contain has to exist
    as a fact; an action's price is no exception.

    Keyed by action id so two proposals cannot collide on ``action_impact``.
    """
    facts: list[NumberFact] = []
    for action in actions:
        impact = action.expected_impact
        facts.extend(
            [
                NumberFact(
                    key=f"action_{action.spec.id}_impact",
                    value=impact.central,
                    unit=unit,
                    method="baseline x elasticity x lever change x effect fraction",
                ),
                NumberFact(
                    key=f"action_{action.spec.id}_impact_low",
                    value=impact.low,
                    unit=unit,
                    method="the same arithmetic at the low end of the elasticity interval",
                ),
                NumberFact(
                    key=f"action_{action.spec.id}_impact_high",
                    value=impact.high,
                    unit=unit,
                    method="the same arithmetic at the high end of the elasticity interval",
                ),
            ]
        )
    return facts


def segments_for(where: WhereResult | None) -> list[SegmentFact]:
    if where is None:
        return []
    return [
        SegmentFact(
            label=item.label,
            actual=item.actual,
            forecast=item.forecast,
            explanatory_power=item.explanatory_power,
            surprise=item.surprise,
            stability=item.stability,
            simpson_flag=item.simpson_flag,
        )
        for item in where.candidates[:8]
    ]


def drivers_for(why: WhyResult | None) -> list[DriverFact]:
    if why is None:
        return []
    return [
        DriverFact(
            driver_id=item.driver_id,
            coefficient=item.coefficient,
            interval_low=item.confidence_interval[0],
            interval_high=item.confidence_interval[1],
            p_value=item.p_value,
            agreement=item.agreement,
            group=list(item.group),
        )
        for item in why.estimates
    ]


def evidence_for(bundle: EvidenceBundle | None) -> list[EvidenceFact]:
    if bundle is None:
        return []
    return [
        EvidenceFact(
            doc_id=item.document.doc_id,
            kind=item.document.kind,
            title=item.document.title,
            publish_date=item.document.publish_date,
            effective_date=item.document.effective_date,
            source_tier=item.document.source_tier,
            confidence=item.confidence,
            independence_key=item.independence_key,
            matched_on=item.matched_on,
        )
        for item in bundle.items
    ]


def action_fact(action: RecommendedAction) -> ActionFact:
    return ActionFact(
        action_id=action.spec.id,
        driver_id=action.driver_id,
        lever=action.spec.lever,
        title=action.spec.title,
        expected_impact_central=action.expected_impact.central,
        expected_impact_low=action.expected_impact.low,
        expected_impact_high=action.expected_impact.high,
        owner_role=action.owner_role,
        needs_approval=action.needs_approval,
        monitoring_kpi=action.spec.monitoring.kpi,
        monitoring_checkpoints=list(action.spec.monitoring.checkpoint_days),
        success_threshold_pct=action.spec.monitoring.success_threshold_pct,
        earliest_effect=action.earliest_effect,
    )


def freshness_for(statuses: list[FreshnessStatus]) -> list[FreshnessFact]:
    return [
        FreshnessFact(
            source_id=item.source_id,
            state=item.state,
            age_hours=item.age_hours,
            sla_hours=item.sla_hours,
            latest_period=item.latest_period,
        )
        for item in statuses
    ]


def lineage_for(contract: KPIContract) -> list[LineageStep]:
    """The contract's own declared lineage, carried onto the card."""
    return [
        LineageStep(
            stage=step.step,
            frm=step.source if isinstance(step.source, str) else ", ".join(step.source),
            to=step.target,
            transform=step.transform,
        )
        for step in contract.lineage
    ]


def eta_for(
    statuses: list[FreshnessStatus], stale: tuple[str, ...], now: dt.datetime
) -> dt.datetime | None:
    """When the blocking source is next due. The abstention card's "come back at"."""
    if not stale:
        return None
    due = [
        status.next_due_at
        for status in statuses
        if status.source_id in stale and status.next_due_at is not None
    ]
    return min(due) if due else now + dt.timedelta(hours=24)
