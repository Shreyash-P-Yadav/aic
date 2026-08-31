"""The contract-to-SQL compiler — the only path to data in this system.

Two properties make this component load-bearing:

1. **The caller never supplies SQL.** It supplies a ``QueryRequest`` naming contract
   concepts. Every identifier in it (dimension, measure, order key) is checked
   against the contract's own allowlist, so an unknown token fails before any SQL
   exists. Every *value* is bound as a parameter, so its content — including a
   sentence beginning "ignore previous instructions" — cannot change the shape of
   the query. The compiled SQL for a malicious value is byte-identical to the
   compiled SQL for a benign one.

2. **Entitlements are applied here, below the language model.** Row filters and
   column masks come from the contract's ``access`` block and the caller's session.
   A route handler cannot forget to apply them, and no prompt can ask the compiler
   to skip them, because the compiler takes no instructions — only a typed request.

Default-deny: a role with no policy entry for a contract is refused. Adding a role
must be a deliberate grant, never an oversight that reads as access.
"""

from __future__ import annotations

import hashlib
import re

from insight_copilot.contracts.governance import RolePolicy
from insight_copilot.contracts.models import KPIContract
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.errors import CompilerError, ContractError, EntitlementError
from insight_copilot.logging import get_logger
from insight_copilot.security.audit import AuditLog, AuditRecord
from insight_copilot.security.identity import SessionContext
from insight_copilot.security.query import (
    MASK_SENTINEL,
    CompiledQuery,
    FilterClause,
    QueryRequest,
)

logger = get_logger(__name__)

_BIND_TOKEN = re.compile(r":([a-z][a-z0-9_]*)")
"""Named bindings inside a contract row-filter template, e.g. ``:user_region``."""

_VALUES_PER_OP: dict[str, int | None] = {
    "eq": 1,
    "ne": 1,
    "gte": 1,
    "lte": 1,
    "between": 2,
    "in": None,  # any number, at least one — enforced by the model's min_length
}

_SQL_OP: dict[str, str] = {"eq": "=", "ne": "<>", "gte": ">=", "lte": "<="}


