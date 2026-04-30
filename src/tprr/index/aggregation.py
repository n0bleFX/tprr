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

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from tprr.config import IndexConfig, ModelRegistry, TierBRevenueConfig
from tprr.index.weights import (
    TierBVolumeFn,
    compute_blended_tier_volumes,
    compute_within_tier_share,
    exponential_weight,
    redistribute_blending_coefficients,
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


class ConstituentExclusionReason(StrEnum):
    """Cause when a constituent decision row carries ``included=False``.

    Empty string ``""`` is used for ``included=True`` rows; this enum
    captures the closed set of exclusion reasons emitted by
    ``compute_tier_index`` (Batch D — Q1 audit trail).
    """

    ALL_PAIRS_SUSPENDED = "all_pairs_suspended"
    """Every (contributor, constituent) pair for this constituent was
    in the suspended-pairs frame on this date — the constituent has no
    surviving panel rows after the drop. Semantically distinct from
    ``TIER_VOLUME_UNAVAILABLE`` (constituent has data, but no volume
    tier resolves): this row signals a contributor-coverage failure at
    the upstream suspension layer, not a tier-resolution failure.
    Phase 10 sensitivity work distinguishes the two when characterising
    cascade dynamics."""

    TIER_VOLUME_UNAVAILABLE = "tier_volume_unavailable"
    """``compute_tier_volume`` returned ``None`` — none of A/B/C
    resolved for this (constituent, date)."""

    SELECTED_TIER_NO_PRICE_ROWS = "selected_tier_no_price_rows"
    """Tier resolved a volume but no panel price rows survived (e.g.
    every Tier A contributor TWAP was excluded by upstream gating)."""

    TIER_AGGREGATION_SUSPENDED = "tier_aggregation_suspended"
    """Constituent computed normally, but the tier as a whole hit a
    suspension condition (insufficient constituents, quality-gate
    cascade) and so this constituent did not actually contribute to
    the published index level. Distinct from per-constituent
    exclusion: the constituent's data is real and queryable."""


_DECISION_FIELDS = (
    "as_of_date",
    "index_code",
    "version",
    "ordering",
    "constituent_id",
    "included",
    "exclusion_reason",
    "attestation_tier",
    "coefficient",
    "raw_volume_mtok",
    "within_tier_volume_share",
    "tier_collapsed_price_usd_mtok",
    "w_vol_contribution",
    "constituent_price_usd_mtok",
    "tier_median_price_usd_mtok",
    "price_distance_from_median_pct",
    "w_vol",
    "w_exp",
    "combined_weight",
    "contributor_count",
)


def _decision_row(
    *,
    as_of_date: date | None,
    index_code: str,
    version: str,
    ordering: str,
    constituent_id: str,
    included: bool,
    exclusion_reason: str,
    attestation_tier: str = "",
    coefficient: float = float("nan"),
    raw_volume_mtok: float = float("nan"),
    within_tier_volume_share: float = float("nan"),
    tier_collapsed_price_usd_mtok: float = float("nan"),
    w_vol_contribution: float = float("nan"),
    constituent_price_usd_mtok: float = float("nan"),
    tier_median_price_usd_mtok: float = float("nan"),
    price_distance_from_median_pct: float = float("nan"),
    w_vol: float = float("nan"),
    w_exp: float = float("nan"),
    combined_weight: float = float("nan"),
    contributor_count: int = 0,
) -> dict[str, Any]:
    """Build one ConstituentDecisionDF row.

    Phase 7H Batch B (DL 2026-04-30) introduces long-format per-tier
    breakdown: each constituent emits one row per contributing tier under
    continuous blending. Per-tier fields (``attestation_tier``,
    ``coefficient``, ``raw_volume_mtok``, ``within_tier_volume_share``,
    ``tier_collapsed_price_usd_mtok``, ``w_vol_contribution``,
    ``contributor_count``) describe THIS row's tier's contribution.
    Constituent-level fields (``constituent_price_usd_mtok``,
    ``tier_median_price_usd_mtok``, ``price_distance_from_median_pct``,
    ``w_vol``, ``w_exp``, ``combined_weight``) are duplicated across the
    constituent's per-tier rows for query convenience.

    Excluded rows (constituent failed before tier resolution OR before
    median computation) carry single rows with ``attestation_tier=""``
    and the appropriate ``exclusion_reason``; numeric per-tier fields
    are NaN.

    ``weight_share_within_tier`` was dropped per DL 2026-04-30 "Phase 7H
    Batch B audit trail design": consumers compute it via
    ``df.groupby([as_of_date, constituent_id]).w_vol_contribution.sum()``
    when needed.
    """
    return {
        "as_of_date": as_of_date,
        "index_code": index_code,
        "version": version,
        "ordering": ordering,
        "constituent_id": constituent_id,
        "included": included,
        "exclusion_reason": exclusion_reason,
        "attestation_tier": attestation_tier,
        "coefficient": float(coefficient),
        "raw_volume_mtok": float(raw_volume_mtok),
        "within_tier_volume_share": float(within_tier_volume_share),
        "tier_collapsed_price_usd_mtok": float(tier_collapsed_price_usd_mtok),
        "w_vol_contribution": float(w_vol_contribution),
        "constituent_price_usd_mtok": float(constituent_price_usd_mtok),
        "tier_median_price_usd_mtok": float(tier_median_price_usd_mtok),
        "price_distance_from_median_pct": float(price_distance_from_median_pct),
        "w_vol": float(w_vol),
        "w_exp": float(w_exp),
        "combined_weight": float(combined_weight),
        "contributor_count": int(contributor_count),
    }


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
    price_field: str = "twap_output_usd_mtok",
    decisions_out: list[dict[str, Any]] | None = None,
    change_events_df: pd.DataFrame | None = None,
    excluded_slots_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute one (tier, date) IndexValue row from a single-day panel slice.

    ``panel_day_df`` must:
      - Span exactly one ``observation_date``.
      - Carry the column named by ``price_field`` populated upstream
        (default ``twap_output_usd_mtok`` — set by ``compute_panel_twap``;
        ``twap_blended_usd_mtok`` for the TPRR_B series, set by
        ``tprr.index.derived.add_blended_twap_column``).
      - Hold rows from all three attestation tiers (A/B/C) needed for
        priority fall-through; rows whose ``tier_code`` differs from
        ``tier`` are filtered out here (panel-as-truth).

    Returns one IndexValue-shape dict keyed for direct DataFrame
    construction. ``suspended=True`` rows carry ``raw_value_usd_mtok``
    set to ``prior_raw_value`` (or ``np.nan`` if no prior exists).

    Per-constituent audit trail (Batch D — Q1, decision log 2026-04-30
    Phase 7 Batch D): when ``decisions_out`` is provided, this function
    appends one ConstituentDecisionDF-shape dict per constituent that
    survived the suspended-pair drop, regardless of whether the
    constituent was ultimately included in the index level. Excluded
    rows carry ``exclusion_reason`` from the ``ConstituentExclusionReason``
    closed set; included rows carry ``included=True`` with all numeric
    fields populated. Phase 10 sensitivity sweeps consume this frame to
    recompute λ-sensitive and haircut-sensitive aggregates without
    re-running the full pipeline.
    """
    if ordering not in ("twap_then_weight", "weight_then_twap"):
        raise NotImplementedError(
            f"compute_tier_index: ordering {ordering!r} not implemented; "
            f"valid values are 'twap_then_weight' or 'weight_then_twap'"
        )

    if ordering == "weight_then_twap":
        if change_events_df is None:
            raise ValueError(
                "compute_tier_index: ordering='weight_then_twap' requires "
                "change_events_df (slot reconstruction needs the events frame)"
            )
        return _compute_weight_then_twap_index(
            panel_day_df=panel_day_df,
            change_events_df=change_events_df,
            excluded_slots_df=excluded_slots_df,
            tier=tier,
            config=config,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
            suspended_pairs_df=suspended_pairs_df,
            prior_raw_value=prior_raw_value,
            version=version,
            price_field=price_field,
            decisions_out=decisions_out,
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
    pre_drop_constituents: set[str] = {
        str(c) for c in tier_panel["constituent_id"].unique()
    }

    # 2. Drop suspended (contributor, constituent) pairs effective on this date.
    # Phase 7H Batch D (DL 2026-04-30): suspended_pairs_df may carry an
    # optional ``reinstatement_date`` column for interval-based semantics
    # (suspension_date <= D < reinstatement_date is "active"). Legacy
    # frames without that column are treated as one-way ratchet.
    if suspended_pairs_df is not None and not suspended_pairs_df.empty:
        as_of_ts = pd.Timestamp(as_of_date_value)
        suspension_active = suspended_pairs_df["suspension_date"] <= as_of_ts
        if "reinstatement_date" in suspended_pairs_df.columns:
            reinstated = (
                suspended_pairs_df["reinstatement_date"].notna()
                & (suspended_pairs_df["reinstatement_date"] <= as_of_ts)
            )
            active_susp = suspended_pairs_df[suspension_active & ~reinstated]
        else:
            active_susp = suspended_pairs_df[suspension_active]
        if not active_susp.empty:
            keep_keys = pd.MultiIndex.from_arrays(
                [tier_panel["contributor_id"], tier_panel["constituent_id"]]
            )
            drop_keys = pd.MultiIndex.from_arrays(
                [active_susp["contributor_id"], active_susp["constituent_id"]]
            )
            tier_panel = tier_panel[~keep_keys.isin(drop_keys)]

    post_drop_constituents: set[str] = {
        str(c) for c in tier_panel["constituent_id"].unique()
    }
    dropped_constituents = pre_drop_constituents - post_drop_constituents

    n_constituents_total = int(tier_panel["constituent_id"].nunique())

    # 3. Per-constituent: tier selection + price collapse + w_vol.
    # Buffer decisions locally so post-loop tier-level outcomes (suspension,
    # quality-gate cascade, success) can backfill weight_share / w_exp /
    # tier_median fields on every active row before we publish to
    # ``decisions_out``.
    pending_decisions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    # 3a. Constituents whose every (contributor, constituent) pair was in the
    # suspended-pairs frame on this date never enter the per-constituent loop —
    # they were dropped at step 2. Emit one ALL_PAIRS_SUSPENDED audit row per
    # dropped constituent. Phase 10 distinguishes this signal from
    # TIER_VOLUME_UNAVAILABLE: the former is a contributor-coverage failure,
    # the latter a tier-resolution failure on a constituent that still had
    # data after the drop. Both can co-occur on the same (date, tier) when
    # tier_panel becomes empty after the drop — the tier-level
    # TIER_DATA_UNAVAILABLE row and these per-constituent rows are not
    # mutually exclusive.
    for const_id in sorted(dropped_constituents):
        pending_decisions.append(
            _decision_row(
                as_of_date=as_of_date_value,
                index_code=tier.value,
                version=version,
                ordering=ordering,
                constituent_id=const_id,
                included=False,
                exclusion_reason=ConstituentExclusionReason.ALL_PAIRS_SUSPENDED.value,
                contributor_count=0,
            )
        )

    def _publish(decisions: list[dict[str, Any]]) -> None:
        if decisions_out is not None:
            decisions_out.extend(decisions)

    if tier_panel.empty:
        _publish(pending_decisions)
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
    # Phase 7H Batch B (DL 2026-04-30): continuous blending replaces priority
    # fall-through. Per-constituent multi-tier resolution + per-tier price
    # collapse, then within-tier-share normalisation across constituents,
    # then coefficient redistribution per constituent, then combined w_vol
    # and combined price.
    for constituent_id in tier_panel["constituent_id"].unique():
        const_id = str(constituent_id)
        sub = tier_panel[tier_panel["constituent_id"] == const_id]

        blended_volumes = compute_blended_tier_volumes(
            constituent_id=const_id,
            as_of_date=as_of_date_value,
            panel_df=sub,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
        )
        if blended_volumes is None:
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=const_id,
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.TIER_VOLUME_UNAVAILABLE.value,
                    contributor_count=int(sub["contributor_id"].nunique()),
                )
            )
            continue

        # Per-tier price collapse: filter price rows for each tier with
        # resolved volume; collapse via volume-weighted contributor average
        # (DL 2026-04-30 Phase 7 contributor-to-constituent collapse rule
        # applied within each tier independently).
        per_tier_data: dict[AttestationTier, dict[str, float]] = {}
        for tier_t, raw_v in blended_volumes.items():
            if tier_t == AttestationTier.A:
                price_rows = sub[
                    (sub["attestation_tier"] == AttestationTier.A.value)
                    & (sub["volume_mtok_7d"] > 0)
                ]
            elif tier_t == AttestationTier.B:
                price_rows = sub[sub["attestation_tier"] == AttestationTier.B.value]
            else:  # AttestationTier.C
                price_rows = sub[
                    (sub["attestation_tier"] == AttestationTier.C.value)
                    & (sub["volume_mtok_7d"] > 0)
                ]
            if price_rows.empty:
                continue  # tier has volume but no surviving prices; drop from blend
            tier_price = collapse_constituent_price(price_rows, price_col=price_field)
            per_tier_data[tier_t] = {
                "raw_volume": float(raw_v),
                "tier_price": float(tier_price),
                "contributor_count": int(price_rows["contributor_id"].nunique()),
            }

        if not per_tier_data:
            # All resolved tiers lost their price rows; constituent excluded.
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=const_id,
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.SELECTED_TIER_NO_PRICE_ROWS.value,
                    contributor_count=int(sub["contributor_id"].nunique()),
                )
            )
            continue

        rows.append(
            {
                "constituent_id": const_id,
                "per_tier_data": per_tier_data,
            }
        )

    if not rows:
        _publish(pending_decisions)
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

    # Pass 2 (continuous blending): within-tier shares per tier across
    # contributing constituents; coefficient redistribution per constituent;
    # combined w_vol and combined price per constituent.
    volumes_by_tier_b: dict[AttestationTier, dict[str, float]] = {
        AttestationTier.A: {},
        AttestationTier.B: {},
        AttestationTier.C: {},
    }
    for r in rows:
        cid = str(r["constituent_id"])
        per_tier = r["per_tier_data"]
        assert isinstance(per_tier, dict)
        for tier_t, info in per_tier.items():
            volumes_by_tier_b[tier_t][cid] = float(info["raw_volume"])
    shares_by_tier_b: dict[AttestationTier, dict[str, float]] = {
        tier_t: compute_within_tier_share(vols)
        for tier_t, vols in volumes_by_tier_b.items()
    }

    for r in rows:
        cid = str(r["constituent_id"])
        per_tier = r["per_tier_data"]
        assert isinstance(per_tier, dict)
        coefficients = redistribute_blending_coefficients(
            available_tiers=set(per_tier.keys()),
            default_coefficients=config.tier_blending_coefficients,
        )
        combined_w_vol = 0.0
        combined_price = 0.0
        for tier_t, info in per_tier.items():
            share = shares_by_tier_b[tier_t][cid]
            coef = coefficients[tier_t]
            w_vol_contribution = coef * volume_weight(share, tier_t, config)
            combined_w_vol += w_vol_contribution
            combined_price += coef * float(info["tier_price"])
            info["share"] = share
            info["coefficient"] = coef
            info["w_vol_contribution"] = w_vol_contribution
        r["w_vol"] = combined_w_vol
        r["price"] = combined_price
        r["contributor_count_total"] = sum(
            int(info["contributor_count"]) for info in per_tier.values()
        )

    n_active = len(rows)

    # n_a/n_b/n_c under continuous blending: count of constituents with ANY
    # non-zero contribution from each tier (constituents may overlap across
    # tiers under blending).
    n_a = sum(1 for r in rows if AttestationTier.A in r["per_tier_data"])
    n_b = sum(1 for r in rows if AttestationTier.B in r["per_tier_data"])
    n_c = sum(1 for r in rows if AttestationTier.C in r["per_tier_data"])

    def _emit_tier_aggregation_suspended_rows(
        rows_in: list[dict[str, Any]],
        median: float = float("nan"),
        compute_w_exp_for_audit: bool = False,
    ) -> None:
        """Emit one TIER_AGGREGATION_SUSPENDED audit row per (constituent,
        contributing tier). Median + w_exp may or may not be computed
        depending on which suspension path fires.
        """
        for r in rows_in:
            cid = str(r["constituent_id"])
            per_tier = r["per_tier_data"]
            assert isinstance(per_tier, dict)
            if compute_w_exp_for_audit and median > 0:
                distance_pct = abs(float(r["price"]) - median) / median
                w_exp_value = exponential_weight(
                    float(r["price"]), median, config.lambda_
                )
                combined_w = float(r["w_vol"]) * w_exp_value
            else:
                distance_pct = float("nan")
                w_exp_value = float("nan")
                combined_w = float("nan")
            for tier_t, info in per_tier.items():
                pending_decisions.append(
                    _decision_row(
                        as_of_date=as_of_date_value,
                        index_code=tier.value,
                        version=version,
                        ordering=ordering,
                        constituent_id=cid,
                        included=False,
                        exclusion_reason=ConstituentExclusionReason.TIER_AGGREGATION_SUSPENDED.value,
                        attestation_tier=tier_t.value,
                        coefficient=float(info["coefficient"]),
                        raw_volume_mtok=float(info["raw_volume"]),
                        within_tier_volume_share=float(info["share"]),
                        tier_collapsed_price_usd_mtok=float(info["tier_price"]),
                        w_vol_contribution=float(info["w_vol_contribution"]),
                        constituent_price_usd_mtok=float(r["price"]),
                        tier_median_price_usd_mtok=median,
                        price_distance_from_median_pct=distance_pct,
                        w_vol=float(r["w_vol"]),
                        w_exp=w_exp_value,
                        combined_weight=combined_w,
                        contributor_count=int(info["contributor_count"]),
                    )
                )

    if n_active < config.min_constituents_per_tier:
        # Tier suspends — emit each "would-be-active" constituent as
        # included=False with TIER_AGGREGATION_SUSPENDED, one row per
        # contributing tier. Median cascade never ran; w_exp/combined_weight
        # are NaN.
        _emit_tier_aggregation_suspended_rows(rows)
        _publish(pending_decisions)
        return _suspended_row(
            tier=tier,
            as_of_date=as_of_date_value,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.INSUFFICIENT_CONSTITUENTS,
            n_constituents=n_constituents_total,
            n_constituents_active=n_active,
            n_a=n_a,
            n_b=n_b,
            n_c=n_c,
            prior_raw_value=prior_raw_value,
        )

    # 4. Tier median across active constituents (Section 3.3.3) — using
    # blended constituent prices.
    tier_median = float(
        np.median(np.array([float(r["price"]) for r in rows], dtype=np.float64))
    )

    # 5. w_exp per constituent (using blended price).
    for r in rows:
        r["w_exp"] = exponential_weight(float(r["price"]), tier_median, config.lambda_)
        r["weight"] = float(r["w_vol"]) * float(r["w_exp"])

    total_weight = float(sum(float(r["weight"]) for r in rows))

    if total_weight <= 0:
        _emit_tier_aggregation_suspended_rows(
            rows, median=tier_median, compute_w_exp_for_audit=True
        )
        _publish(pending_decisions)
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
        sum(float(r["weight"]) * float(r["price"]) for r in rows) / total_weight
    )

    # 7. Tier-level instrumentation. Under continuous blending, each
    # constituent's combined weight (w_vol_combined x w_exp) decomposes
    # across tiers via per-tier w_vol_contribution. tier_X_weight_share is
    # the share of that decomposition attributable to tier X.
    weight_a = (
        sum(
            float(r["per_tier_data"][AttestationTier.A]["w_vol_contribution"])
            * float(r["w_exp"])
            for r in rows
            if AttestationTier.A in r["per_tier_data"]
        )
        / total_weight
    )
    weight_b = (
        sum(
            float(r["per_tier_data"][AttestationTier.B]["w_vol_contribution"])
            * float(r["w_exp"])
            for r in rows
            if AttestationTier.B in r["per_tier_data"]
        )
        / total_weight
    )
    weight_c = (
        sum(
            float(r["per_tier_data"][AttestationTier.C]["w_vol_contribution"])
            * float(r["w_exp"])
            for r in rows
            if AttestationTier.C in r["per_tier_data"]
        )
        / total_weight
    )

    # 8. Emit included=True decision rows — one per (constituent, contributing
    # tier). Constituent-level fields (price, median, w_exp, w_vol, combined_weight)
    # repeat across the constituent's per-tier rows for query convenience.
    for r in rows:
        cid = str(r["constituent_id"])
        per_tier = r["per_tier_data"]
        assert isinstance(per_tier, dict)
        distance_pct = abs(float(r["price"]) - tier_median) / tier_median
        for tier_t, info in per_tier.items():
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=cid,
                    included=True,
                    exclusion_reason="",
                    attestation_tier=tier_t.value,
                    coefficient=float(info["coefficient"]),
                    raw_volume_mtok=float(info["raw_volume"]),
                    within_tier_volume_share=float(info["share"]),
                    tier_collapsed_price_usd_mtok=float(info["tier_price"]),
                    w_vol_contribution=float(info["w_vol_contribution"]),
                    constituent_price_usd_mtok=float(r["price"]),
                    tier_median_price_usd_mtok=tier_median,
                    price_distance_from_median_pct=distance_pct,
                    w_vol=float(r["w_vol"]),
                    w_exp=float(r["w_exp"]),
                    combined_weight=float(r["weight"]),
                    contributor_count=int(info["contributor_count"]),
                )
            )
    _publish(pending_decisions)

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
# Batch E — weight-then-TWAP slot-level aggregation
# (decision log 2026-04-30 "Phase 7 Batch E — weight-then-TWAP slot-level
# implementation choices for Phase 10 comparison")
# ---------------------------------------------------------------------------


_TWAP_SLOTS_PER_DAY = 32


def _build_slot_arrays_for_pair(
    contributor_id: str,
    constituent_id: str,
    as_of_date: date,
    panel_row: pd.Series,
    events: list[dict[str, Any]] | None,
    excluded_slot_indices: set[int] | None,
    *,
    blended: bool,
) -> npt.NDArray[np.float64]:
    """Build a 32-element price array for one (contributor, constituent, date).

    Excluded slots are NaN. When ``blended=True``, returns
    ``0.75*output + 0.25*input`` per slot (methodology Section 3.3.4
    output-heavy weighting; decision log 2026-04-30 "Phase 7 Batch
    B'-fix"). Mirrors ``reconstruct_slots`` segmentation logic on event
    days; uses panel posted price on non-event days.

    Used only by the weight-then-TWAP path; canonical TWAP-then-weight reads
    pre-computed daily TWAPs from the panel directly (compute_panel_twap).
    """

    def _slots_for_field(events: list[dict[str, Any]] | None, raw_field: str) -> npt.NDArray[np.float64]:
        if events:
            arr = np.empty(_TWAP_SLOTS_PER_DAY, dtype=np.float64)
            first = events[0]
            first_slot = int(first["change_slot_idx"])
            arr[:first_slot] = float(first[f"old_{raw_field}"])
            for i, ev in enumerate(events):
                current_slot = int(ev["change_slot_idx"])
                current_new = float(ev[f"new_{raw_field}"])
                end_slot = (
                    int(events[i + 1]["change_slot_idx"])
                    if i + 1 < len(events)
                    else _TWAP_SLOTS_PER_DAY
                )
                arr[current_slot:end_slot] = current_new
            return arr
        # No event → all slots = panel posted price
        return np.full(
            _TWAP_SLOTS_PER_DAY,
            float(panel_row[raw_field]),
            dtype=np.float64,
        )

    if blended:
        out_arr = _slots_for_field(events, "output_price_usd_mtok")
        in_arr = _slots_for_field(events, "input_price_usd_mtok")
        slots = 0.75 * out_arr + 0.25 * in_arr
    else:
        slots = _slots_for_field(events, "output_price_usd_mtok")

    if excluded_slot_indices:
        for idx in excluded_slot_indices:
            slots[idx] = np.nan

    return slots


def _build_event_lookup_local(
    change_events_df: pd.DataFrame,
) -> dict[tuple[str, str, pd.Timestamp], list[dict[str, Any]]]:
    """Mirrors ``tprr.twap.reconstruct._build_event_lookup``; replicated here
    to avoid coupling aggregation.py to the twap module's private helpers."""
    lookup: dict[tuple[str, str, pd.Timestamp], list[dict[str, Any]]] = {}
    if change_events_df.empty:
        return lookup
    for raw in change_events_df.to_dict("records"):
        rec: dict[str, Any] = {str(k): v for k, v in raw.items()}
        key = (
            str(rec["contributor_id"]),
            str(rec["constituent_id"]),
            pd.Timestamp(rec["event_date"]),
        )
        lookup.setdefault(key, []).append(rec)
    for k in lookup:
        lookup[k].sort(key=lambda r: int(r["change_slot_idx"]))
    return lookup


def _build_exclusions_lookup_local(
    excluded_slots_df: pd.DataFrame | None,
) -> dict[tuple[str, str, pd.Timestamp], set[int]]:
    """Mirrors ``tprr.twap.reconstruct._build_exclusions_lookup``."""
    lookup: dict[tuple[str, str, pd.Timestamp], set[int]] = {}
    if excluded_slots_df is None or excluded_slots_df.empty:
        return lookup
    for rec in excluded_slots_df.to_dict("records"):
        key = (
            str(rec["contributor_id"]),
            str(rec["constituent_id"]),
            pd.Timestamp(rec["date"]),
        )
        lookup.setdefault(key, set()).add(int(rec["slot_idx"]))
    return lookup


def _compute_weight_then_twap_index(
    panel_day_df: pd.DataFrame,
    change_events_df: pd.DataFrame,
    excluded_slots_df: pd.DataFrame | None,
    tier: Tier,
    config: IndexConfig,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
    suspended_pairs_df: pd.DataFrame | None,
    *,
    prior_raw_value: float | None,
    version: str,
    price_field: str,
    decisions_out: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Slot-level aggregation, then TWAP across slots — alternate ordering.

    See decision log 2026-04-30 "Phase 7 Batch E — weight-then-TWAP slot-
    level implementation choices for Phase 10 comparison" for the four
    operational choices this implements:

      1. Daily volumes applied at every slot (w_vol constant per pair).
      2. Tier selection (A/B/C) computed once per day from daily metadata.
      3. Slot-level min-3 check; slots with <3 active constituents are
         excluded from the daily TWAP. All-32-slots-fail → daily suspended.
      4. Per-constituent slot price = volume-weighted avg across slot-
         surviving contributors using daily volumes.

    Audit trail: the per-constituent decision rows for ``included=True``
    constituents carry daily-averaged numeric fields (tier_median, w_exp,
    distance, weight_share averaged across surviving slots; constituent
    price = TWAP of surviving slot prices). This makes weight-then-TWAP
    audit rows comparable in shape to TWAP-then-weight while documenting
    that the underlying aggregation is per-slot.

    The ``price_field`` argument signals which price stream to use:
    ``twap_output_usd_mtok`` (default) → slot-level output prices;
    ``twap_blended_usd_mtok`` → slot-level blended (0.25 x out + 0.75 x in).
    """
    blended = price_field == "twap_blended_usd_mtok"
    ordering = "weight_then_twap"

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
            f"_compute_weight_then_twap_index: expected single observation_date, "
            f"got {len(unique_dates)}"
        )
    as_of_date_value = pd.Timestamp(unique_dates[0]).date()

    # 1. Filter by tier_code (panel-as-truth).
    tier_panel = panel_day_df[panel_day_df["tier_code"] == tier.value].copy()
    pre_drop_constituents: set[str] = {
        str(c) for c in tier_panel["constituent_id"].unique()
    }

    # 2. Drop suspended (contributor, constituent) pairs.
    # Phase 7H Batch D: same interval-aware filter as the canonical path.
    if suspended_pairs_df is not None and not suspended_pairs_df.empty:
        as_of_ts_w2t = pd.Timestamp(as_of_date_value)
        suspension_active = suspended_pairs_df["suspension_date"] <= as_of_ts_w2t
        if "reinstatement_date" in suspended_pairs_df.columns:
            reinstated = (
                suspended_pairs_df["reinstatement_date"].notna()
                & (suspended_pairs_df["reinstatement_date"] <= as_of_ts_w2t)
            )
            active_susp = suspended_pairs_df[suspension_active & ~reinstated]
        else:
            active_susp = suspended_pairs_df[suspension_active]
        if not active_susp.empty:
            keep_keys = pd.MultiIndex.from_arrays(
                [tier_panel["contributor_id"], tier_panel["constituent_id"]]
            )
            drop_keys = pd.MultiIndex.from_arrays(
                [active_susp["contributor_id"], active_susp["constituent_id"]]
            )
            tier_panel = tier_panel[~keep_keys.isin(drop_keys)]

    post_drop_constituents: set[str] = {
        str(c) for c in tier_panel["constituent_id"].unique()
    }
    dropped_constituents = pre_drop_constituents - post_drop_constituents
    n_constituents_total = int(tier_panel["constituent_id"].nunique())

    pending_decisions: list[dict[str, Any]] = []
    for const_id in sorted(dropped_constituents):
        pending_decisions.append(
            _decision_row(
                as_of_date=as_of_date_value,
                index_code=tier.value,
                version=version,
                ordering=ordering,
                constituent_id=const_id,
                included=False,
                exclusion_reason=ConstituentExclusionReason.ALL_PAIRS_SUSPENDED.value,
                contributor_count=0,
            )
        )

    def _publish(decisions: list[dict[str, Any]]) -> None:
        if decisions_out is not None:
            decisions_out.extend(decisions)

    if tier_panel.empty:
        _publish(pending_decisions)
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

    # 3. Build slot lookups once per day.
    event_lookup = _build_event_lookup_local(change_events_df)
    exclusions_lookup = _build_exclusions_lookup_local(excluded_slots_df)
    as_of_ts = pd.Timestamp(as_of_date_value)

    # 4. Per-constituent: blended tier resolution + per-tier per-contributor
    # slot arrays. Each entry in ``constituents`` carries daily metadata
    # (per_tier_data) plus slot arrays per tier per contributor.
    constituents: list[dict[str, Any]] = []
    for constituent_id in tier_panel["constituent_id"].unique():
        const_id = str(constituent_id)
        sub = tier_panel[tier_panel["constituent_id"] == const_id]

        blended_volumes = compute_blended_tier_volumes(
            constituent_id=const_id,
            as_of_date=as_of_date_value,
            panel_df=sub,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
        )
        if blended_volumes is None:
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=const_id,
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.TIER_VOLUME_UNAVAILABLE.value,
                    contributor_count=int(sub["contributor_id"].nunique()),
                )
            )
            continue

        # Per-tier: filter price rows + build slot arrays per contributor.
        per_tier_data: dict[AttestationTier, dict[str, Any]] = {}
        for tier_t, raw_v in blended_volumes.items():
            if tier_t == AttestationTier.A:
                price_rows = sub[
                    (sub["attestation_tier"] == AttestationTier.A.value)
                    & (sub["volume_mtok_7d"] > 0)
                ]
            elif tier_t == AttestationTier.B:
                price_rows = sub[sub["attestation_tier"] == AttestationTier.B.value]
            else:  # AttestationTier.C
                price_rows = sub[
                    (sub["attestation_tier"] == AttestationTier.C.value)
                    & (sub["volume_mtok_7d"] > 0)
                ]
            if price_rows.empty:
                continue

            contributor_slot_data: list[
                tuple[str, npt.NDArray[np.float64], float]
            ] = []
            for _, prow in price_rows.iterrows():
                contributor_id = str(prow["contributor_id"])
                key = (contributor_id, const_id, as_of_ts)
                slots = _build_slot_arrays_for_pair(
                    contributor_id=contributor_id,
                    constituent_id=const_id,
                    as_of_date=as_of_date_value,
                    panel_row=prow,
                    events=event_lookup.get(key),
                    excluded_slot_indices=exclusions_lookup.get(key),
                    blended=blended,
                )
                vol = float(prow["volume_mtok_7d"])
                contributor_slot_data.append((contributor_id, slots, vol))

            per_tier_data[tier_t] = {
                "raw_volume": float(raw_v),
                "contributor_slots": contributor_slot_data,
                "contributor_count": int(price_rows["contributor_id"].nunique()),
            }

        if not per_tier_data:
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=const_id,
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.SELECTED_TIER_NO_PRICE_ROWS.value,
                    contributor_count=int(sub["contributor_id"].nunique()),
                )
            )
            continue

        constituents.append(
            {
                "constituent_id": const_id,
                "per_tier_data": per_tier_data,
            }
        )

    if not constituents:
        _publish(pending_decisions)
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

    # Within-tier shares + coefficients per constituent (daily, applied at
    # every slot — DL 2026-04-30 Batch E choice 1+2: volumes/coefficients
    # are daily, only prices vary per slot).
    volumes_by_tier_b: dict[AttestationTier, dict[str, float]] = {
        AttestationTier.A: {},
        AttestationTier.B: {},
        AttestationTier.C: {},
    }
    for c in constituents:
        per_tier = c["per_tier_data"]
        for tier_t, info in per_tier.items():
            volumes_by_tier_b[tier_t][str(c["constituent_id"])] = float(
                info["raw_volume"]
            )
    shares_by_tier_b: dict[AttestationTier, dict[str, float]] = {
        tier_t: compute_within_tier_share(vols)
        for tier_t, vols in volumes_by_tier_b.items()
    }
    for c in constituents:
        cid = str(c["constituent_id"])
        per_tier = c["per_tier_data"]
        coefficients = redistribute_blending_coefficients(
            available_tiers=set(per_tier.keys()),
            default_coefficients=config.tier_blending_coefficients,
        )
        combined_w_vol = 0.0
        for tier_t, info in per_tier.items():
            share = shares_by_tier_b[tier_t][cid]
            coef = coefficients[tier_t]
            w_vol_contribution = coef * volume_weight(share, tier_t, config)
            combined_w_vol += w_vol_contribution
            info["share"] = share
            info["coefficient"] = coef
            info["w_vol_contribution"] = w_vol_contribution
        c["w_vol"] = combined_w_vol

    # 5. Slot-level loop.
    # For each slot s: collapse contributor prices per constituent (volume-
    # weighted), check min-3, compute median + w_exp + slot aggregate.
    n_constituents_resolved = len(constituents)
    min_constituents = config.min_constituents_per_tier

    # Phase 7H Batch B continuous blending at slot level: per slot,
    # per constituent, per tier compute slot-level price, blend across
    # tiers via daily coefficients (renormalised over tiers with valid
    # slot data), check min-3, slot aggregate, average across slots.
    per_tier_slot_prices: dict[tuple[str, AttestationTier], list[float]] = {}
    per_constituent_slot_prices: dict[str, list[float]] = {}
    per_constituent_slot_w_exp: dict[str, list[float]] = {}
    per_constituent_slot_combined_weight: dict[str, list[float]] = {}
    per_constituent_slot_median: dict[str, list[float]] = {}
    per_constituent_slot_distance: dict[str, list[float]] = {}
    for c in constituents:
        cid_init = str(c["constituent_id"])
        per_constituent_slot_prices[cid_init] = []
        per_constituent_slot_w_exp[cid_init] = []
        per_constituent_slot_combined_weight[cid_init] = []
        per_constituent_slot_median[cid_init] = []
        per_constituent_slot_distance[cid_init] = []
        for tier_t in c["per_tier_data"]:
            per_tier_slot_prices[(cid_init, tier_t)] = []

    slot_aggregates: list[float] = []

    def _collapse_tier_slot_price(
        contributor_slots: list[tuple[str, npt.NDArray[np.float64], float]],
        slot_idx: int,
    ) -> float:
        """Volume-weighted slot-s price across this tier's slot-surviving
        contributors. NaN when no contributor has a non-NaN slot-s value."""
        total_v = 0.0
        total_pv = 0.0
        n_surviving = 0
        simple_sum = 0.0
        for _contrib_id, slots_arr, vol in contributor_slots:
            p = float(slots_arr[slot_idx])
            if not np.isnan(p):
                total_v += vol
                total_pv += vol * p
                simple_sum += p
                n_surviving += 1
        if n_surviving == 0:
            return float("nan")
        if total_v > 0:
            return total_pv / total_v
        return simple_sum / n_surviving

    for s in range(_TWAP_SLOTS_PER_DAY):
        # Per constituent: per-tier slot-s price + blended slot-s price
        # (renormalised coefficients over tiers with valid slot data).
        per_constituent_blend: dict[str, dict[str, Any]] = {}
        for c in constituents:
            cid_loop = str(c["constituent_id"])
            per_tier = c["per_tier_data"]
            tier_prices_at_slot: dict[AttestationTier, float] = {}
            for tier_t, info in per_tier.items():
                p_t_s = _collapse_tier_slot_price(info["contributor_slots"], s)
                if not np.isnan(p_t_s):
                    tier_prices_at_slot[tier_t] = p_t_s
            if not tier_prices_at_slot:
                continue
            slot_coefs = redistribute_blending_coefficients(
                available_tiers=set(tier_prices_at_slot.keys()),
                default_coefficients=config.tier_blending_coefficients,
            )
            blended_slot_price = sum(
                slot_coefs[t] * tier_prices_at_slot[t] for t in tier_prices_at_slot
            )
            per_constituent_blend[cid_loop] = {
                "blended_price": blended_slot_price,
                "tier_prices": tier_prices_at_slot,
            }

        if len(per_constituent_blend) < min_constituents:
            continue

        slot_prices_arr = np.array(
            [v["blended_price"] for v in per_constituent_blend.values()],
            dtype=np.float64,
        )
        median_s = float(np.median(slot_prices_arr))
        if median_s <= 0:
            continue

        numer = 0.0
        denom = 0.0
        per_slot_weights: dict[str, float] = {}
        for cid_w, blend_info in per_constituent_blend.items():
            c_record = next(c for c in constituents if c["constituent_id"] == cid_w)
            w_vol_c = float(c_record["w_vol"])
            p_s = float(blend_info["blended_price"])
            w_exp_s = exponential_weight(p_s, median_s, config.lambda_)
            w_combined = w_vol_c * w_exp_s
            numer += w_combined * p_s
            denom += w_combined
            per_slot_weights[cid_w] = w_combined

        if denom <= 0:
            continue

        slot_value = numer / denom
        slot_aggregates.append(slot_value)

        for cid_acc, blend_info in per_constituent_blend.items():
            p_s = float(blend_info["blended_price"])
            distance_pct = abs(p_s - median_s) / median_s
            w_exp_s = exponential_weight(p_s, median_s, config.lambda_)
            w_combined = per_slot_weights[cid_acc]
            per_constituent_slot_prices[cid_acc].append(p_s)
            per_constituent_slot_w_exp[cid_acc].append(w_exp_s)
            per_constituent_slot_combined_weight[cid_acc].append(w_combined)
            per_constituent_slot_median[cid_acc].append(median_s)
            per_constituent_slot_distance[cid_acc].append(distance_pct)
            for tier_tx, p_t_s in blend_info["tier_prices"].items():
                per_tier_slot_prices[(cid_acc, tier_tx)].append(p_t_s)

    n_a = sum(1 for c in constituents if AttestationTier.A in c["per_tier_data"])
    n_b = sum(1 for c in constituents if AttestationTier.B in c["per_tier_data"])
    n_c = sum(1 for c in constituents if AttestationTier.C in c["per_tier_data"])

    def _emit_per_tier_audit_rows_w2t(
        c: dict[str, Any],
        *,
        included: bool,
        exclusion_reason: str = "",
        constituent_price: float = float("nan"),
        avg_median: float = float("nan"),
        avg_distance: float = float("nan"),
        avg_w_exp: float = float("nan"),
        avg_combined: float = float("nan"),
    ) -> None:
        """Emit one per-tier audit row per (constituent, contributing tier)
        in the weight-then-TWAP path. tier_collapsed_price_usd_mtok is the
        average over surviving slots of this tier's collapsed slot price."""
        cid_inner = str(c["constituent_id"])
        per_tier = c["per_tier_data"]
        for tier_t, info in per_tier.items():
            slot_prices_for_tier = per_tier_slot_prices.get((cid_inner, tier_t), [])
            avg_tier_price = (
                float(np.mean(slot_prices_for_tier))
                if slot_prices_for_tier
                else float("nan")
            )
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=cid_inner,
                    included=included,
                    exclusion_reason=exclusion_reason,
                    attestation_tier=tier_t.value,
                    coefficient=float(info["coefficient"]),
                    raw_volume_mtok=float(info["raw_volume"]),
                    within_tier_volume_share=float(info["share"]),
                    tier_collapsed_price_usd_mtok=avg_tier_price,
                    w_vol_contribution=float(info["w_vol_contribution"]),
                    constituent_price_usd_mtok=constituent_price,
                    tier_median_price_usd_mtok=avg_median,
                    price_distance_from_median_pct=avg_distance,
                    w_vol=float(c["w_vol"]),
                    w_exp=avg_w_exp,
                    combined_weight=avg_combined,
                    contributor_count=int(info["contributor_count"]),
                )
            )

    # 6. Daily fix from surviving slots.
    if not slot_aggregates:
        for c in constituents:
            _emit_per_tier_audit_rows_w2t(
                c,
                included=False,
                exclusion_reason=ConstituentExclusionReason.TIER_AGGREGATION_SUSPENDED.value,
            )
        _publish(pending_decisions)
        return _suspended_row(
            tier=tier,
            as_of_date=as_of_date_value,
            config=config,
            ordering=ordering,
            version=version,
            reason=SuspensionReason.INSUFFICIENT_CONSTITUENTS,
            n_constituents=n_constituents_total,
            n_constituents_active=n_constituents_resolved,
            n_a=n_a,
            n_b=n_b,
            n_c=n_c,
            prior_raw_value=prior_raw_value,
        )

    raw_value = float(np.mean(slot_aggregates))

    # Tier-level instrumentation under continuous blending: each tier's
    # contribution is its w_vol_contribution x avg_w_exp summed across
    # constituents. Approximation — for daily-coefficient consistency in
    # the slot-level path, we use the daily w_vol_contribution x the
    # constituent's avg slot w_exp.
    weight_a, weight_b, weight_c = 0.0, 0.0, 0.0
    for c in constituents:
        cid_w = str(c["constituent_id"])
        slot_w_exp = per_constituent_slot_w_exp.get(cid_w, [])
        if not slot_w_exp:
            continue
        avg_w_exp_c = float(np.mean(slot_w_exp))
        per_tier = c["per_tier_data"]
        for tier_t, info in per_tier.items():
            piece = float(info["w_vol_contribution"]) * avg_w_exp_c
            if tier_t == AttestationTier.A:
                weight_a += piece
            elif tier_t == AttestationTier.B:
                weight_b += piece
            else:
                weight_c += piece
    weight_total = weight_a + weight_b + weight_c
    if weight_total > 0:
        weight_a /= weight_total
        weight_b /= weight_total
        weight_c /= weight_total

    # 7. Per-constituent per-tier audit rows.
    for c in constituents:
        cid_audit = str(c["constituent_id"])
        slot_prices = per_constituent_slot_prices[cid_audit]
        if not slot_prices:
            _emit_per_tier_audit_rows_w2t(
                c,
                included=False,
                exclusion_reason=ConstituentExclusionReason.TIER_AGGREGATION_SUSPENDED.value,
            )
            continue
        avg_price = float(np.mean(slot_prices))
        avg_median = float(np.mean(per_constituent_slot_median[cid_audit]))
        avg_distance = float(np.mean(per_constituent_slot_distance[cid_audit]))
        avg_w_exp = float(np.mean(per_constituent_slot_w_exp[cid_audit]))
        avg_combined = float(
            np.mean(per_constituent_slot_combined_weight[cid_audit])
        )
        _emit_per_tier_audit_rows_w2t(
            c,
            included=True,
            exclusion_reason="",
            constituent_price=avg_price,
            avg_median=avg_median,
            avg_distance=avg_distance,
            avg_w_exp=avg_w_exp,
            avg_combined=avg_combined,
        )

    _publish(pending_decisions)

    return {
        "as_of_date": as_of_date_value,
        "index_code": tier.value,
        "version": version,
        "lambda": config.lambda_,
        "ordering": ordering,
        "raw_value_usd_mtok": raw_value,
        "index_level": float("nan"),
        "n_constituents": n_constituents_total,
        "n_constituents_active": n_constituents_resolved,
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
    price_field: str = "twap_output_usd_mtok",
    decisions_out: list[dict[str, Any]] | None = None,
    change_events_df: pd.DataFrame | None = None,
    excluded_slots_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run aggregation across every distinct date in ``panel_df`` for one tier.

    ``panel_df`` must have the column named by ``price_field`` populated
    upstream (default ``twap_output_usd_mtok`` set by
    ``compute_panel_twap``; ``twap_blended_usd_mtok`` for the TPRR_B
    series). The driver iterates dates in ascending order, threading the
    most recent valid ``raw_value_usd_mtok`` as ``prior_raw_value`` so
    suspended rows carry it forward (Q2 lock).

    Output is an IndexValueDF-shape DataFrame (rebase to ``index_level``
    is delegated to ``rebase_index_level`` — caller decides anchor).

    When ``decisions_out`` is provided, per-day per-constituent audit
    rows are appended (one element per constituent per date — see
    ``compute_tier_index`` for schema).
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
            price_field=price_field,
            decisions_out=decisions_out,
            change_events_df=change_events_df,
            excluded_slots_df=excluded_slots_df,
        )
        rows.append(result)
        if not result["suspended"] and not np.isnan(result["raw_value_usd_mtok"]):
            prior_raw_value = float(result["raw_value_usd_mtok"])

    out = pd.DataFrame(rows)
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).astype("datetime64[ns]")
    return out


