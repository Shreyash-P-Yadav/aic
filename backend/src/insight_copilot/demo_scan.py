"""One KPI, scanned end to end — the path both the demo and the demo controls use.

Factored out of :mod:`insight_copilot.demo` for two reasons. The demo showed a single
insight, which made a feed designed to prioritise look like a page with one card on it.
And the interactive controls had no way to re-run the engine, so breaking a feed changed
the world without changing anything a viewer could see.

A scan is described by a :class:`ScanSpec` rather than by a function per KPI, because the
only things that differ between KPIs are the measure the cube carries for them, the
window to judge, and the words to search the corpus with. Everything else — baseline,
conformal detection, attribution, evidence, the six signals — is the same path.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from insight_copilot.api.schemas import KpiSeriesResponse
from insight_copilot.api.state import AppState, InsightRecord
from insight_copilot.demo_ladder import LadderRungs, build_rungs
from insight_copilot.engine.attribute_where import Attributor, WhereResult
from insight_copilot.engine.bundle import AbstentionArtifact, InsightEvidenceBundle
from insight_copilot.engine.cube import CubeWindow, national_factor, segment_actual_forecast
from insight_copilot.engine.dataset import EngineDataset
from insight_copilot.engine.detect import ConformalDetector, apply_fdr
from insight_copilot.engine.evidence import EvidenceRetriever
from insight_copilot.engine.pipeline import InsightEngine, RunInputs
from insight_copilot.engine.regression_baseline import RegressionBaseline, calendar_events
from insight_copilot.engine.series import Series
from insight_copilot.errors import ContractError, StatisticalError
from insight_copilot.ingest.models import FreshnessStatus
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

CHART_DAYS = 180
"""Days of history returned with each insight for its chart."""

MIN_OBSERVED_FRACTION = 0.80
"""Share of days a KPI must actually be observed on before a baseline is fitted.

