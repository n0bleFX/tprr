"""Tests for tprr.index.weights — three-tier selection + dual-weighted primitives.

Covers:

- The CLAUDE.md exponential-weight reference table at λ=3 (3-decimal match).
- Tier-priority fall-through per docs/decision_log.md 2026-04-29:
  Tier A when ≥3 contributors with attested non-zero volume; else Tier B
  when provider has revenue; else Tier C when rankings data exists; else
  excluded.
- Per-tier haircut application (1.0 / 0.5 / 0.8 — Phase 7H Batch C).
- The intentional cross-tier magnitude gap (Phase 10 must observe this —
  the test pins the property so it can't drift silently).
- Hypothesis property tests for exp/vol primitives.
- Error handling at boundary inputs (negative volume, non-positive
  median, empty input).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tprr.config import (
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
    TierBRevenueEntry,
)
from tprr.index.weights import (
    TierBVolumeFn,
    compute_dual_weights,
    compute_exp_weights,
    compute_tier_median,
    compute_tier_volume,
    compute_within_tier_share,
    exponential_weight,
    volume_weight,
)
from tprr.schema import AttestationTier, Tier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _registry() -> ModelRegistry:
    """Tiny registry: two F-tier constituents, one with provider 'openai',
    one with provider 'anthropic'."""
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


def _tier_b_config_with_openai() -> TierBRevenueConfig:
    """Tier B revenue config with two openai quarters; anthropic and google have none."""
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


def _index_config() -> IndexConfig:
    return IndexConfig()  # defaults: λ=3, haircuts A=1.0/B=0.5/C=0.8 (Phase 7H Batch C)


def _stub_tier_b_volume_fn(value: float = 100.0) -> TierBVolumeFn:
    """Return a callable that always emits ``value`` for any (provider, model, date)."""

    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return value

    return _fn


def _panel_row(
    *,
    constituent_id: str,
    contributor_id: str,
    observation_date: date,
    attestation_tier: AttestationTier,
    volume_mtok_7d: float,
    output_price_usd_mtok: float = 50.0,
    input_price_usd_mtok: float = 10.0,
    tier_code: Tier = Tier.TPRR_F,
    source: str = "test",
) -> dict[str, object]:
    return {
        "observation_date": pd.Timestamp(observation_date),
        "constituent_id": constituent_id,
        "contributor_id": contributor_id,
        "tier_code": tier_code.value,
        "attestation_tier": attestation_tier.value,
        "input_price_usd_mtok": float(input_price_usd_mtok),
        "output_price_usd_mtok": float(output_price_usd_mtok),
        "volume_mtok_7d": float(volume_mtok_7d),
        "source": source,
        "submitted_at": pd.Timestamp(observation_date),
        "notes": "",
    }


# ---------------------------------------------------------------------------
# volume_weight
# ---------------------------------------------------------------------------


def test_volume_weight_haircuts_per_tier() -> None:
    """Phase 7H Batch C (DL 2026-04-30): Tier B haircut 0.9 -> 0.5."""
    cfg = _index_config()
    assert volume_weight(100.0, AttestationTier.A, cfg) == pytest.approx(100.0)
    assert volume_weight(100.0, AttestationTier.B, cfg) == pytest.approx(50.0)
    assert volume_weight(100.0, AttestationTier.C, cfg) == pytest.approx(80.0)


def test_volume_weight_zero_volume_returns_zero() -> None:
    cfg = _index_config()
    assert volume_weight(0.0, AttestationTier.A, cfg) == 0.0
    assert volume_weight(0.0, AttestationTier.C, cfg) == 0.0


def test_volume_weight_negative_volume_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        volume_weight(-1.0, AttestationTier.A, _index_config())


# ---------------------------------------------------------------------------
# exponential_weight — CLAUDE.md reference table at λ=3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("distance_pct", "expected"),
    [
        (0.0, 1.000),
        (0.05, 0.861),
        (0.10, 0.741),
        (0.20, 0.549),
        (0.30, 0.407),
        (0.50, 0.223),
        (1.00, 0.050),
    ],
)
def test_exp_weight_matches_claude_md_table(distance_pct: float, expected: float) -> None:
    """At λ=3, exp_weight at distance d% from median matches the methodology table."""
    median = 100.0
    price = median * (1.0 + distance_pct)
    actual = exponential_weight(price, median, lambda_=3.0)
    assert actual == pytest.approx(expected, abs=5e-4)


def test_exp_weight_at_zero_distance_is_exactly_one() -> None:
    assert exponential_weight(50.0, 50.0, lambda_=3.0) == 1.0


def test_exp_weight_symmetric_around_median() -> None:
    median = 50.0
    above = exponential_weight(median * 1.2, median, lambda_=3.0)
    below = exponential_weight(median * 0.8, median, lambda_=3.0)
    assert above == pytest.approx(below)


def test_exp_weight_negative_price_raises() -> None:
    with pytest.raises(ValueError, match="price"):
        exponential_weight(-1.0, 50.0, lambda_=3.0)


def test_exp_weight_zero_median_raises() -> None:
    with pytest.raises(ValueError, match="tier_median"):
        exponential_weight(50.0, 0.0, lambda_=3.0)


def test_exp_weight_negative_lambda_raises() -> None:
    with pytest.raises(ValueError, match="lambda"):
        exponential_weight(50.0, 50.0, lambda_=-1.0)


# ---------------------------------------------------------------------------
# compute_tier_median
# ---------------------------------------------------------------------------


def test_tier_median_simple_list() -> None:
    assert compute_tier_median([10.0, 20.0, 30.0]) == 20.0


def test_tier_median_handles_pandas_series() -> None:
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    assert compute_tier_median(s) == 25.0


def test_tier_median_drops_nan() -> None:
    assert compute_tier_median([10.0, float("nan"), 20.0]) == 15.0


def test_tier_median_empty_raises() -> None:
    with pytest.raises(ValueError, match="no valid prices"):
        compute_tier_median([])


def test_tier_median_all_nan_raises() -> None:
    with pytest.raises(ValueError, match="no valid prices"):
        compute_tier_median([float("nan"), float("nan")])


# ---------------------------------------------------------------------------
# compute_tier_volume — priority fall-through
# ---------------------------------------------------------------------------


def test_tier_a_selected_when_three_contributors_with_volume() -> None:
    """Tier A wins when ≥3 contributors with non-zero attested volume exist."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id=f"contrib_{name}",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            )
            for name in ("alpha", "beta", "gamma")
        ]
    )

    result = compute_tier_volume(
        constituent_id="openai/gpt-5-pro",
        as_of_date=target_date,
        panel_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )

    assert result is not None
    tier, volume = result
    assert tier == AttestationTier.A
    assert volume == pytest.approx(300.0)


