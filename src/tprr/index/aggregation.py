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
    "selected_attestation_tier",
    "raw_volume_mtok",
    "constituent_price_usd_mtok",
    "tier_median_price_usd_mtok",
    "price_distance_from_median_pct",
    "w_vol",
    "w_exp",
    "combined_weight",
    "weight_share_within_tier",
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
    selected_attestation_tier: str = "",
    raw_volume_mtok: float = float("nan"),
    constituent_price_usd_mtok: float = float("nan"),
    tier_median_price_usd_mtok: float = float("nan"),
    price_distance_from_median_pct: float = float("nan"),
    w_vol: float = float("nan"),
    w_exp: float = float("nan"),
    combined_weight: float = float("nan"),
    weight_share_within_tier: float = float("nan"),
    contributor_count: int = 0,
) -> dict[str, Any]:
    """Build one ConstituentDecisionDF row. NaN defaults match the audit
    contract: every numeric field is populated when ``included=True`` and
    selectively populated for exclusion paths (see ``compute_tier_index``)."""
    return {
        "as_of_date": as_of_date,
        "index_code": index_code,
        "version": version,
        "ordering": ordering,
        "constituent_id": constituent_id,
        "included": included,
        "exclusion_reason": exclusion_reason,
        "selected_attestation_tier": selected_attestation_tier,
        "raw_volume_mtok": float(raw_volume_mtok),
        "constituent_price_usd_mtok": float(constituent_price_usd_mtok),
        "tier_median_price_usd_mtok": float(tier_median_price_usd_mtok),
        "price_distance_from_median_pct": float(price_distance_from_median_pct),
        "w_vol": float(w_vol),
        "w_exp": float(w_exp),
        "combined_weight": float(combined_weight),
        "weight_share_within_tier": float(weight_share_within_tier),
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
    pre_drop_constituents: set[str] = {
        str(c) for c in tier_panel["constituent_id"].unique()
    }

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
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=const_id,
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.SELECTED_TIER_NO_PRICE_ROWS.value,
                    selected_attestation_tier=selected_tier.value,
                    raw_volume_mtok=float(raw_volume),
                    contributor_count=int(sub["contributor_id"].nunique()),
                )
            )
            continue

        constituent_price = collapse_constituent_price(
            price_rows, price_col=price_field
        )
        w_vol = volume_weight(raw_volume, selected_tier, config)
        rows.append(
            {
                "constituent_id": const_id,
                "selected_tier": selected_tier.value,
                "price": constituent_price,
                "raw_volume": raw_volume,
                "w_vol": w_vol,
                "contributor_count": int(price_rows["contributor_id"].nunique()),
            }
        )

    if not rows:
        # Tier suspends with TIER_DATA_UNAVAILABLE; per-constituent exclusion
        # decisions (if any) already buffered. No active-row decisions to add.
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

    constituents_df = pd.DataFrame(rows)
    n_active = len(constituents_df)

    if n_active < config.min_constituents_per_tier:
        # Tier suspends — emit each "would-be-active" constituent as
        # included=False with TIER_AGGREGATION_SUSPENDED. w_vol is real
        # (computed); w_exp / weight / tier_median are NaN (the median
        # cascade never ran).
        for r in rows:
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=str(r["constituent_id"]),
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.TIER_AGGREGATION_SUSPENDED.value,
                    selected_attestation_tier=str(r["selected_tier"]),
                    raw_volume_mtok=float(r["raw_volume"]),
                    constituent_price_usd_mtok=float(r["price"]),
                    w_vol=float(r["w_vol"]),
                    contributor_count=int(r["contributor_count"]),
                )
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
        # Quality-gate cascade — emit active constituents as included=False
        # with TIER_AGGREGATION_SUSPENDED. All numeric fields populated except
        # weight_share (no denominator).
        for _, srs in constituents_df.iterrows():
            distance_pct = (
                abs(float(srs["price"]) - tier_median) / tier_median
                if tier_median > 0
                else float("nan")
            )
            pending_decisions.append(
                _decision_row(
                    as_of_date=as_of_date_value,
                    index_code=tier.value,
                    version=version,
                    ordering=ordering,
                    constituent_id=str(srs["constituent_id"]),
                    included=False,
                    exclusion_reason=ConstituentExclusionReason.TIER_AGGREGATION_SUSPENDED.value,
                    selected_attestation_tier=str(srs["selected_tier"]),
                    raw_volume_mtok=float(srs["raw_volume"]),
                    constituent_price_usd_mtok=float(srs["price"]),
                    tier_median_price_usd_mtok=tier_median,
                    price_distance_from_median_pct=distance_pct,
                    w_vol=float(srs["w_vol"]),
                    w_exp=float(srs["w_exp"]),
                    combined_weight=float(srs["weight"]),
                    contributor_count=int(srs["contributor_count"]),
                )
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

    # 8. Emit included=True decision rows with full instrumentation.
    for _, srs in constituents_df.iterrows():
        distance_pct = (
            abs(float(srs["price"]) - tier_median) / tier_median
            if tier_median > 0
            else float("nan")
        )
        pending_decisions.append(
            _decision_row(
                as_of_date=as_of_date_value,
                index_code=tier.value,
                version=version,
                ordering=ordering,
                constituent_id=str(srs["constituent_id"]),
                included=True,
                exclusion_reason="",
                selected_attestation_tier=str(srs["selected_tier"]),
                raw_volume_mtok=float(srs["raw_volume"]),
                constituent_price_usd_mtok=float(srs["price"]),
                tier_median_price_usd_mtok=tier_median,
                price_distance_from_median_pct=distance_pct,
                w_vol=float(srs["w_vol"]),
                w_exp=float(srs["w_exp"]),
                combined_weight=float(srs["weight"]),
                weight_share_within_tier=float(srs["weight"]) / total_weight,
                contributor_count=int(srs["contributor_count"]),
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
) -> CoreIndexResults:
    """Run aggregation for TPRR_F, TPRR_S, TPRR_E with rebase to 100 on base_date.

    Each tier runs independently. Per-tier rebase anchor is computed from
    that tier's own indices_df — different tiers may have different
    anchors when ``base_date`` itself is suspended for some tier. Per-
    constituent audit rows are accumulated across all three tiers and
    returned in ``CoreIndexResults.constituent_decisions``.
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
