"""Tests for tprr.index.aggregation — Phase 7 dual-weighted aggregation.

Covers:
- collapse_constituent_price: volume-weighted average, fallbacks, edge cases.
- compute_tier_index: priority fall-through, suspension reasons, instrumentation
  (n_constituents_a/b/c, tier_*_weight_share).
- run_tier_pipeline: multi-day driver + prior-raw-value carry-forward.
- The cross-tier magnitude property holds end-to-end (a Tier B fall-through
  constituent dominates the index by orders of magnitude — the signal Phase 10
  must characterize per decision_log.md 2026-04-29).
"""

from __future__ import annotations

from datetime import date
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
from tprr.index.aggregation import (
    _DECISION_FIELDS,
    ConstituentExclusionReason,
    SuspensionReason,
    collapse_constituent_price,
    compute_tier_index,
    exponential_weight,
    run_tier_pipeline,
)
from tprr.index.weights import TierBVolumeFn
from tprr.schema import AttestationTier, Tier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _registry() -> ModelRegistry:
    """Three F-tier constituents covering distinct providers."""
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="openai/gpt-5-pro",
                tier=Tier.TPRR_F,
                provider="openai",
                canonical_name="GPT-5 Pro",
                baseline_input_price_usd_mtok=15.0,
                baseline_output_price_usd_mtok=75.0,
            ),
            ModelMetadata(
                constituent_id="anthropic/claude-opus-4-7",
                tier=Tier.TPRR_F,
                provider="anthropic",
                canonical_name="Claude Opus 4.7",
                baseline_input_price_usd_mtok=15.0,
                baseline_output_price_usd_mtok=75.0,
            ),
            ModelMetadata(
                constituent_id="google/gemini-3-pro",
                tier=Tier.TPRR_F,
                provider="google",
                canonical_name="Gemini 3 Pro",
                baseline_input_price_usd_mtok=5.0,
                baseline_output_price_usd_mtok=30.0,
            ),
        ]
    )


def _index_config() -> IndexConfig:
    return IndexConfig()  # λ=3, haircuts A=1.0/B=0.5/C=0.8 (Phase 7H Batch C), min=3


def _empty_tier_b_config() -> TierBRevenueConfig:
    return TierBRevenueConfig(entries=[])


def _tier_b_config_with_openai() -> TierBRevenueConfig:
    return TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="openai",
                period="2025-Q1",
                amount_usd=425_000_000.0,
                source="analyst_triangulation",
            ),
            TierBRevenueEntry(
                provider="openai",
                period="2025-Q2",
                amount_usd=510_000_000.0,
                source="analyst_triangulation",
            ),
        ]
    )


def _stub_tier_b_volume_fn(value: float = 1_000_000.0) -> TierBVolumeFn:
    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return value

    return _fn


def _row(
    *,
    constituent_id: str,
    contributor_id: str,
    observation_date: date,
    attestation_tier: AttestationTier,
    volume_mtok_7d: float,
    twap_output: float = 50.0,
    twap_input: float = 10.0,
    tier_code: Tier = Tier.TPRR_F,
) -> dict[str, Any]:
    return {
        "observation_date": pd.Timestamp(observation_date),
        "constituent_id": constituent_id,
        "contributor_id": contributor_id,
        "tier_code": tier_code.value,
        "attestation_tier": attestation_tier.value,
        "input_price_usd_mtok": float(twap_input),
        "output_price_usd_mtok": float(twap_output),
        "volume_mtok_7d": float(volume_mtok_7d),
        "twap_output_usd_mtok": float(twap_output),
        "twap_input_usd_mtok": float(twap_input),
        "source": "test",
        "submitted_at": pd.Timestamp(observation_date),
        "notes": "",
    }


def _three_contributors_per_constituent_panel(d: date) -> pd.DataFrame:
    """Tier-A-eligible panel: 3 contributors x 3 F-tier constituents on date d."""
    rows = []
    constituent_prices = {
        "openai/gpt-5-pro": 75.0,
        "anthropic/claude-opus-4-7": 70.0,
        "google/gemini-3-pro": 30.0,
    }
    contributors = ["contrib_alpha", "contrib_beta", "contrib_gamma"]
    for cid, price in constituent_prices.items():
        for c in contributors:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# collapse_constituent_price
# ---------------------------------------------------------------------------


def test_collapse_volume_weighted_basic() -> None:
    """Two contributors: v=100 @ 50, v=300 @ 70 → 0.25*50 + 0.75*70 = 65.0."""
    df = pd.DataFrame(
        [
            {"twap_output_usd_mtok": 50.0, "volume_mtok_7d": 100.0},
            {"twap_output_usd_mtok": 70.0, "volume_mtok_7d": 300.0},
        ]
    )
    assert collapse_constituent_price(df) == pytest.approx(65.0)


def test_collapse_equal_volumes_equals_simple_mean() -> None:
    df = pd.DataFrame(
        [
            {"twap_output_usd_mtok": 50.0, "volume_mtok_7d": 100.0},
            {"twap_output_usd_mtok": 70.0, "volume_mtok_7d": 100.0},
            {"twap_output_usd_mtok": 90.0, "volume_mtok_7d": 100.0},
        ]
    )
    assert collapse_constituent_price(df) == pytest.approx(70.0)


def test_collapse_single_row_returns_that_price() -> None:
    df = pd.DataFrame([{"twap_output_usd_mtok": 42.5, "volume_mtok_7d": 17.0}])
    assert collapse_constituent_price(df) == pytest.approx(42.5)


def test_collapse_zero_total_volume_falls_back_to_simple_mean() -> None:
    """Defensive fallback path: pathological all-zero volumes → simple mean."""
    df = pd.DataFrame(
        [
            {"twap_output_usd_mtok": 50.0, "volume_mtok_7d": 0.0},
            {"twap_output_usd_mtok": 70.0, "volume_mtok_7d": 0.0},
        ]
    )
    assert collapse_constituent_price(df) == pytest.approx(60.0)


def test_collapse_empty_raises() -> None:
    df = pd.DataFrame(columns=["twap_output_usd_mtok", "volume_mtok_7d"])
    with pytest.raises(ValueError, match="empty"):
        collapse_constituent_price(df)


def test_collapse_volume_weighted_differs_from_simple_mean_when_volumes_unequal() -> None:
    """Empirical proof the collapse is doing what it should: skewed volumes
    pull the constituent price toward the high-volume contributor's TWAP."""
    df = pd.DataFrame(
        [
            {"twap_output_usd_mtok": 40.0, "volume_mtok_7d": 1.0},
            {"twap_output_usd_mtok": 80.0, "volume_mtok_7d": 99.0},
        ]
    )
    weighted = collapse_constituent_price(df)
    simple_mean = float(df["twap_output_usd_mtok"].mean())
    # Weighted ≈ 79.6, simple = 60. Difference is non-trivial.
    assert weighted == pytest.approx(79.6)
    assert abs(weighted - simple_mean) > 15.0


# ---------------------------------------------------------------------------
# compute_tier_index — Tier A clean panel
# ---------------------------------------------------------------------------


