"""Tests for tprr.mockdata.change_events."""

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
from tprr.mockdata.change_events import (
    _CONTRIB_SPEC_MAG_HI,
    _CONTRIB_SPEC_MAG_LO,
    _TWAP_SLOTS,
    apply_twap_to_panel,
    generate_change_events,
)
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.mockdata.volume import generate_volumes
from tprr.schema import ChangeEventDF, PanelObservationDF, Tier


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


def _panel_config() -> ContributorPanel:
    """Three contributors with coverage overlap, for collision testing."""
    return ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_alpha",
                profile_name="Alpha",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=[
                    "openai/gpt-5-pro",
                    "openai/gpt-5-mini",
                    "google/gemini-flash-lite",
                ],
            ),
            ContributorProfile(
                contributor_id="contrib_beta",
                profile_name="Beta",
                volume_scale=VolumeScale.HIGH,
                price_bias_pct=1.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=[
                    "openai/gpt-5-pro",
                    "openai/gpt-5-mini",
                ],
            ),
            ContributorProfile(
                contributor_id="contrib_gamma",
                profile_name="Gamma",
                volume_scale=VolumeScale.LOW,
                price_bias_pct=-1.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=[
                    "openai/gpt-5-mini",
                    "google/gemini-flash-lite",
                ],
            ),
        ]
    )


def _build_full_pipeline(
    n_days: int = 365, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry, ContributorPanel]:
    """Build panel + step_events for testing change_events generation."""
    registry = _registry()
    contributors = _panel_config()
    baseline, step_events = generate_baseline_prices(
        registry,
        date(2025, 1, 1),
        date(2025, 1, 1) + timedelta(days=n_days - 1),
        seed=seed,
    )
    panel = generate_contributor_panel(baseline, contributors, registry, seed=seed)
    panel = generate_volumes(panel, contributors, seed=seed)
    return panel, step_events, registry, contributors


def test_events_df_validates_against_change_event_schema() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    ChangeEventDF.validate(events)


def test_all_slot_idx_in_range() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    assert (events["change_slot_idx"] >= 0).all()
    assert (events["change_slot_idx"] <= _TWAP_SLOTS - 1).all()


def test_no_duplicate_event_keys() -> None:
    """At most one ChangeEvent per (contributor, constituent, date)."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    key_cols = ["event_date", "contributor_id", "constituent_id"]
    deduped = events.drop_duplicates(subset=key_cols)
    assert len(deduped) == len(events)


def test_propagated_events_have_baseline_move_reason() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    # Propagated events are those whose (event_date, constituent_id) matches
    # a step event row.
    step_keys = {
        (pd.Timestamp(r.event_date), r.constituent_id)
        for r in step_events.itertuples(index=False)
    }
    prop = events[
        events.apply(
            lambda r: (pd.Timestamp(r["event_date"]), r["constituent_id"])
            in step_keys,
            axis=1,
        )
    ]
    assert len(prop) > 0
    assert (prop["reason"] == "baseline_move").all()


def test_contributor_specific_events_have_contract_adjustment_reason() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    step_keys = {
        (pd.Timestamp(r.event_date), r.constituent_id)
        for r in step_events.itertuples(index=False)
    }
    spec = events[
        events.apply(
            lambda r: (pd.Timestamp(r["event_date"]), r["constituent_id"])
            not in step_keys,
            axis=1,
        )
    ]
    assert len(spec) > 0
    assert (spec["reason"] == "contract_adjustment").all()


def test_events_reference_valid_panel_rows() -> None:
    """Every (event_date, contributor, constituent) must exist in the panel."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    panel_keys = set(
        zip(
            panel["observation_date"],
            panel["contributor_id"],
            panel["constituent_id"],
            strict=True,
        )
    )
    event_keys = set(
        zip(
            events["event_date"],
            events["contributor_id"],
            events["constituent_id"],
            strict=True,
        )
    )
    orphans = event_keys - panel_keys
    assert len(orphans) == 0, f"{len(orphans)} events have no matching panel row"


