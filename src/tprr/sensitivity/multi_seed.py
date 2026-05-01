"""Multi-seed pipeline-rerun runner — Phase 10 Batch 10C.

Where Batch 10A's in-memory sweeps and Batch 10B's pipeline-rerun sweeps
characterise *parameter* sensitivity at a fixed seed, Batch 10C
characterises *seed* sensitivity at a fixed config: regenerate the Tier
A panel + change events under N different RNG seeds, run the canonical
pipeline against each, and analyse the resulting distribution.

Per-seed regeneration uses the same generator pipeline as
``scripts/generate_mock_data.py``: ``generate_baseline_prices`` →
``generate_contributor_panel`` → ``generate_volumes`` →
``generate_change_events`` → ``apply_twap_to_panel``. Seed-static
inputs (Tier C panel, OpenRouter rankings, registry, contributor panel,
Tier B revenue config) are loaded once via
``load_pipeline_inputs`` and reused across all per-seed runs.

Output shape mirrors Batch 10B: long-format parquet tagged with
``sweep_id``, ``parameter_label`` (the config label), ``seed``, and
optionally ``panel_id`` (clean or scenario id) for the
scenario-cross-product variant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tprr.config import IndexConfig
from tprr.mockdata.change_events import apply_twap_to_panel, generate_change_events
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.mockdata.volume import generate_volumes
from tprr.sensitivity.baseline import (
    BaselineInputs,
    run_pipeline_at_config,
    run_pipeline_with_scenario,
)
from tprr.sensitivity.manifest import upsert_manifest_row


@dataclass(frozen=True)
class MultiSeedRun:
    """One seed-realisation point in a multi-seed sweep.

    ``parameter_label`` is the config-variant identifier (e.g.
    ``"default"`` / ``"loose"`` / ``"tight"``); ``seed`` is the RNG
    seed for panel regeneration; ``panel_id`` is the panel identifier
    (``"clean"`` or a scenario id) and ``scenario_id`` is the
    registered scenario id when ``panel_id != "clean"``.
    """

    parameter_label: str
    new_config: IndexConfig
    seed: int
    panel_id: str = "clean"
    scenario_id: str | None = None


def regenerate_panel_for_seed(
    *,
    inputs: BaselineInputs,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Regenerate Tier A panel + change events for a new RNG seed.

    Mirrors ``scripts/generate_mock_data.py``: baseline prices →
    contributor panel → volumes → change events → TWAP-adjustment.
    Seed-static configs (registry, contributors, range) come from
    ``inputs``.
    """
    baseline, step_events = generate_baseline_prices(
        inputs.registry, inputs.range_start, inputs.range_end, seed
    )
    panel = generate_contributor_panel(baseline, inputs.contributors, inputs.registry, seed)
    panel = generate_volumes(panel, inputs.contributors, seed)
    events = generate_change_events(panel, step_events, inputs.registry, inputs.contributors, seed)
    panel = apply_twap_to_panel(panel, events)
    return panel, events


def _inputs_for_seed(inputs_static: BaselineInputs, seed: int) -> BaselineInputs:
    """Build a BaselineInputs whose Tier A panel + events are regenerated
    for ``seed`` while reusing ``inputs_static`` for everything else
    (Tier C, rankings, registry, contributors, range, scenarios).
    """
    panel, events = regenerate_panel_for_seed(inputs=inputs_static, seed=seed)
    return BaselineInputs(
        tier_a_panel=panel,
        change_events=events,
        tier_c_panel=inputs_static.tier_c_panel,
        rankings_df=inputs_static.rankings_df,
        registry=inputs_static.registry,
        tier_b_config=inputs_static.tier_b_config,
        contributors=inputs_static.contributors,
        scenarios_by_id=inputs_static.scenarios_by_id,
        range_start=inputs_static.range_start,
        range_end=inputs_static.range_end,
    )