class ContractSQLCompiler:
    """Compiles a typed request against a contract and a session into bound SQL."""

    def __init__(self, registry: ContractRegistry, audit_log: AuditLog) -> None:
        self._registry = registry
        self._audit = audit_log

    # ------------------------------------------------------------------ api --
    def compile(self, request: QueryRequest, session: SessionContext) -> CompiledQuery:
        """Produce parameterised SQL, or raise a typed error. Always audits."""
        contract = self._registry.kpi(request.contract_id)
        policy = self._policy_for(contract, session)

        grain = self._validate_grain(contract, request.grain)
        measures = self._validate_measures(contract, request.measures)
        order_by = self._validate_order_by(grain, measures, request.order_by)

        parameters: dict[str, object] = {}
        row_filter = self._row_filter(policy, session, parameters)
        predicates = [row_filter] if row_filter else []
        predicates.extend(
            self._filter_predicate(contract, clause, index, parameters)
            for index, clause in enumerate(request.filters)
        )

        masked = sorted(set(policy.columns.mask) & set(measures))
        sql = self._render(
            contract=contract,
            grain=grain,
            measures=measures,
            masked=set(masked),
            predicates=predicates,
            order_by=order_by,
            limit=request.limit,
        )
        sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()

        self._audit.record(
            AuditRecord(
                run_id=session.run_id,
                event="compile",
                user_id=session.identity.user_id,
                role=session.role_name,
                intent=session.intent,
                contract_id=contract.kpi.id,
                contract_version=contract.contract_version,
                sql_hash=sql_hash,
                row_filter=row_filter,
                masked_columns=masked,
                outcome="ok",
            )
        )
        logger.info(
            "compiler.compiled",
            run_id=session.run_id,
            contract_id=contract.kpi.id,
            role=session.role_name,
            sql_hash=sql_hash[:12],
            masked=len(masked),
        )
        return CompiledQuery(
            contract_id=contract.kpi.id,
            contract_version=contract.contract_version,
            role=session.role_name,
            sql=sql,
            parameters=parameters,  # type: ignore[arg-type]  # values are FilterValue
            sql_hash=sql_hash,
            grain=grain,
            measures=measures,
            masked_columns=masked,
            row_filter=row_filter,
            national_headline=policy.national_headline,
        )

    # --------------------------------------------------------- entitlements --
    def _policy_for(self, contract: KPIContract, session: SessionContext) -> RolePolicy:
        """Resolve the caller's policy, denying by default and auditing the denial."""
        policy = contract.access.roles.get(session.role_name)
        if policy is None:
            reason = (
                f"Role {session.role_name!r} has no entitlement to "
                f"{contract.kpi.name} ({contract.access.classification}). "
                f"Request access from the data steward ({contract.kpi.data_steward})."
            )
            self._audit_denial(contract, session, reason)
            raise EntitlementError(
                f"{contract.kpi.id}: no policy for role {session.role_name!r}",
                reason=reason,
                contract_id=contract.kpi.id,
                role=session.role_name,
            )
        if policy.deny:
            reason = policy.reason or "Access denied by contract policy."
            self._audit_denial(contract, session, reason)
            raise EntitlementError(
                f"{contract.kpi.id}: denied for role {session.role_name!r}",
                reason=reason,
                contract_id=contract.kpi.id,
                role=session.role_name,
            )
        return policy

    def _audit_denial(self, contract: KPIContract, session: SessionContext, reason: str) -> None:
        """A refusal is as auditable as a result — arguably more so."""
        self._audit.record(
            AuditRecord(
                run_id=session.run_id,
                event="deny",
                user_id=session.identity.user_id,
                role=session.role_name,
                intent=session.intent,
                contract_id=contract.kpi.id,
                contract_version=contract.contract_version,
                outcome="denied",
                reason=reason,
            )
        )
        logger.info(
            "compiler.denied",
            run_id=session.run_id,
            contract_id=contract.kpi.id,
            role=session.role_name,
        )

    def _row_filter(
        self, policy: RolePolicy, session: SessionContext, parameters: dict[str, object]
    ) -> str | None:
        """Turn the contract's filter template into bound SQL.

        The template is contract-authored and validated at load; the values come
        from the session. A template naming a binding the session does not supply is
        a configuration error, never a silently-unfiltered query.
        """
        if policy.rows == "all":
            return None
        bindings = session.bindings
        names = _BIND_TOKEN.findall(policy.rows)
        if not names:
            raise CompilerError(f"row filter binds nothing: {policy.rows!r}")
        for name in names:
            if name not in bindings:
                raise CompilerError(
                    f"row filter needs session binding {name!r}",
                    detail=f"role {session.role_name!r} supplies {sorted(bindings)}",
                )
            parameters[name] = bindings[name]
        return _BIND_TOKEN.sub(lambda match: f"${match.group(1)}", policy.rows)

    # ------------------------------------------------------------ validation --
    @staticmethod
    def _validate_grain(contract: KPIContract, grain: list[str]) -> list[str]:
        """Every grain column must be in the contract's dimension allowlist."""
        allowed = set(contract.definition.dimensions)
        unknown = [column for column in grain if column not in allowed]
        if unknown:
            raise ContractError(
                f"{contract.kpi.id}: grain not permitted by contract: {unknown}",
                detail=f"allowed dimensions: {sorted(allowed)}",
            )
        if len(set(grain)) != len(grain):
            raise ContractError(f"{contract.kpi.id}: duplicate grain columns: {grain}")
        return list(grain)

    @staticmethod
    def _validate_measures(contract: KPIContract, measures: list[str]) -> list[str]:
        """Empty means the primary measure. Anything else must be declared."""
        if not measures:
            return [contract.kpi.id]
        allowed = {contract.kpi.id} | set(contract.calculation.derived_submetrics)
        unknown = [measure for measure in measures if measure not in allowed]
        if unknown:
            raise ContractError(
                f"{contract.kpi.id}: unknown measures: {unknown}",
                detail=f"allowed measures: {sorted(allowed)}",
            )
        return list(dict.fromkeys(measures))

    @staticmethod
    def _validate_order_by(grain: list[str], measures: list[str], order_by: list[str]) -> list[str]:
        """Ordering may only reference columns the query actually selects."""
        selectable = set(grain) | set(measures)
        unknown = [column for column in order_by if column not in selectable]
        if unknown:
            raise ContractError(f"order_by references unselected columns: {unknown}")
        return list(order_by)

    @staticmethod
    def _filter_predicate(
        contract: KPIContract,
        clause: FilterClause,
        index: int,
        parameters: dict[str, object],
    ) -> str:
        """Render one predicate with every value bound, never interpolated."""
        if clause.dimension not in set(contract.definition.dimensions):
            raise ContractError(
                f"{contract.kpi.id}: filter on undeclared dimension {clause.dimension!r}",
                detail=f"allowed dimensions: {sorted(contract.definition.dimensions)}",
            )
        expected = _VALUES_PER_OP[clause.op]
        if expected is not None and len(clause.values) != expected:
            raise ContractError(
                f"filter {clause.dimension!r} with op {clause.op!r} needs "
                f"{expected} value(s), got {len(clause.values)}"
            )

        def bind(position: int) -> str:
            name = f"f{index}_{position}"
            parameters[name] = clause.values[position]
            return f"${name}"

        if clause.op == "in":
            placeholders = ", ".join(bind(position) for position in range(len(clause.values)))
            return f"{clause.dimension} IN ({placeholders})"
        if clause.op == "between":
            return f"{clause.dimension} BETWEEN {bind(0)} AND {bind(1)}"
        return f"{clause.dimension} {_SQL_OP[clause.op]} {bind(0)}"

    # -------------------------------------------------------------- rendering --
    @staticmethod
    def _render(
        *,
        contract: KPIContract,
        grain: list[str],
        measures: list[str],
        masked: set[str],
        predicates: list[str],
        order_by: list[str],
        limit: int | None,
    ) -> str:
        """Assemble the statement. Every token here came from the contract."""
        expressions: dict[str, str] = {
            contract.kpi.id: contract.calculation.measure_sql,
            **contract.calculation.derived_submetrics,
        }
        select: list[str] = list(grain)
        for measure in measures:
            if measure in masked:
                # A masked measure never reaches the aggregation, so the value does
                # not exist even transiently in the result set.
                select.append(f"'{MASK_SENTINEL}' AS {measure}")
            else:
                select.append(f"{expressions[measure]} AS {measure}")

        parts = [
            "SELECT " + ", ".join(select),
            f"FROM {contract.calculation.source_view}",
        ]
        if predicates:
            parts.append("WHERE " + " AND ".join(predicates))
        if grain:
            parts.append("GROUP BY " + ", ".join(grain))
        if order_by:
            parts.append("ORDER BY " + ", ".join(order_by))
        if limit is not None:
            parts.append(f"LIMIT {int(limit)}")
        return "\n".join(parts)
