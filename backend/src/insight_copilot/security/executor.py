"""Execution of compiled queries, with the second half of the audit trail.

WHY execution is separate from compilation: the compiler is a pure function of
(request, contract, session) and is therefore testable without a database, which is
what lets the adversarial entitlement tests run in milliseconds. This module is the
only place a connection is touched, and it audits every run with the row count.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from insight_copilot.errors import CompilerError
from insight_copilot.logging import get_logger
from insight_copilot.security.audit import AuditLog, AuditRecord
from insight_copilot.security.identity import SessionContext
from insight_copilot.security.query import CompiledQuery

logger = get_logger(__name__)


class SQLConnection(Protocol):
    """The slice of a DuckDB connection this module uses.

    A Protocol rather than the concrete type so a test can pass a fake, and so the
    warehouse could be swapped for another engine without touching this file.
    """

    def execute(self, query: str, parameters: object = ..., /) -> Any: ...


class QueryExecutor:
    """Runs a `CompiledQuery` and records the execution."""

    def __init__(self, connection: SQLConnection, audit_log: AuditLog) -> None:
        self._connection = connection
        self._audit = audit_log

    def run(self, compiled: CompiledQuery, session: SessionContext) -> pd.DataFrame:
        """Execute and audit. Errors are audited too, then re-raised typed."""
        try:
            result = self._connection.execute(compiled.sql, dict(compiled.parameters))
            # The Protocol deliberately returns Any: the connection is swappable and
            # DuckDB's result type is not part of this module's contract. Narrow here.
            frame: pd.DataFrame = pd.DataFrame(result.fetchdf())
        except Exception as exc:
            self._record(compiled, session, rows=None, outcome="error", reason=str(exc))
            raise CompilerError(
                f"{compiled.contract_id}: query execution failed", detail=str(exc)
            ) from exc

        self._record(compiled, session, rows=len(frame), outcome="ok")
        logger.info(
            "compiler.executed",
            run_id=session.run_id,
            contract_id=compiled.contract_id,
            rows=len(frame),
            sql_hash=compiled.sql_hash[:12],
        )
        return frame

    def _record(
        self,
        compiled: CompiledQuery,
        session: SessionContext,
        *,
        rows: int | None,
        outcome: str,
        reason: str | None = None,
    ) -> None:
        self._audit.record(
            AuditRecord(
                run_id=session.run_id,
                event="execute",
                user_id=session.identity.user_id,
                role=session.role_name,
                intent=session.intent,
                contract_id=compiled.contract_id,
                contract_version=compiled.contract_version,
                sql_hash=compiled.sql_hash,
                row_filter=compiled.row_filter,
                masked_columns=compiled.masked_columns,
                rows_returned=rows,
                outcome=outcome,  # type: ignore[arg-type]  # Literal narrowed by callers
                reason=reason,
            )
        )
