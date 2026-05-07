"""Per-gate F-tier absorption analysis (Phase 11 Batch 11A).

For each gate value in the Session 1 (and later combined Session 1+2)
parquet, compute:

- Base_date absorption: n_(seed, scenario) pairs with non-zero delta vs
  clean at base_date, max abs delta
- Full-trajectory absorption: n_(seed, scenario) pairs with any
  trajectory delta across the 366-day backtest
- Per-tier breakdown (TPRR_F, TPRR_S, TPRR_E)
- Per-scenario response signature

Usage::

    uv run python scripts/analyze_gate_x_scenarios.py \\
        data/indices/sweeps/multi_seed/gate_x_scenarios_seed42-61_gates_5_10_15.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BASE_DATE = pd.Timestamp("2026-01-01").date()
TIERS = ["TPRR_F", "TPRR_S", "TPRR_E"]
SCENARIOS = [
    "fat_finger_high",
    "intraday_spike",
    "correlated_blackout",
    "stale_quote",
    "shock_price_cut",
    "sustained_manipulation",
]
TRAJECTORY_TOL = 1e-6


def load_parquet(paths: list[Path]) -> pd.DataFrame:
    dfs = [pd.read_parquet(p) for p in paths]
    df = pd.concat(dfs, ignore_index=True)
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
    return df


def base_date_summary(df: pd.DataFrame, gate_label: str, tier: str) -> dict:
    sub = df[
        (df["parameter_label"] == gate_label)
        & (df["index_code"] == tier)
        & (df["as_of_date"] == BASE_DATE)
    ]
    pivot = sub.pivot_table(
        index="seed",
        columns="panel_id",
        values="raw_value_usd_mtok",
        aggfunc="first",
    )
    n_pairs = 0
    n_nonzero = 0
    max_abs = 0.0
    for scen in SCENARIOS:
        if scen not in pivot.columns:
            continue
        for seed in pivot.index:
            n_pairs += 1
            delta = abs(pivot.loc[seed, scen] - pivot.loc[seed, "clean"])
            if delta > TRAJECTORY_TOL:
                n_nonzero += 1
            max_abs = max(max_abs, delta)
    return {
        "gate": gate_label,
        "tier": tier,
        "n_pairs": n_pairs,
        "n_pairs_nonzero": n_nonzero,
        "max_abs_base_date": max_abs,
    }


def trajectory_summary(df: pd.DataFrame, gate_label: str, tier: str) -> dict:
    sub = df[(df["parameter_label"] == gate_label) & (df["index_code"] == tier)].copy()
    sub = sub.set_index(["seed", "panel_id", "as_of_date"]).sort_index()
    series_lookup = sub["raw_value_usd_mtok"]

    n_pairs = 0
    n_pairs_nonzero = 0
    max_traj_abs = 0.0
    scenarios_with_var: set[str] = set()

    for seed in series_lookup.index.get_level_values("seed").unique():
        if (seed, "clean") not in series_lookup.index.droplevel("as_of_date"):
            continue
        clean_series = series_lookup.loc[(seed, "clean")]
        for scen in SCENARIOS:
            if (seed, scen) not in series_lookup.index.droplevel("as_of_date"):
                continue
            n_pairs += 1
            scen_series = series_lookup.loc[(seed, scen)]
            aligned = pd.concat(
                [clean_series, scen_series], axis=1, keys=["clean", "scen"]
            ).dropna()
            delta = (aligned["scen"] - aligned["clean"]).abs()
            mx = float(delta.max())
            max_traj_abs = max(max_traj_abs, mx)
            if (delta > TRAJECTORY_TOL).any():
                n_pairs_nonzero += 1
                scenarios_with_var.add(scen)

    return {
        "gate": gate_label,
        "tier": tier,
        "n_pairs": n_pairs,
        "n_pairs_nonzero": n_pairs_nonzero,
        "max_traj_abs": max_traj_abs,
        "n_scenarios_with_variation": len(scenarios_with_var),
        "scenarios_with_variation": sorted(scenarios_with_var),
    }


def per_scenario_breakdown(df: pd.DataFrame, gate_label: str, tier: str) -> pd.DataFrame:
    sub = df[(df["parameter_label"] == gate_label) & (df["index_code"] == tier)].copy()
    sub = sub.set_index(["seed", "panel_id", "as_of_date"]).sort_index()
    series_lookup = sub["raw_value_usd_mtok"]

    rows = []
    for seed in series_lookup.index.get_level_values("seed").unique():
        if (seed, "clean") not in series_lookup.index.droplevel("as_of_date"):
            continue
        clean_series = series_lookup.loc[(seed, "clean")]
        for scen in SCENARIOS:
            if (seed, scen) not in series_lookup.index.droplevel("as_of_date"):
                continue
            scen_series = series_lookup.loc[(seed, scen)]
            aligned = pd.concat(
                [clean_series, scen_series], axis=1, keys=["clean", "scen"]
            ).dropna()
            delta = (aligned["scen"] - aligned["clean"]).abs()
            rows.append(
                {
                    "seed": seed,
                    "scenario": scen,
                    "max_traj_abs": float(delta.max()),
                    "any_nonzero": bool((delta > TRAJECTORY_TOL).any()),
                }
            )

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    by_scen = out.groupby("scenario").agg(
        n_seeds=("seed", "count"),
        n_seeds_nonzero=("any_nonzero", "sum"),
        max_traj_abs=("max_traj_abs", "max"),
    )
    by_scen.insert(0, "tier", tier)
    by_scen.insert(0, "gate", gate_label)
    return by_scen.reset_index()


def main() -> None:
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        print("usage: analyze_gate_x_scenarios.py <parquet> [<parquet> ...]")
        sys.exit(1)

    df = load_parquet(paths)
    gate_labels = sorted(df["parameter_label"].unique())
    print(
        f"Loaded {sum(p.stat().st_size for p in paths) / 1e6:.1f} MB across {len(paths)} parquet(s)"
    )
    print(f"Gates: {gate_labels}")
    print(f"Seeds: {sorted(df['seed'].unique())}")
    print(f"Tiers: {sorted(df['index_code'].unique())}")
    print()

    pd.set_option("display.float_format", lambda x: f"{x:.6g}")
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 220)

    base_rows = []
    traj_rows = []
    per_scen_frames = []

    for gate_label in gate_labels:
        for tier in TIERS:
            base_rows.append(base_date_summary(df, gate_label, tier))
            traj_rows.append(trajectory_summary(df, gate_label, tier))
            sub_frame = per_scenario_breakdown(df, gate_label, tier)
            if not sub_frame.empty:
                per_scen_frames.append(sub_frame)

    base_df = pd.DataFrame(base_rows)
    traj_df = pd.DataFrame(traj_rows).drop(columns=["scenarios_with_variation"])

    print("=" * 84)
    print("BASE_DATE absorption (120 (seed, scenario) pairs per cell)")
    print("=" * 84)
    print(base_df.to_string(index=False))
    print()

    print("=" * 84)
    print("FULL-TRAJECTORY absorption (366 days x 120 pairs per cell)")
    print("=" * 84)
    print(traj_df.to_string(index=False))
    print()

    if per_scen_frames:
        per_scen = pd.concat(per_scen_frames, ignore_index=True)
        # Cross-gate: pivot to compare scenarios across gates per tier
        for tier in TIERS:
            sub = per_scen[per_scen["tier"] == tier]
            if sub.empty:
                continue
            pivot = sub.pivot_table(
                index="scenario",
                columns="gate",
                values="n_seeds_nonzero",
                aggfunc="first",
            ).reindex(columns=gate_labels)
            print(f"--- {tier} per-scenario response (n_seeds with traj variation, of 20) ---")
            print(pivot.to_string())
            print()
            pivot_mx = sub.pivot_table(
                index="scenario",
                columns="gate",
                values="max_traj_abs",
                aggfunc="first",
            ).reindex(columns=gate_labels)
            print(f"--- {tier} max trajectory abs delta ($/Mtok) per (scenario, gate) ---")
            print(pivot_mx.to_string())
            print()


if __name__ == "__main__":
    main()
