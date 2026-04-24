"""Tests for tprr.mockdata.volume — volume_mtok_7d population."""

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
from tprr.mockdata.volume import generate_volumes
from tprr.schema import PanelObservationDF, Tier


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


def _profile(
    cid: str, scale: VolumeScale, models: list[str]
) -> ContributorProfile:
    return ContributorProfile(
        contributor_id=cid,
        profile_name=cid,
        volume_scale=scale,
        price_bias_pct=0.0,
        daily_noise_sigma_pct=0.5,
        error_rate=0.0,
        covered_models=models,
    )


def _build_panel(n_days: int, contribs: list[ContributorProfile]) -> pd.DataFrame:
    registry = _registry()
    baseline, _events = generate_baseline_prices(
        registry,
        date(2025, 1, 1),
        date(2025, 1, 1) + timedelta(days=n_days - 1),
        seed=42,
    )
    panel_cfg = ContributorPanel(contributors=contribs)
    return generate_contributor_panel(baseline, panel_cfg, registry, seed=42)


def test_panel_validates_after_volume_population() -> None:
    contribs = [_profile("contrib_a", VolumeScale.HIGH, ["openai/gpt-5-pro"])]
    panel = _build_panel(n_days=30, contribs=contribs)
    out = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    PanelObservationDF.validate(out)


def test_volume_column_overwritten_not_appended() -> None:
    contribs = [_profile("contrib_a", VolumeScale.MEDIUM, ["openai/gpt-5-pro"])]
    panel = _build_panel(n_days=30, contribs=contribs)
    assert (panel["volume_mtok_7d"] == 0.0).all()
    out = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    assert (out["volume_mtok_7d"] > 0).all()
    assert list(out.columns) == list(panel.columns)


def test_all_volumes_strictly_positive() -> None:
    contribs = [
        _profile(
            "contrib_a",
            VolumeScale.HIGH,
            ["openai/gpt-5-pro", "openai/gpt-5-mini"],
        )
    ]
    panel = _build_panel(n_days=200, contribs=contribs)
    out = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    assert (out["volume_mtok_7d"] > 0).all()


def test_day_0_volume_in_reasonable_band_around_base_scale() -> None:
    """Day 0 volume = base_scale x model_offset (drawn from exp(N(0, 0.3))).

    Single-pair volume ranges roughly [0.4x, 2.5x] base_scale at 3-sigma.
    Aggregate mean across many pairs should land near base_scale x exp(sigma^2/2).
    """
    expected_mean_factor = float(np.exp(0.5 * 0.3 ** 2))  # ~1.046
    for scale, base in [
        (VolumeScale.LOW, 0.1),
        (VolumeScale.MEDIUM, 1.0),
        (VolumeScale.HIGH, 10.0),
        (VolumeScale.VERY_HIGH, 100.0),
    ]:
        # Build many synthetic contributors all at this scale, each covering one
        # of two models. Day 0 volume across all 50 pairs averages to
        # base * E[offset] within sampling tolerance.
        contribs = [
            _profile(
                f"contrib_{i}",
                scale,
                ["openai/gpt-5-pro" if i % 2 == 0 else "openai/gpt-5-mini"],
            )
            for i in range(50)
        ]
        panel = _build_panel(n_days=10, contribs=contribs)
        out = generate_volumes(
            panel, ContributorPanel(contributors=contribs), seed=42
        )
        day_0 = out[out["observation_date"] == out["observation_date"].min()]
        mean_ratio = float(day_0["volume_mtok_7d"].mean()) / base
        # Expected ~1.046; allow +/-25% to absorb sampling variance over 50 pairs.
        assert 0.78 * expected_mean_factor < mean_ratio < 1.25 * expected_mean_factor, (
            f"{scale}: day-0 mean ratio {mean_ratio:.3f} not within +/-25% "
            f"of expected {expected_mean_factor:.3f}"
        )


def test_7d_trailing_sum_is_consistent_rolling_window() -> None:
    """Reverse-engineer daily volumes from successive 7d sums; must be all positive."""
    contribs = [_profile("contrib_a", VolumeScale.MEDIUM, ["openai/gpt-5-pro"])]
    panel = _build_panel(n_days=14, contribs=contribs)
    out = (
        generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
        .sort_values("observation_date")
        .reset_index(drop=True)
    )
    sums = out["volume_mtok_7d"].to_numpy()
    daily = np.empty(14, dtype=np.float64)
    daily[0] = sums[0]
    # Days 1..5 are expanding window; daily_k = sum_k - sum_{k-1}
    for k in range(1, 6):
        daily[k] = sums[k] - sums[k - 1]
    # Day 6 fills the first complete 7-day window
    daily[6] = sums[6] - sums[5]
    # Day 7+: window slides; daily_k = sum_k - sum_{k-1} + daily_{k-7}
    for k in range(7, 14):
        daily[k] = sums[k] - sums[k - 1] + daily[k - 7]
    assert (daily > 0).all()


