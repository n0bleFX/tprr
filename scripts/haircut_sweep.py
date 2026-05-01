"""Phase 10 Batch 10A — Tier B haircut sensitivity sweep.

Sweeps Tier B confidence haircut ∈ [0.4, 0.5, 0.6, 0.7] holding Tier A at
1.0 and Tier C at 0.8 fixed (the canonical Phase 7H Batch C calibration is
0.5; this sweep brackets it). All other config values match the canonical
run.

Recompute runs in-memory off the seed-42 ConstituentDecisionDF audit; the
haircut affects ``w_vol_contribution = coefficient x within_tier_share x
haircut`` per tier but not constituent prices, so within-tier shares and
tier-collapsed prices from the audit recombine without a pipeline rerun.

Output: ``data/indices/sweeps/tier_b_haircut/haircut_sweep_seed{S}.parquet``
+ manifest row in ``data/indices/sweeps/manifest.csv``.

Usage:
    uv run python scripts/haircut_sweep.py [--seed 42] [--start YYYY-MM-DD]
        [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tprr.schema import AttestationTier
from tprr.sensitivity.baseline import load_baseline
from tprr.sensitivity.recompute import with_overrides
from tprr.sensitivity.sweep import SweepRun, run_in_memory_sweep

TIER_B_HAIRCUT_VALUES: tuple[float, ...] = (0.4, 0.5, 0.6, 0.7)


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
            parameter_label=f"haircut_b={h:g}",
            new_config=with_overrides(
                base_config,
                tier_haircuts={
                    AttestationTier.A: 1.0,
                    AttestationTier.B: h,
                    AttestationTier.C: 0.8,
                },
            ),
        )
        for h in TIER_B_HAIRCUT_VALUES
    ]
    sweep_id = f"haircut_seed{args.seed}"
    output_root = Path(args.output_root)
    output_path = run_in_memory_sweep(
        sweep_id=sweep_id,
        sweep_kind="tier_b_haircut",
        parameter_dim="tier_b_haircut",
        runs=runs,
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        output_dir=output_root / "tier_b_haircut",
        manifest_path=output_root / "manifest.csv",
        seed=args.seed,
        base_audit_id=f"seed{args.seed}_default",
    )
    print(f"Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
