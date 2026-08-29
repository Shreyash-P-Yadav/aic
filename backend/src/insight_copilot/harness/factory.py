"""One place that wires the harness together, so the CLI, the API and the gate agree.

Dependency injection everywhere else means a lot of constructor arguments here. That
is the trade the build standard makes deliberately: every collaborator is swappable in
a test, and the one function that knows the real wiring is this one.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from insight_copilot.config import Settings, get_settings
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.datagen.pipeline import GeneratedWorld, generate_world
from insight_copilot.harness.clock import SimClock
from insight_copilot.harness.controls import DemoControls
from insight_copilot.harness.landing import LandingZone
from insight_copilot.harness.replay import ReplayHarness
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


@dataclass
class HarnessBundle:
    """Everything one running intake stack needs, already wired."""

    world: GeneratedWorld
    warehouse: Warehouse
    landing: LandingZone
    harness: ReplayHarness
    controls: DemoControls
    settings: Settings

    def close(self) -> None:
        """Release the warehouse handle."""
        self.warehouse.close()


def build_harness(
    *,
    settings: Settings | None = None,
    world: GeneratedWorld | None = None,
    warehouse_path: Path | str | None = None,
    landing_dir: Path | None = None,
    start_at: dt.date | None = None,
) -> HarnessBundle:
    """Build the clock, landing zone, warehouse and replay harness from settings."""
    config = settings or get_settings()
    generated = world or generate_world(
        seed=config.seed, registry=ContractRegistry.from_directory(config.contracts_dir)
    )
    registry = ContractRegistry.from_directory(config.contracts_dir)
    warehouse = Warehouse(warehouse_path if warehouse_path is not None else config.warehouse_path)
    zone = LandingZone(landing_dir or config.landing_dir)

    horizon = generated.simulator.config.horizon
    horizon_start = horizon.start
    clock = SimClock(
        start=dt.datetime.combine(start_at or horizon_start, dt.time.min),
        mode=config.clock_mode,
        speed=config.replay_speed,
        tz=config.timezone,
    )
    harness = ReplayHarness(
        clock=clock,
        registry=registry,
        frames=generated.frames,
        warehouse=warehouse,
        landing=zone,
        seeds=generated.simulator.seeds,
        horizon=(horizon.start, horizon.end),
    )
    controls = DemoControls(
        harness,
        warehouse,
        generated.ledger,
        generated.simulator.seeds,
        horizon_start=horizon_start,
    )
    logger.info(
        "harness.built",
        sources=len(registry.source_ids),
        warehouse=str(warehouse_path or config.warehouse_path),
        landing=str(zone.root),
    )
    return HarnessBundle(
        world=generated,
        warehouse=warehouse,
        landing=zone,
        harness=harness,
        controls=controls,
        settings=config,
    )
