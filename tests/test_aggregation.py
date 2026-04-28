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
    SuspensionReason,
    collapse_constituent_price,
    compute_tier_index,
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
    return IndexConfig()  # λ=3, haircuts A=1.0/B=0.9/C=0.8, min_constituents=3


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


def test_compute_tier_index_tier_b_fallthrough_dominates_via_magnitude() -> None:
    """The cross-tier magnitude finding (DL 2026-04-29 priority fall-through):
    a single Tier B fall-through constituent with implied volume orders of
    magnitude larger than Tier A constituents will dominate the index even
    after the 0.9 haircut. Phase 7 must observe this; this test pins the
    property so it can't drift silently."""
    d = date(2025, 1, 1)
    rows = []
    # gpt-5-pro: only 2 contributors with volume → fails Tier A min-3, falls
    # through to Tier B (provider 'openai' has revenue config).
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
    # Tier B panel row for gpt-5-pro (derive_tier_b_volumes upstream emits these).
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
    # Two Tier-A-eligible constituents.
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
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=20_000_000.0),  # ~66,000:1 magnitude
    )
    assert not result["suspended"]
    assert result["n_constituents_a"] == 2
    assert result["n_constituents_b"] == 1
    assert result["n_constituents_c"] == 0
    # Tier B constituent dominates the weight share due to magnitude gap.
    assert result["tier_b_weight_share"] > 0.95


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


def test_run_tier_pipeline_unsupported_ordering_raises() -> None:
    panel = _three_contributors_per_constituent_panel(date(2025, 1, 1))
    with pytest.raises(NotImplementedError, match="weight-then-TWAP"):
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
