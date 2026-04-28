"""Phase 8 — derived TPRR indices (FPR, SER) computed from core (F, S, E).

Two cross-tier ratios per CLAUDE.md / methodology Section 3.3.4:

  TPRR_FPR(t) = TPRR_F(t) / TPRR_S(t)   # Frontier Premium Ratio
  TPRR_SER(t) = TPRR_S(t) / TPRR_E(t)   # Standard Efficiency Ratio

Rebase convention (Q4 lock 2026-04-29 + decision log 2026-04-30 schema):

  index_level = 100 x ratio_today / ratio_anchor_date

Same uniform convention as the price indices — anchor = first non-suspended
ratio at-or-after ``config.base_date``.

Suspension propagation: the derived ratio inherits suspension from the
upstream tier indices. ``FPR`` is suspended on day t if either F or S is
suspended on day t. ``SER`` is suspended on day t if either S or E is
suspended. The ``suspension_reason`` propagated is the numerator's reason
when both are suspended, the suspended one's reason otherwise.

Phase 8 (Batch B' next batch): adds ``compute_tprr_b`` for the blended
``0.25 x P_in + 0.75 x P_out`` series; lives next to FPR/SER here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from tprr.config import IndexConfig
from tprr.index.aggregation import rebase_index_level

INDEX_CODE_FPR = "TPRR_FPR"
INDEX_CODE_SER = "TPRR_SER"


def compute_fpr(
    f_df: pd.DataFrame,
    s_df: pd.DataFrame,
    config: IndexConfig,
    *,
    version: str = "v0_1",
    ordering: str = "twap_then_weight",
) -> tuple[pd.DataFrame, date | None]:
    """Compute TPRR_FPR (F / S) as a per-date IndexValueDF, rebased to 100 on base_date.

    Returns ``(fpr_df, anchor_date)``. Anchor handling delegates to
    ``rebase_index_level``.
    """
    return _compute_ratio_index(
        numerator_df=f_df,
        denominator_df=s_df,
        index_code=INDEX_CODE_FPR,
        config=config,
        version=version,
        ordering=ordering,
    )


def compute_ser(
    s_df: pd.DataFrame,
    e_df: pd.DataFrame,
    config: IndexConfig,
    *,
    version: str = "v0_1",
    ordering: str = "twap_then_weight",
) -> tuple[pd.DataFrame, date | None]:
    """Compute TPRR_SER (S / E) as a per-date IndexValueDF, rebased to 100 on base_date."""
    return _compute_ratio_index(
        numerator_df=s_df,
        denominator_df=e_df,
        index_code=INDEX_CODE_SER,
        config=config,
        version=version,
        ordering=ordering,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _compute_ratio_index(
    *,
    numerator_df: pd.DataFrame,
    denominator_df: pd.DataFrame,
    index_code: str,
    config: IndexConfig,
    version: str,
    ordering: str,
) -> tuple[pd.DataFrame, date | None]:
    """Compute a derived ratio IndexValueDF (numerator / denominator) per date.

    Uses an inner join on ``as_of_date``; dates present in only one input
    don't appear in the output. For the v0.1 backtest the two dataframes
    are produced by the same multi-tier driver run on the same date range,
    so this is a non-issue.
    """
    if numerator_df.empty or denominator_df.empty:
        return pd.DataFrame(), None

    merged = numerator_df.merge(
        denominator_df,
        on="as_of_date",
        suffixes=("_num", "_den"),
        how="inner",
    ).sort_values("as_of_date").reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    prior_ratio: float | None = None
    for raw in merged.to_dict("records"):
        rec: dict[str, Any] = {str(k): v for k, v in raw.items()}
        suspended_num = bool(rec["suspended_num"])
        suspended_den = bool(rec["suspended_den"])
        any_suspended = suspended_num or suspended_den
        denom = float(rec["raw_value_usd_mtok_den"])
        num = float(rec["raw_value_usd_mtok_num"])

        if any_suspended or not (np.isfinite(num) and np.isfinite(denom) and denom > 0):
            ratio = (
                float(prior_ratio) if prior_ratio is not None else float("nan")
            )
            reason = (
                str(rec["suspension_reason_num"])
                if suspended_num
                else str(rec["suspension_reason_den"])
            )
            rows.append(
                _ratio_row(
                    rec=rec,
                    index_code=index_code,
                    config=config,
                    version=version,
                    ordering=ordering,
                    raw_value=ratio,
                    suspended=True,
                    suspension_reason=reason,
                )
            )
        else:
            ratio = num / denom
            prior_ratio = ratio
            rows.append(
                _ratio_row(
                    rec=rec,
                    index_code=index_code,
                    config=config,
                    version=version,
                    ordering=ordering,
                    raw_value=ratio,
                    suspended=False,
                    suspension_reason="",
                )
            )

    out = pd.DataFrame(rows)
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).astype("datetime64[ns]")
    rebased, anchor = rebase_index_level(out, base_date=config.base_date)
    return rebased, anchor


def _ratio_row(
    *,
    rec: dict[str, Any],
    index_code: str,
    config: IndexConfig,
    version: str,
    ordering: str,
    raw_value: float,
    suspended: bool,
    suspension_reason: str,
) -> dict[str, Any]:
    """Construct one IndexValueDF-shape row for a derived ratio index.

    ``n_constituents*`` and ``tier_*_weight_share`` fields are populated
    from the numerator (the ratio inherits Frontier's tier mix for FPR,
    Standard's for SER). Phase 9/10 consumers reading derived rows for
    tier-share information should treat these as the numerator's mix,
    not the ratio's — there's no well-defined "tier mix of a ratio."
    """
    return {
        "as_of_date": rec["as_of_date"],
        "index_code": index_code,
        "version": version,
        "lambda": config.lambda_,
        "ordering": ordering,
        "raw_value_usd_mtok": raw_value,
        "index_level": float("nan"),  # rebase_index_level fills
        "n_constituents": int(rec["n_constituents_num"]),
        "n_constituents_active": int(rec["n_constituents_active_num"]),
        "n_constituents_a": int(rec["n_constituents_a_num"]),
        "n_constituents_b": int(rec["n_constituents_b_num"]),
        "n_constituents_c": int(rec["n_constituents_c_num"]),
        "tier_a_weight_share": float(rec["tier_a_weight_share_num"]),
        "tier_b_weight_share": float(rec["tier_b_weight_share_num"]),
        "tier_c_weight_share": float(rec["tier_c_weight_share_num"]),
        "suspended": suspended,
        "suspension_reason": suspension_reason,
        "notes": "",
    }
