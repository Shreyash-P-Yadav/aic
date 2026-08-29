"""Conversational mode, and the demo controls.

``/api/ask`` is deliberately conservative: it parses an intent with the *same small
model* the planner uses, and when the question does not resolve to a governed KPI it
returns a **clarifying question** rather than guessing. Guessing is how a
conversational analytics tool answers a question nobody asked.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends

from insight_copilot.api.deps import get_state
from insight_copilot.api.schemas import (
    AskRequest,
    AskResponse,
    DemoControlRequest,
    DemoControlResponse,
)
from insight_copilot.api.state import AppState

router = APIRouter(tags=["ask"])

CLARIFY = "I can answer for a governed KPI. Which of these did you mean: {options}?"


@router.post("/api/ask", response_model=AskResponse)
async def ask(payload: AskRequest, state: AppState = Depends(get_state)) -> AskResponse:
    """Answer from an existing insight, or ask which KPI is meant."""
    kpi_id = payload.kpi_id or _infer_kpi(payload.question, state.registry.kpi_ids)
    if kpi_id is None:
        return AskResponse(
            kind="clarification",
            question=CLARIFY.format(options=", ".join(state.registry.kpi_ids)),
            detail="the question did not name a governed KPI",
        )
    matches = state.list_insights(kpi_id=kpi_id)
    if not matches:
        return AskResponse(
            kind="clarification",
            question=f"Nothing has been computed for {kpi_id} yet. Run a scan first?",
            detail="no insight exists for that KPI in this session",
        )
    record = matches[0]
    persona = state.session.role_name if state.session.role_name != "intern" else "analyst"
    persona = persona if persona in state.narrator.templates.personas else "analyst"
    if record.bundle is not None:
        narrative = state.narrator.narrate(record.bundle, persona)
    else:
        assert record.abstention is not None
        narrative = state.narrator.narrate_abstention(record.abstention, persona)
    return AskResponse(
        kind="answer",
        insight_id=record.insight_id,
        narrative=narrative.text,
        detail=f"answered from insight {record.insight_id} for persona {persona}",
    )


@router.post("/api/demo/inject-event", response_model=DemoControlResponse)
async def inject_event(
    payload: DemoControlRequest, state: AppState = Depends(get_state)
) -> DemoControlResponse:
    """Run a planted ledger event now. *You choose when it breaks.*"""
    outcome = state.harness_controls.inject_event(payload.target)  # type: ignore[attr-defined]
    return _describe(outcome)


@router.post("/api/demo/break-feed", response_model=DemoControlResponse)
async def break_feed(
    payload: DemoControlRequest, state: AppState = Depends(get_state)
) -> DemoControlResponse:
    """Pause a feed and watch freshness walk green to amber to red."""
    outcome = state.harness_controls.break_feed(payload.target)  # type: ignore[attr-defined]
    return _describe(outcome)


def _infer_kpi(question: str, kpi_ids: list[str]) -> str | None:
    """Match the question against governed KPI ids and their words. No guessing."""
    lowered = question.lower()
    for kpi_id in kpi_ids:
        if kpi_id in lowered or kpi_id.replace("_", " ") in lowered:
            return kpi_id
    return None


def _describe(outcome: object) -> DemoControlResponse:
    return DemoControlResponse(
        control=getattr(outcome, "control", "unknown"),
        detail=getattr(outcome, "detail", ""),
        sim_time=str(getattr(outcome, "sim_time", dt.datetime.now(dt.UTC))),
    )
