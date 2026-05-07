"""Tests for tprr.sensitivity.multi_seed gate x scenarios x seeds builder.

Phase 11 Batch 11A — gate x scenarios x seeds cross-product. Tests verify:

- Run-count semantics (gates x seeds x (1 + n_scenarios))
- parameter_label format (``f"gate={int(v*100)}pct"``)
- Per-gate IndexConfig has the right ``quality_gate_pct``
- Panel-regeneration caching: regenerations = unique seeds, NOT seeds x gates
- Cross-parquet schema consistency (Session 1 + Session 2 outputs concat cleanly)

Caching test is the load-bearing one for the ~8-hour compute budget.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

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
from tprr.sensitivity import multi_seed as ms
from tprr.sensitivity.baseline import BaselineInputs
from tprr.sensitivity.multi_seed import (
    build_gate_x_scenario_runs,
    run_multi_seed_sweep,
)

# ---------------------------------------------------------------------------
# Tiny in-memory fixture (mirrors test_sensitivity_multi_seed.py)
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
                    _row(cid=cid, contrib=c, d=d, twap_out=p_out, twap_in=p_in, volume=100.0)
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
    return datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Builder semantics
# ---------------------------------------------------------------------------


def test_build_gate_x_scenario_runs_count() -> None:
    """Run count = gates x seeds x (1 + n_scenarios)."""
    base_config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=[0.05, 0.15],
        seeds=[42, 43, 44],
        scenario_ids=["scen_a", "scen_b"],
    )
    # 2 gates x 3 seeds x (1 clean + 2 scenarios) = 18
    assert len(runs) == 18


def test_build_gate_x_scenario_runs_label_format() -> None:
    """parameter_label format: f'gate={int(v*100)}pct'."""
    base_config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=[0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        seeds=[42],
        scenario_ids=[],
    )
    labels = [r.parameter_label for r in runs]
    assert labels == [
        "gate=5pct",
        "gate=10pct",
        "gate=15pct",
        "gate=20pct",
        "gate=25pct",
        "gate=30pct",
    ]


def test_build_gate_x_scenario_runs_distinct_gate_configs() -> None:
    """Each gate value produces a config with the right quality_gate_pct."""
    base_config = IndexConfig(
        base_date=date(2025, 1, 1),
        backtest_start=date(2025, 1, 1),
        quality_gate_pct=0.15,
    )
    runs = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=[0.05, 0.15, 0.30],
        seeds=[42],
        scenario_ids=[],
    )
    assert len(runs) == 3
    assert [r.new_config.quality_gate_pct for r in runs] == [0.05, 0.15, 0.30]
    # Other config fields preserved.
    for r in runs:
        assert r.new_config.base_date == date(2025, 1, 1)


# ---------------------------------------------------------------------------
# Caching: panel regenerations = unique seeds, not seeds x gates
# ---------------------------------------------------------------------------


def test_panel_regeneration_cached_across_gates(tmp_path: Path) -> None:
    """Critical caching test for the ~8-hour compute budget.

    With 2 gates x 2 seeds x 1 scenario = 8 runs total. Per-seed cache in
    ``run_multi_seed_sweep`` should regenerate each seed's panel exactly
    once, regardless of how many gates re-use that seed. Expected
    regeneration count: 2 (= unique seed count).
    """
    inputs = _baseline_inputs_static()
    base_config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    runs = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=[0.05, 0.15],
        seeds=[42, 43],
        scenario_ids=[],
    )
    # 2 gates x 2 seeds x 1 panel (clean only) = 4 runs total
    assert len(runs) == 4

    call_count = {"n": 0}
    original = ms._inputs_for_seed

    def counting_wrapper(inputs_static_arg: BaselineInputs, seed: int) -> BaselineInputs:
        call_count["n"] += 1
        return original(inputs_static_arg, seed)

    output_dir = tmp_path / "multi_seed"
    manifest_path = tmp_path / "manifest.csv"

    with patch.object(ms, "_inputs_for_seed", counting_wrapper):
        run_multi_seed_sweep(
            sweep_id="test_gate_caching",
            sweep_kind="gate_x_scenarios_x_seeds",
            parameter_dim="gate_x_seed",
            runs=runs,
            inputs_static=inputs,
            output_dir=output_dir,
            manifest_path=manifest_path,
            base_audit_id="test_gate_caching",
            timestamp=_ts(),
            progress=False,
        )

    # 2 unique seeds → 2 regenerations expected. NOT 4 (= seeds x gates).
    assert call_count["n"] == 2, (
        f"Panel regeneration count = {call_count['n']}; expected 2 (unique seed count). "
        f"Caching is broken: each (seed, gate) pair is regenerating its own panel."
    )


# ---------------------------------------------------------------------------
# Cross-parquet schema consistency (Session 1 + Session 2 concat-compatible)
# ---------------------------------------------------------------------------


def test_cross_parquet_schema_consistency(tmp_path: Path) -> None:
    """Two driver invocations produce concat-compatible parquets.

    Session 2 analysis loads both Session 1 (gates 5/10/15) and Session 2
    (gates 20/25/30) parquets and concatenates them for cross-gate
    analysis. Schema/dtype mismatch would break the analysis.
    """
    inputs = _baseline_inputs_static()
    base_config = IndexConfig(base_date=date(2025, 1, 1), backtest_start=date(2025, 1, 1))
    output_dir = tmp_path / "multi_seed"
    manifest_path = tmp_path / "manifest.csv"

    runs1 = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=[0.05],
        seeds=[42],
        scenario_ids=[],
    )
    path1 = run_multi_seed_sweep(
        sweep_id="test_session1",
        sweep_kind="gate_x_scenarios_x_seeds",
        parameter_dim="gate_x_seed",
        runs=runs1,
        inputs_static=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        base_audit_id="test_session1",
        timestamp=_ts(),
        progress=False,
    )

    runs2 = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=[0.10],
        seeds=[42],
        scenario_ids=[],
    )
    path2 = run_multi_seed_sweep(
        sweep_id="test_session2",
        sweep_kind="gate_x_scenarios_x_seeds",
        parameter_dim="gate_x_seed",
        runs=runs2,
        inputs_static=inputs,
        output_dir=output_dir,
        manifest_path=manifest_path,
        base_audit_id="test_session2",
        timestamp=_ts(),
        progress=False,
    )

    df1 = pd.read_parquet(path1)
    df2 = pd.read_parquet(path2)

    # Column lists must match.
    assert list(df1.columns) == list(df2.columns), (
        f"Column lists differ: {list(df1.columns)} vs {list(df2.columns)}"
    )
    # Dtypes must match column-by-column.
    for col in df1.columns:
        assert df1[col].dtype == df2[col].dtype, (
            f"Column {col!r} dtype mismatch: {df1[col].dtype} vs {df2[col].dtype}"
        )
    # Concat round-trip preserves row count.
    combined = pd.concat([df1, df2], ignore_index=True)
    assert len(combined) == len(df1) + len(df2)
    assert set(combined["parameter_label"].unique()) == {"gate=5pct", "gate=10pct"}
