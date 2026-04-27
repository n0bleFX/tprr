"""Tests for tprr.mockdata.scenarios — Phase 3.2 composer skeleton + simple scenarios."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tprr.config import (
    ContributorPanel,
    ContributorProfile,
    CorrelatedBlackoutSpec,
    FatFingerSpec,
    IntradaySpikeSpec,
    ModelMetadata,
    ModelRegistry,
    NewModelLaunchSpec,
    RegimeShiftSpec,
    ShockPriceCutSpec,
    StaleQuoteSpec,
    SustainedManipulationSpec,
    TierReshuffleSpec,
    VolumeScale,
)
from tprr.mockdata.change_events import apply_twap_to_panel, generate_change_events
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.outliers import ScenarioManifest
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.mockdata.scenarios import compose_scenario, preflight_event_clear_check
from tprr.mockdata.volume import generate_volumes
from tprr.schema import ChangeEventDF, PanelObservationDF, Tier

BACKTEST_START = date(2025, 1, 1)


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


def _contributors() -> ContributorPanel:
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
    n_days: int = 60, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry, ContributorPanel]:
    registry = _registry()
    contributors = _contributors()
    baseline, step_events = generate_baseline_prices(
        registry,
        BACKTEST_START,
        BACKTEST_START + timedelta(days=n_days - 1),
        seed=seed,
    )
    panel = generate_contributor_panel(baseline, contributors, registry, seed=seed)
    panel = generate_volumes(panel, contributors, seed=seed)
    events = generate_change_events(panel, step_events, registry, contributors, seed=seed)
    panel = apply_twap_to_panel(panel, events)
    return panel, events, registry, contributors


def _ff_spec(
    *,
    sid: str = "ff_test",
    contributor_id: str = "contrib_alpha",
    constituent_id: str = "openai/gpt-5-mini",
    day_offset: int = 30,
    slot: int = 16,
    multiplier: float = 10.0,
    after_slots: int = 1,
) -> FatFingerSpec:
    return FatFingerSpec.model_validate(
        {
            "id": sid,
            "kind": "fat_finger",
            "description": "test",
            "tier": "TPRR_S",
            "target": {
                "contributor_id": contributor_id,
                "constituent_id": constituent_id,
            },
            "timing": {"day_offset": day_offset, "slot": slot},
            "magnitude": {"multiplier": multiplier},
            "revert": {"after_slots": after_slots},
        }
    )


def _stale_quote_spec(
    *,
    contributor_id: str = "contrib_alpha",
    constituent_id: str = "google/gemini-flash-lite",
    day_offset_start: int = 20,
    duration_days: int = 14,
) -> StaleQuoteSpec:
    return StaleQuoteSpec.model_validate(
        {
            "id": "sq_test",
            "kind": "stale_quote",
            "description": "test",
            "tier": "TPRR_E",
            "target": {
                "contributor_id": contributor_id,
                "constituent_id": constituent_id,
            },
            "timing": {
                "day_offset_start": day_offset_start,
                "duration_days": duration_days,
            },
            "freeze_price_source": "entry_day",
        }
    )


def _intraday_spike_spec(
    *,
    contributor_id: str = "contrib_alpha",
    constituent_id: str = "anthropic/claude-haiku-4-5",
    day_offset: int = 25,
    slot_start: int = 10,
    slot_end: int = 12,
    multiplier: float = 1.25,
    revert_at_slot: int = 13,
) -> IntradaySpikeSpec:
    return IntradaySpikeSpec.model_validate(
        {
            "id": "is_test",
            "kind": "intraday_spike",
            "description": "test",
            "tier": "TPRR_S",
            "target": {
                "contributor_id": contributor_id,
                "constituent_id": constituent_id,
            },
            "timing": {
                "day_offset": day_offset,
                "slot_start": slot_start,
                "slot_end": slot_end,
            },
            "magnitude": {"multiplier": multiplier},
            "revert": {"at_slot": revert_at_slot},
        }
    )


def _correlated_blackout_spec(
    *,
    contributor_ids: list[str] | None = None,
    day_offset_start: int = 10,
    duration_days: int = 5,
) -> CorrelatedBlackoutSpec:
    return CorrelatedBlackoutSpec.model_validate(
        {
            "id": "cb_test",
            "kind": "correlated_blackout",
            "description": "test",
            "target": {
                "contributor_ids": (
                    contributor_ids or ["contrib_alpha", "contrib_beta"]
                ),
            },
            "timing": {
                "day_offset_start": day_offset_start,
                "duration_days": duration_days,
            },
        }
    )


def _shock_price_cut_spec(
    *,
    constituent_id: str = "google/gemini-flash-lite",
    day_offset: int = 30,
    multiplier: float = 0.5,
) -> ShockPriceCutSpec:
    return ShockPriceCutSpec.model_validate(
        {
            "id": "spc_test",
            "kind": "shock_price_cut",
            "description": "test",
            "tier": "TPRR_E",
            "target": {"constituent_id": constituent_id},
            "timing": {"day_offset": day_offset},
            "magnitude": {"multiplier": multiplier},
            "notes": ["test note"],
        }
    )


def _sustained_manipulation_spec(
    *,
    contributor_id: str = "contrib_alpha",
    constituent_id: str = "anthropic/claude-haiku-4-5",
    day_offset_start: int = 20,
    duration_days: int = 10,
    multiplier: float = 1.25,
) -> SustainedManipulationSpec:
    return SustainedManipulationSpec.model_validate(
        {
            "id": "sm_test",
            "kind": "sustained_manipulation",
            "description": "test",
            "tier": "TPRR_S",
            "target": {
                "contributor_id": contributor_id,
                "constituent_id": constituent_id,
            },
            "timing": {
                "day_offset_start": day_offset_start,
                "duration_days": duration_days,
            },
            "manipulation": {
                "type": "tier_median_multiplier",
                "multiplier": multiplier,
            },
        }
    )


def _tier_reshuffle_spec(
    *,
    constituent_id: str = "openai/gpt-5-pro",
    new_tier: str = "TPRR_S",
    day_offset: int = 30,
) -> TierReshuffleSpec:
    return TierReshuffleSpec.model_validate(
        {
            "id": "tr_test",
            "kind": "tier_reshuffle",
            "description": "test",
            "target": {"constituent_id": constituent_id},
            "new_tier": new_tier,
            "timing": {"day_offset": day_offset},
        }
    )


def _regime_shift_spec(
    *,
    tier: str = "TPRR_S",
    day_offset_start: int = 60,
    duration_days: int = 90,
    sigma_daily: float = 0.07,
    mu_daily: float = 0.0,
    step_rate_per_year: float = 0.0,
) -> RegimeShiftSpec:
    return RegimeShiftSpec.model_validate(
        {
            "id": "rs_test",
            "kind": "regime_shift",
            "description": "test",
            "tier": tier,
            "target": {"tier_wide": True},
            "timing": {
                "day_offset_start": day_offset_start,
                "duration_days": duration_days,
            },
            "dynamics": {
                "sigma_daily": sigma_daily,
                "mu_daily": mu_daily,
                "step_rate_per_year": step_rate_per_year,
            },
        }
    )


def _new_model_launch_spec(
    *,
    constituent_id: str = "anthropic/claude-haiku-5",
    coverage_ids: list[str] | None = None,
    day_offset: int = 30,
    baseline_input: float = 1.0,
    baseline_output: float = 4.0,
) -> NewModelLaunchSpec:
    return NewModelLaunchSpec.model_validate(
        {
            "id": "nml_test",
            "kind": "new_model_launch",
            "description": "test",
            "new_model": {
                "constituent_id": constituent_id,
                "tier": "TPRR_S",
                "provider": "anthropic",
                "canonical_name": "Claude Haiku 5",
                "baseline_input_price_usd_mtok": baseline_input,
                "baseline_output_price_usd_mtok": baseline_output,
            },
            "coverage": {
                "contributor_ids": (
                    coverage_ids or ["contrib_alpha", "contrib_beta"]
                ),
            },
            "timing": {"day_offset": day_offset},
        }
    )


def _panel_row(
    panel: pd.DataFrame, contrib: str, constituent: str, dt: date
) -> pd.Series:
    ts = pd.Timestamp(dt)
    matches = panel[
        (panel["observation_date"] == ts)
        & (panel["contributor_id"] == contrib)
        & (panel["constituent_id"] == constituent)
    ]
    assert len(matches) == 1, f"expected 1 panel row, got {len(matches)}"
    return matches.iloc[0]


# ---------------------------------------------------------------------------
# fat_finger
# ---------------------------------------------------------------------------


def test_compose_fat_finger_high_panel_twap_matches_expected() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(day_offset=30, slot=16, multiplier=10.0, after_slots=1)
    event_date = BACKTEST_START + timedelta(days=30)
    pre = _panel_row(panel, "contrib_alpha", "openai/gpt-5-mini", event_date)
    base_out = float(pre["output_price_usd_mtok"])

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, registry_out = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    expected_twap = (16 * base_out + 1 * 10.0 * base_out + 15 * base_out) / 32
    post = _panel_row(panel_out, "contrib_alpha", "openai/gpt-5-mini", event_date)
    assert post["output_price_usd_mtok"] == pytest.approx(expected_twap)
    assert registry_out is registry  # unchanged


def test_compose_fat_finger_low_panel_twap_matches_expected() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(
        sid="ff_low",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset=40,
        slot=20,
        multiplier=0.1,
        after_slots=1,
    )
    event_date = BACKTEST_START + timedelta(days=40)
    pre = _panel_row(panel, "contrib_alpha", "anthropic/claude-haiku-4-5", event_date)
    base_out = float(pre["output_price_usd_mtok"])

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    expected_twap = (20 * base_out + 1 * 0.1 * base_out + 11 * base_out) / 32
    post = _panel_row(
        panel_out, "contrib_alpha", "anthropic/claude-haiku-4-5", event_date
    )
    assert post["output_price_usd_mtok"] == pytest.approx(expected_twap)


def test_compose_fat_finger_injects_two_events() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    n_before = len(events)
    spec = _ff_spec(day_offset=30, slot=16, multiplier=10.0, after_slots=1)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    assert len(events_out) == n_before + 2
    new_events = events_out.tail(2)
    assert (new_events["reason"] == "outlier_injection").all()
    assert sorted(new_events["change_slot_idx"].tolist()) == [16, 17]
    assert manifest.events_injected == 2


def test_compose_fat_finger_revert_slot_overflow_raises() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(slot=31, after_slots=1)  # revert would land at 32
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    with pytest.raises(ValueError, match="exceeds maximum slot index"):
        compose_scenario(
            spec, panel, events, registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )


def test_compose_fat_finger_other_panel_rows_unchanged() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(day_offset=30, slot=16, multiplier=10.0, after_slots=1)
    event_date = BACKTEST_START + timedelta(days=30)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    untouched_mask = ~(
        (panel["observation_date"] == pd.Timestamp(event_date))
        & (panel["contributor_id"] == "contrib_alpha")
        & (panel["constituent_id"] == "openai/gpt-5-mini")
    )
    orig = panel.loc[untouched_mask].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    after = panel_out.loc[untouched_mask].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(orig, after)


# ---------------------------------------------------------------------------
# stale_quote
# ---------------------------------------------------------------------------


def test_compose_stale_quote_freezes_panel_to_entry_day_price() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _stale_quote_spec(day_offset_start=20, duration_days=14)
    entry_day = BACKTEST_START + timedelta(days=20)
    end_day = BACKTEST_START + timedelta(days=33)
    entry = _panel_row(
        panel, "contrib_alpha", "google/gemini-flash-lite", entry_day
    )
    entry_out = float(entry["output_price_usd_mtok"])
    entry_in = float(entry["input_price_usd_mtok"])

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    frozen = panel_out[
        (panel_out["contributor_id"] == "contrib_alpha")
        & (panel_out["constituent_id"] == "google/gemini-flash-lite")
        & (panel_out["observation_date"] >= pd.Timestamp(entry_day))
        & (panel_out["observation_date"] <= pd.Timestamp(end_day))
    ]
    assert len(frozen) == 14
    assert (frozen["output_price_usd_mtok"] == entry_out).all()
    assert (frozen["input_price_usd_mtok"] == entry_in).all()


def test_compose_stale_quote_suppresses_in_window_events() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _stale_quote_spec(day_offset_start=20, duration_days=14)
    entry_day = BACKTEST_START + timedelta(days=20)
    end_day = BACKTEST_START + timedelta(days=33)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    in_window = events_out[
        (events_out["contributor_id"] == "contrib_alpha")
        & (events_out["constituent_id"] == "google/gemini-flash-lite")
        & (events_out["event_date"] >= pd.Timestamp(entry_day))
        & (events_out["event_date"] <= pd.Timestamp(end_day))
    ]
    assert len(in_window) == 0


def test_compose_stale_quote_outside_window_unchanged() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _stale_quote_spec(day_offset_start=20, duration_days=14)
    entry_day = BACKTEST_START + timedelta(days=20)
    end_day = BACKTEST_START + timedelta(days=33)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    pair_mask_orig = (
        (panel["contributor_id"] == "contrib_alpha")
        & (panel["constituent_id"] == "google/gemini-flash-lite")
        & (
            (panel["observation_date"] < pd.Timestamp(entry_day))
            | (panel["observation_date"] > pd.Timestamp(end_day))
        )
    )
    pair_mask_out = (
        (panel_out["contributor_id"] == "contrib_alpha")
        & (panel_out["constituent_id"] == "google/gemini-flash-lite")
        & (
            (panel_out["observation_date"] < pd.Timestamp(entry_day))
            | (panel_out["observation_date"] > pd.Timestamp(end_day))
        )
    )
    orig = panel.loc[pair_mask_orig].sort_values("observation_date").reset_index(
        drop=True
    )
    after = panel_out.loc[pair_mask_out].sort_values("observation_date").reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(orig, after)


# ---------------------------------------------------------------------------
# intraday_spike
# ---------------------------------------------------------------------------


def test_compose_intraday_spike_panel_twap_matches_expected() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _intraday_spike_spec(
        day_offset=25,
        slot_start=10,
        slot_end=12,
        multiplier=1.25,
        revert_at_slot=13,
    )
    event_date = BACKTEST_START + timedelta(days=25)
    pre = _panel_row(
        panel, "contrib_alpha", "anthropic/claude-haiku-4-5", event_date
    )
    base_out = float(pre["output_price_usd_mtok"])

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    # Slots [0,10) base + [10,13) base*1.25 + [13,32) base = 32 slots.
    expected_twap = (10 * base_out + 3 * 1.25 * base_out + 19 * base_out) / 32
    post = _panel_row(
        panel_out, "contrib_alpha", "anthropic/claude-haiku-4-5", event_date
    )
    assert post["output_price_usd_mtok"] == pytest.approx(expected_twap)

    new_events = events_out.tail(2)
    assert sorted(new_events["change_slot_idx"].tolist()) == [10, 13]
    assert manifest.events_injected == 2


def test_compose_intraday_spike_revert_at_slot_mismatch_raises() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _intraday_spike_spec(
        slot_start=10, slot_end=12, revert_at_slot=15  # off by 2
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    with pytest.raises(ValueError, match="must be slot_end \\+ 1"):
        compose_scenario(
            spec, panel, events, registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_compose_scenario_dispatches_simple_kinds() -> None:
    """Each implemented kind dispatches without raising and records ops."""
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    specs: list[FatFingerSpec | StaleQuoteSpec | IntradaySpikeSpec] = [
        _ff_spec(),
        _stale_quote_spec(),
        _intraday_spike_spec(),
    ]
    for spec in specs:
        manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
        panel_out, events_out, registry_out = compose_scenario(
            spec, panel, events, registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )
        assert isinstance(panel_out, pd.DataFrame)
        assert isinstance(events_out, pd.DataFrame)
        assert registry_out is registry
        assert len(manifest.operations_applied) >= 1


# All ScenarioEntry kinds are implemented as of Batch D (scenarios 1-10).
# The dispatcher's defensive `# pragma: no cover` branch handles the case
# of a new ScenarioEntry subclass added without a composer; not exercisable
# without constructing a mock pydantic subclass, so no test for it here.


# ---------------------------------------------------------------------------
# Schema validation + manifest accounting
# ---------------------------------------------------------------------------


def test_compose_outputs_validate_dataframe_schemas() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(day_offset=30, slot=16, multiplier=10.0, after_slots=1)
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )
    PanelObservationDF.validate(panel_out)
    ChangeEventDF.validate(events_out)


def test_manifest_records_ops_for_each_composer() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)

    ff_manifest = ScenarioManifest(scenario_id="ff", seed=42)
    compose_scenario(
        _ff_spec(), panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ff_manifest,
    )
    assert ff_manifest.events_injected == 2
    assert len(ff_manifest.operations_applied) == 1  # single inject_change_events
    assert ff_manifest.operations_applied[0]["op"] == "inject_change_events"

    sq_manifest = ScenarioManifest(scenario_id="sq", seed=42)
    compose_scenario(
        _stale_quote_spec(), panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=sq_manifest,
    )
    # freeze_pair_in_window emits two op_records: suppress + override.
    assert len(sq_manifest.operations_applied) == 2
    op_kinds = {r["op"] for r in sq_manifest.operations_applied}
    assert op_kinds == {"suppress_events", "override_panel_prices"}

    is_manifest = ScenarioManifest(scenario_id="is", seed=42)
    compose_scenario(
        _intraday_spike_spec(), panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=is_manifest,
    )
    assert is_manifest.events_injected == 2


def test_compose_fat_finger_deterministic() -> None:
    """Same inputs -> identical panel + events outputs."""
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(day_offset=30, slot=16, multiplier=10.0, after_slots=1)

    panel_a, events_a, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="a", seed=42),
    )
    panel_b, events_b, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="b", seed=42),
    )
    pd.testing.assert_frame_equal(panel_a, panel_b)
    pd.testing.assert_frame_equal(events_a, events_b)


def test_compose_fat_finger_input_and_output_prices_both_scaled() -> None:
    """Multiplier applies uniformly to input and output prices."""
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(day_offset=30, slot=16, multiplier=10.0, after_slots=1)
    event_date = BACKTEST_START + timedelta(days=30)
    pre = _panel_row(panel, "contrib_alpha", "openai/gpt-5-mini", event_date)
    base_out = float(pre["output_price_usd_mtok"])
    base_in = float(pre["input_price_usd_mtok"])

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    expected_twap_out = (16 * base_out + 1 * 10.0 * base_out + 15 * base_out) / 32
    expected_twap_in = (16 * base_in + 1 * 10.0 * base_in + 15 * base_in) / 32
    post = _panel_row(panel_out, "contrib_alpha", "openai/gpt-5-mini", event_date)
    assert post["output_price_usd_mtok"] == pytest.approx(expected_twap_out)
    assert post["input_price_usd_mtok"] == pytest.approx(expected_twap_in)


# ---------------------------------------------------------------------------
# correlated_blackout
# ---------------------------------------------------------------------------


def test_compose_correlated_blackout_removes_panel_rows() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _correlated_blackout_spec(
        contributor_ids=["contrib_alpha", "contrib_beta"],
        day_offset_start=20,
        duration_days=5,
    )
    start = BACKTEST_START + timedelta(days=20)
    end = BACKTEST_START + timedelta(days=24)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    blackout_rows = panel_out[
        (panel_out["contributor_id"].isin(["contrib_alpha", "contrib_beta"]))
        & (panel_out["observation_date"] >= pd.Timestamp(start))
        & (panel_out["observation_date"] <= pd.Timestamp(end))
    ]
    assert len(blackout_rows) == 0


def test_compose_correlated_blackout_suppresses_events() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _correlated_blackout_spec(
        contributor_ids=["contrib_alpha", "contrib_beta"],
        day_offset_start=20,
        duration_days=5,
    )
    start = BACKTEST_START + timedelta(days=20)
    end = BACKTEST_START + timedelta(days=24)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    in_window_blackout = events_out[
        (events_out["contributor_id"].isin(["contrib_alpha", "contrib_beta"]))
        & (events_out["event_date"] >= pd.Timestamp(start))
        & (events_out["event_date"] <= pd.Timestamp(end))
    ]
    assert len(in_window_blackout) == 0


def test_compose_correlated_blackout_outside_window_unchanged() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _correlated_blackout_spec(
        contributor_ids=["contrib_alpha", "contrib_beta"],
        day_offset_start=20,
        duration_days=5,
    )
    start = BACKTEST_START + timedelta(days=20)
    end = BACKTEST_START + timedelta(days=24)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    outside_orig = panel[
        (panel["contributor_id"].isin(["contrib_alpha", "contrib_beta"]))
        & (
            (panel["observation_date"] < pd.Timestamp(start))
            | (panel["observation_date"] > pd.Timestamp(end))
        )
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    outside_out = panel_out[
        (panel_out["contributor_id"].isin(["contrib_alpha", "contrib_beta"]))
        & (
            (panel_out["observation_date"] < pd.Timestamp(start))
            | (panel_out["observation_date"] > pd.Timestamp(end))
        )
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(outside_orig, outside_out)


def test_compose_correlated_blackout_records_four_ops() -> None:
    """Two contributors x (remove_panel_rows + suppress_events) = 4 ops."""
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _correlated_blackout_spec(
        contributor_ids=["contrib_alpha", "contrib_beta"],
        day_offset_start=20,
        duration_days=5,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    op_kinds = [r["op"] for r in manifest.operations_applied]
    assert op_kinds.count("remove_panel_rows") == 2
    assert op_kinds.count("suppress_events") == 2


# ---------------------------------------------------------------------------
# shock_price_cut
# ---------------------------------------------------------------------------


def test_compose_shock_price_cut_fans_out_to_all_covering_contribs() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    # gemini-flash-lite covered by alpha only in test fixture (1 contributor).
    spec = _shock_price_cut_spec(
        constituent_id="google/gemini-flash-lite",
        day_offset=30,
        multiplier=0.5,
    )
    n_before = len(events)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    covering = [
        p.contributor_id
        for p in contributors.contributors
        if "google/gemini-flash-lite" in p.covered_models
    ]
    assert len(events_out) == n_before + len(covering)
    new_events = events_out.tail(len(covering))
    assert set(new_events["contributor_id"].tolist()) == set(covering)
    assert (new_events["constituent_id"] == "google/gemini-flash-lite").all()


def test_compose_shock_price_cut_applies_multiplier_to_both_axes() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _shock_price_cut_spec(
        constituent_id="google/gemini-flash-lite",
        day_offset=30,
        multiplier=0.5,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    new_events = events_out[events_out["reason"] == "outlier_injection"]
    assert len(new_events) > 0
    for _, row in new_events.iterrows():
        assert row["new_output_price_usd_mtok"] == pytest.approx(
            row["old_output_price_usd_mtok"] * 0.5
        )
        assert row["new_input_price_usd_mtok"] == pytest.approx(
            row["old_input_price_usd_mtok"] * 0.5
        )


def test_compose_shock_price_cut_events_have_outlier_injection_reason() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _shock_price_cut_spec(day_offset=30, multiplier=0.5)
    n_before = len(events)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    new_events = events_out.tail(len(events_out) - n_before)
    assert (new_events["reason"] == "outlier_injection").all()


def test_compose_shock_price_cut_slot_indices_in_range() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _shock_price_cut_spec(day_offset=30, multiplier=0.5)
    n_before = len(events)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    new_events = events_out.tail(len(events_out) - n_before)
    assert (new_events["change_slot_idx"] >= 0).all()
    assert (new_events["change_slot_idx"] <= 31).all()


def test_compose_shock_price_cut_deterministic() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _shock_price_cut_spec(day_offset=30, multiplier=0.5)

    panel_a, events_a, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="a", seed=42),
    )
    panel_b, events_b, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="b", seed=42),
    )
    pd.testing.assert_frame_equal(panel_a, panel_b)
    pd.testing.assert_frame_equal(events_a, events_b)


def test_compose_shock_price_cut_records_notes_in_manifest() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _shock_price_cut_spec(day_offset=30, multiplier=0.5)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )
    assert "test note" in manifest.notes


def test_compose_shock_price_cut_no_covering_contribs_raises() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    # uncovered/model isn't in any contributor's covered_models.
    spec = ShockPriceCutSpec.model_validate(
        {
            "id": "spc_uncovered",
            "kind": "shock_price_cut",
            "description": "test",
            "tier": "TPRR_E",
            "target": {"constituent_id": "uncovered/model"},
            "timing": {"day_offset": 30},
            "magnitude": {"multiplier": 0.5},
        }
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    with pytest.raises(ValueError, match="no contributors cover"):
        compose_scenario(
            spec, panel, events, registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )


# ---------------------------------------------------------------------------
# sustained_manipulation
# ---------------------------------------------------------------------------


def _build_manipulation_panel() -> tuple[
    pd.DataFrame, pd.DataFrame, ModelRegistry, ContributorPanel
]:
    """Custom panel with 4 S constituents and constant per-pair prices.

    Designed for predictable median computation in scenario 6 tests:
      target = anthropic/claude-haiku-4-5 (output 5.0, input 1.0 — but we
              parameterise via overrides)
      others = openai/gpt-5-mini (out 4.0), google/gemini-2-flash (out 2.5),
               mistral/mistral-large-3 (out 8.0)
    Median of others' (within-constituent contributor median) outputs:
      median([4.0, 2.5, 8.0]) = 4.0
    Manipulator at multiplier 1.25 -> output = 5.0; input median = 0.5 ->
      manipulator input = 0.625.
    """
    n_days = 30
    target = "anthropic/claude-haiku-4-5"
    others = [
        ("openai/gpt-5-mini", "openai", 0.5, 4.0),
        ("google/gemini-2-flash", "google", 0.3, 2.5),
        ("mistral/mistral-large-3", "mistral", 2.0, 8.0),
    ]
    registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=target,
                tier=Tier.TPRR_S,
                provider="anthropic",
                canonical_name="Claude Haiku 4.5",
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=5.0,
            ),
            *[
                ModelMetadata(
                    constituent_id=cid,
                    tier=Tier.TPRR_S,
                    provider=provider,
                    canonical_name=cid,
                    baseline_input_price_usd_mtok=in_p,
                    baseline_output_price_usd_mtok=out_p,
                )
                for cid, provider, in_p, out_p in others
            ],
        ]
    )
    contribs = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id=cid,
                profile_name=cid,
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=[target] + [c for c, _, _, _ in others],
            )
            for cid in ("contrib_alpha", "contrib_beta")
        ]
    )

    fixed_prices: dict[tuple[str, str], tuple[float, float]] = {
        ("contrib_alpha", target): (1.0, 5.0),
        ("contrib_beta", target): (1.0, 5.0),
    }
    for cid, _, in_p, out_p in others:
        fixed_prices[("contrib_alpha", cid)] = (in_p, out_p)
        fixed_prices[("contrib_beta", cid)] = (in_p, out_p)

    rows: list[dict[str, object]] = []
    for day in range(n_days):
        d = pd.Timestamp(BACKTEST_START + timedelta(days=day))
        for (contrib, constituent), (in_p, out_p) in fixed_prices.items():
            rows.append(
                {
                    "observation_date": d,
                    "constituent_id": constituent,
                    "contributor_id": contrib,
                    "tier_code": "TPRR_S",
                    "attestation_tier": "A",
                    "input_price_usd_mtok": in_p,
                    "output_price_usd_mtok": out_p,
                    "volume_mtok_7d": 100.0,
                    "source": "test_mock",
                    "submitted_at": d,
                    "notes": "",
                }
            )
    panel = pd.DataFrame(rows)

    events = pd.DataFrame(
        {
            "event_date": pd.Series([], dtype="datetime64[ns]"),
            "contributor_id": pd.Series([], dtype="object"),
            "constituent_id": pd.Series([], dtype="object"),
            "change_slot_idx": pd.Series([], dtype="int64"),
            "old_input_price_usd_mtok": pd.Series([], dtype="float64"),
            "new_input_price_usd_mtok": pd.Series([], dtype="float64"),
            "old_output_price_usd_mtok": pd.Series([], dtype="float64"),
            "new_output_price_usd_mtok": pd.Series([], dtype="float64"),
            "reason": pd.Series([], dtype="object"),
        }
    )
    return panel, events, registry, contribs


def test_compose_sustained_manipulation_overrides_to_median_times_multiplier() -> None:
    panel, events, registry, contributors = _build_manipulation_panel()
    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset_start=5,
        duration_days=10,
        multiplier=1.25,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    start = BACKTEST_START + timedelta(days=5)
    end = BACKTEST_START + timedelta(days=14)
    in_window = panel_out[
        (panel_out["contributor_id"] == "contrib_alpha")
        & (panel_out["constituent_id"] == "anthropic/claude-haiku-4-5")
        & (panel_out["observation_date"] >= pd.Timestamp(start))
        & (panel_out["observation_date"] <= pd.Timestamp(end))
    ]
    # median across {4.0, 2.5, 8.0} = 4.0 ; * 1.25 = 5.0
    # median across {0.5, 0.3, 2.0} = 0.5 ; * 1.25 = 0.625
    assert np.allclose(in_window["output_price_usd_mtok"], 5.0)
    assert np.allclose(in_window["input_price_usd_mtok"], 0.625)


def test_compose_sustained_manipulation_excludes_target_from_median_pool() -> None:
    """Setting target prices wildly off must not shift the manipulator's price."""
    panel, events, registry, contributors = _build_manipulation_panel()
    target = "anthropic/claude-haiku-4-5"
    # Replace target's panel prices with 50.0 / 60.0 — would shift median if
    # target were included in the pool.
    target_mask = panel["constituent_id"] == target
    panel = panel.copy()
    panel.loc[target_mask, "output_price_usd_mtok"] = 100.0
    panel.loc[target_mask, "input_price_usd_mtok"] = 50.0

    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id=target,
        day_offset_start=5,
        duration_days=10,
        multiplier=1.25,
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    in_window = panel_out[
        (panel_out["contributor_id"] == "contrib_alpha")
        & (panel_out["constituent_id"] == target)
        & (panel_out["observation_date"] >= pd.Timestamp(BACKTEST_START + timedelta(days=5)))
        & (panel_out["observation_date"] <= pd.Timestamp(BACKTEST_START + timedelta(days=14)))
    ]
    # Same as previous test — target's 100.0 / 50.0 ignored.
    assert np.allclose(in_window["output_price_usd_mtok"], 5.0)
    assert np.allclose(in_window["input_price_usd_mtok"], 0.625)


