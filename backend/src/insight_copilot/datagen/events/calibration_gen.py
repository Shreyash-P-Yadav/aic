"""The calibration corpus: several hundred labelled events for the confidence backtest.

The isotonic map that turns a raw confidence score into a probability needs a few
hundred cases spanning the *whole* score range. The four demo scenarios cannot supply
that, and fitting on them would score the demo cases with a map trained on themselves.

Events are generated with controlled variation along the four axes that actually move
the confidence score (DataLayer §9.3):

| Axis | Sampled over | Spreads |
|---|---|---|
| Magnitude | just below materiality → very large | `c1` detection strength |
| Segment concentration | one SKU → diffuse across a whole category | `c2` attribution stability |
| Evidence availability | 0 documents → 5 corroborating | `c5` evidence support |
| Data condition | clean → stale feed / reconciliation breach | `c4` data trust |

**Lanes.** Events are laid out in `(region, category)` lanes with a minimum gap
inside each lane. Two events in different lanes cannot touch the same rows, so they
can share one counterfactual run — which is what turns ~450 counterfactuals into a
few dozen. Without lanes, several hundred events over 36 months would chain into a
single interaction group and the ground truth would be unaffordable.
"""

from __future__ import annotations

import datetime as dt

from insight_copilot.datagen.events.models import (
    DemandShockMagnitude,
    Event,
    EventScope,
    EventWindow,
    EvidenceSpec,
    GroundTruthSpec,
    OutageMagnitude,
    PriceChangeMagnitude,
)
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

TARGET_COUNT = 440
"""At least 400, per the design. Below ~250 the per-tier table gets thin; above ~600
the ground-truth job stops being a one-off."""

MAX_DURATION_DAYS = 12
"""Longest calibration event. Bounded so the lane spacing below can clear it."""

LANE_MIN_GAP_DAYS = 64
"""Start-to-start spacing inside one lane.

It must exceed ``MAX_DURATION_DAYS + SEPARATION_DAYS`` (12 + 50 = 62), because
interaction is measured from one event's END to the next one's START. Setting it
below that threshold chains every event in a lane into a single interaction group and
makes the ground truth unaffordable — the failure mode this constant exists to
prevent."""

_LEAD_IN_DAYS = 35
"""No calibration events in the first weeks: the inventory system is still settling
from its opening position and a movement there is a warm-up artefact, not a signal."""

_SCENARIO_BLACKOUT = (dt.date(2026, 2, 1), dt.date(2026, 4, 30))
"""No calibration events inside the demo scenarios' window.

The scenarios are excluded from the calibration *fit*, but a calibration event
landing on top of Scenario A would also corrupt Scenario A's own ground truth by
interacting with it. Keeping the window clear costs a few slots and removes the
whole class of problem.
"""

_DATA_CONDITIONS: list[str] = [
    "clean",
    "clean",
    "clean",
    "stale_feed",
    "reconciliation_breach",
    "restatement_open",
]
"""Half the corpus is clean. Weighting towards clean matters: if most cases were
degraded, the calibration curve would describe a broken pipeline rather than a
working one."""