Additive KPIs zero-fill an absent day, which is correct — no sales row means no revenue.
A ratio cannot: an unobserved fill rate is unknown, not zero. Below this coverage the
regression is interpolating more than it is fitting, so the scan declines and says so."""

ATTRIBUTION_DIMENSIONS = ["region", "channel", "category"]
"""The dimensions Adtributor searches. Warehouse, SKU and customer segment are in the
cube too, but a cause nobody owns is not actionable — 'quick-commerce x North' has a
desk; 'SKU-0421 x new customers x DC-West' does not."""


@dataclass(frozen=True)
class ScanSpec:
    """Everything that differs between one KPI's scan and another's."""

    kpi_id: str
    cube_measure: str
    """The column in ``gold.cube_revenue`` that this KPI is measured by. Attribution is
    skipped when a KPI has no cube measure — and skipping is reported, because an
    insight that quietly names no segment looks the same as one that found none."""

    window: tuple[dt.date, dt.date]
    detection_window: tuple[dt.date, dt.date]
    evidence_query: str
    entities: list[str] = field(default_factory=list)
    lever_change: float = 0.0
    alpha: float = 0.01
    ladder: bool = False
    """Run rungs 2 and 3 (Bennet, driver regression) for this KPI.

    Only meaningful for revenue: the Bennet decomposition is defined over price x
    quantity and the driver regression is specified against revenue. Both must run
    BEFORE the engine, not be patched on afterwards — the ``c3`` confidence signal reads
    the regression diagnostics, and every driver figure needs a NumberFact for the
    verifier to check the narrative against. Attaching them later cost a confidence tier
    and made five of eight narratives fail their own verification."""


@dataclass
class ScanOutcome:
    """What a scan produced, and enough context to explain a blank result."""

    record: InsightRecord | None
    detail: str


def scan(
    spec: ScanSpec,
    *,
    dataset: EngineDataset,
    state: AppState,
    warehouse: object,
    documents: list[object],
    freshness: list[FreshnessStatus],
    calibration_exclusions: tuple[tuple[dt.date, dt.date], ...] = (),
) -> ScanOutcome:
    """Detect, attribute, retrieve, score and package one KPI.

    Returns an outcome rather than raising when nothing is found: "no movement cleared
    the bar" is a normal, and in fact desirable, result — it is the fourth scenario the
    brief asks for. A KPI whose data will not load is a different thing and says so.
    """
    contract = state.registry.kpi(spec.kpi_id)
    try:
        series = dataset.kpi_series(spec.kpi_id, state.session)
    except (ContractError, StatisticalError) as exc:
        return ScanOutcome(None, f"{spec.kpi_id}: series unavailable ({exc})")
    if len(series) < contract.confidence_policy.min_history_days_full_stats:
        # Scenario C: too little history to judge. The right answer is to say nothing,
        # and to say why.
        return ScanOutcome(
            None,
            f"{spec.kpi_id}: {len(series)} days against a "
            f"{contract.confidence_policy.min_history_days_full_stats}-day floor",
        )
    observed = float(np.isfinite(series.values).mean())
    if observed < MIN_OBSERVED_FRACTION:
        # A ratio KPI has no zero-fill, so an unobserved day is genuinely unknown rather
        # than nought. Below this coverage the baseline is fitting more gap than data,
        # and declining is more useful than a counterfactual nobody should rely on.
        return ScanOutcome(
            None,
            f"{spec.kpi_id}: only {observed:.0%} of days observed, below the "
            f"{MIN_OBSERVED_FRACTION:.0%} floor for a baseline",
        )

    expected = _counterfactual(dataset, state, warehouse, series, spec.detection_window)
    held_out = series.mask_between(*spec.detection_window)
    calibration = ~held_out
    for start, end in calibration_exclusions:
        calibration &= ~series.mask_between(start, end)

    detections = apply_fdr(
        ConformalDetector(alpha=spec.alpha).scan(
            kpi_id=spec.kpi_id,
            segment="national",
            series=series,
            expected=expected,
            calibration_mask=calibration,
            test_mask=held_out,
        ),
        contract.materiality.statistical.fdr_q,
    )
    survivors = [item for item in detections if item.passed_fdr]
    if not survivors:
        # Scenario D: real, clean, and below the bar. Silence is the right answer, and
        # the reason is recorded so a presenter can say WHY nothing was reported.
        return ScanOutcome(None, f"{spec.kpi_id}: no movement survived the FDR correction")

    detection = min(survivors, key=lambda item: item.day)
    where = _attribute(dataset, state, series, expected, spec)
    rungs = build_rungs(warehouse, contract, spec.window) if spec.ladder else None  # type: ignore[arg-type]
    action_metrics = _observed_metrics(dataset, state, spec, rungs)
    evidence = EvidenceRetriever(documents).retrieve(  # type: ignore[arg-type]  # Document
        spec.evidence_query,
        effect_day=detection.day,
        entities=spec.entities,
        floor=contract.confidence_policy.evidence_floor,
    )
    result = InsightEngine().run(
        RunInputs(
            contract=contract,
            detection=detection,
            where=where,
            why=rungs.why if rungs else None,
            evidence=evidence,
            price_effect=rungs.price_effect if rungs else None,
            volume_effect=rungs.volume_effect if rungs else None,
            mix_effect=rungs.mix_effect if rungs else None,
            pvm_reference=rungs.reference_revenue if rungs else None,
            pvm_comparison=rungs.comparison_revenue if rungs else None,
            pvm_label=rungs.label if rungs else "",
            freshness=freshness,
            required_sources=[source.source_id for source in contract.sources if source.required],
            history_days=len(series),
            period=spec.window,
            baseline_value=float(expected[held_out].sum()),
            lever_change=spec.lever_change,
            observed_metrics=action_metrics,
        ),
        now=dt.datetime.now(dt.UTC),
    )
    record = InsightRecord(
        insight_id=result.insight_id,
        kpi_id=result.kpi_id,
        created_at=dt.datetime.now(dt.UTC),
        bundle=result if isinstance(result, InsightEvidenceBundle) else None,
        abstention=result if isinstance(result, AbstentionArtifact) else None,
        series=series_response(spec.kpi_id, contract.definition.unit, series, expected, spec),
    )
    return ScanOutcome(record, f"{spec.kpi_id}: {result.__class__.__name__}")


def _observed_metrics(
    dataset: EngineDataset,
    state: AppState,
    spec: ScanSpec,
    rungs: LadderRungs | None,
) -> dict[str, float]:
    """The operational metrics an action's preconditions are checked against.

    Only what the warehouse can actually answer. Two metrics the supply catalog asks for
    — ``days_cover`` and ``cross_serve_headroom_pct`` — have no mart in this build, so
    they are deliberately absent rather than defaulted: the action selector treats an
    *unevaluable* precondition exactly like a failed one and withholds the action, which
    is the correct behaviour. Supplying a plausible zero would silently convert "we could
    not check this" into "this passed", which is the precise failure the guard exists to
    prevent.

    An empty dict on any failure, for the same reason: no metrics means every
    precondition is unchecked means no action is proposed.
    """
    metrics: dict[str, float] = {}
    why = rungs.why if rungs is not None else None
    if why is not None:
        metrics["max_vif"] = float(why.diagnostics.max_vif)
        metrics["estimator_agreement"] = float(why.agreement_score)
    try:
        panel = dataset.national_panel(state.session, start=spec.window[0], end=spec.window[1])
    except (ContractError, StatisticalError) as exc:
        logger.warning("scan.metrics_unavailable", kpi_id=spec.kpi_id, error=str(exc))
        return {key: value for key, value in metrics.items() if value == value}
    if not panel.empty:
        for column in ("fill_rate_pct", "discount_depth_pct", "daily_spend_inr"):
            if column in panel.columns:
                metrics[column] = float(panel[column].mean())
        metrics.update(_price_and_margin(dataset, state, spec))
    logger.info("scan.observed_metrics", kpi_id=spec.kpi_id, metrics=sorted(metrics))
    return {key: value for key, value in metrics.items() if value == value}


def _price_and_margin(
    dataset: EngineDataset,
    state: AppState,
    spec: ScanSpec,
) -> dict[str, float]:
    """Price index and gross margin over the reported window, from the cube.

    ``price_index`` is average selling price in the window over the same average in the
    four weeks before it — a relative measure, which is what a precondition reading
    "price_index above 1.02" is asking about. Computing it against a fixed constant
    would make the threshold mean something different in every category.
    """
    window = CubeWindow.ending_before(*spec.window)
    try:
        cube = dataset.cube(state.session, start=window.baseline_start, end=window.test_end)
    except (ContractError, StatisticalError) as exc:
        logger.warning("scan.cube_metrics_unavailable", error=str(exc))
        return {}
    if cube.empty:
        return {}
    stamps = pd.to_datetime(cube["date"]).dt.date
    test = cube.loc[(stamps >= window.test_start) & (stamps <= window.test_end)]
    base = cube.loc[(stamps >= window.baseline_start) & (stamps <= window.baseline_end)]
    metrics: dict[str, float] = {}

    revenue = float(test["net_revenue_inr"].sum())
    if revenue > 0 and "cost_inr" in test.columns:
        metrics["gross_margin_pct"] = 100.0 * (revenue - float(test["cost_inr"].sum())) / revenue
    test_units, base_units = float(test["units"].sum()), float(base["units"].sum())
    base_revenue = float(base["net_revenue_inr"].sum())
    if test_units > 0 and base_units > 0 and base_revenue > 0:
        metrics["price_index"] = (revenue / test_units) / (base_revenue / base_units)
    return metrics


def series_response(
    kpi_id: str, unit: str, series: Series, expected: np.ndarray, spec: ScanSpec
) -> KpiSeriesResponse:
    """The tail of the series and its counterfactual, for the insight's chart."""
    dates = series.dates[-CHART_DAYS:]
    return KpiSeriesResponse(
        kpi_id=kpi_id,
        unit=unit,
        dates=[str(day.astype("datetime64[D]")) for day in dates],
        actual=[float(value) for value in series.values[-CHART_DAYS:]],
        counterfactual=[float(value) for value in expected[-CHART_DAYS:]],
        window_start=spec.detection_window[0].isoformat(),
        window_end=spec.detection_window[1].isoformat(),
    )


