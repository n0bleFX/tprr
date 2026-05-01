"""Sweep runner — executes a list of parameter overrides and persists results.

A "sweep" here is a sequence of recomputes against a fixed input audit, one
per parameter point. The runner concatenates every recompute's IndexValueDF
output into a single long-format parquet keyed by ``sweep_id`` and
``parameter_label``, then upserts a manifest row pointing at it.

The runner is intentionally pure of file I/O policy beyond the parquet
write + manifest upsert; ``output_dir`` and ``manifest_path`` are caller
choices. Driver scripts in ``scripts/`` set them to
``data/indices/sweeps/{kind}/`` and ``data/indices/sweeps/manifest.csv``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from tprr.config import IndexConfig
from tprr.sensitivity.manifest import upsert_manifest_row
from tprr.sensitivity.recompute import recompute_indices_under_override


@dataclass(frozen=True)
class SweepRun:
    """One parameter point in a sweep.

    ``parameter_label`` is the human-readable identifier surfaced in the
    output parquet's ``parameter_label`` column (e.g. ``"lambda=2.0"``).
    Phase 11 writeup queries on this column to slice the parquet.
    """

    parameter_label: str
    new_config: IndexConfig


def run_in_memory_sweep(
    *,
    sweep_id: str,
    sweep_kind: str,
    parameter_dim: str,
    runs: list[SweepRun],
    constituent_decisions: pd.DataFrame,
    original_indices: dict[str, pd.DataFrame],
    output_dir: Path,
    manifest_path: Path,
    seed: int,
    base_audit_id: str,
    timestamp: datetime | None = None,
) -> Path:
    """Run a sequence of single-parameter recomputes and persist as one parquet.

    Each run's per-(date, index_code) IndexValueDF rows are tagged with
    ``sweep_id`` + ``parameter_label`` and concatenated. The output parquet
    file at ``{output_dir}/{sweep_id}.parquet`` contains the full sweep;
    the manifest row at ``manifest_path`` indexes it.

    ``seed`` is recorded in both ``seed_min`` and ``seed_max`` for
    in-memory single-seed sweeps; multi-seed sweeps from Batch 10C use
    the same runner with different seed semantics.
    """
    if not runs:
        raise ValueError("run_in_memory_sweep: runs list is empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{sweep_id}.parquet"

    all_rows: list[pd.DataFrame] = []
    for run in runs:
        recomputed = recompute_indices_under_override(
            constituent_decisions=constituent_decisions,
            original_indices=original_indices,
            new_config=run.new_config,
        )
        for df in recomputed.values():
            if df.empty:
                continue
            tagged = df.copy()
            tagged["sweep_id"] = sweep_id
            tagged["parameter_label"] = run.parameter_label
            all_rows.append(tagged)

    if not all_rows:
        raise ValueError(f"run_in_memory_sweep: every run produced empty output for {sweep_id!r}")
    out = pd.concat(all_rows, ignore_index=True)
    out.to_parquet(output_path)

    upsert_manifest_row(
        manifest_path,
        sweep_id=sweep_id,
        sweep_kind=sweep_kind,
        parameter_dim=parameter_dim,
        parameter_values=[r.parameter_label for r in runs],
        n_seeds=1,
        n_runs=len(runs),
        seed_min=seed,
        seed_max=seed,
        output_path=str(output_path).replace("\\", "/"),
        base_audit_id=base_audit_id,
        n_rows=len(out),
        timestamp=timestamp,
    )
    return output_path
