"""Seasonal period discovery. **Never assume 7 and 365.**

A weekly cycle is the obvious guess for a consumer business and it is usually right —
but "usually right" is not a method, and a series that turns out to have a fortnightly
promotional cycle or no weekly structure at all would be decomposed against a period
it does not have. That produces a seasonal component made of noise and a residual with
the real signal removed, which is the worst possible input to a detector.

So: a periodogram proposes, and the autocorrelation function disposes. A candidate
period is accepted only if its ACF at that lag clears the white-noise significance
band, which is what distinguishes a genuine cycle from the largest bar in a spectrum
that has no peaks at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from insight_copilot.engine.series import Series

MIN_PERIOD = 2
"""A period of one is not a cycle."""

MAX_PERIOD_FRACTION = 0.34
"""A candidate period longer than a third of the series cannot be observed three
times, and three cycles is the least that distinguishes a cycle from a trend."""

ACF_SIGNIFICANCE_Z = 1.96
"""Two-sided 5% band for a white-noise ACF, whose standard error is 1/sqrt(n)."""

PROMINENCE_MARGIN = 0.5
"""A confirmed period's ACF must exceed its neighbouring lags by this fraction of the
significance band. Significance alone is not enough: a smooth series has a high ACF at
*every* short lag, so lag 2 clears the band on autocorrelation rather than periodicity.
A seasonal cycle is a local *peak* — that is what distinguishes it from smoothness."""

TOP_CANDIDATES = 6
"""Spectral peaks tested against the ACF. Beyond a handful the test is fishing."""

ANNUAL_PERIOD = 365
"""Offered as a candidate whenever the series is long enough to see two of them; the
periodogram resolves low frequencies too coarsely to find it reliably on its own."""


@dataclass(frozen=True)
class PeriodEvidence:
    """One candidate period and why it was kept or rejected."""

    period: int
    spectral_power: float
    acf: float
    acf_threshold: float
    accepted: bool

    @property
    def reason(self) -> str:
        """A sentence for the evidence drawer."""
        verdict = "confirmed" if self.accepted else "rejected"
        return (
            f"period {self.period}: spectral power {self.spectral_power:.3g}, "
            f"ACF {self.acf:.3f} against a {self.acf_threshold:.3f} significance band "
            f"— {verdict}"
        )


def autocorrelation(values: np.ndarray, max_lag: int) -> np.ndarray:
    """Sample ACF at lags ``0..max_lag`` of a mean-centred series."""
    centred = values - values.mean()
    denominator = float(np.dot(centred, centred))
    if denominator <= 0.0:
        return np.zeros(max_lag + 1)
    full = np.correlate(centred, centred, mode="full")[centred.size - 1 :]
    acf: np.ndarray = full[: max_lag + 1] / denominator
    return acf


def _prominence(acf: np.ndarray, period: int) -> float:
    """How far a lag's ACF stands above its immediate neighbours."""
    if period >= acf.size:
        return -np.inf
    neighbours = [acf[lag] for lag in (period - 1, period + 1) if 0 < lag < acf.size]
    return float(acf[period] - max(neighbours)) if neighbours else float(acf[period])


def _seasonal_profile(values: np.ndarray, period: int) -> np.ndarray:
    """Mean of the series by phase, centred. The component a period explains."""
    phases = np.arange(values.size) % period
    profile = np.zeros(period)
    for phase in range(period):
        selected = values[phases == phase]
        profile[phase] = float(selected.mean()) if selected.size else 0.0
    centred: np.ndarray = profile - profile.mean()
    return centred


def discover(series: Series, *, detrend: bool = True) -> list[PeriodEvidence]:
    """Candidate periods, strongest first, each with its ACF verdict.

    Selection is iterative: the strongest confirmed period is accepted, its seasonal
    component is *removed*, and the remaining candidates are re-tested against what is
    left. Without that step a weekly cycle also confirms at lags 2, 3 and 4 — the ACF
    of a repeating shape is non-zero almost everywhere — and a decomposition against
    all of them splits one seasonal component across four, leaving none of them
    interpretable and a residual with the real signal removed.
    """
    values = series.values.astype(np.float64)
    n = values.size
    if n < 3 * MIN_PERIOD:
        return []
    if detrend:
        values = signal.detrend(values, type="linear")

    max_period = max(MIN_PERIOD, int(n * MAX_PERIOD_FRACTION))
    frequencies, power = signal.periodogram(values, fs=1.0, scaling="spectrum")
    usable = frequencies > 0
    candidate_periods = np.round(1.0 / frequencies[usable]).astype(int)
    candidate_power = power[usable]

    best: dict[int, float] = {}
    for period, strength in zip(candidate_periods, candidate_power, strict=True):
        if MIN_PERIOD <= period <= max_period:
            best[int(period)] = max(best.get(int(period), 0.0), float(strength))
    ranked = dict(sorted(best.items(), key=lambda item: item[1], reverse=True)[:TOP_CANDIDATES])
    if n >= 2 * ANNUAL_PERIOD:
        # The periodogram resolves low frequencies too coarsely to find an annual cycle
        # reliably, so it is offered as a candidate and tested on the same terms.
        ranked.setdefault(ANNUAL_PERIOD, float(best.get(ANNUAL_PERIOD, 0.0)))

    threshold = float(ACF_SIGNIFICANCE_Z / np.sqrt(n))
    max_lag = min(max(ranked) if ranked else MIN_PERIOD, n - 2)
    working = values.copy()
    evidence: list[PeriodEvidence] = []
    remaining = dict(ranked)

    while remaining:
        acf = autocorrelation(working, max_lag=max_lag)
        scored = {
            period: (float(acf[period]) if period < acf.size else 0.0) for period in remaining
        }
        prominence = {period: _prominence(acf, period) for period in remaining}
        winner = max(scored, key=lambda key: prominence[key])
        accepted = scored[winner] > threshold and prominence[winner] > PROMINENCE_MARGIN * threshold
        evidence.append(
            PeriodEvidence(
                period=winner,
                spectral_power=remaining[winner],
                acf=scored[winner],
                acf_threshold=threshold,
                accepted=accepted,
            )
        )
        del remaining[winner]
        if not accepted:
            # Nothing weaker than a rejected candidate can be accepted, so the rest are
            # recorded as rejected at their current ACF and the search stops.
            evidence.extend(
                PeriodEvidence(
                    period=period,
                    spectral_power=strength,
                    acf=scored[period],
                    acf_threshold=threshold,
                    accepted=False,
                )
                for period, strength in remaining.items()
            )
            break
        profile = _seasonal_profile(working, winner)
        working = working - profile[np.arange(working.size) % winner]

    return evidence


def confirmed_periods(series: Series, *, limit: int = 2) -> list[int]:
    """The periods a decomposition should actually use. May legitimately be empty."""
    accepted = [item.period for item in discover(series) if item.accepted]
    return accepted[:limit]
