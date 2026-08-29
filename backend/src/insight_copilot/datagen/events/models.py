"""The event schema (DataLayer §8).

Everything interesting in this world is an **event** with an explicit, machine-readable
definition. Events are the input to the simulator, the seed for the corpus, and the
key for ground truth — one definition serving three purposes is what keeps the
documents causally consistent with the numbers.

Magnitude is a discriminated union rather than a free-form mapping. An outage caps
picking; a media shift scales spend; a price change scales price. Typing them
separately means the overlay that applies them cannot silently ignore a field, and a
scenario YAML with a misspelled magnitude key fails at load.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EventType = Literal[
    "price_change",
    "promo",
    "media_shift",
    "outage",
    "supplier_delay",
    "launch",
    "competitor_action",
    "bulk_order",
    "regime_break",
    "data_incident",
]

Detectability = Literal["high", "medium", "low", "none"]
EventSet = Literal["scenario", "ambient", "calibration"]


class Frozen(BaseModel):
    """Events are immutable once loaded: they are the ground-truth key."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _members_intersect(mine: list[str], theirs: list[str]) -> bool:
    """Empty means "all members", so an empty list intersects anything."""
    if not mine or not theirs:
        return True
    return bool(set(mine) & set(theirs))


class EventScope(Frozen):
    """Which slice of the business an event touches.

    An empty list means "all members of that dimension". Narrow scope is what makes
    the dimensional attribution search a real search: an event confined to one region
    and three SKUs has to be *found*, not read off a total.
    """

    warehouses: list[str] = Field(default_factory=list)
    skus: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    media_channels: list[str] = Field(default_factory=list)

    @property
    def is_national(self) -> bool:
        """True when no dimension is restricted."""
        return not (self.warehouses or self.skus or self.categories or self.regions)

    def may_interact_with(self, other: EventScope) -> bool:
        """Could these two events' effects interfere with each other?

        Not a blunt dimension intersection — that treats "same category, different
        region" as coupled, which it is not, and chains hundreds of independent
        calibration events into one enormous group. The couplings in this world are
        specific and there are only three:

        * **Demand and substitution** — two events touching the same *region and
          category* compete for the same customers, and censored demand leaks between
          SKUs inside one region-category pool.
        * **Inventory** — two events drawing on the same *warehouse*, for overlapping
          regions, categories and SKUs, compete for the same stock. All four have to
          match: a DC-North conveyor failure in Haircare does not compete for stock
          with a Skincare demand shock in the South, and treating "one side named no
          region" as "every region" would chain every outage to every demand event.
        * **Media adstock** — two events moving the same *media channel* in the same
          region move the same adstock state.

        Anything else is independent, whatever the calendar says. An empty member
        list still means "every member" within each of those tests.
        """
        demand_coupled = (
            _members_intersect(self.regions, other.regions)
            and _members_intersect(self.categories, other.categories)
            and _members_intersect(self.skus, other.skus)
        )
        inventory_coupled = (
            _members_intersect(self.warehouses, other.warehouses)
            and _members_intersect(self.regions, other.regions)
            and _members_intersect(self.categories, other.categories)
            and _members_intersect(self.skus, other.skus)
        )
        media_coupled = _members_intersect(
            self.media_channels, other.media_channels
        ) and _members_intersect(self.regions, other.regions)

        # Media coupling only applies when at least one side actually names a
        # channel; otherwise every pair of events would be "media coupled" through
        # two empty lists.
        if not (self.media_channels or other.media_channels):
            media_coupled = False
        if not (self.warehouses or other.warehouses):
            inventory_coupled = False
        return demand_coupled or inventory_coupled or media_coupled


class EventWindow(Frozen):
    """When an event is in force. Dates are IST calendar dates."""

    start: dt.date
    end: dt.date

    @model_validator(mode="after")
    def _ordered(self) -> EventWindow:
        if self.end < self.start:
            raise ValueError("event window ends before it starts")
        return self

    @property
    def days(self) -> int:
        """Inclusive length in days."""
        return (self.end - self.start).days + 1


