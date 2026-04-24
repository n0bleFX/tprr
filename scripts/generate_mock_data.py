"""Generate the clean mock contributor panel for a backtest window.

CLI entry point for Phase 2a. Loads config, generates baseline prices, applies
contributor noise + bias, populates volumes, and writes the result to
``data/raw/mock_panel_clean_seed{seed}.parquet``.

Phase 2b will extend this with intraday change events; Phase 3 will add
scenario-injection variants.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from tprr.config import load_all
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.mockdata.volume import generate_volumes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate clean mock panel for the TPRR backtest window."
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_all()

    print(f"Generating mock panel: {args.start} to {args.end}, seed={args.seed}")
    print(
        f"Registry: {len(cfg.model_registry)} models, "
        f"{len(cfg.contributors)} contributors"
    )

    baseline = generate_baseline_prices(
        cfg.model_registry, args.start, args.end, args.seed
    )
    panel = generate_contributor_panel(
        baseline, cfg.contributors, cfg.model_registry, args.seed
    )
    panel = generate_volumes(panel, cfg.contributors, args.seed)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"mock_panel_clean_seed{args.seed}.parquet"
    panel.to_parquet(output_path, index=False)

    _print_summary(panel, output_path)
    return 0


def _print_summary(panel: pd.DataFrame, output_path: Path) -> None:
    n_rows = len(panel)
    date_min = panel["observation_date"].min()
    date_max = panel["observation_date"].max()
    n_contributors = panel["contributor_id"].nunique()
    n_models = panel["constituent_id"].nunique()

    print()
    print(f"Wrote {output_path} ({n_rows:,} rows)")
    print(f"  Date range: {date_min.date()} to {date_max.date()}")
    print(f"  Contributors: {n_contributors} unique")
    print(f"  Models: {n_models} unique")

    print()
    print("Mean output price by tier:")
    by_tier = panel.groupby("tier_code")["output_price_usd_mtok"].mean()
    for tier, mean_price in by_tier.items():
        print(f"  {tier}: ${mean_price:.4f}/Mtok")

    print()
    print("Mean volume_mtok_7d by contributor:")
    by_contrib = (
        panel.groupby("contributor_id")["volume_mtok_7d"]
        .mean()
        .sort_values(ascending=False)
    )
    for cid, mean_vol in by_contrib.items():
        print(f"  {cid:<25} {mean_vol:>12.3f}")


if __name__ == "__main__":
    raise SystemExit(main())
