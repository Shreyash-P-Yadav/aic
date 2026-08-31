"""One entry point that runs every eval and writes the report.

Assembled here rather than in the CLI so the gate, the CLI and a future scheduled run
all execute the same sequence. The sequence is: replay the ledger, fit the calibration
map on the pre-cut half, derive the tier bands from the fitted curve, then measure
narration, entitlements and budgets on the live demo path.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from insight_copilot.api.state import AppState
from insight_copilot.config import Settings, get_settings
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.demo import run_demo
from insight_copilot.engine.dataset import EngineDataset
from insight_copilot.errors import ContractError, StatisticalError
from insight_copilot.evals.backtest import CalibrationBacktest
from insight_copilot.evals.checks import NarrationScore, check_entitlements, score_narration
from insight_copilot.evals.corpus import documents_from_warehouse
from insight_copilot.evals.elasticity import ElasticityComparison, media_elasticities
from insight_copilot.evals.models import EvalReport
from insight_copilot.evals.report import write_report
from insight_copilot.evals.suite import build_report, fit_calibrator
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.learning.ranker import PriorityRanker
from insight_copilot.learning.store import FeedbackStore
from insight_copilot.llm.hypotheses import HypothesisProposer
from insight_copilot.llm.narrate import PersonaNarrator
from insight_copilot.logging import get_logger
from insight_copilot.security.compiler import ContractSQLCompiler
from insight_copilot.security.executor import QueryExecutor

logger = get_logger(__name__)

DEFAULT_CUT_DATE = dt.date(2025, 7, 1)
"""The temporal split. Chosen to leave roughly a third of the corpus after it while
keeping the fit set clear of the 2026 demo window entirely — not tuned against any
metric, and stated here so it can be checked."""

PERSONAS = ("cfo", "analyst", "rsm", "marketing_lead")
"""Every persona is narrated, because numeric fidelity has to hold for all of them."""

CALIBRATION_FILE = "calibration.json"
"""Where the fitted map is written, beside the report that justifies it."""


@dataclass
class EvalRun:
    """What a run produced: the report and where it was written."""

    report: EvalReport
    markdown: Path
    json: Path

    @property
    def passed(self) -> bool:
        """Did every metric with a target meet it?"""
        return self.report.passed


def run_evals(
    *,
    settings: Settings | None = None,
    cut_date: dt.date = DEFAULT_CUT_DATE,
    ledger_path: Path | None = None,
) -> EvalRun:
    """Run the whole suite against the loaded warehouse and write both artifacts."""
    config = settings or get_settings()
    ledger_file = ledger_path or (config.data_dir / "ledger.parquet")
    if not ledger_file.exists():
        raise ContractError(
            "the truth ledger has not been generated",
            detail=f"{ledger_file} is missing; run `make generate-truth` first",
        )
    warehouse, snapshot = _open_warehouse(config)
    try:
        return _run(config, warehouse, pd.read_parquet(ledger_file), cut_date)
    finally:
        warehouse.close()
        if snapshot is not None:
            snapshot.unlink(missing_ok=True)


def _open_warehouse(config: Settings) -> tuple[Warehouse, Path | None]:
    """Open the warehouse, snapshotting it first if a running server holds the lock.

    DuckDB permits one writer OR several readers, and `make demo` holds a writer for as
    long as it serves — so running the eval suite against a live demo would otherwise
    fail on a lock rather than on anything to do with the evals. The backtest only ever
    reads, so a file copy is a correct snapshot; it is taken to a temporary path,
    reported, and removed afterwards. The alternative — making the gate order-dependent
    on which server happens to be up — is the kind of constraint nobody remembers.
    """
    try:
        return Warehouse(config.warehouse_path), None
    except duckdb.IOException as exc:
        logger.info("evals.snapshotting_warehouse", reason=str(exc))
    handle, path = tempfile.mkstemp(prefix="insight-copilot-eval-", suffix=".duckdb")
    os.close(handle)
    snapshot = Path(path)
    shutil.copyfile(config.warehouse_path, snapshot)
    logger.info("evals.snapshot_ready", path=str(snapshot))
    return Warehouse(snapshot), snapshot


def _run(
    config: Settings, warehouse: Warehouse, ledger: pd.DataFrame, cut_date: dt.date
) -> EvalRun:
    """The sequence itself, with the warehouse already open."""
    state = AppState(config)
    state.attach_warehouse(warehouse, None, None)
    dataset = EngineDataset(
        warehouse=warehouse,
        registry=state.registry,
        compiler=ContractSQLCompiler(state.registry, state.audit),
        executor=QueryExecutor(warehouse.connection, state.audit),
    )
    documents = documents_from_warehouse(warehouse)
    _seed_insights(state, warehouse, documents)

    started = time.perf_counter()
    backtest = CalibrationBacktest(dataset, state.registry, state.session, documents).run(
        ledger, cut_date=cut_date
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    per_event_ms = elapsed_ms / max(len(backtest.outcomes), 1)

    fit = fit_calibrator(backtest)
    calibration_path = config.artifacts_dir / CALIBRATION_FILE
    notes: list[str] = [f"calibration: {fit.detail}"]
    if fit.calibrator.fitted:
        fit.calibrator.save(calibration_path)
        notes.append(f"calibration map written to {calibration_path}")
    if not fit.adopted:
        notes.append(
            "tier boundaries fall back to the contract's own bands; the system reports "
            "itself uncalibrated rather than claiming a calibration it has not earned"
        )

    elasticity = _elasticity(warehouse)
    leakage = check_entitlements(state.registry, ContractSQLCompiler(state.registry, state.audit))
    narration = _narration(state)
    ranker = PriorityRanker(FeedbackStore(config.data_dir / "feedback.jsonl")).status

    report = build_report(
        backtest,
        calibrator=fit.calibrator,
        boundaries=fit.boundaries,
        narration=narration,
        elasticity=elasticity,
        leakage=leakage,
        ranker=ranker,
        latency_ms=per_event_ms,
        cost_usd=0.0,
        notes=notes,
    )
    markdown, json_path = write_report(report, config.artifacts_dir)
    return EvalRun(report=report, markdown=markdown, json=json_path)


def _elasticity(warehouse: Warehouse) -> ElasticityComparison | None:
    """The endogeneity comparison, or nothing when the marts it needs are absent."""
    try:
        return media_elasticities(warehouse)
    except (ContractError, StatisticalError, KeyError) as exc:
        logger.warning("evals.elasticity_failed", error=str(exc))
        return None


def _seed_insights(state: AppState, warehouse: Warehouse, documents: list[Document]) -> None:
    """Run the scripted scenario so there is something real to narrate and verify.

    The same ``run_demo`` the CLI and the E2E suite drive, given the corpus read back
    out of silver rather than the generator's in-memory documents — so the eval
    narrates the bundle a user would actually see, not a fixture built for the eval.
    """
    try:
        run_demo(state, _CorpusHolder(documents), warehouse)
    except (ContractError, StatisticalError) as exc:
        logger.warning("evals.demo_seed_failed", error=str(exc))


@dataclass(frozen=True)
class _CorpusHolder:
    """The one attribute ``run_demo`` reads off the world object."""

    documents: list[Document]


def _narration(state: AppState) -> NarrationScore | None:
    """Narrate every stored insight for every persona, or report none were available.

    Returns ``None`` rather than a zero score when there is nothing to narrate: a
    fidelity of 100% over zero numbers is not a pass, and the report shows ``n = 0``.
    """
    bundles = [record.bundle for record in state.insights.values() if record.bundle is not None]
    if not bundles:
        logger.info("evals.no_bundles_to_narrate")
        return None
    narrator = PersonaNarrator(state.router)
    proposer = HypothesisProposer(state.router)
    try:
        return score_narration(
            narrator, bundles, list(PERSONAS), proposer=proposer, registry=state.registry
        )
    except StatisticalError as exc:
        logger.warning("evals.narration_failed", error=str(exc))
        return None