def test_very_high_volumes_systematically_above_low() -> None:
    contribs = [
        _profile("contrib_low", VolumeScale.LOW, ["openai/gpt-5-pro"]),
        _profile("contrib_vhigh", VolumeScale.VERY_HIGH, ["openai/gpt-5-pro"]),
    ]
    panel = _build_panel(n_days=200, contribs=contribs)
    out = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    low = out[out["contributor_id"] == "contrib_low"]["volume_mtok_7d"]
    vhigh = out[out["contributor_id"] == "contrib_vhigh"]["volume_mtok_7d"]
    assert vhigh.mean() / low.mean() > 100.0
    assert vhigh.min() > low.max()


def test_seeded_determinism() -> None:
    contribs = [
        _profile(
            "contrib_a",
            VolumeScale.HIGH,
            ["openai/gpt-5-pro", "openai/gpt-5-mini"],
        )
    ]
    panel = _build_panel(n_days=30, contribs=contribs)
    a = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    b = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    pd.testing.assert_frame_equal(a, b)


def test_different_seeds_produce_different_volumes() -> None:
    contribs = [_profile("contrib_a", VolumeScale.HIGH, ["openai/gpt-5-pro"])]
    panel = _build_panel(n_days=60, contribs=contribs)
    a = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    b = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=43)
    a_sorted = a.sort_values("observation_date").reset_index(drop=True)
    b_sorted = b.sort_values("observation_date").reset_index(drop=True)
    assert not (
        a_sorted["volume_mtok_7d"].to_numpy()
        == b_sorted["volume_mtok_7d"].to_numpy()
    ).all()


def test_contributor_cross_model_correlation_in_realistic_range() -> None:
    """Cross-model daily-volume correlations are visibly positive but not perfect.

    Replaces the prior test_contributor_models_share_same_daily_multiplier check.
    Random-walk paths produce wide single-pair correlation variance, so the
    median across many pair-combinations is the stable diagnostic. The shared
    multiplier delivers positive median coupling; per-pair offsets and
    idiosyncratic walks prevent the perfect-correlation regression.
    """
    from itertools import combinations

    from tprr.mockdata.volume import daily_volume_series

    # Use the actual 16-model panel — gives 120 pair-combinations, robust median.
    models = [
        "openai/gpt-5-pro", "openai/gpt-5", "openai/gpt-5-mini",
        "openai/gpt-5-nano", "anthropic/claude-opus-4-7",
        "anthropic/claude-opus-4-6", "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5", "google/gemini-3-pro",
        "google/gemini-2-flash", "google/gemini-flash-lite",
        "mistral/mistral-large-3", "meta/llama-4-70b-hosted",
        "deepseek/deepseek-v3-2", "alibaba/qwen-3-6-plus",
        "xiaomi/mimo-v2-pro",
    ]
    series = {
        m: daily_volume_series("contrib_atlas", m, 100.0, 478, seed=42)
        for m in models
    }
    corrs = []
    for m1, m2 in combinations(models, 2):
        c = float(np.corrcoef(series[m1], series[m2])[0, 1])
        corrs.append(c)
    arr = np.array(corrs)
    assert 0.3 <= float(np.median(arr)) <= 0.85, (
        f"median pair correlation {float(np.median(arr)):.3f} outside [0.3, 0.85]"
    )
    # The original perfect-correlation regression: max correlation must be < 0.99.
    assert float(arr.max()) < 0.99, (
        f"max pair correlation {float(arr.max()):.3f} >= 0.99 — perfect-correlation regression"
    )
    # Sanity: the shared multiplier should produce mostly-positive correlations.
    assert float((arr > 0).mean()) > 0.5, (
        f"only {100 * float((arr > 0).mean()):.1f}% of pairs positively "
        f"correlated — shared multiplier may not be working"
    )


