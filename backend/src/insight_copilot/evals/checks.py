"""The evals that do not come from the backtest: narration, entitlements, budgets.

Each is a small, separately runnable function so a failure names one thing. They all
take their collaborators as arguments — nothing here reaches for a global — which is
what lets the gate run them against a fixture warehouse and the demo run them against
the real one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.engine.bundle import InsightEvidenceBundle
from insight_copilot.errors import ContractError, EntitlementError
from insight_copilot.llm.hypotheses import HypothesisProposer
from insight_copilot.llm.narrate import PersonaNarrator
from insight_copilot.llm.verify_numbers import verify
from insight_copilot.logging import get_logger
from insight_copilot.security.compiler import ContractSQLCompiler
from insight_copilot.security.identity import ROLES, Identity, RoleName, SessionContext
from insight_copilot.security.query import QueryRequest

logger = get_logger(__name__)

MASK_SENTINEL = "MASKED"
"""What a masked column compiles to. Finding a real value where this belongs is the
leakage the entitlement eval exists to detect."""


@dataclass(frozen=True)
class NarrationScore:
    """Numeric fidelity and citation coverage over a set of narrated bundles."""

    narrated: int
    numbers_checked: int
    numbers_verified: int
    cited_claims: int
    total_claims: int
    dropped_claims: int = 0
    unsupported: tuple[str, ...] = ()
    """Every numeral that matched no evidence fact, as it appeared, with its persona.

    Carried because "numeric fidelity 0.94" is not actionable and this metric is the
    one where a single failure matters most. Naming the offending numerals turns a
    recurrence into a diagnosis instead of a re-run.
    """

    @property
    def numeric_fidelity(self) -> float:
        """Fraction of emitted numbers that matched an evidence fact. Target: 1.0."""
        return self.numbers_verified / self.numbers_checked if self.numbers_checked else 1.0

    @property
    def citation_coverage(self) -> float:
        """Fraction of PUBLISHED causal claims resting on a document in the bundle.

        Published, not proposed. A claim the cite-or-drop filter rejected never reaches
        a reader, so counting it would report on the model's habits rather than on what
        the system says. This number checks that the filter actually holds: any kept
        hypothesis whose citation is not in the bundle would pull it below 1.0.
        """
        return self.cited_claims / self.total_claims if self.total_claims else 1.0

    @property
    def drop_rate(self) -> float:
        """Share of proposed claims the cite-or-drop filter rejected. Informational —
        it measures the model, and a rate of zero would mean the filter never runs."""
        proposed = self.total_claims + self.dropped_claims
        return self.dropped_claims / proposed if proposed else 0.0


def score_narration(
    narrator: PersonaNarrator,
    bundles: list[InsightEvidenceBundle],
    personas: list[str],
    *,
    proposer: HypothesisProposer | None = None,
    registry: ContractRegistry | None = None,
) -> NarrationScore:
    """Narrate every bundle for every persona and verify every number it emits.

    Verification is re-run here rather than trusting the narrator's own result: the
    eval's job is to check the verifier's work too, and a verifier that reports on
    itself proves nothing.
    """
    narrated = checked = verified = cited = claims = dropped = 0
    unsupported: list[str] = []
    for bundle in bundles:
        for persona in personas:
            narrative = narrator.narrate(bundle, persona)
            narrated += 1
            result = verify(narrative.text, bundle)
            checked += len(result.numbers)
            verified += len(result.matched)
            unsupported.extend(
                f"{persona}: {item.raw!r} ({item.value:g})" for item in result.unsupported
            )
        if proposer is not None and registry is not None:
            # Coverage is over PUBLISHED claims and their citation must resolve to a
            # document actually in the bundle: a kept hypothesis citing something the
            # bundle never carried would be a filter regression, and this is what
            # would catch it.
            proposal = proposer.propose(bundle, registry.kpi(bundle.kpi_id))
            available = {item.doc_id for item in bundle.evidence}
            claims += len(proposal.kept)
            cited += sum(1 for item in proposal.kept if set(item.cites) & available)
            dropped += len(proposal.dropped_uncited) + len(proposal.dropped_unknown_driver)
    logger.info("evals.narration_scored", narrated=narrated, numbers=checked)
    return NarrationScore(
        narrated=narrated,
        numbers_checked=checked,
        numbers_verified=verified,
        cited_claims=cited,
        total_claims=claims,
        dropped_claims=dropped,
        unsupported=tuple(unsupported),
    )


@dataclass(frozen=True)
class LeakageFinding:
    """One entitlement finding: which role, which contract, and what was wrong."""

    role: str
    contract_id: str
    detail: str
    is_leak: bool = True
    """A leak is a mask or row filter missing from compiled SQL — data a role could
    have seen and should not. A policy that will not compile at all is the opposite
    failure: fail-closed, nothing leaked, but a role denied by accident rather than by
    decision. Both are reported; only the first counts against the leakage target,
    because conflating them would let a broken policy be "fixed" by widening it."""


def check_entitlements(
    registry: ContractRegistry, compiler: ContractSQLCompiler
) -> list[LeakageFinding]:
    """Compile every contract for every role and look for a mask or filter that is missing.

    Compiled SQL is inspected rather than query results, because that is where the
    guarantee lives: if the mask is not in the SQL, no amount of downstream filtering
    puts it back, and a result set that happens to be empty today proves nothing about
    tomorrow's data.
    """
    findings: list[LeakageFinding] = []
    for role_name in ROLES:
        session = _session(role_name)
        for contract_id in registry.kpi_ids:
            contract = registry.kpi(contract_id)
            policy = contract.access.roles.get(role_name)
            # Each contract is compiled at its OWN first permitted grain: a grain the
            # contract forbids raises before any entitlement is applied, which would
            # test the grain validator rather than the mask.
            grain = list(contract.definition.default_reporting_grain)
            request = QueryRequest(
                contract_id=contract_id,
                grain=grain,
                measures=[contract_id],
                filters=[],
                order_by=grain,
            )
            try:
                compiled = compiler.compile(request, session)
            except EntitlementError:
                continue  # A denied role is the strongest possible entitlement.
            except ContractError as exc:
                findings.append(
                    LeakageFinding(
                        role=role_name,
                        contract_id=contract_id,
                        detail=f"policy will not compile (fail-closed): {exc.message}",
                        is_leak=False,
                    )
                )
                continue
            findings.extend(_inspect(compiled.sql, role_name, contract_id, policy))
    logger.info("evals.entitlements_checked", findings=len(findings))
    return findings


def _inspect(
    sql: str, role_name: str, contract_id: str, policy: object | None
) -> list[LeakageFinding]:
    """Does this compiled statement carry the masks and filters the policy demands?"""
    if policy is None:
        return [
            LeakageFinding(
                role=role_name,
                contract_id=contract_id,
                detail="compiled with no entitlement policy for this role",
            )
        ]
    findings: list[LeakageFinding] = []
    for column in getattr(getattr(policy, "columns", None), "mask", []) or []:
        if column in sql and MASK_SENTINEL not in sql:
            findings.append(
                LeakageFinding(
                    role=role_name,
                    contract_id=contract_id,
                    detail=f"{column} appears unmasked in the compiled SQL",
                )
            )
    rows = getattr(policy, "rows", None)
    if rows and ":" in str(rows) and "$" not in sql:
        findings.append(
            LeakageFinding(
                role=role_name,
                contract_id=contract_id,
                detail="a row-filter template is declared but no bind parameter was compiled",
            )
        )
    return findings


def _session(role_name: RoleName) -> SessionContext:
    """A session for one role, with the bindings a scoped role needs."""
    role = ROLES[role_name]
    # Bindings come from the ROLE, not from the session: a caller cannot hand itself a
    # region. That is the whole point of the design, and it is why this function takes
    # no bindings argument.
    return SessionContext(
        identity=Identity(
            user_id=f"{role_name}@example.com", display_name=role.display_name, role=role
        ),
        intent="eval",
    )


@dataclass(frozen=True)
class Timing:
    """One timed stage, in milliseconds."""

    name: str
    milliseconds: float


def timed(name: str, work: object) -> tuple[Timing, object]:
    """Run a zero-argument callable and report how long it took."""
    started = time.perf_counter()
    result = work()  # type: ignore[operator]  # a zero-argument callable by contract
    return Timing(name=name, milliseconds=(time.perf_counter() - started) * 1000.0), result
