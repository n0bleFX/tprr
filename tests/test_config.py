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
    IndexConfig,
    ModelMetadata,
    ScenariosConfig,
    TierBRevenueConfig,
    TierBRevenueEntry,
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
    assert cfg.tier_haircuts == {
        AttestationTier.A: 1.0,
        AttestationTier.B: 0.9,
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
        "2025-q1",     # lowercase q
        "25-Q1",       # two-digit year
        "2025-Q5",     # invalid quarter (high)
        "2025-Q0",     # invalid quarter (low)
        "2025-Q01",    # extra digit on quarter
        "2025-Q1 ",    # trailing whitespace
        " 2025-Q1",    # leading whitespace
        "2025_Q1",     # underscore separator
        "2025-1",      # missing Q
        "Q1-2025",     # reversed
        "",            # empty
        "2025-QQ",     # garbage
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
            TierBRevenueEntry(
                provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"
            ),
            TierBRevenueEntry(
                provider="openai", period="2025-Q2", amount_usd=2_000.0, source="x"
            ),
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
            TierBRevenueEntry(
                provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"
            ),
            TierBRevenueEntry(
                provider="openai", period="2025-Q2", amount_usd=2_000.0, source="x"
            ),
        ]
    )
    assert cfg.get_provider_revenue("openai", date(2025, 3, 31)) == 1_000.0
    assert cfg.get_provider_revenue("openai", date(2025, 6, 30)) == 2_000.0


def test_get_provider_revenue_clamps_below_earliest() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="openai", period="2025-Q2", amount_usd=2_000.0, source="x"
            ),
        ]
    )
    assert cfg.get_provider_revenue("openai", date(2024, 1, 1)) == 2_000.0


def test_get_provider_revenue_clamps_above_latest() -> None:
    cfg = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"
            ),
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
            TierBRevenueEntry(
                provider="openai", period="2025-Q1", amount_usd=1_000.0, source="x"
            ),
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


def test_load_tier_b_revenue_accepts_empty_entries_list(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tier_b_revenue.yaml"
    yaml_path.write_text("entries: []\n", encoding="utf-8")
    cfg = load_tier_b_revenue(yaml_path)
    assert len(cfg) == 0
