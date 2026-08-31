"""The document model the corpus produces and the evidence layer consumes."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentKind = Literal[
    "ops_incident",
    "pricing_memo",
    "campaign_brief",
    "supplier_email",
    "news_article",
    "weekly_review",
]

SourceTier = Literal[1, 2, 3, 4]
"""1 = authoritative internal record, 4 = unverified secondary reporting.

Feeds the `source_tier` term of evidence confidence. An ops incident ticket is a
tier-1 fact; a syndicated trade-press rewrite of a press release is tier 4.
"""


class Document(BaseModel):
    """One corpus document.

    **Dual dates are the point.** ``publish_date`` is when it was written;
    ``effective_date`` is when what it describes takes effect. A price revision
    announced in February and effective in April is a single document with two
    dates, and indexing only by publish date means the April anomaly can never find
    its own cause.
    """

    model_config = ConfigDict(frozen=True)

    doc_id: str
    kind: DocumentKind
    title: str
    body: str
    publish_date: dt.date
    effective_date: dt.date
    source_tier: SourceTier
    outlet: str | None = None
    author: str | None = None

    event_id: str | None = Field(
        default=None, description="The ledger event this document describes, if any."
    )
    syndication_group: str | None = Field(
        default=None,
        description=(
            "Shared by every copy of one story. The dedup key: if it fails, noisy-OR "
            "counts one press release across six outlets as six independent sources."
        ),
    )
    contradicts: str | None = Field(
        default=None, description="doc_id of a document this one disagrees with."
    )
    is_post_dated_decoy: bool = False
    scope_skus: list[str] = Field(default_factory=list)
    scope_regions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)

    @property
    def dates_diverge(self) -> bool:
        """True when the effective date is materially later than publication."""
        return (self.effective_date - self.publish_date).days >= 7