def generate_calibration(
    config: WorldConfig, catalog: ProductCatalog, seeds: SeedBook
) -> list[Event]:
    """Build the calibration event set, laid out in non-interacting lanes."""
    lanes = [(region, category) for region in config.region_ids for category in config.category_ids]
    horizon = config.horizon
    usable_days = horizon.n_days - _LEAD_IN_DAYS - 28
    per_lane = max(1, usable_days // LANE_MIN_GAP_DAYS)

    skus_by_category: dict[str, list[str]] = {}
    for sku in catalog.skus:
        skus_by_category.setdefault(sku.category, []).append(sku.sku_id)

    events: list[Event] = []
    for lane_index, (region, category) in enumerate(lanes):
        for slot in range(per_lane):
            if len(events) >= TARGET_COUNT:
                break
            event = _build_event(
                config=config,
                seeds=seeds,
                skus=skus_by_category.get(category, []),
                region=region,
                category=category,
                lane_index=lane_index,
                slot=slot,
                index=len(events),
            )
            if event is not None:
                events.append(event)
    return events


def _build_event(
    *,
    config: WorldConfig,
    seeds: SeedBook,
    skus: list[str],
    region: str,
    category: str,
    lane_index: int,
    slot: int,
    index: int,
) -> Event | None:
    """One calibration event, or ``None`` when its slot falls in a blackout window."""
    rng = seeds("calibration_event", region, category, slot)
    horizon = config.horizon

    # Jitter inside the slot so events are not on a visible grid, which would be a
    # pattern the detector could learn instead of the signal.
    base = _LEAD_IN_DAYS + slot * LANE_MIN_GAP_DAYS
    offset = base + int(rng.integers(0, 14)) + (lane_index % 7)
    start = horizon.start + dt.timedelta(days=offset)
    duration = int(rng.integers(3, MAX_DURATION_DAYS + 1))
    end = start + dt.timedelta(days=duration)
    if _SCENARIO_BLACKOUT[0] <= start <= _SCENARIO_BLACKOUT[1]:
        return None
    if end > horizon.end - dt.timedelta(days=25):
        return None

    # --- axis 1: magnitude, from just below materiality to very large -----------
    severity = float(rng.uniform(0.0, 1.0))
    effect = 0.02 + 0.42 * severity**1.6  # 2% .. 44% within the affected scope
    direction = -1.0 if rng.random() < 0.72 else 1.0

    # --- axis 2: segment concentration ------------------------------------------
    concentration = float(rng.random())
    if concentration < 0.35 and skus:
        # Concentrated: a handful of SKUs. Hard to find, easy to be sure about.
        # The category is recorded too, even though the SKUs already imply it, so
        # the interaction test can tell two SKU-scoped events in different
        # categories apart instead of treating "no category named" as "all".
        chosen = [str(value) for value in rng.choice(skus, size=min(3, len(skus)), replace=False)]
        scope = EventScope(regions=[region], categories=[category], skus=chosen)
    elif concentration < 0.75:
        scope = EventScope(regions=[region], categories=[category])
    else:
        # Diffuse: one category across several regions. Easy to see, hard to
        # localise, which is what drives bootstrap stability and therefore c2 down.
        # Two or three regions rather than all five: a truly national event would
        # couple every lane of its category and make the ground truth unaffordable
        # for no extra spread on the axis this is here to vary.
        extra = [r for r in config.region_ids if r != region]
        picked = [str(v) for v in rng.choice(extra, size=int(rng.integers(1, 3)), replace=False)]
        scope = EventScope(regions=[region, *picked], categories=[category])

    # The event TYPE is the business label ("a competitor did something"); the
    # magnitude KIND is the mechanism ("demand moved"). They are not the same
    # vocabulary and conflating them is what the discriminated union prevents.
    mechanism = str(rng.choice(["demand_shock", "price_change", "outage"], p=[0.5, 0.32, 0.18]))
    kind: str = {
        "demand_shock": "competitor_action",
        "price_change": "price_change",
        "outage": "supplier_delay",
    }[mechanism]
    magnitude: DemandShockMagnitude | PriceChangeMagnitude | OutageMagnitude
    if mechanism == "outage":
        # The DC and the regions it serves are both recorded. Naming only the
        # warehouse would leave the region list empty, which reads as "every region"
        # to the interaction test and chains this event to every demand event in the
        # world.
        warehouse = next(
            item
            for item in config.warehouses
            if item.home_region == region or region in item.serves
        )
        scope = EventScope(
            warehouses=[warehouse.id],
            regions=[region],
            categories=scope.categories or [category],
            skus=scope.skus,
        )
        magnitude = OutageMagnitude(pick_capacity=max(0.05, 1.0 - effect * 1.6))
    elif mechanism == "price_change":
        category_config = config.category(category)
        # Convert a target demand effect into the price move that produces it, so the
        # magnitude axis means the same thing whatever the mechanism.
        multiplier = float(
            (1.0 + direction * effect) ** (1.0 / category_config.own_price_elasticity)
        )
        magnitude = PriceChangeMagnitude(price_multiplier=min(max(multiplier, 0.55), 1.8))
    else:
        magnitude = DemandShockMagnitude(demand_multiplier=max(0.05, 1.0 + direction * effect))

    # --- axis 3: evidence availability -------------------------------------------
    evidence_draw = float(rng.random())
    documents = 0 if evidence_draw < 0.15 else int(rng.integers(1, 6))
    evidence = EvidenceSpec(
        documents=documents,
        contradiction=documents > 1 and rng.random() < 0.10,
        syndication=int(rng.integers(1, 7)) if documents else 1,
        post_dated_decoy=rng.random() < 0.08,
        effective_date_offset_days=int(rng.integers(5, 45)) if rng.random() < 0.20 else 0,
    )

    # --- axis 4: data condition ---------------------------------------------------
    condition = _DATA_CONDITIONS[int(rng.integers(0, len(_DATA_CONDITIONS)))]

    return Event(
        event_id=f"CAL-{index:04d}",
        type=kind,  # type: ignore[arg-type]  # drawn from the EventType literals
        event_set="calibration",
        scope=scope,
        window=EventWindow(start=start, end=end),
        magnitude=magnitude,
        detectability="high" if severity > 0.6 else "medium" if severity > 0.25 else "low",
        evidence=evidence,
        ground_truth=GroundTruthSpec(compute=True, method="counterfactual"),
        data_condition=condition,  # type: ignore[arg-type]  # from the literal list
        description=(
            f"Calibration {kind.replace('_', ' ')} in {category}"
            f"{'' if scope.is_national else f', {region}'}; "
            f"target effect {direction * effect:+.1%}, data {condition}."
        ),
    )