def test_tier_a_zero_volume_contributor_does_not_count() -> None:
    """A contributor row with volume_mtok_7d == 0 is ignored for the ≥3 count.

    This mirrors the methodology phrasing 'attested volumes' — zero is the
    explicit non-attestation signal.
    """
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_beta",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_gamma",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=0.0,
            ),
        ]
    )
    result = compute_tier_volume(
        constituent_id="openai/gpt-5-pro",
        as_of_date=target_date,
        panel_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=42.0),
    )
    # Only 2 contributors with non-zero → falls through to Tier B (openai has revenue).
    assert result is not None
    tier, volume = result
    assert tier == AttestationTier.B
    assert volume == pytest.approx(42.0)


def test_tier_b_selected_when_a_short_and_provider_has_revenue() -> None:
    """A=2 contributors + openai has revenue → Tier B."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_beta",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
        ]
    )
    result = compute_tier_volume(
        constituent_id="openai/gpt-5-pro",
        as_of_date=target_date,
        panel_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=12345.0),
    )
    assert result is not None
    tier, volume = result
    assert tier == AttestationTier.B
    assert volume == pytest.approx(12345.0)


def test_tier_c_selected_when_a_short_and_no_tier_b_revenue() -> None:
    """A=1 contributor + anthropic has no revenue + Tier C row exists → Tier C."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=50.0,
            ),
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="openrouter:aggregate",
                observation_date=target_date,
                attestation_tier=AttestationTier.C,
                volume_mtok_7d=55_000.0,
                source="openrouter_models",
            ),
        ]
    )
    result = compute_tier_volume(
        constituent_id="anthropic/claude-opus-4-7",
        as_of_date=target_date,
        panel_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),  # anthropic absent
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result is not None
    tier, volume = result
    assert tier == AttestationTier.C
    assert volume == pytest.approx(55_000.0)


