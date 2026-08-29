"""YAML → pydantic contract loading.

WHY a dedicated module rather than a ``model_validate(yaml.safe_load(...))`` call at
each site: contract files are the governance artefact a judge (or an auditor) reads,
so a malformed one must fail with the *filename* and the offending field, not with a
pydantic traceback rooted at an anonymous dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import ValidationError

from insight_copilot.contracts.models import KPIContract
from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.errors import ContractError

ContractT = TypeVar("ContractT", KPIContract, SourceContract)


def _read_yaml(path: Path) -> dict[str, object]:
    """Parse one YAML document, refusing anything that is not a mapping."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"{path.name}: not valid YAML", detail=str(exc)) from exc
    except OSError as exc:
        raise ContractError(f"{path.name}: could not be read", detail=str(exc)) from exc
    if not isinstance(raw, dict):
        raise ContractError(f"{path.name}: top level must be a mapping")
    return raw


def _describe(exc: ValidationError, path: Path) -> str:
    """Render pydantic errors as ``field.path: message`` lines a human can act on."""
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  {location}: {error['msg']}")
    return f"{path.name}:\n" + "\n".join(lines)


def load_contract(path: Path, model: type[ContractT]) -> ContractT:
    """Load and validate one contract file."""
    raw = _read_yaml(path)
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ContractError(
            f"{path.name}: contract failed validation", detail=_describe(exc, path)
        ) from exc


def load_kpi_contract(path: Path) -> KPIContract:
    """Load one KPI contract."""
    return load_contract(path, KPIContract)


def load_source_contract(path: Path) -> SourceContract:
    """Load one source contract."""
    return load_contract(path, SourceContract)


def discover(directory: Path) -> list[Path]:
    """Every ``.yaml`` in a contract directory, in a stable (sorted) order.

    Stable order matters: contract-validation output and the audit trail should not
    reorder between runs on machines whose filesystems enumerate differently.
    """
    if not directory.is_dir():
        raise ContractError(f"contract directory not found: {directory}")
    return sorted(directory.glob("*.yaml"))
