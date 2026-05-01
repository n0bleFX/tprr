"""Tests for tprr.config — typed loaders, validators, and cross-validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from tprr.config import (
    AllConfig,
    ContributorProfile,
    CorrelatedBlackoutSpec,
    FatFingerSpec,
    IndexConfig,
    IntradaySpikeSpec,
    ModelMetadata,
    NewModelLaunchSpec,
    RegimeShiftSpec,
    ScenariosConfig,
    StaleQuoteSpec,
    SustainedManipulationSpec,
    TierBRevenueConfig,
    TierBRevenueEntry,
    TierReshuffleSpec,
    VolumeScale,
    load_all,
    load_index_config,
    load_model_registry,
    load_scenarios,
    load_tier_b_revenue,
)
from tprr.schema import AttestationTier, Tier


def _write_minimal_configs(config_dir: Path) -> None:
    """Write a complete, internally-consistent set of stub config files."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "index_config.yaml").write_text(
        dedent(
            """\
            lambda: 3.0
            base_date: 2026-01-01
            backtest_start: 2025-01-01
            quality_gate_pct: 0.15
            continuity_check_pct: 0.25
            min_constituents_per_tier: 3
            staleness_max_days: 3
            tier_haircuts:
              A: 1.0
              B: 0.9
              C: 0.8
            twap_window_utc: [9, 17]
            twap_slots: 32
            default_ordering: twap_then_weight
            """
        ),
        encoding="utf-8",
    )
    (config_dir / "model_registry.yaml").write_text(
        dedent(
            """\
            models:
              - constituent_id: openai/gpt-5-pro
                tier: TPRR_F
                provider: openai
                canonical_name: GPT-5 Pro
                baseline_input_price_usd_mtok: 15.0
                baseline_output_price_usd_mtok: 75.0
              - constituent_id: openai/gpt-5-mini
                tier: TPRR_S
                provider: openai
                canonical_name: GPT-5 Mini
                baseline_input_price_usd_mtok: 0.5
                baseline_output_price_usd_mtok: 4.0
            """
        ),
        encoding="utf-8",
    )
    (config_dir / "contributors.yaml").write_text(
        dedent(
            """\
            contributors:
              - contributor_id: contrib_alpha
                profile_name: Alpha
                volume_scale: high
                price_bias_pct: 0.0
                daily_noise_sigma_pct: 0.5
                error_rate: 0.01
                covered_models:
                  - openai/gpt-5-pro
                  - openai/gpt-5-mini
            """
        ),
        encoding="utf-8",
    )
    (config_dir / "tier_b_revenue.yaml").write_text(
        dedent(
            """\
            entries:
              - provider: openai
                period: 2025-Q1
                amount_usd: 2500000000
                source: analyst_triangulation
              - provider: openai
                period: 2025-Q2
                amount_usd: 3100000000
                source: reported
            """
        ),
        encoding="utf-8",
    )
    (config_dir / "scenarios.yaml").write_text("scenarios: []\n", encoding="utf-8")


def test_index_config_defaults_when_loaded_from_empty_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "index_config.yaml"
    yaml_path.write_text("", encoding="utf-8")
    cfg = load_index_config(yaml_path)
    assert cfg.lambda_ == 3.0
    assert cfg.base_date == date(2026, 1, 1)
    assert cfg.backtest_start == date(2025, 1, 1)
    assert cfg.quality_gate_pct == 0.15
    assert cfg.continuity_check_pct == 0.25
    assert cfg.min_constituents_per_tier == 3
    assert cfg.staleness_max_days == 3
    # Phase 7H Batch C (DL 2026-04-30): Tier B haircut 0.9 -> 0.5.
    assert cfg.tier_haircuts == {
        AttestationTier.A: 1.0,
        AttestationTier.B: 0.5,
        AttestationTier.C: 0.8,
    }
    assert cfg.twap_window_utc == (9, 17)
    assert cfg.twap_slots == 32
    assert cfg.default_ordering == "twap_then_weight"


def test_index_config_overrides_apply_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "index_config.yaml"
    yaml_path.write_text("lambda: 5.0\nstaleness_max_days: 7\n", encoding="utf-8")
    cfg = load_index_config(yaml_path)
    assert cfg.lambda_ == 5.0
    assert cfg.staleness_max_days == 7
    assert cfg.twap_slots == 32  # untouched default


