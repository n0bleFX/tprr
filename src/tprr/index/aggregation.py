"""Phase 7 — daily TPRR index aggregation.

Pipeline order (methodology Sections 3.3.1, 3.3.2, 3.3.3, 4.2.2 + the
priority fall-through and TWAP-ordering decisions in
``docs/decision_log.md``):

  panel + change events
   → quality gate (slot-level exclusions)        # tprr.index.quality
   → compute_panel_twap                          # tprr.twap.reconstruct
   → tier selection per constituent              # tprr.index.weights
   → constituent-level price collapse            # this module
   → tier median, w_exp, w_vol                   # this module + weights
   → dual-weighted aggregate                     # this module
   → rebase to 100 on base_date                  # this module (Batch B)

Active constituent (decision log 2026-04-30 "Phase 7 active-constituent
definition for tier aggregation"):
  (a) ≥1 non-suspended contributor TWAP surviving the Phase 6 gate
  (b) panel-row ``tier_code`` matches the tier being computed (panel-as-
      truth per decision log 2026-04-27 "Tier reshuffle handling")
  (c) not globally suspended via cross-contributor cascade (vacuous under
      v0.1's per-pair suspension schema; reserved for v0.2+)

Constituent price collapse (decision log 2026-04-30 "Phase 7 contributor-
to-constituent price collapse"): volume-weighted average across the
selected tier's contributor rows, with simple-mean fallback when total
volume is zero.

Batch A: TWAP-then-weight, single tier, clean panel.
Batch B: all 3 core tiers + rebase to 100 on 2026-01-01 (per-tier anchor
  fall-through when base_date itself is suspended for a tier).
Subsequent batches:
- Batch B': blended TPRR-B over (0.25 x P_in + 0.75 x P_out)
- Batch C: suspension consumption + fallback to prior valid index level
- Batch D: schema additions land (already in this file via SuspensionReason)
- Batch E: weight-then-TWAP alternate ordering for Phase 10 comparison
- Batch F: end-to-end tests against scenario panels + close-out
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from tprr.config import IndexConfig, ModelRegistry, TierBRevenueConfig
from tprr.index.weights import (
    TierBVolumeFn,
    compute_tier_volume,
    exponential_weight,
    volume_weight,
)
from tprr.schema import AttestationTier, Tier


class SuspensionReason(StrEnum):
    """Cause when an IndexValue row carries ``suspended=True``.

    Schema-side ``suspension_reason`` is free ``str`` per decision log
    2026-04-30 "Phase 7 IndexValue schema additions" (matches the v0.1
    closed-set-fields-as-str discipline). Producers in this module emit
    these enum values; downstream consumers compare against this enum.
    """

    INSUFFICIENT_CONSTITUENTS = "insufficient_constituents"
    """< ``min_constituents_per_tier`` survived after activation gates."""

    TIER_DATA_UNAVAILABLE = "tier_data_unavailable"
    """No constituent in the tier resolved any A/B/C path."""

    QUALITY_GATE_CASCADE = "quality_gate_cascade"
    """Σ(weight x price) denominator is zero — every active constituent's
    combined w_vol x w_exp evaluated to zero. Defensive bucket; with
    strictly-positive volumes (Tier A activation rule) and the exponential
    weight ∈ (0, 1] this branch should not trigger in v0.1."""


# ---------------------------------------------------------------------------
# Constituent-level price collapse (DL 2026-04-30)
# ---------------------------------------------------------------------------


def collapse_constituent_price(
    rows: pd.DataFrame,
    *,
    price_col: str = "twap_output_usd_mtok",
    volume_col: str = "volume_mtok_7d",
) -> float:
    """Volume-weighted average of contributor TWAPs (decision log 2026-04-30).

    P̃_const = Σ_c [ v_c x P̃_c ] / Σ_c [ v_c ]

    Falls back to simple mean when ``Σ v_c == 0`` (defensive — Tier A
    activation requires Σ v > 0, so this branch is reachable only via
    pathological Tier C inputs where every endpoint reports zero volume).
    Empty input raises.
    """
    if rows.empty:
        raise ValueError("collapse_constituent_price: rows is empty")
    volumes = rows[volume_col].to_numpy(dtype=np.float64)
    prices = rows[price_col].to_numpy(dtype=np.float64)
    total_vol = float(volumes.sum())
    if total_vol <= 0:
        return float(prices.mean())
    return float((volumes * prices).sum() / total_vol)


# ---------------------------------------------------------------------------
# Per-(tier, date) compute
# ---------------------------------------------------------------------------


def compute_tier_index(
    panel_day_df: pd.DataFrame,
    tier: Tier,
    config: IndexConfig,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
    suspended_pairs_df: pd.DataFrame | None = None,
    *,
    ordering: str = "twap_then_weight",
    prior_raw_value: float | None = None,
    version: str = "v0_1",
) -> dict[str, Any]:
    """Compute one (tier, date) IndexValue row from a single-day panel slice.

    ``panel_day_df`` must:
      - Span exactly one ``observation_date``.
      - Carry ``twap_output_usd_mtok`` populated by ``compute_panel_twap``.
      - Hold rows from all three attestation tiers (A/B/C) needed for
        priority fall-through; rows whose ``tier_code`` differs from
        ``tier`` are filtered out here (panel-as-truth).

    Returns one IndexValue-shape dict keyed for direct DataFrame
    construction. ``suspended=True`` rows carry ``raw_value_usd_mtok``
    set to ``prior_raw_value`` (or ``np.nan`` if no prior exists).
    """
    if ordering != "twap_then_weight":
        raise NotImplementedError(
            f"compute_tier_index: ordering {ordering!r} not implemented in Batch A "
            f"(weight-then-TWAP lands in Batch E)"
        )

    if panel_day_df.empty:
        return _suspended_row(
            tier=tier,
            as_of_date=None,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.TIER_DATA_UNAVAILABLE,
            n_constituents=0,
            prior_raw_value=prior_raw_value,
        )

    unique_dates = panel_day_df["observation_date"].unique()
    if len(unique_dates) != 1:
        raise ValueError(
            f"compute_tier_index: expected single observation_date, got {len(unique_dates)}"
        )
    as_of_date_value = pd.Timestamp(unique_dates[0]).date()

    # 1. Filter to the tier under computation (panel-as-truth tier_code).
    tier_panel = panel_day_df[panel_day_df["tier_code"] == tier.value].copy()

    # 2. Drop suspended (contributor, constituent) pairs effective on this date.
    if suspended_pairs_df is not None and not suspended_pairs_df.empty:
        active_susp = suspended_pairs_df[
            suspended_pairs_df["suspension_date"] <= pd.Timestamp(as_of_date_value)
        ]
        if not active_susp.empty:
            keep_keys = pd.MultiIndex.from_arrays(
                [tier_panel["contributor_id"], tier_panel["constituent_id"]]
            )
            drop_keys = pd.MultiIndex.from_arrays(
                [active_susp["contributor_id"], active_susp["constituent_id"]]
            )
            tier_panel = tier_panel[~keep_keys.isin(drop_keys)]

    n_constituents_total = int(tier_panel["constituent_id"].nunique())

    if tier_panel.empty:
        return _suspended_row(
            tier=tier,
            as_of_date=as_of_date_value,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.TIER_DATA_UNAVAILABLE,
            n_constituents=n_constituents_total,
            prior_raw_value=prior_raw_value,
        )

    # 3. Per-constituent: tier selection + price collapse + w_vol.
    rows: list[dict[str, Any]] = []
    for constituent_id in tier_panel["constituent_id"].unique():
        const_id = str(constituent_id)
        sub = tier_panel[tier_panel["constituent_id"] == const_id]

        tier_result = compute_tier_volume(
            constituent_id=const_id,
            as_of_date=as_of_date_value,
            panel_df=sub,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
        )
        if tier_result is None:
            continue

        selected_tier, raw_volume = tier_result
        if selected_tier == AttestationTier.A:
            price_rows = sub[
                (sub["attestation_tier"] == AttestationTier.A.value)
                & (sub["volume_mtok_7d"] > 0)
            ]
        elif selected_tier == AttestationTier.B:
            price_rows = sub[sub["attestation_tier"] == AttestationTier.B.value]
        else:  # AttestationTier.C
            price_rows = sub[
                (sub["attestation_tier"] == AttestationTier.C.value)
                & (sub["volume_mtok_7d"] > 0)
            ]

        if price_rows.empty:
            # Selected tier resolved a volume but the panel has no surviving
            # price rows for that tier (e.g. all Tier A contributor TWAPs
            # were excluded by upstream gating). Skip the constituent.
            continue

        constituent_price = collapse_constituent_price(price_rows)
        w_vol = volume_weight(raw_volume, selected_tier, config)
        rows.append(
            {
                "constituent_id": const_id,
                "selected_tier": selected_tier.value,
                "price": constituent_price,
                "raw_volume": raw_volume,
                "w_vol": w_vol,
            }
        )

    if not rows:
        return _suspended_row(
            tier=tier,
            as_of_date=as_of_date_value,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.TIER_DATA_UNAVAILABLE,
            n_constituents=n_constituents_total,
            prior_raw_value=prior_raw_value,
        )

    constituents_df = pd.DataFrame(rows)
    n_active = len(constituents_df)

    if n_active < config.min_constituents_per_tier:
        return _suspended_row(
            tier=tier,
            as_of_date=as_of_date_value,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.INSUFFICIENT_CONSTITUENTS,
            n_constituents=n_constituents_total,
            n_constituents_active=n_active,
            n_a=int((constituents_df["selected_tier"] == AttestationTier.A.value).sum()),
            n_b=int((constituents_df["selected_tier"] == AttestationTier.B.value).sum()),
            n_c=int((constituents_df["selected_tier"] == AttestationTier.C.value).sum()),
            prior_raw_value=prior_raw_value,
        )

    # 4. Tier median across active constituents (Section 3.3.3).
    tier_median = float(np.median(constituents_df["price"].to_numpy(dtype=np.float64)))

    # 5. w_exp per constituent.
    constituents_df["w_exp"] = constituents_df["price"].apply(
        lambda p: exponential_weight(float(p), tier_median, config.lambda_)
    )

    # 6. Combined weight + dual-weighted aggregate (Section 3.3.1).
    constituents_df["weight"] = constituents_df["w_vol"] * constituents_df["w_exp"]
    total_weight = float(constituents_df["weight"].sum())

    if total_weight <= 0:
        return _suspended_row(
            tier=tier,
            as_of_date=as_of_date_value,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.QUALITY_GATE_CASCADE,
            n_constituents=n_constituents_total,
            n_constituents_active=n_active,
            prior_raw_value=prior_raw_value,
        )

    raw_value = float(
        (constituents_df["weight"] * constituents_df["price"]).sum() / total_weight
    )

    # 7. Tier-level instrumentation (DL 2026-04-30 schema additions).
    n_a = int((constituents_df["selected_tier"] == AttestationTier.A.value).sum())
    n_b = int((constituents_df["selected_tier"] == AttestationTier.B.value).sum())
    n_c = int((constituents_df["selected_tier"] == AttestationTier.C.value).sum())
    weight_a = float(
        constituents_df.loc[
            constituents_df["selected_tier"] == AttestationTier.A.value, "weight"
        ].sum()
        / total_weight
    )
    weight_b = float(
        constituents_df.loc[
            constituents_df["selected_tier"] == AttestationTier.B.value, "weight"
        ].sum()
        / total_weight
    )
    weight_c = float(
        constituents_df.loc[
            constituents_df["selected_tier"] == AttestationTier.C.value, "weight"
        ].sum()
        / total_weight
    )

    return {
        "as_of_date": as_of_date_value,
        "index_code": tier.value,
        "version": version,
        "lambda": config.lambda_,
        "ordering": ordering,
        "raw_value_usd_mtok": raw_value,
        "index_level": float("nan"),  # Batch B rebases
        "n_constituents": n_constituents_total,
        "n_constituents_active": n_active,
        "n_constituents_a": n_a,
        "n_constituents_b": n_b,
        "n_constituents_c": n_c,
        "tier_a_weight_share": weight_a,
        "tier_b_weight_share": weight_b,
        "tier_c_weight_share": weight_c,
        "suspended": False,
        "suspension_reason": "",
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _suspended_row(
    *,
    tier: Tier,
    as_of_date: date | None,
    config: IndexConfig,
    ordering: str,
    version: str,
    reason: SuspensionReason,
    n_constituents: int = 0,
    n_constituents_active: int = 0,
    n_a: int = 0,
    n_b: int = 0,
    n_c: int = 0,
    prior_raw_value: float | None = None,
) -> dict[str, Any]:
    """Construct a suspended IndexValue dict, carrying prior_raw_value forward."""
    fallback = float(prior_raw_value) if prior_raw_value is not None else float("nan")
    return {
        "as_of_date": as_of_date,
        "index_code": tier.value,
        "version": version,
        "lambda": config.lambda_,
        "ordering": ordering,
        "raw_value_usd_mtok": fallback,
        "index_level": float("nan"),
        "n_constituents": n_constituents,
        "n_constituents_active": n_constituents_active,
        "n_constituents_a": n_a,
        "n_constituents_b": n_b,
        "n_constituents_c": n_c,
        "tier_a_weight_share": 0.0,
        "tier_b_weight_share": 0.0,
        "tier_c_weight_share": 0.0,
        "suspended": True,
        "suspension_reason": reason.value,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Multi-day driver
# ---------------------------------------------------------------------------


def run_tier_pipeline(
    panel_df: pd.DataFrame,
    tier: Tier,
    config: IndexConfig,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
    suspended_pairs_df: pd.DataFrame | None = None,
    *,
    ordering: str = "twap_then_weight",
    version: str = "v0_1",
) -> pd.DataFrame:
    """Run aggregation across every distinct date in ``panel_df`` for one tier.

    ``panel_df`` must have ``twap_output_usd_mtok`` populated upstream by
    ``compute_panel_twap``. The driver iterates dates in ascending order,
    threading the most recent valid ``raw_value_usd_mtok`` as
    ``prior_raw_value`` so suspended rows carry it forward (Q2 lock).

    Output is an IndexValueDF-shape DataFrame (Batch B will populate
    ``index_level``; Batch A leaves it NaN).
    """
    if panel_df.empty:
        return pd.DataFrame()

    dates = sorted(panel_df["observation_date"].unique())
    rows: list[dict[str, Any]] = []
    prior_raw_value: float | None = None

    for d in dates:
        slice_df = panel_df[panel_df["observation_date"] == d]
        result = compute_tier_index(
            panel_day_df=slice_df,
            tier=tier,
            config=config,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
            suspended_pairs_df=suspended_pairs_df,
            ordering=ordering,
            prior_raw_value=prior_raw_value,
            version=version,
        )
        rows.append(result)
        if not result["suspended"] and not np.isnan(result["raw_value_usd_mtok"]):
            prior_raw_value = float(result["raw_value_usd_mtok"])

    out = pd.DataFrame(rows)
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).astype("datetime64[ns]")
    return out


# ---------------------------------------------------------------------------
# Rebase + multi-tier driver (Batch B)
# ---------------------------------------------------------------------------


def rebase_index_level(
    indices_df: pd.DataFrame,
    *,
    base_date: date,
    base_value: float = 100.0,
) -> tuple[pd.DataFrame, date | None]:
    """Set ``index_level`` so the anchor row equals ``base_value``.

    Anchor selection (Q4 sub-question lock 2026-04-29):
      anchor = first non-suspended row with finite, positive
      ``raw_value_usd_mtok`` whose ``as_of_date >= base_date``. Different
      indices may have different anchor dates if some are suspended on
      ``base_date``; the caller persists the per-index anchor in metadata.

    When no anchor exists (every row at or after ``base_date`` is
    suspended or non-finite), returns the input unchanged with anchor
    ``None`` — caller may flag the index as un-rebasable.

    Empty input returns ``(input, None)``.
    """
    if indices_df.empty:
        return indices_df, None

    out = indices_df.copy()
    base_ts = pd.Timestamp(base_date)
    eligible = out[
        (out["as_of_date"] >= base_ts)
        & (~out["suspended"])
        & out["raw_value_usd_mtok"].apply(lambda v: isinstance(v, float) and np.isfinite(v) and v > 0)
    ]
    if eligible.empty:
        return out, None
    anchor_row = eligible.iloc[0]
    anchor_value = float(anchor_row["raw_value_usd_mtok"])
    anchor_date = pd.Timestamp(anchor_row["as_of_date"]).date()
    factor = base_value / anchor_value
    out["index_level"] = out["raw_value_usd_mtok"].astype(float) * factor
    return out, anchor_date


@dataclass
class CoreIndexResults:
    """Output of ``run_all_core_indices`` — per-tier IndexValueDF + anchor metadata.

    ``indices`` maps each ``index_code`` (``TPRR_F`` / ``TPRR_S`` / ``TPRR_E``)
    to its IndexValueDF-shape DataFrame with ``index_level`` populated by
    rebase. ``rebase_anchors`` maps ``index_code`` to the anchor date used
    (or ``None`` if no eligible anchor existed at or after ``base_date``).
    """

    indices: dict[str, pd.DataFrame]
    rebase_anchors: dict[str, date | None]


def run_all_core_indices(
    panel_df: pd.DataFrame,
    config: IndexConfig,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
    suspended_pairs_df: pd.DataFrame | None = None,
    *,
    ordering: str = "twap_then_weight",
    version: str = "v0_1",
) -> CoreIndexResults:
    """Run aggregation for TPRR_F, TPRR_S, TPRR_E with rebase to 100 on base_date.

    Each tier runs independently. Per-tier rebase anchor is computed from
    that tier's own indices_df — different tiers may have different
    anchors when ``base_date`` itself is suspended for some tier.
    """
    indices: dict[str, pd.DataFrame] = {}
    anchors: dict[str, date | None] = {}
    for tier in (Tier.TPRR_F, Tier.TPRR_S, Tier.TPRR_E):
        tier_indices = run_tier_pipeline(
            panel_df=panel_df,
            tier=tier,
            config=config,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
            suspended_pairs_df=suspended_pairs_df,
            ordering=ordering,
            version=version,
        )
        rebased, anchor = rebase_index_level(
            tier_indices, base_date=config.base_date
        )
        indices[tier.value] = rebased
        anchors[tier.value] = anchor
    return CoreIndexResults(indices=indices, rebase_anchors=anchors)
