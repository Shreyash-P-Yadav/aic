"""Typed exception hierarchy.

WHY a hierarchy rather than bare ``Exception``: every failure in this system has a
governance meaning. An entitlement denial must be auditable and returned to the user
as a policy statement; a data-quality failure must quarantine rows and depress the
data-trust confidence signal; insufficient evidence is a *designed output*, not a
crash. Callers therefore need to discriminate on type, and ``except Exception`` is
never an acceptable way to do that.
"""

from __future__ import annotations


class InsightCopilotError(Exception):
    """Root of every error this application raises deliberately."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.message}: {self.detail}" if self.detail else self.message


class ConfigError(InsightCopilotError):
    """Settings or environment are internally inconsistent."""


class ContractError(InsightCopilotError):
    """A KPI or source contract is malformed, missing, or violated."""


class CompilerError(ContractError):
    """The contract-to-SQL compiler could not produce a safe query."""


class EntitlementError(InsightCopilotError):
    """The caller's role denies this data. Carries the policy reason verbatim."""

    def __init__(self, message: str, *, reason: str, contract_id: str, role: str) -> None:
        super().__init__(message, detail=reason)
        self.reason = reason
        self.contract_id = contract_id
        self.role = role


class ResourceNotFound(InsightCopilotError):
    """A named object does not exist. Distinct from a malformed request."""


class ServiceUnavailable(InsightCopilotError):
    """A dependency the caller needs has not been started or loaded yet.

    A cold start — an API up before the first backfill — is a documented state of this
    system, not an internal error, and it must not look like one to a client.
    """


class DataQualityError(InsightCopilotError):
    """A data-quality expectation failed hard enough to stop a load."""


class IngestionError(InsightCopilotError):
    """A batch could not be landed, parsed, or reconciled."""


class InsufficientEvidenceError(InsightCopilotError):
    """Evidence did not clear the floor. Callers convert this into an abstention."""


class StatisticalError(InsightCopilotError):
    """A statistical routine could not produce a trustworthy estimate."""


class LLMError(InsightCopilotError):
    """A model call failed, or its output failed validation."""


class VerificationError(LLMError):
    """Generated text contained a number or claim not supported by the bundle."""


class SimulationError(InsightCopilotError):
    """The data generator was asked for something it cannot produce."""
