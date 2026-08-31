"""Building the corpus from the event ledger.

Every document exists because an event caused it, so the text is causally consistent
with the numbers by construction. The **absence** of documents is designed too: about
15% of events get none at all, and those are exactly the cases where attribution is
statistically strong but externally uncorroborated — where confidence should fall and
sometimes where the engine should abstain. Without them the sufficiency check is never
exercised.

The composition rules from DataLayer §6.2, all enforced here and asserted by the gate:

| Rule | Target |
|---|---|
| Events with no document at all | ~15% |
| Events with contradictory pairs | ~10% |
| Syndication of a significant news item | 3-6 outlets |
| Effective date materially later than publish | ~20% |
| Post-dated decoys | ~8% |
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from insight_copilot.datagen.corpus import templates
from insight_copilot.datagen.corpus.models import Document
from insight_copilot.datagen.corpus.pii import PersonGenerator
from insight_copilot.datagen.corpus.routine import weekly_reviews
from insight_copilot.datagen.events.ledger import EventLedger
from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.projection.competitor import COMPETITORS
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

DECOY_LAG_DAYS = 4
"""How far a post-dated decoy follows the effect it appears to explain."""

WEEKLY_REVIEW_EVERY_DAYS = 7
CONTRADICTION_LAG_DAYS = 1
"""A supplier email arriving the day after an ops ticket says the issue is resolved."""


def _ticket_reference(event: Event) -> str:
    """A stable ops-ticket reference derived from the event id.

    ``blake2b`` rather than ``hash()``: Python randomises string hashing per process,
    so a corpus built twice would carry different ticket numbers for the same event
    and the committed fixtures would never match.
    """
    from hashlib import blake2b

    digest = blake2b(event.event_id.encode(), digest_size=2).hexdigest()
    return f"OPS-{event.window.start.strftime('%y%m')}-{int(digest, 16) % 9000 + 1000}"


class CorpusBuilder:
    """Turns an event ledger into a document corpus."""

    def __init__(self, config: WorldConfig, ledger: EventLedger, seeds: SeedBook) -> None:
        self._config = config
        self._ledger = ledger
        self._seeds = seeds
        self._people = PersonGenerator(seeds)

    def build(self) -> list[Document]:
        """Every document, in publication order."""
        documents: list[Document] = []
        for event in self._ledger:
            documents.extend(self._for_event(event))
        documents.extend(weekly_reviews(self._config, self._seeds, self._people))
        documents.sort(key=lambda item: (item.publish_date, item.doc_id))
        logger.info("corpus.built", documents=len(documents))
        return documents

    # ------------------------------------------------------------ per event --
    def _for_event(self, event: Event) -> list[Document]:
        """Documents describing one event. May be empty — that is the design.

        Priority order matters. The contradiction and the decoy are the documents the
        engine is being *tested* on; syndication is volume. Building syndication first
        and truncating to the evidence budget would quietly drop the two document
        types the timing gate and the agreement check exist to handle — which is what
        the first version of this did, leaving 6 decoys in the corpus for 29 events
        that were supposed to carry one.
        """
        wanted = event.evidence.documents
        if wanted == 0:
            return []

        rng = self._seeds("corpus_event", event.event_id)
        documents: list[Document] = []
        primary = self._primary_document(event, rng)
        if primary is not None:
            documents.append(primary)
        if event.evidence.contradiction and primary is not None:
            documents.append(self._contradiction(event, primary, rng))
        if event.evidence.post_dated_decoy:
            documents.append(self._decoy(event, rng))

        # Only a *significant* story gets syndicated across outlets, and only into
        # whatever evidence budget is left. Syndicating every routine calibration
        # event would triple the corpus for no analytical gain.
        remaining = wanted - len(documents)
        if remaining > 0 and event.evidence.syndication > 1 and self._is_significant(event):
            documents.extend(self._syndicate(event, rng, limit=remaining))
        return documents

    def _is_significant(self, event: Event) -> bool:
        """Would the trade press actually have picked this up?

        The demo scenarios always; otherwise only a minority of the large events. Most
        things that move a category do not make the trade press, and syndicating every
        high-detectability calibration event would put the corpus at three times the
        volume the design calls for while adding nothing the dedup test needs.
        """
        if event.is_scenario:
            return True
        if event.detectability != "high":
            return False
        return bool(self._seeds("corpus_newsworthy", event.event_id).random() < 0.22)

    def _primary_document(self, event: Event, rng: np.random.Generator) -> Document | None:
        """The document a person would actually have written about this event."""
        # Narrow on the magnitude itself. Copying `.kind` into a separate variable
        # reads the same but defeats the discriminated union: the type checker can
        # only narrow the object it sees tested.
        magnitude = event.magnitude
        author_key = event.event_id
        author = self._people.name(author_key)
        email = self._people.email(author_key)
        effective = self._effective_date(event, rng)

        if magnitude.kind == "outage":
            warehouse = event.scope.warehouses[0] if event.scope.warehouses else "DC-North"
            alternate = next(item.id for item in self._config.warehouses if item.id != warehouse)
            title_template, body_template = templates.OPS_INCIDENT[
                int(rng.integers(0, len(templates.OPS_INCIDENT)))
            ]
            capacity = round(magnitude.pick_capacity * 100)
            fields = {
                "severity": "P1" if capacity < 60 else "P2",
                "warehouse": warehouse,
                "summary": "conveyor line failure affecting outbound picking",
                "publish_date": event.window.start.isoformat(),
                "start_date": event.window.start.isoformat(),
                "capacity_pct": capacity,
                "alternate": alternate,
                "author": author,
                "email": email,
                "ticket": _ticket_reference(event),
            }
            return self._document(
                event=event,
                kind="ops_incident",
                title=title_template.format(**fields),
                body=body_template.format(**fields),
                publish=event.window.start,
                effective=event.window.start,
                tier=1,
                author=author,
                suffix="ops",
            )

        if magnitude.kind == "price_change":
            category = event.scope.categories[0] if event.scope.categories else "Haircare"
            change = magnitude.price_multiplier - 1.0
            title_template, body_template = templates.PRICING_MEMO[0 if change > 0 else 1]
            publish = event.window.start - dt.timedelta(
                days=event.evidence.effective_date_offset_days
            )
            fields = {
                "category": category,
                "effective_date": event.window.start.isoformat(),
                "publish_date": publish.isoformat(),
                "change_pct": f"{change:+.1%}",
                "regions": ", ".join(event.scope.regions) or "all regions",
                "author": author,
                "email": email,
            }
            return self._document(
                event=event,
                kind="pricing_memo",
                title=title_template.format(**fields),
                body=body_template.format(**fields),
                publish=publish,
                effective=event.window.start,
                tier=2,
                author=author,
                suffix="memo",
            )

        if magnitude.kind == "media_shift":
            channel = event.scope.media_channels[0] if event.scope.media_channels else "paid_social"
            change = magnitude.spend_multiplier - 1.0
            title_template, body_template = templates.CAMPAIGN_BRIEF[
                int(rng.integers(0, len(templates.CAMPAIGN_BRIEF)))
            ]
            fields = {
                "channel": channel.replace("_", " "),
                "change_pct": f"{change:+.0%}",
                "effective_date": event.window.start.isoformat(),
                "publish_date": event.window.start.isoformat(),
                "reason": str(
                    rng.choice(
                        [
                            "quarterly efficiency pilot",
                            "budget reallocation to search",
                            "creative refresh pause",
                        ]
                    )
                ),
                "author": author,
                "email": email,
            }
            return self._document(
                event=event,
                kind="campaign_brief",
                title=title_template.format(**fields),
                body=body_template.format(**fields),
                publish=event.window.start,
                effective=event.window.start,
                tier=2,
                author=author,
                suffix="brief",
            )

        if magnitude.kind == "demand_shock":
            return self._news(event, rng, outlet_index=0, effective=effective)

        return None

    def _news(
        self,
        event: Event,
        rng: np.random.Generator,
        *,
        outlet_index: int,
        effective: dt.date,
        publish: dt.date | None = None,
        decoy: bool = False,
    ) -> Document:
        """One outlet's version of a story."""
        category = event.scope.categories[0] if event.scope.categories else "Haircare"
        competitor = COMPETITORS[int(rng.integers(0, len(COMPETITORS)))]
        outlet = templates.OUTLETS[outlet_index % len(templates.OUTLETS)]
        title_template, body_template = templates.NEWS_ARTICLE[
            outlet_index % len(templates.NEWS_ARTICLE)
        ]
        published = publish or event.window.start
        fields = {
            "competitor": competitor,
            "category": category,
            "outlet": outlet,
            "publish_date": published.isoformat(),
            "effective_date": effective.isoformat(),
        }
        return self._document(
            event=event,
            kind="news_article",
            title=title_template.format(**fields),
            body=body_template.format(**fields),
            publish=published,
            effective=effective,
            # Syndicated rewrites are less authoritative than the first report.
            tier=3 if outlet_index == 0 else 4,
            outlet=outlet,
            suffix=f"news{outlet_index}",
            syndication_group=f"SYN-{event.event_id}",
            decoy=decoy,
        )

    def _syndicate(self, event: Event, rng: np.random.Generator, *, limit: int) -> list[Document]:
        """The same story rewritten across three to six outlets.

        Every copy carries the same ``syndication_group``. If ingestion-time dedup
        fails to collapse them, noisy-OR corroboration treats one press release as six
        independent confirmations — which is the exact failure this exists to test.
        """
        copies = min(max(event.evidence.syndication, 3), 6)
        effective = self._effective_date(event, rng)
        return [
            self._news(event, rng, outlet_index=index, effective=effective)
            for index in range(1, min(copies, limit + 1))
        ]

    def _contradiction(self, event: Event, primary: Document, rng: np.random.Generator) -> Document:
        """A supplier email that disagrees with the incident record."""
        category = event.scope.categories[0] if event.scope.categories else "Haircare"
        author = self._people.name(f"{event.event_id}-supplier")
        title_template, body_template = templates.SUPPLIER_EMAIL[0]
        publish = primary.publish_date + dt.timedelta(days=CONTRADICTION_LAG_DAYS)
        fields = {
            "category": category,
            "author": author,
            "email": self._people.email(f"{event.event_id}-supplier"),
            "publish_date": publish.isoformat(),
            "effective_date": (publish + dt.timedelta(days=int(rng.integers(3, 12)))).isoformat(),
        }
        return self._document(
            event=event,
            kind="supplier_email",
            title=title_template.format(**fields),
            body=body_template.format(**fields),
            publish=publish,
            effective=publish,
            tier=2,
            author=author,
            suffix="contra",
            contradicts=primary.doc_id,
        )

    def _decoy(self, event: Event, rng: np.random.Generator) -> Document:
        """A dramatic, topically relevant document dated AFTER the effect.

        The timing gate's job is to eliminate it. Making it plausible and widely
        repeated is the point: a decoy nobody would believe tests nothing.
        """
        publish = event.window.end + dt.timedelta(days=DECOY_LAG_DAYS)
        return self._news(
            event,
            rng,
            outlet_index=0,
            effective=publish,
            publish=publish,
            decoy=True,
        )

    # -------------------------------------------------------------- helpers --
    def _effective_date(self, event: Event, rng: np.random.Generator) -> dt.date:
        """When what the document describes actually takes effect."""
        del rng
        return event.window.start + dt.timedelta(days=event.evidence.effective_date_offset_days)

    def _document(
        self,
        *,
        event: Event,
        kind: str,
        title: str,
        body: str,
        publish: dt.date,
        effective: dt.date,
        tier: int,
        suffix: str,
        author: str | None = None,
        outlet: str | None = None,
        syndication_group: str | None = None,
        contradicts: str | None = None,
        decoy: bool = False,
    ) -> Document:
        """Assemble a document with a stable, content-derived id."""
        return Document(
            doc_id=f"DOC-{event.event_id}-{suffix}",
            kind=kind,  # type: ignore[arg-type]  # from the DocumentKind literals
            title=title,
            body=body,
            publish_date=publish,
            effective_date=effective,
            source_tier=tier,  # type: ignore[arg-type]  # 1..4
            outlet=outlet,
            author=author,
            event_id=event.event_id,
            syndication_group=syndication_group,
            contradicts=contradicts,
            is_post_dated_decoy=decoy,
            scope_skus=list(event.scope.skus),
            scope_regions=list(event.scope.regions),
            entities=[*event.scope.categories, *event.scope.regions, *event.scope.warehouses],
        )