def test_compose_sustained_manipulation_other_contribs_on_target_unchanged() -> None:
    panel, events, registry, contributors = _build_manipulation_panel()
    target = "anthropic/claude-haiku-4-5"
    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id=target,
        day_offset_start=5,
        duration_days=10,
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    beta_target = panel_out[
        (panel_out["contributor_id"] == "contrib_beta")
        & (panel_out["constituent_id"] == target)
    ].sort_values("observation_date").reset_index(drop=True)
    beta_target_orig = panel[
        (panel["contributor_id"] == "contrib_beta")
        & (panel["constituent_id"] == target)
    ].sort_values("observation_date").reset_index(drop=True)
    pd.testing.assert_frame_equal(beta_target, beta_target_orig)


def test_compose_sustained_manipulation_other_constituents_unchanged() -> None:
    panel, events, registry, contributors = _build_manipulation_panel()
    target = "anthropic/claude-haiku-4-5"
    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id=target,
        day_offset_start=5,
        duration_days=10,
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    other_constituents = ["openai/gpt-5-mini", "google/gemini-2-flash"]
    other_orig = panel[
        panel["constituent_id"].isin(other_constituents)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    other_out = panel_out[
        panel_out["constituent_id"].isin(other_constituents)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(other_orig, other_out)


def test_compose_sustained_manipulation_no_other_s_raises() -> None:
    """Single-S-constituent registry where target is the only one -> no median pool."""
    panel, events, _registry, contributors = _build_manipulation_panel()
    # Strip registry to just the target constituent.
    target = "anthropic/claude-haiku-4-5"
    minimal_registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=target,
                tier=Tier.TPRR_S,
                provider="anthropic",
                canonical_name="X",
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=5.0,
            )
        ]
    )
    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id=target,
        day_offset_start=5,
        duration_days=10,
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    with pytest.raises(ValueError, match="no S constituents other than"):
        compose_scenario(
            spec, panel, events, minimal_registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )


