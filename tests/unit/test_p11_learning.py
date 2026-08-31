"""P11 — the learning loop: feedback store, ranker gating, tuning gate, case library.

The behaviour these tests protect is *restraint*: a ranker that trains on too few
labels, or a tuning loop that applies a change the eval suite did not endorse, is worse
than no learning at all because it looks like progress.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from insight_copilot.learning.case_library import Case, CaseLibrary
from insight_copilot.learning.ranker import (
    MIN_LABELS_FOR_MODEL,
    PriorityRanker,
    RankableInsight,
)
from insight_copilot.learning.store import FeedbackRecord, FeedbackStore
from insight_copilot.learning.tuning import (
    MIN_RECORDS_TO_TUNE,
    TuningProposal,
    apply_if_improved,
    propose,
)


def _record(index: int, label: str = "useful", **overrides: object) -> FeedbackRecord:
    """One feedback record with plausible, varying features."""
    payload: dict[str, object] = {
        "insight_id": f"INS-{index:04d}",
        "kpi_id": "net_revenue",
        "label": label,
        "tier": "Moderate",
        "delta_pct": -5.0 - index % 17,
        "impact_inr": 1e6 * (1 + index % 11),
        "confidence": 0.4 + (index % 5) / 10.0,
    }
    payload.update(overrides)
    return FeedbackRecord.model_validate(payload)


def test_store_round_trips_and_supersedes(tmp_path: Path) -> None:
    """A later correction on the same insight supersedes the earlier one for training."""
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    store.append(_record(1, "wrong_cause"))
    store.append(_record(1, "useful"))
    assert len(store.all()) == 2, "both reactions stay on disk; the history is auditable"
    latest = store.latest_per_insight()
    assert len(latest) == 1
    assert latest["INS-0001"].label == "useful"
    assert store.label_counts() == {"useful": 1}


def test_ranker_stays_on_rules_below_the_label_floor(tmp_path: Path) -> None:
    """The gate the P11 spec names by name: no model below the threshold."""
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    for index in range(MIN_LABELS_FOR_MODEL - 1):
        store.append(_record(index, "useful" if index % 2 else "wrong_cause"))
    ranker = PriorityRanker(store)
    assert ranker.status.trained is False
    assert "below the" in ranker.status.reason


def test_ranker_trains_once_the_corpus_is_large_and_balanced(tmp_path: Path) -> None:
    """Above the floor, with both classes present, the learned ranker takes over."""
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    for index in range(MIN_LABELS_FOR_MODEL + 20):
        store.append(_record(index, "useful" if index % 3 else "not_material"))
    ranker = PriorityRanker(store)
    assert ranker.status.trained is True, ranker.status.reason
    assert ranker.status.positives > 0 and ranker.status.negatives > 0


def test_ranker_reverts_to_rules_when_labels_go_stale(tmp_path: Path) -> None:
    """A model trained on a world nobody has confirmed in a quarter is reverted."""
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=200)
    for index in range(MIN_LABELS_FOR_MODEL + 20):
        store.append(_record(index, "useful" if index % 3 else "not_material", recorded_at=old))
    ranker = PriorityRanker(store)
    assert ranker.status.trained is False
    assert "staleness" in ranker.status.reason


def test_a_seeded_correction_changes_the_next_run_ranking(tmp_path: Path) -> None:
    """The demonstration the P11 gate asks for, as a test rather than a claim.

    Two insights are ranked by the rules. Corrections then arrive saying the *smaller*
    movement is the one readers act on, and the trained ranker reorders accordingly.
    """
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    big = RankableInsight(
        insight_id="BIG", impact_inr=9e7, calibrated=0.5, tier="Low", delta_pct=-80.0
    )
    small = RankableInsight(
        insight_id="SMALL", impact_inr=2e6, calibrated=0.9, tier="High", delta_pct=-4.0
    )
    before = PriorityRanker(store).rank([big, small])
    assert before[0].insight_id == "BIG", "with no labels, the rules lead on magnitude"

    for index in range(MIN_LABELS_FOR_MODEL + 20):
        # Readers consistently find the confident, small, High-tier movements useful
        # and the loud low-confidence ones not material.
        loud = index % 2 == 0
        store.append(
            _record(
                index,
                "not_material" if loud else "useful",
                tier="Low" if loud else "High",
                delta_pct=-80.0 if loud else -4.0,
                impact_inr=9e7 if loud else 2e6,
                confidence=0.5 if loud else 0.9,
            )
        )
    after = PriorityRanker(store).rank([big, small])
    assert after[0].insight_id == "SMALL", "the correction changed the next run's ranking"


def test_tuning_needs_enough_records_and_a_real_complaint_rate() -> None:
    """No proposal from a thin corpus, and none when the named cause is not disputed."""
    assert propose([_record(i) for i in range(5)], stability_floor=0.9, tier4_weight=0.4) == []
    contented = [_record(i, "useful") for i in range(MIN_RECORDS_TO_TUNE + 5)]
    assert propose(contented, stability_floor=0.9, tier4_weight=0.4) == []


def test_tuning_proposes_only_thresholds_never_numbers() -> None:
    """Feedback may move a threshold for speaking. It may never move an estimate."""
    disputed = [
        _record(i, "wrong_cause" if i % 2 else "useful") for i in range(MIN_RECORDS_TO_TUNE + 5)
    ]
    proposals = propose(disputed, stability_floor=0.90, tier4_weight=0.40)
    assert {item.knob for item in proposals} == {
        "attribution.stability_floor",
        "evidence.source_tier_4_weight",
    }
    assert all(item.is_change for item in proposals)


def test_a_proposal_that_regresses_the_guard_metric_is_rejected() -> None:
    """The eval gate over the learning loop, in one assertion."""
    proposal = TuningProposal(
        knob="attribution.stability_floor",
        current=0.90,
        proposed=0.92,
        rationale="test",
        guard_metric="attribution_accuracy",
    )
    accepted, rejected = apply_if_improved(
        [proposal],
        before={"attribution_accuracy": 0.31},
        after={"attribution_accuracy": 0.25},
    )
    assert accepted == []
    assert "fell from" in rejected[0]

    accepted, rejected = apply_if_improved(
        [proposal],
        before={"attribution_accuracy": 0.31},
        after={"attribution_accuracy": 0.31},
    )
    assert accepted == [proposal], "holding steady is enough; only a regression is rejected"
    assert rejected == []


def test_case_library_finds_the_comparable_movement() -> None:
    """Same segment, same direction, similar magnitude, similar season ranks first."""
    library = CaseLibrary(
        [
            Case(
                insight_id="C1",
                kpi_id="net_revenue",
                day=dt.date(2025, 3, 10),
                delta_pct=-12.0,
                segment="region=North",
                cause="DC-North pick capacity",
                resolution="volume reallocated to DC-West",
                days_to_resolve=11,
            ),
            Case(
                insight_id="C2",
                kpi_id="net_revenue",
                day=dt.date(2025, 9, 2),
                delta_pct=+14.0,
                segment="region=West",
                cause="festive pull-forward",
            ),
        ]
    )
    query = Case(
        insight_id="NEW",
        kpi_id="net_revenue",
        day=dt.date(2026, 3, 12),
        delta_pct=-11.5,
        segment="region=North",
    )
    neighbours = library.similar(query, limit=2)
    assert neighbours[0].case.insight_id == "C1"
    assert neighbours[0].similarity > neighbours[1].similarity
    assert "segment" in neighbours[0].detail


def test_case_library_never_returns_the_query_itself() -> None:
    """A movement is not its own precedent."""
    case = Case(
        insight_id="C1",
        kpi_id="net_revenue",
        day=dt.date(2025, 3, 10),
        delta_pct=-12.0,
        segment="region=North",
    )
    assert CaseLibrary([case]).similar(case) == []


@pytest.mark.parametrize("label", ["useful", "already_known", "wrong_cause", "not_material"])
def test_every_label_round_trips(tmp_path: Path, label: str) -> None:
    """All four labels persist and read back — the ranker's target depends on it."""
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    store.append(_record(1, label))
    assert store.all()[0].label == label
