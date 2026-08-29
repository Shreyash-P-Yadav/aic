"""Computing every event's true causal contribution and writing `data/ledger.parquet`.

This is the artefact that turns the confidence score from an assertion into a measured
probability. For every event it records what actually happened, what would have
happened without it, and the difference — at national level and by top segment.

Two effects are recorded per event:

* **Total effect** — the full re-run, including operational feedback. Replenishment
  reacts, media budget reacts to last week's revenue, substitution moves demand
  between SKUs. This is what a CFO means by "what did the outage cost us", and it is
  what the engine is scored against.
* **Direct effect** — the same counterfactual with downstream *decisions* frozen at
  their factual paths, so only the mechanical channel is measured. The gap between
  the two is the size of the operational feedback, which is worth showing.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.datagen.truth.counterfactual import (
    CounterfactualRunner,
    InteractionGroup,
    group_interacting_events,
)
from insight_copilot.datagen.truth.measure import (
    EffectMeasurement,
    measure_effect,
    measurement_window,
)
from insight_copilot.datagen.truth.planner import RunPlan, build_run_plan
from insight_copilot.datagen.truth.shapley import shapley_from_values
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

LEDGER_NAME = "ledger.parquet"
SUMMARY_NAME = "ledger_summary.json"


@dataclass(frozen=True)
class TruthLedger:
    """The computed ground truth, as a table plus the run statistics."""

    frame: pd.DataFrame
    n_runs: int
    n_events: int
    elapsed_seconds: float

    def summary(self) -> str:
        """One-paragraph report for the CLI."""
        return (
            f"OK    ground truth for {self.n_events} events in {self.n_runs} "
            f"simulation runs ({self.elapsed_seconds:.0f}s)"
        )


class GroundTruthComputer:
    """Runs the counterfactual plan and assembles the ledger.

    **Memory is the binding constraint, not time.** Each simulated world is about
    170 MB of arrays, so holding all 149 planned runs would need 25 GB. Instead every
    run is consumed the moment it is produced: the coalition scalars Shapley needs are
    read off, any event whose isolating counterfactual this run realises is measured
    against the factual world, and the panel is then dropped. Peak memory is two
    panels — the factual one, which every measurement compares against, and the run in
    hand.
    """

    def __init__(self, simulator: Simulator, events: list[Event]) -> None:
        self._simulator = simulator
        self._events = list(events)
        self._mechanical = [
            event
            for event in events
            if event.ground_truth.compute and event.magnitude.kind != "none"
        ]
        self._runner = CounterfactualRunner(simulator, self._events)

    def compute(self) -> TruthLedger:
        """Compute every event's contribution. Returns the ledger frame."""
        import time

        started = time.perf_counter()
        groups = group_interacting_events(self._mechanical)
        plan = build_run_plan(groups)
        windows = [self._group_window(group) for group in groups]

        wanted_values, wanted_measures = self._index_wants(groups, plan)
        values, measurements = self._execute(plan, windows, wanted_values, wanted_measures)
        rows = self._rows(groups, values, measurements)

        elapsed = time.perf_counter() - started
        logger.info("truth.ledger_built", events=len(rows), runs=plan.n_runs)
        return TruthLedger(
            frame=pd.DataFrame(rows),
            n_runs=plan.n_runs,
            n_events=len(rows),
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------ scheduling --
    def _index_wants(
        self, groups: list[InteractionGroup], plan: RunPlan
    ) -> tuple[dict[int, list[tuple[int, frozenset[str]]]], dict[int, list[Event]]]:
        """For each run, what must be read off it before the panel is discarded.

        Two things: the coalition scalars for Shapley, and the full segment-level
        measurement for any event whose "everything except me" world this run is.
        """
        values: dict[int, list[tuple[int, frozenset[str]]]] = {}
        for (group_index, present), run in plan.index_of.items():
            values.setdefault(run, []).append((group_index, present))

        measures: dict[int, list[Event]] = {}
        for group_index, group in enumerate(groups):
            everything = frozenset(group.event_ids)
            for event in group.events:
                key = (group_index, everything - {event.event_id})
                run_index = plan.index_of.get(key)
                if run_index is not None:
                    measures.setdefault(run_index, []).append(event)
        return values, measures

    def _execute(
        self,
        plan: RunPlan,
        windows: list[slice],
        wanted_values: dict[int, list[tuple[int, frozenset[str]]]],
        wanted_measures: dict[int, list[Event]],
    ) -> tuple[dict[int, dict[frozenset[str], float]], dict[str, EffectMeasurement]]:
        """Run the plan, reading each world once and then letting it go."""
        factual = self._runner.factual
        horizon_start = self._simulator.config.horizon.start
        values: dict[int, dict[frozenset[str], float]] = {}
        measurements: dict[str, EffectMeasurement] = {}
        step = max(1, plan.n_runs // 10)

        for index, removal in enumerate(plan.removals):
            if index % step == 0 or index == plan.n_runs - 1:
                logger.info("truth.progress", run=index + 1, of=plan.n_runs)
            panel = self._runner.without(set(removal))
            revenue = panel.net_revenue_by_day()

            for group_index, present in wanted_values.get(index, []):
                values.setdefault(group_index, {})[present] = float(
                    revenue[windows[group_index]].sum()
                )
            for event in wanted_measures.get(index, []):
                measurements[event.event_id] = measure_effect(
                    event=event,
                    factual=factual,
                    counterfactual=panel,
                    cells=self._simulator.assortment,
                    config=self._simulator.config,
                    catalog=self._simulator.catalog,
                    horizon_start=horizon_start,
                )
            del panel, revenue
        return values, measurements

    # ------------------------------------------------------------------ rows --
    def _rows(
        self,
        groups: list[InteractionGroup],
        values: dict[int, dict[frozenset[str], float]],
        measurements: dict[str, EffectMeasurement],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for group_index, group in enumerate(groups):
            result = shapley_from_values(group.event_ids, values[group_index])
            for event in group.events:
                measurement = measurements[event.event_id]
                rows.append(
                    {
                        "event_id": event.event_id,
                        "group_id": f"G{group_index:04d}",
                        "event_set": event.event_set,
                        "type": event.type,
                        "mechanism": event.magnitude.kind,
                        "demo_role": event.demo_role,
                        "detectability": event.detectability,
                        "data_condition": event.data_condition,
                        "window_start": event.window.start,
                        "window_end": event.window.end,
                        "measure_start": measurement.window_start,
                        "measure_end": measurement.window_end,
                        # Shapley value when the event interacts with others,
                        # otherwise the plain counterfactual delta. Both are the
                        # TOTAL effect: the full re-run, with operational feedback.
                        "true_contribution_inr": result.contributions[event.event_id],
                        "group_total_inr": result.total,
                        "group_method": result.method,
                        "group_size": len(group.events),
                        "isolated_delta_inr": measurement.revenue_delta,
                        "isolated_delta_pct": measurement.revenue_delta_pct,
                        "scoped_delta_pct": measurement.scoped_delta_pct,
                        "scoped_factual_inr": measurement.scoped_factual_revenue,
                        "scoped_counterfactual_inr": measurement.scoped_counterfactual_revenue,
                        "units_delta": measurement.units_delta,
                        "true_top_region": measurement.top_region,
                        "true_top_region_share": measurement.top_region_share,
                        "true_top_category": measurement.top_category,
                        "true_top_category_share": measurement.top_category_share,
                        "evidence_documents": event.evidence.documents,
                        "evidence_syndication": event.evidence.syndication,
                        "evidence_contradiction": event.evidence.contradiction,
                        "evidence_post_dated_decoy": event.evidence.post_dated_decoy,
                        "excluded_from_calibration_fit": event.is_scenario,
                    }
                )
        return rows

    def _group_window(self, group: InteractionGroup) -> slice:
        """Day slice covering every member's measurement window."""
        horizon_start = self._simulator.config.horizon.start
        n_days = self._runner.factual.n_days
        windows = [measurement_window(event, horizon_start, n_days) for event in group.events]
        return slice(min(w.start for w in windows), max(w.stop for w in windows))


def write_ledger(ledger: TruthLedger, data_dir: Path) -> Path:
    """Write `ledger.parquet` and a small JSON summary beside it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LEDGER_NAME
    ledger.frame.to_parquet(path, index=False)

    frame = ledger.frame
    summary = {
        "events": len(frame),
        "runs": ledger.n_runs,
        "elapsed_seconds": round(ledger.elapsed_seconds, 1),
        "by_set": frame["event_set"].value_counts().to_dict(),
        "scenario_events_excluded_from_fit": int(frame["excluded_from_calibration_fit"].sum()),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "note": "All data is simulated. Contributions are total effects, in INR.",
    }
    (data_dir / SUMMARY_NAME).write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
    logger.info("truth.ledger_written", path=str(path), rows=len(frame))
    return path
