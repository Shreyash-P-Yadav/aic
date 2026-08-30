"""Insights: the list, the card, the evidence drawer, and feedback.

Narratives are rendered **lazily and per persona**, cached on the bundle hash, because
a CFO and an analyst reading the same insight are two renderings of one computation
rather than two computations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from insight_copilot.api.deps import get_state
from insight_copilot.api.schemas import (
    FeedbackRequest,
    FeedbackResponse,
    InsightSummary,
    KpiSeriesResponse,
    NarrativeResponse,
)
from insight_copilot.api.state import AppState, InsightRecord
from insight_copilot.engine.bundle import AbstentionArtifact, InsightEvidenceBundle
from insight_copilot.errors import ResourceNotFound

router = APIRouter(tags=["insights"])


@router.get("/api/insights", response_model=list[InsightSummary])
async def list_insights(
    status: str | None = Query(default=None, pattern="^(published|abstained)$"),
    kpi: str | None = None,
    state: AppState = Depends(get_state),
) -> list[InsightSummary]:
    """Every produced output, newest first. Abstentions are first-class rows."""
    return [_summary(record) for record in state.list_insights(status=status, kpi_id=kpi)]


@router.get("/api/insights/{insight_id}")
async def get_insight(
    insight_id: str, state: AppState = Depends(get_state)
) -> InsightEvidenceBundle | AbstentionArtifact:
    """The whole object — every number the UI may render is inside it."""
    record = _find(state, insight_id)
    return record.bundle or record.abstention  # type: ignore[return-value]  # one is set


@router.get("/api/insights/{insight_id}/series", response_model=KpiSeriesResponse)
async def get_series(insight_id: str, state: AppState = Depends(get_state)) -> KpiSeriesResponse:
    """The KPI's history and the counterfactual it was judged against.

    A 404 rather than an empty series when none was attached: a chart of nothing is
    indistinguishable from a chart of a flat KPI, and the UI should say which it is.
    """
    record = _find(state, insight_id)
    if record.series is None:
        raise ResourceNotFound(
            "no series was attached to this insight",
            detail=f"{insight_id} was produced without one",
        )
    return record.series


@router.get("/api/insights/{insight_id}/narrative", response_model=NarrativeResponse)
async def get_narrative(
    insight_id: str,
    persona: str = Query(default="analyst"),
    state: AppState = Depends(get_state),
) -> NarrativeResponse:
    """Render for one persona, verifying every number before returning it."""
    record = _find(state, insight_id)
    if record.bundle is not None:
        narrative = state.narrator.narrate(record.bundle, persona)
    else:
        assert record.abstention is not None
        narrative = state.narrator.narrate_abstention(record.abstention, persona)
    record.narratives[persona] = narrative.text
    return NarrativeResponse(
        persona=narrative.persona,
        tier=narrative.tier,
        text=narrative.text,
        source=narrative.source,
        attempts=narrative.attempts,
        numbers_checked=len(narrative.numbers.numbers) if narrative.numbers else 0,
        numbers_unsupported=len(narrative.numbers.unsupported) if narrative.numbers else 0,
        faithfulness=narrative.faithfulness,
        cached=narrative.cached,
    )


@router.get("/api/insights/{insight_id}/evidence")
async def get_evidence(insight_id: str, state: AppState = Depends(get_state)) -> dict[str, object]:
    """The drawer: freshness, method, contribution, confidence and lineage."""
    record = _find(state, insight_id)
    source = record.bundle or record.abstention
    assert source is not None
    payload: dict[str, object] = {
        "insight_id": insight_id,
        "confidence": source.confidence.model_dump(mode="json"),
        "freshness": [item.model_dump(mode="json") for item in source.freshness],
    }
    if record.bundle is not None:
        payload.update(
            {
                "numbers": [item.model_dump(mode="json") for item in record.bundle.numbers],
                "segments": [item.model_dump(mode="json") for item in record.bundle.segments],
                "drivers": [item.model_dump(mode="json") for item in record.bundle.drivers],
                "documents": [item.model_dump(mode="json") for item in record.bundle.evidence],
                "lineage": [item.model_dump(mode="json") for item in record.bundle.lineage],
                "rejected_by_timing": record.bundle.evidence_rejected_by_timing,
                "explained_fraction": record.bundle.explained_fraction,
                "unexplained_fraction": record.bundle.unexplained_fraction,
            }
        )
    else:
        payload.update(
            {
                "what_is_known": record.abstention.what_is_known,  # type: ignore[union-attr]
                "failed_checks": record.abstention.failed_checks,  # type: ignore[union-attr]
                "missing_evidence": record.abstention.missing_evidence,  # type: ignore[union-attr]
                "retry_trigger": record.abstention.retry_trigger,  # type: ignore[union-attr]
            }
        )
    return payload


@router.post("/api/insights/{insight_id}/feedback", response_model=FeedbackResponse)
async def post_feedback(
    insight_id: str, payload: FeedbackRequest, state: AppState = Depends(get_state)
) -> FeedbackResponse:
    """Record a reader's reaction. This is the learning loop's only labelled input."""
    record = _find(state, insight_id)
    classified = state.classifier.classify(insight_id, payload.text)
    record.feedback.append(classified)
    return FeedbackResponse(
        insight_id=insight_id,
        label=classified.label,
        reason=classified.reason,
        method=classified.method,
    )


def _find(state: AppState, insight_id: str) -> InsightRecord:
    """One insight, or a typed error naming what exists."""
    try:
        return state.insights[insight_id]
    except KeyError as exc:
        raise ResourceNotFound(
            f"unknown insight {insight_id!r}",
            detail=f"{len(state.insights)} insight(s) available",
        ) from exc


def _summary(record: InsightRecord) -> InsightSummary:
    source = record.bundle or record.abstention
    headline = (
        record.abstention.headline
        if record.abstention is not None
        else f"{record.kpi_id} moved {record.delta_pct:+.2f}% against its counterfactual"
    )
    assert source is not None
    return InsightSummary(
        insight_id=record.insight_id,
        kpi_id=record.kpi_id,
        status=record.status,  # type: ignore[arg-type]  # Literal, one of two values
        tier=record.tier,
        delta_pct=record.delta_pct,
        created_at=record.created_at.isoformat(),
        headline=headline,
        impact=record.impact,
        unit=record.unit,
        top_segment=record.top_segment,
        spark=record.spark(),
    )
