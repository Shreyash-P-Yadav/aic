"""The isotonic map from a composite score to a probability, and the tier boundaries.

Kept apart from the signals because it is the half that must be **fitted on a real
backtest**. Until P11 supplies one, :class:`IsotonicCalibrator` reports itself as
unfitted and passes the composite through unchanged — and everything downstream says
"uncalibrated" rather than quietly presenting a raw score as a probability.
"""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression

from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.confidence import (
    DEFAULT_SIGNALS,
    ConfidenceInputs,
    ConfidenceResult,
    ConfidenceSignal,
    SignalValue,
    Tier,
    softmin,
)
from insight_copilot.errors import StatisticalError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MIN_CALIBRATION_POINTS = 40
"""Below forty backtested insights an isotonic fit is a step function through noise."""


class IsotonicCalibrator:
    """Maps a composite score to an observed hit rate. Monotone, non-parametric."""

    def __init__(self) -> None:
        self._model: IsotonicRegression | None = None
        self._n = 0

    @property
    def fitted(self) -> bool:
        """Has this been fitted on real outcomes? Reported everywhere it is used."""
        return self._model is not None

    @property
    def n_points(self) -> int:
        """How many backtested outcomes the fit rests on."""
        return self._n

    def fit(self, scores: np.ndarray, outcomes: np.ndarray) -> IsotonicCalibrator:
        """Fit on ``(composite score, was it right)`` pairs from a backtest."""
        if scores.size != outcomes.size:
            raise StatisticalError("calibration inputs disagree in length")
        if scores.size < MIN_CALIBRATION_POINTS:
            raise StatisticalError(
                f"{scores.size} outcomes is too few to calibrate",
                detail=f"need at least {MIN_CALIBRATION_POINTS}",
            )
        self._model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(
            scores, outcomes
        )
        self._n = int(scores.size)
        logger.info("calibration.fitted", n=self._n)
        return self

    def transform(self, score: float) -> float:
        """The calibrated probability, or the raw score when unfitted."""
        if self._model is None:
            return float(score)
        return float(self._model.predict([score])[0])


class ConfidenceScorer:
    """Runs the six signals, applies the hard gates, and assigns a tier."""

    def __init__(
        self,
        *,
        signals: tuple[ConfidenceSignal, ...] = DEFAULT_SIGNALS,
        calibrator: IsotonicCalibrator | None = None,
    ) -> None:
        self._signals = signals
        self._calibrator = calibrator or IsotonicCalibrator()

    def score(self, inputs: ConfidenceInputs, contract: KPIContract) -> ConfidenceResult:
        """Measure, compose, calibrate, gate, and band."""
        measured = [signal.measure(inputs) for signal in self._signals]
        composite = softmin([item.value for item in measured])
        calibrated = self._calibrator.transform(composite)
        failures = self._hard_gates(measured, inputs, contract)
        tier = self._tier(calibrated, contract, failures)
        logger.info(
            "confidence.scored",
            composite=composite,
            calibrated=calibrated,
            tier=tier,
            gates=failures,
        )
        return ConfidenceResult(
            signals=measured,
            composite=composite,
            calibrated=calibrated,
            tier=tier,
            calibration_fitted=self._calibrator.fitted,
            hard_gate_failures=failures,
        )

    @staticmethod
    def _hard_gates(
        measured: list[SignalValue], inputs: ConfidenceInputs, contract: KPIContract
    ) -> list[str]:
        """Conditions forcing ``INSUFFICIENT`` regardless of the calibrated score."""
        gates = contract.confidence_policy.hard_gates
        failures: list[str] = []
        if gates.required_sources_fresh and not inputs.freshness_ok:
            failures.append(
                "a required source breaches its freshness SLA: "
                + (", ".join(inputs.stale_sources) or "unnamed")
            )
        if not inputs.reconciliation_ok:
            failures.append("a contract-declared reconciliation check is breached")
        weak = [item for item in measured if item.value < gates.any_signal_min]
        failures.extend(
            f"{item.name} is {item.value:.2f}, below the {gates.any_signal_min:.2f} floor"
            for item in weak
        )
        if inputs.timing_gate_survivors == 0 and inputs.evidence_corroboration > 0.0:
            failures.append("no hypothesis survived the timing gate")
        if inputs.evidence_corroboration < contract.confidence_policy.evidence_floor:
            failures.append(
                f"evidence corroboration {inputs.evidence_corroboration:.2f} is below "
                f"the contract's {contract.confidence_policy.evidence_floor:.2f} floor"
            )
        return failures

    @staticmethod
    def _tier(calibrated: float, contract: KPIContract, failures: list[str]) -> Tier:
        """Band the calibrated score, unless a hard gate has already decided."""
        if failures:
            return "Insufficient"
        policy = contract.confidence_policy
        if calibrated < policy.abstain_below:
            return "Insufficient"
        if calibrated < policy.hedge_below:
            return "Low"
        if calibrated < 0.9:
            return "Moderate"
        return "High"
