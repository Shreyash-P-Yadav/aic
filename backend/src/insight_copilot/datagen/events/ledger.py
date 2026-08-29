"""The event ledger: three sets of events, loaded and indexed.

* **`scenarios/`** — the four scripted demo scenarios. Hand-authored, stable, never
  randomised, and **excluded from the calibration fit entirely** so the demo cases
  are not scored by a map trained on themselves.
* **`ambient`** — routine background events (ordinary promos, campaign changes, minor
  supplier slips) that make the world feel lived-in and give the detector realistic
  non-events to ignore.
* **`calibration`** — several hundred stochastic events spanning the whole confidence
  score range, which is what the isotonic map is fitted on.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml
from pydantic import ValidationError

from insight_copilot.datagen.events.models import Event, EventSet
from insight_copilot.errors import SimulationError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


class EventLedger:
    """Every event in the world, with the indexes the truth layer needs."""

    def __init__(self, events: list[Event]) -> None:
        seen: set[str] = set()
        for event in events:
            if event.event_id in seen:
                raise SimulationError(f"duplicate event id {event.event_id!r}")
            seen.add(event.event_id)
        self._events = sorted(events, key=lambda item: (item.window.start, item.event_id))

    # ------------------------------------------------------------------ read --
    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):  # type: ignore[no-untyped-def]  # returns Iterator[Event]
        return iter(self._events)

    @property
    def events(self) -> list[Event]:
        """Every event, ordered by start date then id."""
        return list(self._events)

    def of_set(self, event_set: EventSet) -> list[Event]:
        """Events belonging to one of the three sets."""
        return [event for event in self._events if event.event_set == event_set]

    @property
    def scenario_events(self) -> list[Event]:
        """The demo scenarios — excluded from the calibration fit."""
        return self.of_set("scenario")

    @property
    def calibration_events(self) -> list[Event]:
        """The stochastic corpus the isotonic map is fitted on."""
        return self.of_set("calibration")

    def by_id(self, event_id: str) -> Event:
        """One event, or an error naming what is available."""
        for event in self._events:
            if event.event_id == event_id:
                return event
        raise SimulationError(f"unknown event {event_id!r}")

    def by_demo_role(self, role: str) -> list[Event]:
        """Events tagged for one demo scenario."""
        return [event for event in self._events if event.demo_role == role]

    def with_ground_truth(self) -> list[Event]:
        """Events whose true causal contribution is to be computed."""
        return [event for event in self._events if event.ground_truth.compute]

    def merge(self, other: EventLedger) -> EventLedger:
        """A ledger containing both sets of events."""
        return EventLedger(self._events + other.events)

    # ------------------------------------------------------------------ load --
    @classmethod
    def from_scenarios(cls, directory: Path | None = None) -> EventLedger:
        """Load the hand-authored scenario events."""
        target = directory or SCENARIOS_DIR
        if not target.is_dir():
            raise SimulationError(f"scenario directory not found: {target}")
        events: list[Event] = []
        for path in sorted(target.glob("*.yaml")):
            events.extend(_load_file(path, event_set="scenario"))
        logger.info("events.scenarios_loaded", count=len(events))
        return cls(events)

    def horizon(self) -> tuple[dt.date, dt.date] | None:
        """Earliest start and latest end across the ledger, or None when empty."""
        if not self._events:
            return None
        return (
            min(event.window.start for event in self._events),
            max(event.window.end for event in self._events),
        )


def _load_file(path: Path, *, event_set: EventSet) -> list[Event]:
    """Load one YAML file of events, failing with the filename and field."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SimulationError(f"{path.name}: not valid YAML", detail=str(exc)) from exc
    if not isinstance(raw, list):
        raise SimulationError(f"{path.name}: expected a list of events")

    events: list[Event] = []
    for index, item in enumerate(raw):
        payload = dict(item) if isinstance(item, dict) else {}
        payload.setdefault("event_set", event_set)
        try:
            events.append(Event.model_validate(payload))
        except ValidationError as exc:
            detail = "\n".join(
                f"  {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise SimulationError(
                f"{path.name}: event #{index + 1} failed validation", detail=detail
            ) from exc
    return events
