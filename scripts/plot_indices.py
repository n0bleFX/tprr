"""Phase 9 — render the TPRR dashboard from the latest pipeline output.

Reads the Tier A panel + change events from ``data/raw/``, the Tier C
snapshot from ``data/raw/openrouter/``, derives Tier B volumes per-date,
runs the full Phase 7 pipeline, and writes an HTML dashboard to
``data/indices/charts/{run_id}_dashboard.html``.

``run_id`` is derived deterministically from (version, lambda, ordering,
seed) so two invocations with the same parameters produce the same
filename. Phase 10 will produce dozens of dashboards under parameter
sweeps; trivial visual identification matters.

Usage::

    uv run python scripts/plot_indices.py [--seed 42] [--start YYYY-MM-DD]
        [--end YYYY-MM-DD]

Phase 9 batches:
- Batch A (current): scaffolds the script, renders 1 panel (TPRR_F)
- Batch B: full Group 1 (6 panels — F/S/E levels, FPR/SER, B-overlay)
- Batch C: Group 2 (tier weight share + n_constituents)
- Batch D: Group 3 (scenario overlays vs clean baseline)
- Batch E: close-out

The disk-loading helpers below mirror ``scripts/compute_indices.py``;
Phase 9 close-out may extract a shared library entry point if the
duplication grows.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from tprr.config import (
    IndexConfig,
    ModelRegistry,
    TierBRevenueConfig,
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
from tprr.viz.charts import (
    build_blended_overlay_subplot,
    build_index_level_subplot,
    build_n_constituents_subplot,
    build_ratio_subplot,
    build_tier_share_subplot,
)
from tprr.viz.dashboard import PanelSpec, plot_tprr_dashboard


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument(
        "--output-dir",
        type=str,
        default="data/indices/charts",
        help="Directory to write HTML dashboards into.",
    )
    return p.parse_args()


def _load_tier_a_panel(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel_path = Path(f"data/raw/mock_panel_clean_seed{seed}.parquet")
    events_path = Path(f"data/raw/mock_change_events_clean_seed{seed}.parquet")
    return pd.read_parquet(panel_path), pd.read_parquet(events_path)


def _rankings_json_to_df(rankings_json: dict[str, object]) -> pd.DataFrame:
    items = rankings_json.get("models", [])
    if not isinstance(items, list):
        return pd.DataFrame()
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


def _load_tier_c_panel(registry: ModelRegistry) -> pd.DataFrame:
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


def _compose_panel_for_date(
    *,
    tier_a_panel: pd.DataFrame,
    tier_c_panel: pd.DataFrame,
    tier_b_panel: pd.DataFrame,
    as_of_date: date,
) -> pd.DataFrame:
    ts = pd.Timestamp(as_of_date)
    a_slice = tier_a_panel[tier_a_panel["observation_date"] == ts].copy()
    c_slice = tier_c_panel.copy()
    if not c_slice.empty:
        c_slice["observation_date"] = ts
    b_slice = tier_b_panel.copy()
    if not b_slice.empty:
        b_slice["observation_date"] = ts
    return pd.concat([a_slice, b_slice, c_slice], ignore_index=True)


def run_pipeline_from_disk(
    *,
    seed: int,
    config: IndexConfig,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    start: date | None = None,
    end: date | None = None,
) -> FullPipelineResults:
    """Load all input data from disk, derive Tier B, compose, run pipeline.

    Library-style entry point: callers pass already-loaded config/registry
    /tier_b_config and get back ``FullPipelineResults``. Mirrors the
    pipeline-running portion of ``scripts/compute_indices.py:main()``.
    """
    tier_a_panel, change_events = _load_tier_a_panel(seed)
    tier_c_panel = _load_tier_c_panel(registry)

    range_start = start if start else tier_a_panel["observation_date"].min().date()
    range_end = end if end else config.base_date

    rankings_dates = sorted(
        p.stem for p in Path("data/raw/openrouter/rankings").glob("*.json")
    )
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

    composed_per_date = [
        _compose_panel_for_date(
            tier_a_panel=tier_a_panel,
            tier_c_panel=tier_c_panel,
            tier_b_panel=tier_b_by_date[ts],
            as_of_date=ts.date(),
        )
        for ts in days
    ]
    full_panel = pd.concat(composed_per_date, ignore_index=True)

    return run_full_pipeline(
        panel_df=full_panel,
        change_events_df=change_events,
        config=config,
        registry=registry,
        tier_b_config=tier_b_config,
        tier_b_volume_fn=tier_b_volume_fn,
    )


def build_run_id(*, config: IndexConfig, seed: int, ordering: str) -> str:
    """Deterministic identifier from (lambda, ordering, seed, base_date).

    Reading order keeps the lambda value first since Phase 10 sweeps will
    vary it across many dashboards; lambda-first scans visually fastest
    when tabulated.
    """
    return (
        f"v0_1_lambda{config.lambda_:.1f}_{ordering}_seed{seed}"
        f"_base{config.base_date.isoformat()}"
    )


def build_dashboard_subtitle(*, config: IndexConfig, ordering: str) -> str:
    return (
        "Synthetic contributor data · OpenRouter Tier C reference · "
        f"Methodology v1.2 · λ={config.lambda_:.1f} · ordering={ordering} · "
        f"Base {config.base_date.isoformat()}"
    )


def main() -> int:
    args = parse_args()
    config = load_index_config()
    registry = load_model_registry()
    tier_b_config = load_tier_b_revenue()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(
        f"Running pipeline (seed={args.seed}, "
        f"ordering={config.default_ordering})...",
        flush=True,
    )
    pipeline = run_pipeline_from_disk(
        seed=args.seed,
        config=config,
        registry=registry,
        tier_b_config=tier_b_config,
        start=start,
        end=end,
    )

    ordering = config.default_ordering
    run_id = build_run_id(config=config, seed=args.seed, ordering=ordering)
    subtitle = build_dashboard_subtitle(config=config, ordering=ordering)

    # Group 1 (Batch B): three core tier levels (row 1) + two ratio
    # indices and one blended overlay (row 2). 2x3 grid. Subsequent
    # batches append rows below for tier-share / n_constituents / scenarios.
    panels: list[PanelSpec] = [
        PanelSpec(
            title="TPRR-F (Frontier) — index level",
            row=1,
            col=1,
            builder=lambda fig, row, col: build_index_level_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_F"],
                index_code="TPRR_F",
            ),
        ),
        PanelSpec(
            title="TPRR-S (Standard) — index level",
            row=1,
            col=2,
            builder=lambda fig, row, col: build_index_level_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_S"],
                index_code="TPRR_S",
            ),
        ),
        PanelSpec(
            title="TPRR-E (Efficiency) — index level",
            row=1,
            col=3,
            builder=lambda fig, row, col: build_index_level_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_E"],
                index_code="TPRR_E",
            ),
        ),
        PanelSpec(
            title="TPRR-FPR — Frontier Premium Ratio (F / S)",
            row=2,
            col=1,
            builder=lambda fig, row, col: build_ratio_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_FPR"],
                index_code="TPRR_FPR",
            ),
        ),
        PanelSpec(
            title="TPRR-SER — Standard Efficiency Ratio (S / E)",
            row=2,
            col=2,
            builder=lambda fig, row, col: build_ratio_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_SER"],
                index_code="TPRR_SER",
            ),
        ),
        PanelSpec(
            title="TPRR-F vs TPRR-B-F — output vs blended (Frontier)",
            row=2,
            col=3,
            builder=lambda fig, row, col: build_blended_overlay_subplot(
                fig,
                row=row,
                col=col,
                core_df=pipeline.indices["TPRR_F"],
                blended_df=pipeline.indices["TPRR_B_F"],
                core_code="TPRR_F",
                blended_code="TPRR_B_F",
            ),
        ),
        # Group 2 (Batch C): tier weight share row + n_constituents row.
        # Row 3: stacked area showing the cross-tier cascade per tier.
        # Row 4: per-attestation constituent counts + total active line.
        PanelSpec(
            title="TPRR-F — tier weight share (A / B / C)",
            row=3,
            col=1,
            builder=lambda fig, row, col: build_tier_share_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_F"],
                tier_code="TPRR_F",
            ),
        ),
        PanelSpec(
            title="TPRR-S — tier weight share (A / B / C)",
            row=3,
            col=2,
            builder=lambda fig, row, col: build_tier_share_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_S"],
                tier_code="TPRR_S",
            ),
        ),
        PanelSpec(
            title="TPRR-E — tier weight share (A / B / C)",
            row=3,
            col=3,
            builder=lambda fig, row, col: build_tier_share_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_E"],
                tier_code="TPRR_E",
            ),
        ),
        PanelSpec(
            title="TPRR-F — active constituent count",
            row=4,
            col=1,
            builder=lambda fig, row, col: build_n_constituents_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_F"],
                tier_code="TPRR_F",
            ),
        ),
        PanelSpec(
            title="TPRR-S — active constituent count",
            row=4,
            col=2,
            builder=lambda fig, row, col: build_n_constituents_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_S"],
                tier_code="TPRR_S",
            ),
        ),
        PanelSpec(
            title="TPRR-E — active constituent count",
            row=4,
            col=3,
            builder=lambda fig, row, col: build_n_constituents_subplot(
                fig,
                row=row,
                col=col,
                indices_df=pipeline.indices["TPRR_E"],
                tier_code="TPRR_E",
            ),
        ),
    ]

    output_path = Path(args.output_dir) / f"{run_id}_dashboard.html"
    plot_tprr_dashboard(
        panels=panels,
        run_id=run_id,
        output_path=output_path,
        title="TPRR Index — v0.1 Backtest",
        subtitle=subtitle,
    )
    print(f"Wrote dashboard to {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
