"""Phase 8 — derived TPRR indices (FPR, SER, B_F/B_S/B_E) from core (F, S, E).

Three derived index families:

* **TPRR_FPR(t) = TPRR_F(t) / TPRR_S(t)** — Frontier Premium Ratio.
* **TPRR_SER(t) = TPRR_S(t) / TPRR_E(t)** — Standard Efficiency Ratio.
* **TPRR_B_F / TPRR_B_S / TPRR_B_E** — blended-price series (methodology
  Section 3.3.4) using P_blended_i = 0.25 x P̃_outᵢ + 0.75 x P̃_inᵢ as the
  per-constituent price input to the dual-weighted formula. Analytics-
  only per CLAUDE.md ("never for derivative settlement").

Rebase convention (Q4 lock 2026-04-29 + decision log 2026-04-30 schema):

  index_level = 100 x ratio_today / ratio_anchor_date

Same uniform convention as the price indices — anchor = first non-suspended
ratio at-or-after ``config.base_date``.

Suspension propagation: ratio derived indices (FPR, SER) inherit suspension
from the upstream tier indices — FPR is suspended on day t if either F or
S is suspended; SER if either S or E is. The B series runs the full
aggregation pipeline on blended prices, so it suspends per the same
v0.1 SuspensionReason mechanism as the core tier indices.

The ``suspension_reason`` propagated for FPR/SER is the numerator's reason
when both are suspended, the suspended one's reason otherwise.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from tprr.config import IndexConfig, ModelRegistry, TierBRevenueConfig
from tprr.index.aggregation import (
    CoreIndexResults,
    rebase_index_level,
    run_tier_pipeline,
)
from tprr.index.weights import TierBVolumeFn
from tprr.schema import Tier

INDEX_CODE_FPR = "TPRR_FPR"
INDEX_CODE_SER = "TPRR_SER"

BLENDED_OUTPUT_WEIGHT = 0.75
BLENDED_INPUT_WEIGHT = 0.25
BLENDED_PRICE_COLUMN = "twap_blended_usd_mtok"

TIER_TO_BLENDED_CODE: dict[Tier, str] = {
    Tier.TPRR_F: "TPRR_B_F",
    Tier.TPRR_S: "TPRR_B_S",
    Tier.TPRR_E: "TPRR_B_E",
}


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

    merged = (
        numerator_df.merge(
            denominator_df,
            on="as_of_date",
            suffixes=("_num", "_den"),
            how="inner",
        )
        .sort_values("as_of_date")
        .reset_index(drop=True)
    )

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
            ratio = float(prior_ratio) if prior_ratio is not None else float("nan")
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

    ``n_constituents*`` are populated from the numerator (the ratio
    inherits the numerator's count). ``tier_*_weight_share`` are NaN per
    decision log 2026-04-30 "Phase 7 Batch D — FPR/SER tier weight share
    semantics: NaN per ratio symmetry": tier weight share is a property
    of constituent aggregations, not ratios of aggregations. Phase 9/10
    consumers needing tier-mix context for a ratio row must join against
    the underlying tier index rows.
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
        "tier_a_weight_share": float("nan"),
        "tier_b_weight_share": float("nan"),
        "tier_c_weight_share": float("nan"),
        "suspended": suspended,
        "suspension_reason": suspension_reason,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# TPRR_B blended series (Section 3.3.4)
# ---------------------------------------------------------------------------


def add_blended_twap_column(panel_df: pd.DataFrame) -> pd.DataFrame:
    """Append ``twap_blended_usd_mtok = 0.75 x out + 0.25 x in`` to a panel.

    Methodology Section 3.3.4 specifies the output-heavy blended price
    ``[P_in x 0.25 + P_out x 0.75]`` applied at the constituent level
    (decision log 2026-04-30 "Phase 7 Batch B'-fix" corrects the prior
    inverted weighting). Computing the blend per (contributor, constituent,
    date) before the volume-weighted constituent-level collapse is
    mathematically equivalent to collapsing output and input separately
    then blending — both produce the same constituent-level blended price
    because the blend is linear (and the collapse is volume-weighted with
    the same weights for both directions). We compute per-row here so
    downstream ``compute_tier_index(price_field=...)`` can operate
    uniformly.

    The input panel must already carry ``twap_output_usd_mtok`` and
    ``twap_input_usd_mtok`` populated by ``compute_panel_twap``.
    """
    if panel_df.empty:
        out = panel_df.copy()
        out[BLENDED_PRICE_COLUMN] = pd.Series([], dtype="float64")
        return out
    out = panel_df.copy()
    out[BLENDED_PRICE_COLUMN] = (
        BLENDED_OUTPUT_WEIGHT * out["twap_output_usd_mtok"]
        + BLENDED_INPUT_WEIGHT * out["twap_input_usd_mtok"]
    )
    return out


def compute_tprr_b_indices(
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
    """Compute the blended TPRR_B_F / TPRR_B_S / TPRR_B_E series.

    Per CLAUDE.md / methodology Section 3.3.4, the blended series uses
    P_blended_i = 0.25 x P̃_outᵢ + 0.75 x P̃_inᵢ as the per-constituent
    price input to the dual-weighted formula. Volume aggregation, w_exp,
    median, and the priority fall-through are all unchanged from the
    output-only core indices — only the price column flowing into the
    dual-weighted aggregation differs.

    Returns a ``CoreIndexResults`` keyed by ``TPRR_B_F`` / ``TPRR_B_S`` /
    ``TPRR_B_E``. Per-tier rebase anchors fall through the same way the
    core indices' anchors do (decision log Q4 lock 2026-04-29).
    Per-constituent audit rows are accumulated across the three blended
    tiers with ``index_code`` rewritten to the ``TPRR_B_*`` form.
    """
    from tprr.index.aggregation import _decisions_list_to_df

    panel_blended = add_blended_twap_column(panel_df)

    indices: dict[str, pd.DataFrame] = {}
    anchors: dict[str, date | None] = {}
    all_decisions: list[dict[str, Any]] = []
    for tier, b_code in TIER_TO_BLENDED_CODE.items():
        tier_decisions: list[dict[str, Any]] = []
        tier_indices = run_tier_pipeline(
            panel_df=panel_blended,
            tier=tier,
            config=config,
            registry=registry,
            tier_b_config=tier_b_config,
            tier_b_volume_fn=tier_b_volume_fn,
            suspended_pairs_df=suspended_pairs_df,
            ordering=ordering,
            version=version,
            price_field=BLENDED_PRICE_COLUMN,
            decisions_out=tier_decisions,
            change_events_df=change_events_df,
            excluded_slots_df=excluded_slots_df,
        )
        # Rewrite index_code from "TPRR_F" → "TPRR_B_F" etc. on both the
        # IndexValueDF rows and the per-constituent audit rows.
        if not tier_indices.empty:
            tier_indices = tier_indices.copy()
            tier_indices["index_code"] = b_code
        for d in tier_decisions:
            d["index_code"] = b_code
        all_decisions.extend(tier_decisions)
        rebased, anchor = rebase_index_level(tier_indices, base_date=config.base_date)
        indices[b_code] = rebased
        anchors[b_code] = anchor
    return CoreIndexResults(
        indices=indices,
        rebase_anchors=anchors,
        constituent_decisions=_decisions_list_to_df(all_decisions),
    )
