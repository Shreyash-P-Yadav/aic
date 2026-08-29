"""Scheduling counterfactual runs so hundreds of events cost dozens of simulations.

Each event needs one or more *coalitions* — sets of events removed from the world — to
measure its contribution. A group of `n` interacting events needs `2**n` coalitions
for Shapley; an isolated event needs one.

Run naively that is hundreds of full simulations. The saving is that groups which
cannot influence each other can have their coalitions removed **in the same run**:
the world without (Skincare-South event #3) and without (Haircare-North event #7) is
simultaneously the counterfactual for both, because neither can reach the other's
rows or the other's window.

So the schedule is: pack groups into batches of mutually independent groups, then run
the batch's coalitions in lockstep. Total runs becomes the sum over batches of the
*largest* group's coalition count, rather than the sum over all groups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from insight_copilot.datagen.truth.counterfactual import (
    SEPARATION_DAYS,
    InteractionGroup,
    plan_batches,
)
from insight_copilot.datagen.truth.shapley import MAX_SHAPLEY_EVENTS
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Coalition:
    """One world to simulate, from one group's point of view."""

    group_index: int
    present: frozenset[str]
    """Event ids from this group that remain in force."""

    removed: frozenset[str]
    """Event ids from this group that are removed."""


@dataclass
class RunPlan:
    """The full schedule: which events to remove in each simulation run."""

    removals: list[frozenset[str]] = field(default_factory=list)
    """One entry per counterfactual run: the union of every coalition's removals."""

    index_of: dict[tuple[int, frozenset[str]], int] = field(default_factory=dict)
    """(group index, present-set) -> the run that realises it."""

    @property
    def n_runs(self) -> int:
        """How many full simulations the plan costs."""
        return len(self.removals)

    def run_for(self, group_index: int, present: frozenset[str]) -> int:
        """Which run realises this group's coalition."""
        return self.index_of[(group_index, present)]


def coalitions_for(group: InteractionGroup, group_index: int) -> list[Coalition]:
    """Every world this group needs simulated.

    Shapley needs all `2**n` subsets. Above `MAX_SHAPLEY_EVENTS` the group falls back
    to one-at-a-time deltas, which need only the full world, the empty world, and one
    world per event.
    """
    ids = group.event_ids
    all_ids = frozenset(ids)
    if len(ids) <= MAX_SHAPLEY_EVENTS:
        subsets = [
            frozenset(present)
            for size in range(len(ids) + 1)
            for present in combinations(ids, size)
        ]
    else:
        subsets = [all_ids, frozenset()] + [all_ids - {event_id} for event_id in ids]
    return [
        Coalition(group_index=group_index, present=present, removed=all_ids - present)
        for present in subsets
    ]


def build_run_plan(
    groups: list[InteractionGroup], *, separation_days: int = SEPARATION_DAYS
) -> RunPlan:
    """Pack every group's coalitions into as few simulation runs as possible."""
    indexed = list(enumerate(groups))
    position_of = {id(group): index for index, group in indexed}
    batches = plan_batches(groups, separation_days=separation_days)

    plan = RunPlan()
    for batch in batches:
        per_group = [coalitions_for(group, position_of[id(group)]) for group in batch]
        longest = max(len(items) for items in per_group)
        for step in range(longest):
            removal: set[str] = set()
            slots: list[Coalition] = []
            for items in per_group:
                # A group with fewer coalitions than the batch's longest simply
                # contributes nothing to the remaining runs; its rows are already
                # measured and leaving it fully present costs nothing.
                coalition = items[step] if step < len(items) else items[0]
                if step < len(items):
                    slots.append(coalition)
                    removal |= coalition.removed
            run_index = len(plan.removals)
            plan.removals.append(frozenset(removal))
            for coalition in slots:
                plan.index_of[(coalition.group_index, coalition.present)] = run_index

    logger.info(
        "truth.run_plan",
        groups=len(groups),
        batches=len(batches),
        runs=plan.n_runs,
    )
    return plan
