"""Routine documents that exist regardless of what happened.

Weekly business reviews are written whether or not anything went wrong, and a handful
of them contain confidently wrong explanations. That is good demo material rather than
filler: the engine's evidence disagrees with the human narrative, and it says so
instead of deferring to the most senior opinion in the room.
"""

from __future__ import annotations

import datetime as dt

from insight_copilot.datagen.corpus import templates
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.datagen.corpus.pii import PersonGenerator
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

WEEKLY_REVIEW_EVERY_DAYS = 7


# ------------------------------------------------------------- routine ---
def weekly_reviews(config: WorldConfig, seeds: SeedBook, people: PersonGenerator) -> list[Document]:
    """Internal weekly reviews, a handful of them confidently wrong.

    Good demo material: the engine's evidence disagrees with the human narrative
    and says so, rather than deferring to the most senior opinion in the room.
    """
    horizon = config.horizon
    documents: list[Document] = []
    day = horizon.start
    index = 0
    while day <= horizon.end:
        rng = seeds("weekly_review", index)
        author = people.name(f"review-{index}")
        claim = templates.WEEKLY_REVIEW_CLAIMS[
            int(rng.integers(0, len(templates.WEEKLY_REVIEW_CLAIMS)))
        ]
        title_template, body_template = templates.WEEKLY_REVIEW[0]
        fields = {
            "publish_date": day.isoformat(),
            "author": author,
            "headline_claim": claim,
        }
        documents.append(
            Document(
                doc_id=f"DOC-REV-{index:04d}",
                kind="weekly_review",
                title=title_template.format(**fields),
                body=body_template.format(**fields),
                publish_date=day,
                effective_date=day,
                source_tier=3,
                author=author,
            )
        )
        day += dt.timedelta(days=WEEKLY_REVIEW_EVERY_DAYS)
        index += 1
    return documents
