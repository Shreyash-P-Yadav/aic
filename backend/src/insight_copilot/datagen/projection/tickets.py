"""I5 — support and CRM tickets. Free text, inconsistent tagging, and PII everywhere.

Tickets are the only source that is *both* a table and a corpus: they have structured
fields the DQ layer checks and a body the retrieval layer indexes. That dual nature is
why PII masking has to happen at silver, before indexing, rather than at query time.

Ticket volume responds to the world: an availability incident produces a burst of
"item unavailable" tickets from the affected region. Forty tickets from forty
customers are forty independent signals, which is exactly what noisy-OR corroboration
is designed to count — and why the syndication dedup that collapses one press release
across six outlets must NOT collapse these.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from insight_copilot.datagen.corpus.pii import PersonGenerator
from insight_copilot.datagen.projection.base import ProjectionContext, SourceProjector

BASE_TICKETS_PER_DAY = 34
"""Routine volume across the whole business."""

AVAILABILITY_TICKETS_PER_LOST_UNIT = 0.012
"""How many complaints a lost unit generates. Low, because most customers who cannot
buy simply leave — which is the whole reason a stockout's revenue cost is larger than
its complaint count suggests."""

_CATEGORIES = ("availability", "damage", "delivery", "billing", "product", "other")
_SEVERITIES = ("p1", "p2", "p3", "p4")

_BODIES = {
    "availability": (
        "Tried to order {sku} again this week and it still shows out of stock in {region}. "
        "This is the third time. My number is {phone} if you want to call. - {name}"
    ),
    "damage": (
        "The outer carton of {sku} arrived crushed and one bottle had leaked. Order {order}. "
        "Please advise on replacement. {name} ({email})"
    ),
    "delivery": (
        "Delivery for order {order} was promised on {date} and has not arrived in {region}. "
        "Tracking has not updated for two days. Contact: {phone}"
    ),
    "billing": (
        "I was charged twice for order {order}. Please reverse one of them to the original "
        "card. Registered email is {email}. - {name}"
    ),
    "product": (
        "The new batch of {sku} smells different from the previous one. Not a complaint "
        "exactly, but wanted to flag it. {name}"
    ),
    "other": "Query about order {order} placed from {region}. Please call {phone}. - {name}",
}


class SupportTicketProjector(SourceProjector):
    """Tickets at ticket-id grain, continuous arrival."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        config = context.config
        calendar = context.calendar
        panel = context.panel
        seeds = context.simulator.seeds
        people = PersonGenerator(seeds)
        cells = context.simulator.assortment

        # Lost units per (region, day) drive the availability-complaint burst.
        lost = np.maximum(panel.latent_demand - panel.units, 0.0)
        lost_by_region = np.zeros((len(config.region_ids), calendar.n_days))
        np.add.at(lost_by_region, cells.region_index, lost)

        rows: list[dict[str, object]] = []
        for day in range(calendar.n_days):
            date = calendar.dates[day].date()
            for region_index, region in enumerate(config.region_ids):
                routine = BASE_TICKETS_PER_DAY * config.regions[region_index].population_weight
                burst = lost_by_region[region_index, day] * AVAILABILITY_TICKETS_PER_LOST_UNIT
                rng = seeds("tickets", region, day)
                count = int(rng.poisson(max(routine + burst, 0.0)))
                availability_share = burst / max(routine + burst, 1e-9)

                for index in range(count):
                    rows.append(
                        _ticket(
                            context=context,
                            people=people,
                            region=region,
                            date=date,
                            index=index,
                            availability_share=float(availability_share),
                        )
                    )
        return pd.DataFrame(rows)


def _ticket(
    *,
    context: ProjectionContext,
    people: PersonGenerator,
    region: str,
    date: dt.date,
    index: int,
    availability_share: float,
) -> dict[str, object]:
    """One ticket, fully determined by its content key."""
    seeds = context.simulator.seeds
    key = f"{region}-{date.isoformat()}-{index}"
    rng = seeds("ticket", key)

    category = (
        "availability"
        if rng.random() < availability_share
        else str(rng.choice(_CATEGORIES, p=[0.10, 0.14, 0.28, 0.12, 0.16, 0.20]))
    )
    # Inconsistent tagging is real: a slice of tickets arrive with no category at all.
    tagged = category if rng.random() > 0.11 else "UNKNOWN"
    severity = str(rng.choice(_SEVERITIES, p=[0.03, 0.12, 0.55, 0.30]))

    sku = context.catalog.skus[int(rng.integers(0, len(context.catalog.skus)))]
    warehouse = next(item.id for item in context.config.warehouses if region in item.serves)
    # A real intra-day shape, not a uniform draw. People raise tickets during working
    # hours with a late-morning peak, and a uniform day has no defined "typical hour"
    # at all — which makes a timezone shift undetectable by construction.
    hour = float(np.clip(rng.normal(12.5, 3.4), 0.0, 23.99))
    opened = dt.datetime.combine(date, dt.time(0, 0)) + dt.timedelta(hours=hour)
    resolved = opened + dt.timedelta(hours=float(rng.gamma(2.0, 9.0)))

    body = _BODIES[category].format(
        sku=sku.name,
        region=region,
        order=f"ORD-{date.strftime('%Y%m%d')}-{int(rng.integers(1000, 9999))}",
        date=date.isoformat(),
        name=people.name(key),
        email=people.email(key),
        phone=people.phone(key),
    )
    return {
        "ticket_id": f"TIC-{date.strftime('%Y%m%d')}-{region[:1]}{index:03d}",
        "opened_at_ts": opened,
        "resolved_at_ts": resolved,
        "category": tagged,
        "severity": severity,
        "warehouse": warehouse,
        "product_sku": sku.sku_id,
        "region": region,
        "body_text": body,
        "customer_name": people.name(key),
        "customer_email": people.email(key),
        "customer_phone": people.phone(key),
    }
