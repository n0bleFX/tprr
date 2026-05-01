"""Phase 10 Batch 10B — suspension threshold sensitivity sweep.

Sweeps ``suspension_threshold_days`` in [2, 3, 5, 7] holding all other
config at canonical defaults (reinstatement_threshold_days=10,
quality_gate_pct=0.15, default ordering twap_then_weight). Runs the
full pipeline per parameter point — the suspension counter operates on
slot-level gate firings cumulatively, so the audit shape changes between
runs and the in-memory recompute path from Batch 10A is not applicable.

Output:
- ``data/indices/sweeps/suspension_threshold/sweep_suspension_seed{S}.parquet``
- ``data/indices/sweeps/suspension_threshold/sweep_suspension_seed{S}_decisions.parquet``
- Manifest row in ``data/indices/sweeps/manifest.csv`` with Batch 10B
  telemetry (median runtime, base_date n_active, suspension intervals,
  reinstatement events).

Usage:
    uv run python scripts/suspension_sweep.py [--seed 42]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tprr.config import load_index_config
from tprr.sensitivity.baseline import load_pipeline_inputs
from tprr.sensitivity.pipeline_rerun import (
    build_threshold_runs,
    run_pipeline_rerun_sweep,
)

SUSPENSION_THRESHOLD_VALUES: tuple[int, ...] = (2, 3, 5, 7)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--output-root", type=str, default="data/indices/sweeps")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(f"Loading pipeline inputs (seed={args.seed})...", flush=True)
    inputs = load_pipeline_inputs(seed=args.seed, start=start, end=end)
    base_config = load_index_config()
    print(
        f"  inputs ready  |  range {inputs.range_start} -> {inputs.range_end}  |  "
        f"{len(inputs.tier_a_panel):,} Tier A rows",
        flush=True,
    )

    runs = build_threshold_runs(
        base_config=base_config,
        parameter_dim="suspension_threshold_days",
        values=list(SUSPENSION_THRESHOLD_VALUES),
    )
    sweep_id = f"suspension_seed{args.seed}"
    output_root = Path(args.output_root)
    output_path = run_pipeline_rerun_sweep(
        sweep_id=sweep_id,
        sweep_kind="suspension_threshold",
        parameter_dim="suspension_threshold_days",
        runs=runs,
        inputs=inputs,
        output_dir=output_root / "suspension_threshold",
        manifest_path=output_root / "manifest.csv",
        seed=args.seed,
        base_audit_id=f"seed{args.seed}_default",
    )
    print(f"Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
