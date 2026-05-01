"""Tests for tprr.index.tier_b — Option B volume derivation with sparse-rankings priors.

Per decision log 2026-04-29 (Tier B price-implied within-provider split).
Covers:

- All-uncovered provider, both priors (price_implied default, equal_volume β):
  cheapest model gets MORE volume under δ; equal volume under β.
- Single-covered provider (deepseek-only): canonical Option B path.
- Mixed-coverage provider (1 covered + 1 uncovered): covered uses canonical
  Option B within its share group; uncovered uses chosen prior; revenue
  identity holds across the union.
- Revenue identity Σ(vol * p) ≈ R for every covered/uncovered/mixed shape.
- Quarterly → 7-day conversion factor (vol_7d * 91.25/7 ≈ vol_quarterly).
- Missing provider: no rows emitted.
- Empty rankings: equivalent to all-uncovered.
- Empty registry-for-provider: warning + skipped.
- Determinism: same inputs → byte-identical output.
- Output schema: rows are PanelObservationDF-compatible.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tprr.config import (
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
    TierBRevenueEntry,
)
from tprr.index.tier_b import (
    DAYS_PER_QUARTER,
    TIER_B_SOURCE,
    derive_tier_b_volumes,
)
from tprr.schema import AttestationTier, PanelObservationDF, Tier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _registry_two_providers() -> ModelRegistry:
    """openai with 4 models (no rankings); deepseek with 1 model (has rankings)."""
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
                constituent_id="openai/gpt-5",
                tier=Tier.TPRR_F,
                provider="openai",
                canonical_name="GPT-5",
                baseline_input_price_usd_mtok=10.0,
                baseline_output_price_usd_mtok=40.0,
            ),
            ModelMetadata(
                constituent_id="openai/gpt-5-mini",
                tier=Tier.TPRR_S,
                provider="openai",
                canonical_name="GPT-5 Mini",
                baseline_input_price_usd_mtok=0.5,
                baseline_output_price_usd_mtok=4.0,
            ),
            ModelMetadata(
                constituent_id="openai/gpt-5-nano",
                tier=Tier.TPRR_E,
                provider="openai",
                canonical_name="GPT-5 Nano",
                baseline_input_price_usd_mtok=0.15,
                baseline_output_price_usd_mtok=0.60,
            ),
            ModelMetadata(
                constituent_id="deepseek/deepseek-v3-2",
                tier=Tier.TPRR_E,
                provider="deepseek",
                canonical_name="DeepSeek V3.2",
                baseline_input_price_usd_mtok=0.25,
                baseline_output_price_usd_mtok=1.0,
            ),
        ]
    )


def _revenue_two_providers() -> TierBRevenueConfig:
    """One quarter of revenue per provider, so interpolation is trivial."""
    return TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="openai",
                period="2025-Q2",
                amount_usd=440_000_000.0,  # matches the actual config value
                source="analyst_triangulation",
            ),
            TierBRevenueEntry(
                provider="deepseek",
                period="2025-Q2",
                amount_usd=130_000_000.0,
                source="synthetic_for_mvp",
            ),
        ]
    )


def _empty_panel() -> pd.DataFrame:
    """Empty panel — algorithm falls back to registry baselines for prices."""
    return pd.DataFrame(
        {
            "observation_date": pd.Series([], dtype="datetime64[ns]"),
            "constituent_id": pd.Series([], dtype="object"),
            "contributor_id": pd.Series([], dtype="object"),
            "tier_code": pd.Series([], dtype="object"),
            "attestation_tier": pd.Series([], dtype="object"),
            "input_price_usd_mtok": pd.Series([], dtype="float64"),
            "output_price_usd_mtok": pd.Series([], dtype="float64"),
            "volume_mtok_7d": pd.Series([], dtype="float64"),
            "source": pd.Series([], dtype="object"),
            "submitted_at": pd.Series([], dtype="datetime64[ns]"),
            "notes": pd.Series([], dtype="object"),
        }
    )


def _rankings_deepseek_only() -> pd.DataFrame:
    """Mirror the v0.1 reality: only deepseek/deepseek-v3-2 in rankings."""
    return pd.DataFrame(
        {
            "constituent_id": ["deepseek/deepseek-v3-2"],
            "volume_mtok_7d": [52_118.57],  # ≈ 52B tokens / 1e6 from rankings JSON
        }
    )


def _empty_rankings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "constituent_id": pd.Series([], dtype="object"),
            "volume_mtok_7d": pd.Series([], dtype="float64"),
        }
    )


def _q2_2025_anchor() -> date:
    """End-of-Q2-2025 date — interpolation hits the exact entry value."""
    return date(2025, 6, 30)


# ---------------------------------------------------------------------------
# Single-covered provider (deepseek-only) — canonical Option B
# ---------------------------------------------------------------------------


def test_single_covered_provider_canonical_option_b() -> None:
    """deepseek has 1 registry model with rankings; Option B trivially produces
    the full provider revenue → volume conversion at the model price."""
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="deepseek/deepseek-v3-2",
                tier=Tier.TPRR_E,
                provider="deepseek",
                canonical_name="DeepSeek V3.2",
                baseline_input_price_usd_mtok=0.25,
                baseline_output_price_usd_mtok=1.0,
            )
        ]
    )
    revenue = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="deepseek",
                period="2025-Q2",
                amount_usd=130_000_000.0,
                source="synthetic_for_mvp",
            )
        ]
    )
    rankings = pd.DataFrame(
        {
            "constituent_id": ["deepseek/deepseek-v3-2"],
            "volume_mtok_7d": [52_118.57],
        }
    )
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=rankings,
        tier_b_revenue_config=revenue,
        model_registry=registry,
    )
    assert len(out) == 1
    row = out.iloc[0]
    # Canonical Option B with single covered model: ref_price = p, total = R/p,
    # vol_quarterly_mtok = 130M / 1.0 = 130_000_000 mtok per quarter.
    expected_quarterly_mtok = 130_000_000.0 / 1.0
    expected_seven_day = expected_quarterly_mtok * 7.0 / DAYS_PER_QUARTER
    assert row["volume_mtok_7d"] == pytest.approx(expected_seven_day)
    assert row["attestation_tier"] == AttestationTier.B.value
    assert row["source"] == TIER_B_SOURCE
    assert row["constituent_id"] == "deepseek/deepseek-v3-2"


# ---------------------------------------------------------------------------
# All-uncovered provider — both priors
# ---------------------------------------------------------------------------


def test_all_uncovered_price_implied_directionality() -> None:
    """openai's 4 models have no rankings; under price_implied, the cheapest
    model receives the most volume and the priciest the least."""
    registry = _registry_two_providers()
    revenue = _revenue_two_providers()
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="price_implied",
    )
    openai_rows = out[out["constituent_id"].str.startswith("openai/")].set_index("constituent_id")
    assert set(openai_rows.index) == {
        "openai/gpt-5-pro",
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "openai/gpt-5-nano",
    }
    # Cheaper model → more volume under δ.
    assert (
        openai_rows.loc["openai/gpt-5-nano", "volume_mtok_7d"]
        > openai_rows.loc["openai/gpt-5-mini", "volume_mtok_7d"]
    )
    assert (
        openai_rows.loc["openai/gpt-5-mini", "volume_mtok_7d"]
        > openai_rows.loc["openai/gpt-5", "volume_mtok_7d"]
    )
    assert (
        openai_rows.loc["openai/gpt-5", "volume_mtok_7d"]
        > openai_rows.loc["openai/gpt-5-pro", "volume_mtok_7d"]
    )


def test_all_uncovered_price_implied_revenue_identity() -> None:
    """Σ(vol_quarterly * p) ≈ R for the openai bucket under price_implied prior."""
    registry = _registry_two_providers()
    revenue = _revenue_two_providers()
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="price_implied",
    )
    openai_rows = out[out["constituent_id"].str.startswith("openai/")]
    accounting_revenue_quarterly = float(
        (
            openai_rows["volume_mtok_7d"]
            * (DAYS_PER_QUARTER / 7.0)
            * openai_rows["output_price_usd_mtok"]
        ).sum()
    )
    assert accounting_revenue_quarterly == pytest.approx(440_000_000.0, rel=1e-9)


def test_all_uncovered_equal_volume_prior_yields_identical_volumes() -> None:
    """Under prior='equal_volume' all 4 openai models receive identical volume."""
    registry = _registry_two_providers()
    revenue = _revenue_two_providers()
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="equal_volume",
    )
    openai_vols = out.loc[
        out["constituent_id"].str.startswith("openai/"), "volume_mtok_7d"
    ].to_numpy()
    assert len(openai_vols) == 4
    assert np.allclose(openai_vols, openai_vols[0])


def test_all_uncovered_equal_volume_revenue_identity() -> None:
    """Σ(vol_quarterly * p) ≈ R under equal_volume prior."""
    registry = _registry_two_providers()
    revenue = _revenue_two_providers()
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="equal_volume",
    )
    openai_rows = out[out["constituent_id"].str.startswith("openai/")]
    accounting_revenue_quarterly = float(
        (
            openai_rows["volume_mtok_7d"]
            * (DAYS_PER_QUARTER / 7.0)
            * openai_rows["output_price_usd_mtok"]
        ).sum()
    )
    assert accounting_revenue_quarterly == pytest.approx(440_000_000.0, rel=1e-9)


def test_priors_produce_different_volume_distributions() -> None:
    """The two priors must produce different per-model volumes for an
    uncovered provider — Phase 10 sensitivity needs daylight between them."""
    registry = _registry_two_providers()
    revenue = _revenue_two_providers()
    out_pi = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="price_implied",
    )
    out_ev = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="equal_volume",
    )
    pi_nano = float(
        out_pi.loc[out_pi["constituent_id"] == "openai/gpt-5-nano", "volume_mtok_7d"].iloc[0]
    )
    ev_nano = float(
        out_ev.loc[out_ev["constituent_id"] == "openai/gpt-5-nano", "volume_mtok_7d"].iloc[0]
    )
    # gpt-5-nano under price_implied (cheap → lots of volume) should be
    # vastly larger than under equal_volume.
    assert pi_nano > 5 * ev_nano


# ---------------------------------------------------------------------------
# Mixed-coverage hypothetical
# ---------------------------------------------------------------------------


def test_mixed_coverage_revenue_identity_holds_across_union() -> None:
    """A provider with 1 covered + 1 uncovered model: revenue identity
    Σ(vol * p) == R must hold across the union (decision_log 2026-04-29
    coverage-share assumption + scale-normalisation step 7)."""
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="provider_x/cheap_covered",
                tier=Tier.TPRR_E,
                provider="provider_x",
                canonical_name="Cheap Covered",
                baseline_input_price_usd_mtok=0.5,
                baseline_output_price_usd_mtok=2.0,
            ),
            ModelMetadata(
                constituent_id="provider_x/premium_uncovered",
                tier=Tier.TPRR_F,
                provider="provider_x",
                canonical_name="Premium Uncovered",
                baseline_input_price_usd_mtok=10.0,
                baseline_output_price_usd_mtok=50.0,
            ),
        ]
    )
    revenue = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="provider_x",
                period="2025-Q2",
                amount_usd=100_000_000.0,
                source="synthetic_for_mvp",
            )
        ]
    )
    rankings = pd.DataFrame(
        {
            "constituent_id": ["provider_x/cheap_covered"],
            "volume_mtok_7d": [10_000.0],
        }
    )
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=rankings,
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="price_implied",
    )
    assert len(out) == 2
    accounting_revenue_quarterly = float(
        (out["volume_mtok_7d"] * (DAYS_PER_QUARTER / 7.0) * out["output_price_usd_mtok"]).sum()
    )
    assert accounting_revenue_quarterly == pytest.approx(100_000_000.0, rel=1e-9)


def test_mixed_coverage_uses_coverage_share_partition() -> None:
    """The covered side gets R * n_covered/n_total; the uncovered side gets
    R * n_uncovered/n_total. With 1 covered + 1 uncovered, each side gets R/2.

    Verify by constructing a case where covered's price = uncovered's price:
    under price_implied uncovered gets vol = (R/2)/p; canonical covered with
    a single model also gets vol = (R/2)/p. Both volumes must be equal.
    """
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="provider_x/covered",
                tier=Tier.TPRR_S,
                provider="provider_x",
                canonical_name="Covered",
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=5.0,
            ),
            ModelMetadata(
                constituent_id="provider_x/uncovered",
                tier=Tier.TPRR_S,
                provider="provider_x",
                canonical_name="Uncovered",
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=5.0,
            ),
        ]
    )
    revenue = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="provider_x",
                period="2025-Q2",
                amount_usd=50_000_000.0,
                source="synthetic_for_mvp",
            )
        ]
    )
    rankings = pd.DataFrame(
        {
            "constituent_id": ["provider_x/covered"],
            "volume_mtok_7d": [1_000.0],
        }
    )
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=rankings,
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="price_implied",
    )
    cv = float(out.loc[out["constituent_id"] == "provider_x/covered", "volume_mtok_7d"].iloc[0])
    uv = float(out.loc[out["constituent_id"] == "provider_x/uncovered", "volume_mtok_7d"].iloc[0])
    assert cv == pytest.approx(uv, rel=1e-9)


def test_uncovered_two_model_hand_computed_numerical() -> None:
    """Direct numerical assertion against a hand-computed expected output.

    Setup: provider_x with two uncovered models — cheap at $1.00/Mtok and
    expensive at $4.00/Mtok — and quarterly revenue $1,000,000,000.

    Hand computation under prior="price_implied" with all-uncovered:
      - n_total = 2; n_covered = 0; n_uncovered = 2
      - R_uncovered = R = $1,000,000,000
      - Per-model revenue share = R_uncovered / n_uncovered = $500,000,000
      - vol_quarterly_cheap     = $500,000,000 / $1.00 = 500,000,000 mtok
      - vol_quarterly_expensive = $500,000,000 / $4.00 = 125,000,000 mtok
      - vol_7d_cheap     = 500,000,000 * 7 / 91.25 ≈ 38,356,164.38 mtok/7d
      - vol_7d_expensive = 125,000,000 * 7 / 91.25 ≈  9,589,041.10 mtok/7d
      - Revenue identity: 500M*$1 + 125M*$4 = $500M + $500M = $1B ✓

    Pairs with test_mixed_coverage_uses_coverage_share_partition (which
    catches algorithmic consistency via same-price models); this catches
    numerical correctness of the actual per-model conversion.
    """
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="provider_x/cheap",
                tier=Tier.TPRR_E,
                provider="provider_x",
                canonical_name="Cheap",
                baseline_input_price_usd_mtok=0.5,
                baseline_output_price_usd_mtok=1.0,
            ),
            ModelMetadata(
                constituent_id="provider_x/expensive",
                tier=Tier.TPRR_F,
                provider="provider_x",
                canonical_name="Expensive",
                baseline_input_price_usd_mtok=2.0,
                baseline_output_price_usd_mtok=4.0,
            ),
        ]
    )
    revenue = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="provider_x",
                period="2025-Q2",
                amount_usd=1_000_000_000.0,
                source="synthetic_for_mvp",
            )
        ]
    )
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
        prior="price_implied",
    )
    expected_cheap_7d = 500_000_000.0 * 7.0 / DAYS_PER_QUARTER
    expected_expensive_7d = 125_000_000.0 * 7.0 / DAYS_PER_QUARTER
    cheap_vol = float(
        out.loc[out["constituent_id"] == "provider_x/cheap", "volume_mtok_7d"].iloc[0]
    )
    expensive_vol = float(
        out.loc[out["constituent_id"] == "provider_x/expensive", "volume_mtok_7d"].iloc[0]
    )
    assert cheap_vol == pytest.approx(expected_cheap_7d, rel=1e-12)
    assert expensive_vol == pytest.approx(expected_expensive_7d, rel=1e-12)
    # Sanity check on the absolute numbers themselves, not just the formula.
    assert cheap_vol == pytest.approx(38_356_164.3835, rel=1e-9)
    assert expensive_vol == pytest.approx(9_589_041.0959, rel=1e-9)


# ---------------------------------------------------------------------------
# Missing / empty inputs
# ---------------------------------------------------------------------------


def test_provider_with_revenue_but_no_registry_models_skipped() -> None:
    """A provider in revenue config with no registered models emits no rows
    (logged at INFO; not raised)."""
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="deepseek/deepseek-v3-2",
                tier=Tier.TPRR_E,
                provider="deepseek",
                canonical_name="DeepSeek V3.2",
                baseline_input_price_usd_mtok=0.25,
                baseline_output_price_usd_mtok=1.0,
            )
        ]
    )
    revenue = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="ghost_provider",
                period="2025-Q2",
                amount_usd=999_000_000.0,
                source="synthetic_for_mvp",
            ),
            TierBRevenueEntry(
                provider="deepseek",
                period="2025-Q2",
                amount_usd=130_000_000.0,
                source="synthetic_for_mvp",
            ),
        ]
    )
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_rankings_deepseek_only(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
    )
    assert set(out["constituent_id"]) == {"deepseek/deepseek-v3-2"}


def test_empty_revenue_config_returns_empty_frame() -> None:
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=TierBRevenueConfig(entries=[]),
        model_registry=_registry_two_providers(),
    )
    assert out.empty
    # Schema columns still present so downstream concat doesn't break.
    assert list(out.columns) == [
        "observation_date",
        "constituent_id",
        "contributor_id",
        "tier_code",
        "attestation_tier",
        "input_price_usd_mtok",
        "output_price_usd_mtok",
        "volume_mtok_7d",
        "source",
        "submitted_at",
        "notes",
    ]


def test_empty_rankings_treated_as_all_uncovered() -> None:
    """Empty rankings frame and absent-from-rankings have identical effect."""
    registry = _registry_two_providers()
    revenue = _revenue_two_providers()
    out_empty = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_empty_rankings(),
        tier_b_revenue_config=revenue,
        model_registry=registry,
    )
    out_no_rankings = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=pd.DataFrame(
            {
                "constituent_id": ["totally/different-model"],
                "volume_mtok_7d": [99.0],
            }
        ),
        tier_b_revenue_config=revenue,
        model_registry=registry,
    )
    pd.testing.assert_frame_equal(out_empty, out_no_rankings)


# ---------------------------------------------------------------------------
# Schema, prior validation, panel-fallback price, determinism
# ---------------------------------------------------------------------------


def test_output_schema_validates() -> None:
    """Emitted rows pass PanelObservationDF validation."""
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=_empty_panel(),
        openrouter_rankings_df=_rankings_deepseek_only(),
        tier_b_revenue_config=_revenue_two_providers(),
        model_registry=_registry_two_providers(),
    )
    PanelObservationDF.validate(out)
    # All Tier B rows by construction
    assert (out["attestation_tier"] == "B").all()
    assert (out["source"] == TIER_B_SOURCE).all()


def test_invalid_prior_raises() -> None:
    with pytest.raises(ValueError, match="prior must be"):
        derive_tier_b_volumes(
            as_of_date=_q2_2025_anchor(),
            panel_df=_empty_panel(),
            openrouter_rankings_df=_empty_rankings(),
            tier_b_revenue_config=_revenue_two_providers(),
            model_registry=_registry_two_providers(),
            prior="bogus",  # type: ignore[arg-type]
        )


def test_panel_price_overrides_registry_baseline() -> None:
    """When panel_df has a row for a constituent on as_of_date, its median
    output price is used in preference to the registry baseline."""
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="deepseek/deepseek-v3-2",
                tier=Tier.TPRR_E,
                provider="deepseek",
                canonical_name="DeepSeek V3.2",
                baseline_input_price_usd_mtok=0.25,
                baseline_output_price_usd_mtok=1.0,
            )
        ]
    )
    revenue = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="deepseek",
                period="2025-Q2",
                amount_usd=130_000_000.0,
                source="synthetic_for_mvp",
            )
        ]
    )
    rankings = pd.DataFrame(
        {
            "constituent_id": ["deepseek/deepseek-v3-2"],
            "volume_mtok_7d": [50_000.0],
        }
    )
    panel = pd.DataFrame(
        [
            {
                "observation_date": pd.Timestamp(_q2_2025_anchor()),
                "constituent_id": "deepseek/deepseek-v3-2",
                "contributor_id": "contrib_alpha",
                "tier_code": Tier.TPRR_E.value,
                "attestation_tier": AttestationTier.A.value,
                "input_price_usd_mtok": 0.5,  # overrides 0.25 baseline
                "output_price_usd_mtok": 2.0,  # overrides 1.0 baseline
                "volume_mtok_7d": 100.0,
                "source": "contributor_mock",
                "submitted_at": pd.Timestamp(_q2_2025_anchor()),
                "notes": "",
            }
        ]
    )
    out = derive_tier_b_volumes(
        as_of_date=_q2_2025_anchor(),
        panel_df=panel,
        openrouter_rankings_df=rankings,
        tier_b_revenue_config=revenue,
        model_registry=registry,
    )
    row = out.iloc[0]
    # Panel-derived prices, not registry baselines
    assert row["output_price_usd_mtok"] == pytest.approx(2.0)
    assert row["input_price_usd_mtok"] == pytest.approx(0.5)
    # Volume reflects panel price: vol_quarterly = 130M / 2.0 = 65M mtok
    assert row["volume_mtok_7d"] == pytest.approx(65_000_000.0 * 7.0 / DAYS_PER_QUARTER)


def test_determinism_two_runs_byte_identical() -> None:
    args = {
        "as_of_date": _q2_2025_anchor(),
        "panel_df": _empty_panel(),
        "openrouter_rankings_df": _rankings_deepseek_only(),
        "tier_b_revenue_config": _revenue_two_providers(),
        "model_registry": _registry_two_providers(),
    }
    a = derive_tier_b_volumes(**args)  # type: ignore[arg-type]
    b = derive_tier_b_volumes(**args)  # type: ignore[arg-type]
    pd.testing.assert_frame_equal(a, b)