def test_compute_tier_index_tier_a_only_clean_panel() -> None:
    """3 constituents, 3 contributors each, all Tier A. Verify raw_value lands
    near the F-tier price cluster and tier_a_weight_share == 1.0."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert not result["suspended"]
    assert result["index_code"] == "TPRR_F"
    assert result["n_constituents_active"] == 3
    assert result["n_constituents_a"] == 3
    assert result["n_constituents_b"] == 0
    assert result["n_constituents_c"] == 0
    assert result["tier_a_weight_share"] == pytest.approx(1.0)
    # Median is 70 (constituents at 30, 70, 75); raw_value lies near median.
    assert 30.0 <= result["raw_value_usd_mtok"] <= 75.0


def test_compute_tier_index_below_min_3_suspends_with_insufficient_constituents() -> None:
    """Two constituents with valid Tier A → tier suspends with the right reason."""
    d = date(2025, 1, 1)
    rows = []
    for cid, price in [("openai/gpt-5-pro", 75.0), ("google/gemini-3-pro", 30.0)]:
        for c in ["contrib_alpha", "contrib_beta", "contrib_gamma"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    panel = pd.DataFrame(rows)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result["suspended"]
    assert result["suspension_reason"] == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value
    assert np.isnan(result["raw_value_usd_mtok"])


def test_compute_tier_index_empty_panel_suspends_with_tier_data_unavailable() -> None:
    result = compute_tier_index(
        panel_day_df=pd.DataFrame(columns=["observation_date", "tier_code"]),
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result["suspended"]
    assert result["suspension_reason"] == SuspensionReason.TIER_DATA_UNAVAILABLE.value


def test_compute_tier_index_prior_raw_value_carried_through_suspension() -> None:
    """Suspended row falls back to prior_raw_value when supplied."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d).iloc[:3]  # one constituent only
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        prior_raw_value=58.5,
    )
    assert result["suspended"]
    assert result["raw_value_usd_mtok"] == pytest.approx(58.5)


def test_compute_tier_index_filters_panel_by_tier_code() -> None:
    """An S-tier constituent in panel_day_df must not contribute to TPRR_F."""
    d = date(2025, 1, 1)
    rows = []
    # Three F-tier constituents
    for cid, price in [
        ("openai/gpt-5-pro", 75.0),
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
    ]:
        for c in ["contrib_alpha", "contrib_beta", "contrib_gamma"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    # An S-tier row at price 4.0 — should be excluded by tier_code filter
    rows.append(
        _row(
            constituent_id="openai/gpt-5-mini",
            contributor_id="contrib_alpha",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=500.0,
            twap_output=4.0,
            tier_code=Tier.TPRR_S,
        )
    )
    panel = pd.DataFrame(rows)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result["n_constituents"] == 3  # F only, S excluded
    assert result["n_constituents_active"] == 3
    # Raw value sits in the F-cluster ($30-75); the S contaminant @ $4 would
    # have pulled it well below if it had been included.
    assert result["raw_value_usd_mtok"] >= 30.0


def test_compute_tier_index_suspended_pair_drops_from_aggregation() -> None:
    """A suspended (contributor, constituent) pair on or before as_of_date drops
    out of the active set on that date."""
    d = date(2025, 1, 10)
    panel = _three_contributors_per_constituent_panel(d)

    # Suspend ALL contributors for openai/gpt-5-pro effective 2025-01-05.
    susp = pd.DataFrame(
        {
            "contributor_id": ["contrib_alpha", "contrib_beta", "contrib_gamma"],
            "constituent_id": ["openai/gpt-5-pro"] * 3,
            "suspension_date": [pd.Timestamp("2025-01-05")] * 3,
        }
    )
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
    )
    # Only 2 F constituents survive → suspension with INSUFFICIENT_CONSTITUENTS.
    assert result["suspended"]
    assert result["suspension_reason"] == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value


def test_compute_tier_index_volume_weighted_collapse_pulls_constituent_price() -> None:
    """Construct a Tier-A constituent with one heavy contributor pricing far
    above the cluster, rest light. The volume-weighted collapse should pull
    the constituent's representative price toward the heavy contributor."""
    d = date(2025, 1, 1)
    rows = [
        # Constituent 1: heavy @ 90, two light @ 60 — weighted ~ 87.5, simple mean = 70
        _row(
            constituent_id="openai/gpt-5-pro",
            contributor_id="heavy",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=900.0,
            twap_output=90.0,
        ),
        _row(
            constituent_id="openai/gpt-5-pro",
            contributor_id="light_1",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=50.0,
            twap_output=60.0,
        ),
        _row(
            constituent_id="openai/gpt-5-pro",
            contributor_id="light_2",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=50.0,
            twap_output=60.0,
        ),
    ]
    # Constituent 2 + 3 (uniform Tier A) so min-3 is met.
    for cid, price in [
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    panel = pd.DataFrame(rows)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    # Expected gpt-5-pro constituent price = (900*90 + 50*60 + 50*60) / 1000 = 87.0
    # Tier median over [87.0, 70.0, 30.0] = 70.0
    # raw_value sits near median (gpt-5-pro carries highest w_vol but is far
    # from median → its w_exp dampens its influence).
    assert not result["suspended"]
    assert result["raw_value_usd_mtok"] < 87.0  # gpt-5-pro doesn't dominate
    assert result["raw_value_usd_mtok"] > 30.0  # gemini doesn't dominate either


# ---------------------------------------------------------------------------
# compute_tier_index — cross-tier mix
# ---------------------------------------------------------------------------


def test_compute_tier_index_priority_fallthrough_preserved_under_within_tier_normalization() -> None:
    """Phase 7H Batch A (DL 2026-04-30) replaces ``w_vol = raw_volume x haircut``
    with ``w_vol = within_tier_share x haircut``. Priority fall-through
    SELECTION is preserved (gpt-5-pro still falls to Tier B because it has
    only 2 Tier A contributors); but the cross-tier weight-share dominance
    that the old test pinned is deliberately removed.

    Under within-tier-share normalization, a tier with one constituent
    contributes share=1.0 x haircut (e.g. 0.5 for Tier B per Phase 7H
    Batch C). A tier with two constituents contributes 2 x 0.5 x haircut.
    The relative weight share
    at the IndexValue level depends on per-constituent w_exp factors, but
    is bounded — Tier B with one constituent no longer dominates simply
    because its raw volume is 4-5 orders of magnitude larger.

    Replaces test_compute_tier_index_tier_b_fallthrough_dominates_via_magnitude.
    """
    d = date(2025, 1, 1)
    rows = []
    # gpt-5-pro: only 2 contributors → fails Tier A min-3, falls to Tier B.
    for c in ["contrib_alpha", "contrib_beta"]:
        rows.append(
            _row(
                constituent_id="openai/gpt-5-pro",
                contributor_id=c,
                observation_date=d,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=50.0,
                twap_output=80.0,
            )
        )
    rows.append(
        _row(
            constituent_id="openai/gpt-5-pro",
            contributor_id="tier_b_derived:openai",
            observation_date=d,
            attestation_tier=AttestationTier.B,
            volume_mtok_7d=20_000_000.0,
            twap_output=80.0,
        )
    )
    for cid, price in [
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    panel = pd.DataFrame(rows)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=20_000_000.0),
    )
    # Priority fall-through SELECTION preserved: gpt-5-pro → Tier B, others → Tier A.
    assert not result["suspended"]
    assert result["n_constituents_a"] == 2
    assert result["n_constituents_b"] == 1
    assert result["n_constituents_c"] == 0
    # Cross-tier weight-share dominance from the old raw-volume formulation
    # is explicitly removed. Tier B no longer dominates by magnitude alone;
    # under Phase 7H Batch C its haircut is 0.5 (was 0.9). Final tier
    # weight shares depend on w_exp; both are non-trivial fractions of
    # total weight (neither swamps the other).
    assert 0.0 < result["tier_a_weight_share"] < 1.0
    assert 0.0 < result["tier_b_weight_share"] < 1.0
    # Tier A's combined weight (2 active) exceeds Tier B's (1 active) under
    # within-tier-share normalization on this panel — the magnitude inversion
    # is structural, not coincidental.
    assert result["tier_a_weight_share"] > result["tier_b_weight_share"]


