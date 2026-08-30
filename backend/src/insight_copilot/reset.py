"""``make demo-reset`` — back to a pristine, re-runnable demo state.

What gets removed is exactly the *derived* state: the warehouse, the landing zone, the
telemetry ledger, the run artifacts. What never gets removed is anything a human wrote
or anything a re-run cannot rebuild — contracts, source code, and the truth ledger,
which costs six minutes of counterfactual simulation to recompute and is deterministic
from the seed anyway.

The distinction matters more than it looks. A reset that deletes the truth ledger turns
a ten-second reset into a six-minute one, and a reset that deletes anything under
version control is a reset nobody will run twice.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from insight_copilot.config import Settings, get_settings
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

DERIVED_FILES = ("warehouse.duckdb", "warehouse.duckdb.wal", "feedback.jsonl")
"""Files the ingestion and the learning loop write. All rebuildable from a re-run."""

DERIVED_DIRECTORIES = ("landing",)
"""The landing zone. Batches are re-landed by ``backfill`` or ``replay``."""

ARTIFACT_FILES = ("eval_report.md", "eval_report.json", "calibration.json")
"""Run artifacts. Screenshots are left alone: they are captured by the E2E suite and
deleting them would make a reset look like a test failure."""

PRESERVED = (
    "ledger.parquet — the counterfactual truth ledger (~6 minutes to recompute, "
    "deterministic from the seed)",
    "generated/ — the simulated world (rebuilt by `make generate`)",
    "sources/ — the projected source extracts",
)
"""Reported on every reset so it is obvious what was kept and why."""


@dataclass
class ResetResult:
    """What a reset removed and what it deliberately left in place."""

    removed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    preserved: tuple[str, ...] = PRESERVED

    @property
    def detail(self) -> str:
        """The line the CLI prints."""
        if not self.removed:
            return "already pristine; nothing to remove"
        return f"removed {len(self.removed)} derived item(s)"


def reset_demo(settings: Settings | None = None) -> ResetResult:
    """Remove derived state so the next ``make demo`` starts from a clean warehouse.

    Idempotent by construction: a path that is already gone is recorded as missing
    rather than raising, so running this twice is not an error.
    """
    config = settings or get_settings()
    result = ResetResult()
    for name in DERIVED_FILES:
        _remove_file(config.data_dir / name, result)
    for name in DERIVED_DIRECTORIES:
        _remove_tree(config.data_dir / name, result)
    for name in ARTIFACT_FILES:
        _remove_file(config.artifacts_dir / name, result)
    config.ensure_dirs()
    logger.info("reset.complete", removed=len(result.removed), missing=len(result.missing))
    return result


def _remove_file(path: Path, result: ResetResult) -> None:
    """Delete one file, recording whether it was there."""
    if path.exists():
        path.unlink()
        result.removed.append(str(path))
    else:
        result.missing.append(str(path))


def _remove_tree(path: Path, result: ResetResult) -> None:
    """Empty one directory, recording it as removed only if it held anything.

    The directory itself is recreated by ``ensure_dirs`` moments later, because the
    next run needs it. Reporting an already-empty directory as "removed" would make a
    second reset look like it found work to do, which is exactly the signal a reader
    uses to tell a pristine state from a dirty one.
    """
    if not path.exists() or not any(path.iterdir()):
        result.missing.append(f"{path}/")
        return
    shutil.rmtree(path)
    result.removed.append(f"{path}/")
