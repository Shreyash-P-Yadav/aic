"""Which insight a reader sees first — rules by default, LightGBM only when earned.

The ordering of a feed is the highest-leverage thing a learning loop can change and
the easiest place to do harm, because a model trained on forty labels will happily
learn one analyst's Tuesday mood and apply it forever. Three guards, all of which must
pass before the learned ranker is allowed to order anything:

1. **A label floor.** Below :data:`MIN_LABELS_FOR_MODEL` reactions the model is not
   trained at all and the rules order the feed. This is not a soft preference: the
   trained model is never even constructed.
2. **Both classes present.** A corpus where every reaction is "useful" carries no
   ordering information, whatever its size.
3. **A staleness monitor.** If the newest label is older than
   :data:`MAX_LABEL_AGE_DAYS`, the model is reverted to rules on the grounds that the
   world it learned has moved on. Reverting is automatic and is *reported*, because a
   silently reverted model is indistinguishable from a broken one.

The rules themselves are the contract's own priority formula made explicit: impact
first, then how confident the system is, then whether the movement is still going. No
weight here was tuned against the eval suite.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from insight_copilot.learning.store import FeedbackRecord, FeedbackStore
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MIN_LABELS_FOR_MODEL = 60
"""Reactions needed before a learned ranker is trained at all. Sixty is roughly ten
per feature: below that the model is fitting the analyst, not the problem."""

MIN_PER_CLASS = 10
"""Both "useful" and "not useful" need this many examples. A one-class corpus has no
ordering to learn, however many rows it has."""

MAX_LABEL_AGE_DAYS = 90
"""Beyond a quarter with no correction the learned ranker reverts to rules. A ranker
trained on a world nobody has confirmed in three months is a liability."""

IMPACT_WEIGHT = 0.55
CONFIDENCE_WEIGHT = 0.30
PERSISTENCE_WEIGHT = 0.15
"""The rules' weights: impact dominates because a large movement is worth a look even
at moderate confidence, and persistence breaks ties between comparable movements.
They sum to one so the rule score is bounded and comparable across KPIs."""

TIER_RANK: dict[str, float] = {
    "High": 1.0,
    "Moderate": 0.66,
    "Low": 0.33,
    "Insufficient": 0.0,
}
"""Tier as a number, for the rule score only. Nothing downstream reads this back as a
probability — the calibrated score is the probability."""


@dataclass(frozen=True)
class RankableInsight:
    """The features an insight offers the ranker. No text, no narrative."""

    insight_id: str
    impact_inr: float
    calibrated: float
    tier: str
    delta_pct: float
    persistence_days: int = 1
    segment: str = ""

    def features(self, impact_scale: float) -> list[float]:
        """The learned model's feature vector. Impact is scaled, never raw."""
        return [
            min(abs(self.impact_inr) / max(impact_scale, 1.0), 1.0),
            self.calibrated,
            TIER_RANK.get(self.tier, 0.0),
            min(abs(self.delta_pct) / 100.0, 1.0),
            min(self.persistence_days / 14.0, 1.0),
        ]


@dataclass(frozen=True)
class RankerStatus:
    """Why the ranker is doing what it is doing. Surfaced in the eval report."""

    trained: bool
    labels: int
    positives: int
    negatives: int
    newest_label_age_days: float | None
    reason: str


