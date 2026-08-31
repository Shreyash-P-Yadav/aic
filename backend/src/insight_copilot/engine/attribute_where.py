"""Rung 1 — *where* the move is: Adtributor over the dimensional cube.

Two quantities, multiplied:

* **Explanatory power.** ``EP_s = (A_s - F_s) / (A_tot - F_tot)`` — how much of the
  total gap this segment accounts for. Large segments dominate it, which is right: a
  1% dip in a segment carrying half the business matters more than a 40% dip in one
  carrying 0.3%.
* **Surprise.** The segment's contribution to the Jensen-Shannon divergence between the
  actual and forecast *share* distributions. Small segments dominate it, which is also
  right: a segment behaving completely unlike its forecast is informative however small.

Their product is what makes Adtributor find the segment that is both big enough to
matter and odd enough to be the cause, rather than the biggest segment (always the same
one) or the weirdest (always a rounding error).

Three guards that turn a ranking into an answer worth stating:

* **Minimum observations.** A segment with a handful of rows has an unstable share and
  an EP that is mostly noise.
* **Simpson's-paradox check.** A parent segment whose children move the *other* way is
  reported as a paradox rather than as a cause. The world contains a planted one.
* **Bootstrap stability.** A hundred resamples, and a win rate. **A cause below the
  stability floor is reported as a ranked shortlist, never as a named cause** — which
  is the difference between an analysis and a guess with a confident voice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd

from insight_copilot.errors import StatisticalError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MIN_SEGMENT_OBSERVATIONS = 20
"""Rows a segment needs before its share is estimated rather than guessed."""

TOP_K_PER_DIMENSION = 5
"""Survivors carried from each single-dimension pass into the combination search.
Searching all pairs of all members is combinatorial and mostly tests noise."""

MAX_COMBINATION_DEPTH = 2
"""Two dimensions. A three-dimension cause is not actionable — nobody owns
'quick-commerce x North x Haircare' — and the search cost triples."""

PARETO_COVERAGE = 0.85
"""Smallest non-overlapping set of segments covering this much of the gap."""

MAX_REPORTED_SEGMENTS = 4
"""However much coverage is left, a list of five causes is not a finding."""

BOOTSTRAP_SAMPLES = 100
"""Resamples for the stability check. Enough to resolve a win rate to about 5%."""

STABILITY_FLOOR = 0.90
"""Below this win rate the top segment is a shortlist entry, not a named cause."""

MIN_ABS_EP = 0.02
"""A segment explaining under 2% of the gap is noise however surprising it looks."""


@dataclass(frozen=True)
class SegmentScore:
    """One candidate segment and everything the ranking used."""

    dimensions: tuple[str, ...]
    members: tuple[str, ...]
    actual: float
    forecast: float
    explanatory_power: float
    surprise: float
    score: float
    observations: int
    stability: float = 0.0
    simpson_flag: bool = False

    @property
    def label(self) -> str:
        """``region=North x channel=quick_commerce``."""
        return " x ".join(
            f"{dimension}={member}"
            for dimension, member in zip(self.dimensions, self.members, strict=True)
        )

    @property
    def delta(self) -> float:
        """The segment's own gap against its forecast."""
        return self.actual - self.forecast


@dataclass
class WhereResult:
    """The Adtributor verdict, and whether it is stable enough to name."""

    candidates: list[SegmentScore]
    reported: list[SegmentScore] = field(default_factory=list)
    coverage: float = 0.0
    total_delta: float = 0.0
    is_named_cause: bool = False
    detail: str = ""

    @property
    def top(self) -> SegmentScore | None:
        """The highest-scoring candidate, named or not."""
        return self.candidates[0] if self.candidates else None


