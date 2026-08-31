"""Single source of runtime configuration.

WHY pydantic-settings and one module-level instance: the build standard forbids
module-level singletons *except* settings and the logger, because every other
collaborator is injected for testability. Configuration is the one thing that is
genuinely process-global, and typing it means a bad ``.env`` fails at import time
with a readable error rather than deep inside a statistical routine.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
"""Repository root: .../backend/src/insight_copilot/config.py -> up three."""

LLMProviderName = Literal["mock", "anthropic"]
ClockMode = Literal["backfill", "replay", "live", "step"]


class Settings(BaseSettings):
    """Every tunable that is environmental rather than analytical.

    Analytical thresholds do NOT live here — they live in KPI contracts, so the
    business can change them without a code change or a redeploy.
    """

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # --- identity / environment -------------------------------------------------
    app_name: str = "Insight Copilot"
    environment: Literal["dev", "test", "demo"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    # --- paths ------------------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    warehouse_path: Path = REPO_ROOT / "data" / "warehouse.duckdb"
    landing_dir: Path = REPO_ROOT / "data" / "landing"
    artifacts_dir: Path = REPO_ROOT / "artifacts"
    contracts_dir: Path = Path(__file__).resolve().parent / "contracts"

    # --- simulation -------------------------------------------------------------
    seed: int = 20260329
    """Master seed. Every draw is content-addressed from it (see datagen.world.seeds)."""

    sim_start: str = "2023-09-01"
    sim_end: str = "2026-08-31"
    sim_today: str = "2026-03-29"
    """Demo 'now'. Late March 2026 leaves five months of post-scenario data for backtesting."""

    timezone: str = "Asia/Kolkata"
    clock_mode: ClockMode = "backfill"
    replay_speed: float = 43200.0
    """Sim-seconds per wall-second in replay mode. 43200 => 1 sim-day per 2 s."""

    # --- LLM --------------------------------------------------------------------
    llm_provider: LLMProviderName = "mock"
    """``mock`` must run the entire application end to end with no API key and no network."""

    anthropic_api_key: str | None = None
    llm_model_small: str = "claude-haiku-4-5-20251001"
    llm_model_mid: str = "claude-sonnet-5"
    llm_max_output_tokens: int = 1400
    llm_temperature: float = 0.0
    llm_cost_cap_usd_per_insight: float = 0.05
    """Breaching this downshifts the model tier and logs the downgrade."""

    # --- optional, feature-flagged (never required) -----------------------------
    enable_dense_retrieval: bool = False
    enable_nli_entailment: bool = False

    # --- api --------------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so ``.env`` stays readable."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def ensure_dirs(self) -> None:
        """Create the writable directories this process expects. Idempotent."""
        for path in (self.data_dir, self.landing_dir, self.artifacts_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, cached so ``.env`` is read exactly once."""
    return Settings()