def test_excluded_when_all_three_tiers_insufficient() -> None:
    """A=0 contributors, no Tier B provider revenue, no Tier C row → None."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=0.0,  # zero volume → excluded from A count
            ),
        ]
    )
    result = compute_tier_volume(
        constituent_id="anthropic/claude-opus-4-7",
        as_of_date=target_date,
        panel_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),  # anthropic absent
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result is None


def test_tier_c_zero_volume_does_not_satisfy() -> None:
    """A Tier C row with volume_mtok_7d == 0 (no rankings data) does not save the constituent.

    Mirrors decision_log 2026-04-28: 'Tier C rankings sparseness' — missing
    data is honestly missing.
    """
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="openrouter:aggregate",
                observation_date=target_date,
                attestation_tier=AttestationTier.C,
                volume_mtok_7d=0.0,  # no rankings data
            ),
        ]
    )
    result = compute_tier_volume(
        constituent_id="anthropic/claude-opus-4-7",
        as_of_date=target_date,
        panel_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result is None


def test_unknown_constituent_id_raises() -> None:
    """A constituent absent from the registry is a programming error."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="ghost/nonexistent",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
        ]
    )
    # Tier A insufficient (1 contributor); falls through to provider lookup.
    with pytest.raises(ValueError, match="not in registry"):
        compute_tier_volume(
            constituent_id="ghost/nonexistent",
            as_of_date=target_date,
            panel_df=panel,
            registry=_registry(),
            tier_b_config=_tier_b_config_with_openai(),
            tier_b_volume_fn=_stub_tier_b_volume_fn(),
        )


# ---------------------------------------------------------------------------
# compute_dual_weights — orchestration + haircut application
# ---------------------------------------------------------------------------


def test_dual_weights_haircut_applied_per_selected_tier() -> None:
    """Tier A constituent gets 1.0 haircut, Tier C constituent gets 0.8 haircut."""
    target_date = date(2025, 6, 1)
    panel_rows = [
        # openai/gpt-5-pro: 3 Tier A contributors → Tier A selected
        _panel_row(
            constituent_id="openai/gpt-5-pro",
            contributor_id=f"contrib_{name}",
            observation_date=target_date,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=100.0,
        )
        for name in ("alpha", "beta", "gamma")
    ]
    # google/gemini-3-pro: 0 Tier A, no Tier B revenue (google absent in
    # _tier_b_config_with_openai), 1 Tier C row → Tier C selected
    panel_rows.append(
        _panel_row(
            constituent_id="google/gemini-3-pro",
            contributor_id="openrouter:aggregate",
            observation_date=target_date,
            attestation_tier=AttestationTier.C,
            volume_mtok_7d=50_000.0,
        )
    )
    panel = pd.DataFrame(panel_rows)

    out = compute_dual_weights(
        panel_day_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        config=_index_config(),
    )

    assert set(out["constituent_id"]) == {
        "openai/gpt-5-pro",
        "google/gemini-3-pro",
    }
    # Phase 7H Batch B (DL 2026-04-30) long-format: openai/gpt-5-pro has
    # both Tier A (3 contributors) AND Tier B (provider revenue config
    # present) → 2 rows. google/gemini-3-pro has only Tier C → 1 row.
    # Total 3 rows.
    assert len(out) == 3
    assert set(out["constituent_id"]) == {
        "openai/gpt-5-pro",
        "google/gemini-3-pro",
    }

    gpt_a = out[
        (out["constituent_id"] == "openai/gpt-5-pro") & (out["attestation_tier"] == "A")
    ].iloc[0]
    gpt_b = out[
        (out["constituent_id"] == "openai/gpt-5-pro") & (out["attestation_tier"] == "B")
    ].iloc[0]
    gemini_c = out[out["constituent_id"] == "google/gemini-3-pro"].iloc[0]

    # gpt-5-pro: Tier A + Tier B available → coefficients redistribute
    # to 0.6/0.7 ≈ 0.857 (A) and 0.1/0.7 ≈ 0.143 (B); each tier has only
    # gpt-5-pro → share = 1.0; w_vol_contribution = coef x share x haircut.
    assert gpt_a["coefficient"] == pytest.approx(0.6 / 0.7)
    assert gpt_a["within_tier_volume_share"] == pytest.approx(1.0)
    assert gpt_a["w_vol_contribution"] == pytest.approx((0.6 / 0.7) * 1.0)

    assert gpt_b["coefficient"] == pytest.approx(0.1 / 0.7)
    assert gpt_b["within_tier_volume_share"] == pytest.approx(1.0)
    # Phase 7H Batch C (DL 2026-04-30): Tier B haircut 0.9 -> 0.5.
    assert gpt_b["w_vol_contribution"] == pytest.approx((0.1 / 0.7) * 0.5)

    # gemini: Tier C only → coefficient = 1.0, share = 1.0, w_vol_contribution = 0.8.
    assert gemini_c["attestation_tier"] == "C"
    assert gemini_c["coefficient"] == pytest.approx(1.0)
    assert gemini_c["w_vol_contribution"] == pytest.approx(0.8)


