"""Weighting primitives for TPRR dual-weighted aggregation.

Implements:

- the three-tier volume hierarchy (methodology Section 3.3.2) with the
  priority fall-through resolved in ``docs/decision_log.md`` 2026-04-29
  (Tier A used when ≥3 contributors with attested non-zero volume; else
  Tier B when the provider has revenue config; else Tier C when rankings
  data exists; else excluded);
- the per-tier confidence haircut (1.0 / 0.9 / 0.8) applied to the
  selected tier's volume — no cross-tier blending;
- the exponential median-distance weight (methodology Section 3.3.3).

Phase 5 (Batch A). Batch B (``tprr.index.tier_b``) provides the real
``tier_b_volume_fn`` that converts disclosed provider revenue to per-model
volume; Batch A treats it as an injected dependency so the selection
algorithm is testable independently of the revenue-to-volume derivation.

Phase 7 stitches the per-constituent w_vol returned here with per-tier
exp-weights and the daily TWAP price to produce the index.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd

from tprr.config import (
    IndexConfig,
    ModelRegistry,
    TierBRevenueConfig,
)
from tprr.schema import AttestationTier

TierBVolumeFn = Callable[[str, str, date], float]
"""Signature: ``(provider, constituent_id, as_of_date) -> volume_mtok_7d``.

