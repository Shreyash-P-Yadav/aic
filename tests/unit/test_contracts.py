"""P1 gate — contracts load, validate, and cross-reference correctly.

These are governance tests. A contract that loads but means the wrong thing is worse
than one that fails to load, so most of these assert on semantics rather than shape.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from insight_copilot.contracts.loader import load_kpi_contract, load_source_contract
from insight_copilot.contracts.models import KPIContract
from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.contracts.source_models import SourceContract
from insight_copilot.errors import ContractError

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "backend/src/insight_copilot/contracts"

EXPECTED_KPIS = {
    "net_revenue",
    "unit_volume",
    "order_fill_rate",
    "marketing_spend",
    "blended_roas",
    "gross_margin_pct",
}
EXPECTED_SOURCES = {
    # full fidelity
    "oms_orders",
    "wms_fulfilment",
    "martech_weekly",
    "support_tickets",
    "competitor_prices",
    # lightweight
    "pim_products",
    "inventory_snapshots",
    "weather_daily",
    "holiday_calendar",
    # corpus only
    "news_articles",
    "pricing_memos",
}


@pytest.fixture(scope="module")
def registry() -> ContractRegistry:
    return ContractRegistry.from_directory(CONTRACTS_DIR)


# ------------------------------------------------------------------ loading --
def test_every_shipped_contract_loads(registry: ContractRegistry) -> None:
    assert set(registry.kpi_ids) == EXPECTED_KPIS
    assert set(registry.source_ids) == EXPECTED_SOURCES


def test_referential_integrity_holds(registry: ContractRegistry) -> None:
    """Every source ref, kpi_ref, feeds edge and masked column resolves."""
    registry.check_referential_integrity()


def test_unknown_kpi_names_the_valid_ones(registry: ContractRegistry) -> None:
    with pytest.raises(ContractError) as excinfo:
        registry.kpi("revenue")
    assert "net_revenue" in (excinfo.value.detail or "")


# ------------------------------------------------------- the brief's minimum --
def test_kpis_span_three_sources_with_different_grains_and_cadences(
    registry: ContractRegistry,
) -> None:
    """The brief's floor: 3-5 connected KPIs over 2-3 sources, mixed grain/cadence."""
    grains = {tuple(registry.kpi(k).definition.base_grain) for k in registry.kpi_ids}
    calendars = {registry.kpi(k).definition.calendar for k in registry.kpi_ids}
    primary_sources = {
        ref.source_id
        for k in registry.kpi_ids
        for ref in registry.kpi(k).sources
        if ref.role == "primary"
    }
    assert len(grains) >= 3, "KPIs must differ in grain, not only in name"
    assert len(calendars) >= 2, "fiscal, ISO-week and gregorian calendars must all appear"
    assert len(primary_sources) >= 3

    cadences = {registry.source(s).covers.period for s in registry.source_ids}
    assert {"previous_day", "previous_iso_week", "t_minus_2"} <= cadences


def test_kpis_are_connected_through_the_driver_dag(registry: ContractRegistry) -> None:
    """fill rate -> volume -> revenue, and spend -> revenue with a lag."""
    revenue = registry.kpi("net_revenue")
    driver_ids = {d.id for d in revenue.drivers.exogenous}
    assert {"fill_rate", "marketing_adstock", "price_index"} <= driver_ids

    fill_rate = registry.kpi("order_fill_rate")
    assert any(edge.kpi_ref == "net_revenue" for edge in fill_rate.drivers.feeds)

    adstock = next(d for d in revenue.drivers.exogenous if d.id == "marketing_adstock")
    assert adstock.lag_days == (0, 21), "the timing gate reads this window"
    assert adstock.adstock_half_life_days == 7


def test_mediators_are_excluded_from_a_total_effect(registry: ContractRegistry) -> None:
    """Conditioning on unit volume would block the effect being measured."""
    revenue = registry.kpi("net_revenue")
    admissible = {d.id for d in revenue.drivers.admissible_regressors("marketing_adstock")}
    assert "unit_volume" not in admissible
    assert "marketing_adstock" not in admissible
    assert "fill_rate" in admissible, "a non-mediator driver stays in the design matrix"


def test_gross_margin_is_the_masked_measure(registry: ContractRegistry) -> None:
    contract = registry.kpi("gross_margin_pct")
    assert "gross_margin_pct" in contract.access.roles["rsm_north"].columns.mask
    assert contract.access.roles["cfo"].columns.mask == []


def test_every_denying_policy_states_a_reason(registry: ContractRegistry) -> None:
    """A refusal the user cannot act on is a bug, not a policy."""
    for kpi_id in registry.kpi_ids:
        for role, policy in registry.kpi(kpi_id).access.roles.items():
            if policy.deny:
                assert policy.reason, f"{kpi_id}/{role} denies without a reason"


def test_blended_roas_hard_gates_include_reconciliation(registry: ContractRegistry) -> None:
    """This gate is what makes Scenario B abstain rather than attribute."""
    gates = registry.kpi("blended_roas").confidence_policy.hard_gates
    assert gates.reconciliation_within_tolerance is True
    assert gates.required_sources_fresh is True


