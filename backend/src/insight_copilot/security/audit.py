"""Append-only audit trail.

Every compile, every execution, and every denial writes a row. A regulator — or a
judge — can replay any insight end to end from these rows plus the pinned contract
version.

WHY an ABC with two implementations: tests need an audit log with no filesystem and
no warehouse, and the demo needs one that survives a restart. Injecting the sink is
what keeps ``ContractSQLCompiler`` free of I/O concerns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field

AuditEvent = Literal["compile", "execute", "deny", "narrate", "feedback", "override"]


class AuditRecord(BaseModel):
    """One immutable audit row.

    ``sql_hash`` rather than the SQL text is what makes two runs comparable at a
    glance: if the hash is unchanged, the query is unchanged, whatever the caller
    typed into a filter value.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event: AuditEvent
    user_id: str
    role: str
    intent: str
    contract_id: str
    contract_version: str
    sql_hash: str | None = None
    row_filter: str | None = None
    masked_columns: list[str] = Field(default_factory=list)
    rows_returned: int | None = None
    outcome: Literal["ok", "denied", "error"] = "ok"
    reason: str | None = None

    def to_json(self) -> bytes:
        """Serialise for a JSONL sink. Sorted keys so diffs of the log are readable."""
        return orjson.dumps(self.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)


class AuditLog(ABC):
    """Where audit rows go."""

    @abstractmethod
    def record(self, record: AuditRecord) -> None:
        """Append one row. Must never raise on a well-formed record."""

    @abstractmethod
    def records(self) -> list[AuditRecord]:
        """Every row written so far, oldest first."""

    def records_for(self, run_id: str) -> list[AuditRecord]:
        """Every row for one run, which is how an insight is replayed."""
        return [record for record in self.records() if record.run_id == run_id]


class InMemoryAuditLog(AuditLog):
    """The default in tests and in-process runs. Bounded only by the process."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def record(self, record: AuditRecord) -> None:
        """Append one row."""
        self._records.append(record)

    def records(self) -> list[AuditRecord]:
        """A copy, so a caller cannot mutate the trail it is auditing."""
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)


class JsonlAuditLog(AuditLog):
    """Append-only JSONL on disk. Used by the running application.

    WHY JSONL and not a DuckDB table: the audit trail must survive a corrupted or
    half-written warehouse, and a line-oriented file is append-only by construction
    rather than by convention.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: AuditRecord) -> None:
        """Append one row and flush, so a crash does not lose the last decision."""
        with self._path.open("ab") as handle:
            handle.write(record.to_json() + b"\n")

    def records(self) -> list[AuditRecord]:
        """Read the whole trail back. Small by design; rotate before it is not."""
        if not self._path.exists():
            return []
        rows = []
        with self._path.open("rb") as handle:
            for line in handle:
                if line.strip():
                    rows.append(AuditRecord.model_validate(orjson.loads(line)))
        return rows
