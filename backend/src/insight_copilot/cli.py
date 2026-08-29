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


COMMANDS: dict[str, Command] = {
    "info": _cmd_info,
    "validate-contracts": _not_yet("P1"),
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
