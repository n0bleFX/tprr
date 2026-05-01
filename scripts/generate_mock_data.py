"""Generate the clean mock contributor panel and change events for a backtest.

CLI entry point for Phase 2a + Phase 2b. Loads config, generates baseline
prices (with step-event list), applies contributor noise + bias, populates
volumes, materialises ChangeEvent records (provider-driven + contributor-
specific), then overwrites panel prices on change-event days with the daily
TWAP and writes both artifacts:

  data/raw/mock_panel_clean_seed{seed}.parquet         (TWAP-adjusted panel)
  data/raw/mock_change_events_clean_seed{seed}.parquet (ChangeEvent records)

Phase 3.2 adds ``--scenarios PATH`` for outlier-injection scenarios. When
provided, the clean Phase 2 pipeline runs once and each scenario is then
composed against a deep copy of the clean state, writing per-scenario:

  data/raw/mock_panel_{scenario_id}_seed{seed}.parquet
  data/raw/mock_change_events_{scenario_id}_seed{seed}.parquet
  data/raw/scenarios/{scenario_id}_seed{seed}_manifest.json

Pre-flight event-clear-day check (``preflight_event_clear_check``) runs
before each scenario is composed. Scenarios with event-clear-day
annotations (fat_finger_high/low, shock_price_cut, intraday_spike) fail
loudly if the target day collides with natural Phase 2 events on the
current seed. Dates are NEVER silently shifted.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from tprr.config import (
    AllConfig,
    ContributorPanel,
    ModelRegistry,
    ScenarioEntry,
    load_all,
)
from tprr.mockdata.change_events import apply_twap_to_panel, generate_change_events
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.outliers import ScenarioManifest
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.mockdata.scenarios import compose_scenario, preflight_event_clear_check
from tprr.mockdata.volume import generate_volumes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Generate clean mock panel + change events for the TPRR backtest window.")
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=date(2025, 1, 1),
        help="backtest start date (ISO format), default 2025-01-01",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=date.today(),
        help="backtest end date (ISO format), default today",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="random seed, default 42",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="output directory, default data/raw",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help=(
            "config directory override, default project config/. Useful for "
            "tests that want to point at a custom config bundle."
        ),
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=None,
        help=(
            "Path to scenarios.yaml. When provided, runs Phase 2 pipeline "
            "for the clean baseline and writes clean artifacts, then composes "
            "each scenario from the YAML (deep-copy of clean state) and "
            "writes per-scenario panel + events + manifest. Pre-flight "
            "event-clear-day check fails loudly on collisions."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_all(
        args.config_dir,
        backtest_end=args.end,
        scenarios_path=args.scenarios,
    )

    print(f"Generating mock panel + change events: {args.start} to {args.end}, seed={args.seed}")
    print(f"Registry: {len(cfg.model_registry)} models, {len(cfg.contributors)} contributors")

    baseline, step_events = generate_baseline_prices(
        cfg.model_registry, args.start, args.end, args.seed
    )
    panel = generate_contributor_panel(baseline, cfg.contributors, cfg.model_registry, args.seed)
    panel = generate_volumes(panel, cfg.contributors, args.seed)
    events = generate_change_events(
        panel, step_events, cfg.model_registry, cfg.contributors, args.seed
    )
    panel = apply_twap_to_panel(panel, events)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    clean_panel_path = args.output_dir / f"mock_panel_clean_seed{args.seed}.parquet"
    clean_events_path = args.output_dir / f"mock_change_events_clean_seed{args.seed}.parquet"
    panel.to_parquet(clean_panel_path, index=False)
    events.to_parquet(clean_events_path, index=False)

    _print_summary(
        panel=panel,
        events=events,
        step_events=step_events,
        registry=cfg.model_registry,
        contributors=cfg.contributors,
        panel_path=clean_panel_path,
        events_path=clean_events_path,
    )

    if args.scenarios is not None:
        _compose_scenarios_from_yaml(
            args=args,
            cfg=cfg,
            clean_panel=panel,
            clean_events=events,
        )

    return 0


def _compose_scenarios_from_yaml(
    *,
    args: argparse.Namespace,
    cfg: AllConfig,
    clean_panel: pd.DataFrame,
    clean_events: pd.DataFrame,
) -> None:
    """Run pre-flight + composer + write artifacts for each scenario.

    Uses ``cfg.scenarios`` (already loaded and cross-validated by
    ``load_all`` with ``scenarios_path=args.scenarios``) — no second
    YAML load needed.
    """
    scenario_manifest_dir = args.output_dir / "scenarios"
    scenario_manifest_dir.mkdir(parents=True, exist_ok=True)

    print()
    print(f"Composing {len(cfg.scenarios.scenarios)} scenarios from {args.scenarios}")

    for spec in cfg.scenarios.scenarios:
        # Pre-flight runs on the CLEAN events (the baseline against which
        # event-clear-day annotations are stated). Composing happens on
        # deep copies so each scenario is independent of every other.
        preflight_event_clear_check(spec, clean_events, cfg.contributors, args.start)

        panel_copy = clean_panel.copy()
        events_copy = clean_events.copy()
        manifest = ScenarioManifest(scenario_id=spec.id, seed=args.seed)

        panel_out, events_out, _registry_out = compose_scenario(
            spec,
            panel_copy,
            events_copy,
            cfg.model_registry,
            cfg.contributors,
            backtest_start=args.start,
            seed=args.seed,
            manifest=manifest,
        )

        scenario_panel_path, scenario_events_path = _scenario_artifact_paths(spec, args)
        panel_out.to_parquet(scenario_panel_path, index=False)
        events_out.to_parquet(scenario_events_path, index=False)
        manifest_path = manifest.write(scenario_manifest_dir)

        print(
            f"  {spec.id:<24}  "
            f"panel={scenario_panel_path.name}  "
            f"events={scenario_events_path.name}  "
            f"manifest={manifest_path.name}"
        )


def _scenario_artifact_paths(spec: ScenarioEntry, args: argparse.Namespace) -> tuple[Path, Path]:
    panel_path = args.output_dir / f"mock_panel_{spec.id}_seed{args.seed}.parquet"
    events_path = args.output_dir / f"mock_change_events_{spec.id}_seed{args.seed}.parquet"
    return panel_path, events_path


def _print_summary(
    *,
    panel: pd.DataFrame,
    events: pd.DataFrame,
    step_events: pd.DataFrame,
    registry: ModelRegistry,
    contributors: ContributorPanel,
    panel_path: Path,
    events_path: Path,
) -> None:
    _ = contributors  # currently unused — was previously read for diagnostics
    n_rows = len(panel)
    date_min = panel["observation_date"].min()
    date_max = panel["observation_date"].max()
    n_days = (pd.Timestamp(date_max).normalize() - pd.Timestamp(date_min).normalize()).days + 1
    n_years = n_days / 365.0

    print()
    print(f"Wrote {panel_path} ({n_rows:,} rows)")
    print(f"  Date range: {date_min.date()} to {date_max.date()}  ({n_days} days)")
    print(f"  Contributors: {panel['contributor_id'].nunique()} unique")
    print(f"  Models: {panel['constituent_id'].nunique()} unique")

    print()
    print("Mean output price by tier (post-TWAP):")
    by_tier = panel.groupby("tier_code")["output_price_usd_mtok"].mean()
    for tier, mean_price in by_tier.items():
        print(f"  {tier}: ${mean_price:.4f}/Mtok")

    print()
    print("Mean volume_mtok_7d by contributor:")
    by_contrib = (
        panel.groupby("contributor_id")["volume_mtok_7d"].mean().sort_values(ascending=False)
    )
    for cid, mean_vol in by_contrib.items():
        print(f"  {cid:<25} {mean_vol:>12.3f}")

    print()
    print(f"Wrote {events_path} ({len(events):,} rows, from {len(step_events)} step events)")

    print()
    print("Events by reason:")
    by_reason = events.groupby("reason").size()
    for reason, n in by_reason.items():
        print(f"  {reason:<22} {n:>6}")

    tier_lookup = {m.constituent_id: m.tier.value for m in registry.models}
    events_with_tier = events.copy()
    events_with_tier["tier"] = events_with_tier["constituent_id"].map(tier_lookup)

    print()
    print("Events by tier x reason:")
    grid = events_with_tier.groupby(["tier", "reason"]).size().unstack(fill_value=0)
    header = "  tier      " + " ".join(f"{c:>22}" for c in grid.columns)
    print(header)
    for tier in ["TPRR_F", "TPRR_S", "TPRR_E"]:
        if tier not in grid.index:
            continue
        row = grid.loc[tier]
        print(f"  {tier:<8}  " + " ".join(f"{int(row[c]):>22}" for c in grid.columns))

    pairs = (
        panel[["tier_code", "contributor_id", "constituent_id"]]
        .drop_duplicates()
        .rename(columns={"tier_code": "tier"})
    )
    n_pairs_by_tier = pairs.groupby("tier").size()
    events_by_tier = events_with_tier.groupby("tier").size()
    print()
    print(f"Per-pair event rate over {n_years:.2f} years:")
    print(
        f"  {'tier':<8}  {'pairs':>6}  {'events':>7}  {'events/pair':>12}  {'events/pair/yr':>15}"
    )
    for tier in ["TPRR_F", "TPRR_S", "TPRR_E"]:
        n_pairs = int(n_pairs_by_tier.get(tier, 0))
        n_events = int(events_by_tier.get(tier, 0))
        if n_pairs == 0:
            continue
        per_pair = n_events / n_pairs
        per_pair_yr = per_pair / n_years if n_years > 0 else 0.0
        print(f"  {tier:<8}  {n_pairs:>6}  {n_events:>7}  {per_pair:>12.2f}  {per_pair_yr:>15.2f}")


if __name__ == "__main__":
    raise SystemExit(main())
