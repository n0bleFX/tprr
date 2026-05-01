"""Shared loader for the canonical seed-N pipeline baseline.

The Phase 10 in-memory sweeps all start from the same input: run the full
pipeline at the canonical config to produce ``constituent_decisions`` +
``indices``, then recompute under parameter overrides. This loader
centralises the pipeline-input plumbing so individual driver scripts
(``scripts/lambda_sweep.py`` etc.) stay thin.

The loading pattern matches ``scripts/plot_indices.py`` and
``scripts/compute_indices.py`` — Tier A from local mock-data parquet, Tier
C from the cached OpenRouter snapshot, Tier B derived per-date from
``config/tier_b_revenue.yaml``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from tprr.config import (
    IndexConfig,
    ModelRegistry,
    load_index_config,
    load_model_registry,
    load_tier_b_revenue,
)
from tprr.index.compute import FullPipelineResults, run_full_pipeline
from tprr.index.tier_b import derive_tier_b_volumes
from tprr.index.weights import TierBVolumeFn
from tprr.reference.openrouter import (
    enrich_with_rankings_volume,
    fetch_models,
    fetch_rankings,
    normalise_models_to_panel,
)


def load_baseline(
    *,
    seed: int = 42,
    start: date | None = None,
    end: date | None = None,
) -> tuple[FullPipelineResults, IndexConfig]:
    """Load disk inputs and run the canonical pipeline.

    Returns the ``FullPipelineResults`` (with ``constituent_decisions`` +
    ``indices`` ready for sensitivity recompute) plus the canonical
    ``IndexConfig`` used to drive the run.
    """
    config = load_index_config()
    registry = load_model_registry()
    tier_b_config = load_tier_b_revenue()

    tier_a_panel, change_events = _load_tier_a_panel(seed)
    tier_c_panel = _load_tier_c_panel(registry)

    range_start = start if start else tier_a_panel["observation_date"].min().date()
    range_end = end if end else config.base_date

    rankings_dates = sorted(p.stem for p in Path("data/raw/openrouter/rankings").glob("*.json"))
    rankings_json = fetch_rankings(as_of_date=date.fromisoformat(rankings_dates[-1]))
    rankings_df = _rankings_json_to_df(rankings_json)

    days = pd.date_range(range_start, range_end, freq="D")
    tier_b_by_date: dict[pd.Timestamp, pd.DataFrame] = {}
    for ts in days:
        d = ts.date()
        tier_a_slice = tier_a_panel[tier_a_panel["observation_date"] == ts]
        tier_b_by_date[ts] = derive_tier_b_volumes(
            as_of_date=d,
            panel_df=tier_a_slice,
            openrouter_rankings_df=rankings_df,
            tier_b_revenue_config=tier_b_config,
            model_registry=registry,
        )
    tier_b_volume_fn = _tier_b_volume_fn_factory(tier_b_by_date)

    composed = []
    for ts in days:
        d = ts.date()
        a_slice = tier_a_panel[tier_a_panel["observation_date"] == ts].copy()
        c_slice = tier_c_panel.copy()
        if not c_slice.empty:
            c_slice["observation_date"] = ts
        b_slice = tier_b_by_date[ts].copy()
        if not b_slice.empty:
            b_slice["observation_date"] = ts
        composed.append(pd.concat([a_slice, b_slice, c_slice], ignore_index=True))
    full_panel = pd.concat(composed, ignore_index=True)

    pipeline = run_full_pipeline(
        panel_df=full_panel,
        change_events_df=change_events,
        config=config,
        registry=registry,
        tier_b_config=tier_b_config,
        tier_b_volume_fn=tier_b_volume_fn,
    )
    return pipeline, config


def _load_tier_a_panel(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel_path = Path(f"data/raw/mock_panel_clean_seed{seed}.parquet")
    events_path = Path(f"data/raw/mock_change_events_clean_seed{seed}.parquet")
    return pd.read_parquet(panel_path), pd.read_parquet(events_path)


def _load_tier_c_panel(registry: ModelRegistry) -> pd.DataFrame:
    cache_dates = sorted(p.stem for p in Path("data/raw/openrouter/models").glob("*.json"))
    if not cache_dates:
        raise FileNotFoundError(
            "No cached OpenRouter models snapshot under data/raw/openrouter/models/. "
            "Run scripts/fetch_openrouter.py first."
        )
    snapshot_date = date.fromisoformat(cache_dates[-1])
    models_json = fetch_models(as_of_date=snapshot_date)
    rankings_json = fetch_rankings(as_of_date=snapshot_date)
    panel = normalise_models_to_panel(models_json, registry, snapshot_date)
    panel = enrich_with_rankings_volume(panel, rankings_json, registry)
    return panel


def _rankings_json_to_df(rankings_json: dict[str, object]) -> pd.DataFrame:
    items = rankings_json.get("models", [])
    if not isinstance(items, list):
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
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
        cid = f"{author}/{slug}" if author and "/" not in str(slug) else slug
        rows.append({"constituent_id": cid, "volume_mtok_7d": volume_mtok})
    return pd.DataFrame(rows)


def _tier_b_volume_fn_factory(
    tier_b_panels_by_date: dict[pd.Timestamp, pd.DataFrame],
) -> TierBVolumeFn:
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


__all__ = ["load_baseline"]
