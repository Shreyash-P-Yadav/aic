"""The landing zone and the watcher that sees files appear in it.

**The prototype never reads a finished table.** It watches files arrive, exactly as a
real deployment does, because every hard part of this problem — freshness,
restatement, out-of-order periods, abstention on a stale feed — lives in the arrival
process and is invisible from a completed warehouse.

Two objects:

* ``LandingZone`` writes one data file plus one manifest per batch into a partitioned
  tree whose layout comes from each contract's ``landing_path``.
* ``SourceWatcher`` polls that tree and hands the ingestion runner the batches whose
  ``received_at`` has passed on the simulated clock. It deliberately re-offers a batch
  it has already offered if the file is still there: idempotency is the batch
  registry's job, not the watcher's, because a watcher that dedupes in memory would
  make the duplicate-delivery path untestable after a restart.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pandas as pd

from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.harness.formats import extension_for, read_batch, write_batch
from insight_copilot.harness.manifest import BatchManifest, Covers, make_batch_id
from insight_copilot.harness.periods import STATIC_PERIOD
from insight_copilot.harness.scheduler import PlannedArrival
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

MANIFEST_SUFFIX = ".manifest.json"
CONTRACT_PATH_PREFIX = "landing/"
"""Contracts write absolute-looking landing paths. The zone root already *is* the
landing directory, so the prefix is stripped rather than nested twice."""


@dataclass(frozen=True)
class LandedBatch:
    """A file on disk and the manifest that describes it."""

    manifest: BatchManifest
    data_path: Path
    manifest_path: Path

    @property
    def source_id(self) -> str:
        """Which feed dropped this."""
        return self.manifest.source_id

    @property
    def batch_id(self) -> str:
        """The idempotency key."""
        return self.manifest.batch_id

    def read(self, contract: SourceContract) -> pd.DataFrame:
        """The delivered rows, untyped, exactly as they were written."""
        return read_batch(self.data_path, contract.format)


class LandingZone:
    """Partitioned files plus a manifest per batch, S3-like on the local disk."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._history: dict[tuple[str, str], list[str]] = {}
        self._reindex()

    @property
    def root(self) -> Path:
        """Where batches land."""
        return self._root

    # ------------------------------------------------------------------ land --
    def land(
        self,
        contract: SourceContract,
        frame: pd.DataFrame,
        arrival: PlannedArrival,
        *,
        producer_note: str | None = None,
    ) -> LandedBatch:
        """Write one batch and its manifest. Re-landing identical content overwrites.

        Overwriting is correct: the batch id is a digest of the content and the sim
        timestamp, so the same id can only ever name the same bytes. A *different*
        delivery gets a different id and a different file.
        """
        directory = self._partition(contract, arrival.periods)
        directory.mkdir(parents=True, exist_ok=True)
        content_digest = _frame_digest(frame)
        batch_id = make_batch_id(
            contract.source_id, arrival.scheduled_at, arrival.periods, content_digest
        )
        data_path = directory / f"{batch_id}{extension_for(contract.format)}"
        write_batch(frame, data_path, contract.format)

        manifest = BatchManifest(
            source_id=contract.source_id,
            batch_id=batch_id,
            generated_at_sim=arrival.scheduled_at,
            received_at=arrival.received_at,
            covers=Covers(grain=contract.watermark, periods=list(arrival.periods)),
            is_restatement=arrival.is_restatement,
            supersedes=self._prior_batches(contract.source_id, arrival.periods, batch_id),
            row_count=len(frame),
            checksum=f"sha256:{_file_digest(data_path)}",
            schema_version=contract.schema_spec.version,
            producer_note=producer_note,
        )
        manifest_path = directory / f"{batch_id}{MANIFEST_SUFFIX}"
        manifest.write(manifest_path)
        self._remember(manifest)

        logger.info(
            "landing.wrote",
            source_id=contract.source_id,
            batch_id=batch_id,
            rows=len(frame),
            periods=list(arrival.periods),
            restatement=arrival.is_restatement,
        )
        return LandedBatch(manifest=manifest, data_path=data_path, manifest_path=manifest_path)

    # ---------------------------------------------------------------- layout --
    def _partition(self, contract: SourceContract, periods: tuple[str, ...]) -> Path:
        """Render the contract's ``landing_path`` for this batch's newest period."""
        relative = contract.landing_path.removeprefix(CONTRACT_PATH_PREFIX).strip("/")
        newest = periods[0] if periods else STATIC_PERIOD
        rendered = relative.format(date=newest, iso_week=newest, period=newest)
        return self._root / rendered

    def _prior_batches(self, source_id: str, periods: tuple[str, ...], batch_id: str) -> list[str]:
        """Batch ids already covering any of these periods — what this one supersedes."""
        seen: list[str] = []
        for period in periods:
            for prior in self._history.get((source_id, period), []):
                if prior != batch_id and prior not in seen:
                    seen.append(prior)
        return seen

    def _remember(self, manifest: BatchManifest) -> None:
        for period in manifest.covers.periods:
            self._history.setdefault((manifest.source_id, period), []).append(manifest.batch_id)

    def _reindex(self) -> None:
        """Rebuild the period history from disk, so a restart supersedes correctly."""
        for path in sorted(self._root.rglob(f"*{MANIFEST_SUFFIX}")):
            manifest = BatchManifest.read(path)
            self._remember(manifest)

    def clear(self) -> None:
        """Remove every landed file. The reset half of the demo controls."""
        for path in sorted(self._root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        self._history.clear()


class SourceWatcher:
    """Polls the landing zone and yields batches whose arrival moment has passed.

    It remembers which manifests it has already parsed, so a long replay does not
    re-read every manifest ever written on every tick — the same thing a real watcher
    does with an object-store listing marker. That memory is an *efficiency* device
    only: idempotency belongs to the batch registry, so a batch offered twice is still
    safe, and :meth:`rescan` deliberately re-offers everything.
    """

    def __init__(self, zone: LandingZone) -> None:
        self._zone = zone
        self._seen: set[Path] = set()

    def rescan(self) -> None:
        """Forget what has been offered, so the next poll re-offers every batch."""
        self._seen.clear()

    def poll(self, now: dt.datetime) -> list[LandedBatch]:
        """Every batch received since the cursor and at or before ``now``, oldest first.

        Ordering is by ``received_at`` and then batch id, so a jittered feed that
        overtakes another source is presented to the pipeline in the order it really
        arrived — which is how out-of-order periods reach the watermark logic at all.
        """
        batches: list[LandedBatch] = []
        for manifest_path in self._zone.root.rglob(f"*{MANIFEST_SUFFIX}"):
            if manifest_path in self._seen:
                continue
            manifest = BatchManifest.read(manifest_path)
            if manifest.received_at > now:
                continue
            data_path = _data_path_for(manifest_path, manifest.batch_id)
            if data_path is None:
                logger.warning(
                    "landing.orphan_manifest",
                    batch_id=manifest.batch_id,
                    path=str(manifest_path),
                )
                continue
            batches.append(
                LandedBatch(manifest=manifest, data_path=data_path, manifest_path=manifest_path)
            )
        batches.sort(key=lambda batch: (batch.manifest.received_at, batch.batch_id))
        self._seen.update(batch.manifest_path for batch in batches)
        return batches


def _data_path_for(manifest_path: Path, batch_id: str) -> Path | None:
    """The data file beside a manifest, whatever extension its format uses."""
    for candidate in sorted(manifest_path.parent.glob(f"{batch_id}.*")):
        if not candidate.name.endswith(MANIFEST_SUFFIX):
            return candidate
    return None


def _frame_digest(frame: pd.DataFrame) -> str:
    """A stable digest of a frame's content, for the batch id."""
    hashed = pd.util.hash_pandas_object(frame, index=False).to_numpy("uint64")
    return sha256(hashed.tobytes() + repr(list(frame.columns)).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    """SHA-256 over the delivered bytes — the manifest's integrity claim."""
    return sha256(path.read_bytes()).hexdigest()
