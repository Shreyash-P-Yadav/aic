"""Where analyst corrections live between runs.

Feedback is the only labelled signal this system ever receives, and it arrives one
sentence at a time from people who will not fill in a form. So the store is
deliberately dumb: append-only JSONL, one record per reaction, no schema migration
story, readable with ``cat``. A learning loop whose training data cannot be inspected
by the person whose corrections are in it is not a loop anyone will trust.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pydantic import Field

from insight_copilot.contracts.common import StrictModel
from insight_copilot.llm.feedback import Label
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


class FeedbackRecord(StrictModel):
    """One analyst reaction to one insight, with everything the ranker needs."""

    insight_id: str
    kpi_id: str
    label: Label
    text: str = ""
    reason: str = ""
    method: str = "rules"
    tier: str = ""
    delta_pct: float = 0.0
    impact_inr: float = 0.0
    confidence: float = 0.0
    segment: str = ""
    recorded_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @property
    def is_positive(self) -> bool:
        """The ranker's target: did the reader find this worth their attention?"""
        return self.label == "useful"


class FeedbackStore:
    """Append-only JSONL of analyst corrections."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Where the records live. Surfaced so the UI can say so."""
        return self._path

    def append(self, record: FeedbackRecord) -> FeedbackRecord:
        """Record one reaction. Never updates in place: a correction is an event."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        logger.info("learning.feedback_recorded", insight_id=record.insight_id, label=record.label)
        return record

    def all(self) -> list[FeedbackRecord]:
        """Every record, oldest first. A missing file is an empty history."""
        if not self._path.exists():
            return []
        records: list[FeedbackRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(FeedbackRecord.model_validate(json.loads(line)))
        return records

    def latest_per_insight(self) -> dict[str, FeedbackRecord]:
        """The most recent reaction per insight — what the ranker trains on.

        Later corrections supersede earlier ones for training while both stay on
        disk, so an analyst who changes their mind is not double-counted and the
        change of mind is still auditable.
        """
        latest: dict[str, FeedbackRecord] = {}
        for record in self.all():
            latest[record.insight_id] = record
        return latest

    def label_counts(self) -> dict[str, int]:
        """How many of each label. The ranker's gate reads this."""
        counts: dict[str, int] = {}
        for record in self.latest_per_insight().values():
            counts[record.label] = counts.get(record.label, 0) + 1
        return counts

    def newest_at(self) -> dt.datetime | None:
        """When the most recent correction arrived. The staleness monitor reads this."""
        records = self.all()
        return max((item.recorded_at for item in records), default=None)
