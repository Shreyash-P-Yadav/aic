"""A realistic Scenario A bundle for the P8 gate, built from the numbers P6 measured."""

from __future__ import annotations

import datetime as dt

from insight_copilot.config import Settings
from insight_copilot.engine.bundle import (
    ActionFact,
    ConfidenceFact,
    DriverFact,
    EvidenceFact,
    FreshnessFact,
    InsightEvidenceBundle,
    LineageStep,
    NumberFact,
    SegmentFact,
)

NOW = dt.datetime(2026, 3, 29, 9, 0, tzinfo=dt.UTC)


def mock_settings() -> Settings:
    """Offline settings. No key, no network, deterministic."""
    return Settings(
        llm_provider="mock",
        anthropic_api_key=None,
        _env_file=None,  # type: ignore[call-arg]
    )


def make_bundle() -> InsightEvidenceBundle:
    """Scenario A as the P6 gate measured it, in bundle form."""
    observed = 136_007_333.0
    counterfactual = 158_198_000.0
    delta = observed - counterfactual
    delta_pct = 100.0 * delta / counterfactual
    return InsightEvidenceBundle(
        insight_id="p8fixture001",
        kpi_id="net_revenue",
        contract_version="1.2.0",
        computed_at=NOW,
        period_start=dt.date(2026, 3, 9),
        period_end=dt.date(2026, 3, 15),
        watermark="2026-03-27",
        observed=observed,
        counterfactual=counterfactual,
        delta=delta,
        delta_pct=delta_pct,
        detection_method="conformal_ar_innovation",
        p_value=0.0039,
        numbers=[
            NumberFact(key="observed", value=observed, unit="INR", method="gold mart"),
            NumberFact(
                key="counterfactual",
                value=counterfactual,
                unit="INR",
                method="regression baseline",
            ),
            NumberFact(key="delta", value=delta, unit="INR", method="observed - counterfactual"),
            NumberFact(
                key="delta_pct", value=delta_pct, unit="pct", method="delta / counterfactual"
            ),
            NumberFact(key="p_value", value=0.0039, unit="probability", method="conformal"),
            NumberFact(key="price_effect", value=-926_696.0, unit="INR", method="Bennet indicator"),
            NumberFact(
                key="volume_effect", value=22_614_746.0, unit="INR", method="Bennet indicator"
            ),
            NumberFact(key="mix_effect", value=2_338_307.0, unit="INR", method="Bennet indicator"),
            NumberFact(
                key="top_segment_ep",
                value=0.507,
                unit="fraction",
                method="Adtributor explanatory power",
            ),
            NumberFact(
                key="top_segment_stability",
                value=0.96,
                unit="fraction",
                method="bootstrap win rate",
            ),
            NumberFact(key="explained_fraction", value=0.62, unit="fraction", method="model R^2"),
            NumberFact(
                key="unexplained_fraction", value=0.38, unit="fraction", method="1 - explained"
            ),
            NumberFact(
                key="fill_rate_coefficient", value=0.68, unit="elasticity", method="OLS-HAC"
            ),
            NumberFact(key="fill_rate_low", value=0.268, unit="elasticity", method="95% interval"),
            NumberFact(key="fill_rate_high", value=1.092, unit="elasticity", method="95% interval"),
            NumberFact(key="driver_agreement", value=0.97, unit="fraction", method="cross-check"),
            NumberFact(key="calibrated", value=0.72, unit="probability", method="softmin"),
            NumberFact(
                key="confidence_level",
                value=95.0,
                unit="pct",
                method="the interval convention every estimate here is reported at",
            ),
            NumberFact(
                key="action_impact", value=9_500_000.0, unit="INR", method="elasticity x lever"
            ),
            NumberFact(key="action_impact_low", value=3_700_000.0, unit="INR", method="interval"),
            NumberFact(key="action_impact_high", value=15_300_000.0, unit="INR", method="interval"),
        ],
        segments=[
            SegmentFact(
                label="region=North",
                actual=32_100_000.0,
                forecast=37_500_000.0,
                explanatory_power=0.507,
                surprise=0.00021,
                stability=0.96,
            ),
            SegmentFact(
                label="channel=quick_commerce",
                actual=29_400_000.0,
                forecast=31_200_000.0,
                explanatory_power=0.188,
                surprise=0.00006,
                stability=0.21,
            ),
        ],
        price_effect=-926_696.0,
        volume_effect=22_614_746.0,
        mix_effect=2_338_307.0,
        drivers=[
            DriverFact(
                driver_id="fill_rate",
                coefficient=0.68,
                interval_low=0.268,
                interval_high=1.092,
                p_value=0.001,
                agreement=0.97,
            )
        ],
        explained_fraction=0.62,
        unexplained_fraction=0.38,
        evidence=[
            EvidenceFact(
                doc_id="DOC-OPS-0001",
                kind="ops_incident",
                title="DC-North pick capacity failure",
                publish_date=dt.date(2026, 3, 6),
                effective_date=dt.date(2026, 3, 6),
                source_tier=1,
                confidence=0.82,
                independence_key="DOC-OPS-0001",
                matched_on="publish_date",
            ),
            EvidenceFact(
                doc_id="DOC-MEMO-0001",
                kind="pricing_memo",
                title="Haircare list price revision",
                publish_date=dt.date(2026, 1, 20),
                effective_date=dt.date(2026, 3, 1),
                source_tier=1,
                confidence=0.71,
                independence_key="DOC-MEMO-0001",
                matched_on="effective_date",
            ),
        ],
        evidence_corroboration=0.79,
        confidence=ConfidenceFact(
            signals={
                "c1_detection": 0.88,
                "c2_attribution": 0.66,
                "c3_statistical": 0.81,
                "c4_data_trust": 0.94,
                "c5_evidence": 0.75,
                "c6_narrative": 1.0,
            },
            signal_detail={
                "c1_detection": "conformal p = 0.0039",
                "c2_attribution": "bootstrap win rate 0.96 x coverage 0.685",
                "c3_statistical": "Ljung-Box p = 0.125; estimator agreement 0.97",
                "c4_data_trust": "stale required sources: none",
                "c5_evidence": "noisy-OR corroboration 0.79 across 2 independent sources",
                "c6_narrative": "verifier passed 100% of generated claims",
            },
            composite=0.72,
            calibrated=0.72,
            calibration_fitted=False,
            tier="Moderate",
            weakest_signal="c2_attribution",
        ),
        actions=[
            ActionFact(
                action_id="reroute_to_cross_serving_dc",
                driver_id="fill_rate",
                lever="replenishment",
                title="Reroute affected demand to the cross-serving DC",
                expected_impact_central=9_500_000.0,
                expected_impact_low=3_700_000.0,
                expected_impact_high=15_300_000.0,
                owner_role="supply_chain_director",
                needs_approval=True,
                monitoring_kpi="order_fill_rate",
                monitoring_checkpoints=[1, 3, 7],
                success_threshold_pct=92.0,
                earliest_effect=dt.date(2026, 3, 30),
            )
        ],
        freshness=[
            FreshnessFact(
                source_id="oms_orders",
                state="green",
                age_hours=7.0,
                sla_hours=6.0,
                latest_period="2026-03-27",
            )
        ],
        lineage=[
            LineageStep(
                stage="mart",
                frm="silver.oms_orders",
                to="gold.fct_revenue_daily",
                transform="ingest/gold.py",
            )
        ],
    )
