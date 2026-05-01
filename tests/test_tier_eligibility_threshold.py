"""Tests for tier-eligibility threshold under continuous blending.

Phase 10 Batch 10A (DL 2026-05-01): an attestation tier with fewer than
``IndexConfig.tier_min_constituents_for_blending`` constituents on a given
date is dormant globally for that index — its blending coefficient
redistributes to the remaining eligible tiers. Audit rows for the dormant
tier still emit (with ``coefficient=0`` / ``w_vol_contribution=0``) so
sparse-coverage constituents (like deepseek-v3-2 in v0.1's TPRR_E) remain
queryable in ConstituentDecisionDF.

The threshold applies symmetrically across:
- ``compute_tier_index`` (twap-then-weight ordering)
- ``_compute_weight_then_twap_index`` (weight-then-twap ordering)
- ``recompute_indices_under_override`` (Phase 10 sensitivity recompute)

Same-config recompute identity tests in ``test_sensitivity_recompute.py``
already cover the recompute-vs-pipeline equivalence under the default
threshold. This file targets the threshold's behavior directly.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from tprr.config import (
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
    TierBRevenueEntry,
)
from tprr.index.aggregation import ConstituentExclusionReason, compute_tier_index
from tprr.index.compute import run_full_pipeline
from tprr.index.weights import TierBVolumeFn
from tprr.schema import AttestationTier, Tier
from tprr.sensitivity.recompute import recompute_indices_under_override


def _registry_three_f() -> ModelRegistry:
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=Tier.TPRR_F,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=p_in,
                baseline_output_price_usd_mtok=p_out,
            )
            for cid, p_in, p_out in [
                ("openai/gpt-5-pro", 15.0, 75.0),
                ("anthropic/claude-opus-4-7", 14.0, 70.0),
                ("google/gemini-3-pro", 5.0, 30.0),
            ]
        ]
    )


def _stub_volume_fn(value: float) -> TierBVolumeFn:
    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return value

    return _fn


def _row(
    *,
    cid: str,
    contrib: str,
    d: date,
    twap_out: float,
    twap_in: float,
    volume: float,
    attestation: AttestationTier = AttestationTier.A,
) -> dict[str, Any]:
    ts = pd.Timestamp(d)
    return {
        "observation_date": ts,
        "constituent_id": cid,
        "contributor_id": contrib,
        "tier_code": Tier.TPRR_F.value,
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


# ---------------------------------------------------------------------------
# Threshold gates contribution: single-Tier-C constituent doesn't dominate
# ---------------------------------------------------------------------------


def test_single_tier_c_constituent_dormant_under_default_threshold() -> None:
    """3 F constituents with Tier A coverage; 1 of them also has Tier C.
    Default threshold (3) blocks Tier C contribution because only 1
    constituent has Tier C data. Result: tier_c_weight_share = 0.
    """
    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    for cid, p_out, p_in in [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_in,
                    volume=100.0,
                )
            )
    # Add Tier C row for ONE of them only.
    rows.append(
        _row(
            cid="google/gemini-3-pro",
            contrib="openrouter:google",
            d=d,
            twap_out=30.0,
            twap_in=5.0,
            volume=10_000.0,
            attestation=AttestationTier.C,
        )
    )
    panel = pd.DataFrame(rows)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=IndexConfig(),
        registry=_registry_three_f(),
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_volume_fn(0.0),
    )
    assert not result["suspended"]
    assert result["n_constituents_a"] == 3
    assert result["n_constituents_c"] == 0  # threshold-aware count
    assert result["tier_c_weight_share"] == 0.0
    assert result["tier_a_weight_share"] > 0.99


def test_single_tier_c_constituent_active_under_permissive_threshold() -> None:
    """Same fixture with threshold=1: Tier C contributes via the single
    constituent, producing non-zero tier_c_weight_share.
    """
    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    for cid, p_out, p_in in [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_in,
                    volume=100.0,
                )
            )
    rows.append(
        _row(
            cid="google/gemini-3-pro",
            contrib="openrouter:google",
            d=d,
            twap_out=30.0,
            twap_in=5.0,
            volume=10_000.0,
            attestation=AttestationTier.C,
        )
    )
    panel = pd.DataFrame(rows)
    permissive = IndexConfig(tier_min_constituents_for_blending=1)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=permissive,
        registry=_registry_three_f(),
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_volume_fn(0.0),
    )
    assert not result["suspended"]
    assert result["n_constituents_c"] == 1
    assert result["tier_c_weight_share"] > 0.0


def test_audit_preserves_single_tier_c_row_with_zero_contribution() -> None:
    """Under default threshold, deepseek-style single-Tier-C constituents
    still emit audit rows for Tier C — with coefficient=0,
    w_vol_contribution=0. Phase 10 sweeps need the audit row to remain
    queryable even when the tier is dormant.
    """
    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    for cid, p_out, p_in in [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_in,
                    volume=100.0,
                )
            )
    rows.append(
        _row(
            cid="google/gemini-3-pro",
            contrib="openrouter:google",
            d=d,
            twap_out=30.0,
            twap_in=5.0,
            volume=10_000.0,
            attestation=AttestationTier.C,
        )
    )
    panel = pd.DataFrame(rows)
    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=IndexConfig(),
        registry=_registry_three_f(),
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_volume_fn(0.0),
        decisions_out=decisions,
    )
    gemini_c_rows = [
        r
        for r in decisions
        if r["constituent_id"] == "google/gemini-3-pro"
        and r["attestation_tier"] == AttestationTier.C.value
    ]
    assert len(gemini_c_rows) == 1
    row = gemini_c_rows[0]
    # Audit preserves raw_volume_mtok and tier_collapsed_price_usd_mtok so
    # downstream can see "this constituent had Tier C data we ignored."
    assert row["raw_volume_mtok"] == 10_000.0
    assert row["tier_collapsed_price_usd_mtok"] == 30.0
    # But coefficient + w_vol_contribution are 0 — Tier C contributed nothing.
    assert row["coefficient"] == 0.0
    assert row["w_vol_contribution"] == 0.0
    # And the constituent IS included in the index (via Tier A).
    assert row["included"]


# ---------------------------------------------------------------------------
# Threshold-induced exclusion: constituent with only ineligible tiers
# ---------------------------------------------------------------------------


def test_constituent_with_only_ineligible_tiers_excluded() -> None:
    """A constituent whose only available tier is dormant gets excluded
    with TIER_INELIGIBLE_FOR_BLENDING. v0.1 has no such constituents
    (deepseek has Tier A coverage too), but v0.2+ might.
    """
    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    # 3 normal F-tier constituents with Tier A.
    for cid, p_out, p_in in [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_in,
                    volume=100.0,
                )
            )
    # An "imaginary" 4th F-tier constituent with ONLY Tier C coverage.
    rows.append(
        _row(
            cid="phantom/tierc-only",
            contrib="openrouter:phantom",
            d=d,
            twap_out=50.0,
            twap_in=10.0,
            volume=10_000.0,
            attestation=AttestationTier.C,
        )
    )
    registry = ModelRegistry(
        models=[
            *_registry_three_f().models,
            ModelMetadata(
                constituent_id="phantom/tierc-only",
                tier=Tier.TPRR_F,
                provider="phantom",
                canonical_name="phantom/tierc-only",
                baseline_input_price_usd_mtok=10.0,
                baseline_output_price_usd_mtok=50.0,
            ),
        ]
    )
    panel = pd.DataFrame(rows)
    decisions: list[dict[str, Any]] = []
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=IndexConfig(),
        registry=registry,
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_volume_fn(0.0),
        decisions_out=decisions,
    )
    phantom_rows = [
        r for r in decisions if r["constituent_id"] == "phantom/tierc-only"
    ]
    assert len(phantom_rows) == 1
    assert not phantom_rows[0]["included"]
    assert (
        phantom_rows[0]["exclusion_reason"]
        == ConstituentExclusionReason.TIER_INELIGIBLE_FOR_BLENDING.value
    )
    # Phantom does not count toward active constituents.
    assert result["n_constituents_active"] == 3
    assert not result["suspended"]


# ---------------------------------------------------------------------------
# Recompute parity: threshold applied identically in pipeline + recompute
# ---------------------------------------------------------------------------


def test_recompute_threshold_matches_pipeline_threshold() -> None:
    """run_full_pipeline + recompute at the same config produce matching
    raw_value_usd_mtok across all 8 indices, including the threshold's
    effect on tier_c_weight_share for sparse-Tier-C panels.
    """
    from datetime import timedelta

    rows: list[dict[str, Any]] = []
    start = date(2025, 1, 1)
    for offset in range(5):
        d = start + timedelta(days=offset)
        for cid, p_out, p_in in [
            ("openai/gpt-5-pro", 75.0, 15.0),
            ("anthropic/claude-opus-4-7", 70.0, 14.0),
            ("google/gemini-3-pro", 30.0, 5.0),
        ]:
            for c in ["c1", "c2", "c3"]:
                rows.append(
                    _row(
                        cid=cid,
                        contrib=c,
                        d=d,
                        twap_out=p_out,
                        twap_in=p_in,
                        volume=100.0,
                    )
                )
        # Single Tier C constituent — would dominate without threshold.
        rows.append(
            _row(
                cid="google/gemini-3-pro",
                contrib="openrouter:google",
                d=d,
                twap_out=30.0,
                twap_in=5.0,
                volume=10_000.0,
                attestation=AttestationTier.C,
            )
        )
    panel = pd.DataFrame(rows)
    config = IndexConfig(base_date=date(2025, 1, 1))
    pipeline = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=config,
        registry=_registry_three_f(),
        tier_b_config=TierBRevenueConfig(
            entries=[
                TierBRevenueEntry(
                    provider=p,
                    period="2025-Q1",
                    amount_usd=1_000_000_000.0,
                    source="test",
                )
                for p in ("openai", "anthropic", "google")
            ]
        ),
        tier_b_volume_fn=_stub_volume_fn(10_000.0),
    )
    recomputed = recompute_indices_under_override(
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        new_config=config,
    )
    for code in pipeline.indices:
        np.testing.assert_allclose(
            recomputed[code]["raw_value_usd_mtok"].to_numpy(),
            pipeline.indices[code]["raw_value_usd_mtok"].to_numpy(),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
            err_msg=f"{code}: recompute drift vs pipeline at default threshold",
        )
    # Specifically: tier_c_weight_share should be 0 throughout (Tier C has 1
    # constituent, dormant under default threshold=3).
    f_indices = pipeline.indices["TPRR_F"]
    assert (f_indices["tier_c_weight_share"] == 0.0).all()