def test_volume_ratios_drift_over_time() -> None:
    """Ratios between two atlas models on day 30 vs 180 vs 360 must materially differ.

    Per-(contributor, model) idiosyncratic random walks make model ratios drift
    over time. A drift of <1% across these checkpoints would indicate the
    idiosyncratic component isn't actually decoupling models.
    """
    contribs = [
        _profile(
            "contrib_atlas_test",
            VolumeScale.VERY_HIGH,
            ["openai/gpt-5-pro", "google/gemini-flash-lite"],
        )
    ]
    panel = _build_panel(n_days=400, contribs=contribs)
    out = generate_volumes(panel, ContributorPanel(contributors=contribs), seed=42)
    out_sorted = out.sort_values(
        ["constituent_id", "observation_date"]
    ).reset_index(drop=True)
    pro = out_sorted[out_sorted["constituent_id"] == "openai/gpt-5-pro"][
        "volume_mtok_7d"
    ].to_numpy()
    flash = out_sorted[out_sorted["constituent_id"] == "google/gemini-flash-lite"][
        "volume_mtok_7d"
    ].to_numpy()
    ratios = pro / flash
    r_30, r_180, r_360 = ratios[30], ratios[180], ratios[360]
    # All three checkpoint ratios must differ pairwise by > 1% (1% is the
    # "static ratios" failure threshold from the per-model offset alone).
    assert abs(r_30 - r_180) / r_180 > 0.01, (
        f"day-30 ratio {r_30:.4f} vs day-180 {r_180:.4f}: insufficient drift"
    )
    assert abs(r_180 - r_360) / r_360 > 0.01, (
        f"day-180 ratio {r_180:.4f} vs day-360 {r_360:.4f}: insufficient drift"
    )
    assert abs(r_30 - r_360) / r_360 > 0.01, (
        f"day-30 ratio {r_30:.4f} vs day-360 {r_360:.4f}: insufficient drift"
    )


def test_panel_with_unknown_contributor_raises() -> None:
    contribs = [_profile("contrib_a", VolumeScale.HIGH, ["openai/gpt-5-pro"])]
    panel = _build_panel(n_days=10, contribs=contribs)
    other_panel = ContributorPanel(
        contributors=[
            _profile("contrib_b", VolumeScale.LOW, ["openai/gpt-5-pro"])
        ]
    )
    with pytest.raises(ValueError, match="not in contributor_panel"):
        generate_volumes(panel, other_panel, seed=42)


def test_panel_missing_required_column_raises() -> None:
    df = pd.DataFrame({"foo": [1, 2, 3]})
    contribs = [_profile("contrib_a", VolumeScale.HIGH, ["openai/gpt-5-pro"])]
    with pytest.raises(ValueError, match="missing required columns"):
        generate_volumes(df, ContributorPanel(contributors=contribs), seed=42)


def test_growing_contributor_ends_higher_than_starting() -> None:
    """Aggregate over many seeds: grow-trend final volume / initial > contract-trend."""
    from tprr.mockdata.pricing import _stable_int

    grow_id = None
    contract_id = None
    for n in range(200):
        cand = f"contrib_test_{n}"
        h = _stable_int(cand) % 3
        if h == 0 and grow_id is None:
            grow_id = cand
        if h == 2 and contract_id is None:
            contract_id = cand
        if grow_id and contract_id:
            break
    assert grow_id is not None and contract_id is not None

    growers_initial: list[float] = []
    growers_final: list[float] = []
    contractors_initial: list[float] = []
    contractors_final: list[float] = []
    for seed in range(15):
        for cid in [grow_id, contract_id]:
            contribs = [_profile(cid, VolumeScale.MEDIUM, ["openai/gpt-5-pro"])]
            panel = _build_panel(n_days=478, contribs=contribs)
            out = (
                generate_volumes(
                    panel, ContributorPanel(contributors=contribs), seed=seed
                )
                .sort_values("observation_date")
                .reset_index(drop=True)
            )
            initial = float(out["volume_mtok_7d"].iloc[0])
            final = float(out["volume_mtok_7d"].iloc[-1])
            if cid == grow_id:
                growers_initial.append(initial)
                growers_final.append(final)
            else:
                contractors_initial.append(initial)
                contractors_final.append(final)
    grow_ratio = sum(growers_final) / sum(growers_initial)
    contract_ratio = sum(contractors_final) / sum(contractors_initial)
    assert grow_ratio > contract_ratio, (
        f"grow ratio {grow_ratio:.2f} should exceed contract ratio {contract_ratio:.2f}"
    )
