"""Shared pytest fixtures.

WHY settings are overridden per-test rather than read from ``.env``: a developer's
local ``.env`` must never change a test outcome, and ``LLM_PROVIDER=mock`` has to be
the guaranteed default so the suite runs offline.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from insight_copilot.config import Settings, get_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings writing every artefact under a per-test temp directory."""
    return Settings(
        environment="test",
        llm_provider="mock",
        data_dir=tmp_path / "data",
        warehouse_path=tmp_path / "data" / "warehouse.duckdb",
        landing_dir=tmp_path / "data" / "landing",
        artifacts_dir=tmp_path / "artifacts",
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings init kwarg
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Keep the cached process settings from leaking between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
