"""Phase 10 sensitivity sweep infrastructure.

Three in-memory sweeps recompute IndexValueDF rows from the Phase 7H
ConstituentDecisionDF audit without re-running the full pipeline:

- ``lambda``: exponent in the median-distance weight (DL 2026-04-30 design)
- ``tier_b_haircut``: Tier B confidence haircut (DL 2026-04-30 Batch C)
- ``blending_coefficient``: per-tier blending coefficients (DL 2026-04-30
  Phase 7H Batch B continuous blending)

Pipeline-rerun sweeps (suspension thresholds, TWAP ordering, slot-level
gate thresholds) live in Batch 10B and use the same manifest schema.

Public surface:
- ``recompute_indices_under_override``: the recompute primitive
- ``with_overrides``: convenience for IndexConfig parameter substitution
- ``run_in_memory_sweep``: sweep runner producing per-sweep parquet
- ``read_manifest`` / ``upsert_manifest_row``: manifest CSV catalogue
"""

from tprr.sensitivity.baseline import (
    BaselineInputs,
    load_baseline,
    load_pipeline_inputs,
    run_pipeline_at_config,
    run_pipeline_with_scenario,
)
from tprr.sensitivity.manifest import (
    MANIFEST_COLUMNS,
    read_manifest,
    upsert_manifest_row,
)
from tprr.sensitivity.pipeline_rerun import (
    PipelineRerunRun,
    build_threshold_runs,
    build_twap_ordering_runs,
    run_pipeline_rerun_sweep,
)
from tprr.sensitivity.recompute import (
    recompute_indices_under_override,
    with_overrides,
)
from tprr.sensitivity.sweep import SweepRun, run_in_memory_sweep

__all__ = [
    "MANIFEST_COLUMNS",
    "BaselineInputs",
    "PipelineRerunRun",
    "SweepRun",
    "build_threshold_runs",
    "build_twap_ordering_runs",
    "load_baseline",
    "load_pipeline_inputs",
    "read_manifest",
    "recompute_indices_under_override",
    "run_in_memory_sweep",
    "run_pipeline_at_config",
    "run_pipeline_rerun_sweep",
    "run_pipeline_with_scenario",
    "upsert_manifest_row",
    "with_overrides",
]
