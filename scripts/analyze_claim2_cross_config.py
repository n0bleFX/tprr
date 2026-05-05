"""Claim 2 cross-config trajectory analysis (Phase 10 Batch 10C final).

For each config (default / loose / tight) and each core tier (F / S / E),
compute:

- base_date absorption: how many (seed, scenario) pairs have non-zero
  base_date delta (120 datapoints per tier per config)
- full-trajectory absorption: how many (seed, scenario) pairs have any
  non-zero trajectory delta across the 366-day backtest
- per-scenario trajectory pattern: which scenarios produce trajectory
  variation in which tier at which config

The base_date absorption is established at default (per existing finding
doc); this analysis tests whether F-tier full-trajectory absorption holds
across all 3 configs (methodology-level finding) or is default-specific
(config-dependent property). Per-scenario S/E trajectory asymmetry is
compared across configs to characterise the scenario response landscape.
"""

from __future__ import annotations

import pandas as pd

BASE_DATE = pd.Timestamp("2026-01-01").date()
PARQUETS = {
    "default": "data/indices/sweeps/multi_seed/multi_seed_default_seed42-61_with_scenarios.parquet",
    "loose": "data/indices/sweeps/multi_seed/multi_seed_loose_seed42-61_with_scenarios.parquet",
    "tight": "data/indices/sweeps/multi_seed/multi_seed_tight_seed42-61_with_scenarios.parquet",
}
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


def load_with_scenarios(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
    return df


def base_date_absorption(df: pd.DataFrame, tier: str) -> dict:
    sub = df[(df["index_code"] == tier) & (df["as_of_date"] == BASE_DATE)]
    pivot = sub.pivot_table(
        index="seed",
        columns="panel_id",
        values="raw_value_usd_mtok",
        aggfunc="first",
    )
    n_pairs = 0
    n_nonzero = 0
    max_abs = 0.0
    for scenario in SCENARIOS:
        if scenario not in pivot.columns:
            continue
        for seed in pivot.index:
            n_pairs += 1
            delta = abs(pivot.loc[seed, scenario] - pivot.loc[seed, "clean"])
            if delta > TRAJECTORY_TOL:
                n_nonzero += 1
            max_abs = max(max_abs, delta)
    return {"n_pairs": n_pairs, "n_nonzero": n_nonzero, "max_abs": max_abs}


def trajectory_pair_deltas(df: pd.DataFrame, tier: str) -> pd.DataFrame:
    """For each (seed, scenario) pair, compute max abs trajectory delta vs clean.

    Uses all days (not just base_date)."""
    sub = df[df["index_code"] == tier].copy()
    sub = sub.set_index(["seed", "panel_id", "as_of_date"])["raw_value_usd_mtok"]
    rows = []
    for seed in sub.index.get_level_values("seed").unique():
        clean_series = sub.loc[(seed, "clean")]
        for scenario in SCENARIOS:
            if (seed, scenario) not in sub.index.droplevel("as_of_date"):
                continue
            scen_series = sub.loc[(seed, scenario)]
            aligned = pd.concat([clean_series, scen_series], axis=1, keys=["clean", "scen"])
            aligned = aligned.dropna()
            delta = (aligned["scen"] - aligned["clean"]).abs()
            rows.append(
                {
                    "seed": seed,
                    "scenario": scenario,
                    "max_traj_abs": delta.max(),
                    "any_nonzero": bool((delta > TRAJECTORY_TOL).any()),
                    "n_days_nonzero": int((delta > TRAJECTORY_TOL).sum()),
                }
            )
    return pd.DataFrame(rows)


def trajectory_summary(traj: pd.DataFrame, tier: str, config: str) -> dict:
    n_pairs = len(traj)
    n_pairs_nonzero = int(traj["any_nonzero"].sum())
    by_scen = traj.groupby("scenario")["any_nonzero"]
    n_scenarios_with_variation = int((by_scen.sum() > 0).sum())
    return {
        "config": config,
        "tier": tier,
        "n_pairs": n_pairs,
        "n_pairs_nonzero": n_pairs_nonzero,
        "max_traj_abs": traj["max_traj_abs"].max(),
        "n_scenarios_with_variation": n_scenarios_with_variation,
    }


def per_scenario_trajectory(traj: pd.DataFrame, config: str, tier: str) -> pd.DataFrame:
    by_scen = traj.groupby("scenario").agg(
        n_seeds=("seed", "count"),
        n_seeds_nonzero=("any_nonzero", "sum"),
        max_traj_abs=("max_traj_abs", "max"),
        median_n_days_nonzero=("n_days_nonzero", "median"),
    )
    by_scen.insert(0, "tier", tier)
    by_scen.insert(0, "config", config)
    return by_scen.reset_index()


def main() -> None:
    print("=" * 84)
    print("CLAIM 2 CROSS-CONFIG TRAJECTORY ANALYSIS")
    print("=" * 84)
    print(f"Base date: {BASE_DATE}")
    print(f"Configs: {list(PARQUETS)}")
    print(f"Tiers: {TIERS}")
    print(f"Scenarios: {SCENARIOS}")
    print("Datapoints per (config, tier): 20 seeds x 6 scenarios = 120 pairs")
    print(f"Trajectory tolerance: {TRAJECTORY_TOL}")
    print()

    base_rows = []
    traj_summary_rows = []
    per_scen_frames = []

    for config, path in PARQUETS.items():
        df = load_with_scenarios(path)
        for tier in TIERS:
            bd = base_date_absorption(df, tier)
            base_rows.append(
                {
                    "config": config,
                    "tier": tier,
                    "n_pairs": bd["n_pairs"],
                    "n_pairs_nonzero": bd["n_nonzero"],
                    "max_abs_base_date": bd["max_abs"],
                }
            )

            traj = trajectory_pair_deltas(df, tier)
            traj_summary_rows.append(trajectory_summary(traj, tier, config))
            per_scen_frames.append(per_scenario_trajectory(traj, config, tier))

    base_df = pd.DataFrame(base_rows)
    traj_summary_df = pd.DataFrame(traj_summary_rows)
    per_scen_df = pd.concat(per_scen_frames, ignore_index=True)

    pd.set_option("display.float_format", lambda x: f"{x:,.6g}")
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 220)

    print("--- BASE_DATE absorption (120 pairs per cell) ---")
    print(base_df.to_string(index=False))
    print()
    print("--- FULL-TRAJECTORY absorption (366 days x 120 pairs per cell) ---")
    print(traj_summary_df.to_string(index=False))
    print()
    print("--- Per-config x per-tier x per-scenario trajectory pattern ---")
    cmp = per_scen_df.pivot_table(
        index=["tier", "scenario"],
        columns="config",
        values="n_seeds_nonzero",
        aggfunc="first",
    ).reindex(columns=["default", "loose", "tight"])
    cmp.columns = [f"n_seeds_traj_{c}/20" for c in cmp.columns]
    print(cmp.to_string())
    print()
    print("--- Max trajectory abs delta ($/Mtok) per (tier, scenario, config) ---")
    cmp_max = per_scen_df.pivot_table(
        index=["tier", "scenario"],
        columns="config",
        values="max_traj_abs",
        aggfunc="first",
    ).reindex(columns=["default", "loose", "tight"])
    cmp_max.columns = [f"max_abs_{c}" for c in cmp_max.columns]
    print(cmp_max.to_string())


if __name__ == "__main__":
    main()
