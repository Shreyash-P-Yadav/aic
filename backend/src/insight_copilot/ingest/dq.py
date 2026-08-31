"""Data-quality gates driven entirely by the source contracts. **Quarantine, never drop.**

Rows that fail an expectation go to ``meta.quarantine_rows`` with the rule that
caught them and the reason. They are visible, countable and they feed the DQ score
that depresses the ``c4`` data-trust confidence signal. Nothing is silently discarded,
because a pipeline that quietly deletes the rows it cannot explain is exactly how a
hundredfold unit error reaches a board pack.

Two severities, and the contract decides which applies:

* **Impossible** — a value outside a declared ``min``/``max``, a broken ``comparison``,
  a null in a column whose ``null_frac_max`` is zero, or a named expectation whose
  tolerated fraction is zero. These rows cannot be true, so they are quarantined.
  This is the gate that catches the silent paise-to-rupees change: every affected
  ``spend_inr`` exceeds the contract's declared ceiling by two orders of magnitude.
* **Tolerated** — a named expectation with a positive ``max_frac_violating``, or a
  positive ``null_frac_max``. The condition is known and survivable ("about one order
  in fifty has no region mapping"), so the rows flow and the *rate* is the finding.
  Above the tolerated fraction it becomes a warning that depresses data trust — but
  the rows are still usable, and quarantining them would invent a revenue dip that
  never happened.
"""

from __future__ import annotations

import pandas as pd

from insight_copilot.contracts.source_models import ColumnSpec, SourceContract
from insight_copilot.ingest.expectations import compile_comparison, predicate_for
from insight_copilot.ingest.models import DQResult, QuarantineRecord
from insight_copilot.logging import get_logger

logger = get_logger(__name__)


