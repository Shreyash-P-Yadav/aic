"""Replay the engine over the truth ledger to produce ``(score, was_it_right)`` pairs.

This is the file the whole confidence claim rests on. Everything else in the system can
be inspected by reading it; whether a score of 0.7 means "right about seven times in
ten" can only be established by running the engine against events whose answer is known
and counting.

Three properties make the count honest:

* **The engine is not told the answer.** Detection, attribution and scoring see only
  the warehouse and the corpus. The ledger supplies the key afterwards.
* **The baseline never fits an event.** Every ledger window is held out of the
  counterfactual fit and out of the conformal calibration set, so the expectation the
  residual is measured against is genuinely a no-event expectation.
* **The four demo scenarios are excluded from the fit entirely**, by the ledger's own
  ``excluded_from_calibration_fit`` flag. Calibrating on the events the demo shows is
  how a system reports a confidence it earned on the test it was about to sit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from insight_copilot.contracts.models import KPIContract
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.engine.attribute_where import Attributor
from insight_copilot.engine.calibration import ConfidenceScorer
from insight_copilot.engine.confidence import ConfidenceInputs
from insight_copilot.engine.dataset import EngineDataset
from insight_copilot.engine.detect import ConformalDetector, Detection
from insight_copilot.engine.evidence import EvidenceRetriever
from insight_copilot.engine.regression_baseline import RegressionBaseline, calendar_events
from insight_copilot.engine.series import Series
from insight_copilot.errors import StatisticalError
from insight_copilot.evals.ledger import LedgerEvent, iter_events
from insight_copilot.evals.truth import LedgerTruth, WindowTruth
from insight_copilot.evals.windows import attribute_window, event_windows, mask_for, query_for
from insight_copilot.logging import get_logger
from insight_copilot.security.identity import SessionContext

logger = get_logger(__name__)

BACKTEST_ALPHA = 0.05
"""Looser than the demo's 0.01. The backtest's job is to produce a *spread* of scores
to calibrate against; scanning at the operational alpha would return only the events
nobody needed a confidence number for."""

SCORE_EVERY_DAY_ALPHA = 1.0
"""The scan alpha used to *score* days. Every conformal p-value is <= 1, so this
returns the whole axis; the operational threshold is applied separately."""

MIN_CALIBRATION_DAYS = 120
"""Below this many event-free days the conformal calibration set is too small for the
p-values to be meaningful, whatever the formula returns."""

BOOTSTRAP_SAMPLES_BACKTEST = 40
"""Fewer resamples than an operational run (100). Stability enters the composite as one
of six signals through a softmin, and 40 resamples put its standard error near 0.08 —
far below the spacing between tiers. Trading that for a run that finishes is a stated
choice, recorded here rather than buried in a call site."""


@dataclass(frozen=True)
class BacktestOutcome:
    """One ledger event, replayed. The unit the calibration curve is fitted on."""

    event_id: str
    event_type: str
    detectability: str
    data_condition: str
    window_start: dt.date
    window_end: dt.date
    measure_end: dt.date
    excluded_from_fit: bool
    detected: bool
    p_value: float
    delta_pct: float
    raw_score: float
    tier: str
    correct: bool
    gradeable: bool
    stability: float
    total_delta: float
    estimated_top: str
    concurrent_events: int
    true_top_region: str
    true_top_category: str
    estimated_share: float
    true_share: float
    coverage: float

    @property
    def share_error(self) -> float:
        """Relative error of the top segment's estimated share of the gap."""
        scale = max(abs(self.true_share), 1e-9)
        return abs(self.estimated_share - self.true_share) / scale


@dataclass
class BacktestResult:
    """Every replayed event, split temporally into a fit set and a holdout."""

    outcomes: list[BacktestOutcome]
    cut_date: dt.date
    detected_days: list[dt.date] = field(default_factory=list)
    scanned_days: int = 0

    @property
    def fit_set(self) -> list[BacktestOutcome]:
        """Events wholly before the cut, minus the demo scenarios."""
        return [
            item
            for item in self.outcomes
            if not item.excluded_from_fit and item.measure_end < self.cut_date
        ]

    @property
    def holdout(self) -> list[BacktestOutcome]:
        """Events after the cut. Never seen by the isotonic fit."""
        return [item for item in self.outcomes if item.measure_end >= self.cut_date]

    def arrays(self, rows: list[BacktestOutcome]) -> tuple[np.ndarray, np.ndarray]:
        """``(raw scores, outcomes)`` as float arrays, ready for the calibrator."""
        return (
            np.array([item.raw_score for item in rows], dtype=np.float64),
            np.array([float(item.correct) for item in rows], dtype=np.float64),
        )


