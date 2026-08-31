"""The predicates behind the source contracts' declared expectations.

Two families:

* **Comparisons** — ``"clicks <= impressions"``, written declaratively in the
  contract. Parsed here into a bounded expression over two declared columns. The
  parser accepts exactly ``<column> <operator> <column>`` and nothing else: a
  contract is data, and data must never become an evaluated expression.
* **Named expectations** — the keys of ``max_frac_violating``. Each is a business
  condition with a tolerated rate ("about one in fifty orders arrives with no region
  mapping"). They are implemented here rather than in the contract because they are
  *predicates*, not thresholds, and the tolerated rate — which is the governed part —
  stays in the YAML.

Every named expectation a shipped contract mentions must resolve, and the registry is
validated at pipeline construction. An unimplemented expectation name would otherwise
read as a passing gate, which is the one failure mode this file exists to prevent.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.errors import ContractError

Predicate = Callable[[pd.DataFrame], pd.Series]
"""Frame in, boolean mask of *violating* rows out. Pure; no I/O, no globals."""

COMPARISON = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*(<=|>=|<|>|==|!=)\s*([a-z][a-z0-9_]*)\s*$")

LOW_MATCH_CONFIDENCE = 0.70
"""Below this the competitor panel's fuzzy SKU match is not trustworthy enough to
link an observation to one of our SKUs. It is the same floor the evidence layer's
entity-link confidence uses, kept here as the ingestion-time view of it."""


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """A declared column, or an all-false mask when the batch did not deliver it."""
    if name not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[name]


def _missing(frame: pd.DataFrame, name: str) -> pd.Series:
    """Rows where a column is absent or null."""
    if name not in frame.columns:
        return pd.Series(True, index=frame.index)
    return frame[name].isna()


def _equals(frame: pd.DataFrame, name: str, value: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[name].astype("string").fillna("") == value


def _below(frame: pd.DataFrame, name: str, bound: float) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(False, index=frame.index)
    return pd.to_numeric(frame[name], errors="coerce").fillna(bound) < bound


NAMED_EXPECTATIONS: dict[str, Predicate] = {
    # oms_orders
    "unknown_region": lambda frame: _equals(frame, "region", "UNKNOWN"),
    "negative_price": lambda frame: _below(frame, "unit_price_net", 0.0),
    # wms_fulfilment
    "fill_rate_above_one": lambda frame: (
        pd.to_numeric(_column(frame, "units_shipped_ok"), errors="coerce").fillna(0)
        > pd.to_numeric(_column(frame, "units_ordered"), errors="coerce").fillna(0)
    ),
    # martech_weekly
    "spend_zero_with_positive_clicks": lambda frame: (
        (pd.to_numeric(_column(frame, "spend_inr"), errors="coerce").fillna(0) == 0)
        & (pd.to_numeric(_column(frame, "clicks"), errors="coerce").fillna(0) > 0)
    ),
    # support_tickets
    "untagged_category": lambda frame: (
        _missing(frame, "category") | _equals(frame, "category", "UNKNOWN")
    ),
    # competitor_prices
    "low_match_confidence": lambda frame: _below(frame, "match_confidence", LOW_MATCH_CONFIDENCE),
    "delisted_gap": lambda frame: _missing(frame, "observed_price_inr"),
    # pim_products
    "unknown_category": lambda frame: _equals(frame, "category", "UNKNOWN"),
    "missing_cost": lambda frame: _missing(frame, "unit_cost"),
    # inventory_snapshots
    "negative_on_hand": lambda frame: _below(frame, "on_hand_units", 0.0),
    # pricing_memos
    "missing_end_date": lambda frame: _missing(frame, "end_date"),
    "late_entry": lambda frame: (
        pd.to_datetime(_column(frame, "publish_date"), errors="coerce")
        > pd.to_datetime(_column(frame, "effective_date"), errors="coerce")
    ),
}


def predicate_for(name: str) -> Predicate:
    """Resolve a named expectation, or fail loudly."""
    try:
        return NAMED_EXPECTATIONS[name]
    except KeyError as exc:
        raise ContractError(
            f"no predicate implements the expectation {name!r}",
            detail=f"implemented: {', '.join(sorted(NAMED_EXPECTATIONS))}",
        ) from exc


def compile_comparison(expression: str, columns: set[str]) -> Predicate:
    """Turn ``"clicks <= impressions"`` into a mask of the rows that violate it."""
    match = COMPARISON.match(expression)
    if match is None:
        raise ContractError(
            f"comparison must be '<column> <op> <column>': {expression!r}",
            detail="permitted operators: <= >= < > == !=",
        )
    left, operator, right = match.groups()
    unknown = {left, right} - columns
    if unknown:
        raise ContractError(f"comparison {expression!r} names undeclared columns {sorted(unknown)}")

    def violating(frame: pd.DataFrame) -> pd.Series:
        if left not in frame.columns or right not in frame.columns:
            return pd.Series(False, index=frame.index)
        lhs, rhs = _comparable(frame[left]), _comparable(frame[right])
        holds = _apply(lhs, operator, rhs)
        # A null on either side cannot violate a comparison; it is a null-fraction
        # finding, and counting it twice would double-penalise the same row.
        return ~holds & lhs.notna() & rhs.notna()

    return violating


def _comparable(values: pd.Series) -> pd.Series:
    """Numeric where possible, datetime otherwise — the two orderings contracts use."""
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any() or values.isna().all():
        return numeric
    return pd.to_datetime(values, errors="coerce", format="mixed")


def _apply(lhs: pd.Series, operator: str, rhs: pd.Series) -> pd.Series:
    """The five orderings and equality, dispatched without ``eval``."""
    if operator == "<=":
        return lhs <= rhs
    if operator == ">=":
        return lhs >= rhs
    if operator == "<":
        return lhs < rhs
    if operator == ">":
        return lhs > rhs
    if operator == "==":
        return lhs == rhs
    return lhs != rhs


def validate_registry(registry: ContractRegistry) -> None:
    """Every expectation every contract names must resolve. Called at construction."""
    problems: list[str] = []
    for source_id in registry.source_ids:
        contract = registry.source(source_id)
        columns = set(contract.schema_spec.columns)
        for name in contract.expectations.max_frac_violating:
            if name not in NAMED_EXPECTATIONS:
                problems.append(f"{source_id}: no predicate for expectation {name!r}")
        for expression in contract.expectations.comparisons:
            try:
                compile_comparison(expression, columns)
            except ContractError as exc:
                problems.append(f"{source_id}: {exc}")
    if problems:
        raise ContractError(
            f"{len(problems)} unimplemented expectation(s)", detail="\n".join(problems)
        )
