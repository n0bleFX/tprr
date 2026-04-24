"""Tests for tprr.mockdata.outliers — Phase 3.1 primitive operations."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
from tprr.mockdata.change_events import apply_twap_to_panel, generate_change_events
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.outliers import (
    ScenarioManifest,
    freeze_pair_in_window,
    inject_change_events,
    mutate_registry,
    override_panel_prices,
    regenerate_constituent_slice,
    remove_panel_rows,
    suppress_events,
)
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
                constituent_id="anthropic/claude-haiku-4-5",
                tier=Tier.TPRR_S,
                provider="anthropic",
                canonical_name="Claude Haiku 4.5",
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=5.0,
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
                    "anthropic/claude-haiku-4-5",
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
                    "anthropic/claude-haiku-4-5",
                ],
            ),
        ]
    )


def _build_pipeline(
    n_days: int = 180, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry, ContributorPanel]:
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
    events = generate_change_events(panel, step_events, registry, contributors, seed=seed)
    panel = apply_twap_to_panel(panel, events)
    return panel, events, registry, contributors


# ---------------------------------------------------------------------------
# Primitive 1: inject_change_events
# ---------------------------------------------------------------------------


def test_inject_change_events_appends_rows() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=30)
    new_events = [
        {
            "event_date": pd.Timestamp("2025-01-15"),
            "contributor_id": "contrib_alpha",
            "constituent_id": "openai/gpt-5-mini",
            "change_slot_idx": 16,
            "old_input_price_usd_mtok": 0.5,
            "new_input_price_usd_mtok": 5.0,
            "old_output_price_usd_mtok": 4.0,
            "new_output_price_usd_mtok": 40.0,
        }
    ]
    out, rec = inject_change_events(events, new_events)
    assert len(out) == len(events) + 1
    assert rec["op"] == "inject_change_events"
    assert rec["n_injected"] == 1
    last = out.iloc[-1]
    assert last["reason"] == "outlier_injection"
    assert last["change_slot_idx"] == 16


def test_inject_change_events_empty_list_returns_copy() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=30)
    out, rec = inject_change_events(events, [])
    assert len(out) == len(events)
    assert rec["n_injected"] == 0


def test_inject_change_events_output_validates_as_changeeventdf() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=30)
    new_events = [
        {
            "event_date": pd.Timestamp("2025-01-15"),
            "contributor_id": "contrib_alpha",
            "constituent_id": "openai/gpt-5-mini",
            "change_slot_idx": 10,
            "old_input_price_usd_mtok": 0.5,
            "new_input_price_usd_mtok": 5.0,
            "old_output_price_usd_mtok": 4.0,
            "new_output_price_usd_mtok": 40.0,
            "reason": "outlier_injection",
        }
    ]
    out, _ = inject_change_events(events, new_events)
    ChangeEventDF.validate(out)


# ---------------------------------------------------------------------------
# Primitive 2: suppress_events
# ---------------------------------------------------------------------------


def test_suppress_events_by_contributor() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=180)
    n_alpha = int((events["contributor_id"] == "contrib_alpha").sum())
    out, rec = suppress_events(events, contributor_id="contrib_alpha")
    assert len(out) == len(events) - n_alpha
    assert rec["n_suppressed"] == n_alpha
    assert "contrib_alpha" not in out["contributor_id"].unique()


def test_suppress_events_by_constituent_and_date_range() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=180)
    out, rec = suppress_events(
        events,
        constituent_id="openai/gpt-5-mini",
        date_range=(date(2025, 2, 1), date(2025, 3, 1)),
    )
    mask = (
        (events["constituent_id"] == "openai/gpt-5-mini")
        & (events["event_date"] >= pd.Timestamp("2025-02-01"))
        & (events["event_date"] <= pd.Timestamp("2025-03-01"))
    )
    expected_suppressed = int(mask.sum())
    assert rec["n_suppressed"] == expected_suppressed
    assert len(out) == len(events) - expected_suppressed


def test_suppress_events_requires_filter() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=30)
    with pytest.raises(ValueError, match="at least one filter"):
        suppress_events(events)


def test_suppress_events_no_match_leaves_df_unchanged() -> None:
    _panel, events, _, _ = _build_pipeline(n_days=30)
    out, rec = suppress_events(events, contributor_id="contrib_nonexistent")
    assert len(out) == len(events)
    assert rec["n_suppressed"] == 0


# ---------------------------------------------------------------------------
# Primitive 3: remove_panel_rows
# ---------------------------------------------------------------------------


def test_remove_panel_rows_by_contributor_and_date_range() -> None:
    panel, _, _, _ = _build_pipeline(n_days=60)
    out, rec = remove_panel_rows(
        panel,
        contributor_id="contrib_alpha",
        date_range=(date(2025, 1, 15), date(2025, 1, 24)),
    )
    mask = (
        (panel["contributor_id"] == "contrib_alpha")
        & (panel["observation_date"] >= pd.Timestamp("2025-01-15"))
        & (panel["observation_date"] <= pd.Timestamp("2025-01-24"))
    )
    expected = int(mask.sum())
    assert rec["n_removed"] == expected
    assert len(out) == len(panel) - expected


def test_remove_panel_rows_requires_filter() -> None:
    panel, _, _, _ = _build_pipeline(n_days=30)
    with pytest.raises(ValueError, match="at least one filter"):
        remove_panel_rows(panel)


# ---------------------------------------------------------------------------
# Primitive 4: override_panel_prices
# ---------------------------------------------------------------------------


def test_override_panel_prices_replaces_only_matching_rows() -> None:
    panel, _, _, _ = _build_pipeline(n_days=30)

    def fixed_price(_row: dict[str, Any]) -> tuple[float, float]:
        return 99.99, 888.88

    out, rec = override_panel_prices(
        panel,
        fixed_price,
        contributor_id="contrib_alpha",
        constituent_id="openai/gpt-5-mini",
    )
    matched = (
        (out["contributor_id"] == "contrib_alpha")
        & (out["constituent_id"] == "openai/gpt-5-mini")
    )
    assert (out.loc[matched, "input_price_usd_mtok"] == 99.99).all()
    assert (out.loc[matched, "output_price_usd_mtok"] == 888.88).all()
    # Non-matching rows untouched
    untouched = panel.loc[~matched, "output_price_usd_mtok"].to_numpy()
    assert np.array_equal(
        out.loc[~matched, "output_price_usd_mtok"].to_numpy(), untouched
    )
    assert rec["n_modified"] == int(matched.sum())


def test_override_panel_prices_price_fn_receives_current_row() -> None:
    panel, _, _, _ = _build_pipeline(n_days=30)
    captured: list[dict[str, Any]] = []

    def record_and_double(row: dict[str, Any]) -> tuple[float, float]:
        captured.append(row)
        return float(row["input_price_usd_mtok"]) * 2, float(row["output_price_usd_mtok"]) * 2

    out, _ = override_panel_prices(
        panel,
        record_and_double,
        contributor_id="contrib_alpha",
        constituent_id="openai/gpt-5-mini",
        date_range=(date(2025, 1, 1), date(2025, 1, 3)),
    )
    assert len(captured) == 3  # three days, one (contrib, model) pair
    assert "observation_date" in captured[0]
    assert "output_price_usd_mtok" in captured[0]
    # Doubling verified
    matched = (
        (out["contributor_id"] == "contrib_alpha")
        & (out["constituent_id"] == "openai/gpt-5-mini")
        & (out["observation_date"] >= pd.Timestamp("2025-01-01"))
        & (out["observation_date"] <= pd.Timestamp("2025-01-03"))
    )
    original = panel.loc[matched, "output_price_usd_mtok"].to_numpy()
    assert np.allclose(
        out.loc[matched, "output_price_usd_mtok"].to_numpy(), original * 2
    )


# ---------------------------------------------------------------------------
# Primitive 5: mutate_registry
# ---------------------------------------------------------------------------


def test_mutate_registry_tier_change() -> None:
    registry = _registry()
    out, rec = mutate_registry(
        registry,
        {
            "type": "tier_change",
            "constituent_id": "openai/gpt-5-mini",
            "new_tier": Tier.TPRR_F,
            "effective_date": date(2025, 6, 1),
        },
    )
    target = next(m for m in out.models if m.constituent_id == "openai/gpt-5-mini")
    assert target.tier == Tier.TPRR_F
    # Others unchanged
    other = next(m for m in out.models if m.constituent_id == "openai/gpt-5-pro")
    assert other.tier == Tier.TPRR_F  # was already F
    assert rec["op"] == "mutate_registry"
    assert rec["mutation"]["type"] == "tier_change"


def test_mutate_registry_add_model() -> None:
    registry = _registry()
    new = ModelMetadata(
        constituent_id="anthropic/claude-haiku-5",
        tier=Tier.TPRR_S,
        provider="anthropic",
        canonical_name="Claude Haiku 5",
        baseline_input_price_usd_mtok=1.0,
        baseline_output_price_usd_mtok=4.0,
    )
    out, rec = mutate_registry(registry, {"type": "add_model", "model": new})
    assert len(out.models) == len(registry.models) + 1
    assert any(m.constituent_id == "anthropic/claude-haiku-5" for m in out.models)
    assert rec["mutation"]["model"] == "anthropic/claude-haiku-5"


def test_mutate_registry_add_duplicate_raises() -> None:
    registry = _registry()
    dup = ModelMetadata(
        constituent_id="openai/gpt-5-mini",  # already in registry
        tier=Tier.TPRR_S,
        provider="openai",
        canonical_name="Duplicate",
        baseline_input_price_usd_mtok=0.5,
        baseline_output_price_usd_mtok=4.0,
    )
    with pytest.raises(ValueError, match="already in registry"):
        mutate_registry(registry, {"type": "add_model", "model": dup})


def test_mutate_registry_unknown_type_raises() -> None:
    registry = _registry()
    with pytest.raises(ValueError, match="unknown registry mutation type"):
        mutate_registry(registry, {"type": "nonsense"})


def test_mutate_registry_tier_change_unknown_constituent_raises() -> None:
    registry = _registry()
    with pytest.raises(ValueError, match="not in registry"):
        mutate_registry(
            registry,
            {
                "type": "tier_change",
                "constituent_id": "fake/model",
                "new_tier": Tier.TPRR_F,
            },
        )


# ---------------------------------------------------------------------------
# Primitive 6: regenerate_constituent_slice
# ---------------------------------------------------------------------------


def test_regenerate_existing_constituent_preserves_pre_and_post_window() -> None:
    """Scenario 10 case: pre-window and post-window rows for target constituent
    are byte-identical to pre-regeneration."""
    panel, events, registry, contributors = _build_pipeline(n_days=180)
    target_model = next(
        m for m in registry.models if m.constituent_id == "openai/gpt-5-mini"
    )
    window_start = date(2025, 3, 1)
    window_end = date(2025, 4, 30)

    out_panel, _out_events, rec = regenerate_constituent_slice(
        panel,
        events,
        target_model,
        contributors,
        (window_start, window_end),
        seed=42,
        sigma_daily=0.07,
        mu_daily=0.0,
        step_rate_per_year=0.0,
    )

    # Pre-window target rows: byte-identical
    pre_mask_orig = (
        (panel["constituent_id"] == target_model.constituent_id)
        & (panel["observation_date"] < pd.Timestamp(window_start))
    )
    pre_mask_out = (
        (out_panel["constituent_id"] == target_model.constituent_id)
        & (out_panel["observation_date"] < pd.Timestamp(window_start))
    )
    orig_pre = panel.loc[pre_mask_orig].sort_values(
        ["contributor_id", "observation_date"]
    ).reset_index(drop=True)
    out_pre = out_panel.loc[pre_mask_out].sort_values(
        ["contributor_id", "observation_date"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(orig_pre, out_pre)

    # Post-window target rows: byte-identical
    post_mask_orig = (
        (panel["constituent_id"] == target_model.constituent_id)
        & (panel["observation_date"] > pd.Timestamp(window_end))
    )
    post_mask_out = (
        (out_panel["constituent_id"] == target_model.constituent_id)
        & (out_panel["observation_date"] > pd.Timestamp(window_end))
    )
    orig_post = panel.loc[post_mask_orig].sort_values(
        ["contributor_id", "observation_date"]
    ).reset_index(drop=True)
    out_post = out_panel.loc[post_mask_out].sort_values(
        ["contributor_id", "observation_date"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(orig_post, out_post)

    assert rec["is_new_constituent"] is False
    assert rec["n_panel_rows_regenerated"] > 0


def test_regenerate_existing_constituent_in_window_prices_change() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180)
    target_model = next(
        m for m in registry.models if m.constituent_id == "openai/gpt-5-mini"
    )
    window_start = date(2025, 3, 1)
    window_end = date(2025, 4, 30)

    out_panel, _, _ = regenerate_constituent_slice(
        panel, events, target_model, contributors,
        (window_start, window_end), seed=42,
        sigma_daily=0.07, mu_daily=0.0, step_rate_per_year=0.0,
    )

    in_window_orig = panel[
        (panel["constituent_id"] == target_model.constituent_id)
        & (panel["observation_date"] >= pd.Timestamp(window_start))
        & (panel["observation_date"] <= pd.Timestamp(window_end))
    ].sort_values(["contributor_id", "observation_date"]).reset_index(drop=True)
    in_window_new = out_panel[
        (out_panel["constituent_id"] == target_model.constituent_id)
        & (out_panel["observation_date"] >= pd.Timestamp(window_start))
        & (out_panel["observation_date"] <= pd.Timestamp(window_end))
    ].sort_values(["contributor_id", "observation_date"]).reset_index(drop=True)

    # Prices differ (new sigma produces different walks)
    assert not np.allclose(
        in_window_orig["output_price_usd_mtok"].to_numpy(),
        in_window_new["output_price_usd_mtok"].to_numpy(),
    )
    # Volumes preserved (regen doesn't touch them)
    np.testing.assert_array_equal(
        in_window_orig["volume_mtok_7d"].to_numpy(),
        in_window_new["volume_mtok_7d"].to_numpy(),
    )


def test_regenerate_existing_constituent_suppresses_in_window_events() -> None:
    """Events on target constituent in window are removed; events outside untouched."""
    panel, events, registry, contributors = _build_pipeline(n_days=180)
    target_model = next(
        m for m in registry.models if m.constituent_id == "openai/gpt-5-mini"
    )
    window_start = date(2025, 3, 1)
    window_end = date(2025, 4, 30)

    # Count events inside the window for target
    in_window_before = int(
        (
            (events["constituent_id"] == target_model.constituent_id)
            & (events["event_date"] >= pd.Timestamp(window_start))
            & (events["event_date"] <= pd.Timestamp(window_end))
        ).sum()
    )

    _, out_events, rec = regenerate_constituent_slice(
        panel, events, target_model, contributors,
        (window_start, window_end), seed=42,
        sigma_daily=0.07, mu_daily=0.0, step_rate_per_year=0.0,
    )

    assert rec["n_events_suppressed"] == in_window_before
    # No events left in window for target
    in_window_after = int(
        (
            (out_events["constituent_id"] == target_model.constituent_id)
            & (out_events["event_date"] >= pd.Timestamp(window_start))
            & (out_events["event_date"] <= pd.Timestamp(window_end))
        ).sum()
    )
    assert in_window_after == 0


def test_regenerate_new_constituent_bootstrap_creates_panel_rows() -> None:
    """Scenario 8 case: new constituent not in panel → bootstrap generates rows."""
    panel, events, _, contributors = _build_pipeline(n_days=180)
    new_model = ModelMetadata(
        constituent_id="anthropic/claude-haiku-5",
        tier=Tier.TPRR_S,
        provider="anthropic",
        canonical_name="Claude Haiku 5",
        baseline_input_price_usd_mtok=1.0,
        baseline_output_price_usd_mtok=4.0,
    )
    # Both contribs cover the new model (for this test, extend existing panel config)
    extended = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id=p.contributor_id,
                profile_name=p.profile_name,
                volume_scale=p.volume_scale,
                price_bias_pct=p.price_bias_pct,
                daily_noise_sigma_pct=p.daily_noise_sigma_pct,
                error_rate=p.error_rate,
                covered_models=[*p.covered_models, "anthropic/claude-haiku-5"],
            )
            for p in contributors.contributors
        ]
    )
    launch_start = date(2025, 5, 1)
    launch_end = date(2025, 6, 29)

    out_panel, _out_events, rec = regenerate_constituent_slice(
        panel,
        events,
        new_model,
        extended,
        (launch_start, launch_end),
        seed=42,
    )

    # Rows for the new constituent exist from launch_start
    new_rows = out_panel[out_panel["constituent_id"] == "anthropic/claude-haiku-5"]
    assert len(new_rows) > 0
    assert new_rows["observation_date"].min() >= pd.Timestamp(launch_start)
    assert new_rows["observation_date"].max() <= pd.Timestamp(launch_end)
    # Schema validates
    PanelObservationDF.validate(out_panel)
    # op_record indicates new-constituent mode
    assert rec["is_new_constituent"] is True
    assert rec["n_panel_rows_regenerated"] > 0


def test_regenerate_independence_across_constituents() -> None:
    """Regenerating constituent A leaves constituent B's rows byte-identical."""
    panel, events, registry, contributors = _build_pipeline(n_days=180)
    constituent_a = next(
        m for m in registry.models if m.constituent_id == "openai/gpt-5-mini"
    )
    constituent_b_id = "anthropic/claude-haiku-4-5"
    window_start = date(2025, 3, 1)
    window_end = date(2025, 4, 30)

    out_panel, out_events, _ = regenerate_constituent_slice(
        panel, events, constituent_a, contributors,
        (window_start, window_end), seed=42,
        sigma_daily=0.07, mu_daily=0.0, step_rate_per_year=0.0,
    )

    b_orig = panel[panel["constituent_id"] == constituent_b_id].sort_values(
        ["contributor_id", "observation_date"]
    ).reset_index(drop=True)
    b_out = out_panel[out_panel["constituent_id"] == constituent_b_id].sort_values(
        ["contributor_id", "observation_date"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(b_orig, b_out)

    # Similarly, events for constituent B unchanged
    b_events_orig = events[events["constituent_id"] == constituent_b_id].sort_values(
        ["event_date", "contributor_id"]
    ).reset_index(drop=True)
    b_events_out = out_events[out_events["constituent_id"] == constituent_b_id].sort_values(
        ["event_date", "contributor_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(b_events_orig, b_events_out)


def test_regenerate_no_covering_contributors_raises() -> None:
    panel, events, _, contributors = _build_pipeline(n_days=30)
    uncovered = ModelMetadata(
        constituent_id="fake/uncovered-model",
        tier=Tier.TPRR_S,
        provider="fake",
        canonical_name="Uncovered",
        baseline_input_price_usd_mtok=1.0,
        baseline_output_price_usd_mtok=4.0,
    )
    with pytest.raises(ValueError, match="no contributors cover"):
        regenerate_constituent_slice(
            panel, events, uncovered, contributors,
            (date(2025, 1, 10), date(2025, 1, 20)), seed=42,
        )


# ---------------------------------------------------------------------------
# Wrapper: freeze_pair_in_window
# ---------------------------------------------------------------------------


def test_freeze_pair_in_window_composes_suppress_and_override() -> None:
    panel, events, _, _ = _build_pipeline(n_days=90)
    freeze_start = date(2025, 2, 10)
    freeze_end = date(2025, 2, 23)
    entry_row = panel[
        (panel["contributor_id"] == "contrib_alpha")
        & (panel["constituent_id"] == "openai/gpt-5-mini")
        & (panel["observation_date"] == pd.Timestamp(freeze_start))
    ].iloc[0]
    entry_out = float(entry_row["output_price_usd_mtok"])
    entry_in = float(entry_row["input_price_usd_mtok"])

    out_panel, out_events, op_records = freeze_pair_in_window(
        panel, events,
        contributor_id="contrib_alpha",
        constituent_id="openai/gpt-5-mini",
        date_range=(freeze_start, freeze_end),
    )

    # All frozen rows have entry-day prices
    frozen = out_panel[
        (out_panel["contributor_id"] == "contrib_alpha")
        & (out_panel["constituent_id"] == "openai/gpt-5-mini")
        & (out_panel["observation_date"] >= pd.Timestamp(freeze_start))
        & (out_panel["observation_date"] <= pd.Timestamp(freeze_end))
    ]
    assert (frozen["output_price_usd_mtok"] == entry_out).all()
    assert (frozen["input_price_usd_mtok"] == entry_in).all()
    # Events for the pair in window are suppressed
    remaining_events = out_events[
        (out_events["contributor_id"] == "contrib_alpha")
        & (out_events["constituent_id"] == "openai/gpt-5-mini")
        & (out_events["event_date"] >= pd.Timestamp(freeze_start))
        & (out_events["event_date"] <= pd.Timestamp(freeze_end))
    ]
    assert len(remaining_events) == 0
    # Op records: two entries (suppress + override)
    assert len(op_records) == 2
    assert op_records[0]["op"] == "suppress_events"
    assert op_records[1]["op"] == "override_panel_prices"


def test_freeze_pair_in_window_no_entry_day_row_raises() -> None:
    panel, events, _, _ = _build_pipeline(n_days=30)
    with pytest.raises(ValueError, match="no entry-day panel row"):
        freeze_pair_in_window(
            panel, events,
            contributor_id="contrib_alpha",
            constituent_id="openai/gpt-5-mini",
            date_range=(date(2030, 1, 1), date(2030, 1, 10)),  # future, no row
        )


def test_freeze_pair_in_window_unsupported_source_raises() -> None:
    panel, events, _, _ = _build_pipeline(n_days=30)
    with pytest.raises(ValueError, match="freeze_price_source"):
        freeze_pair_in_window(
            panel, events,
            contributor_id="contrib_alpha",
            constituent_id="openai/gpt-5-mini",
            date_range=(date(2025, 1, 10), date(2025, 1, 20)),
            freeze_price_source="tier_median",  # not implemented in Phase 3.1
        )


# ---------------------------------------------------------------------------
# ScenarioManifest
# ---------------------------------------------------------------------------


def test_scenario_manifest_record_updates_counters() -> None:
    m = ScenarioManifest(scenario_id="test", seed=42)
    m.record({"op": "inject_change_events", "n_injected": 5})
    m.record({"op": "suppress_events", "n_suppressed": 3})
    m.record({"op": "remove_panel_rows", "n_removed": 10})
    m.record({"op": "override_panel_prices", "n_modified": 7})
    m.record({"op": "mutate_registry", "mutation": {"type": "tier_change"}})
    assert m.events_injected == 5
    assert m.events_suppressed == 3
    assert m.panel_rows_removed == 10
    assert m.panel_rows_modified == 7
    assert len(m.registry_mutations) == 1
    assert len(m.operations_applied) == 5


def test_scenario_manifest_notes_and_json() -> None:
    m = ScenarioManifest(scenario_id="scenario_5", seed=42)
    m.add_note("shifted from day 200 to day 203 due to natural event at day 198")
    m.record({"op": "inject_change_events", "n_injected": 6})
    payload = json.loads(m.to_json())
    assert payload["scenario_id"] == "scenario_5"
    assert payload["seed"] == 42
    assert payload["events_injected"] == 6
    assert "shifted from day 200" in payload["notes"][0]


def test_scenario_manifest_write_to_disk(tmp_path: Path) -> None:
    m = ScenarioManifest(scenario_id="scenario_9", seed=42)
    m.record({"op": "inject_change_events", "n_injected": 2})
    out_path = m.write(tmp_path)
    assert out_path.exists()
    assert out_path.name == "scenario_9_seed42_manifest.json"
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["scenario_id"] == "scenario_9"
    assert loaded["events_injected"] == 2