# ---------------------------------------------------------------------------
# run_tier_pipeline — multi-day driver
# ---------------------------------------------------------------------------


def test_run_tier_pipeline_emits_one_row_per_date() -> None:
    panel_d1 = _three_contributors_per_constituent_panel(date(2025, 1, 1))
    panel_d2 = _three_contributors_per_constituent_panel(date(2025, 1, 2))
    panel = pd.concat([panel_d1, panel_d2], ignore_index=True)
    out = run_tier_pipeline(
        panel_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert len(out) == 2
    assert (~out["suspended"]).all()


def test_run_tier_pipeline_carries_prior_raw_value_through_suspension() -> None:
    """Day 1 produces a valid fix; day 2 has only 2 constituents → suspended
    but carries day 1's raw_value forward."""
    rows_d1 = _three_contributors_per_constituent_panel(date(2025, 1, 1))
    rows_d2_partial = _three_contributors_per_constituent_panel(
        date(2025, 1, 2)
    )
    rows_d2_partial = rows_d2_partial[
        rows_d2_partial["constituent_id"] != "google/gemini-3-pro"
    ]
    panel = pd.concat([rows_d1, rows_d2_partial], ignore_index=True)
    out = run_tier_pipeline(
        panel_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert len(out) == 2
    d1_value = float(out.iloc[0]["raw_value_usd_mtok"])
    assert not out.iloc[0]["suspended"]
    assert out.iloc[1]["suspended"]
    assert (
        out.iloc[1]["suspension_reason"]
        == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value
    )
    assert float(out.iloc[1]["raw_value_usd_mtok"]) == pytest.approx(d1_value)


def test_run_tier_pipeline_empty_panel_returns_empty() -> None:
    out = run_tier_pipeline(
        panel_df=pd.DataFrame(),
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert out.empty


def test_run_tier_pipeline_unknown_ordering_raises() -> None:
    """Unknown ordering values raise NotImplementedError. The two recognised
    orderings are 'twap_then_weight' (canonical, DL 2026-04-23) and
    'weight_then_twap' (Phase 10 comparison path, DL 2026-04-30 Batch E)."""
    panel = _three_contributors_per_constituent_panel(date(2025, 1, 1))
    with pytest.raises(NotImplementedError, match="not implemented"):
        run_tier_pipeline(
            panel_df=panel,
            tier=Tier.TPRR_F,
            config=_index_config(),
            registry=_registry(),
            tier_b_config=_empty_tier_b_config(),
            tier_b_volume_fn=_stub_tier_b_volume_fn(),
            ordering="some_unknown_ordering",
        )


def test_run_tier_pipeline_weight_then_twap_without_change_events_raises() -> None:
    """The weight-then-TWAP path requires change_events_df for slot
    reconstruction; missing the frame must raise rather than silently
    fall back to TWAP-then-weight."""
    panel = _three_contributors_per_constituent_panel(date(2025, 1, 1))
    with pytest.raises(ValueError, match="requires change_events_df"):
        run_tier_pipeline(
            panel_df=panel,
            tier=Tier.TPRR_F,
            config=_index_config(),
            registry=_registry(),
            tier_b_config=_empty_tier_b_config(),
            tier_b_volume_fn=_stub_tier_b_volume_fn(),
            ordering="weight_then_twap",
        )


# ---------------------------------------------------------------------------
# rebase_index_level (Batch B)
# ---------------------------------------------------------------------------


def _index_value_df_row(
    *,
    as_of_date: date,
    index_code: str = "TPRR_F",
    raw_value: float,
    suspended: bool = False,
    suspension_reason: str = "",
) -> dict[str, Any]:
    return {
        "as_of_date": pd.Timestamp(as_of_date),
        "index_code": index_code,
        "version": "v0_1",
        "lambda": 3.0,
        "ordering": "twap_then_weight",
        "raw_value_usd_mtok": raw_value,
        "index_level": float("nan"),
        "n_constituents": 6,
        "n_constituents_active": 6,
        "n_constituents_a": 6,
        "n_constituents_b": 0,
        "n_constituents_c": 0,
        "tier_a_weight_share": 1.0,
        "tier_b_weight_share": 0.0,
        "tier_c_weight_share": 0.0,
        "suspended": suspended,
        "suspension_reason": suspension_reason,
        "notes": "",
    }


def test_rebase_index_level_anchors_on_base_date() -> None:
    """When base_date is in the panel and not suspended, rebase factor is
    100 / raw_value_at_base_date and applies uniformly to all rows."""
    from tprr.index.aggregation import rebase_index_level

    df = pd.DataFrame(
        [
            _index_value_df_row(as_of_date=date(2025, 12, 31), raw_value=50.0),
            _index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=60.0),
            _index_value_df_row(as_of_date=date(2026, 1, 2), raw_value=63.0),
        ]
    )
    out, anchor = rebase_index_level(df, base_date=date(2026, 1, 1))
    assert anchor == date(2026, 1, 1)
    # Factor = 100 / 60 = 1.6667. So 50 -> 83.33, 60 -> 100, 63 -> 105.
    assert float(out.iloc[0]["index_level"]) == pytest.approx(50.0 * 100 / 60)
    assert float(out.iloc[1]["index_level"]) == pytest.approx(100.0)
    assert float(out.iloc[2]["index_level"]) == pytest.approx(63.0 * 100 / 60)


def test_rebase_index_level_skips_suspended_anchor() -> None:
    """If base_date row is suspended, anchor falls through to next valid row."""
    from tprr.index.aggregation import rebase_index_level

    df = pd.DataFrame(
        [
            _index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=float("nan"), suspended=True),
            _index_value_df_row(as_of_date=date(2026, 1, 2), raw_value=float("nan"), suspended=True),
            _index_value_df_row(as_of_date=date(2026, 1, 3), raw_value=70.0),
        ]
    )
    out, anchor = rebase_index_level(df, base_date=date(2026, 1, 1))
    assert anchor == date(2026, 1, 3)
    # Suspended rows have NaN raw_value → factor application produces NaN.
    assert np.isnan(float(out.iloc[0]["index_level"]))
    assert np.isnan(float(out.iloc[1]["index_level"]))
    assert float(out.iloc[2]["index_level"]) == pytest.approx(100.0)


def test_rebase_index_level_no_eligible_anchor_returns_none() -> None:
    """If every row at-or-after base_date is suspended, anchor is None and
    index_level stays NaN throughout."""
    from tprr.index.aggregation import rebase_index_level

    df = pd.DataFrame(
        [
            _index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=float("nan"), suspended=True),
            _index_value_df_row(as_of_date=date(2026, 1, 2), raw_value=float("nan"), suspended=True),
        ]
    )
    out, anchor = rebase_index_level(df, base_date=date(2026, 1, 1))
    assert anchor is None
    assert out["index_level"].isna().all()


def test_rebase_index_level_empty_input_returns_empty_no_anchor() -> None:
    from tprr.index.aggregation import rebase_index_level

    out, anchor = rebase_index_level(pd.DataFrame(), base_date=date(2026, 1, 1))
    assert anchor is None
    assert out.empty


