"""structlog configuration.

WHY structured logging rather than ``print`` or stdlib formatting: every stage of the
pipeline logs start/end bound to a ``run_id``, and the telemetry page reads those same
fields. If the log line is a formatted string, the telemetry has to re-parse English.
Key/value events are the same data in both places.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from insight_copilot.config import Settings, get_settings

_CONFIGURED = False


def configure_logging(settings: Settings | None = None) -> None:
    """Install the processor chain. Idempotent — safe to call from any entry point."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    cfg = settings or get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, cfg.log_level),
    )

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if cfg.log_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, cfg.log_level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. The only module-level singleton besides settings."""
    configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