def test_index_config_lambda_alias_serialises() -> None:
    cfg = IndexConfig()
    dumped = cfg.model_dump(by_alias=True)
    assert "lambda" in dumped
    assert "lambda_" not in dumped


def test_model_registry_loads_valid_yaml(tmp_path: Path) -> None:
    _write_minimal_configs(tmp_path)
    registry = load_model_registry(tmp_path / "model_registry.yaml")
    assert len(registry) == 2
    assert registry.models[0].constituent_id == "openai/gpt-5-pro"
    assert registry.models[0].tier == Tier.TPRR_F
    assert registry.models[0].openrouter_author is None
    assert registry.models[0].active_from is None


def test_model_metadata_rejects_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        ModelMetadata(  # type: ignore[call-arg]
            constituent_id="x/y",
            tier=Tier.TPRR_F,
            canonical_name="X",
            baseline_input_price_usd_mtok=1.0,
            baseline_output_price_usd_mtok=2.0,
        )


def test_model_metadata_rejects_invalid_tier() -> None:
    with pytest.raises(ValidationError):
        ModelMetadata(
            constituent_id="x/y",
            tier="TPRR_XYZ",  # type: ignore[arg-type]
            provider="x",
            canonical_name="X",
            baseline_input_price_usd_mtok=1.0,
            baseline_output_price_usd_mtok=2.0,
        )


def test_contributor_profile_accepts_valid_volume_scale() -> None:
    profile = ContributorProfile(
        contributor_id="a",
        profile_name="A",
        volume_scale=VolumeScale.HIGH,
        price_bias_pct=0.0,
        daily_noise_sigma_pct=0.5,
        error_rate=0.01,
        covered_models=["openai/gpt-5-pro"],
    )
    assert profile.volume_scale == VolumeScale.HIGH


def test_contributor_profile_rejects_invalid_volume_scale() -> None:
    with pytest.raises(ValidationError):
        ContributorProfile(
            contributor_id="a",
            profile_name="A",
            volume_scale="enormous",  # type: ignore[arg-type]
            price_bias_pct=0.0,
            daily_noise_sigma_pct=0.5,
            error_rate=0.01,
            covered_models=[],
        )


def test_tier_b_revenue_entry_accepts_valid_period() -> None:
    entry = TierBRevenueEntry(
        provider="openai",
        period="2025-Q1",
        amount_usd=1.0,
        source="reported",
    )
    assert entry.period == "2025-Q1"


@pytest.mark.parametrize(
    "bad_period",
    [
        "2025-q1",  # lowercase q
        "25-Q1",  # two-digit year
        "2025-Q5",  # invalid quarter (high)
        "2025-Q0",  # invalid quarter (low)
        "2025-Q01",  # extra digit on quarter
        "2025-Q1 ",  # trailing whitespace
        " 2025-Q1",  # leading whitespace
        "2025_Q1",  # underscore separator
        "2025-1",  # missing Q
        "Q1-2025",  # reversed
        "",  # empty
        "2025-QQ",  # garbage
    ],
)
def test_tier_b_revenue_entry_rejects_malformed_period(bad_period: str) -> None:
    with pytest.raises(ValidationError):
        TierBRevenueEntry(
            provider="openai",
            period=bad_period,
            amount_usd=1.0,
            source="reported",
        )


def test_tier_b_revenue_entry_accepts_each_valid_quarter() -> None:
    for q in (1, 2, 3, 4):
        entry = TierBRevenueEntry(
            provider="openai",
            period=f"2025-Q{q}",
            amount_usd=1.0,
            source="x",
        )
        assert entry.period == f"2025-Q{q}"


def test_get_provider_revenue_interpolates_between_quarters() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"),
            TierBRevenueEntry(provider="openai", period="2025-Q2", amount_usd=2_000.0, source="x"),
        ]
    )
    midpoint = date(2025, 5, 15)
    revenue = cfg.get_provider_revenue("openai", midpoint)
    span_days = (date(2025, 6, 30) - date(2025, 3, 31)).days
    days_in = (midpoint - date(2025, 3, 31)).days
    expected = 1_000.0 + (days_in / span_days) * 1_000.0
    assert abs(revenue - expected) < 1e-9