class CalibrationBacktest:
    """Replays the engine over the ledger, once, and reports what it got right."""

    def __init__(
        self,
        dataset: EngineDataset,
        registry: ContractRegistry,
        session: SessionContext,
        documents: list[Document],
        *,
        contract_id: str = "net_revenue",
        alpha: float = BACKTEST_ALPHA,
    ) -> None:
        self._dataset = dataset
        self._registry = registry
        self._session = session
        self._documents = documents
        self._contract_id = contract_id
        self._alpha = alpha

    def run(self, ledger: pd.DataFrame, *, cut_date: dt.date) -> BacktestResult:
        """Fit one counterfactual, scan once, then score every event against truth."""
        contract = self._registry.kpi(self._contract_id)
        series = self._dataset.kpi_series(self._contract_id, self._session)
        events = event_windows(ledger)
        event_mask = mask_for(series, events)

        baseline = self._fit_baseline(series, event_mask)
        expected = baseline.counterfactual(series)
        calibration = ~event_mask
        if int(calibration.sum()) < MIN_CALIBRATION_DAYS:
            raise StatisticalError(
                "too few event-free days to calibrate the conformal scan",
                detail=f"{int(calibration.sum())} of {len(series)}",
            )
        # Scanned at alpha = 1 so EVERY day comes back with its p-value. The
        # operational alpha is applied below, by this module, when deciding whether a
        # day counts as flagged. Scanning at the operational alpha instead would drop
        # every quiet window from the corpus, and a calibration curve fitted only on
        # events that were already detected has no low end — it would report the
        # system as well calibrated precisely where it never has to make a judgement.
        detections = ConformalDetector(alpha=SCORE_EVERY_DAY_ALPHA).scan(
            kpi_id=self._contract_id,
            segment="national",
            series=series,
            expected=expected,
            calibration_mask=calibration,
            test_mask=np.ones(len(series), dtype=bool),
        )
        by_day = {item.day: item for item in detections}
        flagged = [item.day for item in detections if item.p_value <= self._alpha]

        cube = self._dataset.cube(
            self._session, start=series.dates[0].astype("O"), end=series.dates[-1].astype("O")
        )
        truth = LedgerTruth(ledger)
        retriever = EvidenceRetriever(self._documents)
        scorer = ConfidenceScorer()
        attributor = Attributor(seed=7, bootstrap_samples=BOOTSTRAP_SAMPLES_BACKTEST)

        outcomes: list[BacktestOutcome] = []
        for row in iter_events(ledger):
            outcome = self._replay(
                row,
                contract=contract,
                series=series,
                expected=expected,
                cube=cube,
                by_day=by_day,
                truth=truth,
                retriever=retriever,
                scorer=scorer,
                attributor=attributor,
            )
            if outcome is not None:
                outcomes.append(outcome)
        logger.info("backtest.complete", events=len(outcomes), flagged_days=len(flagged))
        return BacktestResult(
            outcomes=outcomes, cut_date=cut_date, detected_days=flagged, scanned_days=len(series)
        )

    # ----------------------------------------------------------------- parts --
    def _fit_baseline(self, series: Series, event_mask: np.ndarray) -> RegressionBaseline:
        """A counterfactual fitted only on days no ledger event touches."""
        calendar = self._dataset.warehouse.query(
            "SELECT date, is_holiday FROM gold.dim_calendar ORDER BY date"
        )
        panel = self._dataset.national_panel(self._session)
        baseline = RegressionBaseline(
            events=calendar_events(calendar),
            controls=panel[["date", "rainfall_mm", "temp_max_c", "discount_depth_pct"]],
        )
        baseline.fit(series.exclude(event_mask))
        return baseline

    def _replay(
        self,
        row: LedgerEvent,
        *,
        contract: KPIContract,
        series: Series,
        expected: np.ndarray,
        cube: pd.DataFrame,
        by_day: dict[dt.date, Detection],
        truth: LedgerTruth,
        retriever: EvidenceRetriever,
        scorer: ConfidenceScorer,
        attributor: Attributor,
    ) -> BacktestOutcome | None:
        """One window: pick its strongest day, attribute, retrieve, score, compare.

        The window graded is the event's own ``window_start..window_end``, not its
        measurement window. The measurement window runs a month past the event so the
        counterfactual can capture the tail; attributing over it would dilute a one-week
        movement across four weeks of nothing happening.
        """
        start = pd.Timestamp(row.window_start).date()
        end = pd.Timestamp(row.window_end).date()
        window = [day for day in by_day if start <= day <= end]
        if not window:
            return None
        detection = min((by_day[day] for day in window), key=lambda item: item.p_value)

        where = attribute_window(series, expected, cube, attributor, start, end)
        evidence = retriever.retrieve(
            query_for(row),
            effect_day=detection.day,
            entities=[str(row.true_top_region)],
            floor=contract.confidence_policy.evidence_floor,
        )
        result = scorer.score(
            ConfidenceInputs(
                p_value=detection.p_value,
                delta_pct=detection.delta_pct,
                materiality_ratio=abs(detection.delta)
                / (contract.materiality.business.min_abs_impact_inr or 1.0),
                bootstrap_stability=where.top.stability if where and where.top else 0.0,
                attribution_coverage=where.coverage if where else 0.0,
                evidence_corroboration=evidence.corroboration,
                timing_gate_survivors=len(evidence.items),
                history_days=len(series),
                min_history_days=contract.confidence_policy.min_history_days_full_stats,
            ),
            contract,
        )
        top = where.top if where else None
        window_truth = truth.for_window(start, end)
        if not window_truth.is_decided:
            return None
        graded = _score_top(top, window_truth)
        estimated_share = (
            abs(top.delta) / abs(where.total_delta)
            if top is not None and where is not None and abs(where.total_delta) > 0.0
            else float("nan")
        )
        return BacktestOutcome(
            event_id=str(row.event_id),
            event_type=str(row.type),
            detectability=str(row.detectability),
            data_condition=str(row.data_condition),
            window_start=start,
            window_end=end,
            measure_end=pd.Timestamp(row.measure_end).date(),
            excluded_from_fit=bool(row.excluded_from_calibration_fit),
            detected=detection.p_value <= self._alpha,
            p_value=detection.p_value,
            delta_pct=detection.delta_pct,
            raw_score=result.composite,
            tier=result.tier,
            correct=bool(graded[0]),
            gradeable=graded[0] is not None,
            stability=top.stability if top is not None else 0.0,
            total_delta=float(where.total_delta) if where is not None else 0.0,
            estimated_top=top.label if top is not None else "—",
            concurrent_events=window_truth.contributors,
            true_top_region=window_truth.dominant["region"],
            true_top_category=window_truth.dominant["category"],
            estimated_share=estimated_share,
            true_share=graded[1],
            coverage=where.coverage if where else 0.0,
        )