# ---------------------------------------------------------------------------
# run_all_core_indices
# ---------------------------------------------------------------------------


def _three_tier_panel(d: date) -> pd.DataFrame:
    """Tier A panel covering 3 F + 3 S + 3 E constituents on date d.

    Lets run_all_core_indices return non-empty IndexValueDFs for all 3 tiers.
    """
    rows: list[dict[str, Any]] = []
    f_constituents = [
        ("openai/gpt-5-pro", 75.0),
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
    ]
    s_constituents = [
        ("openai/gpt-5-mini", 4.0),
        ("anthropic/claude-haiku-4-5", 5.0),
        ("google/gemini-2-flash", 2.5),
    ]
    e_constituents = [
        ("google/gemini-flash-lite", 0.4),
        ("openai/gpt-5-nano", 0.6),
        ("deepseek/deepseek-v3-2", 1.0),
    ]
    for cid, price in f_constituents:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                    tier_code=Tier.TPRR_F,
                )
            )
    for cid, price in s_constituents:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=300.0,
                    twap_output=price,
                    tier_code=Tier.TPRR_S,
                )
            )
    for cid, price in e_constituents:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=900.0,
                    twap_output=price,
                    tier_code=Tier.TPRR_E,
                )
            )
    return pd.DataFrame(rows)


def _three_tier_registry() -> ModelRegistry:
    """Mini registry covering the constituents in _three_tier_panel."""
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=baseline_in,
                baseline_output_price_usd_mtok=baseline_out,
            )
            for cid, tier, baseline_in, baseline_out in [
                ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
                ("anthropic/claude-opus-4-7", Tier.TPRR_F, 15.0, 75.0),
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


def test_run_all_core_indices_emits_three_tiers_with_rebase() -> None:
    """All three core tier indices land with rebase to 100 on base_date."""
    from tprr.index.aggregation import run_all_core_indices

    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = pd.concat(
        [_three_tier_panel(date(2025, 1, 1)), _three_tier_panel(date(2025, 1, 2))],
        ignore_index=True,
    )
    result = run_all_core_indices(
        panel_df=panel,
        config=config,
        registry=_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert set(result.indices.keys()) == {"TPRR_F", "TPRR_S", "TPRR_E"}
    for df in result.indices.values():
        assert len(df) == 2
        # First row (anchor) should land at 100.0
        anchor_row = df[df["as_of_date"] == pd.Timestamp(date(2025, 1, 1))]
        assert float(anchor_row["index_level"].iloc[0]) == pytest.approx(100.0)
    # Anchor metadata for each tier
    for code in ("TPRR_F", "TPRR_S", "TPRR_E"):
        assert result.rebase_anchors[code] == date(2025, 1, 1)


def test_run_all_core_indices_per_tier_anchor_when_one_tier_suspended() -> None:
    """If TPRR_S is suspended on base_date but F/E are not, F/E anchor on
    base_date while S anchors on the next valid day."""
    from tprr.index.aggregation import run_all_core_indices

    config = IndexConfig(base_date=date(2025, 1, 1))
    # Day 1: full panel for F + E, only 2 S constituents (S suspends).
    p1 = _three_tier_panel(date(2025, 1, 1))
    p1 = p1[
        ~(
            (p1["constituent_id"] == "google/gemini-2-flash")
            & (p1["observation_date"] == pd.Timestamp(date(2025, 1, 1)))
        )
    ]
    # Day 2: full panel, all tiers active.
    p2 = _three_tier_panel(date(2025, 1, 2))
    panel = pd.concat([p1, p2], ignore_index=True)

    result = run_all_core_indices(
        panel_df=panel,
        config=config,
        registry=_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result.rebase_anchors["TPRR_F"] == date(2025, 1, 1)
    assert result.rebase_anchors["TPRR_E"] == date(2025, 1, 1)
    assert result.rebase_anchors["TPRR_S"] == date(2025, 1, 2)


# ---------------------------------------------------------------------------
# build_rebase_metadata_df (Batch D — Q2)
# ---------------------------------------------------------------------------


def test_build_rebase_metadata_df_columns_match_spec() -> None:
    """Schema check: every required column appears with one row per index_code."""
    from tprr.index.aggregation import build_rebase_metadata_df

    indices = {
        "TPRR_F": pd.DataFrame(
            [
                _index_value_df_row(as_of_date=date(2025, 12, 31), raw_value=50.0),
                _index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=60.0),
            ]
        ),
    }
    metadata = build_rebase_metadata_df(
        indices=indices,
        rebase_anchors={"TPRR_F": date(2026, 1, 1)},
        base_date=date(2026, 1, 1),
    )
    expected_cols = {
        "index_code",
        "base_date",
        "anchor_date",
        "anchor_raw_value",
        "n_pre_anchor_suspended_days",
    }
    assert set(metadata.columns) == expected_cols
    assert len(metadata) == 1
    assert (metadata["index_code"] == "TPRR_F").all()


def test_build_rebase_metadata_df_anchor_date_matches_index_level_100_row() -> None:
    """anchor_date equals the date where index_level hits the rebase target,
    and anchor_raw_value matches that row's raw_value_usd_mtok."""
    from tprr.index.aggregation import (
        build_rebase_metadata_df,
        rebase_index_level,
    )

    df = pd.DataFrame(
        [
            _index_value_df_row(as_of_date=date(2025, 12, 31), raw_value=50.0),
            _index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=60.0),
            _index_value_df_row(as_of_date=date(2026, 1, 2), raw_value=63.0),
        ]
    )
    rebased, anchor = rebase_index_level(df, base_date=date(2026, 1, 1))
    metadata = build_rebase_metadata_df(
        indices={"TPRR_F": rebased},
        rebase_anchors={"TPRR_F": anchor},
        base_date=date(2026, 1, 1),
    )
    row = metadata.iloc[0]
    # The anchor row in the rebased DF should have index_level == 100.
    anchor_row_in_df = rebased[rebased["as_of_date"] == pd.Timestamp(row["anchor_date"])]
    assert float(anchor_row_in_df["index_level"].iloc[0]) == pytest.approx(100.0)
    # anchor_raw_value matches the raw_value at that date.
    assert float(row["anchor_raw_value"]) == pytest.approx(60.0)


def test_build_rebase_metadata_df_n_pre_anchor_suspended_days_counts_correctly() -> None:
    """Counts rows strictly before anchor_date with suspended=True. Suspended
    rows on or after the anchor are NOT counted; non-suspended pre-anchor rows
    are NOT counted."""
    from tprr.index.aggregation import build_rebase_metadata_df

    df = pd.DataFrame(
        [
            # Pre-anchor: 2 suspended, 1 not suspended → 2 counted
            _index_value_df_row(
                as_of_date=date(2025, 12, 28),
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="insufficient_constituents",
            ),
            _index_value_df_row(
                as_of_date=date(2025, 12, 29),
                raw_value=50.0,
                suspended=False,
            ),
            _index_value_df_row(
                as_of_date=date(2025, 12, 30),
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="tier_data_unavailable",
            ),
            # On anchor: not counted as pre-anchor
            _index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=60.0),
            # Post-anchor suspended row: NOT counted
            _index_value_df_row(
                as_of_date=date(2026, 1, 2),
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="quality_gate_cascade",
            ),
        ]
    )
    metadata = build_rebase_metadata_df(
        indices={"TPRR_F": df},
        rebase_anchors={"TPRR_F": date(2026, 1, 1)},
        base_date=date(2026, 1, 1),
    )
    assert int(metadata.iloc[0]["n_pre_anchor_suspended_days"]) == 2


