"""Phase 10 Batch 10B — TWAP ordering comparison sweep.

Runs both ``twap_then_weight`` (canonical, DL 2026-04-30 Phase 7 Batch E
Q1) and ``weight_then_twap`` (alternate ordering for comparison) against
the clean panel + 6 representative scenarios (the same 6 surfaced in
Phase 9 Batch D's dashboard panels). 2 orderings x 7 panels = 14
pipeline runs.

The output parquet has one row per (date, index_code, ordering, panel)
so Phase 10 synthesis can pivot ordering against panel for difference
analysis. ``parameter_label`` encodes ``ordering=X|panel=Y``.

Output:
- ``data/indices/sweeps/twap_ordering/sweep_twap_ordering_seed{S}.parquet``
- ``data/indices/sweeps/twap_ordering/sweep_twap_ordering_seed{S}_decisions.parquet``
- Manifest row in ``data/indices/sweeps/manifest.csv``.

Usage:
    uv run python scripts/twap_ordering_sweep.py [--seed 42]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tprr.config import load_index_config
from tprr.sensitivity.baseline import load_pipeline_inputs
from tprr.sensitivity.pipeline_rerun import (
    build_twap_ordering_runs,
    run_pipeline_rerun_sweep,
)

ORDERINGS: tuple[str, ...] = ("twap_then_weight", "weight_then_twap")

# Same 6 scenarios surfaced in Phase 9 Batch D dashboard panels —
# fat_finger / intraday / blackout / stale_quote / shock_price_cut /
# sustained_manipulation. Plus the clean panel as the baseline.
PANELS: tuple[tuple[str, str | None], ...] = (
    ("clean", None),
    ("fat_finger_high", "fat_finger_high"),
    ("intraday_spike", "intraday_spike"),
    ("correlated_blackout", "correlated_blackout"),
    ("stale_quote", "stale_quote"),
    ("shock_price_cut", "shock_price_cut"),
    ("sustained_manipulation", "sustained_manipulation"),
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

    print(f"Loading pipeline inputs (seed={args.seed})...", flush=True)
    inputs = load_pipeline_inputs(seed=args.seed, start=start, end=end)
    base_config = load_index_config()
    print(
        f"  inputs ready  |  range {inputs.range_start} -> {inputs.range_end}  |  "
        f"{len(inputs.tier_a_panel):,} Tier A rows  |  "
        f"{len(inputs.scenarios_by_id)} scenarios available",
        flush=True,
    )

    runs = build_twap_ordering_runs(
        base_config=base_config,
        orderings=list(ORDERINGS),
        panels=list(PANELS),
    )
    sweep_id = f"twap_ordering_seed{args.seed}"
    output_root = Path(args.output_root)
    output_path = run_pipeline_rerun_sweep(
        sweep_id=sweep_id,
        sweep_kind="twap_ordering",
        parameter_dim="ordering_x_panel",
        runs=runs,
        inputs=inputs,
        output_dir=output_root / "twap_ordering",
        manifest_path=output_root / "manifest.csv",
        seed=args.seed,
        base_audit_id=f"seed{args.seed}_default",
    )
    print(f"Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