def test_dual_weights_tier_b_haircut() -> None:
    """Tier B selected → 0.5 haircut applied (Phase 7H Batch C; was 0.9)."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
            _panel_row(
                constituent_id="openai/gpt-5-pro",
                contributor_id="contrib_beta",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=100.0,
            ),
        ]
    )
    out = compute_dual_weights(
        panel_day_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=10_000.0),
        config=_index_config(),
    )
    row = out.iloc[0]
    # Phase 7H Batch C (DL 2026-04-30): Tier B haircut 0.9 -> 0.5.
    # Single Tier-B-resolved constituent → 1 row → coefficient=1.0,
    # share=1.0, w_vol_contribution = 1.0 x 1.0 x 0.5 = 0.5.
    assert row["attestation_tier"] == "B"
    assert row["raw_volume"] == pytest.approx(10_000.0)
    assert row["within_tier_volume_share"] == pytest.approx(1.0)
    assert row["coefficient"] == pytest.approx(1.0)
    assert row["w_vol_contribution"] == pytest.approx(0.5)


def test_dual_weights_excludes_unweightable_constituent() -> None:
    """A constituent that fails all three tiers is omitted from the output frame."""
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            # openai gets Tier A
            *[
                _panel_row(
                    constituent_id="openai/gpt-5-pro",
                    contributor_id=f"contrib_{name}",
                    observation_date=target_date,
                    attestation_tier=AttestationTier.A,
                    volume_mtok_7d=100.0,
                )
                for name in ("alpha", "beta", "gamma")
            ],
            # anthropic: 1 Tier A, no Tier B (anthropic absent), no Tier C → excluded
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=80.0,
            ),
        ]
    )
    out = compute_dual_weights(
        panel_day_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        config=_index_config(),
    )
    # Phase 7H Batch B: openai/gpt-5-pro emits 2 rows (Tier A + Tier B);
    # anthropic excluded (only 1 Tier A contributor, no Tier B, no Tier C).
    # Set comparison ignores duplicates from long-format.
    assert set(out["constituent_id"]) == {"openai/gpt-5-pro"}


def test_dual_weights_output_label_is_selected_tier_not_panel_row_tier() -> None:
    """When a constituent has 1 Tier A row + 1 Tier C row and Tier A is short,
    the output's ``attestation_tier`` is "C" (the selected tier from priority
    fall-through), not "A" (a label that exists on a panel row).

    This pins the selected-vs-source-label distinction. A future regression
    that copies the panel row's attestation_tier into the output would pass
    most other tier-selection tests but fail this one.
    """
    target_date = date(2025, 6, 1)
    panel = pd.DataFrame(
        [
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="contrib_alpha",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=80.0,  # 1 Tier A contributor — below the ≥3 threshold
            ),
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id="openrouter:aggregate",
                observation_date=target_date,
                attestation_tier=AttestationTier.C,
                volume_mtok_7d=42_000.0,
            ),
        ]
    )
    out = compute_dual_weights(
        panel_day_df=panel,
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),  # anthropic absent → no Tier B
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        config=_index_config(),
    )
    assert len(out) == 1
    row = out.iloc[0]
    # Phase 7H Batch B: single Tier-C-resolved constituent → 1 row →
    # coefficient=1.0, share=1.0, w_vol_contribution = 1.0 x 1.0 x 0.8 = 0.8.
    assert row["constituent_id"] == "anthropic/claude-opus-4-7"
    assert row["attestation_tier"] == "C"
    assert row["raw_volume"] == pytest.approx(42_000.0)
    assert row["within_tier_volume_share"] == pytest.approx(1.0)
    assert row["coefficient"] == pytest.approx(1.0)
    assert row["w_vol_contribution"] == pytest.approx(0.8)


def test_dual_weights_empty_panel_returns_empty_frame() -> None:
    out = compute_dual_weights(
        panel_day_df=pd.DataFrame(),
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        config=_index_config(),
    )
    assert out.empty
    # Phase 7H Batch B long-format columns.
    assert list(out.columns) == [
        "constituent_id",
        "observation_date",
        "attestation_tier",
        "raw_volume",
        "within_tier_volume_share",
        "coefficient",
        "w_vol_contribution",
    ]


def test_dual_weights_rejects_multi_date_input() -> None:
    """Function operates on one day; passing a multi-day panel is a caller bug."""
    rows = [
        _panel_row(
            constituent_id="openai/gpt-5-pro",
            contributor_id="contrib_alpha",
            observation_date=d,
            attestation_tier=AttestationTier.A,
            volume_mtok_7d=100.0,
        )
        for d in (date(2025, 6, 1), date(2025, 6, 2))
    ]
    with pytest.raises(ValueError, match="single observation_date"):
        compute_dual_weights(
            panel_day_df=pd.DataFrame(rows),
            registry=_registry(),
            tier_b_config=_tier_b_config_with_openai(),
            tier_b_volume_fn=_stub_tier_b_volume_fn(),
            config=_index_config(),
        )


# ---------------------------------------------------------------------------
# Cross-tier magnitude property — Phase 10 must observe this
# ---------------------------------------------------------------------------


def test_w_vol_bounded_under_within_tier_share_normalization() -> None:
    """Under Phase 7H Batch A within-tier-share normalization (DL 2026-04-30),
    w_vol = within_tier_share x haircut. Both factors are bounded:
    within_tier_share in [0, 1] by construction (it's a proportion of the
    tier total), and haircut in {1.0, 0.5, 0.8} by config. So w_vol in [0, 1]
    regardless of underlying raw-volume scale.

    This test pins the bounded-w_vol property that Phase 7H Batch A
    introduced. It REPLACES the prior test_cross_tier_magnitude_gap_is_
    intentional test which asserted the >100x cross-tier gap that
    within-tier-share normalization deliberately closes. The two are
    incompatible by design — Phase 7H's purpose is to close that gap
    so continuous blending in Batch B has structurally comparable inputs.

    See DL 2026-04-30 "Phase 7H methodology design" entry for context.
    """
    target_date = date(2025, 6, 1)
    panel_rows = [
        # X: anthropic/claude-opus-4-7 — Tier A (3 contributors, panel-sum
        # volume ~80 mtok/7d each → 240 mtok total panel-sum)
        *[
            _panel_row(
                constituent_id="anthropic/claude-opus-4-7",
                contributor_id=f"contrib_{name}",
                observation_date=target_date,
                attestation_tier=AttestationTier.A,
                volume_mtok_7d=80.0,
            )
            for name in ("alpha", "beta", "gamma")
        ],
        # Y: google/gemini-3-pro - Tier C (whole-market rankings volume,
        # 50_000 mtok/7d, ~200x the Tier A panel-sum)
        _panel_row(
            constituent_id="google/gemini-3-pro",
            contributor_id="openrouter:aggregate",
            observation_date=target_date,
            attestation_tier=AttestationTier.C,
            volume_mtok_7d=50_000.0,
        ),
    ]
    out = compute_dual_weights(
        panel_day_df=pd.DataFrame(panel_rows),
        registry=_registry(),
        tier_b_config=_tier_b_config_with_openai(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        config=_index_config(),
    )

    # Phase 7H Batch B: long-format. Each constituent has 1 row per
    # contributing tier; here each has only 1 contributing tier, so 1
    # row per constituent. w_vol_contribution = coef x share x haircut.
    a_w = float(
        out.set_index("constituent_id").loc["anthropic/claude-opus-4-7", "w_vol_contribution"]
    )
    c_w = float(out.set_index("constituent_id").loc["google/gemini-3-pro", "w_vol_contribution"])

    # Both w_vol_contributions bounded in [0, 1].
    assert 0.0 <= a_w <= 1.0, f"Tier A w_vol_contribution out of [0, 1]: {a_w}"
    assert 0.0 <= c_w <= 1.0, f"Tier C w_vol_contribution out of [0, 1]: {c_w}"

    # Single tier per constituent → coefficient redistributes to 1.0 →
    # w_vol_contribution = 1.0 x 1.0 x haircut = haircut.
    assert a_w == pytest.approx(1.0)
    assert c_w == pytest.approx(0.8)

    # Raw-volume ratio is preserved in raw_volume (audit-trail field) but
    # NOT in w_vol — that's the whole point.
    a_raw = float(out.set_index("constituent_id").loc["anthropic/claude-opus-4-7", "raw_volume"])
    c_raw = float(out.set_index("constituent_id").loc["google/gemini-3-pro", "raw_volume"])
    assert c_raw / a_raw > 100, (
        "Raw volumes still reflect the realistic ~200x panel-sum vs rankings "
        "magnitude — w_vol normalisation does not erase the underlying signal, "
        "it just isolates it from the dual-weighted formula's volume term."
    )


# ---------------------------------------------------------------------------
# compute_exp_weights
# ---------------------------------------------------------------------------


def test_exp_weights_preserves_index() -> None:
    prices = pd.Series(
        [20.0, 22.0, 23.0, 25.0, 50.0],
        index=["a", "b", "c", "d", "e"],
    )
    weights = compute_exp_weights(prices, lambda_=3.0)
    assert list(weights.index) == ["a", "b", "c", "d", "e"]


def test_exp_weights_at_median_is_one() -> None:
    """The price exactly at the tier median gets w_exp = 1.0."""
    prices = pd.Series([20.0, 23.0, 50.0])  # median = 23
    weights = compute_exp_weights(prices, lambda_=3.0)
    assert weights.iloc[1] == pytest.approx(1.0)


def test_exp_weights_matches_prompts_md_5a2_fixture() -> None:
    """prompts.md 5a.2: prices [20, 22, 23, 25, 50], median 23, λ=3."""
    prices = pd.Series([20.0, 22.0, 23.0, 25.0, 50.0])
    weights = compute_exp_weights(prices, lambda_=3.0)
    # Distance from median 23 in fractional terms:
    # 20 → 13.04%, 22 → 4.35%, 23 → 0%, 25 → 8.70%, 50 → 117.39%
    expected = np.exp(-3.0 * np.array([3.0 / 23, 1.0 / 23, 0.0, 2.0 / 23, 27.0 / 23]))
    assert np.allclose(weights.to_numpy(), expected, atol=1e-9)


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


@given(
    median=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False),
    distance_pct=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
    lambda_=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
)
def test_property_exp_weight_in_unit_interval(
    median: float, distance_pct: float, lambda_: float
) -> None:
    """Exponential weight is always in (0, 1] for non-negative inputs."""
    price = median * (1.0 + distance_pct)
    w = exponential_weight(price, median, lambda_)
    assert 0.0 < w <= 1.0


@given(
    median=st.floats(min_value=0.1, max_value=100.0, allow_nan=False),
    d1=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    d2=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    lambda_=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
)
def test_property_exp_weight_monotonic_in_distance(
    median: float, d1: float, d2: float, lambda_: float
) -> None:
    """Closer to median → higher weight, regardless of side."""
    p1 = median * (1.0 + d1)
    p2 = median * (1.0 + d2)
    w1 = exponential_weight(p1, median, lambda_)
    w2 = exponential_weight(p2, median, lambda_)
    if d1 < d2:
        assert w1 >= w2
    elif d1 > d2:
        assert w1 <= w2
    else:
        assert w1 == pytest.approx(w2)


@given(
    median=st.floats(min_value=0.1, max_value=100.0, allow_nan=False),
    distance_pct=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    lambda_=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
)
def test_property_exp_weight_symmetric(median: float, distance_pct: float, lambda_: float) -> None:
    """w_exp(median + d) == w_exp(median - d) when both are positive."""
    p_above = median * (1.0 + distance_pct)
    p_below = median * (1.0 - distance_pct)
    if p_below < 0:
        return  # symmetry only well-defined when both sides are non-negative prices
    w_above = exponential_weight(p_above, median, lambda_)
    w_below = exponential_weight(p_below, median, lambda_)
    assert w_above == pytest.approx(w_below)


@given(
    volume=st.floats(min_value=0.0, max_value=1e9, allow_nan=False),
    scale=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    tier=st.sampled_from(list(AttestationTier)),
)
def test_property_volume_weight_linear_in_volume(
    volume: float, scale: float, tier: AttestationTier
) -> None:
    """Scaling volume by k scales w_vol by k (haircut is constant)."""
    cfg = _index_config()
    w_base = volume_weight(volume, tier, cfg)
    w_scaled = volume_weight(volume * scale, tier, cfg)
    assert w_scaled == pytest.approx(w_base * scale, rel=1e-9)


# ---------------------------------------------------------------------------
# compute_within_tier_share — Phase 7H Batch A (DL 2026-04-30)
# ---------------------------------------------------------------------------


def test_compute_within_tier_share_basic() -> None:
    """Three positive volumes → shares sum to 1.0 and reflect proportions."""
    out = compute_within_tier_share({"a": 100.0, "b": 200.0, "c": 700.0})
    assert out["a"] == pytest.approx(0.10)
    assert out["b"] == pytest.approx(0.20)
    assert out["c"] == pytest.approx(0.70)
    assert sum(out.values()) == pytest.approx(1.0)


def test_compute_within_tier_share_single_constituent_returns_one() -> None:
    """Single constituent occupies the full tier → share = 1.0."""
    out = compute_within_tier_share({"only": 42.0})
    assert out == {"only": 1.0}


def test_compute_within_tier_share_empty_input_returns_empty() -> None:
    """Empty input → empty dict (no constituents to normalize)."""
    out = compute_within_tier_share({})
    assert out == {}


def test_compute_within_tier_share_all_zero_volumes_returns_zeros() -> None:
    """All-zero volumes → all-zero shares (defensive against div-by-zero)."""
    out = compute_within_tier_share({"a": 0.0, "b": 0.0, "c": 0.0})
    assert out == {"a": 0.0, "b": 0.0, "c": 0.0}


def test_compute_within_tier_share_negative_volume_raises() -> None:
    with pytest.raises(ValueError, match="negative volume"):
        compute_within_tier_share({"a": 100.0, "b": -1.0})


def test_compute_within_tier_share_bounded_in_zero_to_one() -> None:
    """Phase 7H Batch A invariant: every share ∈ [0, 1] regardless of input
    scale. This is the property that makes within-tier shares structurally
    comparable across tiers (the cross-tier blending prerequisite)."""
    # Mix tiny + huge volumes to verify the invariant under wide scale ranges.
    out = compute_within_tier_share(
        {
            "tiny": 1e-6,
            "small": 1.0,
            "medium": 1_000.0,
            "huge": 1_000_000_000.0,
        }
    )
    for cid, share in out.items():
        assert 0.0 <= share <= 1.0, f"{cid} share {share} out of [0, 1]"
    assert sum(out.values()) == pytest.approx(1.0)


@given(
    volumes=st.lists(
        st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    )
)
def test_property_compute_within_tier_share_sum_invariant(
    volumes: list[float],
) -> None:
    """Sum of shares equals 1.0 (or all-zero if total volume is zero)."""
    raw = {f"c{i}": v for i, v in enumerate(volumes)}
    out = compute_within_tier_share(raw)
    total = sum(out.values())
    if sum(volumes) > 0:
        assert total == pytest.approx(1.0, abs=1e-9)
    else:
        assert total == 0.0
