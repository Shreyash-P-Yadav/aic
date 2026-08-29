"""Command-line entry point.

WHY a hand-rolled argparse CLI rather than an orchestration framework: the design
docs explicitly reject Airflow/Dagster — orchestration is not what is being judged,
and a ~100-line dispatcher is auditable in one screen.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from insight_copilot.config import get_settings
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.errors import ContractError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

Command = Callable[[argparse.Namespace], int]


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


COMMANDS: dict[str, Command] = {
    "info": _cmd_info,
    "validate-contracts": _cmd_validate_contracts,
    "generate": _not_yet("P2"),
    "backfill": _not_yet("P5"),
    "run": _not_yet("P6"),
    "backtest": _not_yet("P11"),
    "demo": _not_yet("P12"),
    "demo-reset": _not_yet("P12"),
}


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a subcommand. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="insight-copilot", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS), help="subcommand to run")
    args, _rest = parser.parse_known_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
