"""Counterfactual re-simulation, and the batching that makes it affordable.

**Full re-runs, not warm-started windows.** The design proposes re-simulating only
`[event_start - 60d, event_end + 60d]`, warm-started from the factual state, because
a full re-run was assumed to be expensive. In this build a full 36-month run takes
about 2.6 seconds, so a full re-run is both cheaper to reason about and strictly more
correct — there is no warm-start approximation to defend, and the common-random-number
property guarantees the two worlds differ only by the event.

**Batching is where the windowing idea survives, and it is the important half.**
Two events separated by more than the process's memory horizon cannot influence each
other, so both can be removed in a *single* counterfactual run and each measured in
its own window. With ~400 calibration events over 36 months this turns ~400 runs into
a few dozen. That is the same insight as windowing, applied to the run count rather
than to the day count.

**Interacting events get Shapley, not one-at-a-time deltas** — see `shapley.py`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from insight_copilot.datagen.events.effects import LedgerOverlay
from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SEPARATION_DAYS = 50
"""Gap, measured from the END of one event to the START of the next, beyond which
two events cannot interact.

The process has bounded memory and the binding constraint is inventory: a
replenishment cycle plus its lead time is about six weeks, adstock decays over about
three, and the AR(1) company shock over about two. Fifty days clears all three.

Note this is measured end-to-start, not start-to-start. The calibration generator's
lane spacing has to exceed `max_duration + SEPARATION_DAYS`, or consecutive events in
the same lane chain into one group — which is exactly the arithmetic slip that turned
420 independent events into a single 418-event group on the first attempt.
"""

INTERACTION_REACH_DAYS = 90
"""How far past its start an event can still interact with a *new* event.

A permanent change — a list-price revision that never ends — would otherwise chain
every subsequent event into one enormous group, because its window runs to the end of
the horizon. Its ongoing presence is a LEVEL, not an interaction: it shifts the
baseline every later event is measured against, which the counterfactual already
handles by keeping it in every coalition. Bounding the reach separates "these two
events happened close enough together to interfere" from "this one is still in
force", which are different questions.
"""


def _interaction_reach(event: Event, separation_days: int) -> dt.date:
    """The last date on which a new event could still interact with this one."""
    effective_end = min(
        event.window.end, event.window.start + dt.timedelta(days=INTERACTION_REACH_DAYS)
    )
    return effective_end + dt.timedelta(days=separation_days)


@dataclass(frozen=True)
class InteractionGroup:
    """Events close enough in time that their effects can interact.

    A group of one needs a single counterfactual. A group of several needs Shapley
    over its subsets, because one-at-a-time deltas do not sum to the total when the
    events interact — and in Scenario A they do interact, since a stockout suppresses
    the volume that marketing would otherwise have driven.
    """

    events: tuple[Event, ...]

    @property
    def event_ids(self) -> tuple[str, ...]:
        """Ids in ledger order."""
        return tuple(event.event_id for event in self.events)

    @property
    def start(self) -> dt.date:
        """Earliest start in the group."""
        return min(event.window.start for event in self.events)

    @property
    def end(self) -> dt.date:
        """Latest end in the group."""
        return max(event.window.end for event in self.events)

    @property
    def needs_shapley(self) -> bool:
        """True when the group has more than one event."""
        return len(self.events) > 1


def group_interacting_events(
    events: list[Event], *, separation_days: int = SEPARATION_DAYS
) -> list[InteractionGroup]:
    """Cluster events whose influence windows overlap.

    Two events are in the same group when they are close in time AND their scopes
    can touch the same rows. Both conditions are needed: several hundred calibration
    events over 36 months are unavoidably close in time, but an event confined to
    Skincare in the South cannot interact with one confined to Haircare in the North,
    so they can share a single counterfactual run.

    Single-linkage is the conservative choice: it errs towards putting events in the
    same group, which costs run time but never mis-attributes an interaction away.
    """
    if not events:
        return []
    ordered = sorted(events, key=lambda event: (event.window.start, event.event_id))
    groups: list[list[Event]] = []
    reaches: list[dt.date] = []

    for event in ordered:
        for position, group in enumerate(groups):
            if event.window.start > reaches[position]:
                continue
            if any(event.scope.may_interact_with(member.scope) for member in group):
                group.append(event)
                reaches[position] = max(
                    reaches[position], _interaction_reach(event, separation_days)
                )
                break
        else:
            groups.append([event])
            reaches.append(_interaction_reach(event, separation_days))
    return [InteractionGroup(tuple(group)) for group in groups]


def plan_batches(
    groups: list[InteractionGroup], *, separation_days: int = SEPARATION_DAYS
) -> list[list[InteractionGroup]]:
    """Pack groups into batches that can share one counterfactual run.

    Groups in a batch cannot influence each other — they are either separated by more
    than the memory horizon or confined to disjoint slices of the business — so
    removing all of them at once and measuring each in its own window gives the same
    answer as removing them one at a time. Greedy first-fit over groups sorted by
    start date.
    """
    batches: list[list[InteractionGroup]] = []
    for group in sorted(groups, key=lambda item: item.start):
        for batch in batches:
            if all(_groups_independent(group, other, separation_days) for other in batch):
                batch.append(group)
                break
        else:
            batches.append([group])
    return batches


def _groups_independent(
    left: InteractionGroup, right: InteractionGroup, separation_days: int
) -> bool:
    """True when two groups cannot influence each other."""
    gap = dt.timedelta(days=separation_days)
    if left.start > right.end + gap or right.start > left.end + gap:
        return True
    return not any(
        one.scope.may_interact_with(other.scope) for one in left.events for other in right.events
    )


class CounterfactualRunner:
    """Produces counterfactual panels for an event ledger.

    The factual panel is computed once and reused. Every counterfactual is a full run
    of the *same* simulator with the *same* seeds — the only difference is which
    events the overlay contains.
    """

    def __init__(self, simulator: Simulator, events: list[Event]) -> None:
        self._simulator = simulator
        self._events = list(events)
        self._overlay = self._overlay_for(self._events)
        self._factual: SimulationPanel | None = None

    def _overlay_for(self, events: list[Event]) -> LedgerOverlay:
        return LedgerOverlay(
            events,
            config=self._simulator.config,
            catalog=self._simulator.catalog,
            cells=self._simulator.assortment,
            horizon_start=self._simulator.config.horizon.start,
        )

    @property
    def factual(self) -> SimulationPanel:
        """The world as it happened, with every event in force."""
        if self._factual is None:
            self._factual = self._simulator.run(self._overlay)
        return self._factual

    def without(self, removed: set[str]) -> SimulationPanel:
        """The world with ``removed`` events never having happened."""
        kept = [event for event in self._events if event.event_id not in removed]
        logger.debug("truth.counterfactual", removed=len(removed), kept=len(kept))
        return self._simulator.run(self._overlay_for(kept))