class DataQualityGate:
    """Evaluates one batch against its source contract's expectations.

    Deliberately stateless and free of I/O: a gate is a pure function of a contract
    and a frame, so every expectation can be tested against a five-row fixture with
    no warehouse in sight. Persisting the findings is :class:`DQStore`'s job.
    """

    def evaluate(
        self,
        contract: SourceContract,
        frame: pd.DataFrame,
        batch_id: str,
        *,
        coercion_failures: dict[str, int],
    ) -> tuple[list[DQResult], list[QuarantineRecord]]:
        """Run every declared gate. Returns findings and the rows to hold back."""
        results: list[DQResult] = []
        quarantine: list[QuarantineRecord] = []
        results.extend(self._row_count(contract, frame, batch_id))
        for name, count in sorted(coercion_failures.items()):
            results.append(
                self._result(
                    contract,
                    batch_id,
                    f"type:{name}",
                    "quarantine",
                    float(count),
                    0.0,
                    count,
                    f"{count} value(s) in {name!r} did not parse as "
                    f"{contract.schema_spec.columns[name].type}",
                )
            )
            quarantine.append(
                self._hold(
                    contract,
                    frame,
                    batch_id,
                    frame[name].isna(),
                    f"type:{name}",
                    f"unparseable {contract.schema_spec.columns[name].type}",
                )
            )
        for name, spec in contract.schema_spec.columns.items():
            self._column_gates(contract, frame, batch_id, name, spec, results, quarantine)
        self._comparison_gates(contract, frame, batch_id, results, quarantine)
        self._named_gates(contract, frame, batch_id, results, quarantine)
        return results, [record for record in quarantine if record.row_count > 0]

    # ----------------------------------------------------------------- gates --
    def _row_count(
        self, contract: SourceContract, frame: pd.DataFrame, batch_id: str
    ) -> list[DQResult]:
        """A batch far outside its expected size is a gap or a doubled export."""
        expectations = contract.expectations
        rows = len(frame)
        results: list[DQResult] = []
        if expectations.row_count_min is not None and rows < expectations.row_count_min:
            results.append(
                self._result(
                    contract,
                    batch_id,
                    "row_count_min",
                    "warn",
                    float(rows),
                    float(expectations.row_count_min),
                    0,
                    f"{rows} rows delivered, contract expects at least "
                    f"{expectations.row_count_min}",
                )
            )
        if expectations.row_count_max is not None and rows > expectations.row_count_max:
            results.append(
                self._result(
                    contract,
                    batch_id,
                    "row_count_max",
                    "warn",
                    float(rows),
                    float(expectations.row_count_max),
                    0,
                    f"{rows} rows delivered, contract expects at most {expectations.row_count_max}",
                )
            )
        return results

    def _column_gates(
        self,
        contract: SourceContract,
        frame: pd.DataFrame,
        batch_id: str,
        name: str,
        spec: ColumnSpec,
        results: list[DQResult],
        quarantine: list[QuarantineRecord],
    ) -> None:
        """Range, allowed-value and null-fraction gates for one declared column."""
        if name not in frame.columns or frame.empty:
            return
        values = frame[name]
        if spec.allowed is not None:
            outside = values.notna() & ~values.astype("string").isin(spec.allowed)
            if outside.any():
                results.append(
                    self._result(
                        contract,
                        batch_id,
                        f"allowed:{name}",
                        "quarantine",
                        float(outside.sum()),
                        0.0,
                        int(outside.sum()),
                        f"{int(outside.sum())} row(s) carry a {name!r} outside the "
                        f"contract's allowed set",
                    )
                )
                quarantine.append(
                    self._hold(
                        contract,
                        frame,
                        batch_id,
                        outside,
                        f"allowed:{name}",
                        "value outside the contract's allowed set",
                    )
                )
        if spec.min is not None or spec.max is not None:
            numeric = pd.to_numeric(values, errors="coerce")
            low = numeric < spec.min if spec.min is not None else pd.Series(False, frame.index)
            high = numeric > spec.max if spec.max is not None else pd.Series(False, frame.index)
            outside = (low | high).fillna(False)
            if outside.any():
                worst = float(numeric[outside].abs().max())
                results.append(
                    self._result(
                        contract,
                        batch_id,
                        f"range:{name}",
                        "quarantine",
                        worst,
                        spec.max if spec.max is not None else spec.min,
                        int(outside.sum()),
                        f"{int(outside.sum())} row(s) fall outside the declared range "
                        f"[{spec.min}, {spec.max}] for {name!r}; largest magnitude {worst:,.2f}",
                    )
                )
                quarantine.append(
                    self._hold(
                        contract,
                        frame,
                        batch_id,
                        outside,
                        f"range:{name}",
                        f"outside declared range [{spec.min}, {spec.max}]",
                    )
                )
        if spec.null_frac_max is not None:
            nulls = values.isna()
            fraction = float(nulls.mean())
            if spec.null_frac_max == 0.0 and nulls.any():
                results.append(
                    self._result(
                        contract,
                        batch_id,
                        f"nulls:{name}",
                        "quarantine",
                        fraction,
                        0.0,
                        int(nulls.sum()),
                        f"{name!r} may never be null; {int(nulls.sum())} were",
                    )
                )
                quarantine.append(
                    self._hold(
                        contract,
                        frame,
                        batch_id,
                        nulls,
                        f"nulls:{name}",
                        "null in a column declared non-nullable",
                    )
                )
            elif fraction > spec.null_frac_max:
                results.append(
                    self._result(
                        contract,
                        batch_id,
                        f"nulls:{name}",
                        "warn",
                        fraction,
                        spec.null_frac_max,
                        int(nulls.sum()),
                        f"{fraction:.1%} of {name!r} is null against a tolerated "
                        f"{spec.null_frac_max:.1%}",
                    )
                )

    def _comparison_gates(
        self,
        contract: SourceContract,
        frame: pd.DataFrame,
        batch_id: str,
        results: list[DQResult],
        quarantine: list[QuarantineRecord],
    ) -> None:
        """Declared row predicates. A broken one is an impossibility, so it quarantines."""
        columns = set(contract.schema_spec.columns)
        for expression in contract.expectations.comparisons:
            violating = compile_comparison(expression, columns)(frame)
            if not violating.any():
                continue
            results.append(
                self._result(
                    contract,
                    batch_id,
                    f"comparison:{expression}",
                    "quarantine",
                    float(violating.sum()),
                    0.0,
                    int(violating.sum()),
                    f"{int(violating.sum())} row(s) violate {expression!r}",
                )
            )
            quarantine.append(
                self._hold(
                    contract,
                    frame,
                    batch_id,
                    violating,
                    f"comparison:{expression}",
                    f"violates {expression}",
                )
            )

    def _named_gates(
        self,
        contract: SourceContract,
        frame: pd.DataFrame,
        batch_id: str,
        results: list[DQResult],
        quarantine: list[QuarantineRecord],
    ) -> None:
        """Named expectations with a tolerated fraction. See the module docstring."""
        if frame.empty:
            return
        for name, tolerance in sorted(contract.expectations.max_frac_violating.items()):
            violating = predicate_for(name)(frame).fillna(False)
            fraction = float(violating.mean())
            if tolerance == 0.0 and violating.any():
                results.append(
                    self._result(
                        contract,
                        batch_id,
                        name,
                        "quarantine",
                        fraction,
                        0.0,
                        int(violating.sum()),
                        f"{int(violating.sum())} row(s) meet {name!r}, which the contract "
                        f"declares impossible",
                    )
                )
                quarantine.append(
                    self._hold(
                        contract,
                        frame,
                        batch_id,
                        violating,
                        name,
                        "condition the contract declares impossible",
                    )
                )
            elif fraction > tolerance:
                results.append(
                    self._result(
                        contract,
                        batch_id,
                        name,
                        "warn",
                        fraction,
                        tolerance,
                        int(violating.sum()),
                        f"{fraction:.1%} of rows meet {name!r} against a tolerated {tolerance:.1%}",
                    )
                )

    # ---------------------------------------------------------------- helpers --
    @staticmethod
    def _result(
        contract: SourceContract,
        batch_id: str,
        expectation: str,
        outcome: str,
        observed: float | None,
        threshold: float | None,
        rows: int,
        detail: str,
    ) -> DQResult:
        return DQResult(
            source_id=contract.source_id,
            batch_id=batch_id,
            expectation=expectation,
            outcome=outcome,  # type: ignore[arg-type]  # Literal, fixed by every call site
            observed=observed,
            threshold=threshold,
            rows_affected=rows,
            detail=detail,
        )

    @staticmethod
    def _hold(
        contract: SourceContract,
        frame: pd.DataFrame,
        batch_id: str,
        mask: pd.Series,
        rule: str,
        reason: str,
    ) -> QuarantineRecord:
        """Build the quarantine record for a mask of offending rows."""
        selected = mask.fillna(False)
        hashes = (
            frame.loc[selected, "_row_hash"].astype(str).tolist()
            if "_row_hash" in frame.columns
            else []
        )
        logger.info(
            "dq.quarantined",
            source_id=contract.source_id,
            batch_id=batch_id,
            rule=rule,
            rows=int(selected.sum()),
        )
        return QuarantineRecord(
            source_id=contract.source_id,
            batch_id=batch_id,
            rule=rule,
            reason=reason,
            row_count=int(selected.sum()),
            row_hashes=hashes,
        )
