"""Volume population for the mock contributor panel.

Adds ``volume_mtok_7d`` to a PanelObservation-shaped DataFrame. Per-contributor
volume is composed of three independent stochastic layers:

1. **Shared random-walk multiplier** (per contributor) — slow daily drift that
   moves all of a contributor's models together. Carries the contributor's
   long-term grow / flat / contract trend.
2. **Static per-pair offset** — drawn once per ``(contributor, model)`` from
   ``exp(N(0, sigma_offset))``. Gives different baseline weights to different
   models within the same contributor.
3. **Per-pair idiosyncratic random walk** — independent daily drift per
   ``(contributor, model)``. Causes model mix to shift over time even within
   a single contributor.

The shared component delivers visible cross-model correlation ("atlas had a
busy day across the board"). The idiosyncratic layer prevents perfect
correlation, so model ratios drift — required for thesis-aligned testing of
Tier B derivation and Phase 10 scenarios that depend on fluid model mix.

Determinism contract: per-contributor RNG seeded by ``(seed, stable_int(contributor_id))``;
per-pair RNG by ``(seed, stable_int(contributor_id), stable_int(constituent_id))``.
Adding or removing contributors / models leaves all other paths byte-identical.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd

from tprr.config import ContributorPanel, VolumeScale
from tprr.mockdata.pricing import _stable_int

_VOLUME_SCALE_BASELINE_MTOK_PER_DAY: dict[VolumeScale, float] = {
    VolumeScale.LOW: 0.1,
    VolumeScale.MEDIUM: 1.0,
    VolumeScale.HIGH: 10.0,
    VolumeScale.VERY_HIGH: 100.0,
}

# Long-term trend in log-volume on the shared multiplier, assigned by
# stable_int(contributor_id) mod 3. 0 = grow (~+62% over 480 days), 1 = flat,
# 2 = contract (~-21% over 480 days).
_TREND_DAILY_BY_ID: dict[int, float] = {
    0: 0.0010,
    1: 0.0,
    2: -0.0005,
}

# Daily noise on the contributor's shared random walk (~1% / day in log space).
_SHARED_NOISE_SIGMA = 0.01

# Static per-(contributor, model) log-offset standard deviation (~30%).
# Gives different baseline volumes per model within a contributor; 1-sigma
# range exp(+/-0.3) = [0.74, 1.35].
_MODEL_OFFSET_SIGMA = 0.3

# Per-(contributor, model) idiosyncratic random-walk daily noise (~1.2%).
# Empirically tuned (not by closed-form) so the median pair-correlation across
# a contributor's 16 covered models on seed 42 lands at ~0.72 — squarely in
# the [0.5, 0.85] target band. Single-seed pair-level correlations vary widely
# (sometimes negative) because random-walk path divergence is path-dependent;
# only the median across many pairs is stable. Lowering this value makes
# correlations cluster higher (closer to perfect-correlation regression);
# raising it kills the cross-model coupling.
_MODEL_IDIO_WALK_SIGMA = 0.012

# Floor on daily volume — avoids zeros that would cause downstream
# division-by-zero in weight calculations.
_MIN_DAILY_VOLUME_MTOK = 0.001

_TRAILING_WINDOW_DAYS = 7


def generate_volumes(
    panel_df: pd.DataFrame,
    contributor_panel: ContributorPanel,
    seed: int,
) -> pd.DataFrame:
    """Populate ``volume_mtok_7d`` on a PanelObservation-shaped DataFrame.

    Returns a copy of ``panel_df`` (column order preserved) with
    ``volume_mtok_7d`` repopulated. Pre-existing values are overwritten.

    Volume composition per ``(contributor, model, day)``:
      ``daily = base_scale * shared_mult[t] * model_offset * idio_walk[t]``
      ``volume_mtok_7d[t] = sum(daily[t-6 .. t])`` (expanding for first 6 days)

    Where ``shared_mult`` is the contributor's daily random walk (with
    grow/flat/contract trend), ``model_offset`` is a per-pair static draw,
    and ``idio_walk`` is a per-pair daily random walk. ``daily`` is clipped
    at 0.001 Mtok/day before the rolling sum.
    """
    required = {"observation_date", "contributor_id", "constituent_id"}
    missing = required - set(panel_df.columns)
    if missing:
        raise ValueError(f"panel_df missing required columns: {sorted(missing)}")

    contrib_by_id = {p.contributor_id: p for p in contributor_panel.contributors}
    panel_contributor_ids = set(panel_df["contributor_id"].unique())
    missing_profiles = panel_contributor_ids - set(contrib_by_id.keys())
    if missing_profiles:
        raise ValueError(
            f"panel_df references contributors not in contributor_panel: {sorted(missing_profiles)}"
        )

    all_dates = pd.DatetimeIndex(sorted(panel_df["observation_date"].unique()))
    n_days = len(all_dates)

    shared_mult_by_id: dict[str, npt.NDArray[np.float64]] = {}
    base_scale_by_id: dict[str, float] = {}
    for cid, profile in contrib_by_id.items():
        shared_mult_by_id[cid] = _build_shared_multiplier_path(cid, n_days, seed)
        base_scale_by_id[cid] = _VOLUME_SCALE_BASELINE_MTOK_PER_DAY[profile.volume_scale]

    pairs = panel_df[["contributor_id", "constituent_id"]].drop_duplicates()
    mult_frames: list[pd.DataFrame] = []
    for cid_value, mid_value in pairs.itertuples(index=False, name=None):
        cid = str(cid_value)
        mid = str(mid_value)
        offset, idio_path = _build_pair_components(cid, mid, n_days, seed)
        daily = np.maximum(
            base_scale_by_id[cid] * shared_mult_by_id[cid] * offset * idio_path,
            _MIN_DAILY_VOLUME_MTOK,
        )
        mult_frames.append(
            pd.DataFrame(
                {
                    "observation_date": all_dates,
                    "contributor_id": cid,
                    "constituent_id": mid,
                    "_daily_volume_mtok": daily,
                }
            )
        )
    mult_df = pd.concat(mult_frames, ignore_index=True)

    original_columns = panel_df.columns.tolist()
    out = panel_df.merge(
        mult_df,
        on=["observation_date", "contributor_id", "constituent_id"],
        how="left",
    )
    if out["_daily_volume_mtok"].isna().any():
        raise RuntimeError("volume merge left null daily volumes; check date alignment")

    out = out.sort_values(["contributor_id", "constituent_id", "observation_date"]).reset_index(
        drop=True
    )

    if "volume_mtok_7d" in out.columns:
        out = out.drop(columns=["volume_mtok_7d"])

    out["volume_mtok_7d"] = out.groupby(["contributor_id", "constituent_id"])[
        "_daily_volume_mtok"
    ].transform(lambda x: x.rolling(_TRAILING_WINDOW_DAYS, min_periods=1).sum())

    out = out.drop(columns=["_daily_volume_mtok"])
    return out[original_columns]


def _build_shared_multiplier_path(
    contributor_id: str, n_days: int, seed: int
) -> npt.NDArray[np.float64]:
    """Per-contributor random walk on log-volume; multiplier[0] = 1.0 always."""
    seed_seq = np.random.SeedSequence([seed, _stable_int(contributor_id)])
    rng = np.random.default_rng(seed_seq)
    trend = _TREND_DAILY_BY_ID[_stable_int(contributor_id) % 3]

    log_mult = np.zeros(n_days, dtype=np.float64)
    if n_days > 1:
        increments = trend + rng.normal(0.0, _SHARED_NOISE_SIGMA, n_days - 1)
        log_mult[1:] = np.cumsum(increments)
    return np.exp(log_mult)


def _build_pair_components(
    contributor_id: str, constituent_id: str, n_days: int, seed: int
) -> tuple[float, npt.NDArray[np.float64]]:
    """Per-(contributor, model) static offset and idiosyncratic walk path."""
    seed_seq = np.random.SeedSequence(
        [seed, _stable_int(contributor_id), _stable_int(constituent_id)]
    )
    rng = np.random.default_rng(seed_seq)

    log_offset = float(rng.normal(0.0, _MODEL_OFFSET_SIGMA))
    offset = float(np.exp(log_offset))

    log_idio = np.zeros(n_days, dtype=np.float64)
    if n_days > 1:
        log_idio[1:] = np.cumsum(rng.normal(0.0, _MODEL_IDIO_WALK_SIGMA, n_days - 1))
    idio_path = np.exp(log_idio)
    return offset, idio_path


def daily_volume_series(
    contributor_id: str,
    constituent_id: str,
    base_scale: float,
    n_days: int,
    seed: int,
) -> npt.NDArray[np.float64]:
    """Compose the per-day volume series for one (contributor, model) pair.

    Public helper for diagnostics and tests. Composes the same three layers as
    ``generate_volumes`` (shared multiplier, static offset, idiosyncratic walk)
    and applies the MIN clip — but skips the 7-day rolling sum and DataFrame
    plumbing.
    """
    shared_mult = _build_shared_multiplier_path(contributor_id, n_days, seed)
    offset, idio_path = _build_pair_components(contributor_id, constituent_id, n_days, seed)
    return np.maximum(base_scale * shared_mult * offset * idio_path, _MIN_DAILY_VOLUME_MTOK)