def run_multi_seed_sweep(
    *,
    sweep_id: str,
    sweep_kind: str,
    parameter_dim: str,
    runs: list[MultiSeedRun],
    inputs_static: BaselineInputs,
    output_dir: Path,
    manifest_path: Path,
    base_audit_id: str,
    timestamp: datetime | None = None,
    progress: bool = True,
) -> Path:
    """Run a sequence of multi-seed pipeline runs and persist as one parquet.

    Each run's IndexValueDF rows are tagged with ``sweep_id``,
    ``parameter_label``, ``seed``, ``panel_id``, then concatenated into
    ``{output_dir}/{sweep_id}.parquet``. Audit rows write to
    ``{output_dir}/{sweep_id}_decisions.parquet``. Manifest row at
    ``manifest_path`` records sweep telemetry (median runtime + counts
    across all runs).

    Per-seed panel regeneration is cached within the call: if the same
    seed appears in multiple ``MultiSeedRun`` entries (e.g. clean +
    several scenarios at the same seed), the regenerated panel is
    reused without re-deriving.
    """
    if not runs:
        raise ValueError("run_multi_seed_sweep: runs list is empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    indices_path = output_dir / f"{sweep_id}.parquet"
    decisions_path = output_dir / f"{sweep_id}_decisions.parquet"

    indices_rows: list[pd.DataFrame] = []
    decisions_rows: list[pd.DataFrame] = []
    runtimes_s: list[float] = []
    base_date_active_counts: list[int] = []
    suspension_interval_counts: list[int] = []
    reinstatement_event_counts: list[int] = []

    seed_inputs_cache: dict[int, BaselineInputs] = {}

    for idx, run in enumerate(runs, start=1):
        if progress:
            print(
                f"  [{idx}/{len(runs)}] {run.parameter_label} seed={run.seed} "
                f"panel={run.panel_id}...",
                flush=True,
            )
        if run.seed not in seed_inputs_cache:
            seed_inputs_cache[run.seed] = _inputs_for_seed(inputs_static, run.seed)
        seed_inputs = seed_inputs_cache[run.seed]

        t0 = time.perf_counter()
        if run.scenario_id is None:
            pipeline = run_pipeline_at_config(seed_inputs, run.new_config)
        else:
            scenario = seed_inputs.scenarios_by_id.get(run.scenario_id)
            if scenario is None:
                raise KeyError(f"Scenario {run.scenario_id!r} not found in scenarios.yaml")
            pipeline = run_pipeline_with_scenario(
                seed_inputs, run.new_config, scenario, seed=run.seed
            )
        elapsed = time.perf_counter() - t0
        runtimes_s.append(elapsed)

        # Tag IndexValueDF rows.
        indices_concat = []
        for df in pipeline.indices.values():
            if df.empty:
                continue
            tagged = df.copy()
            tagged["sweep_id"] = sweep_id
            tagged["parameter_label"] = run.parameter_label
            tagged["seed"] = run.seed
            tagged["panel_id"] = run.panel_id
            indices_concat.append(tagged)
        if indices_concat:
            indices_rows.append(pd.concat(indices_concat, ignore_index=True))

        # Tag ConstituentDecisionDF rows.
        if not pipeline.constituent_decisions.empty:
            tagged_decisions = pipeline.constituent_decisions.copy()
            tagged_decisions["sweep_id"] = sweep_id
            tagged_decisions["parameter_label"] = run.parameter_label
            tagged_decisions["seed"] = run.seed
            tagged_decisions["panel_id"] = run.panel_id
            decisions_rows.append(tagged_decisions)

        # Telemetry.
        base_ts = pd.Timestamp(run.new_config.base_date)
        f_at_base = pipeline.indices.get("TPRR_F", pd.DataFrame())
        if not f_at_base.empty:
            match = f_at_base[f_at_base["as_of_date"] == base_ts]
            if not match.empty:
                base_date_active_counts.append(int(match.iloc[0]["n_constituents_active"]))
        susp = pipeline.suspended_pairs
        if susp is None or susp.empty:
            suspension_interval_counts.append(0)
            reinstatement_event_counts.append(0)
        else:
            suspension_interval_counts.append(len(susp))
            if "reinstatement_date" in susp.columns:
                reinstatement_event_counts.append(int(susp["reinstatement_date"].notna().sum()))
            else:
                reinstatement_event_counts.append(0)

    if not indices_rows:
        raise ValueError(f"run_multi_seed_sweep: every run produced empty output for {sweep_id!r}")
    indices_out = pd.concat(indices_rows, ignore_index=True)
    indices_out.to_parquet(indices_path)
    if decisions_rows:
        decisions_out = pd.concat(decisions_rows, ignore_index=True)
        decisions_out.to_parquet(decisions_path)
    else:
        pd.DataFrame().to_parquet(decisions_path)

    seeds_in_sweep = sorted({r.seed for r in runs})
    upsert_manifest_row(
        manifest_path,
        sweep_id=sweep_id,
        sweep_kind=sweep_kind,
        parameter_dim=parameter_dim,
        parameter_values=[r.parameter_label for r in runs],
        n_seeds=len(seeds_in_sweep),
        n_runs=len(runs),
        seed_min=min(seeds_in_sweep),
        seed_max=max(seeds_in_sweep),
        output_path=str(indices_path).replace("\\", "/"),
        base_audit_id=base_audit_id,
        n_rows=len(indices_out),
        timestamp=timestamp,
        pipeline_runtime_s=float(np.median(runtimes_s)) if runtimes_s else None,
        n_active_constituents_at_base_date=(
            int(np.median(base_date_active_counts)) if base_date_active_counts else None
        ),
        n_suspension_intervals=(
            int(np.median(suspension_interval_counts)) if suspension_interval_counts else None
        ),
        n_reinstatement_events=(
            int(np.median(reinstatement_event_counts)) if reinstatement_event_counts else None
        ),
    )
    return indices_path


def build_clean_panel_runs(
    *,
    parameter_label: str,
    config: IndexConfig,
    seeds: list[int],
) -> list[MultiSeedRun]:
    """Build clean-panel-only runs across ``seeds`` at a fixed config."""
    return [
        MultiSeedRun(
            parameter_label=parameter_label,
            new_config=config,
            seed=seed,
            panel_id="clean",
            scenario_id=None,
        )
        for seed in seeds
    ]


def build_clean_plus_scenario_runs(
    *,
    parameter_label: str,
    config: IndexConfig,
    seeds: list[int],
    scenario_ids: list[str],
) -> list[MultiSeedRun]:
    """Build (clean + N scenarios) per-seed runs at a fixed config.

    Per-seed grouping is preserved in the run order so the cache in
    ``run_multi_seed_sweep`` regenerates each seed's panel only once.
    """
    runs: list[MultiSeedRun] = []
    for seed in seeds:
        runs.append(
            MultiSeedRun(
                parameter_label=parameter_label,
                new_config=config,
                seed=seed,
                panel_id="clean",
                scenario_id=None,
            )
        )
        for scenario_id in scenario_ids:
            runs.append(
                MultiSeedRun(
                    parameter_label=parameter_label,
                    new_config=config,
                    seed=seed,
                    panel_id=scenario_id,
                    scenario_id=scenario_id,
                )
            )
    return runs
