"""Tests for tprr.sensitivity.multi_seed — Phase 10 Batch 10C.

The multi-seed runner regenerates the Tier A panel per seed via the same
pipeline as ``scripts/generate_mock_data.py``, then runs the canonical
pipeline on each. Tests use a small seed range (3 seeds) for speed —
empirical validation of the 20-seed runs lives in the Batch 10C
analysis itself.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tprr.config import (
    ContributorPanel,
    ContributorProfile,
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
    VolumeScale,
)
from tprr.schema import AttestationTier, Tier
from tprr.sensitivity.baseline import BaselineInputs
from tprr.sensitivity.manifest import read_manifest
from tprr.sensitivity.multi_seed import (
    MultiSeedRun,
    build_clean_panel_runs,
    build_clean_plus_scenario_runs,
    run_multi_seed_sweep,
)

# ---------------------------------------------------------------------------
# Tiny in-memory fixture
# ---------------------------------------------------------------------------


def _registry_three_f() -> ModelRegistry:
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=Tier.TPRR_F,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=p_in,
                baseline_output_price_usd_mtok=p_out,
            )
            for cid, p_in, p_out in [
                ("openai/gpt-5-pro", 15.0, 75.0),
                ("anthropic/claude-opus-4-7", 14.0, 70.0),
                ("google/gemini-3-pro", 5.0, 30.0),
            ]
        ]
    )


def _contributors_three() -> ContributorPanel:
    return ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id=c,
                profile_name="test",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.0,
                error_rate=0.0,
                covered_models=[
                    "openai/gpt-5-pro",
                    "anthropic/claude-opus-4-7",
                    "google/gemini-3-pro",
                ],
            )
            for c in ("c1", "c2", "c3")
        ]
    )


def _row(
    *,
    cid: str,
    contrib: str,
    d: date,
    twap_out: float,
    twap_in: float,
    volume: float,
    tier: Tier = Tier.TPRR_F,
    attestation: AttestationTier = AttestationTier.A,
) -> dict[str, Any]:
    ts = pd.Timestamp(d)
    return {
        "observation_date": ts,
        "constituent_id": cid,
        "contributor_id": contrib,
        "tier_code": tier.value,
        "attestation_tier": attestation.value,
        "input_price_usd_mtok": float(twap_in),
        "output_price_usd_mtok": float(twap_out),
        "volume_mtok_7d": float(volume),
        "twap_output_usd_mtok": float(twap_out),
        "twap_input_usd_mtok": float(twap_in),
        "source": "test",
        "submitted_at": ts,
        "notes": "",
    }


def _multi_day_clean_panel(n_days: int = 5, start: date = date(2025, 1, 1)) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for offset in range(n_days):
        d = start + timedelta(days=offset)
        for cid, p_out, p_in in [
            ("openai/gpt-5-pro", 75.0, 15.0),
            ("anthropic/claude-opus-4-7", 70.0, 14.0),
            ("google/gemini-3-pro", 30.0, 5.0),
        ]:
            for c in ["c1", "c2", "c3"]:
                rows.append(
                    _row(
                        cid=cid,
                        contrib=c,
                        d=d,
                        twap_out=p_out,
                        twap_in=p_in,
                        volume=100.0,
                    )
                )
    return pd.DataFrame(rows)


def _empty_change_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
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
    )


def _baseline_inputs_static() -> BaselineInputs:
    """Provides the seed-static inputs (Tier C empty, registry, contributors,
    range). Tier A panel here is unused — the multi-seed runner regenerates
    it per seed from generators. We populate ``tier_a_panel`` with a small
    valid-shape frame so static-typed callers don't see an empty default.
    """
    return BaselineInputs(
        tier_a_panel=_multi_day_clean_panel(n_days=2),
        change_events=_empty_change_events(),
        tier_c_panel=pd.DataFrame(
            columns=[
                "observation_date",
                "constituent_id",
                "contributor_id",
                "tier_code",
                "attestation_tier",
                "input_price_usd_mtok",
                "output_price_usd_mtok",
                "volume_mtok_7d",
                "twap_output_usd_mtok",
                "twap_input_usd_mtok",
                "source",
                "submitted_at",
                "notes",
            ]
        ),
        rankings_df=pd.DataFrame(),
        registry=_registry_three_f(),
        tier_b_config=TierBRevenueConfig(entries=[]),
        contributors=_contributors_three(),
        scenarios_by_id={},
        range_start=date(2025, 1, 1),
        range_end=date(2025, 1, 5),
    )


def _ts() -> datetime:
    return datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# regenerate_panel_for_seed produces deterministic-per-seed outputs
# ---------------------------------------------------------------------------


def test_regenerate_panel_per_seed_deterministic() -> None:
    """Same seed → identical panel + events; different seeds → different output."""
    from tprr.sensitivity.multi_seed import regenerate_panel_for_seed

    inputs = _baseline_inputs_static()
    panel_a, events_a = regenerate_panel_for_seed(inputs=inputs, seed=42)
    panel_b, events_b = regenerate_panel_for_seed(inputs=inputs, seed=42)
    assert panel_a.equals(panel_b)
    assert events_a.equals(events_b)
    panel_c, _ = regenerate_panel_for_seed(inputs=inputs, seed=43)
    # Different seed must produce different prices on at least one row
    # (regenerated baseline + contributor noise are seeded).
    assert not panel_a.equals(panel_c)


# ---------------------------------------------------------------------------
# run_multi_seed_sweep: clean-panel only
# ---------------------------------------------------------------------------


def test_run_multi_seed_sweep_clean_panel_three_seeds(tmp_path: Path) -> None:
    inputs = _baseline_inputs_static()
    base_config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = build_clean_panel_runs(
        parameter_label="default",
        config=base_config,
        seeds=[42, 43, 44],
    )
    output_dir = tmp_path / "multi_seed"
    manifest_path = tmp_path / "manifest.csv"
    indices_path = run_multi_seed_sweep(
        sweep_id="ms_test_clean",
        sweep_kind="multi_seed",
        parameter_dim="seed_x_default",
        runs=runs,
        inputs_static=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        base_audit_id="multi_seed_default",
        timestamp=_ts(),
        progress=False,
    )
    assert indices_path.exists()
    df = pd.read_parquet(indices_path)
    assert {"sweep_id", "parameter_label", "seed", "panel_id"}.issubset(df.columns)
    assert sorted(df["seed"].unique().tolist()) == [42, 43, 44]
    assert (df["panel_id"] == "clean").all()
    assert (df["parameter_label"] == "default").all()


def test_multi_seed_sweep_manifest_telemetry(tmp_path: Path) -> None:
    inputs = _baseline_inputs_static()
    config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = build_clean_panel_runs(
        parameter_label="default",
        config=config,
        seeds=[42, 43, 44],
    )
    output_dir = tmp_path / "multi_seed"
    manifest_path = tmp_path / "manifest.csv"
    run_multi_seed_sweep(
        sweep_id="ms_telemetry",
        sweep_kind="multi_seed",
        parameter_dim="seed_x_default",
        runs=runs,
        inputs_static=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        base_audit_id="multi_seed_default",
        timestamp=_ts(),
        progress=False,
    )
    manifest = read_manifest(manifest_path)
    row = manifest.iloc[0]
    assert int(row["n_seeds"]) == 3
    assert int(row["seed_min"]) == 42
    assert int(row["seed_max"]) == 44
    assert int(row["n_runs"]) == 3
    assert pd.notna(row["pipeline_runtime_s"])
    assert float(row["pipeline_runtime_s"]) > 0.0
    assert pd.notna(row["n_active_constituents_at_base_date"])
    assert int(row["n_active_constituents_at_base_date"]) == 3  # 3 F constituents


def test_multi_seed_seed_in_output_distinguishes_runs(tmp_path: Path) -> None:
    """Different seeds produce non-identical panels → different IndexValueDF
    rows. ``seed`` column distinguishes."""
    inputs = _baseline_inputs_static()
    config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = build_clean_panel_runs(parameter_label="default", config=config, seeds=[42, 43])
    output_dir = tmp_path / "multi_seed"
    manifest_path = tmp_path / "manifest.csv"
    indices_path = run_multi_seed_sweep(
        sweep_id="ms_seed_distinguish",
        sweep_kind="multi_seed",
        parameter_dim="seed_x_default",
        runs=runs,
        inputs_static=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        base_audit_id="multi_seed_default",
        timestamp=_ts(),
        progress=False,
    )
    df = pd.read_parquet(indices_path)
    f = df[df["index_code"] == "TPRR_F"]
    pivot = f.pivot(index="as_of_date", columns="seed", values="raw_value_usd_mtok")
    diff = pivot[42] - pivot[43]
    # At least one date must differ — different seeds drive different panels.
    assert (diff.abs() > 1e-10).any()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def test_build_clean_panel_runs_label_and_seed_propagation() -> None:
    config = IndexConfig()
    runs = build_clean_panel_runs(parameter_label="loose", config=config, seeds=[42, 43, 44])
    assert [r.seed for r in runs] == [42, 43, 44]
    assert all(r.parameter_label == "loose" for r in runs)
    assert all(r.panel_id == "clean" for r in runs)
    assert all(r.scenario_id is None for r in runs)
    assert all(r.new_config is config for r in runs)


def test_build_clean_plus_scenario_runs_per_seed_grouping() -> None:
    """Each seed's clean run is followed by its scenario runs so the panel-
    regeneration cache reuses the panel within the seed group."""
    config = IndexConfig()
    runs = build_clean_plus_scenario_runs(
        parameter_label="default",
        config=config,
        seeds=[42, 43],
        scenario_ids=["fat_finger_high", "intraday_spike"],
    )
    assert len(runs) == 2 * (1 + 2)  # 2 seeds x (1 clean + 2 scenarios)
    expected = [
        (42, "clean", None),
        (42, "fat_finger_high", "fat_finger_high"),
        (42, "intraday_spike", "intraday_spike"),
        (43, "clean", None),
        (43, "fat_finger_high", "fat_finger_high"),
        (43, "intraday_spike", "intraday_spike"),
    ]
    actual = [(r.seed, r.panel_id, r.scenario_id) for r in runs]
    assert actual == expected


# ---------------------------------------------------------------------------
# Empty-runs rejection
# ---------------------------------------------------------------------------


def test_run_multi_seed_sweep_rejects_empty_runs(tmp_path: Path) -> None:
    inputs = _baseline_inputs_static()
    with pytest.raises(ValueError, match="runs list is empty"):
        run_multi_seed_sweep(
            sweep_id="x",
            sweep_kind="multi_seed",
            parameter_dim="seed_x_default",
            runs=[],
            inputs_static=inputs,
            output_dir=tmp_path / "out",
            manifest_path=tmp_path / "manifest.csv",
            base_audit_id="multi_seed_default",
            progress=False,
        )


def test_multi_seed_run_with_unknown_scenario_raises(tmp_path: Path) -> None:
    inputs = _baseline_inputs_static()
    config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = [
        MultiSeedRun(
            parameter_label="default",
            new_config=config,
            seed=42,
            panel_id="bogus",
            scenario_id="bogus_scenario",
        )
    ]
    with pytest.raises(KeyError, match="bogus_scenario"):
        run_multi_seed_sweep(
            sweep_id="ms_missing_scenario",
            sweep_kind="multi_seed",
            parameter_dim="seed_x_default",
            runs=runs,
            inputs_static=inputs,
            output_dir=tmp_path / "out",
            manifest_path=tmp_path / "manifest.csv",
            base_audit_id="multi_seed_default",
            progress=False,
        )
