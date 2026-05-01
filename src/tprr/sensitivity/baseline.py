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

Phase 10 Batch 10B added ``BaselineInputs`` and ``run_pipeline_at_config``
so pipeline-rerun sweeps can load disk inputs once and re-run the
pipeline with different ``IndexConfig`` overrides without paying the
load-and-derive cost on every sweep point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from tprr.config import (
    ContributorPanel,
    IndexConfig,
    ModelRegistry,
    ScenarioEntry,
    TierBRevenueConfig,
    load_contributors,
    load_index_config,
    load_model_registry,
    load_scenarios,
    load_tier_b_revenue,
)
from tprr.index.compute import FullPipelineResults, run_full_pipeline
from tprr.index.tier_b import derive_tier_b_volumes
from tprr.index.weights import TierBVolumeFn
from tprr.mockdata.outliers import ScenarioManifest
from tprr.mockdata.scenarios import compose_scenario
from tprr.reference.openrouter import (
    enrich_with_rankings_volume,
    fetch_models,
    fetch_rankings,
    normalise_models_to_panel,
)


@dataclass
class BaselineInputs:
    """Disk-loaded pipeline inputs reusable across multiple pipeline runs.

    Phase 10 Batch 10B: pipeline-rerun sweeps load these once and re-run
    ``run_pipeline_at_config`` per parameter point. Re-deriving Tier B
    volumes per-date and re-loading parquet files for every sweep point
    would dominate the per-run cost; this dataclass amortises the load.

    Tier B volumes are *not* pre-derived here because scenarios that
    perturb the Tier A panel must re-derive Tier B from the perturbed
    panel. Use ``run_pipeline_at_config`` to derive + run; or
    ``run_pipeline_with_scenario`` to compose a scenario then derive +
    run.
    """

    tier_a_panel: pd.DataFrame
    change_events: pd.DataFrame
    tier_c_panel: pd.DataFrame
    rankings_df: pd.DataFrame
    registry: ModelRegistry
    tier_b_config: TierBRevenueConfig
    contributors: ContributorPanel
    scenarios_by_id: dict[str, ScenarioEntry]
    range_start: date
    range_end: date


def load_pipeline_inputs(
    *,
    seed: int = 42,
    start: date | None = None,
    end: date | None = None,
) -> BaselineInputs:
    """Load all pipeline inputs from disk into a reusable container.

    ``range_start`` defaults to the panel's earliest observation date;
    ``range_end`` defaults to the canonical ``IndexConfig.base_date``
    (so sweep runs cover the full backtest window like Phase 9).
    """
    config = load_index_config()
    registry = load_model_registry()
    tier_b_config = load_tier_b_revenue()
    contributors = load_contributors()
    scenarios_config = load_scenarios()

    tier_a_panel, change_events = _load_tier_a_panel(seed)
    tier_c_panel = _load_tier_c_panel(registry)

    range_start = start if start else tier_a_panel["observation_date"].min().date()
    range_end = end if end else config.base_date

    rankings_dates = sorted(p.stem for p in Path("data/raw/openrouter/rankings").glob("*.json"))
    rankings_json = fetch_rankings(as_of_date=date.fromisoformat(rankings_dates[-1]))
    rankings_df = _rankings_json_to_df(rankings_json)

    return BaselineInputs(
        tier_a_panel=tier_a_panel,
        change_events=change_events,
        tier_c_panel=tier_c_panel,
        rankings_df=rankings_df,
        registry=registry,
        tier_b_config=tier_b_config,
        contributors=contributors,
        scenarios_by_id={s.id: s for s in scenarios_config.scenarios},
        range_start=range_start,
        range_end=range_end,
    )


def run_pipeline_at_config(
    inputs: BaselineInputs,
    config: IndexConfig,
    *,
    tier_a_panel_override: pd.DataFrame | None = None,
    change_events_override: pd.DataFrame | None = None,
    registry_override: ModelRegistry | None = None,
    ordering: str | None = None,
) -> FullPipelineResults:
    """Compose multi-tier panel + run the full pipeline using ``config``.

    ``tier_a_panel_override`` and ``change_events_override`` allow a
    scenario-composed panel to be substituted for the canonical Tier A
    inputs (used by ``run_pipeline_with_scenario``). ``registry_override``
    handles scenarios that mutate the model registry (e.g. constituent
    addition). ``ordering`` overrides the config's default ordering when
    set — the TWAP-ordering sweep (Batch 10B) uses this to drive both
    ``twap_then_weight`` and ``weight_then_twap`` runs from the same
    config.
    """
    panel = inputs.tier_a_panel if tier_a_panel_override is None else tier_a_panel_override
    events = inputs.change_events if change_events_override is None else change_events_override
    registry = inputs.registry if registry_override is None else registry_override

    days = pd.date_range(inputs.range_start, inputs.range_end, freq="D")
    tier_b_by_date: dict[pd.Timestamp, pd.DataFrame] = {}
    for ts in days:
        d = ts.date()
        a_slice = panel[panel["observation_date"] == ts]
        tier_b_by_date[ts] = derive_tier_b_volumes(
            as_of_date=d,
            panel_df=a_slice,
            openrouter_rankings_df=inputs.rankings_df,
            tier_b_revenue_config=inputs.tier_b_config,
            model_registry=registry,
        )
    tier_b_volume_fn = _tier_b_volume_fn_factory(tier_b_by_date)

    composed = []
    for ts in days:
        a_slice = panel[panel["observation_date"] == ts].copy()
        c_slice = inputs.tier_c_panel.copy()
        if not c_slice.empty:
            c_slice["observation_date"] = ts
        b_slice = tier_b_by_date[ts].copy()
        if not b_slice.empty:
            b_slice["observation_date"] = ts
        composed.append(pd.concat([a_slice, b_slice, c_slice], ignore_index=True))
    full_panel = pd.concat(composed, ignore_index=True)

    return run_full_pipeline(
        panel_df=full_panel,
        change_events_df=events,
        config=config,
        registry=registry,
        tier_b_config=inputs.tier_b_config,
        tier_b_volume_fn=tier_b_volume_fn,
        ordering=ordering or config.default_ordering,
    )


def run_pipeline_with_scenario(
    inputs: BaselineInputs,
    config: IndexConfig,
    scenario: ScenarioEntry,
    *,
    seed: int,
    ordering: str | None = None,
) -> FullPipelineResults:
    """Compose ``scenario`` on top of the clean Tier A panel + events,
    then re-derive Tier B from the composed panel and run the full
    pipeline. Mirrors ``scripts/plot_indices.py``'s
    ``compose_and_run_scenario``.
    """
    manifest = ScenarioManifest(scenario_id=str(scenario.id), seed=seed)
    panel_out, events_out, registry_out = compose_scenario(
        spec=scenario,
        panel_df=inputs.tier_a_panel,
        events_df=inputs.change_events,
        registry=inputs.registry,
        contributors=inputs.contributors,
        backtest_start=inputs.range_start,
        seed=seed,
        manifest=manifest,
    )
    return run_pipeline_at_config(
        inputs,
        config,
        tier_a_panel_override=panel_out,
        change_events_override=events_out,
        registry_override=registry_out,
        ordering=ordering,
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
    inputs = load_pipeline_inputs(seed=seed, start=start, end=end)
    config = load_index_config()
    pipeline = run_pipeline_at_config(inputs, config)
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


__all__ = [
    "BaselineInputs",
    "load_baseline",
    "load_pipeline_inputs",
    "run_pipeline_at_config",
    "run_pipeline_with_scenario",
]
