"""Daily baseline output and input prices per registry model.

Implements the bidirectional drift + bidirectional step-event model documented
in docs/findings/pricing_model_design.md. Per-model deterministic given seed.
No contributor-level noise here — that enters in Phase 2a.2.

Determinism contract: same registry + same date range + same seed produces a
byte-identical DataFrame. Per-model RNGs are seeded by mixing the global seed
with a stable hash of the constituent_id, so adding or removing a model does
not perturb other models' paths.
"""

from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt
import pandas as pd

from tprr.config import ModelRegistry
from tprr.schema import Tier

logger = logging.getLogger(__name__)

# Threshold above which a path's cumulative ratio (current / starting) is
# implausible for a 480-day window and warrants a DEBUG log. The path is not
# capped — Phase 10 wants visibility into pathological seeds, not protection
# from them.
_PATHOLOGICAL_RATIO_THRESHOLD = 3.0


@dataclass(frozen=True)
class TierPricingParams:
    """Stochastic process parameters per tier (docs/findings/pricing_model_design.md)."""

    rate_per_year: float            # Poisson rate of step events
    mu_daily: float                 # Mean daily return
    sigma_daily: float              # Daily return volatility
    down_magnitude_lo: float        # Step-down lower bound (uniform draw)
    down_magnitude_hi: float        # Step-down upper bound
    up_magnitude_lo: float          # Step-up lower bound
    up_magnitude_hi: float          # Step-up upper bound
    down_probability: float = 0.75  # Probability a step event is a step-down


TIER_PARAMS: dict[Tier, TierPricingParams] = {
    Tier.TPRR_F: TierPricingParams(
        rate_per_year=3.0,
        mu_daily=-0.00005,
        sigma_daily=0.0015,
        down_magnitude_lo=0.10,
        down_magnitude_hi=0.25,
        up_magnitude_lo=0.08,
        up_magnitude_hi=0.20,
    ),
    Tier.TPRR_S: TierPricingParams(
        rate_per_year=4.0,
        mu_daily=-0.00010,
        sigma_daily=0.0025,
        down_magnitude_lo=0.12,
        down_magnitude_hi=0.25,
        up_magnitude_lo=0.05,
        up_magnitude_hi=0.15,
    ),
    Tier.TPRR_E: TierPricingParams(
        rate_per_year=5.0,
        mu_daily=-0.00015,
        sigma_daily=0.0040,
        down_magnitude_lo=0.20,
        down_magnitude_hi=0.35,
        up_magnitude_lo=0.05,
        up_magnitude_hi=0.12,
    ),
}


def generate_baseline_prices(
    model_registry: ModelRegistry,
    start_date: date,
    end_date: date,
    seed: int,
) -> pd.DataFrame:
    """Generate daily baseline prices for every registry model.

    Returns a long-format DataFrame with columns
    ``[date, constituent_id, baseline_input_price_usd_mtok, baseline_output_price_usd_mtok]``,
    one row per (constituent, date) over ``[start_date, end_date]`` inclusive.

    Each model evolves independently (no cross-provider correlation in v0.1).
    Both input and output prices receive the same daily return and the same
    step-event multiplier, modelling input/output price coupling at the
    constituent level. Pathological paths emit a DEBUG log on first crossing
    of the ``_PATHOLOGICAL_RATIO_THRESHOLD`` but are not capped.
    """
    if end_date < start_date:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}")
    if not model_registry.models:
        raise ValueError("model_registry has no models")

    n_days = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(n_days)]
    # Force ns precision; pandas 3.x defaults to s precision for date inputs,
    # which downstream validators accept but ns matches PanelObservationDF convention.
    date_index = pd.to_datetime(dates).astype("datetime64[ns]")

    frames: list[pd.DataFrame] = []
    for model in model_registry.models:
        input_path, output_path = _simulate_path(
            constituent_id=model.constituent_id,
            tier=model.tier,
            start_input=model.baseline_input_price_usd_mtok,
            start_output=model.baseline_output_price_usd_mtok,
            n_days=n_days,
            seed=seed,
            dates=dates,
        )
        frames.append(
            pd.DataFrame(
                {
                    "date": date_index,
                    "constituent_id": model.constituent_id,
                    "baseline_input_price_usd_mtok": input_path,
                    "baseline_output_price_usd_mtok": output_path,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _simulate_path(
    *,
    constituent_id: str,
    tier: Tier,
    start_input: float,
    start_output: float,
    n_days: int,
    seed: int,
    dates: list[date],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Simulate one model's full price path. Returns ``(input_path, output_path)``."""
    if start_input <= 0 or start_output <= 0:
        raise ValueError(
            f"{constituent_id}: baseline prices must be > 0 "
            f"(input={start_input}, output={start_output})"
        )

    params = TIER_PARAMS[tier]
    p_event = params.rate_per_year / 365.0
    seed_seq = np.random.SeedSequence([seed, _stable_int(constituent_id)])
    rng = np.random.default_rng(seed_seq)

    output_path = np.empty(n_days, dtype=np.float64)
    input_path = np.empty(n_days, dtype=np.float64)
    output_path[0] = start_output
    input_path[0] = start_input

    pathological_logged = False
    for d in range(1, n_days):
        ret = rng.normal(params.mu_daily, params.sigma_daily)
        output_path[d] = output_path[d - 1] * (1.0 + ret)
        input_path[d] = input_path[d - 1] * (1.0 + ret)

        if rng.random() < p_event:
            if rng.random() < params.down_probability:
                mag = rng.uniform(params.down_magnitude_lo, params.down_magnitude_hi)
                output_path[d] *= 1.0 - mag
                input_path[d] *= 1.0 - mag
            else:
                mag = rng.uniform(params.up_magnitude_lo, params.up_magnitude_hi)
                output_path[d] *= 1.0 + mag
                input_path[d] *= 1.0 + mag

        if not pathological_logged:
            ratio = output_path[d] / output_path[0]
            if ratio > _PATHOLOGICAL_RATIO_THRESHOLD:
                logger.debug(
                    "pathological price path: %s on %s reached %.2fx starting baseline",
                    constituent_id,
                    dates[d].isoformat(),
                    ratio,
                )
                pathological_logged = True

    return input_path, output_path


def _stable_int(s: str) -> int:
    """Cross-process-stable hash of a string for SeedSequence mixing."""
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF
