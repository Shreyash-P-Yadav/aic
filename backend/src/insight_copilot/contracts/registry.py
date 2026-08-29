"""The contract registry — the single place anything asks "what is this KPI?".

WHY a registry object rather than module-level dicts: it is injected into the
compiler, the engine and the API, so a test can build a registry over three
fixture contracts without touching the filesystem or a global. That is the same
property that lets the API pin a contract *version* into an audit row.
"""

from __future__ import annotations

from pathlib import Path

from insight_copilot.contracts.loader import discover, load_kpi_contract, load_source_contract
from insight_copilot.contracts.models import KPIContract
from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.errors import ContractError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


class ContractRegistry:
    """An immutable, validated view of every KPI and source contract."""

    def __init__(
        self,
        kpi_contracts: dict[str, KPIContract],
        source_contracts: dict[str, SourceContract],
    ) -> None:
        self._kpis = dict(kpi_contracts)
        self._sources = dict(source_contracts)

    # ----------------------------------------------------------------- build --
    @classmethod
    def from_directory(cls, root: Path) -> ContractRegistry:
        """Load ``root/kpi/*.yaml`` and ``root/source/*.yaml``.

        Every file is loaded before any error is raised, so ``make
        validate-contracts`` reports all problems in one run rather than one per
        invocation.
        """
        problems: list[str] = []
        kpis: dict[str, KPIContract] = {}
        sources: dict[str, SourceContract] = {}

        for path in discover(root / "kpi"):
            try:
                contract = load_kpi_contract(path)
            except ContractError as exc:
                problems.append(str(exc))
                continue
            if contract.kpi.id in kpis:
                problems.append(f"{path.name}: duplicate kpi id {contract.kpi.id!r}")
            kpis[contract.kpi.id] = contract

        for path in discover(root / "source"):
            try:
                source = load_source_contract(path)
            except ContractError as exc:
                problems.append(str(exc))
                continue
            if source.source_id in sources:
                problems.append(f"{path.name}: duplicate source id {source.source_id!r}")
            sources[source.source_id] = source

        if problems:
            raise ContractError(f"{len(problems)} contract problem(s)", detail="\n".join(problems))

        registry = cls(kpis, sources)
        registry.check_referential_integrity()
        logger.info("contracts.loaded", kpis=len(kpis), sources=len(sources))
        return registry

    # ------------------------------------------------------------------ read --
    @property
    def kpi_ids(self) -> list[str]:
        """Every governed KPI id, sorted."""
        return sorted(self._kpis)

    @property
    def source_ids(self) -> list[str]:
        """Every declared source id, sorted."""
        return sorted(self._sources)

    def kpi(self, kpi_id: str) -> KPIContract:
        """Fetch a KPI contract, or fail with the list of valid ids."""
        try:
            return self._kpis[kpi_id]
        except KeyError as exc:
            raise ContractError(
                f"unknown KPI {kpi_id!r}", detail=f"known: {', '.join(self.kpi_ids)}"
            ) from exc

    def source(self, source_id: str) -> SourceContract:
        """Fetch a source contract, or fail with the list of valid ids."""
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise ContractError(
                f"unknown source {source_id!r}", detail=f"known: {', '.join(self.source_ids)}"
            ) from exc

    def kpis_depending_on(self, source_id: str) -> list[KPIContract]:
        """KPIs a landing on ``source_id`` must wake.

        WHY: the analytics layer is event-driven, not cron-driven. A MarTech drop
        wakes ``blended_roas`` and ``marketing_spend``; it does not re-scan fill
        rate. Work happens when data changes, which is the whole cost story.
        """
        return [
            contract
            for _, contract in sorted(self._kpis.items())
            if any(ref.source_id == source_id for ref in contract.sources)
        ]

    # ------------------------------------------------------------- integrity --
    def check_referential_integrity(self) -> None:
        """Every cross-reference resolves. Raises with all problems at once."""
        problems: list[str] = []
        known_kpis = set(self._kpis)
        known_sources = set(self._sources)

        for kpi_id, contract in sorted(self._kpis.items()):
            for ref in contract.sources:
                if ref.source_id not in known_sources:
                    problems.append(f"{kpi_id}: sources -> unknown source {ref.source_id!r}")
            for driver in contract.drivers.exogenous:
                if driver.kpi_ref and driver.kpi_ref not in known_kpis:
                    problems.append(
                        f"{kpi_id}: driver {driver.id!r} -> unknown kpi_ref {driver.kpi_ref!r}"
                    )
                for mediated in driver.mediates:
                    driver_ids = {d.id for d in contract.drivers.exogenous}
                    if mediated not in driver_ids:
                        problems.append(
                            f"{kpi_id}: driver {driver.id!r} mediates unknown {mediated!r}"
                        )
            for edge in contract.drivers.feeds:
                if edge.kpi_ref not in known_kpis:
                    problems.append(f"{kpi_id}: feeds -> unknown kpi {edge.kpi_ref!r}")
            # A mask may name the KPI's own measure, a derived submetric, or a
            # dimension. Anything else is a typo that would silently mask nothing.
            maskable = (
                {contract.kpi.id}
                | set(contract.calculation.derived_submetrics)
                | set(contract.definition.dimensions)
            )
            for masked in sorted(contract.maskable_columns - maskable):
                problems.append(
                    f"{kpi_id}: access masks {masked!r}, which is neither the measure, "
                    f"a derived submetric, nor a dimension"
                )

        for source_id, source in sorted(self._sources.items()):
            for check in source.reconciliation:
                if check.against not in known_sources:
                    problems.append(
                        f"{source_id}: reconciliation against unknown source {check.against!r}"
                    )

        if problems:
            raise ContractError(
                f"{len(problems)} referential problem(s)", detail="\n".join(problems)
            )
