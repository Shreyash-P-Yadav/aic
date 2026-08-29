"""Assembling the complete event ledger: scenarios, ambient and calibration.

One entry point so the CLI, the truth computation and the tests all see exactly the
same world. Deterministic: the ledger is a pure function of the world config and the
seed, so two runs produce the same events in the same order.
"""

from __future__ import annotations

from insight_copilot.datagen.events.ambient import generate_ambient
from insight_copilot.datagen.events.calibration_gen import generate_calibration
from insight_copilot.datagen.events.ledger import EventLedger
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


def build_full_ledger(config: WorldConfig, catalog: ProductCatalog, seeds: SeedBook) -> EventLedger:
    """The scripted scenarios, the ambient background, and the calibration corpus."""
    scenarios = EventLedger.from_scenarios()
    ambient = generate_ambient(config, seeds)
    calibration = generate_calibration(config, catalog, seeds)
    ledger = EventLedger([*scenarios.events, *ambient, *calibration])
    logger.info(
        "events.ledger_built",
        scenario=len(scenarios),
        ambient=len(ambient),
        calibration=len(calibration),
        total=len(ledger),
    )
    return ledger
