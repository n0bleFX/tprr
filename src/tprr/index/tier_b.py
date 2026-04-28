"""Tier B revenue-derived volume proxy — Phase 5b implementation.

Per ``docs/decision_log.md``:

- 2026-04-22: Tier B implementation = Option B, revenue-anchored, OpenRouter
  within-provider split.
- 2026-04-29: with the v0.1 OR rankings mirror's top-9 limit, 5 of 6 Tier B
  providers have zero model-level rankings coverage. The default fallback
  is a price-implied within-provider split (Option δ). Phase 10 runs the
  equal-volume alternative (Option β) as sensitivity comparison via the
  ``prior`` parameter.

For each provider with a Tier B revenue entry on a given ``as_of_date``,
:func:`derive_tier_b_volumes` derives per-model 7-day volume by:

  1. Reading interpolated quarterly revenue R(t) from the revenue config.
  2. Partitioning the provider's registered models into covered (with
     model-level OR rankings) and uncovered groups; allocating revenue
     between the two by equal-revenue-share across registered models.
  3. Within the covered group: canonical Option B (revenue / share-weighted
     reference price → total volume; allocate by share).
  4. Within the uncovered group: applying the selected ``prior``:
       - ``"price_implied"`` (default, δ): vol_i = (R_uncovered / n) / p_i
       - ``"equal_volume"`` (β): vol_i = (R_uncovered / mean_price) / n
  5. Scale normalisation: enforce revenue identity Σ(vol * p) == R as a
     floating-point safety check (the algorithm above makes the factor
     ≈ 1.0 by construction).
  6. Quarterly → 7-day conversion: vol_7d = vol_quarterly * 7 / 91.25.
  7. Emitting one PanelObservationDF-shaped row per (provider, model,
     as_of_date) with ``attestation_tier='B'`` and
     ``source='tier_b_derived'``.

Output rows are panel-shape and ready for inclusion in the union panel
that Phase 7 aggregation consumes.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from tprr.config import ModelMetadata, ModelRegistry, TierBRevenueConfig
from tprr.schema import AttestationTier

logger = logging.getLogger(__name__)

# Calendar-stable days per quarter: 365.25 / 4. Used to convert quarterly
# revenue-derived volume into the 7-day basis the panel schema carries.
DAYS_PER_QUARTER = 91.25

TIER_B_SOURCE = "tier_b_derived"

Prior = Literal["price_implied", "equal_volume"]

_TIER_B_OUTPUT_COLUMNS = [
    "observation_date",
    "constituent_id",
    "contributor_id",
    "tier_code",
    "attestation_tier",
    "input_price_usd_mtok",
    "output_price_usd_mtok",
    "volume_mtok_7d",
    "source",
    "submitted_at",
    "notes",
]


def derive_tier_b_volumes(
    as_of_date: date,
    panel_df: pd.DataFrame,
    openrouter_rankings_df: pd.DataFrame,
    tier_b_revenue_config: TierBRevenueConfig,
    model_registry: ModelRegistry,
    *,
    prior: Prior = "price_implied",
) -> pd.DataFrame:
    """Emit Tier B panel rows for every provider with revenue on ``as_of_date``.

    Parameters
    ----------
    as_of_date
        Computation date. Quarterly revenue interpolation anchors at end-of-quarter
        per ``decision_log.md`` 2026-04-23.
    panel_df
        Existing panel rows used for per-constituent output prices. The function
        reads OUTPUT prices for the algorithm's reference-price computation, and
        copies the panel-derived per-constituent (output, input) price pair into
        the emitted rows. Median across all panel rows for the constituent on
        ``as_of_date`` is used; registry baseline is the fallback when the
        constituent has no panel row that day.
    openrouter_rankings_df
        Rankings volume per constituent. Must have columns
        ``["constituent_id", "volume_mtok_7d"]``. A constituent absent from this
        frame is treated as having zero rankings coverage. Pass an empty frame
        with these columns if no rankings data is available.
    tier_b_revenue_config
        Per-provider quarterly revenue entries.
    model_registry
        Source of provider→models mapping and registry baseline prices.
    prior
        Allocation prior for models lacking OR rankings:
          ``"price_implied"`` (default) — equal revenue share within provider,
          giving cheaper models more volume. Phase 10 default.
          ``"equal_volume"`` — equal volume across uncovered models.
          Phase 10 sensitivity comparison.

    Returns
    -------
    pd.DataFrame
        Panel-shape rows, one per (provider model, as_of_date) for providers
        with revenue config and at least one registered model. Columns match
        ``PanelObservationDF``. Empty frame (with correct columns) if no
        provider-with-revenue has registered models.
    """
    if prior not in ("price_implied", "equal_volume"):
        raise ValueError(
            f"derive_tier_b_volumes: prior must be 'price_implied' or 'equal_volume', got {prior!r}"
        )

    rankings_lookup = _build_rankings_lookup(openrouter_rankings_df)
    models_by_provider = _group_models_by_provider(model_registry)
    providers_with_revenue = sorted({entry.provider for entry in tier_b_revenue_config.entries})

    rows: list[dict[str, object]] = []
    for provider in providers_with_revenue:
        models = models_by_provider.get(provider, [])
        if not models:
            logger.info(
                "Tier B: provider %r has revenue but no registered models — skipped",
                provider,
            )
            continue

        revenue = tier_b_revenue_config.get_provider_revenue(provider, as_of_date)
        rows.extend(
            _derive_provider_rows(
                provider=provider,
                revenue=revenue,
                models=models,
                rankings_lookup=rankings_lookup,
                panel_df=panel_df,
                as_of_date=as_of_date,
                prior=prior,
            )
        )

    return _build_output_df(rows)


# ---------------------------------------------------------------------------
# Per-provider derivation
# ---------------------------------------------------------------------------


def _derive_provider_rows(
    *,
    provider: str,
    revenue: float,
    models: list[ModelMetadata],
    rankings_lookup: dict[str, float],
    panel_df: pd.DataFrame,
    as_of_date: date,
    prior: Prior,
) -> list[dict[str, object]]:
    """Compute Tier B rows for one provider on one date.

    Implements the partition/allocate algorithm in ``decision_log.md``
    2026-04-29. ``revenue`` is the interpolated quarterly amount (USD).
    """
    output_prices = {
        m.constituent_id: _lookup_constituent_price(
            constituent_id=m.constituent_id,
            price_field="output_price_usd_mtok",
            panel_df=panel_df,
            as_of_date=as_of_date,
            registry_fallback=m.baseline_output_price_usd_mtok,
        )
        for m in models
    }
    input_prices = {
        m.constituent_id: _lookup_constituent_price(
            constituent_id=m.constituent_id,
            price_field="input_price_usd_mtok",
            panel_df=panel_df,
            as_of_date=as_of_date,
            registry_fallback=m.baseline_input_price_usd_mtok,
        )
        for m in models
    }

    covered = [m for m in models if m.constituent_id in rankings_lookup]
    uncovered = [m for m in models if m.constituent_id not in rankings_lookup]
    n_total = len(models)
    n_covered = len(covered)
    n_uncovered = len(uncovered)

    if n_uncovered:
        logger.info(
            "Tier B: provider %r has %d/%d models without OR rankings "
            "coverage — applying %r prior to uncovered group",
            provider,
            n_uncovered,
            n_total,
            prior,
        )

    # Equal-revenue partition between covered and uncovered (decision log
    # 2026-04-29 step 4). Both groups receive a slice of R proportional
    # to model count.
    revenue_covered = revenue * n_covered / n_total
    revenue_uncovered = revenue * n_uncovered / n_total

    quarterly_volume_mtok: dict[str, float] = {}

    if covered:
        quarterly_volume_mtok.update(
            _allocate_covered(
                covered_models=covered,
                output_prices=output_prices,
                rankings_lookup=rankings_lookup,
                revenue_covered=revenue_covered,
            )
        )

    if uncovered:
        quarterly_volume_mtok.update(
            _allocate_uncovered(
                uncovered_models=uncovered,
                output_prices=output_prices,
                revenue_uncovered=revenue_uncovered,
                prior=prior,
            )
        )

    # Step 7: scale normalisation. By construction the factor is ≈ 1.0;
    # this catches floating-point drift and any future algorithm tweak
    # that breaks the identity.
    accounting_revenue = sum(
        quarterly_volume_mtok[m.constituent_id] * output_prices[m.constituent_id] for m in models
    )
    if accounting_revenue > 0:
        scale_factor = revenue / accounting_revenue
        for cid in quarterly_volume_mtok:
            quarterly_volume_mtok[cid] *= scale_factor

    # Step 8: quarterly → 7-day; emit panel rows.
    submitted_at = pd.Timestamp(as_of_date)
    coverage_note = (
        f"prior={prior};coverage={n_covered}/{n_total}"
        if n_uncovered
        else f"prior={prior};coverage=full"
    )
    rows: list[dict[str, object]] = []
    for m in models:
        seven_day_volume = quarterly_volume_mtok[m.constituent_id] * 7.0 / DAYS_PER_QUARTER
        rows.append(
            {
                "observation_date": pd.Timestamp(as_of_date),
                "constituent_id": m.constituent_id,
                "contributor_id": f"tier_b:{provider}",
                "tier_code": m.tier.value,
                "attestation_tier": AttestationTier.B.value,
                "input_price_usd_mtok": input_prices[m.constituent_id],
                "output_price_usd_mtok": output_prices[m.constituent_id],
                "volume_mtok_7d": seven_day_volume,
                "source": TIER_B_SOURCE,
                "submitted_at": submitted_at,
                "notes": coverage_note,
            }
        )
    return rows


def _allocate_covered(
    *,
    covered_models: list[ModelMetadata],
    output_prices: dict[str, float],
    rankings_lookup: dict[str, float],
    revenue_covered: float,
) -> dict[str, float]:
    """Canonical Option B within the covered group.

    ref_price = Σ(p * s) / Σ(s); total_vol = R_covered / ref_price;
    vol_i = total_vol * s_i / Σ(s).
    """
    shares = np.array([rankings_lookup[m.constituent_id] for m in covered_models], dtype=float)
    prices = np.array([output_prices[m.constituent_id] for m in covered_models], dtype=float)
    shares_sum = float(shares.sum())
    if shares_sum <= 0:
        # Defensive: can happen only if the rankings lookup contains zero
        # entries for every covered model. Treat as uncovered in caller.
        raise RuntimeError(
            "Tier B: covered group has zero total rankings volume — "
            "rankings_lookup should not contain zero entries"
        )
    ref_price = float((prices * shares).sum() / shares_sum)
    total_covered_vol = revenue_covered / ref_price
    return {
        m.constituent_id: total_covered_vol * float(s) / shares_sum
        for m, s in zip(covered_models, shares, strict=True)
    }


def _allocate_uncovered(
    *,
    uncovered_models: list[ModelMetadata],
    output_prices: dict[str, float],
    revenue_uncovered: float,
    prior: Prior,
) -> dict[str, float]:
    """Apply the chosen prior to the uncovered group.

    ``"price_implied"``: each model gets equal revenue share R/n;
    volume = (R/n) / p. Cheaper models get more volume.

    ``"equal_volume"``: each model gets equal volume; total provider
    volume = R / mean(p), divided equally across n models.
    """
    n_uncovered = len(uncovered_models)
    if prior == "price_implied":
        per_model_revenue = revenue_uncovered / n_uncovered
        return {
            m.constituent_id: per_model_revenue / output_prices[m.constituent_id]
            for m in uncovered_models
        }
    # equal_volume
    prices = np.array([output_prices[m.constituent_id] for m in uncovered_models], dtype=float)
    mean_price = float(prices.mean())
    total_uncovered_vol = revenue_uncovered / mean_price
    per_model_vol = total_uncovered_vol / n_uncovered
    return {m.constituent_id: per_model_vol for m in uncovered_models}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_rankings_lookup(rankings_df: pd.DataFrame) -> dict[str, float]:
    """Build ``{constituent_id: volume_mtok_7d}`` from a rankings DataFrame.

    Only entries with ``volume_mtok_7d > 0`` are retained — a zero entry
    represents "no rankings data" per ``decision_log.md`` 2026-04-28
    Tier C sparseness, which the algorithm treats as uncovered for
    allocation purposes.
    """
    if rankings_df.empty or "constituent_id" not in rankings_df.columns:
        return {}
    out: dict[str, float] = {}
    for cid, vol in zip(
        rankings_df["constituent_id"],
        rankings_df["volume_mtok_7d"],
        strict=True,
    ):
        cid_str = str(cid)
        vol_f = float(vol)
        if vol_f > 0:
            out[cid_str] = vol_f
    return out


def _group_models_by_provider(
    registry: ModelRegistry,
) -> dict[str, list[ModelMetadata]]:
    out: dict[str, list[ModelMetadata]] = {}
    for m in registry.models:
        out.setdefault(m.provider, []).append(m)
    return out


def _lookup_constituent_price(
    *,
    constituent_id: str,
    price_field: str,
    panel_df: pd.DataFrame,
    as_of_date: date,
    registry_fallback: float,
) -> float:
    """Median of ``price_field`` across panel rows for ``constituent_id`` on ``as_of_date``.

    Falls back to ``registry_fallback`` when no panel row exists or the
    median resolves to a non-positive value.
    """
    if panel_df.empty or "observation_date" not in panel_df.columns:
        return registry_fallback
    target = pd.Timestamp(as_of_date)
    mask = (panel_df["constituent_id"] == constituent_id) & (panel_df["observation_date"] == target)
    matched = panel_df.loc[mask, price_field]
    if matched.empty:
        return registry_fallback
    median_price = float(matched.median())
    if not np.isfinite(median_price) or median_price <= 0:
        return registry_fallback
    return median_price


def _build_output_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Assemble Tier B rows as a PanelObservationDF-compatible frame.

    Returns an empty frame with the correct columns and dtypes when no
    rows are produced — keeps the schema validator happy upstream.
    """
    if not rows:
        return pd.DataFrame(
            {
                "observation_date": pd.Series([], dtype="datetime64[ns]"),
                "constituent_id": pd.Series([], dtype="object"),
                "contributor_id": pd.Series([], dtype="object"),
                "tier_code": pd.Series([], dtype="object"),
                "attestation_tier": pd.Series([], dtype="object"),
                "input_price_usd_mtok": pd.Series([], dtype="float64"),
                "output_price_usd_mtok": pd.Series([], dtype="float64"),
                "volume_mtok_7d": pd.Series([], dtype="float64"),
                "source": pd.Series([], dtype="object"),
                "submitted_at": pd.Series([], dtype="datetime64[ns]"),
                "notes": pd.Series([], dtype="object"),
            }
        )
    df = pd.DataFrame(rows)
    df["observation_date"] = pd.to_datetime(df["observation_date"]).astype("datetime64[ns]")
    df["submitted_at"] = pd.to_datetime(df["submitted_at"]).astype("datetime64[ns]")
    return df[_TIER_B_OUTPUT_COLUMNS].reset_index(drop=True)
