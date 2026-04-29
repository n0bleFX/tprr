"""Phase 7 — end-to-end TPRR compute pipeline.

Wires the full Phase 6 + Phase 7 chain into a single callable:

  panel + change events
   → apply_slot_level_gate                       # tprr.index.quality (Phase 6)
   → compute_consecutive_day_suspensions         # tprr.index.quality (Phase 6)
   → compute_panel_twap (with exclusions)        # tprr.twap.reconstruct
   → compute_tier_index per (tier, date)         # tprr.index.aggregation
   → rebase_index_level per tier                 # tprr.index.aggregation
   → compute_fpr / compute_ser                   # tprr.index.derived
   → compute_tprr_b_indices                      # tprr.index.derived

Returns the full set of 8 IndexValueDF-shape DataFrames (TPRR_F/S/E/FPR/
SER/B_F/B_S/B_E) plus per-tier rebase anchor metadata.

Suspension cascade (decision log 2026-04-29 Phase 6 + DL 2026-04-30 active-
constituent definition):

  pair (contributor x constituent) suspended on day D —— sticky from D
   → constituent loses contributors on/after D
   → if constituent's active Tier A contributors fall < 3, falls through
     to Tier B (revenue-derived) or Tier C (rankings-derived); if all
     three tiers fail to resolve, constituent is excluded that day
   → if active-constituent count for a tier falls < min_constituents_per_tier
     on day D, the tier suspends with INSUFFICIENT_CONSTITUENTS and the
     prior valid raw_value is carried forward

Tier suspension is a DAILY snapshot — if active count climbs back above
the threshold on a later day, the tier resumes that day. Pair-level
suspension stays sticky.
"""

from __future__ import annotations

from datetime import date
from typing import Any, NamedTuple

import pandas as pd

from tprr.config import IndexConfig, ModelRegistry, TierBRevenueConfig
from tprr.index.aggregation import (
    _decisions_list_to_df,
    build_rebase_metadata_df,
    rebase_index_level,
    run_tier_pipeline,
)
from tprr.index.derived import (
    compute_fpr,
    compute_ser,
    compute_tprr_b_indices,
)
from tprr.index.quality import (
    apply_slot_level_gate,
    compute_consecutive_day_suspensions,
)
from tprr.index.weights import TierBVolumeFn
from tprr.schema import Tier
from tprr.twap.reconstruct import compute_panel_twap


class FullPipelineResults(NamedTuple):
    """Output of ``run_full_pipeline``.

    ``indices``: dict mapping each of the 8 ``index_code`` values to its
    IndexValueDF-shape DataFrame.
    ``rebase_anchors``: per-index anchor date (``None`` if no eligible
    anchor existed at or after ``config.base_date``).
    ``rebase_metadata_df``: structured DataFrame with one row per
    ``index_code`` carrying ``(base_date, anchor_date, anchor_raw_value,
    n_pre_anchor_suspended_days)``. Built by ``build_rebase_metadata_df``;
    the dict above stays as a quick lookup, this frame is the artefact
    Phase 10 sweeps load and compare across parameter realisations
    (decision log 2026-04-30 Phase 7 Batch D — Q2).
    ``constituent_decisions``: per-(date, index_code, constituent_id)
    audit DataFrame for the 6 constituent-aggregation indices
    (TPRR_F/S/E + TPRR_B_F/B_S/B_E). FPR/SER do not contribute rows
    (they are ratios, not constituent aggregations). Schema documented
    in ``tprr.index.aggregation._DECISION_FIELDS``. Phase 10 sensitivity
    sweeps consume this frame to recompute λ-sensitive and haircut-
    sensitive aggregates without re-running the full pipeline (decision
    log 2026-04-30 Phase 7 Batch D — Q1).
    ``excluded_slots``: the slot-level gate's output for traceability.
    ``suspended_pairs``: the (contributor, constituent, suspension_date)
    DataFrame consumed by aggregation, for traceability.
    """

    indices: dict[str, pd.DataFrame]
    rebase_anchors: dict[str, date | None]
    rebase_metadata_df: pd.DataFrame
    constituent_decisions: pd.DataFrame
    excluded_slots: pd.DataFrame
    suspended_pairs: pd.DataFrame


