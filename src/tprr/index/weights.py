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
    volume_mtok: float,
    attestation_tier: AttestationTier,
    config: IndexConfig,
) -> float:
    """Apply the tier confidence haircut (Section 3.3.2) to a raw volume.

    Negative volumes raise — the caller must surface bad data, not silently
    coerce it. Zero volume returns zero (constituent has no weight on this
    day from this tier).
    """
    if volume_mtok < 0:
        raise ValueError(f"volume_weight: volume_mtok must be non-negative, got {volume_mtok}")
    return volume_mtok * config.tier_haircuts[attestation_tier]


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
    """One row per constituent on a single date with selected tier, raw_volume, w_vol.

    Iterates over distinct ``constituent_id`` values in ``panel_day_df``,
    calls :func:`compute_tier_volume` per constituent, and applies the
    per-tier haircut via :func:`volume_weight`. Constituents for whom
    all three tiers are insufficient are dropped from the output —
    Phase 7's tier-membership and minimum-3 suspension logic consume
    only surviving rows.

    Output columns: ``constituent_id``, ``observation_date``,
    ``attestation_tier`` (the **selected** A/B/C label), ``raw_volume``,
    ``w_vol``. The output's ``attestation_tier`` reflects the tier that
    won the priority fall-through, which may differ from any single
    panel row's ``attestation_tier`` (e.g. a constituent with one Tier
    A panel row and a Tier C panel row falls through to Tier C if Tier
    B is unavailable; ``attestation_tier`` in the output is "C").

    Raises ``ValueError`` if ``panel_day_df`` spans more than one date —
    enforces the per-day shape this function operates on.
    """
    if panel_day_df.empty:
        return pd.DataFrame(
            columns=[
                "constituent_id",
                "observation_date",
                "attestation_tier",
                "raw_volume",
                "w_vol",
            ]
        )

    unique_dates = panel_day_df["observation_date"].unique()
    if len(unique_dates) != 1:
        raise ValueError(
            f"compute_dual_weights: expected single observation_date in panel_day_df, "
            f"got {len(unique_dates)} unique dates"
        )
    as_of_date_value = pd.Timestamp(unique_dates[0]).date()

    rows: list[dict[str, str | date | float]] = []
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
        tier_used, raw_volume = result
        w_vol = volume_weight(raw_volume, tier_used, config)
        rows.append(
            {
                "constituent_id": constituent_id,
                "observation_date": as_of_date_value,
                "attestation_tier": tier_used.value,
                "raw_volume": raw_volume,
                "w_vol": w_vol,
            }
        )

    return pd.DataFrame(rows)