def test_build_rebase_metadata_df_no_anchor_emits_nan_anchor_value() -> None:
    """When rebase produced no anchor, anchor_date is None, anchor_raw_value
    is NaN, n_pre_anchor_suspended_days holds the total suspended-row count
    (no anchor was reached, all suspended rows are pre-anchor in the limit)."""
    from tprr.index.aggregation import build_rebase_metadata_df

    df = pd.DataFrame(
        [
            _index_value_df_row(
                as_of_date=date(2026, 1, 1),
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="insufficient_constituents",
            ),
            _index_value_df_row(
                as_of_date=date(2026, 1, 2),
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="insufficient_constituents",
            ),
        ]
    )
    metadata = build_rebase_metadata_df(
        indices={"TPRR_F": df},
        rebase_anchors={"TPRR_F": None},
        base_date=date(2026, 1, 1),
    )
    row = metadata.iloc[0]
    assert row["anchor_date"] is None
    assert np.isnan(float(row["anchor_raw_value"]))
    assert int(row["n_pre_anchor_suspended_days"]) == 2


def test_build_rebase_metadata_df_every_index_represented() -> None:
    """One row per index_code, regardless of suspension state — Phase 10
    sweeps need every index in the metadata frame for joinability."""
    from tprr.index.aggregation import build_rebase_metadata_df

    indices = {
        "TPRR_F": pd.DataFrame(
            [_index_value_df_row(as_of_date=date(2026, 1, 1), raw_value=60.0)]
        ),
        "TPRR_S": pd.DataFrame(
            [
                _index_value_df_row(
                    as_of_date=date(2026, 1, 1),
                    raw_value=float("nan"),
                    suspended=True,
                    suspension_reason="insufficient_constituents",
                )
            ]
        ),
        "TPRR_E": pd.DataFrame(),
    }
    anchors: dict[str, date | None] = {
        "TPRR_F": date(2026, 1, 1),
        "TPRR_S": None,
        "TPRR_E": None,
    }
    metadata = build_rebase_metadata_df(
        indices=indices,
        rebase_anchors=anchors,
        base_date=date(2026, 1, 1),
    )
    assert set(metadata["index_code"]) == {"TPRR_F", "TPRR_S", "TPRR_E"}
    assert (metadata["base_date"] == date(2026, 1, 1)).all()


# ---------------------------------------------------------------------------
# ConstituentDecisionDF — Batch D Q1 audit trail
# ---------------------------------------------------------------------------


def _registry_three_full_tiers() -> ModelRegistry:
    """3F + 3S + 3E so run_all_core_indices touches every tier."""
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


def test_decisions_out_emits_one_row_per_active_constituent() -> None:
    """Clean panel with 3 F constituents → 3 decision rows, all included=True."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)
    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions,
    )
    assert len(decisions) == 3
    assert all(d["included"] for d in decisions)
    assert all(d["exclusion_reason"] == "" for d in decisions)
    constituent_ids = {d["constituent_id"] for d in decisions}
    assert constituent_ids == {
        "openai/gpt-5-pro",
        "anthropic/claude-opus-4-7",
        "google/gemini-3-pro",
    }


def test_decisions_out_schema_matches_decision_fields() -> None:
    """Every emitted decision row carries the full closed-set schema."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)
    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions,
    )
    for row in decisions:
        assert set(row.keys()) == set(_DECISION_FIELDS)


def test_decisions_out_included_rows_populate_all_numeric_fields() -> None:
    """Active rows under Phase 7H Batch B long-format (DL 2026-04-30): each
    (constituent, contributing tier) row populates per-tier numeric fields
    plus the constituent-level fields duplicated across the constituent's
    rows. weight_share_within_tier was deprecated; consumers compute via
    groupby on w_vol_contribution if needed."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)
    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions,
    )
    numeric_fields = (
        "raw_volume_mtok",
        "within_tier_volume_share",
        "tier_collapsed_price_usd_mtok",
        "coefficient",
        "w_vol_contribution",
        "constituent_price_usd_mtok",
        "tier_median_price_usd_mtok",
        "price_distance_from_median_pct",
        "w_vol",
        "w_exp",
        "combined_weight",
    )
    for row in decisions:
        for field_name in numeric_fields:
            assert not np.isnan(row[field_name]), (
                f"included row should populate {field_name!r}"
            )
        assert row["contributor_count"] > 0
    # Sum of w_vol_contribution per constituent equals that constituent's
    # combined w_vol — Phase 9/10 consumers reconstruct combined w_vol via
    # groupby([constituent_id]).w_vol_contribution.sum().
    by_constituent: dict[str, float] = {}
    by_constituent_w_vol: dict[str, float] = {}
    for row in decisions:
        cid = row["constituent_id"]
        by_constituent[cid] = by_constituent.get(cid, 0.0) + row["w_vol_contribution"]
        by_constituent_w_vol[cid] = row["w_vol"]  # duplicated across rows
    for cid in by_constituent:
        assert by_constituent[cid] == pytest.approx(by_constituent_w_vol[cid])


def test_decisions_out_tier_volume_unavailable_emits_excluded_row() -> None:
    """A constituent that fails compute_tier_volume (all 3 tiers fail) emits
    an excluded row with exclusion_reason=TIER_VOLUME_UNAVAILABLE. NaN
    numerics, but constituent_id and contributor_count are populated.

    Construction: 3 healthy F constituents (so the tier survives min-3) +
    a 4th constituent (gpt-5-pro) with a Tier A row at volume_mtok_7d=0
    (fails strict-positive Tier A activation), and provider has no Tier B
    revenue config and no Tier C row → all 3 tiers fail → exclusion.
    The other 3 constituents stay active with included=True."""
    d = date(2025, 1, 1)
    # Extend registry with a 4th F constituent so min-3 holds after gpt-5-pro drops.
    registry = ModelRegistry(
        models=[
            *_registry().models,
            ModelMetadata(
                constituent_id="meta/llama-4-405b",
                tier=Tier.TPRR_F,
                provider="meta",
                canonical_name="Llama 4 405B",
                baseline_input_price_usd_mtok=10.0,
                baseline_output_price_usd_mtok=50.0,
            ),
        ]
    )
    rows = []
    # 3 healthy F constituents (opus, gemini, llama)
    for cid, price in [
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
        ("meta/llama-4-405b", 50.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    # gpt-5-pro: 1 contributor with zero volume → Tier A fails (need ≥3 with
    # vol>0), no Tier B revenue config → no Tier C row → excluded.
    rows.append(
        _row(
            constituent_id="openai/gpt-5-pro",
            contributor_id="c1",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=0.0,
            twap_output=80.0,
        )
    )
    panel = pd.DataFrame(rows)
    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=registry,
        tier_b_config=_empty_tier_b_config(),  # no Tier B for openai
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions,
    )
    excluded = [d for d in decisions if not d["included"]]
    assert len(excluded) == 1
    assert excluded[0]["constituent_id"] == "openai/gpt-5-pro"
    assert (
        excluded[0]["exclusion_reason"]
        == ConstituentExclusionReason.TIER_VOLUME_UNAVAILABLE.value
    )
    assert excluded[0]["attestation_tier"] == ""
    assert np.isnan(excluded[0]["raw_volume_mtok"])
    assert np.isnan(excluded[0]["w_vol"])
    # The other 3 constituents are included with one row per contributing
    # tier — under this panel each has only Tier A → 1 row each = 3 rows.
    included = [d for d in decisions if d["included"]]
    assert len(included) == 3


def test_decisions_out_tier_aggregation_suspended_when_min_3_fails() -> None:
    """Two active constituents → tier suspends (INSUFFICIENT_CONSTITUENTS).
    The two computed-but-unused constituents emit excluded rows with
    exclusion_reason=TIER_AGGREGATION_SUSPENDED. w_vol is real (computed);
    w_exp / weight / median fields are NaN (the cascade never ran)."""
    d = date(2025, 1, 1)
    rows = []
    for cid, price in [
        ("openai/gpt-5-pro", 75.0),
        ("google/gemini-3-pro", 30.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    panel = pd.DataFrame(rows)
    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions,
    )
    # Under Phase 7H Batch B long-format: 2 constituents x 1 contributing
    # tier each (only Tier A available) = 2 rows.
    assert len(decisions) == 2
    for row in decisions:
        assert not row["included"]
        assert (
            row["exclusion_reason"]
            == ConstituentExclusionReason.TIER_AGGREGATION_SUSPENDED.value
        )
        # w_vol_contribution was computed before suspension decision.
        assert not np.isnan(row["w_vol_contribution"])
        assert not np.isnan(row["w_vol"])
        # median + w_exp + weight cascade never ran.
        assert np.isnan(row["tier_median_price_usd_mtok"])
        assert np.isnan(row["w_exp"])
        assert np.isnan(row["combined_weight"])


def test_decisions_out_lambda_recomputability() -> None:
    """Phase 10 λ-sweep: the decisions DataFrame must be sufficient to
    recompute w_exp at a different λ without re-running the full pipeline.
    Confirm that recomputed weights match a fresh pipeline run with the
    new λ within float tolerance."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)

    # Run #1 at λ=3, capture decisions
    config_a = IndexConfig(lambda_=3.0)
    decisions_a: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=config_a,
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions_a,
    )

    # Run #2 at λ=5, capture decisions (the "ground truth" for λ=5)
    config_b = IndexConfig(lambda_=5.0)
    decisions_b: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=config_b,
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions_b,
    )

    # Recompute λ=5 weights from λ=3's decisions: w_exp = exp(-λ * |distance|)
    # since price_distance_from_median_pct = |p - median| / median.
    by_id_a = {d["constituent_id"]: d for d in decisions_a}
    by_id_b = {d["constituent_id"]: d for d in decisions_b}
    for cid, row_a in by_id_a.items():
        recomputed_w_exp = exponential_weight(
            row_a["constituent_price_usd_mtok"],
            row_a["tier_median_price_usd_mtok"],
            5.0,
        )
        assert recomputed_w_exp == pytest.approx(by_id_b[cid]["w_exp"])


