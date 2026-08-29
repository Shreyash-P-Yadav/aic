"""The end-to-end insight run: detect, attribute, retrieve, score, recommend, bundle.

One object so the API, the demo and the gate all run the *same* path, and so the two
possible outcomes — an insight or an abstention — are produced by one function rather
than by two code paths that can drift apart. Abstention is reached by returning a
different type, never by raising past the bundle assembly, because everything the
abstention needs to say was computed before the decision to abstain was made.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.actions import ActionCatalog, ActionSelector, RecommendedAction
from insight_copilot.engine.attribute_where import WhereResult
from insight_copilot.engine.attribute_why import WhyResult
from insight_copilot.engine.bundle import (
    AbstentionArtifact,
    ActionFact,
    ConfidenceFact,
    DriverFact,
    EvidenceFact,
    FreshnessFact,
    InsightEvidenceBundle,
    LineageStep,
    NumberFact,
    SegmentFact,
)
from insight_copilot.engine.calibration import ConfidenceScorer
from insight_copilot.engine.confidence import ConfidenceInputs, ConfidenceResult
from insight_copilot.engine.detect import Detection
from insight_copilot.engine.evidence import EvidenceBundle
from insight_copilot.ingest.models import FreshnessStatus
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

RETRY_ON_FRESHNESS = "the next successful batch from the stale source"
RETRY_ON_EVIDENCE = "the next corpus drop, or an analyst attaching a document"
RETRY_ON_RECONCILIATION = "the next batch that brings the two sources back inside tolerance"


@dataclass
class RunInputs:
    """Everything one insight run consumes. Assembled by the caller from the engine."""

    contract: KPIContract
    detection: Detection
    where: WhereResult | None = None
    why: WhyResult | None = None
    evidence: EvidenceBundle | None = None
    freshness: list[FreshnessStatus] = field(default_factory=list)
    required_sources: list[str] = field(default_factory=list)
    dq_pass_rate: float = 1.0
    reconciliation_ok: bool = True
    restatement_exposure: float = 0.0
    history_days: int = 0
    price_effect: float | None = None
    volume_effect: float | None = None
    mix_effect: float | None = None
    baseline_value: float = 0.0
    lever_change: float = 0.0
    observed_metrics: dict[str, float] = field(default_factory=dict)
    period: tuple[dt.date, dt.date] | None = None
    watermark: str | None = None

    def stale_required_sources(self) -> tuple[str, ...]:
        """Required sources whose freshness is breached. The ``c4`` hard gate reads this."""
        required = set(self.required_sources) or {
            source.source_id for source in self.contract.sources if source.required
        }
        return tuple(
            status.source_id
            for status in self.freshness
            if status.source_id in required and status.breached
        )


class InsightEngine:
    """Assembles one insight — or one abstention — from the analytical results."""

    def __init__(self, scorer: ConfidenceScorer | None = None) -> None:
        self._scorer = scorer or ConfidenceScorer()

    def run(
        self, inputs: RunInputs, *, now: dt.datetime
    ) -> InsightEvidenceBundle | AbstentionArtifact:
        """Score confidence, then build whichever output the tier permits."""
        confidence = self._scorer.score(self._inputs_for(inputs), inputs.contract)
        fact = _confidence_fact(confidence)
        if confidence.abstained:
            return self._abstain(inputs, confidence, fact, now=now)
        return self._insight(inputs, confidence, fact, now=now)

    # ---------------------------------------------------------------- signals --
    @staticmethod
    def _inputs_for(inputs: RunInputs) -> ConfidenceInputs:
        """Map the analytical results onto the six signals' measurements."""
        contract = inputs.contract
        floor = contract.materiality.business.min_abs_impact_inr or 1.0
        stale = inputs.stale_required_sources()
        where = inputs.where
        why = inputs.why
        evidence = inputs.evidence
        return ConfidenceInputs(
            p_value=inputs.detection.p_value,
            delta_pct=inputs.detection.delta_pct,
            materiality_ratio=abs(inputs.detection.delta) / floor,
            bootstrap_stability=where.top.stability if where and where.top else 0.0,
            attribution_coverage=where.coverage if where else 0.0,
            ljung_box_p=why.diagnostics.ljung_box_p if why else float("nan"),
            breusch_pagan_p=why.diagnostics.breusch_pagan_p if why else float("nan"),
            estimator_agreement=why.agreement_score if why else 0.0,
            history_days=inputs.history_days,
            min_history_days=contract.confidence_policy.min_history_days_full_stats,
            freshness_ok=not stale,
            stale_sources=stale,
            dq_pass_rate=inputs.dq_pass_rate,
            reconciliation_ok=inputs.reconciliation_ok,
            restatement_exposure=inputs.restatement_exposure,
            evidence_corroboration=evidence.corroboration if evidence else 0.0,
            independent_sources=evidence.independent_sources if evidence else 0,
            timing_gate_survivors=len(evidence.items) if evidence else 0,
        )

    # ---------------------------------------------------------------- outputs --
    def _insight(
        self,
        inputs: RunInputs,
        confidence: ConfidenceResult,
        fact: ConfidenceFact,
        *,
        now: dt.datetime,
    ) -> InsightEvidenceBundle:
        """Build the bundle. Every number in it was computed, none was written."""
        detection = inputs.detection
        start, end = inputs.period or (detection.day, detection.day)
        actions = self._actions(inputs, confidence, now.date())
        bundle = InsightEvidenceBundle(
            insight_id=uuid.uuid4().hex[:12],
            kpi_id=inputs.contract.kpi.id,
            contract_version=inputs.contract.contract_version,
            computed_at=now,
            period_start=start,
            period_end=end,
            watermark=inputs.watermark,
            observed=detection.observed,
            counterfactual=detection.expected,
            delta=detection.delta,
            delta_pct=detection.delta_pct,
            detection_method=detection.method,
            p_value=detection.p_value,
            numbers=_numbers(inputs),
            segments=_segments(inputs.where),
            price_effect=inputs.price_effect,
            volume_effect=inputs.volume_effect,
            mix_effect=inputs.mix_effect,
            drivers=_drivers(inputs.why),
            explained_fraction=inputs.why.explained_fraction if inputs.why else 0.0,
            unexplained_fraction=inputs.why.unexplained_fraction if inputs.why else 1.0,
            evidence=_evidence(inputs.evidence),
            evidence_corroboration=inputs.evidence.corroboration if inputs.evidence else 0.0,
            evidence_rejected_by_timing=(
                inputs.evidence.rejected_by_timing if inputs.evidence else []
            ),
            confidence=fact,
            actions=[_action_fact(item) for item in actions],
            freshness=_freshness(inputs.freshness),
            lineage=_lineage(inputs.contract),
        )
        logger.info(
            "engine.insight",
            kpi=bundle.kpi_id,
            tier=fact.tier,
            actions=len(bundle.actions),
            delta_pct=bundle.delta_pct,
        )
        return bundle

    def _actions(
        self, inputs: RunInputs, confidence: ConfidenceResult, today: dt.date
    ) -> list[RecommendedAction]:
        """Governed actions for the leading driver, or none when the tier forbids them."""
        if inputs.why is None or not inputs.contract.actions_ref:
            return []
        leading = max(inputs.why.estimates, key=lambda item: abs(item.coefficient), default=None)
        if leading is None:
            return []
        catalog = ActionCatalog.load(inputs.contract.actions_ref)
        return ActionSelector(catalog).select(
            contract=inputs.contract,
            driver_id=leading.driver_id,
            confidence=confidence,
            baseline_value=inputs.baseline_value or abs(inputs.detection.expected),
            elasticity=leading.coefficient,
            elasticity_interval=leading.confidence_interval,
            lever_change=inputs.lever_change or 0.01,
            observed=inputs.observed_metrics,
            today=today,
        )

    @staticmethod
    def _abstain(
        inputs: RunInputs,
        confidence: ConfidenceResult,
        fact: ConfidenceFact,
        *,
        now: dt.datetime,
    ) -> AbstentionArtifact:
        """Say what is known, what failed, and when to come back."""
        detection = inputs.detection
        start, end = inputs.period or (detection.day, detection.day)
        stale = inputs.stale_required_sources()
        known = [
            f"{inputs.contract.kpi.name} moved {detection.delta_pct:+.2f}% against its "
            f"counterfactual ({detection.observed:,.0f} against {detection.expected:,.0f})",
            f"the movement was flagged by {detection.method} at p = {detection.p_value:.4f}",
        ]
        if inputs.where and inputs.where.top is not None:
            known.append(
                f"the largest single contribution is {inputs.where.top.label} at "
                f"{inputs.where.top.explanatory_power:.0%} of the gap"
            )
        missing: list[str] = []
        if inputs.evidence is not None and not inputs.evidence.sufficient:
            missing.append(
                f"no document cleared the evidence floor "
                f"({inputs.evidence.corroboration:.2f} against "
                f"{inputs.evidence.floor:.2f}); "
                f"{len(inputs.evidence.rejected_by_timing)} eliminated by the timing gate"
            )
        if stale:
            missing.append(f"a current batch from {', '.join(stale)}")
        artifact = AbstentionArtifact(
            insight_id=uuid.uuid4().hex[:12],
            kpi_id=inputs.contract.kpi.id,
            computed_at=now,
            period_start=start,
            period_end=end,
            observed_movement=f"{detection.delta_pct:+.2f}% against the counterfactual",
            what_is_known=known,
            failed_checks=confidence.hard_gate_failures
            or [f"calibrated confidence {confidence.calibrated:.2f} is below the abstain floor"],
            missing_evidence=missing,
            retry_trigger=(
                RETRY_ON_FRESHNESS
                if stale
                else RETRY_ON_RECONCILIATION
                if not inputs.reconciliation_ok
                else RETRY_ON_EVIDENCE
            ),
            eta=_eta(inputs.freshness, stale, now),
            confidence=fact,
            freshness=_freshness(inputs.freshness),
        )
        logger.info(
            "engine.abstained",
            kpi=artifact.kpi_id,
            gates=confidence.hard_gate_failures,
            retry=artifact.retry_trigger,
        )
        return artifact


