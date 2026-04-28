"""End-to-end TPRR index compute pipeline — Phase 7.

Batch A scope: TPRR_F only, TWAP-then-weight ordering, clean panel
(``data/raw/mock_panel_clean_seed42.parquet``). Composes the multi-tier
panel (Tier A from disk + Tier B derived per-date + Tier C from
OpenRouter), runs Phase 6 quality gate, Phase 2c TWAP reconstruction,
then Phase 7 dual-weighted aggregation.

Usage:
    uv run python scripts/compute_indices.py [--seed 42] [--end YYYY-MM-DD]
        [--start YYYY-MM-DD] [--summary-only]

Output: prints a one-line summary per date in the requested range. With
``--summary-only`` (default for Batch A), prints only the first valid fix
plus a tier-share / constituent-share breakdown for inspection.

Subsequent batches will:
  * Batch B — extend to TPRR_S, TPRR_E + rebase to 100 on 2026-01-01.
  * Batch B' — TPRR_B blended (0.25*P_in + 0.75*P_out).
  * Batch C — suspension consumption + fallback fall-through.
  * Batch D — SQLite + parquet persistence.
  * Batch E — weight-then-TWAP alternate ordering.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tprr.config import (
    ModelRegistry,
    load_index_config,
    load_model_registry,
    load_tier_b_revenue,
)
from tprr.index.aggregation import compute_tier_index
from tprr.index.tier_b import derive_tier_b_volumes
from tprr.index.weights import TierBVolumeFn
from tprr.reference.openrouter import (
    enrich_with_rankings_volume,
    fetch_models,
    fetch_rankings,
    normalise_models_to_panel,
)
from tprr.schema import Tier
from tprr.twap.reconstruct import compute_panel_twap


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", type=str, default=None, help="ISO date; default = panel min")
    p.add_argument("--end", type=str, default=None, help="ISO date; default = panel min + 1 day")
    p.add_argument("--summary-only", action="store_true", default=True)
    p.add_argument("--no-summary-only", dest="summary_only", action="store_false")
    return p.parse_args()


def _load_tier_a_panel(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel_path = Path(f"data/raw/mock_panel_clean_seed{seed}.parquet")
    events_path = Path(f"data/raw/mock_change_events_clean_seed{seed}.parquet")
    return pd.read_parquet(panel_path), pd.read_parquet(events_path)


def _load_tier_c_panel(registry: ModelRegistry) -> pd.DataFrame:
    """Tier C panel from cached OpenRouter snapshots.

    Per decision_log.md 2026-04-28 ("Tier C historical backfill: option (a)
    static current snapshot"), the rankings + models snapshot is reused
    across the full backtest as a static structural proxy.
    """
    cache_dates = sorted(
        p.stem for p in Path("data/raw/openrouter/models").glob("*.json")
    )
    if not cache_dates:
        raise FileNotFoundError(
            "No cached OpenRouter models snapshot under data/raw/openrouter/models/. "
            "Run scripts/fetch_openrouter.py first."
        )
    snapshot_date = date.fromisoformat(cache_dates[-1])
    models_json = fetch_models(as_of_date=snapshot_date)
    rankings_json = fetch_rankings(as_of_date=snapshot_date)
    rankings_df = _rankings_json_to_df(rankings_json)
    panel = normalise_models_to_panel(models_json, registry, snapshot_date)
    panel = enrich_with_rankings_volume(panel, rankings_df, registry)
    return panel


def _rankings_json_to_df(rankings_json: dict[str, object]) -> pd.DataFrame:
    """Flatten the rankings JSON to a (constituent_id-ish, volume_mtok_7d) DF.

    Matches the shape ``enrich_with_rankings_volume`` and
    ``derive_tier_b_volumes`` consume. Token counts arrive as integers; this
    converts to mtok (input + output / 1e6) and uses the slug as id; the
    Tier B / Tier C consumers handle author/slug matching via the registry.
    """
    items = rankings_json.get("models", [])
    rows = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("model_slug") or entry.get("slug") or entry.get("id")
        author = entry.get("author") or entry.get("model_author")
        if not slug:
            continue
        tokens = entry.get("total_tokens", 0) or 0
        try:
            volume_mtok = float(tokens) / 1e6
        except (TypeError, ValueError):
            continue
        cid = f"{author}/{slug}" if author and "/" not in slug else slug
        rows.append({"constituent_id": cid, "volume_mtok_7d": volume_mtok})
    return pd.DataFrame(rows)


def _tier_b_volume_fn_factory(
    tier_b_panels_by_date: dict[pd.Timestamp, pd.DataFrame],
) -> TierBVolumeFn:
    """Build a TierBVolumeFn that looks up volumes from pre-derived per-date Tier B panels."""

    def _fn(_provider: str, constituent_id: str, as_of_date: date) -> float:
        ts = pd.Timestamp(as_of_date)
        panel = tier_b_panels_by_date.get(ts)
        if panel is None or panel.empty:
            return 0.0
        match = panel[panel["constituent_id"] == constituent_id]
        if match.empty:
            return 0.0
        return float(match.iloc[0]["volume_mtok_7d"])

    return _fn


def compose_panel_for_date(
    *,
    tier_a_panel: pd.DataFrame,
    tier_c_panel: pd.DataFrame,
    tier_b_panel: pd.DataFrame,
    as_of_date: date,
) -> pd.DataFrame:
    """Compose a single-day multi-tier panel for compute_tier_index.

    Tier A: filtered to as_of_date from the multi-day mock panel.
    Tier B: pre-derived for as_of_date; observation_date set explicitly.
    Tier C: static snapshot reused across dates per DL 2026-04-28; the
            row-level observation_date is rewritten to as_of_date so the
            single-date filter inside compute_tier_index sees one date.
    """
    ts = pd.Timestamp(as_of_date)
    a_slice = tier_a_panel[tier_a_panel["observation_date"] == ts].copy()
    c_slice = tier_c_panel.copy()
    if not c_slice.empty:
        c_slice["observation_date"] = ts
    b_slice = tier_b_panel.copy()
    if not b_slice.empty:
        b_slice["observation_date"] = ts
    return pd.concat([a_slice, b_slice, c_slice], ignore_index=True)


def main() -> int:
    args = parse_args()
    config = load_index_config()
    registry = load_model_registry()
    tier_b_config = load_tier_b_revenue()

    print("Loading Tier A panel + change events...", flush=True)
    tier_a_panel, change_events = _load_tier_a_panel(args.seed)
    print(
        f"  panel: {len(tier_a_panel):,} rows | "
        f"events: {len(change_events):,} rows | "
        f"date range: "
        f"{tier_a_panel['observation_date'].min().date()} -> "
        f"{tier_a_panel['observation_date'].max().date()}",
        flush=True,
    )

    print("Loading Tier C panel from OpenRouter cache...", flush=True)
    tier_c_panel = _load_tier_c_panel(registry)
    print(
        f"  tier C constituents: {tier_c_panel['constituent_id'].nunique()}",
        flush=True,
    )

    start = date.fromisoformat(args.start) if args.start else tier_a_panel["observation_date"].min().date()
    end = date.fromisoformat(args.end) if args.end else start + timedelta(days=1)

    rankings_json = fetch_rankings(
        as_of_date=date.fromisoformat(
            sorted(p.stem for p in Path("data/raw/openrouter/rankings").glob("*.json"))[-1]
        )
    )
    rankings_df = _rankings_json_to_df(rankings_json)

    days = pd.date_range(start, end, freq="D")
    tier_b_by_date: dict[pd.Timestamp, pd.DataFrame] = {}
    for ts in days:
        d = ts.date()
        tier_a_slice_for_b = tier_a_panel[tier_a_panel["observation_date"] == ts]
        tier_b_by_date[ts] = derive_tier_b_volumes(
            as_of_date=d,
            panel_df=tier_a_slice_for_b,
            openrouter_rankings_df=rankings_df,
            tier_b_revenue_config=tier_b_config,
            model_registry=registry,
        )

    tier_b_volume_fn = _tier_b_volume_fn_factory(tier_b_by_date)

    print(f"\nRunning TPRR_F aggregation from {start} to {end} (TWAP-then-weight)", flush=True)
    print("=" * 70, flush=True)
    prior_raw_value: float | None = None
    first_valid: dict[str, object] | None = None
    for ts in days:
        d = ts.date()
        composed = compose_panel_for_date(
            tier_a_panel=tier_a_panel,
            tier_c_panel=tier_c_panel,
            tier_b_panel=tier_b_by_date[ts],
            as_of_date=d,
        )
        composed_with_twap = compute_panel_twap(composed, change_events)
        result = compute_tier_index(
            panel_day_df=composed_with_twap,
            tier=Tier.TPRR_F,
            config=config,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
            prior_raw_value=prior_raw_value,
        )
        if not result["suspended"]:
            prior_raw_value = float(result["raw_value_usd_mtok"])
            if first_valid is None:
                first_valid = result
        _print_result(result)

    if first_valid is not None and args.summary_only:
        print("\n" + "=" * 70)
        print("First valid TPRR_F fix:")
        print(json.dumps(_jsonable(first_valid), indent=2, default=str))
    return 0


def _print_result(result: dict[str, object]) -> None:
    d = result["as_of_date"]
    susp = "SUSPENDED" if result["suspended"] else "         "
    raw = result["raw_value_usd_mtok"]
    raw_str = f"${raw:.4f}/Mtok" if isinstance(raw, float) and raw == raw else "      NaN"
    n_a = result["n_constituents_a"]
    n_b = result["n_constituents_b"]
    n_c = result["n_constituents_c"]
    wa = result["tier_a_weight_share"]
    wb = result["tier_b_weight_share"]
    wc = result["tier_c_weight_share"]
    print(
        f"{d}  {susp}  {raw_str:>20}  "
        f"n=A{n_a}/B{n_b}/C{n_c}  "
        f"w=A{wa:.3f}/B{wb:.3f}/C{wc:.3f}  "
        f"{result['suspension_reason']}"
    )


def _jsonable(obj: dict[str, object]) -> dict[str, object]:
    return {k: (v if not hasattr(v, "isoformat") else v.isoformat()) for k, v in obj.items()}


if __name__ == "__main__":
    raise SystemExit(main())