Phase 5b's ``derive_tier_b_volumes`` will be wrapped to fit this shape.
"""

_TIER_A_MIN_CONTRIBUTORS = 3


def volume_weight(
    volume_or_share: float,
    attestation_tier: AttestationTier,
    config: IndexConfig,
) -> float:
    """Apply the tier confidence haircut (Section 3.3.2) to a volume input.

    The input is interpreted as either a raw volume (legacy use) or a
    within-tier share (post-Phase-7H-Batch-A use). The haircut math is
    identical; the caller decides which input semantics apply. Phase 7H
    Batch A switches all aggregation callers (compute_dual_weights,
    compute_tier_index) to within-tier-share inputs per DL 2026-04-30
    "Phase 7H Batch A — within-tier-share normalization".

    Negative input raises — the caller must surface bad data, not silently
    coerce it. Zero input returns zero.
    """
    if volume_or_share < 0:
        raise ValueError(
            f"volume_weight: volume_or_share must be non-negative, got {volume_or_share}"
        )
    return volume_or_share * config.tier_haircuts[attestation_tier]


def compute_within_tier_share(raw_volumes: dict[str, float]) -> dict[str, float]:
    """Within-tier share normalization: share_i = volume_i / Σ volumes.

    Pure helper. Takes a dict mapping constituent_id to raw volume for
    constituents that resolved to the same selected attestation tier, and
    returns a dict mapping constituent_id to bounded [0, 1] within-tier
    share. Used by ``compute_dual_weights`` and the aggregation drivers
    in ``tprr.index.aggregation`` to enable cross-tier blending without
    cross-tier magnitude domination (DL 2026-04-30 Phase 7H design).

    Empty input → empty dict. All-zero input → all-zero output (defensive
    against division-by-zero; no constituent contributes when the tier
    has no positive volume). Negative volumes raise.
    """
    if not raw_volumes:
        return {}
    for cid, v in raw_volumes.items():
        if v < 0:
            raise ValueError(
                f"compute_within_tier_share: negative volume for {cid!r}: {v}"
            )
    total = sum(raw_volumes.values())
    if total <= 0:
        return {cid: 0.0 for cid in raw_volumes}
    return {cid: v / total for cid, v in raw_volumes.items()}


def redistribute_blending_coefficients(
    available_tiers: set[AttestationTier],
    default_coefficients: dict[AttestationTier, float],
) -> dict[AttestationTier, float]:
    """Redistribute default blending coefficients proportionally to available tiers.

    Phase 7H Batch B continuous blending (DL 2026-04-30). When a constituent
    has data for a subset of tiers (e.g. Tier A and Tier C but not Tier B),
    the default coefficients (e.g. ``{A: 0.6, C: 0.3, B: 0.1}``) are
    renormalised over the available subset:

      coefficient[t] = default[t] / Σ_{t' in available_tiers} default[t']

    so the actual coefficients always sum to 1.0 across the available tiers.

    Examples (default ``{A: 0.6, C: 0.3, B: 0.1}``):

    - All three available → returned unchanged: ``{A: 0.6, C: 0.3, B: 0.1}``
    - A + C only → ``{A: 0.667, C: 0.333}`` (sum 0.9, A=0.6/0.9, C=0.3/0.9)
    - A + B only → ``{A: 0.857, B: 0.143}`` (sum 0.7)
    - C + B only → ``{C: 0.75, B: 0.25}`` (sum 0.4)
    - A only → ``{A: 1.0}``
    - Empty available_tiers → ``{}``

    Returns a dict with one entry per available tier (other tiers omitted).
    """
    if not available_tiers:
        return {}
    subset_total = sum(default_coefficients[t] for t in available_tiers)
    if subset_total <= 0:
        # All coefficients in the available subset are zero — defensive
        # branch. Distribute uniformly so the constituent still contributes.
        n = len(available_tiers)
        return {t: 1.0 / n for t in available_tiers}
    return {
        t: default_coefficients[t] / subset_total for t in available_tiers
    }


def compute_blended_tier_volumes(
    constituent_id: str,
    as_of_date: date,
    panel_df: pd.DataFrame,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
) -> dict[AttestationTier, float] | None:
    """Resolve raw volumes for ALL tiers this constituent has data for.

    Phase 7H Batch B continuous blending (DL 2026-04-30) replaces priority
    fall-through with simultaneous multi-tier contribution. Returns a dict
    mapping attestation tier → raw volume for each tier where the
    constituent has resolvable data. Returns ``None`` when no tier
    resolves (constituent excluded from aggregation).

    Resolution rules per tier:

    1. **Tier A**: ``panel_df`` has ≥3 distinct contributors with
       ``attestation_tier == 'A'`` and ``volume_mtok_7d > 0`` for this
       constituent on this date. Raw volume = sum across those contributors.
    2. **Tier B**: provider has revenue config in ``tier_b_config``. Raw
       volume from ``tier_b_volume_fn(provider, constituent_id, as_of_date)``.
    3. **Tier C**: ``panel_df`` has ≥1 row with ``attestation_tier == 'C'``
       and ``volume_mtok_7d > 0`` for this constituent. Raw volume = sum.

    Each tier's resolution is INDEPENDENT — a constituent with all three
    tiers available returns ``{A: ..., B: ..., C: ...}``. Compare to
    ``compute_tier_volume`` which returns a single (tier, raw_volume)
    via priority fall-through; that legacy function is retained for
    pre-Phase-7H compatibility but the aggregation pipeline now uses
    this blended resolver.
    """
    target = pd.Timestamp(as_of_date)
    constituent_filter = panel_df["constituent_id"] == constituent_id
    date_filter = panel_df["observation_date"] == target
    base = panel_df[constituent_filter & date_filter]

    resolved: dict[AttestationTier, float] = {}

    tier_a_rows = base[
        (base["attestation_tier"] == AttestationTier.A.value) & (base["volume_mtok_7d"] > 0)
    ]
    if tier_a_rows["contributor_id"].nunique() >= _TIER_A_MIN_CONTRIBUTORS:
        resolved[AttestationTier.A] = float(tier_a_rows["volume_mtok_7d"].sum())

    provider = _provider_for_constituent(constituent_id, registry)
    if _provider_has_tier_b(provider, as_of_date, tier_b_config):
        tier_b_volume = float(tier_b_volume_fn(provider, constituent_id, as_of_date))
        if tier_b_volume > 0:
            resolved[AttestationTier.B] = tier_b_volume

    tier_c_rows = base[
        (base["attestation_tier"] == AttestationTier.C.value) & (base["volume_mtok_7d"] > 0)
    ]
    if not tier_c_rows.empty:
        resolved[AttestationTier.C] = float(tier_c_rows["volume_mtok_7d"].sum())

    if not resolved:
        return None
    return resolved


def exponential_weight(
    price: float,
    tier_median: float,
    lambda_: float,
) -> float:
    """Exponential median-distance weight: ``exp(-lambda * |P - P_med| / P_med)``.

    Methodology Section 3.3.3. Negative prices, non-positive medians, and
    negative ``lambda_`` all raise — these would either produce meaningless
    weights or hide an upstream bug.
    """
    if price < 0:
        raise ValueError(f"exponential_weight: price must be non-negative, got {price}")
    if tier_median <= 0:
        raise ValueError(f"exponential_weight: tier_median must be positive, got {tier_median}")
    if lambda_ < 0:
        raise ValueError(f"exponential_weight: lambda must be non-negative, got {lambda_}")
    return float(np.exp(-lambda_ * abs(price - tier_median) / tier_median))


def compute_tier_median(
    prices: list[float] | tuple[float, ...] | np.ndarray | pd.Series,
) -> float:
    """Median over non-NaN prices. Empty / all-NaN raises ValueError."""
    arr = np.asarray(prices, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        raise ValueError("compute_tier_median: no valid prices supplied")
    return float(np.median(arr))


def _provider_for_constituent(constituent_id: str, registry: ModelRegistry) -> str:
    for m in registry.models:
        if m.constituent_id == constituent_id:
            return m.provider
    raise ValueError(
        f"_provider_for_constituent: constituent_id {constituent_id!r} not in registry"
    )


def _provider_has_tier_b(
    provider: str, as_of_date: date, tier_b_config: TierBRevenueConfig
) -> bool:
    try:
        tier_b_config.get_provider_revenue(provider, as_of_date)
    except ValueError:
        return False
    return True


def compute_tier_volume(
    constituent_id: str,
    as_of_date: date,
    panel_df: pd.DataFrame,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
) -> tuple[AttestationTier, float] | None:
    """Select highest-confidence tier per Section 3.3.2 and return (tier, raw_volume).

    Returns ``None`` when all three tiers are insufficient — the constituent
    is excluded from aggregation for that date and contributes neither to
    the tier median nor to the weighted sum.

    Tier selection (priority fall-through, ``decision_log.md`` 2026-04-29):

    1. **Tier A** when ``panel_df`` has ≥3 distinct contributors with
       ``attestation_tier == 'A'`` and ``volume_mtok_7d > 0`` for this
       constituent on this date (strict >0 per ``decision_log.md``
       2026-04-29 "Tier A 'attested volume' interpretation"). Raw volume
       is the sum across those contributors (per-panel-contributor sum,
       the Tier A unit).
    2. **Tier B** otherwise, when the provider has at least one revenue
       entry in ``tier_b_config``. Raw volume comes from
       ``tier_b_volume_fn(provider, constituent_id, as_of_date)``.
    3. **Tier C** otherwise, when ``panel_df`` has any
       ``attestation_tier == 'C'`` row with ``volume_mtok_7d > 0`` for
       this constituent on this date. Raw volume is the sum across those
       rows.
    4. Else **None**.

    ``panel_df`` is the source of truth for who reported on a date — a
    configured contributor missing a submission isn't counted, even if
    they cover the constituent in ``contributors.yaml``.
    """
    target = pd.Timestamp(as_of_date)
    constituent_filter = panel_df["constituent_id"] == constituent_id
    date_filter = panel_df["observation_date"] == target
    base = panel_df[constituent_filter & date_filter]

    tier_a_rows = base[
        (base["attestation_tier"] == AttestationTier.A.value) & (base["volume_mtok_7d"] > 0)
    ]
    n_tier_a = tier_a_rows["contributor_id"].nunique()
    if n_tier_a >= _TIER_A_MIN_CONTRIBUTORS:
        return (
            AttestationTier.A,
            float(tier_a_rows["volume_mtok_7d"].sum()),
        )

    provider = _provider_for_constituent(constituent_id, registry)
    if _provider_has_tier_b(provider, as_of_date, tier_b_config):
        tier_b_volume = tier_b_volume_fn(provider, constituent_id, as_of_date)
        return AttestationTier.B, float(tier_b_volume)

    tier_c_rows = base[
        (base["attestation_tier"] == AttestationTier.C.value) & (base["volume_mtok_7d"] > 0)
    ]
    if not tier_c_rows.empty:
        return (
            AttestationTier.C,
            float(tier_c_rows["volume_mtok_7d"].sum()),
        )

    return None


def compute_exp_weights(
    prices: pd.Series,
    lambda_: float,
) -> pd.Series:
    """Exponential median-distance weight per constituent in a tier-day slice.

    The series index is preserved on the output. The median is computed
    once over the full input — this is one tier on one day. Callers
    aggregating across tiers must call this per tier.

    Raises ``ValueError`` if no valid prices are supplied (empty input,
    all NaN). Phase 7's tier-suspension logic guards against this case
    upstream; callers should handle it before invoking.
    """
    median = compute_tier_median(prices)
    return prices.map(lambda p: exponential_weight(float(p), median, lambda_))


def compute_dual_weights(
    panel_day_df: pd.DataFrame,
    registry: ModelRegistry,
    tier_b_config: TierBRevenueConfig,
    tier_b_volume_fn: TierBVolumeFn,
    config: IndexConfig,
) -> pd.DataFrame:
    """One row per (constituent, contributing tier) with raw_volume, share,
    coefficient, w_vol_contribution.

    Phase 7H Batch B continuous blending (DL 2026-04-30) replaces priority
    fall-through with simultaneous multi-tier contribution. Each constituent
    can produce up to 3 rows (one per tier where it has data); coefficients
    are redistributed proportionally over the constituent's available tiers.

    Pipeline:

    1. Per constituent, call :func:`compute_blended_tier_volumes` to resolve
       a dict mapping each available tier → raw volume. Constituents with
       no resolvable tier are dropped.
    2. Per tier, compute within-tier shares via
       :func:`compute_within_tier_share` over constituents that have that
       tier available.
    3. Per constituent, redistribute the default blending coefficients
       (``config.tier_blending_coefficients``) over the constituent's
       available tiers via :func:`redistribute_blending_coefficients`.
    4. Per (constituent, tier): emit one row with
       ``w_vol_contribution = coefficient x within_tier_share x haircut``.

    Output columns: ``constituent_id``, ``observation_date``,
    ``attestation_tier``, ``raw_volume``, ``within_tier_volume_share``,
    ``coefficient``, ``w_vol_contribution``.

    The combined w_vol per constituent is the sum of w_vol_contribution
    over its rows: ``df.groupby("constituent_id")["w_vol_contribution"].sum()``.
    Long format chosen per DL 2026-04-30 "Phase 7H Batch B audit trail
    design: long-format per-tier breakdown".

    Raises ``ValueError`` if ``panel_day_df`` spans more than one date.
    """
    output_columns = [
        "constituent_id",
        "observation_date",
        "attestation_tier",
        "raw_volume",
        "within_tier_volume_share",
        "coefficient",
        "w_vol_contribution",
    ]
    if panel_day_df.empty:
        return pd.DataFrame(columns=output_columns)

    unique_dates = panel_day_df["observation_date"].unique()
    if len(unique_dates) != 1:
        raise ValueError(
            f"compute_dual_weights: expected single observation_date in panel_day_df, "
            f"got {len(unique_dates)} unique dates"
        )
    as_of_date_value = pd.Timestamp(unique_dates[0]).date()

    # Pass 1: blended tier resolution per constituent.
    resolved: dict[str, dict[AttestationTier, float]] = {}
    for constituent_id in panel_day_df["constituent_id"].unique():
        per_tier_volumes = compute_blended_tier_volumes(
            constituent_id=constituent_id,
            as_of_date=as_of_date_value,
            panel_df=panel_day_df,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
        )
        if per_tier_volumes is None:
            continue
        resolved[str(constituent_id)] = per_tier_volumes

    # Pass 2: within-tier shares per tier (denominator = constituents with
    # that tier available).
    volumes_by_tier: dict[AttestationTier, dict[str, float]] = {
        AttestationTier.A: {},
        AttestationTier.B: {},
        AttestationTier.C: {},
    }
    for cid, per_tier in resolved.items():
        for tier_t, raw_v in per_tier.items():
            volumes_by_tier[tier_t][cid] = raw_v
    shares_by_tier: dict[AttestationTier, dict[str, float]] = {
        tier: compute_within_tier_share(vols)
        for tier, vols in volumes_by_tier.items()
    }

    # Pass 3: per (constituent, tier) emit one row.
    rows: list[dict[str, str | date | float]] = []
    for cid, per_tier in resolved.items():
        coefficients = redistribute_blending_coefficients(
            available_tiers=set(per_tier.keys()),
            default_coefficients=config.tier_blending_coefficients,
        )
        for tier_t, raw_v in per_tier.items():
            share = shares_by_tier[tier_t][cid]
            coef = coefficients[tier_t]
            w_vol_contribution = coef * volume_weight(share, tier_t, config)
            rows.append(
                {
                    "constituent_id": cid,
                    "observation_date": as_of_date_value,
                    "attestation_tier": tier_t.value,
                    "raw_volume": raw_v,
                    "within_tier_volume_share": share,
                    "coefficient": coef,
                    "w_vol_contribution": w_vol_contribution,
                }
            )

    return pd.DataFrame(rows, columns=output_columns)
