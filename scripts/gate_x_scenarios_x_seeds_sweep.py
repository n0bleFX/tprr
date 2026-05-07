"""Phase 11 Batch 11A — gate x scenarios x seeds cross-product driver.

Strengthens the F-tier scenario absorption finding's scope clause by
testing whether absorption holds across the upstream gate-threshold
parameter (which Batch 10C did NOT sweep against scenarios).

For each gate value x seed x panel (clean + N scenarios), runs the
canonical default-config pipeline. Per-seed panel regeneration is
cached in ``run_multi_seed_sweep`` so each seed's panel is regenerated
exactly once across all gate values.

Output:
- ``data/indices/sweeps/multi_seed/gate_x_scenarios_seed{lo}-{hi}_gates_{labels}.parquet``
  (per invocation; supports session-resumable runs by passing distinct
  ``--gates`` lists across sessions)
- Manifest row tagged with ``sweep_kind="gate_x_scenarios_x_seeds"``
- Decisions parquet generated locally per Batch 10A convention
  (gitignored under ``multi_seed/*_decisions.parquet``)

Usage::

    uv run python scripts/gate_x_scenarios_x_seeds_sweep.py \\
        --gates 5,10,15 \\
        --seeds 42-61 \\
        --scenarios fat_finger_high,intraday_spike,correlated_blackout,\\
stale_quote,shock_price_cut,sustained_manipulation
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tprr.config import load_index_config
from tprr.sensitivity.baseline import load_pipeline_inputs
from tprr.sensitivity.multi_seed import build_gate_x_scenario_runs, run_multi_seed_sweep


def _parse_seed_range(spec: str) -> list[int]:
    """Parse ``"42-61"`` or ``"42,43,44"`` into a list of ints."""
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in spec.split(",")]


def _parse_gate_values(spec: str) -> list[float]:
    """Parse comma-separated gate values.

    Accepts both percentage form (``"5,10,15"`` → ``[0.05, 0.10, 0.15]``)
    and fraction form (``"0.05,0.10,0.15"`` → ``[0.05, 0.10, 0.15]``).
    Any value > 1.0 is interpreted as a percentage.
    """
    out: list[float] = []
    for s in spec.split(","):
        v = float(s.strip())
        out.append(v / 100 if v > 1.0 else v)
    return out


def _gate_label(gate_value: float) -> str:
    """Format a gate value as ``"5pct"`` etc. for filename composition."""
    return f"{round(gate_value * 100)}pct"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--gates",
        type=str,
        default="5,10,15",
        help="Comma-separated gate values (percentages or fractions).",
    )
    p.add_argument(
        "--seeds",
        type=str,
        default="42-61",
        help="Seed range like '42-61' or comma list '42,43,44'.",
    )
    p.add_argument(
        "--scenarios",
        type=str,
        required=True,
        help="Comma-separated scenario ids.",
    )
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--output-root", type=str, default="data/indices/sweeps")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    seeds = _parse_seed_range(args.seeds)
    gates = _parse_gate_values(args.gates)
    scenario_ids = [s.strip() for s in args.scenarios.split(",")]
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(
        f"gate x scenarios x seeds sweep: "
        f"gates={[f'{g:.2f}' for g in gates]}  "
        f"seeds={seeds[0]}-{seeds[-1]}  "
        f"scenarios={scenario_ids}",
        flush=True,
    )

    print(f"Loading static inputs (using seed={seeds[0]} for boilerplate)...", flush=True)
    inputs_static = load_pipeline_inputs(seed=seeds[0], start=start, end=end)
    base_config = load_index_config()
    print(
        f"  range {inputs_static.range_start} -> {inputs_static.range_end}  |  "
        f"{len(inputs_static.scenarios_by_id)} scenarios available",
        flush=True,
    )

    runs = build_gate_x_scenario_runs(
        base_config=base_config,
        gate_values=gates,
        seeds=seeds,
        scenario_ids=scenario_ids,
    )
    print(
        f"\nTotal runs: {len(runs)} "
        f"({len(gates)} gates x {len(seeds)} seeds x {1 + len(scenario_ids)} panels)",
        flush=True,
    )

    seed_lo, seed_hi = seeds[0], seeds[-1]
    gate_label_str = "_".join(_gate_label(g).removesuffix("pct") for g in gates)
    sweep_id = f"gate_x_scenarios_seed{seed_lo}-{seed_hi}_gates_{gate_label_str}"

    output_root = Path(args.output_root) / "multi_seed"
    output_path = run_multi_seed_sweep(
        sweep_id=sweep_id,
        sweep_kind="gate_x_scenarios_x_seeds",
        parameter_dim="gate_x_seed",
        runs=runs,
        inputs_static=inputs_static,
        output_dir=output_root,
        manifest_path=output_root.parent / "manifest.csv",
        base_audit_id="gate_x_scenarios",
    )
    print(f"\nWrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