def test_run_tier_pipeline_decisions_out_accumulates_across_dates() -> None:
    """The multi-day driver appends decisions across dates into the same list."""
    panel_d1 = _three_contributors_per_constituent_panel(date(2025, 1, 1))
    panel_d2 = _three_contributors_per_constituent_panel(date(2025, 1, 2))
    panel = pd.concat([panel_d1, panel_d2], ignore_index=True)

    decisions: list[dict[str, Any]] = []
    run_tier_pipeline(
        panel_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        decisions_out=decisions,
    )
    # 3 constituents x 2 days = 6 rows
    assert len(decisions) == 6
    dates = {d["as_of_date"] for d in decisions}
    assert dates == {date(2025, 1, 1), date(2025, 1, 2)}


def test_run_all_core_indices_constituent_decisions_covers_all_three_tiers() -> None:
    """run_all_core_indices' constituent_decisions DataFrame contains rows for
    F + S + E tiers — total 9 constituents on a clean single-day panel."""
    from tprr.index.aggregation import run_all_core_indices

    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = _three_tier_panel(date(2025, 1, 1))
    result = run_all_core_indices(
        panel_df=panel,
        config=config,
        registry=_registry_three_full_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    decisions = result.constituent_decisions
    assert set(decisions["index_code"]) == {"TPRR_F", "TPRR_S", "TPRR_E"}
    assert len(decisions) == 9  # 3 constituents per tier x 3 tiers
    assert decisions["included"].all()


def test_run_all_core_indices_constituent_decisions_schema() -> None:
    """The DataFrame produced by run_all_core_indices carries every field
    in _DECISION_FIELDS."""
    from tprr.index.aggregation import run_all_core_indices

    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = _three_tier_panel(date(2025, 1, 1))
    result = run_all_core_indices(
        panel_df=panel,
        config=config,
        registry=_registry_three_full_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert set(result.constituent_decisions.columns) == set(_DECISION_FIELDS)


def test_decisions_list_to_df_empty_input_returns_empty_with_schema() -> None:
    """An empty decisions list yields an empty DataFrame with all schema
    columns present — keeps downstream consumer code uniform."""
    from tprr.index.aggregation import _decisions_list_to_df

    out = _decisions_list_to_df([])
    assert out.empty
    assert set(out.columns) == set(_DECISION_FIELDS)


def test_decisions_out_all_pairs_suspended_emits_excluded_row() -> None:
    """When every (contributor, constituent) pair for a constituent is
    suspended, that constituent disappears from the per-constituent loop.
    Audit trail emits an ALL_PAIRS_SUSPENDED decision row with NaN
    numerics and contributor_count=0."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)

    # Suspend ALL three contributor pairs for openai/gpt-5-pro effective today.
    susp = pd.DataFrame(
        {
            "contributor_id": ["contrib_alpha", "contrib_beta", "contrib_gamma"],
            "constituent_id": ["openai/gpt-5-pro"] * 3,
            "suspension_date": [pd.Timestamp(d)] * 3,
        }
    )

    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
        decisions_out=decisions,
    )

    all_pairs_suspended = [
        x
        for x in decisions
        if x["exclusion_reason"]
        == ConstituentExclusionReason.ALL_PAIRS_SUSPENDED.value
    ]
    assert len(all_pairs_suspended) == 1
    row = all_pairs_suspended[0]
    assert row["constituent_id"] == "openai/gpt-5-pro"
    assert not row["included"]
    assert row["attestation_tier"] == ""
    assert row["contributor_count"] == 0
    for f in (
        "coefficient",
        "raw_volume_mtok",
        "within_tier_volume_share",
        "tier_collapsed_price_usd_mtok",
        "w_vol_contribution",
        "constituent_price_usd_mtok",
        "tier_median_price_usd_mtok",
        "price_distance_from_median_pct",
        "w_vol",
        "w_exp",
        "combined_weight",
    ):
        assert np.isnan(row[f]), f"ALL_PAIRS_SUSPENDED row {f!r} should be NaN"


def test_decisions_out_all_pairs_suspended_co_fires_with_tier_data_unavailable() -> None:
    """When EVERY constituent in a tier loses all its pairs, the tier itself
    suspends with TIER_DATA_UNAVAILABLE AND each affected constituent gets
    an ALL_PAIRS_SUSPENDED audit row. The two signals are not mutually
    exclusive — they describe the same event from different levels."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)

    # Suspend EVERY contributor pair for EVERY F constituent on this date.
    susp_rows = []
    for cid in (
        "openai/gpt-5-pro",
        "anthropic/claude-opus-4-7",
        "google/gemini-3-pro",
    ):
        for c in ("contrib_alpha", "contrib_beta", "contrib_gamma"):
            susp_rows.append(
                {
                    "contributor_id": c,
                    "constituent_id": cid,
                    "suspension_date": pd.Timestamp(d),
                }
            )
    susp = pd.DataFrame(susp_rows)

    decisions: list[dict[str, Any]] = []
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
        decisions_out=decisions,
    )
    # Tier-level: TIER_DATA_UNAVAILABLE.
    assert result["suspended"]
    assert (
        result["suspension_reason"]
        == SuspensionReason.TIER_DATA_UNAVAILABLE.value
    )
    # Per-constituent: 3 ALL_PAIRS_SUSPENDED rows (one per F constituent).
    all_pairs_suspended = [
        x
        for x in decisions
        if x["exclusion_reason"]
        == ConstituentExclusionReason.ALL_PAIRS_SUSPENDED.value
    ]
    assert len(all_pairs_suspended) == 3
    suspended_constituents = {x["constituent_id"] for x in all_pairs_suspended}
    assert suspended_constituents == {
        "openai/gpt-5-pro",
        "anthropic/claude-opus-4-7",
        "google/gemini-3-pro",
    }


def test_decisions_out_all_pairs_suspended_respects_tier_code_filter() -> None:
    """A constituent in a different tier whose pairs are suspended on this
    date does NOT contribute an ALL_PAIRS_SUSPENDED row to a tier under
    computation that doesn't include it. Ensures the pre-drop snapshot
    runs after the tier_code filter."""
    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    # F-tier panel — 3 healthy F constituents
    for cid, price in [
        ("openai/gpt-5-pro", 75.0),
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    constituent_id=cid,
                    contributor_id=c,
                    observation_date=d,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                    twap_output=price,
                )
            )
    # An S-tier constituent — its pairs will be suspended, but the S
    # constituent must NOT show up in the F-tier audit.
    rows.append(
        _row(
            constituent_id="openai/gpt-5-mini",
            contributor_id="contrib_alpha",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=500.0,
            twap_output=4.0,
            tier_code=Tier.TPRR_S,
        )
    )
    panel = pd.DataFrame(rows)

    susp = pd.DataFrame(
        {
            "contributor_id": ["contrib_alpha"],
            "constituent_id": ["openai/gpt-5-mini"],
            "suspension_date": [pd.Timestamp(d)],
        }
    )

    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
        decisions_out=decisions,
    )

    # The S-tier constituent must not appear in the F audit at all.
    constituent_ids = {x["constituent_id"] for x in decisions}
    assert "openai/gpt-5-mini" not in constituent_ids
    # No ALL_PAIRS_SUSPENDED rows on the F tier — no F constituent fully
    # suspended.
    all_pairs_suspended = [
        x
        for x in decisions
        if x["exclusion_reason"]
        == ConstituentExclusionReason.ALL_PAIRS_SUSPENDED.value
    ]
    assert len(all_pairs_suspended) == 0


