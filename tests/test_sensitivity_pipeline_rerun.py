"""Tests for tprr.sensitivity.pipeline_rerun — Phase 10 Batch 10B.

The pipeline-rerun sweep runner cannot be reduced to a pure recompute the
way Batch 10A's recompute is, because the parameters it sweeps
(suspension threshold, reinstatement threshold, gate threshold, TWAP
ordering) all change the audit row set. These tests exercise the
end-to-end rerun loop on small in-memory fixtures rather than the
seed-42 panel — the seed-42 fixture is a ~30-second pipeline run, too
slow for unit tests.

Coverage:
- Sweep runner produces well-formed indices + decisions parquets
- Manifest row includes Batch 10B telemetry fields (runtime, base-date
  active, suspension intervals, reinstatement events)
- ``build_threshold_runs`` and ``build_twap_ordering_runs`` produce the
  expected configs/labels
- Empirical: lower gate threshold (5%) triggers more slot exclusions
  than higher (25%) on a fixture with a 15% deviation event
- Empirical: ``twap_then_weight`` and ``weight_then_twap`` produce
  non-identical output on a fixture with an intraday change event
- Driver scripts importable + end-to-end smoke
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
    ScenarioEntry,
    TierBRevenueConfig,
    VolumeScale,
)
from tprr.schema import AttestationTier, Tier
from tprr.sensitivity.baseline import BaselineInputs
from tprr.sensitivity.manifest import read_manifest
from tprr.sensitivity.pipeline_rerun import (
    PipelineRerunRun,
    build_threshold_runs,
    build_twap_ordering_runs,
    run_pipeline_rerun_sweep,
)

# ---------------------------------------------------------------------------
# Fixtures — in-memory BaselineInputs avoiding disk loads
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


def _change_event(
    *,
    d: date,
    contrib: str,
    cid: str,
    slot: int,
    old_p: float,
    new_p: float,
) -> dict[str, Any]:
    return {
        "event_date": pd.Timestamp(d),
        "contributor_id": contrib,
        "constituent_id": cid,
        "change_slot_idx": int(slot),
        "old_input_price_usd_mtok": float(old_p / 5.0),
        "new_input_price_usd_mtok": float(new_p / 5.0),
        "old_output_price_usd_mtok": float(old_p),
        "new_output_price_usd_mtok": float(new_p),
        "reason": "test",
    }


def _baseline_inputs(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    *,
    range_start: date,
    range_end: date,
) -> BaselineInputs:
    return BaselineInputs(
        tier_a_panel=panel,
        change_events=events,
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
        contributors=ContributorPanel(
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
        ),
        scenarios_by_id={},
        range_start=range_start,
        range_end=range_end,
    )


def _ts() -> datetime:
    return datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Sweep runner produces well-formed outputs
# ---------------------------------------------------------------------------


def test_run_pipeline_rerun_sweep_writes_indices_and_decisions(tmp_path: Path) -> None:
    panel = _multi_day_clean_panel(n_days=5)
    inputs = _baseline_inputs(
        panel,
        _empty_change_events(),
        range_start=date(2025, 1, 1),
        range_end=date(2025, 1, 5),
    )
    base_config = IndexConfig(base_date=date(2025, 1, 1))
    runs = build_threshold_runs(
        base_config=base_config,
        parameter_dim="suspension_threshold_days",
        values=[2, 3],
    )
    output_dir = tmp_path / "sweep"
    manifest_path = tmp_path / "manifest.csv"
    indices_path = run_pipeline_rerun_sweep(
        sweep_id="susp_test",
        sweep_kind="suspension_threshold",
        parameter_dim="suspension_threshold_days",
        runs=runs,
        inputs=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        seed=42,
        base_audit_id="seed42_test",
        timestamp=_ts(),
        progress=False,
    )
    assert indices_path.exists()
    decisions_path = output_dir / "susp_test_decisions.parquet"
    assert decisions_path.exists()

    indices_df = pd.read_parquet(indices_path)
    assert {"sweep_id", "parameter_label", "panel_id"}.issubset(indices_df.columns)
    assert set(indices_df["parameter_label"]) == {
        "suspension_threshold_days=2",
        "suspension_threshold_days=3",
    }
    assert (indices_df["panel_id"] == "clean").all()


def test_run_pipeline_rerun_sweep_populates_manifest_telemetry(
    tmp_path: Path,
) -> None:
    panel = _multi_day_clean_panel(n_days=5)
    inputs = _baseline_inputs(
        panel,
        _empty_change_events(),
        range_start=date(2025, 1, 1),
        range_end=date(2025, 1, 5),
    )
    base_config = IndexConfig(base_date=date(2025, 1, 1))
    runs = build_threshold_runs(
        base_config=base_config,
        parameter_dim="suspension_threshold_days",
        values=[3],
    )
    output_dir = tmp_path / "sweep"
    manifest_path = tmp_path / "manifest.csv"
    run_pipeline_rerun_sweep(
        sweep_id="susp_telemetry_test",
        sweep_kind="suspension_threshold",
        parameter_dim="suspension_threshold_days",
        runs=runs,
        inputs=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        seed=42,
        base_audit_id="seed42_test",
        timestamp=_ts(),
        progress=False,
    )
    manifest = read_manifest(manifest_path)
    row = manifest.iloc[0]
    # Batch 10B telemetry columns populated.
    assert pd.notna(row["pipeline_runtime_s"])
    assert float(row["pipeline_runtime_s"]) > 0.0
    assert pd.notna(row["n_active_constituents_at_base_date"])
    assert int(row["n_active_constituents_at_base_date"]) == 3  # 3 F constituents
    # Clean panel + no events → no suspensions, no reinstatements.
    assert int(row["n_suspension_intervals"]) == 0
    assert int(row["n_reinstatement_events"]) == 0


def test_manifest_telemetry_remains_nan_for_in_memory_sweeps(
    tmp_path: Path,
) -> None:
    """Batch 10A in-memory sweeps don't populate the rerun-telemetry
    columns; reading the manifest after such a sweep returns NaN for
    those four columns even when the row is otherwise complete.
    """
    from tprr.sensitivity.manifest import upsert_manifest_row

    manifest_path = tmp_path / "manifest.csv"
    upsert_manifest_row(
        manifest_path,
        sweep_id="lambda_test",
        sweep_kind="lambda",
        parameter_dim="lambda",
        parameter_values=["1.0", "2.0", "3.0"],
        n_seeds=1,
        n_runs=3,
        seed_min=42,
        seed_max=42,
        output_path="x.parquet",
        base_audit_id="seed42_default",
        n_rows=100,
        timestamp=_ts(),
    )
    manifest = read_manifest(manifest_path)
    row = manifest.iloc[0]
    assert pd.isna(row["pipeline_runtime_s"])
    assert pd.isna(row["n_active_constituents_at_base_date"])
    assert pd.isna(row["n_suspension_intervals"])
    assert pd.isna(row["n_reinstatement_events"])


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def test_build_threshold_runs_suspension_labels() -> None:
    base = IndexConfig()
    runs = build_threshold_runs(
        base_config=base,
        parameter_dim="suspension_threshold_days",
        values=[2, 5, 7],
    )
    assert [r.parameter_label for r in runs] == [
        "suspension_threshold_days=2",
        "suspension_threshold_days=5",
        "suspension_threshold_days=7",
    ]
    assert [r.new_config.suspension_threshold_days for r in runs] == [2, 5, 7]
    assert all(r.scenario_id is None for r in runs)
    assert all(r.panel_id == "clean" for r in runs)


def test_build_threshold_runs_gate_pct_uses_two_decimals() -> None:
    base = IndexConfig()
    runs = build_threshold_runs(
        base_config=base,
        parameter_dim="quality_gate_pct",
        values=[0.05, 0.15, 0.30],
    )
    assert [r.parameter_label for r in runs] == [
        "quality_gate_pct=0.05",
        "quality_gate_pct=0.15",
        "quality_gate_pct=0.30",
    ]
    assert [r.new_config.quality_gate_pct for r in runs] == [0.05, 0.15, 0.30]


def test_build_twap_ordering_runs_cross_product() -> None:
    base = IndexConfig()
    runs = build_twap_ordering_runs(
        base_config=base,
        orderings=["twap_then_weight", "weight_then_twap"],
        panels=[("clean", None), ("scenario_x", "scenario_x")],
    )
    assert len(runs) == 4
    # All runs share the same base config — only ordering / panel differ.
    assert all(r.new_config is base for r in runs)
    labels = {r.parameter_label for r in runs}
    assert labels == {
        "ordering=twap_then_weight|panel=clean",
        "ordering=twap_then_weight|panel=scenario_x",
        "ordering=weight_then_twap|panel=clean",
        "ordering=weight_then_twap|panel=scenario_x",
    }
    # The clean panel runs have scenario_id None; scenario_x has it set.
    by_label = {r.parameter_label: r for r in runs}
    assert by_label["ordering=twap_then_weight|panel=clean"].scenario_id is None
    assert by_label["ordering=weight_then_twap|panel=scenario_x"].scenario_id == "scenario_x"


# ---------------------------------------------------------------------------
# Empirical sanity
# ---------------------------------------------------------------------------


def test_lower_gate_threshold_excludes_more_slots() -> None:
    """A 15% deviation event triggers gate=10% but not gate=25%."""
    panel = _multi_day_clean_panel(n_days=10, start=date(2025, 1, 1))
    # Add a 15% deviation event on c1's gpt-5-pro at slot 16 on day 10.
    events = pd.DataFrame(
        [
            _change_event(
                d=date(2025, 1, 10),
                contrib="c1",
                cid="openai/gpt-5-pro",
                slot=16,
                old_p=75.0,
                new_p=86.25,  # +15.0%
            )
        ]
    )
    inputs = _baseline_inputs(
        panel, events, range_start=date(2025, 1, 1), range_end=date(2025, 1, 10)
    )
    base_config = IndexConfig(base_date=date(2025, 1, 1))

    from tprr.sensitivity.baseline import run_pipeline_at_config

    pipeline_strict = run_pipeline_at_config(
        inputs, base_config.model_copy(update={"quality_gate_pct": 0.10})
    )
    pipeline_loose = run_pipeline_at_config(
        inputs, base_config.model_copy(update={"quality_gate_pct": 0.25})
    )
    # Strict gate (10%) catches the 15% deviation; loose (25%) does not.
    assert len(pipeline_strict.excluded_slots) > len(pipeline_loose.excluded_slots)


def test_twap_orderings_produce_non_identical_output() -> None:
    """With an intraday change event that creates within-day price
    dispersion, twap_then_weight and weight_then_twap produce different
    raw_value_usd_mtok on at least one day. (Identical-on-constant-prices
    is the boring degenerate; the test forces meaningful divergence.)"""
    panel = _multi_day_clean_panel(n_days=5, start=date(2025, 1, 1))
    events = pd.DataFrame(
        [
            _change_event(
                d=date(2025, 1, 3),
                contrib="c1",
                cid="openai/gpt-5-pro",
                slot=16,
                old_p=75.0,
                new_p=82.5,  # +10% mid-day
            ),
        ]
    )
    inputs = _baseline_inputs(
        panel, events, range_start=date(2025, 1, 1), range_end=date(2025, 1, 5)
    )
    config = IndexConfig(base_date=date(2025, 1, 1))

    from tprr.sensitivity.baseline import run_pipeline_at_config

    twap_then = run_pipeline_at_config(inputs, config, ordering="twap_then_weight")
    weight_then = run_pipeline_at_config(inputs, config, ordering="weight_then_twap")

    f_twap = twap_then.indices["TPRR_F"]["raw_value_usd_mtok"].to_numpy()
    f_weight = weight_then.indices["TPRR_F"]["raw_value_usd_mtok"].to_numpy()
    # At least one day must differ — orderings are mathematically distinct
    # under intra-day price changes that the gate doesn't filter out.
    assert not (f_twap == pytest.approx(f_weight, rel=1e-9, abs=1e-9))


# ---------------------------------------------------------------------------
# Empty-runs rejection
# ---------------------------------------------------------------------------


def test_run_pipeline_rerun_sweep_rejects_empty_runs(tmp_path: Path) -> None:
    inputs = _baseline_inputs(
        _multi_day_clean_panel(n_days=2),
        _empty_change_events(),
        range_start=date(2025, 1, 1),
        range_end=date(2025, 1, 2),
    )
    with pytest.raises(ValueError, match="runs list is empty"):
        run_pipeline_rerun_sweep(
            sweep_id="x",
            sweep_kind="suspension_threshold",
            parameter_dim="suspension_threshold_days",
            runs=[],
            inputs=inputs,
            output_dir=tmp_path / "out",
            manifest_path=tmp_path / "manifest.csv",
            seed=42,
            base_audit_id="seed42_test",
            progress=False,
        )


def test_pipeline_rerun_run_with_unknown_scenario_raises(tmp_path: Path) -> None:
    inputs = _baseline_inputs(
        _multi_day_clean_panel(n_days=2),
        _empty_change_events(),
        range_start=date(2025, 1, 1),
        range_end=date(2025, 1, 2),
    )
    runs = [
        PipelineRerunRun(
            parameter_label="x",
            new_config=IndexConfig(base_date=date(2025, 1, 1)),
            scenario_id="not_in_inputs",
        )
    ]
    with pytest.raises(KeyError, match="not_in_inputs"):
        run_pipeline_rerun_sweep(
            sweep_id="missing_scenario",
            sweep_kind="twap_ordering",
            parameter_dim="ordering_x_panel",
            runs=runs,
            inputs=inputs,
            output_dir=tmp_path / "out",
            manifest_path=tmp_path / "manifest.csv",
            seed=42,
            base_audit_id="seed42_test",
            progress=False,
        )
    # Unused import note: ScenarioEntry kept for type-completeness in future
    # tests that exercise the scenario path with valid inputs.
    _ = ScenarioEntry
