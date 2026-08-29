"""Arrival-time quirks: the two pathologies that only exist in *how a batch lands*.

Most of the defect catalog (P4) is a property of rows and is injected into the
generated frames. Two are not. A schema drift and a restatement are properties of a
*delivery*: they cannot be represented in a single table because the same business
key has to appear twice, with two shapes or two values, at two different moments.

WHY these live in ``harness/`` and not in ``ingest/``: this module is the simulated
outside world, not the pipeline. It emulates what the producing system does. Nothing
here is imported by anything downstream of the landing zone, and every magnitude it
uses is taken from the defect injector that documents it — there is one definition of
"the MarTech feed revises by about six percent", and it is in ``defects/arrival.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.datagen.defects.arrival import Restatement
from insight_copilot.datagen.defects.schema import SchemaDrift
from insight_copilot.datagen.world.seeds import RNGSource
from insight_copilot.harness.periods import WEEK_LABEL, label_start
from insight_copilot.harness.scheduler import PlannedArrival


class BatchQuirk(ABC):
    """Something the producing system does to a batch on its way out of the door."""

    @abstractmethod
    def applies_to(self, contract: SourceContract, arrival: PlannedArrival) -> bool:
        """Is this delivery affected at all?"""

    @abstractmethod
    def mutate(
        self, frame: pd.DataFrame, contract: SourceContract, arrival: PlannedArrival
    ) -> pd.DataFrame:
        """Return the rows as this delivery actually carries them."""


class SchemaDriftQuirk(BatchQuirk):
    """P7 — from a known date the MarTech export also emits ``spend_amount``.

    Delivered as an *added alias* rather than a rename, exactly as the P7 injector
    documents: the platform's new export template renamed the field, and the
    aggregator's compatibility shim kept the old one. The pipeline therefore sees an
    undeclared column, which is what ``drift_policy: quarantine_and_alert`` is for.
    """

    SOURCE_ID = "martech_weekly"
    ORIGINAL_COLUMN = "spend_inr"

    def applies_to(self, contract: SourceContract, arrival: PlannedArrival) -> bool:
        if contract.source_id != self.SOURCE_ID:
            return False
        return any(
            WEEK_LABEL.match(label) and label_start(label) >= SchemaDrift.DRIFT_FROM
            for label in arrival.periods
        )

    def mutate(
        self, frame: pd.DataFrame, contract: SourceContract, arrival: PlannedArrival
    ) -> pd.DataFrame:
        del contract, arrival
        if self.ORIGINAL_COLUMN not in frame.columns:
            return frame
        result = frame.copy()
        result[SchemaDrift.RENAMED_TO] = result[self.ORIGINAL_COLUMN]
        return result


class RestatementQuirk(BatchQuirk):
    """P3 — a restating source revises the periods it re-sends.

    The revision size is the injector's published ``RESTATEMENT_DRIFT``; the draw is
    content-addressed by ``(source_id, period, revision)`` so the *n*-th redelivery of
    a given week always carries the same revised figure however many times the demo
    is replayed. Revision 0 — the period this batch is actually reporting — is never
    touched, so the first version of every period is the projected truth.
    """

    REVISED_MEASURES: dict[str, str] = {"martech_weekly": "attributed_revenue_inr"}
    """Which measure a source revises. Attribution settles as view-throughs land;
    spend, which is billed, does not move."""

    def __init__(self, seeds: RNGSource) -> None:
        self._seeds = seeds

    def applies_to(self, contract: SourceContract, arrival: PlannedArrival) -> bool:
        return (
            contract.restatement.expected
            and contract.source_id in self.REVISED_MEASURES
            and len(arrival.periods) > 1
        )

    def mutate(
        self, frame: pd.DataFrame, contract: SourceContract, arrival: PlannedArrival
    ) -> pd.DataFrame:
        result = frame
        for revision, period in enumerate(arrival.periods):
            if revision > 0:
                result = self.revise(result, contract, period, revision)
        return result

    def revise(
        self, frame: pd.DataFrame, contract: SourceContract, period: str, revision: int
    ) -> pd.DataFrame:
        """Apply the ``revision``-th revision of one period. Deterministic in all three."""
        measure = self.REVISED_MEASURES.get(contract.source_id)
        if measure is None or measure not in frame.columns or frame.empty:
            return frame
        selected = frame[contract.watermark].astype(str) == period
        if not selected.any():
            return frame
        rng = self._seeds("restatement_delivery", contract.source_id, period, revision)
        drift = float(np.abs(1.0 + Restatement.RESTATEMENT_DRIFT * rng.normal(0.0, 1.0)))
        result = frame.copy()
        result.loc[selected, measure] = (result.loc[selected, measure] * drift).round(2)
        return result


def default_quirks(seeds: RNGSource) -> list[BatchQuirk]:
    """Every quirk the shipped contracts need, in application order."""
    return [RestatementQuirk(seeds), SchemaDriftQuirk()]
