"""Shared fixtures for the integration tests.

The generated world is expensive (~35 s) and read-only, so it is built once per
session and shared. No test mutates it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from insight_copilot.datagen.pipeline import GeneratedWorld, generate_world
from insight_copilot.harness.factory import build_harness

SEED = 20260329

P5_GO_LIVE = dt.date(2026, 1, 5)
"""Where the bulk historical load stops and live arrivals begin. It leaves a
clean quarter of replay in front of the demo's ``sim_today`` (2026-03-29)."""

P5_REPLAY_DAYS = 90
"""The P5 gate's replay window: thirteen MarTech drops, ninety OMS drops and
several thousand ticket batches — every declared cadence, many times over."""


@pytest.fixture(scope="session")
def world() -> GeneratedWorld:
    """Truth, eleven source extracts, the full defect catalog and the corpus."""
    return generate_world(seed=SEED)


@pytest.fixture(scope="session")
def clean_world() -> GeneratedWorld:
    """The same world with the defect catalog switched off.

    Used to prove a defect is *injected* rather than incidental: if a pathology is
    present with the injectors disabled, it was never the injector's doing.
    """
    return generate_world(seed=SEED, apply_defects=False)


@pytest.fixture(scope="session")
def replayed(world: GeneratedWorld, tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """The bulk historical load followed by ninety simulated days of live arrivals.

    One session-scoped stack rather than two: the historical load is the expensive
    step and running it twice would double the gate's wall time for no extra coverage.
    The tests that assert on the load run first and the mutating ones (restatements,
    a paused feed, a late batch) run after, each re-deriving its own baseline.
    """
    root = tmp_path_factory.mktemp("p5")
    bundle = build_harness(
        world=world, warehouse_path=root / "warehouse.duckdb", landing_dir=root / "landing"
    )
    loaded_summary = bundle.harness.backfill(world.simulator.config.horizon.start, P5_GO_LIVE)
    summary = bundle.harness.advance_days(P5_REPLAY_DAYS)
    return {
        "bundle": bundle,
        "harness": bundle.harness,
        "controls": bundle.controls,
        "warehouse": bundle.warehouse,
        "seeds": world.simulator.seeds,
        "summary": summary,
        "backfill": loaded_summary,
    }


@pytest.fixture(scope="session")
def loaded(replayed: dict[str, object]) -> dict[str, object]:
    """The same stack, named for the assertions that are about the historical load."""
    return replayed