def _decisions_list_to_df(decisions: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert an accumulated decisions list into a ConstituentDecisionDF.

    Empty input returns a DataFrame with the audit-trail columns present
    but no rows — keeps the schema contract uniform for downstream
    consumers (Phase 9/10) and avoids ``KeyError`` on ``df.columns``.
    """
    if not decisions:
        empty: dict[str, list[Any]] = {col: [] for col in _DECISION_FIELDS}
        out = pd.DataFrame(empty)
    else:
        out = pd.DataFrame(decisions)
    if "as_of_date" in out.columns and not out.empty:
        out["as_of_date"] = pd.to_datetime(out["as_of_date"]).astype("datetime64[ns]")
    elif "as_of_date" in out.columns:
        out["as_of_date"] = out["as_of_date"].astype("datetime64[ns]")
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
    ``constituent_decisions`` is the per-(date, index_code, constituent_id)
    audit DataFrame produced by Batch D Q1; empty when no constituents
    surfaced through any tier.
    """

    indices: dict[str, pd.DataFrame]
    rebase_anchors: dict[str, date | None]
    constituent_decisions: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_rebase_metadata_df(
    indices: dict[str, pd.DataFrame],
    rebase_anchors: dict[str, date | None],
    base_date: date,
) -> pd.DataFrame:
    """Per-index rebase metadata DataFrame for Phase 9/10 consumption.

    Columns:

    - ``index_code``: str — TPRR_F/S/E/FPR/SER/B_F/B_S/B_E
    - ``base_date``: date — ``IndexConfig.base_date`` driving this run
    - ``anchor_date``: ``date | None`` — actual rebase anchor (the first
      non-suspended row at-or-after ``base_date`` with positive finite
      ``raw_value_usd_mtok``; ``None`` when no eligible anchor exists)
    - ``anchor_raw_value``: float — ``raw_value_usd_mtok`` at the anchor
      row (``NaN`` when ``anchor_date is None``)
    - ``n_pre_anchor_suspended_days``: int — count of rows with
      ``suspended=True`` and ``as_of_date < anchor_date``. When
      ``anchor_date`` is ``None`` (un-rebasable index), holds the total
      suspended-row count for the index — no anchor was reached, so every
      suspended day counts as "pre-anchor" in the limit.

    Companion to ``FullPipelineResults.rebase_anchors`` (the dict): the
    dict stays as a quick lookup; this DataFrame is the structured artefact
    Phase 10 sweeps over when comparing parameter realisations.
    """
    rows: list[dict[str, Any]] = []
    for code, df in indices.items():
        anchor = rebase_anchors.get(code)
        if anchor is None:
            anchor_raw_value = float("nan")
            n_pre = (
                int(df["suspended"].sum())
                if not df.empty and "suspended" in df.columns
                else 0
            )
        else:
            anchor_ts = pd.Timestamp(anchor)
            anchor_rows = df[df["as_of_date"] == anchor_ts]
            anchor_raw_value = (
                float(anchor_rows.iloc[0]["raw_value_usd_mtok"])
                if not anchor_rows.empty
                else float("nan")
            )
            n_pre = int(
                df[(df["as_of_date"] < anchor_ts) & df["suspended"]].shape[0]
            )
        rows.append(
            {
                "index_code": code,
                "base_date": base_date,
                "anchor_date": anchor,
                "anchor_raw_value": anchor_raw_value,
                "n_pre_anchor_suspended_days": n_pre,
            }
        )
    return pd.DataFrame(rows)


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
    change_events_df: pd.DataFrame | None = None,
    excluded_slots_df: pd.DataFrame | None = None,
) -> CoreIndexResults:
    """Run aggregation for TPRR_F, TPRR_S, TPRR_E with rebase to 100 on base_date.

    Each tier runs independently. Per-tier rebase anchor is computed from
    that tier's own indices_df — different tiers may have different
    anchors when ``base_date`` itself is suspended for some tier. Per-
    constituent audit rows are accumulated across all three tiers and
    returned in ``CoreIndexResults.constituent_decisions``.

    ``change_events_df`` and ``excluded_slots_df`` are required when
    ``ordering='weight_then_twap'``; ignored for the canonical TWAP-then-
    weight path which reads pre-computed daily TWAP columns from the panel.
    """
    indices: dict[str, pd.DataFrame] = {}
    anchors: dict[str, date | None] = {}
    decisions: list[dict[str, Any]] = []
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
            decisions_out=decisions,
            change_events_df=change_events_df,
            excluded_slots_df=excluded_slots_df,
        )
        rebased, anchor = rebase_index_level(
            tier_indices, base_date=config.base_date
        )
        indices[tier.value] = rebased
        anchors[tier.value] = anchor
    return CoreIndexResults(
        indices=indices,
        rebase_anchors=anchors,
        constituent_decisions=_decisions_list_to_df(decisions),
    )
