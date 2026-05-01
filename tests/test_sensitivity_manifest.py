"""Tests for tprr.sensitivity.manifest — Phase 10 Batch 10A."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tprr.sensitivity.manifest import (
    MANIFEST_COLUMNS,
    read_manifest,
    upsert_manifest_row,
)


def _ts(year: int = 2026, month: int = 5, day: int = 1, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=UTC)


def _add_row(path: Path, *, sweep_id: str, ts: datetime, n_rows: int = 100) -> pd.DataFrame:
    return upsert_manifest_row(
        path,
        sweep_id=sweep_id,
        sweep_kind="lambda",
        parameter_dim="lambda",
        parameter_values=["1.0", "2.0", "3.0"],
        n_seeds=1,
        n_runs=3,
        seed_min=42,
        seed_max=42,
        output_path=f"data/indices/sweeps/lambda/{sweep_id}.parquet",
        base_audit_id="seed42_default",
        n_rows=n_rows,
        timestamp=ts,
    )


def test_read_manifest_missing_returns_empty_frame_with_columns(tmp_path: Path) -> None:
    df = read_manifest(tmp_path / "manifest.csv")
    assert df.empty
    assert tuple(df.columns) == MANIFEST_COLUMNS


def test_upsert_creates_file_and_appends_row(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    df = _add_row(path, sweep_id="lambda_seed42", ts=_ts())
    assert path.exists()
    assert len(df) == 1
    assert df["sweep_id"].iloc[0] == "lambda_seed42"
    assert df["parameter_values"].iloc[0] == "1.0,2.0,3.0"
    assert df["timestamp_utc"].iloc[0] == "2026-05-01T12:00:00Z"


def test_upsert_idempotent_replaces_existing_row(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    _add_row(path, sweep_id="lambda_seed42", ts=_ts(hour=10), n_rows=50)
    df = _add_row(path, sweep_id="lambda_seed42", ts=_ts(hour=14), n_rows=200)
    assert len(df) == 1
    assert df["n_rows"].iloc[0] == 200
    assert df["timestamp_utc"].iloc[0] == "2026-05-01T14:00:00Z"


def test_upsert_preserves_other_rows(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    _add_row(path, sweep_id="lambda_seed42", ts=_ts(hour=10))
    _add_row(path, sweep_id="haircut_seed42", ts=_ts(hour=11))
    df = _add_row(path, sweep_id="lambda_seed42", ts=_ts(hour=12), n_rows=999)
    assert len(df) == 2
    assert set(df["sweep_id"]) == {"lambda_seed42", "haircut_seed42"}
    lam_row = df[df["sweep_id"] == "lambda_seed42"].iloc[0]
    assert lam_row["n_rows"] == 999


def test_upsert_appends_new_rows_to_bottom(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    _add_row(path, sweep_id="first", ts=_ts(hour=10))
    _add_row(path, sweep_id="second", ts=_ts(hour=11))
    df = _add_row(path, sweep_id="third", ts=_ts(hour=12))
    assert list(df["sweep_id"]) == ["first", "second", "third"]


def test_read_manifest_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    pd.DataFrame({"sweep_id": ["x"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing required columns"):
        read_manifest(path)


def test_manifest_round_trip_via_disk(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    _add_row(path, sweep_id="a", ts=_ts(hour=10))
    df = read_manifest(path)
    assert tuple(df.columns) == MANIFEST_COLUMNS
    assert df.iloc[0]["sweep_id"] == "a"
    assert df.iloc[0]["seed_min"] == 42