def test_get_provider_revenue_exact_at_anchor_dates() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"),
            TierBRevenueEntry(provider="openai", period="2025-Q2", amount_usd=2_000.0, source="x"),
        ]
    )
    assert cfg.get_provider_revenue("openai", date(2025, 3, 31)) == 1_000.0
    assert cfg.get_provider_revenue("openai", date(2025, 6, 30)) == 2_000.0


def test_get_provider_revenue_clamps_below_earliest() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(provider="openai", period="2025-Q2", amount_usd=2_000.0, source="x"),
        ]
    )
    assert cfg.get_provider_revenue("openai", date(2024, 1, 1)) == 2_000.0


def test_get_provider_revenue_clamps_above_latest() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"),
        ]
    )
    assert cfg.get_provider_revenue("openai", date(2027, 1, 1)) == 1_000.0


def test_get_provider_revenue_raises_on_unknown_provider() -> None:
    cfg = TierBRevenueConfig(entries=[])
    with pytest.raises(ValueError, match="no Tier B revenue entries"):
        cfg.get_provider_revenue("nonexistent", date(2025, 1, 1))


def test_get_provider_revenue_filters_to_matching_provider_only() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"),
            TierBRevenueEntry(
                provider="anthropic",
                period="2025-Q1",
                amount_usd=999_999.0,
                source="x",
            ),
        ]
    )
    assert cfg.get_provider_revenue("openai", date(2025, 3, 31)) == 1_000.0
    assert cfg.get_provider_revenue("anthropic", date(2025, 3, 31)) == 999_999.0


def test_load_all_returns_validated_bundle(tmp_path: Path) -> None:
    _write_minimal_configs(tmp_path)
    bundle = load_all(tmp_path)
    assert isinstance(bundle, AllConfig)
    assert bundle.index.lambda_ == 3.0
    assert len(bundle.model_registry) == 2
    assert len(bundle.contributors) == 1


