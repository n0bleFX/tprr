"""Pipeline-rerun sweep runner — Phase 10 Batch 10B.

Where Batch 10A's in-memory sweeps recompute IndexValueDF rows from the
audit at zero pipeline cost, Batch 10B sweeps require a fresh
``run_full_pipeline`` per parameter point because the parameters affect
which constituents survive (suspension threshold, reinstatement
threshold) or how slot prices reconstruct (gate threshold, TWAP
ordering). The audit shape changes between runs, so the recompute path
isn't applicable.

The runner persists, per sweep:
- One IndexValueDF parquet (long-format, tagged with ``sweep_id``,
  ``parameter_label``, optionally ``panel_id`` for the TWAP-ordering
  sweep where each parameter point covers multiple panels)
- One ConstituentDecisionDF parquet capturing the audit per run

Per-sweep telemetry is written to ``manifest.csv`` via
``upsert_manifest_row`` with the four Batch 10B columns
(``pipeline_runtime_s``, ``n_active_constituents_at_base_date``,
``n_suspension_intervals``, ``n_reinstatement_events``) populated from
the median run in the sweep — Phase 11 reads the manifest as the
shape-of-the-sweep summary and per-run details are queried from the
parquet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from tprr.config import IndexConfig
from tprr.sensitivity.baseline import (
    BaselineInputs,
    run_pipeline_at_config,
    run_pipeline_with_scenario,
)
from tprr.sensitivity.manifest import upsert_manifest_row


@dataclass(frozen=True)
class PipelineRerunRun:
    """One pipeline-rerun point in a sweep.

    ``parameter_label`` is the human-readable identifier (e.g.
    ``"suspension_threshold_days=2"``).

    ``new_config`` carries the parameter override; the runner calls
    ``run_pipeline_at_config(inputs, new_config)`` (or the scenario
    variant when ``scenario_id`` is set).

    ``panel_id`` is the human-readable panel identifier for sweeps that
    cover multiple panels per parameter point (the TWAP-ordering sweep).
    Defaults to ``"clean"``. ``scenario_id`` is the registered scenario
    id (or ``None`` for the clean panel).

    ``ordering_override`` is consumed by the TWAP-ordering sweep — both
    orderings run from the same ``new_config`` with this field
    distinguishing the two pipelines.
    """

    parameter_label: str
    new_config: IndexConfig
    panel_id: str = "clean"
    scenario_id: str | None = None
    ordering_override: str | None = None


def run_pipeline_rerun_sweep(
    *,
    sweep_id: str,
    sweep_kind: str,
    parameter_dim: str,
    runs: list[PipelineRerunRun],
    inputs: BaselineInputs,
    output_dir: Path,
    manifest_path: Path,
    seed: int,
    base_audit_id: str,
    timestamp: datetime | None = None,
    progress: bool = True,
) -> Path:
    """Run a sequence of pipeline reruns and persist as one parquet.

    Each run's IndexValueDF rows are tagged with ``sweep_id``,
    ``parameter_label``, ``panel_id``, and concatenated. The parquet is
    written to ``{output_dir}/{sweep_id}.parquet``; the audit
    (ConstituentDecisionDF) is written to
    ``{output_dir}/{sweep_id}_decisions.parquet``. Manifest row at
    ``manifest_path`` records sweep telemetry (median runtime, base-date
    counts).

    ``progress`` controls per-run printout to stderr; useful when a
    sweep spans multi-minute compute and the user wants visibility.
    """
    if not runs:
        raise ValueError("run_pipeline_rerun_sweep: runs list is empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    indices_path = output_dir / f"{sweep_id}.parquet"
    decisions_path = output_dir / f"{sweep_id}_decisions.parquet"

    indices_rows: list[pd.DataFrame] = []
    decisions_rows: list[pd.DataFrame] = []
    runtimes_s: list[float] = []
    base_date_active_counts: list[int] = []
    suspension_interval_counts: list[int] = []
    reinstatement_event_counts: list[int] = []

    for idx, run in enumerate(runs, start=1):
        if progress:
            print(
                f"  [{idx}/{len(runs)}] {run.parameter_label} (panel={run.panel_id})...",
                flush=True,
            )
        t0 = time.perf_counter()
        if run.scenario_id is None:
            pipeline = run_pipeline_at_config(
                inputs, run.new_config, ordering=run.ordering_override
            )
        else:
            scenario = inputs.scenarios_by_id.get(run.scenario_id)
            if scenario is None:
                raise KeyError(f"Scenario {run.scenario_id!r} not found in scenarios.yaml")
            pipeline = run_pipeline_with_scenario(
                inputs,
                run.new_config,
                scenario,
                seed=seed,
                ordering=run.ordering_override,
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
            tagged["panel_id"] = run.panel_id
            indices_concat.append(tagged)
        if indices_concat:
            indices_rows.append(pd.concat(indices_concat, ignore_index=True))

        # Tag ConstituentDecisionDF rows.
        if not pipeline.constituent_decisions.empty:
            tagged_decisions = pipeline.constituent_decisions.copy()
            tagged_decisions["sweep_id"] = sweep_id
            tagged_decisions["parameter_label"] = run.parameter_label
            tagged_decisions["panel_id"] = run.panel_id
            decisions_rows.append(tagged_decisions)

        # Telemetry: base_date n_active, suspension intervals, reinstatement events.
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
        raise ValueError(
            f"run_pipeline_rerun_sweep: every run produced empty output for {sweep_id!r}"
        )
    indices_out = pd.concat(indices_rows, ignore_index=True)
    indices_out.to_parquet(indices_path)
    if decisions_rows:
        decisions_out = pd.concat(decisions_rows, ignore_index=True)
        decisions_out.to_parquet(decisions_path)
    else:
        pd.DataFrame().to_parquet(decisions_path)

    # Manifest telemetry: report medians across the sweep so a single row
    # captures the typical pipeline cost without exploding into per-run rows.
    median_runtime = float(np.median(runtimes_s)) if runtimes_s else None
    median_base_active = (
        int(np.median(base_date_active_counts)) if base_date_active_counts else None
    )
    median_susp_intervals = (
        int(np.median(suspension_interval_counts)) if suspension_interval_counts else None
    )
    median_reinstatements = (
        int(np.median(reinstatement_event_counts)) if reinstatement_event_counts else None
    )

    upsert_manifest_row(
        manifest_path,
        sweep_id=sweep_id,
        sweep_kind=sweep_kind,
        parameter_dim=parameter_dim,
        parameter_values=[r.parameter_label for r in runs],
        n_seeds=1,
        n_runs=len(runs),
        seed_min=seed,
        seed_max=seed,
        output_path=str(indices_path).replace("\\", "/"),
        base_audit_id=base_audit_id,
        n_rows=len(indices_out),
        timestamp=timestamp,
        pipeline_runtime_s=median_runtime,
        n_active_constituents_at_base_date=median_base_active,
        n_suspension_intervals=median_susp_intervals,
        n_reinstatement_events=median_reinstatements,
    )
    return indices_path


# ---------------------------------------------------------------------------
# Convenience builders for the four Batch 10B sweep flavors
# ---------------------------------------------------------------------------


def build_threshold_runs(
    *,
    base_config: IndexConfig,
    parameter_dim: Literal[
        "suspension_threshold_days",
        "reinstatement_threshold_days",
        "quality_gate_pct",
    ],
    values: list[float],
) -> list[PipelineRerunRun]:
    """Build single-parameter sweep runs over the clean panel.

    Used by suspension / reinstatement / gate sweeps where the only
    perturbation is a scalar field on ``IndexConfig``.
    """
    runs: list[PipelineRerunRun] = []
    for v in values:
        if parameter_dim == "suspension_threshold_days":
            new_config = base_config.model_copy(update={"suspension_threshold_days": int(v)})
            label = f"suspension_threshold_days={int(v)}"
        elif parameter_dim == "reinstatement_threshold_days":
            new_config = base_config.model_copy(update={"reinstatement_threshold_days": int(v)})
            label = f"reinstatement_threshold_days={int(v)}"
        else:  # quality_gate_pct
            new_config = base_config.model_copy(update={"quality_gate_pct": float(v)})
            label = f"quality_gate_pct={float(v):.2f}"
        runs.append(PipelineRerunRun(parameter_label=label, new_config=new_config))
    return runs


def build_twap_ordering_runs(
    *,
    base_config: IndexConfig,
    orderings: list[str],
    panels: list[tuple[str, str | None]],
) -> list[PipelineRerunRun]:
    """Build cross-(ordering x panel) sweep runs for the TWAP-ordering sweep.

    ``panels`` is a list of ``(panel_id, scenario_id)`` pairs;
    ``scenario_id=None`` denotes the clean panel.
    """
    runs: list[PipelineRerunRun] = []
    for ordering in orderings:
        for panel_id, scenario_id in panels:
            label = f"ordering={ordering}|panel={panel_id}"
            runs.append(
                PipelineRerunRun(
                    parameter_label=label,
                    new_config=base_config,
                    panel_id=panel_id,
                    scenario_id=scenario_id,
                    ordering_override=ordering,
                )
            )
    return runs