def _score_top(top: object | None, truth: WindowTruth) -> tuple[bool | None, float]:
    """Was the top segment the window's dominant cause, on the dimensions it names?

    Adtributor reports whichever dimension carries the movement most surprisingly —
    sometimes a region, sometimes a category, sometimes a pair. A claim is counted
    correct only when **every** gradeable dimension it names matches: naming the right
    category and the wrong region is a wrong answer, not a half-right one, because it
    sends someone to the wrong desk. A claim on a dimension the ledger records no truth
    for (channel) is neither credited nor penalised on that dimension.

    The share returned is truth's share on the dimension the claim leads with, so the
    error term compares like with like.
    """
    if top is None:
        return False, float("nan")
    dimensions = [str(name) for name in getattr(top, "dimensions", ())]
    members = [str(value) for value in getattr(top, "members", ())]
    checkable = [
        (name, value)
        for name, value in zip(dimensions, members, strict=True)
        if name in truth.dominant
    ]
    if not checkable:
        # A claim only about channel. The ledger plants no channel-scoped mechanism, so
        # there is no answer key: returning ``None`` drops the row from the accuracy
        # denominator rather than scoring it wrong, which would penalise the engine for
        # a question this corpus cannot pose.
        return None, float("nan")
    correct = all(truth.matches(name, value) for name, value in checkable)
    return correct, truth.share[checkable[0][0]]
