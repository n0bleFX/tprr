"""Tests for tprr.sensitivity.sweep — Phase 10 Batch 10A.

Verifies the end-to-end sweep contract: parquet output is well-formed
long-format with ``sweep_id`` / ``parameter_label`` columns; manifest is
upserted; reruns are idempotent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tprr.config import (
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
)
from tprr.index.compute import run_full_pipeline
from tprr.index.weights import TierBVolumeFn
from tprr.schema import AttestationTier, Tier
from tprr.sensitivity.manifest import read_manifest
from tprr.sensitivity.recompute import with_overrides
from tprr.sensitivity.sweep import SweepRun, run_in_memory_sweep


def _registry() -> ModelRegistry:
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=p_in,
                baseline_output_price_usd_mtok=p_out,
            )
            for cid, tier, p_in, p_out in [
                ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
                ("anthropic/claude-opus-4-7", Tier.TPRR_F, 14.0, 70.0),
                ("google/gemini-3-pro", Tier.TPRR_F, 5.0, 30.0),
                ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
                ("anthropic/claude-haiku-4-5", Tier.TPRR_S, 1.0, 5.0),
                ("google/gemini-2-flash", Tier.TPRR_S, 0.3, 2.5),
                ("google/gemini-flash-lite", Tier.TPRR_E, 0.1, 0.4),
                ("openai/gpt-5-nano", Tier.TPRR_E, 0.15, 0.6),
                ("deepseek/deepseek-v3-2", Tier.TPRR_E, 0.25, 1.0),
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
    tier: Tier,
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


def _multi_tier_panel() -> pd.DataFrame:
    start = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    f_set = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    s_set = [
        ("openai/gpt-5-mini", 4.0, 0.5),
        ("anthropic/claude-haiku-4-5", 5.0, 1.0),
        ("google/gemini-2-flash", 2.5, 0.3),
    ]
    e_set = [
        ("google/gemini-flash-lite", 0.4, 0.1),
        ("openai/gpt-5-nano", 0.6, 0.15),
        ("deepseek/deepseek-v3-2", 1.0, 0.25),
    ]
    for offset in range(5):
        d = start + timedelta(days=offset)
        for tier_set, tier in [
            (f_set, Tier.TPRR_F),
            (s_set, Tier.TPRR_S),
            (e_set, Tier.TPRR_E),
        ]:
            for cid, p_out, p_in in tier_set:
                for contrib in ["c1", "c2", "c3"]:
                    rows.append(
                        _row(
                            cid=cid,
                            contrib=contrib,
                            d=d,
                            twap_out=p_out,
                            twap_in=p_in,
                            volume=100.0,
                            tier=tier,
                        )
                    )
    return pd.DataFrame(rows)


def _stub_volume_fn(value: float = 0.0) -> TierBVolumeFn:
    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return value

    return _fn


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


def _build_pipeline_inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = _multi_tier_panel()
    pipeline = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=config,
        registry=_registry(),
        tier_b_config=TierBRevenueConfig(entries=[]),
        tier_b_volume_fn=_stub_volume_fn(0.0),
    )
    return pipeline.constituent_decisions, pipeline.indices


def _ts() -> datetime:
    return datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def test_run_in_memory_sweep_writes_parquet_and_manifest(tmp_path: Path) -> None:
    audit, indices = _build_pipeline_inputs()
    config = IndexConfig(base_date=date(2025, 1, 1))
    runs = [
        SweepRun(parameter_label=f"lambda={lam}", new_config=with_overrides(config, lambda_=lam))
        for lam in (1.0, 3.0, 5.0)
    ]
    output_dir = tmp_path / "lambda"
    manifest_path = tmp_path / "manifest.csv"
    output_path = run_in_memory_sweep(
        sweep_id="lambda_seed42",
        sweep_kind="lambda",
        parameter_dim="lambda",
        runs=runs,
        constituent_decisions=audit,
        original_indices=indices,
        output_dir=output_dir,
        manifest_path=manifest_path,
        seed=42,
        base_audit_id="seed42_default",
        timestamp=_ts(),
    )
    assert output_path.exists()
    df = pd.read_parquet(output_path)
    assert "sweep_id" in df.columns
    assert "parameter_label" in df.columns
    assert set(df["parameter_label"]) == {"lambda=1.0", "lambda=3.0", "lambda=5.0"}
    # 8 indices x 5 days x 3 runs = 120 rows
    expected_rows = sum(len(indices[code]) for code in indices) * len(runs)
    assert len(df) == expected_rows

    manifest = read_manifest(manifest_path)
    assert len(manifest) == 1
    row = manifest.iloc[0]
    assert row["sweep_id"] == "lambda_seed42"
    assert row["sweep_kind"] == "lambda"
    assert row["n_runs"] == 3
    assert row["n_rows"] == expected_rows
    assert row["output_path"].endswith("lambda_seed42.parquet")


def test_run_in_memory_sweep_idempotent(tmp_path: Path) -> None:
    audit, indices = _build_pipeline_inputs()
    config = IndexConfig(base_date=date(2025, 1, 1))
    runs = [
        SweepRun(
            parameter_label=f"lambda={lam}",
            new_config=with_overrides(config, lambda_=lam),
        )
        for lam in (1.0, 3.0)
    ]
    output_dir = tmp_path / "lambda"
    manifest_path = tmp_path / "manifest.csv"
    for _ in range(2):
        run_in_memory_sweep(
            sweep_id="lambda_seed42",
            sweep_kind="lambda",
            parameter_dim="lambda",
            runs=runs,
            constituent_decisions=audit,
            original_indices=indices,
            output_dir=output_dir,
            manifest_path=manifest_path,
            seed=42,
            base_audit_id="seed42_default",
            timestamp=_ts(),
        )
    manifest = read_manifest(manifest_path)
    assert len(manifest) == 1


def test_run_in_memory_sweep_rejects_empty_runs(tmp_path: Path) -> None:
    audit, indices = _build_pipeline_inputs()
    with pytest.raises(ValueError, match="runs list is empty"):
        run_in_memory_sweep(
            sweep_id="x",
            sweep_kind="lambda",
            parameter_dim="lambda",
            runs=[],
            constituent_decisions=audit,
            original_indices=indices,
            output_dir=tmp_path / "out",
            manifest_path=tmp_path / "manifest.csv",
            seed=42,
            base_audit_id="seed42_default",
        )


def test_run_in_memory_sweep_two_kinds_share_manifest(tmp_path: Path) -> None:
    """One manifest can hold rows from multiple sweep kinds."""
    audit, indices = _build_pipeline_inputs()
    config = IndexConfig(base_date=date(2025, 1, 1))
    manifest_path = tmp_path / "manifest.csv"
    run_in_memory_sweep(
        sweep_id="lambda_seed42",
        sweep_kind="lambda",
        parameter_dim="lambda",
        runs=[
            SweepRun(
                parameter_label=f"lambda={lam}",
                new_config=with_overrides(config, lambda_=lam),
            )
            for lam in (1.0, 3.0)
        ],
        constituent_decisions=audit,
        original_indices=indices,
        output_dir=tmp_path / "lambda",
        manifest_path=manifest_path,
        seed=42,
        base_audit_id="seed42_default",
        timestamp=_ts(),
    )
    run_in_memory_sweep(
        sweep_id="haircut_seed42",
        sweep_kind="tier_b_haircut",
        parameter_dim="tier_b_haircut",
        runs=[
            SweepRun(
                parameter_label=f"haircut_b={h}",
                new_config=with_overrides(
                    config,
                    tier_haircuts={
                        AttestationTier.A: 1.0,
                        AttestationTier.B: h,
                        AttestationTier.C: 0.8,
                    },
                ),
            )
            for h in (0.4, 0.5)
        ],
        constituent_decisions=audit,
        original_indices=indices,
        output_dir=tmp_path / "tier_b_haircut",
        manifest_path=manifest_path,
        seed=42,
        base_audit_id="seed42_default",
        timestamp=_ts(),
    )
    manifest = read_manifest(manifest_path)
    assert len(manifest) == 2
    assert set(manifest["sweep_kind"]) == {"lambda", "tier_b_haircut"}