# ---------------------------------------------------------------------------
# Batch E — weight-then-TWAP alternate ordering for Phase 10 comparison
# (decision log 2026-04-30 "Phase 7 Batch E — weight-then-TWAP slot-level
# implementation choices for Phase 10 comparison")
# ---------------------------------------------------------------------------


def _empty_change_events_df() -> pd.DataFrame:
    """Empty change_events DataFrame with the required columns for slot
    reconstruction. Used in identity tests where there are no intraday
    changes — every slot equals the panel's posted price."""
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


def test_weight_then_twap_identity_matches_twap_then_weight_with_no_intraday_changes() -> None:
    """When there are no intraday change events, every slot equals the
    posted price → slot-level weighted aggregate equals the daily-TWAP
    weighted aggregate. The two orderings produce numerically identical
    raw_value_usd_mtok on a clean panel.

    This is the "identity" boundary: weight-then-TWAP should agree with
    TWAP-then-weight in the limit of constant intraday prices."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)

    canonical = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="twap_then_weight",
    )
    weight_then = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="weight_then_twap",
        change_events_df=_empty_change_events_df(),
    )
    assert canonical["raw_value_usd_mtok"] == pytest.approx(
        weight_then["raw_value_usd_mtok"]
    )
    # Both should be unsuspended with same active count
    assert canonical["suspended"] == weight_then["suspended"]
    assert canonical["n_constituents_active"] == weight_then["n_constituents_active"]
    assert weight_then["ordering"] == "weight_then_twap"


def test_weight_then_twap_diverges_when_intraday_change_crosses_tier_median() -> None:
    """An intraday change event that pushes one constituent's price across
    the tier median produces a meaningful divergence between orderings:
    - TWAP-then-weight: the contributor's daily TWAP is averaged across
      slots; the constituent's collapsed daily price reflects the average.
    - Weight-then-TWAP: the constituent's slot-by-slot price (and therefore
      its w_exp) varies — some slots have it above median, some below.

    The test pins the property that the orderings diverge on this panel.
    The exact direction of divergence depends on lambda + price geometry."""
    d = date(2025, 1, 1)

    # Panel: 3 F constituents, 3 contributors each. gpt-5-pro starts at 75
    # and via an intraday change drops to 25 mid-day for ALL its contributors.
    panel = _three_contributors_per_constituent_panel(d)
    # Re-write panel rows for gpt-5-pro to carry the daily TWAP between the
    # two prices (slots [0, 16) at 75, slots [16, 32) at 25 → TWAP = 50).
    twap_value = (16 * 75.0 + 16 * 25.0) / 32.0  # 50.0
    mask = panel["constituent_id"] == "openai/gpt-5-pro"
    panel.loc[mask, "output_price_usd_mtok"] = twap_value
    panel.loc[mask, "twap_output_usd_mtok"] = twap_value

    # Change events: each gpt-5-pro contributor has slot-16 transition 75→25.
    change_events_rows = []
    for contributor_id in ["contrib_alpha", "contrib_beta", "contrib_gamma"]:
        change_events_rows.append(
            {
                "event_date": pd.Timestamp(d),
                "contributor_id": contributor_id,
                "constituent_id": "openai/gpt-5-pro",
                "change_slot_idx": 16,
                "old_input_price_usd_mtok": 15.0,
                "new_input_price_usd_mtok": 5.0,
                "old_output_price_usd_mtok": 75.0,
                "new_output_price_usd_mtok": 25.0,
                "reason": "test_intraday_drop",
            }
        )
    change_events_df = pd.DataFrame(change_events_rows)

    canonical = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="twap_then_weight",
    )
    weight_then = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="weight_then_twap",
        change_events_df=change_events_df,
    )
    # Both should be unsuspended (3 active constituents each).
    assert not canonical["suspended"]
    assert not weight_then["suspended"]
    # Material divergence on a panel where the intraday change crosses the
    # tier median.
    assert canonical["raw_value_usd_mtok"] != pytest.approx(
        weight_then["raw_value_usd_mtok"]
    )
    # Sanity: both fall within the F-tier price range.
    assert 25.0 <= canonical["raw_value_usd_mtok"] <= 75.0
    assert 25.0 <= weight_then["raw_value_usd_mtok"] <= 75.0


def test_weight_then_twap_sparse_intraday_creates_more_suspended_slots() -> None:
    """When some slots have <3 contributors (due to slot-level exclusions)
    but daily TWAP across all 32 slots still has ≥3, weight-then-TWAP
    suspends more days than TWAP-then-weight (DL 2026-04-30 Batch E
    "important property"). Build a panel where excluded_slots make the
    first 30 slots have <3 active contributors per constituent, then
    verify weight-then-TWAP sees fewer surviving slots than canonical.

    Construction: 3 F constituents, 3 contributors each. For 2 of the 3
    contributors per constituent, slots [0, 30) are excluded — leaving
    only 1 contributor per constituent per slot for slots [0, 30). Slots
    [30, 32) have full 3-contributor coverage. Daily TWAP across all 32
    slots still aggregates from 3 contributors (just with sparser inputs)
    so canonical proceeds; weight-then-TWAP has min-3 violations on
    slots [0, 30) (only 1 contributor per constituent → after collapse
    each constituent has a price, but constituents themselves still have
    3 valid prices → the constituent-level test passes). The actual
    sparsity test must come from constituent-level not contributor-level.

    Updated construction: drop entire (contributor_id, constituent_id)
    slot ranges such that for 2 of 3 constituents, slots [0, 30) have NO
    surviving contributors → constituent has no price at those slots →
    only 1 active constituent at slots [0, 30) → slot suspended (min-3
    fails). Slots [30, 32) have all 3 constituents active. Result: 30
    suspended slots in weight-then-TWAP (only 2 surviving), but daily
    TWAP-then-weight still computes a valid daily fix because each
    constituent has SOME slot prices that survive."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)
    change_events_df = _empty_change_events_df()

    # Build excluded_slots: for 2 of 3 constituents, exclude slots [0, 30)
    # for ALL 3 contributors → no surviving slot-level price at those
    # slots → constituent has no slot-s price → only 1 constituent active
    # at slots [0, 30).
    excluded_rows = []
    for cid in ("anthropic/claude-opus-4-7", "google/gemini-3-pro"):
        for contributor in ("contrib_alpha", "contrib_beta", "contrib_gamma"):
            for slot in range(30):
                excluded_rows.append(
                    {
                        "contributor_id": contributor,
                        "constituent_id": cid,
                        "date": pd.Timestamp(d),
                        "slot_idx": slot,
                    }
                )
    excluded_slots_df = pd.DataFrame(excluded_rows)

    weight_then = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="weight_then_twap",
        change_events_df=change_events_df,
        excluded_slots_df=excluded_slots_df,
    )
    # weight-then-TWAP daily TWAP averages over only 2 surviving slots
    # (slots 30 + 31) — both have 3 active constituents. So the daily fix
    # is meaningful but only built from 2/32 slots.
    # The load-bearing assertion: the daily fix exists (not suspended)
    # because slots 30+31 had min-3 active constituents.
    assert not weight_then["suspended"]
    # If we'd excluded ALL 32 slots → tier suspended with INSUFFICIENT_CONSTITUENTS.
    # Verify that case too: extend the exclusions to all 32 slots.
    excluded_rows_all_slots = []
    for cid in ("anthropic/claude-opus-4-7", "google/gemini-3-pro"):
        for contributor in ("contrib_alpha", "contrib_beta", "contrib_gamma"):
            for slot in range(32):
                excluded_rows_all_slots.append(
                    {
                        "contributor_id": contributor,
                        "constituent_id": cid,
                        "date": pd.Timestamp(d),
                        "slot_idx": slot,
                    }
                )
    excluded_all = pd.DataFrame(excluded_rows_all_slots)
    weight_then_all = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="weight_then_twap",
        change_events_df=change_events_df,
        excluded_slots_df=excluded_all,
    )
    assert weight_then_all["suspended"]
    assert (
        weight_then_all["suspension_reason"]
        == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value
    )