# ------------------------------------------------------------------ mappers --
def _confidence_fact(result: ConfidenceResult) -> ConfidenceFact:
    return ConfidenceFact(
        signals={item.name: item.value for item in result.signals},
        signal_detail={item.name: item.detail for item in result.signals},
        composite=result.composite,
        calibrated=result.calibrated,
        calibration_fitted=result.calibration_fitted,
        tier=result.tier,
        weakest_signal=result.weakest.name,
        hard_gate_failures=result.hard_gate_failures,
    )


def _numbers(inputs: RunInputs) -> list[NumberFact]:
    """Every number a sentence about this insight may contain."""
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
    if inputs.where and inputs.where.top is not None:
        facts.append(
            NumberFact(
                key="top_segment_ep",
                value=inputs.where.top.explanatory_power,
                unit="fraction",
                method="Adtributor explanatory power",
            )
        )
    return facts


def _segments(where: WhereResult | None) -> list[SegmentFact]:
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


def _drivers(why: WhyResult | None) -> list[DriverFact]:
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


def _evidence(bundle: EvidenceBundle | None) -> list[EvidenceFact]:
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


def _action_fact(action: RecommendedAction) -> ActionFact:
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


def _freshness(statuses: list[FreshnessStatus]) -> list[FreshnessFact]:
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


def _lineage(contract: KPIContract) -> list[LineageStep]:
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


def _eta(
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
