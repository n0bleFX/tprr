"""End-to-end TPRR index compute pipeline — Phase 7.

Batch A scope: TPRR_F only, TWAP-then-weight ordering, clean panel.
Batch B scope: all 3 core tiers (F/S/E) + derived (FPR, SER), rebased to
100 on the configured base_date. Composes the multi-tier panel (Tier A
from disk + Tier B derived per-date + Tier C from OpenRouter), runs
Phase 2c TWAP reconstruction, then Phase 7 dual-weighted aggregation.

Usage:
    uv run python scripts/compute_indices.py [--seed 42] [--start YYYY-MM-DD]
        [--end YYYY-MM-DD]

Output: prints a one-line summary per (index, date) in the requested
range, plus a per-index "first valid fix" report at the end with the
rebase anchor metadata.

Subsequent batches will:
  * Batch B' — TPRR_B blended (0.25*P_in + 0.75*P_out).
  * Batch C — suspension consumption + fallback fall-through.
  * Batch D — SQLite + parquet persistence.
  * Batch E — weight-then-TWAP alternate ordering.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from tprr.config import (
    ModelRegistry,
    load_index_config,
    load_model_registry,
    load_tier_b_revenue,
)
from tprr.index.aggregation import compute_tier_index, rebase_index_level
from tprr.index.derived import compute_fpr, compute_ser
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
    p.add_argument(
        "--end",
        type=str,
        default=None,
        help="ISO date; default = base_date (first valid fix proof + rebase exercise)",
    )
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
    end = date.fromisoformat(args.end) if args.end else config.base_date

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

    print(
        f"\nRunning core indices (TPRR_F/S/E) + derived (FPR/SER) from "
        f"{start} to {end} (TWAP-then-weight)",
        flush=True,
    )
    print("=" * 90, flush=True)
    prior_raw_value: dict[str, float | None] = {
        "TPRR_F": None,
        "TPRR_S": None,
        "TPRR_E": None,
    }
    rows_per_index: dict[str, list[dict[str, Any]]] = {
        "TPRR_F": [],
        "TPRR_S": [],
        "TPRR_E": [],
    }
    for ts in days:
        d = ts.date()
        composed = compose_panel_for_date(
            tier_a_panel=tier_a_panel,
            tier_c_panel=tier_c_panel,
            tier_b_panel=tier_b_by_date[ts],
            as_of_date=d,
        )
        composed_with_twap = compute_panel_twap(composed, change_events)
        for tier in (Tier.TPRR_F, Tier.TPRR_S, Tier.TPRR_E):
            result = compute_tier_index(
                panel_day_df=composed_with_twap,
                tier=tier,
                config=config,
                registry=registry,
                tier_b_config=tier_b_config,
                tier_b_volume_fn=tier_b_volume_fn,
                prior_raw_value=prior_raw_value[tier.value],
            )
            if not result["suspended"]:
                prior_raw_value[tier.value] = float(result["raw_value_usd_mtok"])
            rows_per_index[tier.value].append(result)

    rebased: dict[str, pd.DataFrame] = {}
    anchors: dict[str, date | None] = {}
    for code, rows in rows_per_index.items():
        df = pd.DataFrame(rows)
        df["as_of_date"] = pd.to_datetime(df["as_of_date"]).astype("datetime64[ns]")
        df_rebased, anchor = rebase_index_level(df, base_date=config.base_date)
        rebased[code] = df_rebased
        anchors[code] = anchor

    fpr_df, anchors["TPRR_FPR"] = compute_fpr(rebased["TPRR_F"], rebased["TPRR_S"], config)
    ser_df, anchors["TPRR_SER"] = compute_ser(rebased["TPRR_S"], rebased["TPRR_E"], config)
    rebased["TPRR_FPR"] = fpr_df
    rebased["TPRR_SER"] = ser_df

    print("\nFirst valid fix per index:")
    print("-" * 90)
    for code, df in rebased.items():
        if df.empty:
            print(f"  {code}: empty result")
            continue
        valid = df[~df["suspended"]]
        if valid.empty:
            print(f"  {code}: NO valid fix in range")
            continue
        first = valid.iloc[0]
        print(
            f"  {code:10s}  first_valid={pd.Timestamp(first['as_of_date']).date()}  "
            f"raw={float(first['raw_value_usd_mtok']):>12.4f}  "
            f"index_level={float(first['index_level']):>10.4f}  "
            f"anchor={anchors[code]}  "
            f"n=A{int(first['n_constituents_a'])}/B{int(first['n_constituents_b'])}/C{int(first['n_constituents_c'])}  "
            f"w=A{float(first['tier_a_weight_share']):.3f}/B{float(first['tier_b_weight_share']):.3f}/C{float(first['tier_c_weight_share']):.3f}"
        )

    print("\nValue at base_date (anchor day; rebase target = 100):")
    print("-" * 90)
    base_ts = pd.Timestamp(config.base_date)
    for code, df in rebased.items():
        if df.empty:
            continue
        match = df[df["as_of_date"] == base_ts]
        if match.empty:
            continue
        r = match.iloc[0]
        susp_str = "[SUSP]" if bool(r["suspended"]) else "      "
        print(
            f"  {code:10s}  {susp_str}  raw={float(r['raw_value_usd_mtok']):>12.4f}  "
            f"index_level={float(r['index_level']):>10.4f}  "
            f"reason={r['suspension_reason'] or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