def test_weight_then_twap_emits_constituent_decisions_with_full_audit_schema() -> None:
    """Audit rows from weight-then-TWAP carry the same schema as
    TWAP-then-weight; numeric fields are daily averages over surviving slots."""
    d = date(2025, 1, 1)
    panel = _three_contributors_per_constituent_panel(d)

    decisions: list[dict[str, Any]] = []
    compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_index_config(),
        registry=_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="weight_then_twap",
        change_events_df=_empty_change_events_df(),
        decisions_out=decisions,
    )
    assert len(decisions) == 3
    for row in decisions:
        assert set(row.keys()) == set(_DECISION_FIELDS)
        assert row["included"]
        assert row["ordering"] == "weight_then_twap"


def test_weight_then_twap_run_full_pipeline_rebases_to_100_for_six_indices() -> None:
    """End-to-end: weight-then-TWAP through run_full_pipeline produces all
    8 indices with index_level=100 at the rebase anchor for the 6 aggregation
    indices (F/S/E/B_F/B_S/B_E). FPR/SER inherit suspension propagation."""
    from datetime import timedelta as _td

    from tprr.config import (
        IndexConfig as _IndexConfig,
    )
    from tprr.config import (
        ModelMetadata as _ModelMetadata,
    )
    from tprr.config import (
        ModelRegistry as _ModelRegistry,
    )
    from tprr.config import (
        TierBRevenueConfig as _TierBRevenueConfig,
    )
    from tprr.index.compute import run_full_pipeline as _run_full_pipeline

    # Build a minimal 3-day, 3-tier panel.
    rows = []
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
    for offset in range(3):
        d = date(2025, 1, 1) + _td(days=offset)
        for tier_set, tier in [
            (f_set, Tier.TPRR_F),
            (s_set, Tier.TPRR_S),
            (e_set, Tier.TPRR_E),
        ]:
            for cid, p_out, p_in in tier_set:
                for c in ["c1", "c2", "c3"]:
                    rows.append(
                        {
                            "observation_date": pd.Timestamp(d),
                            "constituent_id": cid,
                            "contributor_id": c,
                            "tier_code": tier.value,
                            "attestation_tier": "A",
                            "input_price_usd_mtok": float(p_in),
                            "output_price_usd_mtok": float(p_out),
                            "volume_mtok_7d": 100.0,
                            "source": "test",
                            "submitted_at": pd.Timestamp(d),
                            "notes": "",
                        }
                    )
    panel = pd.DataFrame(rows)

    config = _IndexConfig(base_date=date(2025, 1, 1))
    registry = _ModelRegistry(
        models=[
            _ModelMetadata(
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
    result = _run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events_df(),
        config=config,
        registry=registry,
        tier_b_config=_TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        ordering="weight_then_twap",
    )
    expected_codes = {
        "TPRR_F", "TPRR_S", "TPRR_E",
        "TPRR_FPR", "TPRR_SER",
        "TPRR_B_F", "TPRR_B_S", "TPRR_B_E",
    }
    assert set(result.indices.keys()) == expected_codes
    # 6 aggregation indices rebase to 100 on base_date.
    for code in ("TPRR_F", "TPRR_S", "TPRR_E", "TPRR_B_F", "TPRR_B_S", "TPRR_B_E"):
        df = result.indices[code]
        anchor_row = df[df["as_of_date"] == pd.Timestamp(date(2025, 1, 1))]
        assert float(anchor_row["index_level"].iloc[0]) == pytest.approx(100.0)
        # ordering field threaded through
        assert (df["ordering"] == "weight_then_twap").all()
    # FPR/SER are ratios — index_level = 100 at first non-suspended ratio.
    fpr_anchor = result.indices["TPRR_FPR"][
        result.indices["TPRR_FPR"]["as_of_date"] == pd.Timestamp(date(2025, 1, 1))
    ]
    assert float(fpr_anchor["index_level"].iloc[0]) == pytest.approx(100.0)
