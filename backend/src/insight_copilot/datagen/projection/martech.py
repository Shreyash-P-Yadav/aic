"""I3 — the ad-platform aggregator. Weekly, restated, short-memoried, and wrong on purpose.

This feed carries Scenario B, and three of its properties are load-bearing:

* **Attributed revenue is not order-linked revenue.** Platform attribution counts
  view-throughs and cross-device journeys the order book never sees, so it runs 5-15%
  high. That is a *designed disagreement*, inside tolerance, and the engine is meant
  to live with it. Scenario B pushes it to ~18% against a 5% contract tolerance, and
  living with it is then no longer an option.
* **Restatement.** Each drop revises the previous fortnight as attribution settles.
  Prior versions are retained, never overwritten, so the audit trail can show what we
  believed and when.
* **Twelve months of history.** The aggregator's retention window caps it, so any
  model using marketing spend has a shorter usable window than one that does not —
  and the confidence engine has to know that.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.projection.base import ProjectionContext, SourceProjector

CAMPAIGNS_PER_CHANNEL = 7
"""~40 concurrent campaigns across six channels."""

CAMPAIGN_ID_REUSE_YEARS = 2
"""Campaign ids are recycled every two years — a real planning-tool habit, and a
planted trap for anyone joining on campaign_id without a year."""

SCENARIO_B_GAP = 0.18
"""The attribution gap during Scenario B, against a 5% contract tolerance."""


class MarTechProjector(SourceProjector):
    """Spend and attributed revenue at ISO week x campaign x channel."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        config = context.config
        panel = context.panel
        calendar = context.calendar
        seeds = context.simulator.seeds

        weeks = pd.Index(dict.fromkeys(calendar.iso_week))
        media_names = [channel.id for channel in config.media.channels]

        # Weekly spend by (region, media channel), from the simulated media plan.
        spend = pd.DataFrame(panel.media_spend.sum(axis=0).T, columns=media_names)
        spend["iso_week"] = calendar.iso_week
        weekly_spend = spend.groupby("iso_week", sort=False).sum(numeric_only=True)

        # Order-linked revenue by week: what the order book can actually see.
        revenue = pd.Series((panel.units * panel.unit_price_net).sum(axis=0))
        revenue.index = pd.Index(calendar.iso_week)
        weekly_revenue = revenue.groupby(level=0, sort=False).sum()

        inflation_low, inflation_high = config.media.attributed_revenue_inflation
        breach_weeks = _scenario_b_weeks(context, calendar)

        rows: list[dict[str, object]] = []
        for week in weeks:
            week_spend = weekly_spend.loc[week]
            total_spend = float(week_spend.sum())
            if total_spend <= 0:
                continue
            order_linked = float(weekly_revenue.get(week, 0.0))

            for channel_id in media_names:
                channel_spend = float(week_spend[channel_id])
                if channel_spend <= 0:
                    continue
                share = channel_spend / total_spend
                # ONE Dirichlet per (week, channel), indexed by campaign. Drawing a
                # separate Dirichlet per campaign and taking one component gives
                # weights that do not sum to 1, so the channel's weekly spend would
                # not survive the split into campaigns — and every downstream
                # correlation would be attenuated by an artefact of the projection.
                split = seeds("martech_split", week, channel_id).dirichlet(
                    np.full(CAMPAIGNS_PER_CHANNEL, 2.0)
                )
                for campaign in range(CAMPAIGNS_PER_CHANNEL):
                    rng = seeds("martech_campaign", week, channel_id, campaign)
                    weight = float(split[campaign])
                    campaign_spend = channel_spend * weight
                    if campaign_spend < 1.0:
                        continue

                    inflation = (
                        1.0 + SCENARIO_B_GAP
                        if week in breach_weeks
                        else float(rng.uniform(inflation_low, inflation_high))
                    )
                    # Attributed revenue is the platform's claim on the slice of
                    # order-linked revenue this campaign's spend share implies,
                    # inflated by the attribution window.
                    attributed = order_linked * share * weight * inflation
                    cpm = next(c.cpm_inr for c in config.media.channels if c.id == channel_id)
                    impressions_count = campaign_spend / cpm * 1000.0
                    click_rate = float(rng.uniform(0.006, 0.031))
                    rows.append(
                        {
                            "iso_week": week,
                            "campaign_id": _campaign_id(week, channel_id, campaign),
                            "channel": channel_id,
                            "region": "ALL",
                            "spend_inr": round(campaign_spend, 2),
                            "impressions": int(impressions_count),
                            "clicks": int(impressions_count * click_rate),
                            "attributed_revenue_inr": round(attributed, 2),
                        }
                    )
        return pd.DataFrame(rows)


def _campaign_id(week: str, channel: str, index: int) -> str:
    """Campaign ids recycle every two years.

    Deliberate: a join on campaign_id alone silently merges a 2024 campaign with a
    2026 one, which is exactly the kind of defect a semantic layer is supposed to make
    impossible to hit by accident.
    """
    year = int(week[:4])
    cycle = year % CAMPAIGN_ID_REUSE_YEARS
    return f"CMP-{channel[:3].upper()}-{cycle}{index:02d}"


def _scenario_b_weeks(context: ProjectionContext, calendar: object) -> set[str]:
    """ISO weeks in which the attribution reconciliation is out of tolerance."""
    breaches: set[str] = set()
    for event in context.ledger:
        if event.demo_role != "scenario_B_reconciliation":
            continue
        breaches |= _weeks_between(event, calendar)
    return breaches


def _weeks_between(event: Event, calendar: object) -> set[str]:
    """ISO week labels covered by an event's window."""
    dates = calendar.dates  # type: ignore[attr-defined]
    labels = calendar.iso_week  # type: ignore[attr-defined]
    inside = (dates.date >= event.window.start) & (dates.date <= event.window.end)
    return set(labels[inside])


def martech_history_cutoff(today: dt.date, months: int) -> dt.date:
    """Earliest date the aggregator still holds, given its retention window."""
    return today - dt.timedelta(days=int(months * 30.44))
