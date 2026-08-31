"""Turning the corpus into the two corpus-only source frames.

`news_articles` and `pricing_memos` are sources like any other: they have source
contracts, they land in the landing zone, and they go through ingestion. This module
is the boundary between "the corpus as documents" and "the corpus as two feeds", and
it lives apart from `assemble.py` because the two answer different questions.
"""

from __future__ import annotations

import pandas as pd

from insight_copilot.datagen.corpus.models import Document


def to_news_frame(documents: list[Document]) -> pd.DataFrame:
    """The `news_articles` source frame."""
    rows = [
        {
            "doc_id": document.doc_id,
            "outlet": document.outlet or "",
            "headline": document.title,
            "body_text": document.body,
            "publish_date": document.publish_date,
            "effective_date": document.effective_date,
            "entities": "|".join(document.entities),
            "source_tier": document.source_tier,
            "syndication_group": document.syndication_group or document.doc_id,
        }
        for document in documents
        if document.kind == "news_article"
    ]
    return pd.DataFrame(rows)


def to_memo_frame(documents: list[Document]) -> pd.DataFrame:
    """The `pricing_memos` source frame — memos, briefs, emails and reviews."""
    kinds = {"pricing_memo", "campaign_brief", "supplier_email", "weekly_review", "ops_incident"}
    memo_type = {
        "pricing_memo": "price_change",
        "campaign_brief": "campaign_brief",
        "supplier_email": "supplier_note",
        "weekly_review": "weekly_review",
        "ops_incident": "supplier_note",
    }
    rows = [
        {
            "doc_id": document.doc_id,
            "memo_type": memo_type[document.kind],
            "author": document.author or "",
            "body_text": document.body,
            "publish_date": document.publish_date,
            "effective_date": document.effective_date,
            # Missing end dates are a real defect, not an omission: the planning tool
            # lets a promo be entered without one and nobody goes back to fix it.
            "end_date": None,
            "scope_skus": "|".join(document.scope_skus),
            "scope_regions": "|".join(document.scope_regions),
            "source_tier": document.source_tier,
        }
        for document in documents
        if document.kind in kinds
    ]
    return pd.DataFrame(rows)
