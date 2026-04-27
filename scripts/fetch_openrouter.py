"""Fetch OpenRouter Tier C reference data and normalise to panel schema.

CLI entry point for Phase 4. Loads config, fetches the three OpenRouter
sources (with daily caching), normalises to PanelObservationDF rows,
enriches aggregate rows with rankings-derived volume, and writes the
combined panel to ``data/raw/openrouter_panel_{YYYY-MM-DD}.parquet``.

Three sources:
  /api/v1/models                       -> aggregate per-constituent row
                                          (contributor_id = "openrouter:aggregate")
  /api/v1/models/{author}/{slug}/      -> per-hosting-provider rows
    endpoints                            (contributor_id = "openrouter:{provider_slug}")
  jampongsathorn rankings mirror       -> volume_mtok_7d on aggregate rows

Per docs/decision_log.md 2026-04-28 ("Tier C rankings sparseness"):
rankings volume is populated only on aggregate rows for constituents
matching a rankings entry via date-suffix stripping. Unmatched
constituents (and all per-provider rows) carry volume_mtok_7d = 0,
with aggregate rows flagged ``no_rankings_data`` in ``notes``.

Per docs/decision_log.md 2026-04-28 ("Tier C historical backfill"):
the current OpenRouter snapshot is used as a static structural proxy
across the full backtest. Don't fabricate historical ranking movements.

Five constituents have NO OpenRouter analogue at all (only one — meta —
post-Batch-D); these are skipped at the /models stage and produce no
endpoints fetch.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from tprr.config import load_all
from tprr.reference.openrouter import (
    enrich_with_rankings_volume,
    fetch_model_endpoints,
    fetch_models,
    fetch_rankings,
    normalise_endpoints_to_panel,
    normalise_models_to_panel,
)
from tprr.schema import PanelObservationDF


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch + normalise OpenRouter Tier C reference data, write "
            "combined panel parquet."
        )
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=date.today(),
        help="as-of date (ISO format), default today",
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
    cfg = load_all(backtest_end=args.as_of)
    as_of = args.as_of

    print(f"OpenRouter fetch + normalise: as_of={as_of}")
    print(
        f"Registry: {len(cfg.model_registry)} models, "
        f"{sum(1 for m in cfg.model_registry.models if m.openrouter_author and m.openrouter_slug)} mapped to OpenRouter"
    )

    print("\nFetching /api/v1/models...")
    models_json = fetch_models(as_of_date=as_of)
    aggregate_panel = normalise_models_to_panel(
        models_json, cfg.model_registry, as_of
    )
    print(
        f"  {len(aggregate_panel)} aggregate Tier C rows from /models"
    )

    print("\nFetching rankings mirror...")
    rankings_json = fetch_rankings(as_of_date=as_of)
    aggregate_panel = enrich_with_rankings_volume(
        aggregate_panel, rankings_json, cfg.model_registry
    )
    n_with_volume = int((aggregate_panel["volume_mtok_7d"] > 0).sum())
    print(
        f"  {n_with_volume}/{len(aggregate_panel)} aggregate rows enriched "
        f"with rankings volume"
    )

    print("\nFetching per-model endpoints...")
    endpoint_frames: list[pd.DataFrame] = []
    n_endpoints_calls = 0
    for m in cfg.model_registry.models:
        if not (m.openrouter_author and m.openrouter_slug):
            continue
        endpoints_json = fetch_model_endpoints(
            m.openrouter_author, m.openrouter_slug, as_of_date=as_of
        )
        n_endpoints_calls += 1
        ep_panel = normalise_endpoints_to_panel(
            endpoints_json, m.constituent_id, m.tier, as_of
        )
        endpoint_frames.append(ep_panel)
    if endpoint_frames:
        endpoints_panel = pd.concat(endpoint_frames, ignore_index=True)
    else:
        endpoints_panel = aggregate_panel.iloc[0:0].copy()  # empty, same schema
    print(
        f"  {n_endpoints_calls} /endpoints fetches; {len(endpoints_panel)} "
        f"per-provider rows"
    )

    full_panel = pd.concat(
        [aggregate_panel, endpoints_panel], ignore_index=True
    )
    PanelObservationDF.validate(full_panel)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        args.output_dir / f"openrouter_panel_{as_of.isoformat()}.parquet"
    )
    full_panel.to_parquet(output_path, index=False)

    _print_summary(
        full_panel=full_panel,
        aggregate_panel=aggregate_panel,
        endpoints_panel=endpoints_panel,
        registry=cfg.model_registry,
        output_path=output_path,
    )
    return 0


def _print_summary(
    *,
    full_panel: pd.DataFrame,
    aggregate_panel: pd.DataFrame,
    endpoints_panel: pd.DataFrame,
    registry: object,  # ModelRegistry; loose-typed to avoid extra import
    output_path: Path,
) -> None:
    print()
    print(f"Wrote {output_path}  ({len(full_panel):,} rows)")

    n_registry = len(getattr(registry, "models", []))
    matched_constituents = set(aggregate_panel["constituent_id"])
    all_constituents = {
        m.constituent_id for m in getattr(registry, "models", [])
    }
    unmatched = sorted(all_constituents - matched_constituents)

    print()
    print(
        f"Match rate: {len(matched_constituents)}/{n_registry} "
        f"registry constituents have an OpenRouter aggregate row"
    )
    if unmatched:
        print(f"  unmatched: {unmatched}")

    print()
    print("Mean output price by tier (Tier C aggregate rows, USD/Mtok):")
    by_tier = aggregate_panel.groupby("tier_code")[
        "output_price_usd_mtok"
    ].mean()
    for tier, mean_price in by_tier.items():
        print(f"  {tier}: ${mean_price:.4f}/Mtok")

    print()
    n_provider_rows = len(endpoints_panel)
    if n_provider_rows > 0:
        n_constituents_with_endpoints = endpoints_panel["constituent_id"].nunique()
        avg_providers = n_provider_rows / n_constituents_with_endpoints
        print(
            f"Per-provider rows: {n_provider_rows} across "
            f"{n_constituents_with_endpoints} constituents "
            f"(avg {avg_providers:.1f} providers per constituent)"
        )

    print()
    print("Volume coverage (rankings-derived):")
    n_with_volume = int((aggregate_panel["volume_mtok_7d"] > 0).sum())
    n_total = len(aggregate_panel)
    print(
        f"  {n_with_volume} of {n_total} aggregate rows have non-zero volume"
    )
    if n_with_volume > 0:
        with_vol = aggregate_panel[aggregate_panel["volume_mtok_7d"] > 0]
        for _, row in with_vol.iterrows():
            print(
                f"    {row['constituent_id']:<35} "
                f"{row['volume_mtok_7d']:>14,.1f} mtok/7d"
            )


if __name__ == "__main__":
    raise SystemExit(main())
