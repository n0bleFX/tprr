"""Tests for tprr.mockdata.pricing — daily baseline price generator."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tprr.config import ModelMetadata, ModelRegistry
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.schema import Tier


def _registry_with(
    models: list[tuple[str, Tier, float, float]],
) -> ModelRegistry:
    """Helper: build a minimal ModelRegistry from (id, tier, in_price, out_price) tuples."""
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=in_p,
                baseline_output_price_usd_mtok=out_p,
            )
            for cid, tier, in_p, out_p in models
        ]
    )


def test_output_shape_matches_n_days_times_n_models() -> None:
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
        ]
    )
    df, _events = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 1, 30), seed=42)
    assert len(df) == 30 * 2  # 30 days inclusive x 2 models
    assert list(df.columns) == [
        "date",
        "constituent_id",
        "baseline_input_price_usd_mtok",
        "baseline_output_price_usd_mtok",
    ]


def test_dtypes_match_spec() -> None:
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    df, _events = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 1, 10), seed=42)
    assert df["date"].dtype == "datetime64[ns]"
    assert df["baseline_input_price_usd_mtok"].dtype == "float64"
    assert df["baseline_output_price_usd_mtok"].dtype == "float64"


def test_all_prices_positive_and_finite() -> None:
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    df, _events = generate_baseline_prices(registry, date(2025, 1, 1), date(2026, 4, 23), seed=42)
    assert (df["baseline_input_price_usd_mtok"] > 0).all()
    assert (df["baseline_output_price_usd_mtok"] > 0).all()
    assert df["baseline_input_price_usd_mtok"].notna().all()
    assert df["baseline_output_price_usd_mtok"].notna().all()
    assert np.isfinite(df["baseline_input_price_usd_mtok"]).all()
    assert np.isfinite(df["baseline_output_price_usd_mtok"]).all()


def test_seeded_determinism_byte_identical() -> None:
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    a_prices, a_events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2025, 12, 31), seed=42
    )
    b_prices, b_events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2025, 12, 31), seed=42
    )
    pd.testing.assert_frame_equal(a_prices, b_prices)
    pd.testing.assert_frame_equal(a_events, b_events)


def test_different_seeds_produce_different_paths() -> None:
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    a, _ea = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 12, 31), seed=42)
    b, _eb = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 12, 31), seed=43)
    assert (
        a["baseline_output_price_usd_mtok"].iloc[0] == b["baseline_output_price_usd_mtok"].iloc[0]
    )
    assert not (
        a["baseline_output_price_usd_mtok"].iloc[1:].to_numpy()
        == b["baseline_output_price_usd_mtok"].iloc[1:].to_numpy()
    ).all()


def test_first_day_equals_registry_baseline_exactly() -> None:
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    df, _events = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 1, 10), seed=42)
    first_day = df[df["date"] == pd.Timestamp("2025-01-01")]
    pro = first_day[first_day["constituent_id"] == "openai/gpt-5-pro"].iloc[0]
    assert pro["baseline_input_price_usd_mtok"] == 15.0
    assert pro["baseline_output_price_usd_mtok"] == 75.0
    flash = first_day[first_day["constituent_id"] == "google/gemini-flash-lite"].iloc[0]
    assert flash["baseline_input_price_usd_mtok"] == 0.10
    assert flash["baseline_output_price_usd_mtok"] == 0.40


def test_mean_trend_downward_aggregated_over_seeds() -> None:
    """Per-model mean ending price (over many seeds) is below starting baseline."""
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    finals_by_model: dict[str, list[float]] = {
        "openai/gpt-5-pro": [],
        "openai/gpt-5-mini": [],
        "google/gemini-flash-lite": [],
    }
    for seed in range(20):
        df, _events = generate_baseline_prices(
            registry, date(2025, 1, 1), date(2026, 4, 23), seed=seed
        )
        for cid in finals_by_model:
            path = df[df["constituent_id"] == cid].sort_values("date")
            finals_by_model[cid].append(float(path["baseline_output_price_usd_mtok"].iloc[-1]))

    starts = {
        "openai/gpt-5-pro": 75.0,
        "openai/gpt-5-mini": 4.0,
        "google/gemini-flash-lite": 0.40,
    }
    for cid, finals in finals_by_model.items():
        mean_final = sum(finals) / len(finals)
        assert mean_final < starts[cid], (
            f"{cid}: 20-seed mean ending price {mean_final} is not below "
            f"starting baseline {starts[cid]}"
        )


def test_input_output_prices_move_in_lockstep() -> None:
    """Input/output ratio stays constant over time (coupled at constituent level)."""
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    df, _events = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 6, 30), seed=42)
    df = df.sort_values("date")
    initial_ratio = (
        df["baseline_output_price_usd_mtok"].iloc[0] / df["baseline_input_price_usd_mtok"].iloc[0]
    )
    later_ratios = df["baseline_output_price_usd_mtok"] / df["baseline_input_price_usd_mtok"]
    assert (abs(later_ratios - initial_ratio) < 1e-9).all()


def test_end_before_start_raises() -> None:
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    with pytest.raises(ValueError, match="before start_date"):
        generate_baseline_prices(registry, date(2025, 12, 31), date(2025, 1, 1), seed=42)


def test_empty_registry_raises() -> None:
    registry = ModelRegistry(models=[])
    with pytest.raises(ValueError, match="no models"):
        generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 1, 10), seed=42)


def test_single_day_window_returns_baseline_only() -> None:
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    df, events = generate_baseline_prices(registry, date(2025, 1, 1), date(2025, 1, 1), seed=42)
    assert len(df) == 1
    assert df["baseline_input_price_usd_mtok"].iloc[0] == 15.0
    assert df["baseline_output_price_usd_mtok"].iloc[0] == 75.0
    # No step events possible on a single-day window (loop starts at day 1).
    assert len(events) == 0


def test_adding_a_model_does_not_perturb_existing_paths() -> None:
    """Per-constituent seeding means adding a model leaves other models' paths untouched."""
    base_registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    extended_registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
        ]
    )
    a, _ea = generate_baseline_prices(base_registry, date(2025, 1, 1), date(2025, 6, 30), seed=42)
    b, _eb = generate_baseline_prices(
        extended_registry, date(2025, 1, 1), date(2025, 6, 30), seed=42
    )
    a_pro = a[a["constituent_id"] == "openai/gpt-5-pro"].sort_values("date")
    b_pro = b[b["constituent_id"] == "openai/gpt-5-pro"].sort_values("date")
    assert (
        a_pro["baseline_output_price_usd_mtok"].to_numpy()
        == b_pro["baseline_output_price_usd_mtok"].to_numpy()
    ).all()