def test_load_all_raises_when_covered_model_missing_from_registry(
    tmp_path: Path,
) -> None:
    _write_minimal_configs(tmp_path)
    (tmp_path / "contributors.yaml").write_text(
        dedent(
            """\
            contributors:
              - contributor_id: contrib_alpha
                profile_name: Alpha
                volume_scale: high
                price_bias_pct: 0.0
                daily_noise_sigma_pct: 0.5
                error_rate: 0.01
                covered_models:
                  - openai/gpt-5-pro
                  - openai/gpt-5-nonexistent
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not in model registry"):
        load_all(tmp_path)


def test_load_index_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "index_config.yaml"
    yaml_path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected YAML mapping"):
        load_index_config(yaml_path)


def test_load_scenarios_accepts_empty_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "scenarios.yaml"
    yaml_path.write_text("", encoding="utf-8")
    scenarios = load_scenarios(yaml_path)
    assert isinstance(scenarios, ScenariosConfig)


# ===========================================================================
# Phase 4b — production tier_b_revenue.yaml
# ===========================================================================


_TIER_B_EXPECTED_PROVIDERS = {
    "openai",
    "anthropic",
    "google",
    "deepseek",
    "alibaba",
    "mistral",
}
_TIER_B_EXCLUDED_PROVIDERS = {"meta", "xiaomi"}
_TIER_B_EXPECTED_PERIODS = {
    "2025-Q1",
    "2025-Q2",
    "2025-Q3",
    "2025-Q4",
    "2026-Q1",
}


def test_production_tier_b_revenue_loads_cleanly() -> None:
    cfg = load_tier_b_revenue()
    # 6 providers x 5 quarters = 30 entries
    assert len(cfg) == 30


def test_production_tier_b_revenue_has_six_v0_1_providers() -> None:
    cfg = load_tier_b_revenue()
    providers = {e.provider for e in cfg.entries}
    assert providers == _TIER_B_EXPECTED_PROVIDERS


def test_production_tier_b_revenue_excludes_meta_and_xiaomi() -> None:
    """Meta (Llama) and Xiaomi (MiMo) are intentionally absent per
    decision log 2026-04-28 'Tier B revenue config: Meta + Xiaomi
    excluded as Tier-A-only'."""
    cfg = load_tier_b_revenue()
    providers = {e.provider for e in cfg.entries}
    assert _TIER_B_EXCLUDED_PROVIDERS.isdisjoint(providers)


@pytest.mark.parametrize("provider", sorted(_TIER_B_EXPECTED_PROVIDERS))
def test_production_tier_b_revenue_each_provider_has_5_quarters(
    provider: str,
) -> None:
    cfg = load_tier_b_revenue()
    periods = {e.period for e in cfg.entries if e.provider == provider}
    assert periods == _TIER_B_EXPECTED_PERIODS


def test_production_tier_b_revenue_get_provider_revenue_at_q1_2025() -> None:
    cfg = load_tier_b_revenue()
    # Spot-check exact end-of-quarter anchor returns the YAML amount
    openai_q1 = cfg.get_provider_revenue("openai", date(2025, 3, 31))
    anthropic_q1 = cfg.get_provider_revenue("anthropic", date(2025, 3, 31))
    google_q1 = cfg.get_provider_revenue("google", date(2025, 3, 31))
    assert openai_q1 == 300_000_000.0
    assert anthropic_q1 == 200_000_000.0
    assert google_q1 == 940_000_000.0


def test_production_tier_b_revenue_interpolates_between_quarters() -> None:
    cfg = load_tier_b_revenue()
    # Mid-Q2 (mid-May) should fall between Q1 (Mar 31) and Q2 (Jun 30) anchors.
    # OpenAI: Q1=$300M, Q2=$440M. Mid-May ~45 days into the 91-day window.
    mid_q2 = cfg.get_provider_revenue("openai", date(2025, 5, 15))
    span_days = (date(2025, 6, 30) - date(2025, 3, 31)).days
    days_in = (date(2025, 5, 15) - date(2025, 3, 31)).days
    expected = 300_000_000.0 + (days_in / span_days) * (440_000_000.0 - 300_000_000.0)
    assert abs(mid_q2 - expected) < 1.0


def test_production_tier_b_revenue_meta_raises_no_entries() -> None:
    cfg = load_tier_b_revenue()
    with pytest.raises(ValueError, match="no Tier B revenue entries"):
        cfg.get_provider_revenue("meta", date(2025, 6, 30))


def test_production_tier_b_revenue_xiaomi_raises_no_entries() -> None:
    cfg = load_tier_b_revenue()
    with pytest.raises(ValueError, match="no Tier B revenue entries"):
        cfg.get_provider_revenue("xiaomi", date(2025, 6, 30))


def test_production_tier_b_revenue_clamps_below_earliest_quarter() -> None:
    """Below earliest anchor (2025-Q1 → Mar 31), returns earliest amount."""
    cfg = load_tier_b_revenue()
    early = cfg.get_provider_revenue("openai", date(2024, 1, 1))
    assert early == 300_000_000.0  # 2025-Q1 amount, clamped


def test_production_tier_b_revenue_clamps_above_latest_quarter() -> None:
    """Above latest anchor (2026-Q1 → Mar 31), returns latest amount."""
    cfg = load_tier_b_revenue()
    late = cfg.get_provider_revenue("anthropic", date(2027, 1, 1))
    assert late == 2_520_000_000.0  # 2026-Q1 amount, clamped


def test_production_tier_b_revenue_amounts_strictly_increasing_per_provider() -> None:
    """Each provider's quarterly revenue should be monotonically non-decreasing
    across the v0.1 ARR-growth period (Jan 2025 - Mar 2026)."""
    from itertools import pairwise

    cfg = load_tier_b_revenue()
    period_order = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1"]
    for provider in _TIER_B_EXPECTED_PROVIDERS:
        amounts = [
            next(e.amount_usd for e in cfg.entries if e.provider == provider and e.period == p)
            for p in period_order
        ]
        for prev, curr in pairwise(amounts):
            assert curr >= prev, (
                f"{provider}: revenue not monotonic across {period_order} = {amounts}"
            )


def test_production_tier_b_revenue_source_values_in_known_set() -> None:
    """Source field values must be one of the documented categories."""
    cfg = load_tier_b_revenue()
    known_sources = {"reported", "analyst_triangulation", "synthetic_for_mvp"}
    actual_sources = {e.source for e in cfg.entries}
    assert actual_sources <= known_sources, (
        f"Unknown source values: {actual_sources - known_sources}"
    )


def test_load_tier_b_revenue_accepts_empty_entries_list(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tier_b_revenue.yaml"
    yaml_path.write_text("entries: []\n", encoding="utf-8")
    cfg = load_tier_b_revenue(yaml_path)
    assert len(cfg) == 0


# ===========================================================================
# Scenarios — schema-level validation tests (per-spec, no I/O)
# ===========================================================================


def _ff_payload(**overrides: object) -> dict[str, object]:
    """Minimal fat_finger payload as a dict — overridable per test."""
    base: dict[str, object] = {
        "id": "ff_test",
        "kind": "fat_finger",
        "description": "test",
        "tier": "TPRR_S",
        "target": {"contributor_id": "c", "constituent_id": "m"},
        "timing": {"day_offset": 10, "slot": 5},
        "magnitude": {"multiplier": 10.0},
        "revert": {"after_slots": 1},
    }
    base.update(overrides)
    return base


def test_fat_finger_spec_validates_minimal_happy_path() -> None:
    spec = FatFingerSpec.model_validate(_ff_payload())
    assert spec.id == "ff_test"
    assert spec.tier == Tier.TPRR_S
    assert spec.timing.slot == 5
    assert spec.magnitude.multiplier == 10.0


def test_fat_finger_spec_rejects_invalid_slot() -> None:
    payload = _ff_payload(timing={"day_offset": 10, "slot": 32})
    with pytest.raises(ValidationError):
        FatFingerSpec.model_validate(payload)


def test_fat_finger_spec_rejects_zero_or_negative_multiplier() -> None:
    for bad in (0.0, -1.0):
        payload = _ff_payload(magnitude={"multiplier": bad})
        with pytest.raises(ValidationError):
            FatFingerSpec.model_validate(payload)


def test_fat_finger_spec_rejects_negative_day_offset() -> None:
    payload = _ff_payload(timing={"day_offset": -1, "slot": 5})
    with pytest.raises(ValidationError):
        FatFingerSpec.model_validate(payload)


def test_intraday_spike_spec_rejects_slot_start_after_end() -> None:
    payload = {
        "id": "is_test",
        "kind": "intraday_spike",
        "description": "test",
        "tier": "TPRR_S",
        "target": {"contributor_id": "c", "constituent_id": "m"},
        "timing": {"day_offset": 10, "slot_start": 20, "slot_end": 10},
        "magnitude": {"multiplier": 1.25},
        "revert": {"at_slot": 11},
    }
    with pytest.raises(ValidationError, match="slot_start"):
        IntradaySpikeSpec.model_validate(payload)


def test_intraday_spike_spec_validates_full_range_at_boundary() -> None:
    """Boundary case: slot_start=0 + slot_end=31 covers the entire fixing window."""
    payload = {
        "id": "is_test",
        "kind": "intraday_spike",
        "description": "test",
        "tier": "TPRR_S",
        "target": {"contributor_id": "c", "constituent_id": "m"},
        "timing": {"day_offset": 10, "slot_start": 0, "slot_end": 31},
        "magnitude": {"multiplier": 1.25},
        "revert": {"at_slot": 0},
    }
    spec = IntradaySpikeSpec.model_validate(payload)
    assert spec.timing.slot_start == 0
    assert spec.timing.slot_end == 31


def test_correlated_blackout_spec_rejects_single_contributor() -> None:
    payload = {
        "id": "cb_test",
        "kind": "correlated_blackout",
        "description": "test",
        "target": {"contributor_ids": ["c1"]},
        "timing": {"day_offset_start": 10, "duration_days": 5},
    }
    with pytest.raises(ValidationError, match="at least 2"):
        CorrelatedBlackoutSpec.model_validate(payload)


def test_correlated_blackout_spec_rejects_duplicate_contributors() -> None:
    payload = {
        "id": "cb_test",
        "kind": "correlated_blackout",
        "description": "test",
        "target": {"contributor_ids": ["c1", "c1"]},
        "timing": {"day_offset_start": 10, "duration_days": 5},
    }
    with pytest.raises(ValidationError, match="unique"):
        CorrelatedBlackoutSpec.model_validate(payload)


def test_tier_reshuffle_spec_validates_happy_path() -> None:
    payload = {
        "id": "tr_test",
        "kind": "tier_reshuffle",
        "description": "test",
        "target": {"constituent_id": "x/y"},
        "new_tier": "TPRR_S",
        "timing": {"day_offset": 200},
    }
    spec = TierReshuffleSpec.model_validate(payload)
    assert spec.new_tier == Tier.TPRR_S
    assert spec.timing.day_offset == 200


def test_new_model_launch_spec_rejects_negative_baseline_price() -> None:
    payload = {
        "id": "nml_test",
        "kind": "new_model_launch",
        "description": "test",
        "new_model": {
            "constituent_id": "x/new",
            "tier": "TPRR_S",
            "provider": "x",
            "canonical_name": "X New",
            "baseline_input_price_usd_mtok": -1.0,
            "baseline_output_price_usd_mtok": 4.0,
        },
        "coverage": {"contributor_ids": ["c1"]},
        "timing": {"day_offset": 100},
    }
    with pytest.raises(ValidationError):
        NewModelLaunchSpec.model_validate(payload)


def test_regime_shift_spec_rejects_negative_sigma() -> None:
    payload = {
        "id": "rs_test",
        "kind": "regime_shift",
        "description": "test",
        "tier": "TPRR_S",
        "target": {"tier_wide": True},
        "timing": {"day_offset_start": 0, "duration_days": 10},
        "dynamics": {
            "sigma_daily": -0.01,
            "mu_daily": 0.0,
            "step_rate_per_year": 0.0,
        },
    }
    with pytest.raises(ValidationError):
        RegimeShiftSpec.model_validate(payload)


def test_stale_quote_spec_rejects_unsupported_freeze_source() -> None:
    payload = {
        "id": "sq_test",
        "kind": "stale_quote",
        "description": "test",
        "tier": "TPRR_E",
        "target": {"contributor_id": "c", "constituent_id": "m"},
        "timing": {"day_offset_start": 100, "duration_days": 14},
        "freeze_price_source": "tier_median",
    }
    with pytest.raises(ValidationError):
        StaleQuoteSpec.model_validate(payload)


def test_sustained_manipulation_spec_rejects_unknown_manipulation_type() -> None:
    payload = {
        "id": "sm_test",
        "kind": "sustained_manipulation",
        "description": "test",
        "tier": "TPRR_S",
        "target": {"contributor_id": "c", "constituent_id": "m"},
        "timing": {"day_offset_start": 100, "duration_days": 60},
        "manipulation": {"type": "tier_min_multiplier", "multiplier": 1.25},
    }
    with pytest.raises(ValidationError):
        SustainedManipulationSpec.model_validate(payload)


def test_scenarios_config_discriminates_correctly_on_kind() -> None:
    """A list with mixed kinds parses each entry to the right concrete class."""
    cfg = ScenariosConfig.model_validate(
        {
            "scenarios": [
                _ff_payload(id="ff_a"),
                {
                    "id": "rs_a",
                    "kind": "regime_shift",
                    "description": "x",
                    "tier": "TPRR_S",
                    "target": {"tier_wide": True},
                    "timing": {"day_offset_start": 0, "duration_days": 10},
                    "dynamics": {
                        "sigma_daily": 0.01,
                        "mu_daily": 0.0,
                        "step_rate_per_year": 0.0,
                    },
                },
            ]
        }
    )
    assert isinstance(cfg.scenarios[0], FatFingerSpec)
    assert isinstance(cfg.scenarios[1], RegimeShiftSpec)


def test_scenarios_config_unknown_kind_raises() -> None:
    payload = {
        "scenarios": [
            {"id": "x", "kind": "unknown_kind", "description": "x"},
        ]
    }
    with pytest.raises(ValidationError):
        ScenariosConfig.model_validate(payload)


def test_scenarios_config_rejects_duplicate_scenario_ids() -> None:
    payload = {
        "scenarios": [
            _ff_payload(id="dup"),
            _ff_payload(id="dup", timing={"day_offset": 11, "slot": 6}),
        ]
    }
    with pytest.raises(ValidationError, match="unique"):
        ScenariosConfig.model_validate(payload)


# ===========================================================================
# Scenarios — file-load + cross-validation tests
# ===========================================================================


def test_load_scenarios_full_manifest_from_disk() -> None:
    """Production config/scenarios.yaml loads with all 10 expected entries."""
    cfg = load_scenarios()
    assert len(cfg.scenarios) == 10
    expected_ids = {
        "fat_finger_high",
        "fat_finger_low",
        "stale_quote",
        "correlated_blackout",
        "shock_price_cut",
        "sustained_manipulation",
        "tier_reshuffle",
        "new_model_launch",
        "intraday_spike",
        "regime_shift",
    }
    assert {s.id for s in cfg.scenarios} == expected_ids


def test_load_all_cross_validates_scenario_contributor_refs(
    tmp_path: Path,
) -> None:
    _write_minimal_configs(tmp_path)
    (tmp_path / "scenarios.yaml").write_text(
        dedent(
            """\
            scenarios:
              - id: bad_contrib
                kind: fat_finger
                description: x
                tier: TPRR_S
                target:
                  contributor_id: contrib_nonexistent
                  constituent_id: openai/gpt-5-pro
                timing: { day_offset: 10, slot: 5 }
                magnitude: { multiplier: 10.0 }
                revert: { after_slots: 1 }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not in contributor panel"):
        load_all(tmp_path, backtest_end=date(2027, 1, 1))


def test_load_all_cross_validates_scenario_constituent_refs(
    tmp_path: Path,
) -> None:
    _write_minimal_configs(tmp_path)
    (tmp_path / "scenarios.yaml").write_text(
        dedent(
            """\
            scenarios:
              - id: bad_const
                kind: fat_finger
                description: x
                tier: TPRR_S
                target:
                  contributor_id: contrib_alpha
                  constituent_id: nonexistent/model
                timing: { day_offset: 10, slot: 5 }
                magnitude: { multiplier: 10.0 }
                revert: { after_slots: 1 }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not in model registry"):
        load_all(tmp_path, backtest_end=date(2027, 1, 1))


def test_load_all_rejects_new_model_launch_constituent_already_in_registry(
    tmp_path: Path,
) -> None:
    _write_minimal_configs(tmp_path)
    (tmp_path / "scenarios.yaml").write_text(
        dedent(
            """\
            scenarios:
              - id: dup_constituent
                kind: new_model_launch
                description: x
                new_model:
                  constituent_id: openai/gpt-5-pro
                  tier: TPRR_F
                  provider: openai
                  canonical_name: GPT-5 Pro Duplicate
                  baseline_input_price_usd_mtok: 15.0
                  baseline_output_price_usd_mtok: 75.0
                coverage:
                  contributor_ids: [contrib_alpha]
                timing: { day_offset: 100 }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="already in registry"):
        load_all(tmp_path, backtest_end=date(2027, 1, 1))


def test_load_all_rejects_scenario_day_offset_beyond_backtest_window(
    tmp_path: Path,
) -> None:
    _write_minimal_configs(tmp_path)
    (tmp_path / "scenarios.yaml").write_text(
        dedent(
            """\
            scenarios:
              - id: too_far
                kind: fat_finger
                description: x
                tier: TPRR_S
                target:
                  contributor_id: contrib_alpha
                  constituent_id: openai/gpt-5-pro
                timing: { day_offset: 999, slot: 5 }
                magnitude: { multiplier: 10.0 }
                revert: { after_slots: 1 }
            """
        ),
        encoding="utf-8",
    )
    # backtest_start (2025-01-01) -> backtest_end (2025-01-31) = 30-day window.
    with pytest.raises(ValueError, match="exceeds backtest window"):
        load_all(tmp_path, backtest_end=date(2025, 1, 31))


def test_load_all_rejects_scenario_window_extending_beyond_backtest_end(
    tmp_path: Path,
) -> None:
    _write_minimal_configs(tmp_path)
    (tmp_path / "scenarios.yaml").write_text(
        dedent(
            """\
            scenarios:
              - id: window_overflow
                kind: regime_shift
                description: x
                tier: TPRR_S
                target: { tier_wide: true }
                timing: { day_offset_start: 25, duration_days: 20 }
                dynamics:
                  sigma_daily: 0.05
                  mu_daily: 0.0
                  step_rate_per_year: 0.0
            """
        ),
        encoding="utf-8",
    )
    # day_offset_start=25 + duration_days=20 → last day 44, > 30-day window.
    with pytest.raises(ValueError, match="exceeds backtest window"):
        load_all(tmp_path, backtest_end=date(2025, 1, 31))
