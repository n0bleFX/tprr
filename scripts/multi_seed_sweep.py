"""Phase 10 Batch 10C — multi-seed runs + cliff-edge characterization.

For each of 3 config variants (default / loose / tight) and a seed range,
regenerate the Tier A panel per seed and re-run the canonical pipeline.
The output enables Phase 11 distributional claims:

- Claim 1 — cliff-edge resolution holds across seeds (tier_a_weight_share
  distribution at base_date)
- Claim 3 — suspension reinstatement frequency is robust (n_suspension_intervals
  distribution per config)
- Claim 4 — annualised volatility distribution under clean panel
- Claim 5 — n_constituents_active dispersion at base_date

Claim 2 (scenario x multi-seed cross-product) is opt-in via
``--scenarios``: when set, each seed runs clean + 6 scenarios at the
selected config(s). Without ``--scenarios``, the sweep is clean-panel
only (~30 min total for 3 configs x 20 seeds).

Output:
- ``data/indices/sweeps/multi_seed/multi_seed_{label}_seed{lo}-{hi}.parquet``
  per config (default / loose / tight)
- ``..._decisions.parquet`` per config

Usage::

    uv run python scripts/multi_seed_sweep.py [--config default,loose,tight]
        [--seeds 42-61] [--scenarios fat_finger_high,intraday_spike,...]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tprr.config import IndexConfig, load_index_config
from tprr.schema import AttestationTier
from tprr.sensitivity.baseline import load_pipeline_inputs
from tprr.sensitivity.multi_seed import (
    build_clean_panel_runs,
    build_clean_plus_scenario_runs,
    run_multi_seed_sweep,
)


def _config_default(base: IndexConfig) -> IndexConfig:
    return base.model_copy(
        update={
            "lambda_": 3.0,
            "tier_haircuts": {
                AttestationTier.A: 1.0,
                AttestationTier.B: 0.5,
                AttestationTier.C: 0.8,
            },
            "tier_blending_coefficients": {
                AttestationTier.A: 0.6,
                AttestationTier.C: 0.3,
                AttestationTier.B: 0.1,
            },
            "suspension_threshold_days": 3,
            "reinstatement_threshold_days": 10,
        }
    )


def _config_loose(base: IndexConfig) -> IndexConfig:
    """Less aggressive Tier B downweighting + lower median-distance λ."""
    return base.model_copy(
        update={
            "lambda_": 2.0,
            "tier_haircuts": {
                AttestationTier.A: 1.0,
                AttestationTier.B: 0.6,
                AttestationTier.C: 0.8,
            },
            "tier_blending_coefficients": {
                AttestationTier.A: 0.6,
                AttestationTier.C: 0.3,
                AttestationTier.B: 0.1,
            },
            "suspension_threshold_days": 3,
            "reinstatement_threshold_days": 10,
        }
    )


def _config_tight(base: IndexConfig) -> IndexConfig:
    """More aggressive Tier B downweighting + higher median-distance λ."""
    return base.model_copy(
        update={
            "lambda_": 5.0,
            "tier_haircuts": {
                AttestationTier.A: 1.0,
                AttestationTier.B: 0.4,
                AttestationTier.C: 0.8,
            },
            "tier_blending_coefficients": {
                AttestationTier.A: 0.6,
                AttestationTier.C: 0.3,
                AttestationTier.B: 0.1,
            },
            "suspension_threshold_days": 3,
            "reinstatement_threshold_days": 10,
        }
    )


CONFIG_BUILDERS = {
    "default": _config_default,
    "loose": _config_loose,
    "tight": _config_tight,
}


def _parse_seed_range(spec: str) -> list[int]:
    """Parse ``"42-61"`` or ``"42,43,44"`` into a list of ints."""
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in spec.split(",")]


def _parse_config_set(spec: str) -> list[str]:
    out = [s.strip() for s in spec.split(",")]
    for s in out:
        if s not in CONFIG_BUILDERS:
            raise ValueError(f"Unknown config {s!r}; expected one of {list(CONFIG_BUILDERS)}")
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config",
        type=str,
        default="default,loose,tight",
        help="Comma-separated config labels (default/loose/tight).",
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
        default=None,
        help="Comma-separated scenario ids; when set, runs each seed x clean x scenarios.",
    )
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--output-root", type=str, default="data/indices/sweeps")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    seeds = _parse_seed_range(args.seeds)
    config_labels = _parse_config_set(args.config)
    scenario_ids = [s.strip() for s in args.scenarios.split(",")] if args.scenarios else []
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(
        f"Multi-seed sweep: configs={config_labels}  seeds={seeds[0]}-{seeds[-1]}  "
        f"scenarios={scenario_ids if scenario_ids else 'none (clean only)'}",
        flush=True,
    )
    # Use the first seed's parquet for static-input loading (Tier C, rankings,
    # registry, contributors, range). The Tier A panel from this load is
    # discarded; per-seed regeneration replaces it.
    print(f"Loading static inputs (using seed={seeds[0]} for boilerplate)...", flush=True)
    inputs_static = load_pipeline_inputs(seed=seeds[0], start=start, end=end)
    base_config = load_index_config()
    print(
        f"  range {inputs_static.range_start} -> {inputs_static.range_end}  |  "
        f"{len(inputs_static.scenarios_by_id)} scenarios available",
        flush=True,
    )

    output_root = Path(args.output_root) / "multi_seed"
    seed_lo, seed_hi = seeds[0], seeds[-1]

    for label in config_labels:
        config = CONFIG_BUILDERS[label](base_config)
        if scenario_ids:
            runs = build_clean_plus_scenario_runs(
                parameter_label=label,
                config=config,
                seeds=seeds,
                scenario_ids=scenario_ids,
            )
            sweep_id = f"multi_seed_{label}_seed{seed_lo}-{seed_hi}_with_scenarios"
        else:
            runs = build_clean_panel_runs(
                parameter_label=label,
                config=config,
                seeds=seeds,
            )
            sweep_id = f"multi_seed_{label}_seed{seed_lo}-{seed_hi}"
        print(f"\nConfig={label}: {len(runs)} runs", flush=True)
        output_path = run_multi_seed_sweep(
            sweep_id=sweep_id,
            sweep_kind="multi_seed",
            parameter_dim=f"seed_x_{label}",
            runs=runs,
            inputs_static=inputs_static,
            output_dir=output_root,
            manifest_path=output_root.parent / "manifest.csv",
            base_audit_id=f"multi_seed_{label}",
        )
        print(f"  Wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