def test_compose_sustained_manipulation_in_window_events_suppressed() -> None:
    """Events for the manipulator pair in window are removed."""
    panel, events, registry, contributors = _build_manipulation_panel()
    # Inject one fake pre-existing event for (alpha, target) inside window.
    fake_event = pd.DataFrame(
        [
            {
                "event_date": pd.Timestamp(BACKTEST_START + timedelta(days=8)),
                "contributor_id": "contrib_alpha",
                "constituent_id": "anthropic/claude-haiku-4-5",
                "change_slot_idx": 12,
                "old_input_price_usd_mtok": 1.0,
                "new_input_price_usd_mtok": 1.5,
                "old_output_price_usd_mtok": 5.0,
                "new_output_price_usd_mtok": 6.0,
                "reason": "baseline_move",
            }
        ]
    ).astype(
        {
            "event_date": "datetime64[ns]",
            "change_slot_idx": "int64",
        }
    )
    events_with_fake = pd.concat([events, fake_event], ignore_index=True)

    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset_start=5,
        duration_days=10,
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events_with_fake, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    in_window = events_out[
        (events_out["contributor_id"] == "contrib_alpha")
        & (events_out["constituent_id"] == "anthropic/claude-haiku-4-5")
        & (events_out["event_date"] >= pd.Timestamp(BACKTEST_START + timedelta(days=5)))
        & (events_out["event_date"] <= pd.Timestamp(BACKTEST_START + timedelta(days=14)))
    ]
    assert len(in_window) == 0


