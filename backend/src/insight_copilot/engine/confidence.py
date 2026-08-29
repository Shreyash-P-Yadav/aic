"""Confidence: six measured signals, a softmin, an isotonic map, and hard gates.

**Confidence is computed and calibrated, never claimed.** Every number below is a
measurement of something that actually happened during the run, and the mapping from
those measurements to a probability is fitted on a backtest rather than asserted.

Why ``softmin(p = -4)`` rather than a mean: a chain is as strong as its weakest link.
An insight with flawless statistics resting on a stale feed is not "quite good on
average" — it is unreliable, and an arithmetic mean would hide that behind five strong
signals. A softmin is dominated by the smallest input while staying differentiable and
free of the cliff a hard ``min`` would introduce.

Why isotonic rather than a linear rescale: the map from a composite score to an
observed hit rate is monotone but not linear, and isotonic regression is the standard
non-parametric fit for exactly that shape. Until P11 fits one on a real backtest, the
identity map is used **and reported as uncalibrated**, because a fabricated calibration
curve would be worse than none.

The hard gates are not part of the arithmetic. A breached freshness SLA on a required
source forces ``INSUFFICIENT`` whatever the score says, because the score is computed
from data the system already knows it cannot trust.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from insight_copilot.logging import get_logger

logger = get_logger(__name__)

Tier = Literal["High", "Moderate", "Low", "Insufficient"]

SOFTMIN_P = -4.0
"""The power-mean exponent. At -4 the composite sits close to the minimum while a
second weak signal still pulls it further down, which a hard ``min`` would not."""

SIGNAL_FLOOR = 1e-6
"""Softmin divides by each signal, so a signal of exactly zero is clamped here. The
clamp is visible in the resulting score — it drives the composite to ~0 — rather than
raising, because a zero signal is a real state and abstention is its right answer."""


@dataclass(frozen=True)
class SignalValue:
    """One measured signal, with the measurement that produced it."""

    name: str
    value: float
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", float(min(1.0, max(0.0, self.value))))


class ConfidenceSignal(ABC):
    """One of the six inputs. Each measures, none asserts."""

    name: str = "signal"

    @abstractmethod
    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """Compute this signal from what the run actually produced."""


@dataclass
class ConfidenceInputs:
    """Everything the six signals read. Populated by the pipeline, never by a model."""

    p_value: float = 1.0
    delta_pct: float = 0.0
    materiality_ratio: float = 0.0
    bootstrap_stability: float = 0.0
    attribution_coverage: float = 0.0
    ljung_box_p: float = float("nan")
    breusch_pagan_p: float = float("nan")
    estimator_agreement: float = 0.0
    history_days: int = 0
    min_history_days: int = 28
    freshness_ok: bool = True
    stale_sources: tuple[str, ...] = ()
    dq_pass_rate: float = 1.0
    reconciliation_ok: bool = True
    restatement_exposure: float = 0.0
    evidence_corroboration: float = 0.0
    independent_sources: int = 0
    timing_gate_survivors: int = 0
    narrative_faithfulness: float = 1.0


class DetectionStrength(ConfidenceSignal):
    """``c1`` — how far outside the calibration distribution the observation sits."""

    name = "c1_detection"

    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """A small conformal p-value and a move well past the materiality floor."""
        significance = float(1.0 - min(1.0, evidence.p_value / 0.05))
        size = float(min(1.0, evidence.materiality_ratio))
        value = 0.7 * significance + 0.3 * size
        return SignalValue(
            self.name,
            value,
            f"conformal p = {evidence.p_value:.4f}; move is "
            f"{evidence.materiality_ratio:.1f}x the contract's business floor",
        )


class AttributionQuality(ConfidenceSignal):
    """``c2`` — bootstrap stability times coverage. Both, because either alone lies."""

    name = "c2_attribution"

    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """A stable segment explaining little is not an explanation, and vice versa."""
        value = float(evidence.bootstrap_stability * evidence.attribution_coverage)
        return SignalValue(
            self.name,
            value,
            f"bootstrap win rate {evidence.bootstrap_stability:.2f} x coverage "
            f"{evidence.attribution_coverage:.2f}",
        )


class StatisticalValidity(ConfidenceSignal):
    """``c3`` — did the regression's assumptions survive, and do the estimators agree?"""

    name = "c3_statistical"

    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """Diagnostics that failed are the reason this number is not to be trusted."""
        checks: list[float] = []
        notes: list[str] = []
        if not np.isnan(evidence.ljung_box_p):
            checks.append(1.0 if evidence.ljung_box_p > 0.05 else 0.4)
            notes.append(f"Ljung-Box p = {evidence.ljung_box_p:.3f}")
        if not np.isnan(evidence.breusch_pagan_p):
            checks.append(1.0 if evidence.breusch_pagan_p > 0.05 else 0.6)
            notes.append(f"Breusch-Pagan p = {evidence.breusch_pagan_p:.3f}")
        checks.append(float(evidence.estimator_agreement))
        notes.append(f"estimator agreement {evidence.estimator_agreement:.2f}")
        if evidence.history_days:
            adequacy = min(1.0, evidence.history_days / max(evidence.min_history_days, 1))
            checks.append(adequacy)
            notes.append(
                f"n = {evidence.history_days} against a "
                f"{evidence.min_history_days}-day floor for full statistics"
            )
        return SignalValue(self.name, float(np.mean(checks)), "; ".join(notes))


