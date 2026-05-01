"""Tests for tprr.sensitivity.recompute — Phase 10 Batch 10A.

Three contracts:

1. **Identity**: ``recompute_indices_under_override(orig_audit, orig_indices,
   orig_config)`` returns frames numerically equivalent to the original
   pipeline outputs. Floating-point equality within a tight tolerance.
2. **Equivalence vs pipeline rerun**: recompute under a perturbed config
   matches a fresh ``run_full_pipeline`` at that perturbed config.
3. **Schema invariant**: output IndexValueDF dtypes match the original's
   column-for-column. Phase 11 writeup joins across sweeps; schema drift
   is a contract violation.

Fixtures cover three audit shapes (Batch 10A scope locked with Matt):
- ``multi_tier_clean``: 10 days, 3-tier coverage on every constituent
- ``single_tier_only``: 10 days, Tier A only — exercises the
  ``redistribute_blending_coefficients`` single-tier branch
- ``with_suspended_days``: 10 days where some days are tier-suspended via
  insufficient_constituents — exercises the suspension passthrough
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tprr.config import (
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
    TierBRevenueEntry,
)
from tprr.index.compute import run_full_pipeline
from tprr.index.weights import TierBVolumeFn
from tprr.schema import AttestationTier, Tier
from tprr.sensitivity.recompute import (
    CORE_INDEX_CODES,
    recompute_indices_under_override,
    with_overrides,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _registry_three_tiers() -> ModelRegistry:
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=p_in,
                baseline_output_price_usd_mtok=p_out,
            )
            for cid, tier, p_in, p_out in [
                ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
                ("anthropic/claude-opus-4-7", Tier.TPRR_F, 14.0, 70.0),
                ("google/gemini-3-pro", Tier.TPRR_F, 5.0, 30.0),
                ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
                ("anthropic/claude-haiku-4-5", Tier.TPRR_S, 1.0, 5.0),
                ("google/gemini-2-flash", Tier.TPRR_S, 0.3, 2.5),
                ("google/gemini-flash-lite", Tier.TPRR_E, 0.1, 0.4),
                ("openai/gpt-5-nano", Tier.TPRR_E, 0.15, 0.6),
                ("deepseek/deepseek-v3-2", Tier.TPRR_E, 0.25, 1.0),
            ]
        ]
    )


def _stub_tier_b_volume_fn(value: float = 0.0) -> TierBVolumeFn:
    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return value

    return _fn


def _empty_change_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_date",
            "contributor_id",
            "constituent_id",
            "change_slot_idx",
            "old_input_price_usd_mtok",
            "new_input_price_usd_mtok",
            "old_output_price_usd_mtok",
            "new_output_price_usd_mtok",
            "reason",
        ]
    )


def _row(
    *,
    cid: str,
    contrib: str,
    d: date,
    twap_out: float,
    twap_in: float,
    volume: float,
    tier: Tier,
    attestation: AttestationTier = AttestationTier.A,
) -> dict[str, Any]:
    ts = pd.Timestamp(d)
    return {
        "observation_date": ts,
        "constituent_id": cid,
        "contributor_id": contrib,
        "tier_code": tier.value,
        "attestation_tier": attestation.value,
        "input_price_usd_mtok": float(twap_in),
        "output_price_usd_mtok": float(twap_out),
        "volume_mtok_7d": float(volume),
        "twap_output_usd_mtok": float(twap_out),
        "twap_input_usd_mtok": float(twap_in),
        "source": "test",
        "submitted_at": ts,
        "notes": "",
    }


def _multi_tier_clean_panel(n_days: int = 10) -> pd.DataFrame:
    """3 F + 3 S + 3 E constituents x 3 contributors x n_days, Tier A + Tier C."""
    start = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    f_set = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    s_set = [
        ("openai/gpt-5-mini", 4.0, 0.5),
        ("anthropic/claude-haiku-4-5", 5.0, 1.0),
        ("google/gemini-2-flash", 2.5, 0.3),
    ]
    e_set = [
        ("google/gemini-flash-lite", 0.4, 0.1),
        ("openai/gpt-5-nano", 0.6, 0.15),
        ("deepseek/deepseek-v3-2", 1.0, 0.25),
    ]
    for offset in range(n_days):
        d = start + timedelta(days=offset)
        for tier_set, tier in [
            (f_set, Tier.TPRR_F),
            (s_set, Tier.TPRR_S),
            (e_set, Tier.TPRR_E),
        ]:
            for cid, p_out, p_in in tier_set:
                for contrib in ["c1", "c2", "c3"]:
                    rows.append(
                        _row(
                            cid=cid,
                            contrib=contrib,
                            d=d,
                            twap_out=p_out,
                            twap_in=p_in,
                            volume=100.0,
                            tier=tier,
                        )
                    )
                # Tier C row per constituent (single contributor, larger volume).
                rows.append(
                    _row(
                        cid=cid,
                        contrib=f"openrouter:{cid.split('/')[0]}",
                        d=d,
                        twap_out=p_out * 1.02,  # slight Tier C drift
                        twap_in=p_in * 1.02,
                        volume=5_000.0,
                        tier=tier,
                        attestation=AttestationTier.C,
                    )
                )
    return pd.DataFrame(rows)


def _tier_b_config_three_providers() -> TierBRevenueConfig:
    return TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider=p,
                period="2025-Q1",
                amount_usd=1_000_000_000.0,
                source="test",
            )
            for p in ("openai", "anthropic", "google", "deepseek")
        ]
    )


def _config_default(base_date: date = date(2025, 1, 1)) -> IndexConfig:
    return IndexConfig(base_date=base_date)


# ---------------------------------------------------------------------------
# Identity contract — recompute at orig config matches pipeline output
# ---------------------------------------------------------------------------


def test_recompute_identity_multi_tier_clean() -> None:
    panel = _multi_tier_clean_panel(n_days=10)
    config = _config_default(date(2025, 1, 1))
    pipeline = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=config,
        registry=_registry_three_tiers(),
        tier_b_config=_tier_b_config_three_providers(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=10_000.0),
    )

    recomputed = recompute_indices_under_override(
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        new_config=config,
    )

    assert set(recomputed.keys()) == set(pipeline.indices.keys())
    for code, original in pipeline.indices.items():
        new_df = recomputed[code]
        assert len(new_df) == len(original), f"{code}: row count mismatch"
        assert (new_df["suspended"].to_numpy() == original["suspended"].to_numpy()).all(), (
            f"{code}: suspension shape mismatch"
        )
        np.testing.assert_allclose(
            new_df["raw_value_usd_mtok"].to_numpy(),
            original["raw_value_usd_mtok"].to_numpy(),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
            err_msg=f"{code}: raw_value drift",
        )
        np.testing.assert_allclose(
            new_df["index_level"].to_numpy(),
            original["index_level"].to_numpy(),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
            err_msg=f"{code}: index_level drift",
        )


def test_recompute_identity_single_tier_only() -> None:
    """Tier A only — exercises ``redistribute_blending_coefficients`` single-tier
    branch. No Tier B revenue config; Tier B volume fn returns 0; Tier C
    panel rows omitted.
    """
    start = date(2025, 1, 1)
    panel_rows: list[dict[str, Any]] = []
    for offset in range(10):
        d = start + timedelta(days=offset)
        for cid, p_out, p_in, tier in [
            ("openai/gpt-5-pro", 75.0, 15.0, Tier.TPRR_F),
            ("anthropic/claude-opus-4-7", 70.0, 14.0, Tier.TPRR_F),
            ("google/gemini-3-pro", 30.0, 5.0, Tier.TPRR_F),
        ]:
            for contrib in ["c1", "c2", "c3"]:
                panel_rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_out,
                        twap_in=p_in,
                        volume=100.0,
                        tier=tier,
                    )
                )
    panel = pd.DataFrame(panel_rows)
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=Tier.TPRR_F,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=p_in,
                baseline_output_price_usd_mtok=p_out,
            )
            for cid, p_out, p_in in [
                ("openai/gpt-5-pro", 75.0, 15.0),
                ("anthropic/claude-opus-4-7", 70.0, 14.0),
                ("google/gemini-3-pro", 30.0, 5.0),
            ]
        ]
    )
    config = _config_default(date(2025, 1, 1))
    pipeline = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=config,
        registry=registry,
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=0.0),
    )
    recomputed = recompute_indices_under_override(
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        new_config=config,
    )
    f_orig = pipeline.indices["TPRR_F"]
    f_new = recomputed["TPRR_F"]
    np.testing.assert_allclose(
        f_new["raw_value_usd_mtok"].to_numpy(),
        f_orig["raw_value_usd_mtok"].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )


def test_recompute_identity_with_suspended_days() -> None:
    """Insufficient-constituents suspension days pass through unchanged."""
    start = date(2025, 1, 1)
    panel_rows: list[dict[str, Any]] = []
    for offset in range(10):
        d = start + timedelta(days=offset)
        # Only 2 F constituents (below min=3) → tier suspends every day.
        for cid, p_out, p_in in [
            ("openai/gpt-5-pro", 75.0, 15.0),
            ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ]:
            for contrib in ["c1", "c2", "c3"]:
                panel_rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_out,
                        twap_in=p_in,
                        volume=100.0,
                        tier=Tier.TPRR_F,
                    )
                )
        # Full S, E coverage so those tiers compute.
        for cid, p_out, p_in in [
            ("openai/gpt-5-mini", 4.0, 0.5),
            ("anthropic/claude-haiku-4-5", 5.0, 1.0),
            ("google/gemini-2-flash", 2.5, 0.3),
        ]:
            for contrib in ["c1", "c2", "c3"]:
                panel_rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_out,
                        twap_in=p_in,
                        volume=100.0,
                        tier=Tier.TPRR_S,
                    )
                )
        for cid, p_out, p_in in [
            ("google/gemini-flash-lite", 0.4, 0.1),
            ("openai/gpt-5-nano", 0.6, 0.15),
            ("deepseek/deepseek-v3-2", 1.0, 0.25),
        ]:
            for contrib in ["c1", "c2", "c3"]:
                panel_rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_out,
                        twap_in=p_in,
                        volume=100.0,
                        tier=Tier.TPRR_E,
                    )
                )
    panel = pd.DataFrame(panel_rows)
    config = _config_default(date(2025, 1, 1))
    pipeline = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=config,
        registry=_registry_three_tiers(),
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=0.0),
    )
    f_orig = pipeline.indices["TPRR_F"]
    assert f_orig["suspended"].all()  # every F day suspended

    recomputed = recompute_indices_under_override(
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        new_config=config,
    )
    f_new = recomputed["TPRR_F"]
    assert f_new["suspended"].all()
    assert (f_new["suspension_reason"].to_numpy() == f_orig["suspension_reason"].to_numpy()).all()
    # S and E should match exactly under identity recompute.
    for code in ("TPRR_S", "TPRR_E"):
        np.testing.assert_allclose(
            recomputed[code]["raw_value_usd_mtok"].to_numpy(),
            pipeline.indices[code]["raw_value_usd_mtok"].to_numpy(),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        )


# ---------------------------------------------------------------------------
# Equivalence vs pipeline rerun — recompute under perturbed config
# ---------------------------------------------------------------------------


def _run_pipeline_at(config: IndexConfig) -> Any:
    panel = _multi_tier_clean_panel(n_days=10)
    return run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=config,
        registry=_registry_three_tiers(),
        tier_b_config=_tier_b_config_three_providers(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=10_000.0),
    )


@pytest.mark.parametrize("new_lambda", [1.0, 2.0, 5.0, 10.0])
def test_recompute_lambda_matches_pipeline_rerun(new_lambda: float) -> None:
    base_config = _config_default(date(2025, 1, 1))
    base = _run_pipeline_at(base_config)
    target_config = with_overrides(base_config, lambda_=new_lambda)
    target = _run_pipeline_at(target_config)
    recomputed = recompute_indices_under_override(
        constituent_decisions=base.constituent_decisions,
        original_indices=base.indices,
        new_config=target_config,
    )
    for code in CORE_INDEX_CODES:
        if base.indices[code].empty:
            continue
        np.testing.assert_allclose(
            recomputed[code]["raw_value_usd_mtok"].to_numpy(),
            target.indices[code]["raw_value_usd_mtok"].to_numpy(),
            rtol=1e-10,
            atol=1e-10,
            equal_nan=True,
            err_msg=f"{code} @ λ={new_lambda}: raw_value drift vs pipeline rerun",
        )


@pytest.mark.parametrize("haircut_b", [0.4, 0.5, 0.6, 0.7])
def test_recompute_haircut_matches_pipeline_rerun(haircut_b: float) -> None:
    base_config = _config_default(date(2025, 1, 1))
    base = _run_pipeline_at(base_config)
    target_config = with_overrides(
        base_config,
        tier_haircuts={
            AttestationTier.A: 1.0,
            AttestationTier.B: haircut_b,
            AttestationTier.C: 0.8,
        },
    )
    target = _run_pipeline_at(target_config)
    recomputed = recompute_indices_under_override(
        constituent_decisions=base.constituent_decisions,
        original_indices=base.indices,
        new_config=target_config,
    )
    for code in CORE_INDEX_CODES:
        if base.indices[code].empty:
            continue
        np.testing.assert_allclose(
            recomputed[code]["raw_value_usd_mtok"].to_numpy(),
            target.indices[code]["raw_value_usd_mtok"].to_numpy(),
            rtol=1e-10,
            atol=1e-10,
            equal_nan=True,
            err_msg=f"{code} @ haircut_b={haircut_b}: raw_value drift",
        )


@pytest.mark.parametrize(
    "coefs",
    [
        {AttestationTier.A: 0.5, AttestationTier.B: 0.15, AttestationTier.C: 0.35},
        {AttestationTier.A: 0.7, AttestationTier.B: 0.10, AttestationTier.C: 0.20},
        {AttestationTier.A: 0.6, AttestationTier.B: 0.20, AttestationTier.C: 0.20},
    ],
)
def test_recompute_coefficients_match_pipeline_rerun(
    coefs: dict[AttestationTier, float],
) -> None:
    base_config = _config_default(date(2025, 1, 1))
    base = _run_pipeline_at(base_config)
    target_config = with_overrides(base_config, tier_blending_coefficients=coefs)
    target = _run_pipeline_at(target_config)
    recomputed = recompute_indices_under_override(
        constituent_decisions=base.constituent_decisions,
        original_indices=base.indices,
        new_config=target_config,
    )
    for code in CORE_INDEX_CODES:
        if base.indices[code].empty:
            continue
        np.testing.assert_allclose(
            recomputed[code]["raw_value_usd_mtok"].to_numpy(),
            target.indices[code]["raw_value_usd_mtok"].to_numpy(),
            rtol=1e-10,
            atol=1e-10,
            equal_nan=True,
            err_msg=f"{code} @ coefs={coefs}: raw_value drift",
        )


# ---------------------------------------------------------------------------
# Schema invariant
# ---------------------------------------------------------------------------


def test_recompute_preserves_index_value_schema() -> None:
    config = _config_default(date(2025, 1, 1))
    base = _run_pipeline_at(config)
    target_config = with_overrides(config, lambda_=2.0)
    recomputed = recompute_indices_under_override(
        constituent_decisions=base.constituent_decisions,
        original_indices=base.indices,
        new_config=target_config,
    )
    for code, original in base.indices.items():
        new_df = recomputed[code]
        assert list(new_df.columns) == list(original.columns), f"{code}: columns differ"
        for col in original.columns:
            assert new_df[col].dtype == original[col].dtype, (
                f"{code}.{col}: dtype {new_df[col].dtype!r} != {original[col].dtype!r}"
            )


# ---------------------------------------------------------------------------
# with_overrides helper contract
# ---------------------------------------------------------------------------


def test_with_overrides_no_change_returns_copy() -> None:
    base = _config_default()
    out = with_overrides(base)
    assert out.lambda_ == base.lambda_
    assert out.tier_haircuts == base.tier_haircuts
    assert out is not base  # model_copy returns a new instance


def test_with_overrides_substitutes_only_supplied_fields() -> None:
    base = _config_default()
    out = with_overrides(base, lambda_=1.5)
    assert out.lambda_ == 1.5
    assert out.tier_haircuts == base.tier_haircuts
    assert out.tier_blending_coefficients == base.tier_blending_coefficients


def test_with_overrides_replaces_haircut_dict_entirely() -> None:
    base = _config_default()
    out = with_overrides(
        base,
        tier_haircuts={
            AttestationTier.A: 0.95,
            AttestationTier.B: 0.45,
            AttestationTier.C: 0.75,
        },
    )
    assert out.tier_haircuts[AttestationTier.B] == 0.45
    assert base.tier_haircuts[AttestationTier.B] != 0.45  # base unchanged