def test_compose_sustained_manipulation_records_suppress_and_override() -> None:
    panel, events, registry, contributors = _build_manipulation_panel()
    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset_start=5,
        duration_days=10,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    op_kinds = {r["op"] for r in manifest.operations_applied}
    assert op_kinds == {"suppress_events", "override_panel_prices"}


def test_compose_sustained_manipulation_deterministic() -> None:
    panel, events, registry, contributors = _build_manipulation_panel()
    spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset_start=5,
        duration_days=10,
    )

    panel_a, events_a, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="a", seed=42),
    )
    panel_b, events_b, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="b", seed=42),
    )
    pd.testing.assert_frame_equal(panel_a, panel_b)
    pd.testing.assert_frame_equal(events_a, events_b)


# ---------------------------------------------------------------------------
# new_model_launch
# ---------------------------------------------------------------------------


def test_compose_new_model_launch_panel_rows_appear_from_launch_day() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _new_model_launch_spec(
        constituent_id="anthropic/claude-haiku-5",
        coverage_ids=["contrib_alpha", "contrib_beta"],
        day_offset=30,
    )
    launch_date = BACKTEST_START + timedelta(days=30)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    new_rows = panel_out[
        panel_out["constituent_id"] == "anthropic/claude-haiku-5"
    ]
    assert len(new_rows) > 0
    assert new_rows["observation_date"].min() >= pd.Timestamp(launch_date)