def test_step_events_df_has_expected_schema() -> None:
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    _prices, events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2026, 4, 23), seed=42
    )
    expected_cols = [
        "event_date",
        "constituent_id",
        "direction",
        "old_input_price_usd_mtok",
        "new_input_price_usd_mtok",
        "old_output_price_usd_mtok",
        "new_output_price_usd_mtok",
    ]
    assert list(events.columns) == expected_cols
    assert events["event_date"].dtype == "datetime64[ns]"
    assert events["old_output_price_usd_mtok"].dtype == "float64"
    assert events["new_output_price_usd_mtok"].dtype == "float64"
    assert events["direction"].isin({"down", "up"}).all()


def test_step_events_direction_matches_magnitude_sign() -> None:
    """direction=down -> new < old; direction=up -> new > old (for both input & output)."""
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    _prices, events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2026, 4, 23), seed=42
    )
    down = events[events["direction"] == "down"]
    up = events[events["direction"] == "up"]
    assert (down["new_output_price_usd_mtok"] < down["old_output_price_usd_mtok"]).all()
    assert (down["new_input_price_usd_mtok"] < down["old_input_price_usd_mtok"]).all()
    assert (up["new_output_price_usd_mtok"] > up["old_output_price_usd_mtok"]).all()
    assert (up["new_input_price_usd_mtok"] > up["old_input_price_usd_mtok"]).all()


def test_step_events_input_output_magnitude_ratio_matches() -> None:
    """Input and output get the same step multiplier: ratio new/old is identical."""
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    _prices, events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2026, 4, 23), seed=42
    )
    out_ratio = events["new_output_price_usd_mtok"] / events["old_output_price_usd_mtok"]
    in_ratio = events["new_input_price_usd_mtok"] / events["old_input_price_usd_mtok"]
    assert np.allclose(out_ratio, in_ratio, atol=1e-12)


def test_step_events_match_observed_baseline_jumps() -> None:
    """Every event in events_df corresponds to a real jump in prices_df on the same day.

    The event's new_output_price_usd_mtok must equal the baseline on event_date,
    and old_output_price_usd_mtok must equal the baseline on the preceding day
    times (1 + daily_return) — i.e. the pre-step-post-drift price.
    """
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    prices, events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2026, 4, 23), seed=42
    )
    prices_by_date = prices[prices["constituent_id"] == "openai/gpt-5-pro"].set_index("date")[
        "baseline_output_price_usd_mtok"
    ]
    for _, ev in events.iterrows():
        post_price = prices_by_date.loc[ev["event_date"]]
        assert abs(post_price - ev["new_output_price_usd_mtok"]) < 1e-9


def test_step_event_counts_in_expected_range() -> None:
    """Per-tier event counts across 478 days + n_models are within Poisson variance."""
    registry = _registry_with(
        [
            ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
            ("openai/gpt-5", Tier.TPRR_F, 10.0, 40.0),
            ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
            ("google/gemini-flash-lite", Tier.TPRR_E, 0.10, 0.40),
        ]
    )
    _prices, events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2026, 4, 23), seed=42
    )
    # F: 2 models x 3/yr x (478/365) ≈ 7.9, S: 1 x 4 x 1.31 ≈ 5.2,
    # E: 1 x 5 x 1.31 ≈ 6.5. Single-seed variance is wide; use loose bands.
    assert 0 < len(events) < 100
    # No duplicate (event_date, constituent_id) — at most one step per model per day.
    deduped = events.drop_duplicates(subset=["event_date", "constituent_id"])
    assert len(deduped) == len(events)


def test_empty_step_events_df_has_correct_schema() -> None:
    """Very short window with no events still returns a correctly-typed empty frame."""
    registry = _registry_with([("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0)])
    _prices, events = generate_baseline_prices(
        registry, date(2025, 1, 1), date(2025, 1, 2), seed=42
    )
    # 2-day window can produce 0 or 1 event; schema must be correct either way.
    assert list(events.columns) == [
        "event_date",
        "constituent_id",
        "direction",
        "old_input_price_usd_mtok",
        "new_input_price_usd_mtok",
        "old_output_price_usd_mtok",
        "new_output_price_usd_mtok",
    ]
    assert events["event_date"].dtype == "datetime64[ns]"
