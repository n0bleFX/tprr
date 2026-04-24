"""Tests for tprr.mockdata.contributors — per-contributor daily observations."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tprr.config import (
    ContributorPanel,
    ContributorProfile,
    ModelMetadata,
    ModelRegistry,
    VolumeScale,
)
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.schema import AttestationTier, PanelObservationDF, Tier


def _registry() -> ModelRegistry:
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
                constituent_id="openai/gpt-5-mini",
                tier=Tier.TPRR_S,
                provider="openai",
                canonical_name="GPT-5 Mini",
                baseline_input_price_usd_mtok=0.5,
                baseline_output_price_usd_mtok=4.0,
            ),
            ModelMetadata(
                constituent_id="google/gemini-flash-lite",
                tier=Tier.TPRR_E,
                provider="google",
                canonical_name="Gemini Flash Lite",
                baseline_input_price_usd_mtok=0.10,
                baseline_output_price_usd_mtok=0.40,
            ),
        ]
    )


def _two_contributor_panel() -> ContributorPanel:
    return ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_high_bias",
                profile_name="High Bias",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=2.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro", "openai/gpt-5-mini"],
            ),
            ContributorProfile(
                contributor_id="contrib_low_bias",
                profile_name="Low Bias",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=-2.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro", "google/gemini-flash-lite"],
            ),
        ]
    )


def _baseline(registry: ModelRegistry, n_days: int = 100) -> pd.DataFrame:
    return generate_baseline_prices(
        registry,
        date(2025, 1, 1),
        date(2025, 1, 1) + timedelta(days=n_days - 1),
        seed=42,
    )


def test_panel_validates_against_panel_observation_df() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=30)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    PanelObservationDF.validate(panel)


def test_contributors_only_have_rows_for_covered_models() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=30)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    high = panel[panel["contributor_id"] == "contrib_high_bias"]
    low = panel[panel["contributor_id"] == "contrib_low_bias"]
    assert set(high["constituent_id"].unique()) == {
        "openai/gpt-5-pro",
        "openai/gpt-5-mini",
    }
    assert set(low["constituent_id"].unique()) == {
        "openai/gpt-5-pro",
        "google/gemini-flash-lite",
    }


def test_bias_is_multiplicative_not_additive() -> None:
    """+2.0% bias -> 1.02x baseline, not baseline + 0.02 USD.

    A small high-priced model magnifies the difference between the two
    interpretations: at baseline ~75 USD/Mtok, multiplicative gives ~76.5 (delta
    1.5), additive would give 75.02 (delta 0.02). The test checks the
    multiplicative interpretation explicitly.
    """
    registry = _registry()
    baseline = _baseline(registry, n_days=200)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    high_pro = panel[
        (panel["contributor_id"] == "contrib_high_bias")
        & (panel["constituent_id"] == "openai/gpt-5-pro")
    ].sort_values("observation_date")
    base_pro = baseline[
        baseline["constituent_id"] == "openai/gpt-5-pro"
    ].sort_values("date")
    ratios = (
        high_pro["output_price_usd_mtok"].to_numpy()
        / base_pro["baseline_output_price_usd_mtok"].to_numpy()
    )
    mean_ratio = float(np.mean(ratios))
    assert abs(mean_ratio - 1.02) < 0.005, (
        f"mean ratio {mean_ratio} not within 0.5pp of 1.02 (multiplicative bias)"
    )


def test_high_bias_mean_above_low_bias_mean_on_shared_model() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=200)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    high_pro = panel[
        (panel["contributor_id"] == "contrib_high_bias")
        & (panel["constituent_id"] == "openai/gpt-5-pro")
    ]
    low_pro = panel[
        (panel["contributor_id"] == "contrib_low_bias")
        & (panel["constituent_id"] == "openai/gpt-5-pro")
    ]
    assert (
        high_pro["output_price_usd_mtok"].mean()
        > low_pro["output_price_usd_mtok"].mean()
    )


def test_per_contributor_noise_std_matches_configured_sigma() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=400)
    quiet_panel = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_quiet",
                profile_name="Q",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro"],
            ),
        ]
    )
    panel = generate_contributor_panel(
        baseline, quiet_panel, registry, seed=42
    )
    panel_pro = panel.sort_values("observation_date")
    base_pro = baseline[
        baseline["constituent_id"] == "openai/gpt-5-pro"
    ].sort_values("date")
    ratios = (
        panel_pro["output_price_usd_mtok"].to_numpy()
        / base_pro["baseline_output_price_usd_mtok"].to_numpy()
    )
    noise_std = float(np.std(ratios - 1.0, ddof=1))
    expected = 0.005  # 0.5 % expressed as fraction
    assert 0.7 * expected < noise_std < 1.3 * expected, (
        f"noise std {noise_std:.5f} not within +/-30% of expected {expected:.5f}"
    )


def test_seeded_determinism() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=60)
    a = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    b = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    pd.testing.assert_frame_equal(a, b)


def test_different_seeds_produce_different_observations() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=60)
    a = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    b = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=43
    )
    assert len(a) == len(b)
    assert not (
        a["output_price_usd_mtok"].to_numpy()
        == b["output_price_usd_mtok"].to_numpy()
    ).all()


def test_attestation_tier_and_source_are_constants() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=30)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    assert (panel["attestation_tier"] == AttestationTier.A.value).all()
    assert (panel["source"] == "contributor_mock").all()


def test_volume_placeholder_is_zero() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=30)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    assert (panel["volume_mtok_7d"] == 0.0).all()


def test_input_output_share_noise_per_day() -> None:
    """Input and output ratios over baseline should match exactly per row."""
    registry = _registry()
    baseline = _baseline(registry, n_days=60)
    panel = generate_contributor_panel(
        baseline, _two_contributor_panel(), registry, seed=42
    )
    pro = panel[
        (panel["contributor_id"] == "contrib_high_bias")
        & (panel["constituent_id"] == "openai/gpt-5-pro")
    ].sort_values("observation_date")
    base = baseline[baseline["constituent_id"] == "openai/gpt-5-pro"].sort_values(
        "date"
    )
    in_ratio = (
        pro["input_price_usd_mtok"].to_numpy()
        / base["baseline_input_price_usd_mtok"].to_numpy()
    )
    out_ratio = (
        pro["output_price_usd_mtok"].to_numpy()
        / base["baseline_output_price_usd_mtok"].to_numpy()
    )
    assert np.allclose(in_ratio, out_ratio, atol=1e-12)


def test_error_rate_amplifies_noise_sigma_by_ten() -> None:
    """error_rate=1.0 should produce ~10x the noise std of error_rate=0.0."""
    registry = _registry()
    baseline = _baseline(registry, n_days=400)
    quiet = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_quiet",
                profile_name="Q",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro"],
            )
        ]
    )
    erroring = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_erroring",
                profile_name="E",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=1.0,
                covered_models=["openai/gpt-5-pro"],
            )
        ]
    )
    a = generate_contributor_panel(baseline, quiet, registry, seed=42)
    b = generate_contributor_panel(baseline, erroring, registry, seed=42)
    base = baseline[baseline["constituent_id"] == "openai/gpt-5-pro"].sort_values(
        "date"
    )
    a_std = float(
        np.std(
            a.sort_values("observation_date")["output_price_usd_mtok"].to_numpy()
            / base["baseline_output_price_usd_mtok"].to_numpy()
            - 1.0
        )
    )
    b_std = float(
        np.std(
            b.sort_values("observation_date")["output_price_usd_mtok"].to_numpy()
            / base["baseline_output_price_usd_mtok"].to_numpy()
            - 1.0
        )
    )
    ratio = b_std / a_std
    assert 7.0 < ratio < 13.0, (
        f"erroring/quiet std ratio {ratio:.2f} not in expected ~10x band"
    )


def test_unknown_covered_model_raises() -> None:
    registry = _registry()
    baseline = _baseline(registry, n_days=30)
    bad_panel = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_bad",
                profile_name="Bad",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/nonexistent"],
            )
        ]
    )
    with pytest.raises(ValueError, match="not in model_registry"):
        generate_contributor_panel(baseline, bad_panel, registry, seed=42)


def test_adding_a_contributor_does_not_perturb_others() -> None:
    """Per-(contributor, model) seeding -> adding a contributor leaves others alone."""
    registry = _registry()
    baseline = _baseline(registry, n_days=60)
    base_panel = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_alpha",
                profile_name="Alpha",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro"],
            )
        ]
    )
    extended_panel = ContributorPanel(
        contributors=[
            *base_panel.contributors,
            ContributorProfile(
                contributor_id="contrib_beta",
                profile_name="Beta",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=1.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro"],
            ),
        ]
    )
    a = generate_contributor_panel(baseline, base_panel, registry, seed=42)
    b = generate_contributor_panel(baseline, extended_panel, registry, seed=42)
    a_alpha = a[a["contributor_id"] == "contrib_alpha"].sort_values(
        "observation_date"
    )
    b_alpha = b[b["contributor_id"] == "contrib_alpha"].sort_values(
        "observation_date"
    )
    assert (
        a_alpha["output_price_usd_mtok"].to_numpy()
        == b_alpha["output_price_usd_mtok"].to_numpy()
    ).all()
