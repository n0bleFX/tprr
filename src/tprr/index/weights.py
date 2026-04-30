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
    """One row per constituent on a single date with selected tier, raw_volume,
    within_tier_volume_share, w_vol.

    Two-pass:

    1. Per constituent, call :func:`compute_tier_volume` to resolve
       (selected_tier, raw_volume) per the priority fall-through rules.
       Constituents for whom all three tiers are insufficient are dropped.
    2. Per selected tier, compute within-tier shares via
       :func:`compute_within_tier_share`, then apply the per-tier haircut
       via :func:`volume_weight` to produce w_vol.

    Phase 7H Batch A (DL 2026-04-30) replaces ``w_vol = raw_volume x haircut``
    with ``w_vol = within_tier_share x haircut``. Priority fall-through
    selection is unchanged; only the volume representation changes. Within-
    tier shares are bounded in [0, 1] regardless of underlying volume scale,
    enabling Batch B's continuous blending without one tier's magnitude
    dominating regardless of coefficient choice.

    Output columns: ``constituent_id``, ``observation_date``,
    ``attestation_tier`` (the **selected** A/B/C label), ``raw_volume``,
    ``within_tier_volume_share``, ``w_vol``.

    Raises ``ValueError`` if ``panel_day_df`` spans more than one date.
    """
    output_columns = [
        "constituent_id",
        "observation_date",
        "attestation_tier",
        "raw_volume",
        "within_tier_volume_share",
        "w_vol",
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

    # Pass 1: tier resolution per constituent.
    resolved: dict[str, tuple[AttestationTier, float]] = {}
    for constituent_id in panel_day_df["constituent_id"].unique():
        result = compute_tier_volume(
            constituent_id=constituent_id,
            as_of_date=as_of_date_value,
            panel_df=panel_day_df,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
        )
        if result is None:
            continue
        resolved[str(constituent_id)] = result

    # Pass 2: group by selected tier, compute within-tier shares.
    volumes_by_tier: dict[AttestationTier, dict[str, float]] = {
        AttestationTier.A: {},
        AttestationTier.B: {},
        AttestationTier.C: {},
    }
    for cid, (tier_used, raw_volume) in resolved.items():
        volumes_by_tier[tier_used][cid] = raw_volume

    shares_by_tier: dict[AttestationTier, dict[str, float]] = {
        tier: compute_within_tier_share(vols)
        for tier, vols in volumes_by_tier.items()
    }

    # Pass 3: apply haircut to within-tier-share to produce w_vol.
    rows: list[dict[str, str | date | float]] = []
    for cid, (tier_used, raw_volume) in resolved.items():
        share = shares_by_tier[tier_used][cid]
        w_vol = volume_weight(share, tier_used, config)
        rows.append(
            {
                "constituent_id": cid,
                "observation_date": as_of_date_value,
                "attestation_tier": tier_used.value,
                "raw_volume": raw_volume,
                "within_tier_volume_share": share,
                "w_vol": w_vol,
            }
        )

    return pd.DataFrame(rows, columns=output_columns)
