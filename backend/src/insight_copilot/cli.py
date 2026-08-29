"""Command-line entry point.

WHY a hand-rolled argparse CLI rather than an orchestration framework: the design
docs explicitly reject Airflow/Dagster — orchestration is not what is being judged,
and a ~100-line dispatcher is auditable in one screen.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from insight_copilot.config import get_settings
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.errors import ContractError, SimulationError
from insight_copilot.logging import get_logger

if TYPE_CHECKING:
    from insight_copilot.harness.factory import HarnessBundle

logger = get_logger(__name__)

Command = Callable[[argparse.Namespace], int]

DEFAULT_REPLAY_DAYS = 30
"""A month of live arrivals is enough for every declared cadence — daily, weekly,
T+2, half-hourly and annual — to be exercised at least once."""


def _not_yet(phase: str) -> Command:
    """Placeholder that fails loudly. A stub must never look like a success."""

    def run(_: argparse.Namespace) -> int:
        logger.error("cli.not_implemented", phase=phase)
        print(f"Not implemented yet — arrives in phase {phase}.", file=sys.stderr)
        return 2

    return run


def _cmd_info(_: argparse.Namespace) -> int:
    """Print the resolved configuration. Useful when a demo behaves unexpectedly."""
    cfg = get_settings()
    print(f"{cfg.app_name} · environment={cfg.environment} · llm_provider={cfg.llm_provider}")
    print(f"seed={cfg.seed} sim_today={cfg.sim_today} clock_mode={cfg.clock_mode}")
    print(f"warehouse={cfg.warehouse_path}")
    return 0


def _cmd_validate_contracts(_: argparse.Namespace) -> int:
    """Load and cross-check every contract, reporting all problems in one pass."""
    cfg = get_settings()
    try:
        registry = ContractRegistry.from_directory(cfg.contracts_dir)
    except ContractError as exc:
        print(f"FAIL  {exc.message}", file=sys.stderr)
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return 1
    print(f"OK    {len(registry.kpi_ids)} KPI contracts:    {', '.join(registry.kpi_ids)}")
    print(f"OK    {len(registry.source_ids)} source contracts: {', '.join(registry.source_ids)}")
    for kpi_id in registry.kpi_ids:
        contract = registry.kpi(kpi_id)
        roles = ", ".join(
            f"{name}{'(deny)' if policy.deny else ''}"
            for name, policy in sorted(contract.access.roles.items())
        )
        print(f"      {kpi_id} v{contract.contract_version} — roles: {roles}")
    return 0


def _cmd_generate_truth(_: argparse.Namespace) -> int:
    """Compute every planted event's true causal contribution and write the ledger.

    The expensive step in the whole build: one full simulation per planned
    counterfactual. Independent events share runs, so the 448-event ledger costs
    about 150 simulations rather than about 900.
    """
    from insight_copilot.datagen.events.build import build_full_ledger
    from insight_copilot.datagen.simulate import Simulator
    from insight_copilot.datagen.truth.ledger_writer import GroundTruthComputer, write_ledger

    cfg = get_settings()
    cfg.ensure_dirs()
    try:
        simulator = Simulator.from_defaults(cfg.seed)
        ledger = build_full_ledger(simulator.config, simulator.catalog, simulator.seeds)
        truth = GroundTruthComputer(simulator, ledger.events).compute()
        path = write_ledger(truth, cfg.data_dir)
    except SimulationError as exc:
        print(f"FAIL  {exc.message}", file=sys.stderr)
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return 1
    print(truth.summary())
    print(f"      -> {path}")
    return 0


def _cmd_generate(_: argparse.Namespace) -> int:
    """Simulate the world and write the L3 truth tables."""
    import time

    from insight_copilot.datagen.pipeline import generate_world
    from insight_copilot.datagen.writer import write_sources, write_truth_tables

    cfg = get_settings()
    cfg.ensure_dirs()
    try:
        started = time.perf_counter()
        world = generate_world(seed=cfg.seed)
        result = write_truth_tables(
            world.simulator, world.panel, cfg.data_dir, elapsed=time.perf_counter() - started
        )
        source_counts = write_sources(world, cfg.data_dir)
    except SimulationError as exc:
        print(f"FAIL  {exc.message}", file=sys.stderr)
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return 1

    print(result.summary())
    print(f"OK    {len(world.frames.source_ids)} source extracts -> {cfg.data_dir / 'sources'}")
    for name, count in sorted(source_counts.items()):
        print(f"      {name:24s} {count:>10,} rows")

    evidence = world.catalog.detect_all(world.frames, world.context)
    detected = sum(1 for item in evidence.values() if item.present)
    print(
        f"OK    defect catalog: {detected}/{len(world.catalog)} pathologies present and detectable"
    )
    for delta in world.reconciliations:
        status = "ok " if delta.in_designed_range else "OUT"
        print(
            f"      [{status}] {delta.name:34s} median {delta.median_pct:6.2f}% "
            f"(designed {delta.designed_range[0]:.1f}-{delta.designed_range[1]:.1f}%)"
        )
    print("      All data is simulated. Meridian Consumer Brands is a fictional company.")
    return 0


def _cmd_backfill(_: argparse.Namespace) -> int:
    """Bulk historical load: land one extract per source and build every mart.

    This is how a real deployment begins, and it is also the cold-start demo — the
    moment the system comes up it has thirty-six months for most SKUs and eighteen
    days for the newest launch, which is the whole point of Scenario C.
    """
    return _run_intake(days=0, replay=False)


def _cmd_replay(args: argparse.Namespace) -> int:
    """Backfill to N days before ``sim_today``, then replay those days live."""
    return _run_intake(
        days=max(int(getattr(args, "days", 0) or DEFAULT_REPLAY_DAYS), 1), replay=True
    )


def _run_intake(*, days: int, replay: bool) -> int:
    """Shared body of ``backfill`` and ``replay``: build, load, report."""
    import datetime as dt

    from insight_copilot.errors import IngestionError
    from insight_copilot.harness.factory import build_harness

    cfg = get_settings()
    cfg.ensure_dirs()
    today = dt.date.fromisoformat(cfg.sim_today)
    go_live = today - dt.timedelta(days=days) if replay else today

    bundle: HarnessBundle | None = None
    try:
        bundle = build_harness()
        horizon_start = bundle.world.simulator.config.horizon.start
        summary = bundle.harness.backfill(horizon_start, go_live)
        print(
            f"OK    historical load {horizon_start}..{go_live}: "
            f"{summary.landed} extracts, {summary.rows_landed:,} rows, "
            f"{summary.rows_quarantined:,} quarantined"
        )
        if replay:
            summary = bundle.harness.advance_days(days)
            print(
                f"OK    replayed {days} sim-days to {bundle.harness.clock.today}: "
                f"{summary.landed} batches landed, {summary.missed} drops missed, "
                f"{summary.rows_landed:,} rows, {summary.rows_quarantined:,} quarantined"
            )
        _print_marts(bundle)
        _print_freshness(bundle)
    except (IngestionError, SimulationError) as exc:
        print(f"FAIL  {exc.message}", file=sys.stderr)
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return 1
    finally:
        if bundle is not None:
            bundle.close()
    return 0


def _print_marts(bundle: HarnessBundle) -> None:
    """Row counts for every gold object the KPI contracts read."""
    print("OK    gold marts:")
    for table in (
        "fct_revenue_daily",
        "fct_fulfilment_daily",
        "fct_marketing_weekly",
        "cube_revenue",
        "driver_panel",
        "dim_calendar",
    ):
        print(f"      gold.{table:22s} {bundle.warehouse.row_count('gold', table):>10,} rows")


def _print_freshness(bundle: HarnessBundle) -> None:
    """The landing-zone monitor, as text."""
    print("OK    freshness:")
    for status in bundle.harness.freshness():
        age = f"{status.age_hours:6.1f}h" if status.age_hours is not None else "     -"
        print(
            f"      [{status.state:5s}] {status.source_id:22s} age {age} "
            f"sla {status.sla_hours:5.0f}h  latest {status.latest_period or '-'}"
        )


COMMANDS: dict[str, Command] = {
    "info": _cmd_info,
    "validate-contracts": _cmd_validate_contracts,
    "generate": _cmd_generate,
    "generate-truth": _cmd_generate_truth,
    "backfill": _cmd_backfill,
    "replay": _cmd_replay,
    "run": _not_yet("P6"),
    "backtest": _not_yet("P11"),
    "demo": _not_yet("P12"),
    "demo-reset": _not_yet("P12"),
}


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a subcommand. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="insight-copilot", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS), help="subcommand to run")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_REPLAY_DAYS,
        help="replay window in simulated days (replay only)",
    )
    args, _rest = parser.parse_known_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