def run_full_pipeline(
    panel_df: pd.DataFrame,
    change_events_df: pd.DataFrame,
    config: IndexConfig,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
    *,
    ordering: str = "twap_then_weight",
    version: str = "v0_1",
) -> FullPipelineResults:
    """End-to-end Phase 7 pipeline. ``panel_df`` must be multi-day, multi-tier.

    Steps:

    1. ``apply_slot_level_gate`` on the full panel. The gate operates only on
       Tier A rows (per the Tier-A-only scope addendum in DL 2026-04-29 Phase
       6 slot-level quality gate parameters). Returns
       ``excluded_slots_df``.
    2. ``compute_consecutive_day_suspensions`` on the gate output.
       3-consecutive-day rule (DL 2026-04-29 Phase 6 suspension counter).
       Returns ``suspended_pairs_df``.
    3. ``compute_panel_twap`` on the full panel, honouring the gate's
       exclusions. Tier B/C rows pass through unchanged because they have no
       slot dimension.
    4. ``run_tier_pipeline`` for each of TPRR_F / TPRR_S / TPRR_E with the
       suspended-pairs frame; rebase each via ``rebase_index_level``.
    5. ``compute_fpr`` and ``compute_ser`` from the rebased core indices.
    6. ``compute_tprr_b_indices`` for the blended series, using the same
       suspension and TWAP inputs.

    Returns a ``FullPipelineResults`` named tuple keyed for downstream
    persistence (Batch D), plotting (Phase 9), and sensitivity sweeps
    (Phase 10).
    """
    excluded_slots = apply_slot_level_gate(
        panel_df,
        change_events_df,
        trailing_window_days=5,
        deviation_pct=config.quality_gate_pct,
    )
    suspended_pairs = compute_consecutive_day_suspensions(
        excluded_slots,
        threshold_days=3,
    )

    # All-32-slots-excluded handling: when every slot fires for a
    # (contributor, constituent, date), the contributor has no surviving TWAP
    # that day. Per the active-constituent definition (DL 2026-04-30 clause
    # (a) — "≥1 non-suspended contributor TWAP surviving the Phase 6 gate"),
    # such rows are equivalent to "contributor didn't report that day": drop
    # the row from the panel and from the exclusions frame before TWAP
    # computation. The (32-fire) day still counts toward the suspension
    # counter (the excluded_slots_df keys feeding compute_consecutive_day_
    # suspensions are unchanged); aggregation simply sees one fewer Tier A
    # contributor on that day, and the priority fall-through handles the
    # downstream effect.
    panel_filtered, exclusions_filtered = _drop_fully_excluded_rows(
        panel_df, excluded_slots
    )

    panel_with_twap = compute_panel_twap(
        panel_filtered,
        change_events_df,
        excluded_slots_df=exclusions_filtered,
    )

    indices: dict[str, pd.DataFrame] = {}
    anchors: dict[str, date | None] = {}
    decisions: list[dict[str, Any]] = []

    for tier in (Tier.TPRR_F, Tier.TPRR_S, Tier.TPRR_E):
        tier_indices = run_tier_pipeline(
            panel_df=panel_with_twap,
            tier=tier,
            config=config,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
            suspended_pairs_df=suspended_pairs,
            ordering=ordering,
            version=version,
            decisions_out=decisions,
            change_events_df=change_events_df,
            excluded_slots_df=exclusions_filtered,
        )
        rebased, anchor = rebase_index_level(
            tier_indices, base_date=config.base_date
        )
        indices[tier.value] = rebased
        anchors[tier.value] = anchor

    fpr_df, fpr_anchor = compute_fpr(
        indices["TPRR_F"], indices["TPRR_S"], config,
        version=version, ordering=ordering,
    )
    ser_df, ser_anchor = compute_ser(
        indices["TPRR_S"], indices["TPRR_E"], config,
        version=version, ordering=ordering,
    )
    indices["TPRR_FPR"] = fpr_df
    indices["TPRR_SER"] = ser_df
    anchors["TPRR_FPR"] = fpr_anchor
    anchors["TPRR_SER"] = ser_anchor

    b_result = compute_tprr_b_indices(
        panel_df=panel_with_twap,
        config=config,
        registry=registry,
        tier_b_config=tier_b_config,
        tier_b_volume_fn=tier_b_volume_fn,
        suspended_pairs_df=suspended_pairs,
        ordering=ordering,
        version=version,
        change_events_df=change_events_df,
        excluded_slots_df=exclusions_filtered,
    )
    for code, df in b_result.indices.items():
        indices[code] = df
        anchors[code] = b_result.rebase_anchors[code]
    # Merge B-series per-constituent decisions into the same accumulator.
    if not b_result.constituent_decisions.empty:
        b_records: list[dict[str, Any]] = [
            {str(k): v for k, v in rec.items()}
            for rec in b_result.constituent_decisions.to_dict("records")
        ]
        decisions.extend(b_records)

    rebase_metadata_df = build_rebase_metadata_df(
        indices=indices,
        rebase_anchors=anchors,
        base_date=config.base_date,
    )

    return FullPipelineResults(
        indices=indices,
        rebase_anchors=anchors,
        rebase_metadata_df=rebase_metadata_df,
        constituent_decisions=_decisions_list_to_df(decisions),
        excluded_slots=excluded_slots,
        suspended_pairs=suspended_pairs,
    )


_TWAP_SLOTS_PER_DAY = 32


def _drop_fully_excluded_rows(
    panel_df: pd.DataFrame,
    excluded_slots_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter out (contributor, constituent, date) keys whose every slot fired.

    Returns ``(panel_without_fully_excluded, exclusions_without_fully_excluded)``.
    The exclusions frame is filtered too because there's no longer a panel row
    for those keys for ``compute_panel_twap`` to consume — leaving the
    exclusions in would be a no-op but the filter keeps the contract tight.
    The fully-excluded keys ARE retained in the upstream ``excluded_slots``
    frame returned by ``run_full_pipeline`` so the suspension counter (which
    operates on exclusions before this filter) and Phase 9 / Phase 10
    consumers can see the full gate-firing history.
    """
    if excluded_slots_df.empty:
        return panel_df, excluded_slots_df
    per_key = excluded_slots_df.groupby(
        ["contributor_id", "constituent_id", "date"]
    ).size()
    fully_excluded_keys = per_key[per_key >= _TWAP_SLOTS_PER_DAY].index
    if len(fully_excluded_keys) == 0:
        return panel_df, excluded_slots_df

    # Filter panel rows
    panel_keys = pd.MultiIndex.from_arrays(
        [
            panel_df["contributor_id"],
            panel_df["constituent_id"],
            panel_df["observation_date"],
        ]
    )
    panel_keep_mask = ~panel_keys.isin(fully_excluded_keys)
    panel_out = panel_df[panel_keep_mask].copy()

    # Filter exclusion rows for the same keys (no panel row to honour them)
    excl_keys = pd.MultiIndex.from_arrays(
        [
            excluded_slots_df["contributor_id"],
            excluded_slots_df["constituent_id"],
            excluded_slots_df["date"],
        ]
    )
    excl_keep_mask = ~excl_keys.isin(fully_excluded_keys)
    excl_out = excluded_slots_df[excl_keep_mask].copy()
    return panel_out, excl_out
