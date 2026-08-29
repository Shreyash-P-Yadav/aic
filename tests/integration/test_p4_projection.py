"""P4 gate — source projection, the defect catalog, and the corpus.

The catalog's contract is **present AND detectable**. A defect that exists but cannot
be found is worthless: it would flatter the engine by existing without ever being
caught. So every one of the thirty-one pathologies gets an assertion that a detector
actually finds it in the generated data.
"""

from __future__ import annotations

import pytest

from insight_copilot.datagen.corpus.pii import (
    EMAIL_DOMAINS,
    contains_real_looking_identifier,
)
from insight_copilot.datagen.defects.base import build_catalog
from insight_copilot.datagen.pipeline import GeneratedWorld

CATALOG_CODES = build_catalog().codes


# ============================================================== projection ====
def test_every_built_source_is_projected(world: GeneratedWorld) -> None:
    """Nine tabular sources plus the two corpus-only ones."""
    assert set(world.frames.source_ids) == {
        "oms_orders",
        "wms_fulfilment",
        "martech_weekly",
        "support_tickets",
        "competitor_prices",
        "pim_products",
        "inventory_snapshots",
        "weather_daily",
        "holiday_calendar",
        "news_articles",
        "pricing_memos",
    }


def test_every_projection_matches_its_source_contract(world: GeneratedWorld) -> None:
    """Columns exactly as declared — no extras, none missing.

    Checked at generation time by `SourceProjector.validate`; asserted here so a
    projector that drifts from its contract fails in the gate rather than at
    ingestion, where the symptom would be a DQ failure with a confusing cause.
    """
    from insight_copilot.contracts.registry import ContractRegistry
    from insight_copilot.datagen.pipeline import _contracts_dir

    registry = ContractRegistry.from_directory(_contracts_dir())
    for source_id in world.frames.source_ids:
        declared = set(registry.source(source_id).schema_spec.columns)
        assert set(world.frames[source_id].columns) == declared, source_id


@pytest.mark.parametrize(
    "check",
    [
        "oms_units_vs_wms_units",
        "martech_attributed_vs_oms_linked",
        "inventory_snapshot_vs_implied",
        "competitor_match_confidence",
    ],
)
def test_reconciliation_deltas_fall_in_their_designed_ranges(
    world: GeneratedWorld, check: str
) -> None:
    """Each disagreement is where the design says it should be.

    The engine is expected to *live with* the normal range and to abstain only when a
    check exceeds its contract tolerance. A disagreement outside its designed range
    would make that distinction meaningless.
    """
    delta = next(item for item in world.reconciliations if item.name == check)
    assert delta.in_designed_range, (
        f"{check}: median {delta.median_pct:.2f}% outside {delta.designed_range}"
    )


def test_martech_holds_only_twelve_months_of_history(world: GeneratedWorld) -> None:
    """Retention caps this feed, so models using spend have a shorter usable window."""
    weeks = world.frames["martech_weekly"]["iso_week"].nunique()
    total_weeks = len({str(label) for label in world.simulator.calendar.iso_week})
    assert weeks < total_weeks, "MarTech history is not capped at all"


# ================================================== the defect catalog ========
def test_the_catalog_covers_every_pathology_in_the_design(world: GeneratedWorld) -> None:
    """P1 to P30, with P6 split into its two forms as the design does."""
    codes = world.catalog.codes
    assert len(codes) == 31
    assert codes[0] == "P1"
    assert codes[-1] == "P30"
    assert {"P6a", "P6b"} <= set(codes)


@pytest.mark.parametrize("code", CATALOG_CODES)
def test_defect_is_present_and_detectable(world: GeneratedWorld, code: str) -> None:
    """One test per pathology. This is the gate's core assertion."""
    evidence = world.catalog.get(code).detect(world.frames, world.context)
    assert evidence.present, f"{code} not detected: {evidence.detail}"


def test_the_silent_unit_change_is_caught_by_a_range_expectation(
    world: GeneratedWorld,
) -> None:
    """P8, named explicitly. The scariest defect in the catalog.

    A hundredfold jump in every spend figure, with no schema change and no error.
    Every chart still renders. The only thing that catches it is the `max` range
    expectation on `spend_inr` in the source contract — which is why every numeric
    column in every source contract carries one.
    """
    evidence = world.catalog.get("P8").detect(world.frames, world.context)
    assert evidence.present
    assert evidence.metrics["ratio"] > 50.0, "the unit change is not a 100x jump"
    assert evidence.metrics["rows_over_contract_max"] > 0, (
        "no row breaches the contract's declared maximum, so a DQ gate would miss it"
    )


def test_the_silent_unit_change_is_injected_not_incidental(
    world: GeneratedWorld, clean_world: GeneratedWorld
) -> None:
    """With the injectors off, the jump must be absent.

    Without this, a pathology that happened to be a property of the world would pass
    its own test and the catalog would be measuring nothing.
    """
    injected = world.catalog.get("P8").detect(world.frames, world.context)
    clean = clean_world.catalog.get("P8").detect(clean_world.frames, clean_world.context)
    assert injected.present
    assert not clean.present