# ------------------------------------------------------------------ magnitudes --
class OutageMagnitude(Frozen):
    """A warehouse's throughput is capped. The units are there; they cannot move.

    ``pick_capacity`` is the fraction of the day's DEMAND the site can still pick and
    ship, not a fraction of stock: a conveyor failure limits units per day through
    the building, and inventory is untouched. Cross-serving from another DC then
    recovers part of the shortfall, which is why an outage costs less revenue than it
    costs fill rate — and separating those two is what the ladder has to get right.
    """

    kind: Literal["outage"] = "outage"
    pick_capacity: float = Field(
        ge=0.0, le=1.0, description="Fraction of the day's demand the site can ship."
    )


class MediaShiftMagnitude(Frozen):
    """Spend on named channels is scaled. A cut is a multiplier below 1."""

    kind: Literal["media_shift"] = "media_shift"
    spend_multiplier: float = Field(ge=0.0, le=5.0)


class PriceChangeMagnitude(Frozen):
    """Effective price is scaled. Demand responds through the category elasticity."""

    kind: Literal["price_change"] = "price_change"
    price_multiplier: float = Field(gt=0.0, le=3.0)


class DemandShockMagnitude(Frozen):
    """Demand moves for a reason outside our own levers.

    Competitor launches, category news, weather beyond the modelled response.
    """

    kind: Literal["demand_shock"] = "demand_shock"
    demand_multiplier: float = Field(ge=0.0, le=5.0)


class BulkOrderMagnitude(Frozen):
    """A one-off institutional order. A data event, never a trend."""

    kind: Literal["bulk_order"] = "bulk_order"
    units: float = Field(ge=0.0)


class NoOpMagnitude(Frozen):
    """An event with no mechanical effect at all.

    Used for two things: data incidents, whose effect is on the *feed* rather than on
    the business (they are applied in P4/P5, not here), and the zero-magnitude probe
    the determinism test relies on.
    """

    kind: Literal["none"] = "none"


Magnitude = Annotated[
    OutageMagnitude
    | MediaShiftMagnitude
    | PriceChangeMagnitude
    | DemandShockMagnitude
    | BulkOrderMagnitude
    | NoOpMagnitude,
    Field(discriminator="kind"),
]


# -------------------------------------------------------------------- evidence --
class EvidenceSpec(Frozen):
    """How much documentary evidence this event leaves behind.

    ``documents: 0`` is a **deliberate evidence gap** — a case where attribution is
    statistically strong but externally uncorroborated, which is exactly where
    confidence should fall and sometimes where the engine should abstain. Without
    these, the sufficiency check is never exercised.
    """

    documents: int = Field(default=1, ge=0, le=12)
    contradiction: bool = False
    syndication: int = Field(default=1, ge=1, le=8)
    post_dated_decoy: bool = False
    effective_date_offset_days: int = Field(
        default=0,
        ge=0,
        description="Days by which a document's effective date follows its publication.",
    )


class GroundTruthSpec(Frozen):
    """Whether and how this event's true causal contribution is computed."""

    compute: bool = True
    method: Literal["counterfactual", "shapley_within_window"] = "counterfactual"


class Event(Frozen):
    """One thing that happened, fully specified."""

    event_id: str
    type: EventType
    event_set: EventSet = "ambient"
    scope: EventScope = Field(default_factory=EventScope)
    window: EventWindow
    magnitude: Magnitude = Field(default_factory=NoOpMagnitude)
    detectability: Detectability = "medium"
    evidence: EvidenceSpec = Field(default_factory=EvidenceSpec)
    ground_truth: GroundTruthSpec = Field(default_factory=GroundTruthSpec)
    data_condition: Literal["clean", "stale_feed", "reconciliation_breach", "restatement_open"] = (
        "clean"
    )
    """The state of the DATA at the time this event happened.

    One of the four axes the calibration corpus varies, and the one that spreads the
    data-trust signal ``c4``. It has no mechanical effect on the business — the feed
    degradation it names is applied at source projection and ingestion, not here.
    """

    demo_role: str | None = None
    description: str = ""

    @property
    def is_scenario(self) -> bool:
        """Scenario events are excluded from the calibration fit entirely.

        Otherwise the demo cases would be scored by a map trained on themselves.
        """
        return self.event_set == "scenario"

    @property
    def memory_horizon_days(self) -> int:
        """How long this event can still be influencing the world after it ends.

        The process has bounded memory: adstock ~3 weeks, inventory ~6 weeks, the
        AR(1) shock ~2 weeks. Sixty days is comfortably past all three, and it is the
        separation two events need before their effects can be measured independently.
        """
        return 60