def jensen_shannon_terms(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Per-segment contributions to ``JS(p ‖ q)`` between two share distributions.

    The square root is not taken: the divergence's *decomposition* into per-segment
    terms is what is wanted here, and only the divergence itself decomposes additively.
    """
    p = _shares(actual)
    q = _shares(forecast)
    m = 0.5 * (p + q)
    with np.errstate(divide="ignore", invalid="ignore"):
        left = np.where(p > 0, p * np.log(p / m), 0.0)
        right = np.where(q > 0, q * np.log(q / m), 0.0)
    terms: np.ndarray = 0.5 * (np.nan_to_num(left) + np.nan_to_num(right))
    return terms


def score_dimension(
    frame: pd.DataFrame,
    dimensions: tuple[str, ...],
    *,
    actual_column: str,
    forecast_column: str,
    count_column: str | None = None,
) -> list[SegmentScore]:
    """Score every member of one dimension (or combination) by ``EP x Surprise``."""
    grouped = frame.groupby(list(dimensions), observed=True).agg(
        actual=(actual_column, "sum"), forecast=(forecast_column, "sum")
    )
    counts = (
        frame.groupby(list(dimensions), observed=True)[count_column].sum()
        if count_column
        else frame.groupby(list(dimensions), observed=True).size()
    )
    grouped["observations"] = counts
    if grouped.empty:
        return []

    actual = grouped["actual"].to_numpy(dtype=np.float64)
    forecast = grouped["forecast"].to_numpy(dtype=np.float64)
    total_delta = float(actual.sum() - forecast.sum())
    if abs(total_delta) < 1e-9:
        raise StatisticalError(
            "Adtributor needs a non-zero total gap",
            detail="explanatory power is undefined when actual equals forecast",
        )
    explanatory = (actual - forecast) / total_delta
    surprise = jensen_shannon_terms(actual, forecast)

    scores: list[SegmentScore] = []
    for position, key in enumerate(grouped.index):
        members = key if isinstance(key, tuple) else (key,)
        observations = int(grouped["observations"].iloc[position])
        if observations < MIN_SEGMENT_OBSERVATIONS:
            continue
        scores.append(
            SegmentScore(
                dimensions=dimensions,
                members=tuple(str(member) for member in members),
                actual=float(actual[position]),
                forecast=float(forecast[position]),
                explanatory_power=float(explanatory[position]),
                surprise=float(surprise[position]),
                score=float(explanatory[position] * surprise[position]),
                observations=observations,
            )
        )
    return sorted(scores, key=lambda item: item.score, reverse=True)


class Attributor:
    """Rung 1 of the ladder: which segments account for the movement."""

    def __init__(
        self,
        *,
        bootstrap_samples: int = BOOTSTRAP_SAMPLES,
        stability_floor: float = STABILITY_FLOOR,
        seed: int = 0,
    ) -> None:
        self._samples = bootstrap_samples
        self._floor = stability_floor
        self._rng = np.random.default_rng(seed)

    def attribute(
        self,
        frame: pd.DataFrame,
        dimensions: list[str],
        *,
        actual_column: str,
        forecast_column: str,
    ) -> WhereResult:
        """Score each dimension, then the pairs among survivors, then decide."""
        singles: dict[str, list[SegmentScore]] = {}
        for dimension in dimensions:
            scored = score_dimension(
                frame, (dimension,), actual_column=actual_column, forecast_column=forecast_column
            )
            singles[dimension] = [
                item for item in scored if abs(item.explanatory_power) >= MIN_ABS_EP
            ][:TOP_K_PER_DIMENSION]

        candidates = [item for scored in singles.values() for item in scored]
        survivors = [dimension for dimension, scored in singles.items() if scored]
        for pair in combinations(survivors, MAX_COMBINATION_DEPTH):
            restricted = _restrict(frame, singles, pair)
            if restricted.empty:
                continue
            candidates.extend(
                item
                for item in score_dimension(
                    restricted, pair, actual_column=actual_column, forecast_column=forecast_column
                )
                if abs(item.explanatory_power) >= MIN_ABS_EP
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        if not candidates:
            return WhereResult(candidates=[], detail="no segment cleared the minimum-EP floor")

        flagged = self._flag_simpson(candidates, frame, dimensions, actual_column, forecast_column)
        stable = self._with_stability(flagged, frame, actual_column, forecast_column)
        reported, coverage = _pareto(stable)
        total_delta = float(frame[actual_column].sum() - frame[forecast_column].sum())
        top = stable[0]
        named = top.stability >= self._floor and not top.simpson_flag
        return WhereResult(
            candidates=stable,
            reported=reported,
            coverage=coverage,
            total_delta=total_delta,
            is_named_cause=named,
            detail=(
                f"{top.label} explains {top.explanatory_power:.0%} of the gap with a "
                f"bootstrap win rate of {top.stability:.0%}"
                + ("" if named else " — below the stability floor, reported as a shortlist")
            ),
        )

    # -------------------------------------------------------------- stability --
    def _with_stability(
        self,
        candidates: list[SegmentScore],
        frame: pd.DataFrame,
        actual_column: str,
        forecast_column: str,
    ) -> list[SegmentScore]:
        """Resample rows and count how often each candidate wins its own dimension."""
        wins: dict[tuple[tuple[str, ...], tuple[str, ...]], int] = {}
        n = len(frame)
        for _ in range(self._samples):
            sample = frame.iloc[self._rng.integers(0, n, n)]
            for dimensions in {item.dimensions for item in candidates}:
                try:
                    scored = score_dimension(
                        sample,
                        dimensions,
                        actual_column=actual_column,
                        forecast_column=forecast_column,
                    )
                except StatisticalError:
                    continue
                if scored:
                    key = (dimensions, scored[0].members)
                    wins[key] = wins.get(key, 0) + 1
        return [
            SegmentScore(
                **{
                    **vars(item),
                    "stability": wins.get((item.dimensions, item.members), 0) / self._samples,
                }
            )
            for item in candidates
        ]

    # ---------------------------------------------------------------- simpson --
    @staticmethod
    def _flag_simpson(
        candidates: list[SegmentScore],
        frame: pd.DataFrame,
        dimensions: list[str],
        actual_column: str,
        forecast_column: str,
    ) -> list[SegmentScore]:
        """Flag a segment whose nested children move against it.

        This is the planted paradox: a segment can improve overall while every one of
        its parts gets worse, purely because the mix between the parts moved. Naming it
        as a cause would be a true sentence and a false explanation.
        """
        flagged: list[SegmentScore] = []
        for item in candidates:
            nested = [name for name in dimensions if name not in item.dimensions]
            paradox = False
            if len(item.dimensions) == 1 and nested:
                subset = frame[frame[item.dimensions[0]].astype(str) == item.members[0]]
                parent_delta = float(subset[actual_column].sum() - subset[forecast_column].sum())
                for child in nested:
                    grouped = subset.groupby(child, observed=True)
                    children = grouped[actual_column].sum() - grouped[forecast_column].sum()
                    if children.empty or parent_delta == 0.0:
                        continue
                    if np.all(np.sign(children.to_numpy()) == -np.sign(parent_delta)):
                        paradox = True
                        break
            flagged.append(SegmentScore(**{**vars(item), "simpson_flag": paradox}))
        return flagged


def _restrict(
    frame: pd.DataFrame, singles: dict[str, list[SegmentScore]], pair: tuple[str, ...]
) -> pd.DataFrame:
    """Rows whose members survived the single-dimension pass on both dimensions."""
    restricted = frame
    for dimension in pair:
        keep = {item.members[0] for item in singles[dimension]}
        restricted = restricted[restricted[dimension].astype(str).isin(keep)]
    return restricted


def _pareto(candidates: list[SegmentScore]) -> tuple[list[SegmentScore], float]:
    """Smallest non-overlapping set covering ``PARETO_COVERAGE`` of the gap, capped."""
    reported: list[SegmentScore] = []
    used_dimensions: set[str] = set()
    coverage = 0.0
    for item in candidates:
        if set(item.dimensions) & used_dimensions:
            continue
        reported.append(item)
        used_dimensions.update(item.dimensions)
        coverage += abs(item.explanatory_power)
        if coverage >= PARETO_COVERAGE or len(reported) >= MAX_REPORTED_SEGMENTS:
            break
    return reported, coverage


def _shares(values: np.ndarray) -> np.ndarray:
    """Normalise to a distribution, guarding a zero or negative total."""
    positive = np.clip(values, 0.0, None)
    total = positive.sum()
    return positive / total if total > 0 else np.zeros_like(positive)
