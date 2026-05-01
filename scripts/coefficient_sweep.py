"""Phase 10 Batch 10A — blending-coefficient sensitivity sweep.

Sweeps tier blending coefficients across four variants holding canonical
config otherwise:

- ``default``: A=0.6 / C=0.3 / B=0.1 (Phase 7H Batch B locked default)
- ``balanced_C``: A=0.5 / C=0.35 / B=0.15 (smaller A weight, larger C, small B)
- ``A_dominant``: A=0.7 / C=0.20 / B=0.10 (A pushed up; B and C compressed)
- ``BC_equal``: A=0.6 / C=0.20 / B=0.20 (Tier B and C equal weight; tests
  the Phase 7H Batch C "Tier C above Tier B" ordering claim)

Coefficient changes affect both ``constituent_price = sum(coef x tier_price)``
and ``w_vol_contribution = coef x share x haircut``, so the recompute
re-derives constituent prices, tier medians, ``w_exp``, and the final
weight aggregates from the audit's per-tier collapsed prices.

Output: ``data/indices/sweeps/blending_coefficient/coefficient_sweep_seed{S}.parquet``
+ manifest row in ``data/indices/sweeps/manifest.csv``.

Usage:
    uv run python scripts/coefficient_sweep.py [--seed 42] [--start YYYY-MM-DD]
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

COEFFICIENT_VARIANTS: tuple[tuple[str, dict[AttestationTier, float]], ...] = (
    (
        "default",
        {AttestationTier.A: 0.6, AttestationTier.C: 0.3, AttestationTier.B: 0.1},
    ),
    (
        "balanced_C",
        {AttestationTier.A: 0.5, AttestationTier.C: 0.35, AttestationTier.B: 0.15},
    ),
    (
        "A_dominant",
        {AttestationTier.A: 0.7, AttestationTier.C: 0.2, AttestationTier.B: 0.1},
    ),
    (
        "BC_equal",
        {AttestationTier.A: 0.6, AttestationTier.C: 0.2, AttestationTier.B: 0.2},
    ),
)


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
            parameter_label=label,
            new_config=with_overrides(base_config, tier_blending_coefficients=coefs),
        )
        for label, coefs in COEFFICIENT_VARIANTS
    ]
    sweep_id = f"coefficient_seed{args.seed}"
    output_root = Path(args.output_root)
    output_path = run_in_memory_sweep(
        sweep_id=sweep_id,
        sweep_kind="blending_coefficient",
        parameter_dim="blending_coefficient",
        runs=runs,
        constituent_decisions=pipeline.constituent_decisions,
        original_indices=pipeline.indices,
        output_dir=output_root / "blending_coefficient",
        manifest_path=output_root / "manifest.csv",
        seed=args.seed,
        base_audit_id=f"seed{args.seed}_default",
    )
    print(f"Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
