"""P26-P30 — the evidence-layer pathologies, plus the clean control period.

These live in the corpus rather than in the tables, and they attack the *confidence*
half of the system. Syndication is the sharpest: if dedup fails, noisy-OR treats one
press release across six outlets as six independent confirmations and confidence is
inflated on exactly the stories that are most widely repeated.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from insight_copilot.datagen.corpus.pii import contains_real_looking_identifier
from insight_copilot.datagen.defects.base import DefectEvidence, DefectInjector
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames


class SyndicatedDuplicates(DefectInjector):
    """P26 — one press release across six outlets. **The corroboration trap.**

    If dedup fails, one story counts as six independent sources and noisy-OR inflates
    evidence confidence precisely where the story is loudest. Every syndicated copy
    carries the same `syndication_group`, which is the key ingestion-time dedup uses;
    the test asserts both that the duplicates exist AND that the key collapses them.
    """

    code: ClassVar[str] = "P26"
    title: ClassVar[str] = "Syndicated duplicates"
    complexity: ClassVar[str] = "Syndicated duplicates"
    exercises: ClassVar[str] = "MinHash-style dedup at ingestion"
    demo_moment: ClassVar[str] = "Evidence corroboration"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        if "news_articles" not in frames:
            return self._missing("no news corpus projected")
        news = frames["news_articles"]
        sizes = news.groupby("syndication_group", observed=True).size()
        syndicated = sizes.loc[sizes > 1]
        collapsed = int(sizes.sum() - len(sizes))
        return (
            self._found(
                f"{len(syndicated)} stories appear across 2-{int(sizes.max())} outlets; "
                f"dedup by syndication_group collapses {collapsed} rows",
                syndicated_stories=len(syndicated),
                max_outlets=float(sizes.max()),
                collapsed_rows=collapsed,
            )
            if len(syndicated) >= 5 and sizes.max() >= 3
            else self._missing(f"only {len(syndicated)} syndicated stories")
        )


class PIIInText(DefectInjector):
    """P27 — names, emails and phones in ticket bodies, masked before indexing."""

    code: ClassVar[str] = "P27"
    title: ClassVar[str] = "PII in text"
    complexity: ClassVar[str] = "PII in text"
    exercises: ClassVar[str] = "Masking before indexing"
    demo_moment: ClassVar[str] = "Governance story"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del context
        tickets = frames["support_tickets"]
        sample = tickets["body_text"].astype(str).head(4000)
        with_email = int(sample.str.contains("@", regex=False).sum())
        with_phone = int(sample.str.contains(r"\+91", regex=True).sum())

        # And it must all be synthetic: a real-looking identifier anywhere is a
        # failure, not a defect.
        offender = None
        for text in sample:
            offender = contains_real_looking_identifier(text)
            if offender:
                break
        if offender:
            return self._missing(f"a real-looking identifier appears in a ticket: {offender!r}")
        return (
            self._found(
                f"{with_email} of {len(sample)} sampled tickets carry an email and "
                f"{with_phone} a phone number, all synthetic",
                with_email=with_email,
                with_phone=with_phone,
            )
            if with_email + with_phone > 0
            else self._missing("no PII present in ticket bodies")
        )


class ContradictoryEvidence(DefectInjector):
    """P28 — a ticket and a supplier email that disagree."""

    code: ClassVar[str] = "P28"
    title: ClassVar[str] = "Contradictory evidence"
    complexity: ClassVar[str] = "Contradictory evidence"
    exercises: ClassVar[str] = "Evidence agreement, hedged tier"
    demo_moment: ClassVar[str] = "Moderate-tier example"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        events = [event for event in context.ledger if event.ground_truth.compute]
        contradicted = [event for event in events if event.evidence.contradiction]
        rate = len(contradicted) / max(len(events), 1)
        return (
            self._found(
                f"{len(contradicted)} events carry contradictory documents ({rate:.1%})",
                events=len(contradicted),
                rate=rate,
            )
            if 0.03 <= rate <= 0.20
            else self._missing(
                f"contradiction rate {rate:.1%} outside the designed band", rate=rate
            )
        )


class PostDatedRedHerring(DefectInjector):
    """P29 — a dramatic document dated after the effect it appears to explain."""

    code: ClassVar[str] = "P29"
    title: ClassVar[str] = "Post-dated red herring"
    complexity: ClassVar[str] = "Post-dated red herring"
    exercises: ClassVar[str] = "Timing gate"
    demo_moment: ClassVar[str] = "Scenario A"
    structural: ClassVar[bool] = True

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        events = [event for event in context.ledger if event.ground_truth.compute]
        decoys = [event for event in events if event.evidence.post_dated_decoy]
        rate = len(decoys) / max(len(events), 1)
        scenario_decoy = [
            event for event in context.ledger if event.demo_role == "scenario_A_decoy"
        ]
        return (
            self._found(
                f"{len(decoys)} post-dated decoys ({rate:.1%}), including Scenario A's "
                f"competitor announcement",
                decoys=len(decoys),
                rate=rate,
            )
            if decoys and scenario_decoy
            else self._missing(
                f"{len(decoys)} decoys, scenario decoy present: {bool(scenario_decoy)}"
            )
        )


class CleanControlPeriod(DefectInjector):
    """P30 — a stretch with nothing wrong, for measuring the false-positive rate.

    Without it there is no window in which a detection is unambiguously a false alarm,
    and "precision" becomes a number with no denominator.
    """

    code: ClassVar[str] = "P30"
    title: ClassVar[str] = "Clean control period"
    complexity: ClassVar[str] = "Clean control period"
    exercises: ClassVar[str] = "False-positive rate measurement"
    demo_moment: ClassVar[str] = "Backtest"
    structural: ClassVar[bool] = True

    MIN_CLEAN_DAYS: ClassVar[int] = 21
    """Three weeks with no event of any kind is enough to measure a daily FDR against."""

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        del frames
        calendar = context.calendar
        dates = [timestamp.date() for timestamp in calendar.dates]
        busy = [False] * len(dates)
        for event in context.ledger:
            if event.magnitude.kind == "none":
                continue
            for index, day in enumerate(dates):
                if event.window.start <= day <= event.window.end:
                    busy[index] = True

        longest, current, start_index, best_index = 0, 0, None, None
        for index, is_busy in enumerate(busy):
            if is_busy:
                current, start_index = 0, None
            else:
                current += 1
                start_index = index if start_index is None else start_index
                if current > longest:
                    longest, best_index = current, start_index
        window_start = dates[best_index] if best_index is not None else dt.date.min
        return (
            self._found(
                f"longest clean stretch is {longest} days from {window_start}",
                clean_days=longest,
            )
            if longest >= self.MIN_CLEAN_DAYS
            else self._missing(f"longest clean stretch is only {longest} days", clean_days=longest)
        )


INJECTORS = [
    SyndicatedDuplicates(),
    PIIInText(),
    ContradictoryEvidence(),
    PostDatedRedHerring(),
    CleanControlPeriod(),
]
