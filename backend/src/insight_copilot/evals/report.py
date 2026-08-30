"""Rendering the eval report to ``artifacts/eval_report.md`` and ``.json``.

The JSON is the record: complete, machine-readable, and what a future run diffs
against. The markdown is for the human who has to decide whether to trust this system,
so it leads with what failed. A report that opens with its successes is a report that
was written to be skimmed past.
"""

from __future__ import annotations

import json
from pathlib import Path

from insight_copilot.evals.models import EvalReport, Measurement
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

SIMULATED_NOTICE = (
    "All data in this report is simulated. Meridian Consumer Brands is a fictional "
    "company; no figure here describes a real business."
)


def write_report(report: EvalReport, directory: Path) -> tuple[Path, Path]:
    """Write both artifacts and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "eval_report.json"
    md_path = directory / "eval_report.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    logger.info("evals.report_written", markdown=str(md_path), json=str(json_path))
    return md_path, json_path


def to_markdown(report: EvalReport) -> str:
    """The report as markdown, failures first."""
    lines: list[str] = [
        "# Insight Copilot — evaluation report",
        "",
        f"_{SIMULATED_NOTICE}_",
        "",
        f"Generated {report.generated_at:%Y-%m-%d %H:%M} UTC.",
        "",
        _headline(report),
        "",
        "## Corpus",
        "",
        f"- {report.corpus_events} ledger events replayed",
        f"- temporal split at **{report.cut_date}** — {report.fit_events} events fitted, "
        f"{report.holdout_events} held out",
        f"- {report.excluded_events} demo-scenario events excluded from the fit entirely",
        "",
    ]
    if report.failures:
        lines += ["## What failed", "", _table(report.failures), ""]
    for section in report.sections:
        lines += [f"## {section.name}", ""]
        if section.detail:
            lines += [section.detail, ""]
        lines += [_table(section.measurements), ""]
    if report.tiers:
        lines += [
            "## Tiers as measured",
            "",
            f"Boundaries: {report.tier_basis}",
            "",
            "| Tier | boundary | n | mean score | observed hit rate |",
            "|---|---:|---:|---:|---:|",
        ]
        lines += [
            f"| {row.tier} | {row.boundary:.3f} | {row.n} | {row.mean_score:.3f} | "
            f"{row.hit_rate:.1%} |"
            for row in report.tiers
        ]
        lines += [""]
    if report.reliability:
        lines += [
            "## Reliability curve",
            "",
            "| bin | n | mean score | observed hit rate | gap |",
            "|---|---:|---:|---:|---:|",
        ]
        lines += [
            f"| {row.lower:.1f} to {row.upper:.1f} | {row.n} | "
            + (
                f"{row.mean_score:.3f} | {row.hit_rate:.3f} | "
                f"{abs(row.mean_score - row.hit_rate):.3f} |"
                if row.n
                else "— | — | — |"
            )
            for row in report.reliability
        ]
        lines += [""]
    if report.ranker_status:
        lines += ["## Priority ranker", "", report.ranker_status, ""]
    if report.notes:
        lines += ["## Notes", ""] + [f"- {note}" for note in report.notes] + [""]
    return "\n".join(lines)


def _headline(report: EvalReport) -> str:
    """One sentence a reader can act on."""
    if report.passed:
        return f"**All {len(report.measurements)} targeted metrics met their target.**"
    return (
        f"**{len(report.failures)} of {len(report.measurements)} metrics missed their "
        "target.** Each is listed below with the measured number; none has been "
        "removed, reweighted or re-targeted to produce a pass."
    )


def _table(measurements: list[Measurement]) -> str:
    """A markdown table of measurements, target and verdict included."""
    header = ["| metric | measured | target | n | verdict |", "|---|---:|---:|---:|---|"]
    rows = [
        "| {name} | {value} | {target} | {n} | {verdict} |".format(
            name=item.name,
            value=_number(item.value, item.unit),
            target="—" if item.target is None else _number(item.target, item.unit),
            n=item.n,
            verdict=item.verdict,
        )
        for item in measurements
    ]
    return "\n".join(header + rows)


def _number(value: float, unit: str) -> str:
    """Format a measurement the way its unit wants to be read."""
    if value != value:
        return "not measured"
    if unit == "%":
        return f"{value:.1%}"
    if unit == "ms":
        return f"{value:,.0f} ms"
    if unit == "usd":
        return f"${value:.4f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:.3f}"


def read_report(path: Path) -> EvalReport:
    """Read a report back. Used to diff one run against the last."""
    return EvalReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
