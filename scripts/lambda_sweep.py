"""Phase 10 Batch 10A — λ sensitivity sweep.

Sweeps λ ∈ [1, 2, 3, 5, 10] holding the canonical config otherwise. Recompute
runs in-memory off the seed-42 ConstituentDecisionDF audit (Phase 7H Batch
B long format), so total runtime is one full pipeline run (~30s) plus N
recomputes (~seconds each).

Output: ``data/indices/sweeps/lambda/lambda_sweep_seed{S}.parquet`` +
manifest row in ``data/indices/sweeps/manifest.csv``.

Usage:
    uv run python scripts/lambda_sweep.py [--seed 42] [--start YYYY-MM-DD]
        [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tprr.sensitivity.baseline import load_baseline
from tprr.sensitivity.recompute import with_overrides
from tprr.sensitivity.sweep import SweepRun, run_in_memory_sweep

LAMBDA_VALUES: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0, 10.0)


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

    print(f"Loading baseline pipeline (seed={args.seed})...", flush=True)
    pipeline, base_config = load_baseline(seed=args.seed, start=start, end=end)
    print(
        f"  baseline: {len(pipeline.constituent_decisions):,} audit rows, "
        f"{sum(len(df) for df in pipeline.indices.values()):,} index rows",
        flush=True,
    )

    runs = [
        SweepRun(
            parameter_label=f"lambda={lam:g}",
            new_config=with_overrides(base_config, lambda_=lam),
        )
        for lam in LAMBDA_VALUES
    ]
    sweep_id = f"lambda_seed{args.seed}"
    output_root = Path(args.output_root)
    output_path = run_in_memory_sweep(
        sweep_id=sweep_id,
        sweep_kind="lambda",
        parameter_dim="lambda",
        runs=runs,
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        output_dir=output_root / "lambda",
        manifest_path=output_root / "manifest.csv",
        seed=args.seed,
        base_audit_id=f"seed{args.seed}_default",
    )
    print(f"Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