def test_syndication_is_present_and_collapses_on_its_dedup_key(
    world: GeneratedWorld,
) -> None:
    """P26, named explicitly. The corroboration trap.

    If ingestion-time dedup fails, noisy-OR treats one press release across six
    outlets as six independent confirmations, and confidence is inflated precisely on
    the stories that are most widely repeated. The test asserts both halves: the
    duplicates exist, and the syndication key collapses them.
    """
    news = world.frames["news_articles"]
    sizes = news.groupby("syndication_group", observed=True).size()
    syndicated = sizes.loc[sizes > 1]

    assert len(syndicated) >= 5, "not enough syndicated stories to test dedup"
    assert sizes.max() >= 3, "no story appears across three or more outlets"
    assert news["syndication_group"].nunique() < len(news), (
        "the dedup key does not collapse anything"
    )

    # And the copies must be genuinely different text, or dedup would be trivial.
    group = syndicated.index[0]
    copies = news.loc[news["syndication_group"] == group, "headline"]
    assert copies.nunique() > 1, "syndicated copies are byte-identical, which is too easy"


# ========================================================= the corpus =========
def test_corpus_size_is_in_the_designed_band(world: GeneratedWorld) -> None:
    assert 600 <= len(world.documents) <= 800


def test_about_fifteen_percent_of_events_get_no_document(world: GeneratedWorld) -> None:
    """The deliberate evidence gaps — what makes the sufficiency check real.

    These are the cases where attribution is statistically strong but externally
    uncorroborated: exactly where confidence should fall and sometimes where the
    engine should abstain. Without them the sufficiency check is never exercised.
    """
    mechanical = [event for event in world.ledger if event.magnitude.kind != "none"]
    documented = {document.event_id for document in world.documents if document.event_id}
    gap_rate = 1.0 - len(documented) / len(mechanical)
    assert 0.10 <= gap_rate <= 0.22, f"evidence-gap rate {gap_rate:.1%}, design target ~15%"


def test_contradictory_pairs_exist(world: GeneratedWorld) -> None:
    """A ticket and a supplier email that disagree, for the hedged-tier case."""
    contradictions = [item for item in world.documents if item.contradicts]
    assert len(contradictions) >= 15
    ids = {item.doc_id for item in world.documents}
    for document in contradictions:
        assert document.contradicts in ids, "a contradiction points at no document"


def test_post_dated_decoys_exist_and_post_date_their_events(world: GeneratedWorld) -> None:
    """P29's corpus half: the timing gate's test cases."""
    decoys = [item for item in world.documents if item.is_post_dated_decoy]
    assert len(decoys) >= 15
    by_id = {event.event_id: event for event in world.ledger}
    for decoy in decoys:
        event = by_id[str(decoy.event_id)]
        assert decoy.publish_date > event.window.end, f"{decoy.doc_id} does not post-date its event"


def test_dual_dates_diverge_on_about_a_fifth_of_news_and_memos(
    world: GeneratedWorld,
) -> None:
    """A February memo effective in April cannot be found by publish date alone."""
    relevant = [item for item in world.documents if item.kind in {"news_article", "pricing_memo"}]
    diverging = [item for item in relevant if item.dates_diverge]
    rate = len(diverging) / len(relevant)
    assert 0.12 <= rate <= 0.35, f"dual-date rate {rate:.1%}, design target ~20%"


def test_documents_are_causally_consistent_with_the_ledger(world: GeneratedWorld) -> None:
    """A document referencing an event exists only if that event is in the ledger."""
    known = {event.event_id for event in world.ledger}
    for document in world.documents:
        if document.event_id is not None:
            assert document.event_id in known, document.doc_id


# ============================================================ PII =============
def test_no_document_contains_a_real_looking_personal_identifier(
    world: GeneratedWorld,
) -> None:
    """Every name, email and phone number is synthetic and from a reserved pattern.

    This matters twice: ethically, because a repository that might be shared must not
    contain anything resembling a real person's data; and demonstrably, because the
    masking story is only credible if the generator is disciplined.
    """
    for document in world.documents:
        for field in (document.title, document.body, document.author or ""):
            offender = contains_real_looking_identifier(field)
            assert offender is None, f"{document.doc_id}: {offender!r}"


def test_no_ticket_contains_a_real_looking_personal_identifier(
    world: GeneratedWorld,
) -> None:
    """Same rule for the structured PII fields the tickets carry."""
    tickets = world.frames["support_tickets"]
    for column in ("body_text", "customer_email", "customer_phone", "customer_name"):
        for value in tickets[column].astype(str).head(5000):
            offender = contains_real_looking_identifier(value)
            assert offender is None, f"{column}: {offender!r}"


def test_every_synthetic_email_uses_a_reserved_domain(world: GeneratedWorld) -> None:
    """RFC 2606 reserved domains only, so nothing can reach a real inbox."""
    emails = world.frames["support_tickets"]["customer_email"].astype(str)
    domains = {value.rsplit("@", 1)[-1] for value in emails.head(5000)}
    assert domains <= set(EMAIL_DOMAINS), (
        f"unexpected domains: {sorted(domains - set(EMAIL_DOMAINS))}"
    )


def test_pii_is_present_at_all(world: GeneratedWorld) -> None:
    """Masking a corpus with no PII in it would prove nothing."""
    bodies = world.frames["support_tickets"]["body_text"].astype(str).head(3000)
    assert bodies.str.contains("@", regex=False).sum() > 0