# --------------------------------------------------------- source contracts --
def test_martech_declares_its_restatement_window(registry: ContractRegistry) -> None:
    martech = registry.source("martech_weekly")
    assert martech.restatement.expected is True
    assert martech.restatement.window_days == 14
    assert martech.restatement.policy == "supersede_by_batch"
    assert martech.history_available_months == 12, "retention caps this feed's history"


def test_external_sources_have_shorter_history_than_internal(registry: ContractRegistry) -> None:
    """A real analytical constraint: the confidence engine must know about it."""
    assert registry.source("competitor_prices").history_available_months == 14
    assert registry.source("oms_orders").history_available_months == 36


def test_pii_columns_are_declared_so_they_can_be_masked(registry: ContractRegistry) -> None:
    tickets = registry.source("support_tickets")
    assert set(tickets.schema_spec.pii_columns) >= {
        "body_text",
        "customer_name",
        "customer_email",
        "customer_phone",
    }


def test_unit_range_expectations_exist_to_catch_a_silent_unit_change(
    registry: ContractRegistry,
) -> None:
    """P8: paise -> rupees is a 100x jump; only a range expectation catches it."""
    spend = registry.source("martech_weekly").schema_spec.columns["spend_inr"]
    assert spend.min == 0
    assert spend.max is not None and spend.max > 0


def test_landing_wakes_only_dependent_kpis(registry: ContractRegistry) -> None:
    """Event-driven, not cron-driven: a MarTech drop must not re-scan fill rate."""
    woken = {c.kpi.id for c in registry.kpis_depending_on("martech_weekly")}
    assert woken == {"marketing_spend", "blended_roas"}
    assert "order_fill_rate" not in woken


# ------------------------------------------------------------- validation ---
def test_a_typo_in_a_yaml_key_is_rejected(tmp_path: Path) -> None:
    """extra='forbid' — a misspelled block must not silently fall back to defaults."""
    raw = yaml.safe_load((CONTRACTS_DIR / "kpi/net_revenue.yaml").read_text())
    raw["materiallity"] = raw.pop("materiality")
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ContractError) as excinfo:
        load_kpi_contract(path)
    assert "materiallity" in (excinfo.value.detail or "") or "materiality" in (
        excinfo.value.detail or ""
    )


def test_a_measure_expression_may_not_break_the_statement(tmp_path: Path) -> None:
    raw = yaml.safe_load((CONTRACTS_DIR / "kpi/net_revenue.yaml").read_text())
    raw["calculation"]["measure_sql"] = "SUM(units); DROP TABLE gold.fct_revenue_daily"
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ContractError):
        load_kpi_contract(path)


def test_a_row_filter_must_bind_a_session_value(tmp_path: Path) -> None:
    """A literal filter would hard-code one region into the policy for everyone."""
    raw = yaml.safe_load((CONTRACTS_DIR / "kpi/net_revenue.yaml").read_text())
    raw["access"]["roles"]["rsm_north"]["rows"] = "region = 'North'"
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ContractError):
        load_kpi_contract(path)


def test_contract_models_are_frozen() -> None:
    """A loaded contract is a governance record; nothing may mutate it in flight."""
    contract = load_kpi_contract(CONTRACTS_DIR / "kpi/net_revenue.yaml")
    assert isinstance(contract, KPIContract)
    with pytest.raises(Exception, match=r"frozen|immutable"):
        contract.contract_version = "9.9.9"  # type: ignore[misc]


def test_source_contract_watermark_must_be_delivered(tmp_path: Path) -> None:
    raw = yaml.safe_load((CONTRACTS_DIR / "source/oms_orders.yaml").read_text())
    raw["watermark"] = "not_a_column"
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ContractError):
        load_source_contract(path)


def test_source_contracts_are_the_11_built_feeds(registry: ContractRegistry) -> None:
    tiers = {registry.source(s).build_tier for s in registry.source_ids}
    assert tiers == {"full", "lightweight", "corpus_only"}
    full = [s for s in registry.source_ids if registry.source(s).build_tier == "full"]
    assert len(full) == 5
    assert isinstance(registry.source("oms_orders"), SourceContract)


def test_a_row_filter_may_only_bind_values_the_role_actually_carries(tmp_path: Path) -> None:
    """The intern has no region, so scoping the intern by region can never compile.

    This is the authoring bug this check exists for: at query time the compiler fails
    closed, which is safe but silent — the role ends up denied by accident rather than
    by decision, and nobody learns of it until someone runs that exact query. Catching
    it at validation time is the difference between a policy and a landmine.
    """
    raw = yaml.safe_load((CONTRACTS_DIR / "kpi/unit_volume.yaml").read_text())
    raw["access"]["roles"]["intern"]["rows"] = "region = :user_region"
    shutil.copytree(CONTRACTS_DIR / "kpi", tmp_path / "kpi")
    shutil.copytree(CONTRACTS_DIR / "source", tmp_path / "source")
    (tmp_path / "kpi/unit_volume.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ContractError) as excinfo:
        ContractRegistry.from_directory(tmp_path)
    detail = excinfo.value.detail or ""
    assert detail.splitlines() == [
        "unit_volume: row filter for role 'intern' binds 'user_region', "
        "which the role does not supply (it supplies [])"
    ]


def test_every_shipped_row_filter_binds_only_supplied_values(registry: ContractRegistry) -> None:
    """The real contracts pass the same check — no accidental denials in the build."""
    registry.check_referential_integrity()
