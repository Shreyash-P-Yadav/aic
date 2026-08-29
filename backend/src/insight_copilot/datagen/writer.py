"""Persist the simulated business reality (L3) to parquet, with a manifest.

WHY a manifest with a checksum rather than just files: the determinism guarantee is
the foundation of every ground-truth number, so the artefact on disk records the seed
and the bit-level digest that produced it. A regeneration that silently drifts is
then a one-line diff rather than a mystery in a downstream eval.

These are the *truth* tables, not source extracts. Nothing here has been through a
source system yet — the lossy projections and the defect catalog arrive in P4.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

TRUTH_SUBDIR = "generated"
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class GenerationResult:
    """What a generation run produced, for the CLI and the tests."""

    directory: Path
    checksum: str
    row_counts: dict[str, int]
    elapsed_seconds: float

    def summary(self) -> str:
        """One line per table, for the CLI."""
        rows = "\n".join(
            f"      {name:24s} {count:>10,} rows" for name, count in sorted(self.row_counts.items())
        )
        return (
            f"OK    generated in {self.elapsed_seconds:.1f}s -> {self.directory}\n"
            f"      checksum {self.checksum[:16]}\n{rows}"
        )


def write_truth_tables(
    simulator: Simulator, panel: SimulationPanel, data_dir: Path, *, elapsed: float = 0.0
) -> GenerationResult:
    """Write every L3 table plus the manifest. Overwrites in place, idempotently."""
    directory = data_dir / TRUTH_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)

    tables: dict[str, pd.DataFrame] = {
        "sales_daily": panel.sales_frame(simulator.config, simulator.catalog),
        "fulfilment_daily": panel.fulfilment_frame(simulator.config, simulator.catalog),
        "media_weekly": panel.media_frame(simulator.config, simulator.calendar.iso_week),
        "product_master": simulator.catalog.to_frame(),
        "calendar_spine": simulator.calendar.to_frame(),
        "weather_daily": _weather_frame(simulator, panel),
    }

    row_counts: dict[str, int] = {}
    for name, frame in tables.items():
        frame.to_parquet(directory / f"{name}.parquet", index=False)
        row_counts[name] = len(frame)

    checksum = panel.checksum()
    manifest = {
        "generator_version": 1,
        "seed": simulator.seeds.seed,
        "horizon": {
            "start": simulator.config.horizon.start.isoformat(),
            "end": simulator.config.horizon.end.isoformat(),
            "days": simulator.calendar.n_days,
        },
        "cells": simulator.assortment.n_cells,
        "skus": len(simulator.catalog.skus),
        "checksum": checksum,
        "row_counts": row_counts,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "note": "All data is simulated. Meridian Consumer Brands is a fictional company.",
    }
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True))

    logger.info("datagen.written", directory=str(directory), rows=sum(row_counts.values()))
    return GenerationResult(
        directory=directory, checksum=checksum, row_counts=row_counts, elapsed_seconds=elapsed
    )


def _weather_frame(simulator: Simulator, panel: SimulationPanel) -> pd.DataFrame:
    """Region x day weather, the exogenous driver the weather feed publishes."""
    calendar = simulator.calendar
    regions = simulator.config.region_ids
    frames = []
    for row, region in enumerate(regions):
        frames.append(
            pd.DataFrame(
                {
                    "observation_date": calendar.dates,
                    "region": region,
                    "monsoon_intensity": calendar.monsoon_intensity[row],
                    "heat_intensity": calendar.heat_intensity[row],
                    "weather_index": panel.weather_index[row],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def read_manifest(data_dir: Path) -> dict[str, object]:
    """Read back the manifest, so a caller can compare checksums across runs."""
    path = data_dir / TRUTH_SUBDIR / MANIFEST_NAME
    payload: dict[str, object] = json.loads(path.read_text())
    return payload
