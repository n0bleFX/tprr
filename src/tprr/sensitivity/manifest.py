"""Manifest CSV catalogue for Phase 10 parameter sweeps.

The manifest is the navigable index of every sweep run that has produced a
parquet under ``data/indices/sweeps/``. Phase 11 writeup queries this CSV
to locate the sweep output backing each finding. The natural key is
``sweep_id`` — derived deterministically from
``(sweep_kind, base_audit_id)`` so reruns upsert in place.

CSV chosen over parquet for human readability: the manifest is small
(O(10s of rows for v0.1), columns are scalar), and a CSV opens cleanly in
git diffs / spreadsheets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

MANIFEST_COLUMNS: tuple[str, ...] = (
    "sweep_id",
    "sweep_kind",
    "parameter_dim",
    "parameter_values",
    "n_seeds",
    "n_runs",
    "seed_min",
    "seed_max",
    "output_path",
    "base_audit_id",
    "timestamp_utc",
    "n_rows",
)


def read_manifest(path: Path) -> pd.DataFrame:
    """Read the manifest CSV at ``path``, returning an empty DataFrame with
    the canonical column order if the file does not yet exist.
    """
    if not path.exists():
        return pd.DataFrame({col: pd.Series(dtype="object") for col in MANIFEST_COLUMNS})
    df = pd.read_csv(path)
    missing = [c for c in MANIFEST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"manifest at {path}: missing required columns: {missing}")
    return df[list(MANIFEST_COLUMNS)]


def upsert_manifest_row(
    path: Path,
    *,
    sweep_id: str,
    sweep_kind: str,
    parameter_dim: str,
    parameter_values: list[str],
    n_seeds: int,
    n_runs: int,
    seed_min: int,
    seed_max: int,
    output_path: str,
    base_audit_id: str,
    n_rows: int,
    timestamp: datetime | None = None,
) -> pd.DataFrame:
    """Upsert one row keyed by ``sweep_id``.

    Reruns at the same ``sweep_id`` replace the existing row. Order of
    surviving rows is preserved (existing-then-new), so successive sweeps
    add to the bottom of the manifest. ``timestamp`` defaults to ``now()``
    in UTC; explicit value is for tests.
    """
    df = read_manifest(path)
    if not df.empty:
        df = df[df["sweep_id"] != sweep_id].reset_index(drop=True)
    ts = timestamp if timestamp is not None else datetime.now(UTC)
    new_row = {
        "sweep_id": sweep_id,
        "sweep_kind": sweep_kind,
        "parameter_dim": parameter_dim,
        "parameter_values": ",".join(parameter_values),
        "n_seeds": int(n_seeds),
        "n_runs": int(n_runs),
        "seed_min": int(seed_min),
        "seed_max": int(seed_max),
        "output_path": output_path,
        "base_audit_id": base_audit_id,
        "timestamp_utc": ts.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "n_rows": int(n_rows),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df