class PriorityRanker:
    """Orders a feed. Learned when the guards pass, rules otherwise, always says which."""

    def __init__(
        self,
        store: FeedbackStore,
        *,
        min_labels: int = MIN_LABELS_FOR_MODEL,
        max_age_days: int = MAX_LABEL_AGE_DAYS,
        now: dt.datetime | None = None,
    ) -> None:
        self._store = store
        self._min_labels = min_labels
        self._max_age_days = max_age_days
        self._now = now or dt.datetime.now(dt.UTC)
        self._model: object | None = None
        self._impact_scale = 1.0
        self._status = self._train()

    @property
    def status(self) -> RankerStatus:
        """Whether the learned ranker is in force, and why."""
        return self._status

    def rank(self, insights: list[RankableInsight]) -> list[RankableInsight]:
        """Highest priority first. Deterministic: ties break on insight id."""
        scored = [(self.score(item), item.insight_id, item) for item in insights]
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [item for _, _, item in scored]

    def score(self, insight: RankableInsight) -> float:
        """The priority score in force — learned or rule-based."""
        if self._model is None:
            return self._rule_score(insight)
        features = np.array([insight.features(self._impact_scale)], dtype=np.float64)
        predicted = self._model.predict(features)  # type: ignore[attr-defined]  # LGBMRegressor
        return float(np.clip(predicted[0], 0.0, 1.0))

    @staticmethod
    def _rule_score(insight: RankableInsight) -> float:
        """Impact x tier x persistence, all bounded, weights stated above."""
        impact = min(abs(insight.delta_pct) / 100.0, 1.0)
        confidence = TIER_RANK.get(insight.tier, 0.0) * insight.calibrated
        persistence = min(insight.persistence_days / 14.0, 1.0)
        return float(
            IMPACT_WEIGHT * impact
            + CONFIDENCE_WEIGHT * confidence
            + PERSISTENCE_WEIGHT * persistence
        )

    # -------------------------------------------------------------- training --
    def _train(self) -> RankerStatus:
        """Train, or explain in one sentence why not."""
        records = list(self._store.latest_per_insight().values())
        positives = sum(1 for item in records if item.is_positive)
        negatives = len(records) - positives
        age = self._age_days(records)

        if len(records) < self._min_labels:
            return self._untrained(
                records,
                positives,
                negatives,
                age,
                f"{len(records)} labels, below the {self._min_labels} floor; using rules",
            )
        if min(positives, negatives) < MIN_PER_CLASS:
            return self._untrained(
                records,
                positives,
                negatives,
                age,
                f"{positives} positive / {negatives} negative; a class is too thin for a model",
            )
        if age is not None and age > self._max_age_days:
            return self._untrained(
                records,
                positives,
                negatives,
                age,
                f"newest label is {age:.0f} days old, past the {self._max_age_days}-day "
                "staleness limit; reverted to rules",
            )
        return self._fit(records, positives, negatives, age)

    def _fit(
        self,
        records: list[FeedbackRecord],
        positives: int,
        negatives: int,
        age: float | None,
    ) -> RankerStatus:
        """Fit the gradient-boosted ranker. Import is local so the guards run first."""
        from lightgbm import LGBMRegressor

        self._impact_scale = float(
            np.percentile([abs(item.impact_inr) for item in records], 90) or 1.0
        )
        rows = [
            RankableInsight(
                insight_id=item.insight_id,
                impact_inr=item.impact_inr,
                calibrated=item.confidence,
                tier=item.tier,
                delta_pct=item.delta_pct,
            ).features(self._impact_scale)
            for item in records
        ]
        target = np.array([float(item.is_positive) for item in records], dtype=np.float64)
        model = LGBMRegressor(
            n_estimators=120, learning_rate=0.05, num_leaves=7, min_child_samples=10, verbose=-1
        )
        model.fit(np.array(rows, dtype=np.float64), target)
        self._model = model
        logger.info("learning.ranker_trained", labels=len(records), positives=positives)
        return RankerStatus(
            trained=True,
            labels=len(records),
            positives=positives,
            negatives=negatives,
            newest_label_age_days=age,
            reason=f"trained on {len(records)} labels ({positives} positive)",
        )

    def _untrained(
        self,
        records: list[FeedbackRecord],
        positives: int,
        negatives: int,
        age: float | None,
        reason: str,
    ) -> RankerStatus:
        """Record why the learned ranker is not in force. Never silent."""
        self._model = None
        logger.info("learning.ranker_rules", reason=reason, labels=len(records))
        return RankerStatus(
            trained=False,
            labels=len(records),
            positives=positives,
            negatives=negatives,
            newest_label_age_days=age,
            reason=reason,
        )

    def _age_days(self, records: list[FeedbackRecord]) -> float | None:
        """Days since the newest label, or ``None`` when there are none."""
        if not records:
            return None
        newest = max(item.recorded_at for item in records)
        return (self._now - newest).total_seconds() / 86400.0
