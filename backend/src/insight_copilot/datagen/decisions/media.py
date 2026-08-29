"""Media budget allocation — the deliberately endogenous decision.

If marketing spend were exogenous random noise, a regression would recover its
elasticity trivially and the econometrics in the architecture would be theatre. Real
budgets respond to performance, which creates simultaneity and biases naive
estimates upward. So::

    spend[c, w] = planned_budget[c, quarter(w)]                  # set quarterly, EXOGENOUS
                * (1 + kappa * (revenue[w-1] / target[w-1] - 1)) # tactical, ENDOGENOUS
                * seasonal_media_multiplier[w]
                * exp(noise)

Three payoffs from this one choice:

1. The problem becomes real. Naive OLS recovers an inflated marketing elasticity;
   the DAG-specified estimate does not. Because the true value is known, both numbers
   can be shown side by side — the P6 endogeneity demonstration.
2. It supplies an identification strategy. The quarterly plan is set months ahead for
   reasons unrelated to this week's demand: quasi-exogenous variation to lean on, and
   a real answer to "how do you know that is causal and not just correlated?"
3. ``kappa`` is capped at 0.3 on purpose. Stronger and the parameter stops being
   identifiable at all, which is a different and much less useful demonstration.

The second planted pathology here is **collinearity**: paid social and display are
run by one agency team and their budgets move together (rho ~ 0.8) for two quarters.
The VIF gate must attribute them as a group rather than inventing false precision.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.world.calendar import Calendar
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

SPEND_NOISE_SIGMA = 0.09
"""Execution noise on the weekly plan: creative delays, platform pacing, invoice timing."""

SEASONAL_MEDIA_AMPLITUDE = 0.12
"""Media leans into the festive quarter harder than demand does, which is why spend
and demand seasonality are correlated but not identical — a second thing the design
matrix has to separate. Kept modest because it is a *shared* component: a large one
would correlate all six channels with each other and leave no coefficient separately
identifiable anywhere, which is neither realistic nor a useful test."""

COLLINEAR_SHOCK_SIGMA = 0.30
"""Log-scale amplitude of the shared shock inside the collinear window. It replaces
the pair's independent wobble rather than adding to it, so this is their whole
week-to-week movement for those two quarters."""

CHANNEL_WOBBLE_PHI = 0.62
CHANNEL_WOBBLE_SIGMA = 0.22
"""Each channel carries its own persistent budget wobble — an agency reallocating,
a creative flight ending, a platform's auction dynamics. This independent variation
is what keeps baseline cross-channel correlation moderate, so the ONE deliberately
collinear pair actually stands out to the VIF gate instead of being lost among six
channels that all move together."""


class MediaPlan:
    """The quarterly plan and the machinery to realise it week by week.

    Stateful by design: weekly spend depends on the *previous* week's realised
    revenue, so it cannot be precomputed. The simulator calls
    :meth:`spend_for_week` once per ISO week inside the main day loop.
    """

    def __init__(self, config: WorldConfig, calendar: Calendar, seeds: SeedBook) -> None:
        self._config = config
        self._calendar = calendar
        self._seeds = seeds
        self._weeks = list(dict.fromkeys(calendar.iso_week))
        self._week_position = {week: index for index, week in enumerate(self._weeks)}
        self._channel_ids = [channel.id for channel in config.media.channels]

    @property
    def weeks(self) -> list[str]:
        """ISO week labels in order."""
        return list(self._weeks)

    @property
    def channel_ids(self) -> list[str]:
        """Media channel ids in configuration order."""
        return list(self._channel_ids)

    @property
    def weekly_target_revenue(self) -> float:
        """The revenue target the tactical overlay is measured against."""
        return self._config.company.target_annual_net_revenue_inr / 52.0

    def planned_weekly_budget(self, week: str) -> np.ndarray:
        """``(n_media_channels,)`` the exogenous quarterly plan, pro-rated to a week.

        Set once a quarter, months ahead, for reasons unrelated to this week's
        demand. This is the quasi-exogenous variation the identification leans on.
        """
        config = self._config
        position = self._week_position[week]
        annual = config.company.target_annual_net_revenue_inr * (
            config.media.annual_spend_share_of_revenue
        )
        weekly = annual / 52.0
        shares = np.array([channel.budget_share for channel in config.media.channels])

        quarter = f"{week[:4]}Q{position // 13 + 1}"
        # Quarterly revision and seasonal phase are drawn PER CHANNEL. One shared draw
        # would move all six channels in lockstep, so every pair would be collinear,
        # no media coefficient would be separately identifiable anywhere in the
        # history, and the ONE pair we deliberately made collinear would not stand
        # out. Channel budgets are also revised by different people at different
        # times, so independent drift is the more realistic model as well.
        plan_keys = [self._plan_key(channel.id, week) for channel in config.media.channels]
        drift = np.array(
            [
                max(float(self._seeds("media_quarter_plan", quarter, key).normal(1.0, 0.13)), 0.5)
                for key in plan_keys
            ]
        )
        phase = np.array(
            [
                float(self._seeds("media_seasonal_phase", key).uniform(-10.0, 10.0))
                for key in plan_keys
            ]
        )
        seasonal = 1.0 + SEASONAL_MEDIA_AMPLITUDE * np.cos(
            2.0 * np.pi * (position - 8.0 + phase) / 52.0
        )
        budget: np.ndarray = weekly * shares * drift * seasonal
        return budget

    def collinearity_shock(self, week: str) -> np.ndarray:
        """``(n_media_channels,)`` shared shock that ties two channels together.

        For the configured window, paid social and display receive a *common* draw
        plus a small independent component, giving a correlation near the configured
        rho. Outside the window their shocks are independent.
        """
        config = self._config
        multipliers = np.ones(len(self._channel_ids), dtype=np.float64)
        if not self._in_collinear_window(week):
            return multipliers

        rho = config.media.collinear_rho
        shared = float(self._seeds("media_collinear_shared", week).normal(0.0, 1.0))
        for channel_id in config.media.collinear_pair:
            index = self._channel_ids.index(channel_id)
            independent = float(
                self._seeds("media_collinear_own", week, channel_id).normal(0.0, 1.0)
            )
            combined = np.sqrt(rho) * shared + np.sqrt(1.0 - rho) * independent
            multipliers[index] = float(np.exp(COLLINEAR_SHOCK_SIGMA * combined))
        return multipliers

    def channel_wobble(self, week: str) -> np.ndarray:
        """``(n_media_channels,)`` persistent, independent per-channel budget wobble.

        An AR(1) in log space, recomputed from the week index rather than carried as
        state, so it stays a pure function of the content key and a windowed re-run
        sees the same path.

        Inside the collinear window the pair's independent wobble is SUPPRESSED
        rather than added to: the point of that window is that one agency team ran
        both budgets off a single plan, so their independent variation stops existing
        for those two quarters. Adding a shared shock on top of undiminished
        independent variation would raise their covariance without raising their
        correlation, which is not the pathology the VIF gate is meant to catch.
        """
        position = self._week_position[week]
        wobble = np.empty(len(self._channel_ids), dtype=np.float64)
        for index, channel_id in enumerate(self._channel_ids):
            innovations = CHANNEL_WOBBLE_SIGMA * self._seeds(
                "media_channel_wobble", channel_id
            ).standard_normal(len(self._weeks))
            level = 0.0
            for step in range(position + 1):
                level = CHANNEL_WOBBLE_PHI * level + innovations[step]
            wobble[index] = np.exp(level - 0.5 * CHANNEL_WOBBLE_SIGMA**2)
        if self._in_collinear_window(week):
            joint = float(
                np.exp(
                    CHANNEL_WOBBLE_SIGMA
                    * self._seeds("media_channel_wobble", "agency_joint_plan", week).normal()
                    - 0.5 * CHANNEL_WOBBLE_SIGMA**2
                )
            )
            for channel_id in self._config.media.collinear_pair:
                wobble[self._channel_ids.index(channel_id)] = joint
        return wobble

    def _plan_key(self, channel_id: str, week: str) -> str:
        """Which plan a channel's budget is drawn from in a given week.

        Inside the collinear window the two named channels are planned by ONE agency
        team off ONE plan, so they share a key and therefore share their quarterly
        revision and their seasonal phase. That — not merely a correlated shock on
        top of independent plans — is what makes them genuinely collinear, and it is
        the realistic mechanism: the correlation exists because the decision was
        joint, not because two independent decisions happened to agree.
        """
        if channel_id in self._config.media.collinear_pair and self._in_collinear_window(week):
            return "agency_joint_plan"
        return channel_id

    def _in_collinear_window(self, week: str) -> bool:
        """Is this ISO week inside the configured collinear window?"""
        position = self._week_position[week]
        day = self._calendar.dates[min(position * 7, self._calendar.n_days - 1)].date()
        start, end = self._config.media.collinear_window
        return bool(start <= day <= end)

    def spend_for_week(self, week: str, previous_week_revenue: float | None) -> np.ndarray:
        """``(n_media_channels,)`` realised spend for one ISO week.

        ``previous_week_revenue`` of ``None`` (the first week) means no tactical
        response: there is nothing yet to respond to.
        """
        planned = self.planned_weekly_budget(week)
        if previous_week_revenue is None:
            tactical = 1.0
        else:
            gap = previous_week_revenue / self.weekly_target_revenue - 1.0
            # Cap the response so one extreme week cannot drive spend negative or
            # to an implausible multiple; a real budget has guardrails too.
            tactical = float(np.clip(1.0 + self._config.media.endogeneity_kappa * gap, 0.55, 1.65))
        noise = np.exp(
            SPEND_NOISE_SIGMA
            * self._seeds("media_exec_noise", week).standard_normal(len(self._channel_ids))
            - 0.5 * SPEND_NOISE_SIGMA**2
        )
        spend: np.ndarray = (
            planned * tactical * self.collinearity_shock(week) * self.channel_wobble(week) * noise
        )
        return spend

    def daily_share(self, week: str) -> np.ndarray:
        """``(n_media_channels, 7)`` how each channel paces its week across days.

        Pacing is not flat and it is not shared: platforms front-load differently,
        search follows query volume, CTV buys inventory in blocks. Drawing one shared
        pacing vector would impose an identical daily shape on every channel and make
        all six perfectly collinear at daily grain — which would destroy the driver
        regression's ability to separate any of them, and would swamp the ONE pair we
        deliberately made collinear.
        """
        rows = []
        for channel in self._config.media.channels:
            raw = 1.0 + 0.16 * self._seeds("media_pacing", week, channel.id).standard_normal(7)
            raw = np.clip(raw, 0.5, 1.6)
            rows.append(raw / raw.sum())
        return np.array(rows)