def test_panel_prices_shift_meaningfully_on_event_days() -> None:
    """apply_twap_to_panel must change prices vs. pre-TWAP on event days."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    updated = apply_twap_to_panel(panel, events)
    # Merge on event-keys and compare
    merged = events.merge(
        panel,
        left_on=["event_date", "contributor_id", "constituent_id"],
        right_on=["observation_date", "contributor_id", "constituent_id"],
        how="left",
        suffixes=("", "_panel"),
    ).merge(
        updated,
        left_on=["event_date", "contributor_id", "constituent_id"],
        right_on=["observation_date", "contributor_id", "constituent_id"],
        how="left",
        suffixes=("_orig", "_twap"),
    )
    # For each event, TWAP panel output should differ from the original panel
    # output unless the event has slot_idx == 0 AND old == new (trivial no-op).
    nontrivial = merged[
        ~(
            (merged["change_slot_idx"] == 0)
            & (
                merged["old_output_price_usd_mtok"]
                == merged["new_output_price_usd_mtok"]
            )
        )
    ]
    diffs = (
        nontrivial["output_price_usd_mtok_twap"]
        - nontrivial["output_price_usd_mtok_orig"]
    ).abs()
    assert (diffs > 1e-9).any(), "TWAP update did not change any panel prices"


def test_apply_twap_preserves_non_event_days_exactly() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    updated = apply_twap_to_panel(panel, events)
    # Build the set of event keys
    event_keys = set(
        zip(
            events["event_date"],
            events["contributor_id"],
            events["constituent_id"],
            strict=True,
        )
    )
    key_series = list(
        zip(
            panel["observation_date"],
            panel["contributor_id"],
            panel["constituent_id"],
            strict=True,
        )
    )
    non_event_mask = np.array([k not in event_keys for k in key_series])
    np.testing.assert_array_equal(
        panel.loc[non_event_mask, "output_price_usd_mtok"].to_numpy(),
        updated.loc[non_event_mask, "output_price_usd_mtok"].to_numpy(),
    )
    np.testing.assert_array_equal(
        panel.loc[non_event_mask, "input_price_usd_mtok"].to_numpy(),
        updated.loc[non_event_mask, "input_price_usd_mtok"].to_numpy(),
    )


def test_twap_formula_exact_on_event_days() -> None:
    """Updated panel price on event day equals (S*old + (32-S)*new) / 32."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    updated = apply_twap_to_panel(panel, events)
    n = _TWAP_SLOTS
    merged = events.merge(
        updated,
        left_on=["event_date", "contributor_id", "constituent_id"],
        right_on=["observation_date", "contributor_id", "constituent_id"],
        how="left",
    )
    expected_out = (
        merged["change_slot_idx"] * merged["old_output_price_usd_mtok"]
        + (n - merged["change_slot_idx"]) * merged["new_output_price_usd_mtok"]
    ) / n
    expected_in = (
        merged["change_slot_idx"] * merged["old_input_price_usd_mtok"]
        + (n - merged["change_slot_idx"]) * merged["new_input_price_usd_mtok"]
    ) / n
    np.testing.assert_allclose(
        merged["output_price_usd_mtok"].to_numpy(),
        expected_out.to_numpy(),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        merged["input_price_usd_mtok"].to_numpy(),
        expected_in.to_numpy(),
        atol=1e-12,
    )


def test_apply_twap_preserves_panel_observation_df_schema() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    updated = apply_twap_to_panel(panel, events)
    PanelObservationDF.validate(updated)
    assert list(updated.columns) == list(panel.columns)


def test_seeded_determinism() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    a = generate_change_events(panel, step_events, registry, contributors, seed=42)
    b = generate_change_events(panel, step_events, registry, contributors, seed=42)
    pd.testing.assert_frame_equal(
        a.sort_values(["event_date", "contributor_id", "constituent_id"]).reset_index(
            drop=True
        ),
        b.sort_values(["event_date", "contributor_id", "constituent_id"]).reset_index(
            drop=True
        ),
    )