class DataTrust(ConfidenceSignal):
    """``c4`` — freshness, data quality, reconciliation and restatement exposure."""

    name = "c4_data_trust"

    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """The signal Scenario B collapses. A stale required feed is not a small penalty."""
        freshness = 1.0 if evidence.freshness_ok else 0.1
        reconciliation = 1.0 if evidence.reconciliation_ok else 0.25
        exposure = 1.0 - min(1.0, evidence.restatement_exposure)
        value = float(np.mean([freshness, evidence.dq_pass_rate, reconciliation, exposure]))
        stale = ", ".join(evidence.stale_sources) or "none"
        return SignalValue(
            self.name,
            value,
            f"stale required sources: {stale}; DQ pass rate "
            f"{evidence.dq_pass_rate:.2f}; reconciliation "
            f"{'within tolerance' if evidence.reconciliation_ok else 'BREACHED'}; "
            f"restatement exposure {evidence.restatement_exposure:.2f}",
        )


class EvidenceSupport(ConfidenceSignal):
    """``c5`` — corroboration across independent sources, after the timing gate."""

    name = "c5_evidence"

    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """Independence is counted, not assumed: syndicated copies are one source."""
        independence = min(1.0, evidence.independent_sources / 3.0)
        value = float(evidence.evidence_corroboration * (0.6 + 0.4 * independence))
        return SignalValue(
            self.name,
            value,
            f"noisy-OR corroboration {evidence.evidence_corroboration:.2f} across "
            f"{evidence.independent_sources} independent source(s); "
            f"{evidence.timing_gate_survivors} survived the timing gate",
        )


class NarrativeFaithfulness(ConfidenceSignal):
    """``c6`` — set *after* narration, by the deterministic verifier. Never by the model."""

    name = "c6_narrative"

    def measure(self, evidence: ConfidenceInputs) -> SignalValue:
        """One if every number and claim in the text was checked against the bundle."""
        return SignalValue(
            self.name,
            evidence.narrative_faithfulness,
            f"verifier passed {evidence.narrative_faithfulness:.0%} of generated claims",
        )


DEFAULT_SIGNALS: tuple[ConfidenceSignal, ...] = (
    DetectionStrength(),
    AttributionQuality(),
    StatisticalValidity(),
    DataTrust(),
    EvidenceSupport(),
    NarrativeFaithfulness(),
)


def softmin(values: list[float], p: float = SOFTMIN_P) -> float:
    """Power mean at ``p``. Dominated by the weakest input, smooth everywhere."""
    clamped = np.array([max(SIGNAL_FLOOR, min(1.0, value)) for value in values])
    if clamped.size == 0:
        return 0.0
    return float(np.mean(clamped**p) ** (1.0 / p))


@dataclass
class ConfidenceResult:
    """The composite, the tier, and every reason behind them."""

    signals: list[SignalValue]
    composite: float
    calibrated: float
    tier: Tier
    calibration_fitted: bool
    hard_gate_failures: list[str] = field(default_factory=list)

    @property
    def abstained(self) -> bool:
        """Is this an abstention rather than an insight?"""
        return self.tier == "Insufficient"

    @property
    def weakest(self) -> SignalValue:
        """The signal driving the composite. The sentence a reader wants first."""
        return min(self.signals, key=lambda item: item.value)

    def signal(self, name: str) -> SignalValue | None:
        """One signal by name."""
        return next((item for item in self.signals if item.name.startswith(name)), None)

    @property
    def detail(self) -> str:
        """The line the evidence drawer leads with."""
        gates = "; ".join(self.hard_gate_failures)
        return (
            f"{self.tier} ({self.calibrated:.2f}); weakest signal "
            f"{self.weakest.name} at {self.weakest.value:.2f} — {self.weakest.detail}"
            + (f"; hard gates failed: {gates}" if gates else "")
        )
