"""Per-contributor daily price observations from baselines.

Applies each contributor's systematic bias and daily Gaussian noise to the
baseline price series, producing a panel that matches PanelObservationDF.

Determinism contract: per (contributor, model) RNGs are seeded by mixing the
global seed with stable hashes of both contributor_id and constituent_id.
Adding or removing a contributor or model leaves all other (contributor, model)
streams untouched. Same baseline_prices + same panel + same seed produces a
byte-identical output.

Volume column is populated with 0.0 here as a placeholder; Phase 2a.3 fills in
real volumes via tprr.mockdata.volume.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd

from tprr.config import ContributorPanel, ContributorProfile, ModelRegistry
from tprr.mockdata.pricing import _stable_int
from tprr.schema import AttestationTier, Tier

_ERROR_NOISE_AMPLIFICATION = 10.0
_SUBMITTED_AT_HOUR_UTC = 17  # end of TWAP window (matches IndexConfig.twap_window_utc)
_SOURCE_LABEL = "contributor_mock"
_NOTES_DEFAULT = ""
_VOLUME_PLACEHOLDER = 0.0  # Phase 2a.3 populates


def generate_contributor_panel(
    baseline_prices: pd.DataFrame,
    contributor_panel: ContributorPanel,
    model_registry: ModelRegistry,
    seed: int,
) -> pd.DataFrame:
    """Generate per-contributor daily observations matching PanelObservationDF.

    For each (contributor, covered_model, date) emits one row. The submitted
    price model:

      noise ~ Normal(0, sigma_pct/100), or with probability error_rate,
      noise ~ Normal(0, 10 x sigma_pct/100) — a wide-sigma "data error" draw
      that the Phase 6 quality gate should catch.

      submitted_input  = baseline_input  x (1 + bias_pct/100) x (1 + noise)
      submitted_output = baseline_output x (1 + bias_pct/100) x (1 + noise)

    Bias is a systematic MULTIPLICATIVE offset (price_bias_pct=+2.0 means
    1.02x baseline, not baseline + 0.02 USD). Input and output share the same
    noise draw at each (contributor, model, date), modelling billing-system
    coupling at the contributor level.

    All rows: attestation_tier=A, source="contributor_mock". volume_mtok_7d
    placeholder = 0.0 (Phase 2a.3 fills via generate_volumes).

    Note on signature: prompt 2a.2 specifies (baseline_prices, contributor_panel,
    seed). model_registry was added because tier_code is required by
    PanelObservationDF and is not in baseline_prices.
    """
    baseline_indexed = baseline_prices.set_index(
        ["date", "constituent_id"]
    ).sort_index()

    tier_by_constituent = {
        m.constituent_id: m.tier for m in model_registry.models
    }
    valid_constituents = set(tier_by_constituent.keys())
    for profile in contributor_panel.contributors:
        unknown = sorted(set(profile.covered_models) - valid_constituents)
        if unknown:
            raise ValueError(
                f"contributor {profile.contributor_id!r} covers models "
                f"{unknown} not in model_registry"
            )

    all_dates = pd.DatetimeIndex(sorted(baseline_prices["date"].unique()))

    frames: list[pd.DataFrame] = []
    for profile in contributor_panel.contributors:
        for constituent_id in profile.covered_models:
            input_path, output_path = _generate_observation_path(
                profile=profile,
                constituent_id=constituent_id,
                baseline_indexed=baseline_indexed,
                seed=seed,
            )
            frames.append(
                _assemble_rows(
                    profile=profile,
                    constituent_id=constituent_id,
                    tier=tier_by_constituent[constituent_id],
                    dates=all_dates,
                    input_path=input_path,
                    output_path=output_path,
                )
            )
    return pd.concat(frames, ignore_index=True)


def _generate_observation_path(
    *,
    profile: ContributorProfile,
    constituent_id: str,
    baseline_indexed: pd.DataFrame,
    seed: int,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Generate input/output observation arrays for one (contributor, model)."""
    baseline_in = (
        baseline_indexed.xs(constituent_id, level="constituent_id")[
            "baseline_input_price_usd_mtok"
        ]
        .to_numpy()
        .astype(np.float64)
    )
    baseline_out = (
        baseline_indexed.xs(constituent_id, level="constituent_id")[
            "baseline_output_price_usd_mtok"
        ]
        .to_numpy()
        .astype(np.float64)
    )
    n_days = len(baseline_in)

    # Per (contributor, model) RNG — same independence pattern as pricing.py.
    seed_seq = np.random.SeedSequence([
        seed,
        _stable_int(profile.contributor_id),
        _stable_int(constituent_id),
    ])
    rng = np.random.default_rng(seed_seq)

    sigma = profile.daily_noise_sigma_pct / 100.0
    bias_factor = 1.0 + profile.price_bias_pct / 100.0

    is_error = rng.random(n_days) < profile.error_rate
    sigma_per_day = np.where(
        is_error, sigma * _ERROR_NOISE_AMPLIFICATION, sigma
    )
    noise = rng.standard_normal(n_days) * sigma_per_day

    multiplier = bias_factor * (1.0 + noise)
    return baseline_in * multiplier, baseline_out * multiplier


def _assemble_rows(
    *,
    profile: ContributorProfile,
    constituent_id: str,
    tier: Tier,
    dates: pd.DatetimeIndex,
    input_path: npt.NDArray[np.float64],
    output_path: npt.NDArray[np.float64],
) -> pd.DataFrame:
    """Pack one (contributor, model) series into PanelObservationDF rows."""
    submitted_at = (
        dates.normalize() + pd.Timedelta(hours=_SUBMITTED_AT_HOUR_UTC)
    ).astype("datetime64[ns]")
    return pd.DataFrame(
        {
            "observation_date": dates,
            "constituent_id": constituent_id,
            "contributor_id": profile.contributor_id,
            "tier_code": tier.value,
            "attestation_tier": AttestationTier.A.value,
            "input_price_usd_mtok": input_path,
            "output_price_usd_mtok": output_path,
            "volume_mtok_7d": _VOLUME_PLACEHOLDER,
            "source": _SOURCE_LABEL,
            "submitted_at": submitted_at,
            "notes": _NOTES_DEFAULT,
        }
    )