def test_different_seeds_diverge() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    a = generate_change_events(panel, step_events, registry, contributors, seed=42)
    b = generate_change_events(panel, step_events, registry, contributors, seed=43)
    # At minimum the number of contributor-specific events should differ;
    # propagated events share step dates but slot_idx will diverge.
    assert not (
        a["change_slot_idx"].sum() == b["change_slot_idx"].sum()
        and len(a) == len(b)
    )


def test_empty_step_events_with_zero_rate_yields_empty_events() -> None:
    """No propagated events + no contributor-specific events => empty frame."""
    registry = _registry()
    contributors = ContributorPanel(contributors=[])  # no contributors
    panel, step_events, _, _ = _build_full_pipeline()
    # Slice to no contributors
    empty_panel = panel.iloc[:0]
    empty_step_events = step_events.iloc[:0]
    events = generate_change_events(
        empty_panel, empty_step_events, registry, contributors, seed=42
    )
    assert len(events) == 0
    # Schema is still well-formed
    expected = [
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
    assert list(events.columns) == expected


def test_slot_distribution_centred_near_16() -> None:
    """Mean slot across all events sits within [10, 22] — roughly centred at 16."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    assert 10 <= events["change_slot_idx"].mean() <= 22


def test_event_dates_within_panel_range() -> None:
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    assert events["event_date"].min() >= panel["observation_date"].min()
    assert events["event_date"].max() <= panel["observation_date"].max()


def test_propagated_event_price_ratios_match_step_event_magnitude() -> None:
    """old_output / new_output in a propagated event equals step's ratio."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    prop = events[events["reason"] == "baseline_move"]
    for step in step_events.itertuples(index=False):
        matching = prop[
            (prop["event_date"] == pd.Timestamp(step.event_date))
            & (prop["constituent_id"] == step.constituent_id)
        ]
        if len(matching) == 0:
            continue
        expected_ratio = (
            step.old_output_price_usd_mtok / step.new_output_price_usd_mtok
        )
        observed_ratios = (
            matching["old_output_price_usd_mtok"]
            / matching["new_output_price_usd_mtok"]
        )
        np.testing.assert_allclose(
            observed_ratios.to_numpy(),
            np.full(len(matching), expected_ratio),
            atol=1e-10,
        )


def test_contributor_specific_magnitudes_in_configured_band() -> None:
    """|new/old - 1| falls within [_CONTRIB_SPEC_MAG_LO, _CONTRIB_SPEC_MAG_HI]."""
    panel, step_events, registry, contributors = _build_full_pipeline()
    events = generate_change_events(
        panel, step_events, registry, contributors, seed=42
    )
    spec = events[events["reason"] == "contract_adjustment"]
    ratios = spec["new_output_price_usd_mtok"] / spec["old_output_price_usd_mtok"]
    magnitudes = (ratios - 1.0).abs()
    assert (magnitudes >= _CONTRIB_SPEC_MAG_LO - 1e-9).all()
    assert (magnitudes <= _CONTRIB_SPEC_MAG_HI + 1e-9).all()


def test_panel_missing_required_column_raises() -> None:
    bad_panel = pd.DataFrame({"foo": [1, 2, 3]})
    registry = _registry()
    contributors = _panel_config()
    step_events = pd.DataFrame(
        {
            "event_date": pd.Series([], dtype="datetime64[ns]"),
            "constituent_id": pd.Series([], dtype="object"),
            "direction": pd.Series([], dtype="object"),
            "old_input_price_usd_mtok": pd.Series([], dtype="float64"),
            "new_input_price_usd_mtok": pd.Series([], dtype="float64"),
            "old_output_price_usd_mtok": pd.Series([], dtype="float64"),
            "new_output_price_usd_mtok": pd.Series([], dtype="float64"),
        }
    )
    with pytest.raises(ValueError, match="missing required columns"):
        generate_change_events(
            bad_panel, step_events, registry, contributors, seed=42
        )
