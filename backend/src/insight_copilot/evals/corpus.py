"""The evidence corpus as the *system* sees it: read back out of silver.

The backtest deliberately does not use the generator's in-memory documents. Those
carry ``event_id`` and the syndication bookkeeping the projection strips on the way
out, so retrieving against them would be scoring the evidence layer on a corpus it
will never meet in production. Reading silver instead means the backtest retrieves
exactly what an insight run retrieves — text, two dates, an outlet and a tier.
"""

from __future__ import annotations

import datetime as dt
from typing import cast

import pandas as pd

from insight_copilot.datagen.corpus.models import Document, SourceTier
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

DEFAULT_NEWS_TIER: SourceTier = 4
"""Unverified secondary reporting, which is what an unlabelled news row is."""

DEFAULT_MEMO_TIER: SourceTier = 2
"""An internal memo is a primary record, but a partly manual one."""


def documents_from_warehouse(warehouse: Warehouse) -> list[Document]:
    """Every retrievable document in silver, as the evidence layer's model."""
    documents: list[Document] = []
    if warehouse.exists("silver", "news_articles"):
        documents.extend(_news(warehouse.query("SELECT * FROM silver.news_articles")))
    if warehouse.exists("silver", "pricing_memos"):
        documents.extend(_memos(warehouse.query("SELECT * FROM silver.pricing_memos")))
    documents.sort(key=lambda item: (item.publish_date, item.doc_id))
    logger.info("evals.corpus_loaded", documents=len(documents))
    return documents


def _news(frame: pd.DataFrame) -> list[Document]:
    """News rows. The syndication group survives projection, so dedup still works."""
    return [
        Document(
            doc_id=str(row.doc_id),
            kind="news_article",
            title=str(row.headline),
            body=str(row.body_text),
            publish_date=_as_date(row.publish_date),
            effective_date=_as_date(row.effective_date),
            source_tier=_tier(getattr(row, "source_tier", None), DEFAULT_NEWS_TIER),
            outlet=str(row.outlet) if row.outlet is not None else None,
            syndication_group=(
                str(row.syndication_group) if row.syndication_group is not None else None
            ),
            entities=_entities(row.entities),
        )
        for row in frame.itertuples()
    ]


def _memos(frame: pd.DataFrame) -> list[Document]:
    """Pricing and promo memos — the dual-date documents the timing gate exists for."""
    return [
        Document(
            doc_id=str(row.doc_id),
            kind="pricing_memo",
            title=str(row.memo_type),
            body=str(row.body_text),
            publish_date=_as_date(row.publish_date),
            effective_date=_as_date(row.effective_date),
            source_tier=_tier(getattr(row, "source_tier", None), DEFAULT_MEMO_TIER),
            author=str(row.author) if row.author is not None else None,
            scope_regions=_entities(row.scope_regions),
            scope_skus=_entities(row.scope_skus),
        )
        for row in frame.itertuples()
    ]


def _as_date(value: object) -> dt.date:
    """Whatever DuckDB handed back, as a date."""
    return pd.Timestamp(cast(str, value)).date()


def _tier(value: object, default: SourceTier) -> SourceTier:
    """A tier from the row, or the kind's default when the projection dropped it."""
    if value is None or not isinstance(value, (int, float, str)) or pd.isna(value):
        return default
    number = int(float(value))
    return cast(SourceTier, number) if 1 <= number <= 4 else default


def _entities(value: object) -> list[str]:
    """Entity lists arrive as a list, a delimited string, or nothing at all."""
    if value is None or isinstance(value, float):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    text = str(value).strip("[]{} ")
    return [part.strip().strip("'\"") for part in text.split(",") if part.strip()]