def test_compose_new_model_launch_no_panel_rows_before_launch() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _new_model_launch_spec(
        constituent_id="anthropic/claude-haiku-5",
        coverage_ids=["contrib_alpha", "contrib_beta"],
        day_offset=30,
    )
    launch_date = BACKTEST_START + timedelta(days=30)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    pre_launch = panel_out[
        (panel_out["constituent_id"] == "anthropic/claude-haiku-5")
        & (panel_out["observation_date"] < pd.Timestamp(launch_date))
    ]
    assert len(pre_launch) == 0


def test_compose_new_model_launch_registry_includes_new_constituent() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _new_model_launch_spec(
        constituent_id="anthropic/claude-haiku-5",
        coverage_ids=["contrib_alpha", "contrib_beta"],
        day_offset=30,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, _events_out, registry_out = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    new_ids = {m.constituent_id for m in registry_out.models}
    assert "anthropic/claude-haiku-5" in new_ids
    # Original registry untouched.
    orig_ids = {m.constituent_id for m in registry.models}
    assert "anthropic/claude-haiku-5" not in orig_ids


def test_compose_new_model_launch_other_constituents_unchanged() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _new_model_launch_spec(
        constituent_id="anthropic/claude-haiku-5",
        coverage_ids=["contrib_alpha", "contrib_beta"],
        day_offset=30,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    existing_ids = {m.constituent_id for m in registry.models}
    existing_orig = panel[panel["constituent_id"].isin(existing_ids)].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    existing_out = panel_out[panel_out["constituent_id"].isin(existing_ids)].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(existing_orig, existing_out)


def test_compose_new_model_launch_records_mutate_and_regen_ops() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _new_model_launch_spec(
        constituent_id="anthropic/claude-haiku-5",
        coverage_ids=["contrib_alpha", "contrib_beta"],
        day_offset=30,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    op_kinds = {r["op"] for r in manifest.operations_applied}
    assert op_kinds == {"mutate_registry", "regenerate_constituent_slice"}


def test_compose_new_model_launch_resulting_panel_validates_schema() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _new_model_launch_spec(
        constituent_id="anthropic/claude-haiku-5",
        coverage_ids=["contrib_alpha", "contrib_beta"],
        day_offset=30,
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )
    PanelObservationDF.validate(panel_out)
    ChangeEventDF.validate(events_out)


# ---------------------------------------------------------------------------
# Dispatcher coverage for Batch C kinds
# ---------------------------------------------------------------------------


def test_compose_scenario_dispatches_all_batch_c_kinds() -> None:
    """All four Batch C kinds dispatch without raising."""
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    specs: list = [
        _correlated_blackout_spec(
            contributor_ids=["contrib_alpha", "contrib_beta"],
            day_offset_start=20,
            duration_days=5,
        ),
        _shock_price_cut_spec(day_offset=30, multiplier=0.5),
        _new_model_launch_spec(
            coverage_ids=["contrib_alpha", "contrib_beta"], day_offset=30
        ),
    ]
    for spec in specs:
        manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
        panel_out, events_out, _ = compose_scenario(
            spec, panel, events, registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )
        assert isinstance(panel_out, pd.DataFrame)
        assert isinstance(events_out, pd.DataFrame)
        assert len(manifest.operations_applied) >= 1

    # Sustained manipulation needs the dedicated panel.
    panel_m, events_m, registry_m, contribs_m = _build_manipulation_panel()
    sm_spec = _sustained_manipulation_spec(
        contributor_id="contrib_alpha",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset_start=5,
        duration_days=10,
    )
    sm_manifest = ScenarioManifest(scenario_id=sm_spec.id, seed=42)
    sm_panel_out, sm_events_out, _ = compose_scenario(
        sm_spec, panel_m, events_m, registry_m, contribs_m,
        BACKTEST_START, seed=42, manifest=sm_manifest,
    )
    assert isinstance(sm_panel_out, pd.DataFrame)
    assert isinstance(sm_events_out, pd.DataFrame)


# ---------------------------------------------------------------------------
# tier_reshuffle (scenario 7)
# ---------------------------------------------------------------------------


def test_compose_tier_reshuffle_pre_effective_rows_keep_old_tier_code() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )
    effective_date = BACKTEST_START + timedelta(days=30)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    pre = panel_out[
        (panel_out["constituent_id"] == "openai/gpt-5-pro")
        & (panel_out["observation_date"] < pd.Timestamp(effective_date))
    ]
    assert len(pre) > 0
    assert (pre["tier_code"] == "TPRR_F").all()


def test_compose_tier_reshuffle_post_effective_rows_have_new_tier_code() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )
    effective_date = BACKTEST_START + timedelta(days=30)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    post = panel_out[
        (panel_out["constituent_id"] == "openai/gpt-5-pro")
        & (panel_out["observation_date"] >= pd.Timestamp(effective_date))
    ]
    assert len(post) > 0
    assert (post["tier_code"] == "TPRR_S").all()


def test_compose_tier_reshuffle_prices_unchanged_across_boundary() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    target_orig = panel[panel["constituent_id"] == "openai/gpt-5-pro"].sort_values(
        ["observation_date", "contributor_id"]
    ).reset_index(drop=True)
    target_out = panel_out[
        panel_out["constituent_id"] == "openai/gpt-5-pro"
    ].sort_values(["observation_date", "contributor_id"]).reset_index(drop=True)

    np.testing.assert_array_equal(
        target_orig["output_price_usd_mtok"].to_numpy(),
        target_out["output_price_usd_mtok"].to_numpy(),
    )
    np.testing.assert_array_equal(
        target_orig["input_price_usd_mtok"].to_numpy(),
        target_out["input_price_usd_mtok"].to_numpy(),
    )


def test_compose_tier_reshuffle_other_constituents_unchanged() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    other_ids = [
        m.constituent_id
        for m in registry.models
        if m.constituent_id != "openai/gpt-5-pro"
    ]
    other_orig = panel[panel["constituent_id"].isin(other_ids)].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    other_out = panel_out[panel_out["constituent_id"].isin(other_ids)].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(other_orig, other_out)


def test_compose_tier_reshuffle_registry_reflects_new_tier() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, _events_out, registry_out = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    target = next(
        m for m in registry_out.models if m.constituent_id == "openai/gpt-5-pro"
    )
    assert target.tier == Tier.TPRR_S
    # Original registry untouched (composer returns a new registry).
    orig_target = next(
        m for m in registry.models if m.constituent_id == "openai/gpt-5-pro"
    )
    assert orig_target.tier == Tier.TPRR_F


def test_compose_tier_reshuffle_records_op_and_warning_note() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    op_kinds = {r["op"] for r in manifest.operations_applied}
    assert op_kinds == {"mutate_registry"}
    # Warning note flags Phase 7 must read panel.tier_code, not registry.
    note_text = " ".join(manifest.notes)
    assert "panel.tier_code" in note_text
    assert "Phase 7" in note_text


def test_compose_tier_reshuffle_events_unchanged() -> None:
    """Events carry no tier_code -> events_df is byte-identical post-composition."""
    panel, events, registry, contributors = _build_pipeline(n_days=60)
    spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    _panel_out, events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )
    pd.testing.assert_frame_equal(
        events.reset_index(drop=True), events_out.reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# regime_shift (scenario 10)
# ---------------------------------------------------------------------------


def _s_constituent_panel_series(
    panel_df: pd.DataFrame,
    contributor_id: str,
    constituent_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> np.ndarray:
    rows = panel_df[
        (panel_df["contributor_id"] == contributor_id)
        & (panel_df["constituent_id"] == constituent_id)
        & (panel_df["observation_date"] >= start)
        & (panel_df["observation_date"] <= end)
    ].sort_values("observation_date")
    return rows["output_price_usd_mtok"].to_numpy()


def test_compose_regime_shift_in_window_prices_differ_from_phase2() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    start = pd.Timestamp(BACKTEST_START + timedelta(days=60))
    end = pd.Timestamp(BACKTEST_START + timedelta(days=149))

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    s_ids = {m.constituent_id for m in registry.models if m.tier == Tier.TPRR_S}
    in_window_orig = panel[
        panel["constituent_id"].isin(s_ids)
        & (panel["observation_date"] >= start)
        & (panel["observation_date"] <= end)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    in_window_out = panel_out[
        panel_out["constituent_id"].isin(s_ids)
        & (panel_out["observation_date"] >= start)
        & (panel_out["observation_date"] <= end)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    assert not np.allclose(
        in_window_orig["output_price_usd_mtok"].to_numpy(),
        in_window_out["output_price_usd_mtok"].to_numpy(),
    )


def test_compose_regime_shift_pre_window_byte_identical() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    start = pd.Timestamp(BACKTEST_START + timedelta(days=60))

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    s_ids = {m.constituent_id for m in registry.models if m.tier == Tier.TPRR_S}
    pre_orig = panel[
        panel["constituent_id"].isin(s_ids)
        & (panel["observation_date"] < start)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pre_out = panel_out[
        panel_out["constituent_id"].isin(s_ids)
        & (panel_out["observation_date"] < start)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(pre_orig, pre_out)


def test_compose_regime_shift_post_window_byte_identical_no_reanchor() -> None:
    """Post-window panel rows untouched — walks land where they land, no re-anchoring."""
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    end = pd.Timestamp(BACKTEST_START + timedelta(days=149))

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    s_ids = {m.constituent_id for m in registry.models if m.tier == Tier.TPRR_S}
    post_orig = panel[
        panel["constituent_id"].isin(s_ids)
        & (panel["observation_date"] > end)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    post_out = panel_out[
        panel_out["constituent_id"].isin(s_ids)
        & (panel_out["observation_date"] > end)
    ].sort_values(
        ["observation_date", "contributor_id", "constituent_id"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(post_orig, post_out)


def test_compose_regime_shift_pairwise_correlation_low() -> None:
    """Two S constituents have low pairwise correlation of daily returns in window."""
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    start = pd.Timestamp(BACKTEST_START + timedelta(days=60))
    end = pd.Timestamp(BACKTEST_START + timedelta(days=149))

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    panel_out, _events_out, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    # contrib_alpha covers both S constituents — sample one contributor's
    # walk on each constituent. Independence of regenerate_constituent_slice
    # streams across constituents should yield low sample correlation.
    series_mini = _s_constituent_panel_series(
        panel_out, "contrib_alpha", "openai/gpt-5-mini", start, end
    )
    series_haiku = _s_constituent_panel_series(
        panel_out, "contrib_alpha", "anthropic/claude-haiku-4-5", start, end
    )
    returns_mini = np.diff(series_mini) / series_mini[:-1]
    returns_haiku = np.diff(series_haiku) / series_haiku[:-1]
    correlation = float(np.corrcoef(returns_mini, returns_haiku)[0, 1])
    assert abs(correlation) < 0.5, f"correlation {correlation:.3f} >= 0.5 — streams not independent"


def test_compose_regime_shift_records_one_op_per_s_constituent() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    n_s = sum(1 for m in registry.models if m.tier == Tier.TPRR_S)

    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=manifest,
    )

    op_kinds = [r["op"] for r in manifest.operations_applied]
    assert op_kinds.count("regenerate_constituent_slice") == n_s


def test_compose_regime_shift_step_rate_nonzero_raises() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(
        day_offset_start=60, duration_days=90, step_rate_per_year=2.0
    )
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    with pytest.raises(ValueError, match="step_rate_per_year == 0"):
        compose_scenario(
            spec, panel, events, registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )


def test_compose_regime_shift_no_constituents_in_tier_raises() -> None:
    panel, events, _registry, contributors = _build_pipeline(n_days=180, seed=42)
    # Empty-tier registry: no S constituents.
    empty_s_registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="openai/gpt-5-pro",
                tier=Tier.TPRR_F,
                provider="openai",
                canonical_name="GPT-5 Pro",
                baseline_input_price_usd_mtok=15.0,
                baseline_output_price_usd_mtok=75.0,
            )
        ]
    )
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    manifest = ScenarioManifest(scenario_id=spec.id, seed=42)
    with pytest.raises(ValueError, match="no constituents in tier"):
        compose_scenario(
            spec, panel, events, empty_s_registry, contributors,
            BACKTEST_START, seed=42, manifest=manifest,
        )


def test_compose_regime_shift_deterministic() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _regime_shift_spec(day_offset_start=60, duration_days=90)

    panel_a, events_a, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="a", seed=42),
    )
    panel_b, events_b, _ = compose_scenario(
        spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=ScenarioManifest(scenario_id="b", seed=42),
    )
    pd.testing.assert_frame_equal(panel_a, panel_b)
    pd.testing.assert_frame_equal(events_a, events_b)


# ---------------------------------------------------------------------------
# Final dispatcher coverage — all 9 scenario kinds resolve
# ---------------------------------------------------------------------------


def test_compose_scenario_dispatches_all_batch_d_kinds() -> None:
    panel, events, registry, contributors = _build_pipeline(n_days=180, seed=42)

    tr_spec = _tier_reshuffle_spec(
        constituent_id="openai/gpt-5-pro", new_tier="TPRR_S", day_offset=30
    )
    tr_manifest = ScenarioManifest(scenario_id=tr_spec.id, seed=42)
    tr_panel, tr_events, tr_registry = compose_scenario(
        tr_spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=tr_manifest,
    )
    assert isinstance(tr_panel, pd.DataFrame)
    assert isinstance(tr_events, pd.DataFrame)
    assert tr_registry is not registry  # new registry returned

    rs_spec = _regime_shift_spec(day_offset_start=60, duration_days=90)
    rs_manifest = ScenarioManifest(scenario_id=rs_spec.id, seed=42)
    rs_panel, rs_events, _ = compose_scenario(
        rs_spec, panel, events, registry, contributors,
        BACKTEST_START, seed=42, manifest=rs_manifest,
    )
    assert isinstance(rs_panel, pd.DataFrame)
    assert isinstance(rs_events, pd.DataFrame)


# ---------------------------------------------------------------------------
# preflight_event_clear_check
# ---------------------------------------------------------------------------


def _make_event_row(
    *,
    event_date: date,
    contributor_id: str,
    constituent_id: str,
    slot: int = 16,
) -> dict[str, object]:
    return {
        "event_date": pd.Timestamp(event_date),
        "contributor_id": contributor_id,
        "constituent_id": constituent_id,
        "change_slot_idx": slot,
        "old_input_price_usd_mtok": 1.0,
        "new_input_price_usd_mtok": 1.1,
        "old_output_price_usd_mtok": 5.0,
        "new_output_price_usd_mtok": 5.5,
        "reason": "baseline_move",
    }


def _events_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            {
                "event_date": pd.Series([], dtype="datetime64[ns]"),
                "contributor_id": pd.Series([], dtype="object"),
                "constituent_id": pd.Series([], dtype="object"),
                "change_slot_idx": pd.Series([], dtype="int64"),
                "old_input_price_usd_mtok": pd.Series([], dtype="float64"),
                "new_input_price_usd_mtok": pd.Series([], dtype="float64"),
                "old_output_price_usd_mtok": pd.Series([], dtype="float64"),
                "new_output_price_usd_mtok": pd.Series([], dtype="float64"),
                "reason": pd.Series([], dtype="object"),
            }
        )
    df = pd.DataFrame(rows)
    df["event_date"] = pd.to_datetime(df["event_date"]).astype("datetime64[ns]")
    df["change_slot_idx"] = df["change_slot_idx"].astype("int64")
    return df


def test_preflight_fat_finger_clean_day_passes() -> None:
    _, events, _, contributors = _build_pipeline(n_days=180, seed=42)
    spec = _ff_spec(
        contributor_id="contrib_alpha",
        constituent_id="openai/gpt-5-mini",
        day_offset=120,
    )
    # Strip events for the target pair so it's guaranteed clear.
    clean_events = events[
        ~(
            (events["contributor_id"] == "contrib_alpha")
            & (events["constituent_id"] == "openai/gpt-5-mini")
        )
    ].reset_index(drop=True)
    preflight_event_clear_check(spec, clean_events, contributors, BACKTEST_START)


def test_preflight_fat_finger_collision_within_window_raises() -> None:
    _, _, _, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(
        contributor_id="contrib_alpha",
        constituent_id="openai/gpt-5-mini",
        day_offset=30,
    )
    # Inject a collision 2 days before the scenario day_offset (within +-5 window).
    events_with_collision = _events_df(
        [
            _make_event_row(
                event_date=BACKTEST_START + timedelta(days=28),
                contributor_id="contrib_alpha",
                constituent_id="openai/gpt-5-mini",
            )
        ]
    )
    with pytest.raises(ValueError, match="pre-flight event-clear-day check FAILED"):
        preflight_event_clear_check(
            spec, events_with_collision, contributors, BACKTEST_START
        )


def test_preflight_fat_finger_outside_window_passes() -> None:
    _, _, _, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(day_offset=30)
    # Event 6 days after target (outside +-5 window) — should pass.
    events_outside = _events_df(
        [
            _make_event_row(
                event_date=BACKTEST_START + timedelta(days=36),
                contributor_id=spec.target.contributor_id,
                constituent_id=spec.target.constituent_id,
            )
        ]
    )
    preflight_event_clear_check(spec, events_outside, contributors, BACKTEST_START)


def test_preflight_intraday_spike_collision_raises() -> None:
    _, _, _, contributors = _build_pipeline(n_days=60)
    spec = _intraday_spike_spec(
        contributor_id="contrib_alpha",
        constituent_id="anthropic/claude-haiku-4-5",
        day_offset=30,
    )
    events_with_collision = _events_df(
        [
            _make_event_row(
                event_date=BACKTEST_START + timedelta(days=30),
                contributor_id="contrib_alpha",
                constituent_id="anthropic/claude-haiku-4-5",
            )
        ]
    )
    with pytest.raises(ValueError, match="pre-flight event-clear-day check FAILED"):
        preflight_event_clear_check(
            spec, events_with_collision, contributors, BACKTEST_START
        )


def test_preflight_shock_price_cut_skipped_no_event_clear_required() -> None:
    """shock_price_cut is NOT in the pre-flight scope (Matt's Batch E spec
    enumerates 1, 2, 9 only). The day-203 annotation in scenarios.yaml
    tracks provider-level baseline step events at a different semantic
    layer; pre-flight at the per-contributor event level would be too
    strict and would conflict with the historical annotation that
    considered day 203 clear given a natural step event at day 198."""
    _, events, _, contributors = _build_pipeline(n_days=60)
    spec = _shock_price_cut_spec(day_offset=30)
    # Even with heavy natural events on the target constituent in window,
    # pre-flight is a no-op for shock_price_cut.
    preflight_event_clear_check(spec, events, contributors, BACKTEST_START)


def test_preflight_correlated_blackout_skipped_no_event_clear_required() -> None:
    """Non-event-clear scenario kinds skip the pre-flight check."""
    _, events, _, contributors = _build_pipeline(n_days=60)
    spec = _correlated_blackout_spec(
        contributor_ids=["contrib_alpha", "contrib_beta"],
        day_offset_start=20,
        duration_days=5,
    )
    # Should not raise even though events_df is heavy with natural events.
    preflight_event_clear_check(spec, events, contributors, BACKTEST_START)


def test_preflight_error_message_names_scenario_pair_and_event_date() -> None:
    _, _, _, contributors = _build_pipeline(n_days=60)
    spec = _ff_spec(
        sid="ff_collide",
        contributor_id="contrib_alpha",
        constituent_id="openai/gpt-5-mini",
        day_offset=30,
    )
    collision_date = BACKTEST_START + timedelta(days=32)
    events_with_collision = _events_df(
        [
            _make_event_row(
                event_date=collision_date,
                contributor_id="contrib_alpha",
                constituent_id="openai/gpt-5-mini",
            )
        ]
    )
    with pytest.raises(ValueError) as excinfo:
        preflight_event_clear_check(
            spec, events_with_collision, contributors, BACKTEST_START
        )
    msg = str(excinfo.value)
    assert "ff_collide" in msg
    assert "contrib_alpha" in msg
    assert "openai/gpt-5-mini" in msg
    assert collision_date.isoformat() in msg
    # Action suggestions present.
    assert "do NOT silently shift" in msg
    assert "Re-verify scenarios.yaml" in msg
    assert "Change seed" in msg


# Production scenarios.yaml + seed 42 end-to-end pre-flight is covered by
# the integration test in tests/test_generate_mock_data.py — that test runs
# the script with the full production registry where the day_offset
# annotations were verified.