def _counterfactual(
    dataset: EngineDataset,
    state: AppState,
    warehouse: object,
    series: Series,
    window: tuple[dt.date, dt.date],
) -> np.ndarray:
    """Fit the baseline with the judged window held out, so it never learns the event."""
    calendar = warehouse.query(  # type: ignore[attr-defined]
        "SELECT date, is_holiday FROM gold.dim_calendar ORDER BY date"
    )
    panel = dataset.national_panel(state.session)
    baseline = RegressionBaseline(
        events=calendar_events(calendar),
        controls=panel[["date", "rainfall_mm", "temp_max_c", "discount_depth_pct"]],
    )
    baseline.fit(series.exclude(series.mask_between(*window)))
    counterfactual: np.ndarray = baseline.counterfactual(series)
    return counterfactual


def _attribute(
    dataset: EngineDataset,
    state: AppState,
    series: Series,
    expected: np.ndarray,
    spec: ScanSpec,
) -> WhereResult | None:
    """Rung 1 over the reported window, or ``None`` when the cube cannot support it."""
    if not spec.cube_measure:
        return None
    week = series.mask_between(*spec.window)
    window = CubeWindow.ending_before(*spec.window)
    baseline_mask = series.mask_between(window.baseline_start, window.baseline_end)
    if not week.any() or not baseline_mask.any():
        return None
    try:
        cube = dataset.cube(state.session, start=window.baseline_start, end=window.test_end)
        factor = national_factor(
            float(expected[week].sum()), float(series.values[baseline_mask].sum()), window
        )
        frame = segment_actual_forecast(
            cube,
            window,
            dimensions=ATTRIBUTION_DIMENSIONS,
            measure=spec.cube_measure,
            national_factor=factor,
        )
        return Attributor(seed=7).attribute(
            frame,
            ATTRIBUTION_DIMENSIONS,
            actual_column="actual",
            forecast_column="forecast",
        )
    except (ContractError, StatisticalError) as exc:
        logger.warning("scan.attribution_failed", kpi_id=spec.kpi_id, error=str(exc))
        return None
