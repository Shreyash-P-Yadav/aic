"""Routine background events — the world being lived in rather than staged.

These exist so the detector has realistic *non*-events to ignore. A world in which
the only things that ever happen are the four demo scenarios makes a detector look
infallible for the wrong reason: it has nothing to be wrong about. Ambient events are
deliberately small — mostly below the contracts' business materiality floors — so
correctly *not* firing on them is a measurable property (specificity), not an
assumption.

Every draw is addressed by content key on the event's index, so adding an ambient
event never re-rolls another one.
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
    MediaShiftMagnitude,
    OutageMagnitude,
    PriceChangeMagnitude,
)
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

AMBIENT_COUNT = 90
"""Enough to make the world feel busy without swamping the calibration corpus."""

_MIN_GAP_DAYS = 5
"""Ambient events are small and mostly disjoint in scope, so they may sit close
together — but not on top of each other, which would just be one bigger event."""


def generate_ambient(config: WorldConfig, seeds: SeedBook) -> list[Event]:
    """Build the ambient event set.

    Magnitudes are drawn small on purpose: a 1-4% move inside one region-category is
    below every contract's business floor, so the materiality gate should reject them.
    A handful sit just above the floor, which is what makes the gate a decision rather
    than a formality.
    """
    horizon = config.horizon
    span = horizon.n_days - 30
    events: list[Event] = []

    for index in range(AMBIENT_COUNT):
        rng = seeds("ambient_event", index)
        offset = int(rng.integers(14, max(15, span)))
        start = horizon.start + dt.timedelta(days=offset)
        duration = int(rng.integers(2, 15))
        region = str(rng.choice(config.region_ids))
        category = str(rng.choice(config.category_ids))
        kind = str(
            rng.choice(
                ["promo", "media_shift", "supplier_delay", "competitor_action"],
                p=[0.40, 0.22, 0.20, 0.18],
            )
        )

        scope = EventScope(regions=[region], categories=[category])
        magnitude: (
            PriceChangeMagnitude | MediaShiftMagnitude | OutageMagnitude | DemandShockMagnitude
        )
        if kind == "promo":
            magnitude = PriceChangeMagnitude(price_multiplier=float(rng.uniform(0.88, 0.97)))
        elif kind == "media_shift":
            scope = EventScope(
                regions=[region],
                media_channels=[str(rng.choice([c.id for c in config.media.channels]))],
            )
            magnitude = MediaShiftMagnitude(spend_multiplier=float(rng.uniform(0.72, 1.30)))
        elif kind == "supplier_delay":
            scope = EventScope(
                warehouses=[str(rng.choice(config.warehouse_ids))], categories=[category]
            )
            magnitude = OutageMagnitude(pick_capacity=float(rng.uniform(0.80, 0.96)))
        else:
            magnitude = DemandShockMagnitude(demand_multiplier=float(rng.uniform(0.94, 1.07)))

        events.append(
            Event(
                event_id=f"AMB-{index:04d}",
                type=kind,  # type: ignore[arg-type]  # drawn from the EventType literals
                event_set="ambient",
                scope=scope,
                window=EventWindow(start=start, end=start + dt.timedelta(days=duration)),
                magnitude=magnitude,
                detectability="low",
                evidence=EvidenceSpec(documents=int(rng.integers(0, 3))),
                # Ambient events are background, not evidence for the calibration
                # curve, so their true contribution is not computed: several hundred
                # extra counterfactual runs for numbers nothing consumes.
                ground_truth=GroundTruthSpec(compute=False),
                description=f"Routine {kind.replace('_', ' ')} in {category}, {region}.",
            )
        )
    return _drop_collisions(events)


def _drop_collisions(events: list[Event]) -> list[Event]:
    """Remove ambient events that land on top of an identically-scoped sibling.

    Two overlapping events with the same scope are indistinguishable from one bigger
    event, which would quietly break the one-event-one-contribution assumption the
    ledger rests on.
    """
    kept: list[Event] = []
    for event in sorted(events, key=lambda item: item.window.start):
        clash = any(
            other.scope == event.scope
            and event.window.start <= other.window.end + dt.timedelta(days=_MIN_GAP_DAYS)
            and other.window.start <= event.window.end + dt.timedelta(days=_MIN_GAP_DAYS)
            for other in kept
        )
        if not clash:
            kept.append(event)
    return kept
