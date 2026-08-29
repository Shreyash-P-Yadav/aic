"""E1 — the competitor price panel. Partial, fuzzy, and short of history.

Three limitations are modelled because each one propagates into the evidence layer:

* **~60% SKU coverage.** We only see the competitors' listings a vendor happens to
  track. Coverage becomes a confidence input, not a footnote.
* **Fuzzy matching at ~85%.** "Botanical Hair Oil 200 ml" matching one of our SKUs is
  a probabilistic join with a score, not a key. That score is the `EntityLinkConf`
  term in evidence confidence.
* **Fourteen months of history.** You only have data from when you started paying for
  it, so any model using competitor prices has a shorter usable window than one that
  does not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from insight_copilot.datagen.projection.base import ProjectionContext, SourceProjector

COMPETITORS = ("Rivera Naturals", "Kesh & Co", "Blue Lotus Home", "Prakriti Labs")
"""Fictional competitors."""

SCRAPE_LAG_DAYS = 3
"""The panel reports last week's shelf, seen three days ago."""

DELISTING_RATE = 0.04
"""Weekly chance a matched listing silently disappears. Silent is the point: the row
is simply absent, with no marker, so a naive join quietly loses a competitor."""


class CompetitorPriceProjector(SourceProjector):
    """Competitor prices at ISO week x competitor x matched SKU."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        config = context.config
        calendar = context.calendar
        catalog = context.catalog
        seeds = context.simulator.seeds

        # Fourteen months of history: you only have data from when you started
        # paying for it, which is a real analytical constraint rather than a defect.
        history_start = pd.Timestamp(config.horizon.end) - pd.Timedelta(
            days=int(self.contract.history_available_months * 30.44)
        )
        weeks = list(dict.fromkeys(calendar.iso_week))
        week_first_day: dict[str, pd.Timestamp] = {}
        for index, week in enumerate(calendar.iso_week):
            week_first_day.setdefault(week, calendar.dates[index])

        # Coverage is a property of the SKU, not of the week: a listing the vendor
        # tracks is tracked every week until it is delisted.
        covered = [
            sku
            for sku in catalog.skus
            if float(seeds("competitor_coverage", sku.sku_id).random())
            < config.competitor.sku_coverage
        ]

        rows: list[dict[str, object]] = []
        for week in weeks:
            first_day = week_first_day[week]
            if first_day < history_start:
                continue
            for sku in covered:
                for competitor in COMPETITORS:
                    rng = seeds("competitor_row", week, sku.sku_id, competitor)
                    if rng.random() < DELISTING_RATE:
                        continue
                    confidence = float(
                        np.clip(
                            rng.normal(
                                config.competitor.match_confidence.mean,
                                config.competitor.match_confidence.sd,
                            ),
                            0.35,
                            1.0,
                        )
                    )
                    region = str(rng.choice(config.region_ids))
                    region_index = config.region_ids.index(region)
                    day_index = calendar.index_of(first_day.date())
                    index_value = float(
                        context.simulator.price_plan.competitor_index[
                            catalog.sku_ids.index(sku.sku_id), region_index, day_index
                        ]
                    )
                    # Their shelf price, not ours: our reference times their index
                    # times a per-competitor positioning offset.
                    offset = float(rng.uniform(0.88, 1.14))
                    rows.append(
                        {
                            "iso_week": week,
                            "competitor": competitor,
                            "matched_sku": sku.sku_id,
                            "competitor_product_title": _title(sku.name, competitor, rng),
                            "match_confidence": round(confidence, 3),
                            "observed_price_inr": round(
                                sku.ref_price_inr * index_value * offset, 2
                            ),
                            "region": region,
                            "scraped_at_ts": first_day + pd.Timedelta(days=SCRAPE_LAG_DAYS),
                        }
                    )
        return pd.DataFrame(rows)


def _title(our_name: str, competitor: str, rng: np.random.Generator) -> str:
    """Their listing title, which is why the match is fuzzy rather than a key."""
    form = our_name.split(" ", 1)[-1]
    qualifier = str(rng.choice(["", " Advanced", " Naturals", " Pro", " Everyday"]))
    size = str(rng.choice(["100 ml", "200 ml", "250 ml", "400 ml"]))
    return f"{competitor.split()[0]}{qualifier} {form} {size}"
