"""Recompute IndexValueDF rows from a long-format ConstituentDecisionDF audit.

The Phase 7H Batch B audit (DL 2026-04-30 "Phase 7H Batch B audit trail
design") emits one row per (date, index_code, constituent_id, attestation_tier)
under continuous blending. These rows carry every per-tier intermediate the
dual-weighted formula consumes:

- ``raw_volume_mtok``, ``within_tier_volume_share``: invariant under λ /
  haircut / coefficient changes (they describe panel structure, not
  weighting)
- ``tier_collapsed_price_usd_mtok``: the volume-weighted contributor TWAP
  for that tier on that constituent — invariant under all three sweep
  parameter changes
- ``coefficient``, ``w_vol_contribution``, ``constituent_price_usd_mtok``,
  ``tier_median_price_usd_mtok``, ``w_exp``, ``combined_weight``:
  parameter-dependent — recomputed here

Recompute scope (Batch 10A): λ, Tier B haircut, blending coefficients. All
three sweep types preserve which constituents survived tier-volume
resolution, so the audit row set is invariant. Pipeline-rerun sweeps
(suspension threshold, TWAP ordering — Batch 10B) change row presence and
require a fresh pipeline run.

The ``recompute_indices_under_override`` entry point preserves all
suspension shape from the original IndexValueDF: rows with
``suspended=True`` pass through with the new ``lambda`` field but no other
changes (suspension reason is a tier-resolution property, not a parameter
property). Non-suspended rows are recomputed from audit then rebased via
``rebase_index_level``. FPR/SER are recomputed from new F/S/E via
``compute_fpr`` / ``compute_ser``.
"""

from __future__ import annotations

import contextlib
from typing import Any, cast

import numpy as np
import pandas as pd

from tprr.config import IndexConfig
from tprr.index.aggregation import rebase_index_level
from tprr.index.derived import compute_fpr, compute_ser
from tprr.index.weights import (
    exponential_weight,
    redistribute_blending_coefficients,
    volume_weight,
)
from tprr.schema import AttestationTier

CORE_INDEX_CODES: tuple[str, ...] = (
    "TPRR_F",
    "TPRR_S",
    "TPRR_E",
    "TPRR_B_F",
    "TPRR_B_S",
    "TPRR_B_E",
)


def with_overrides(
    base: IndexConfig,
    *,
    lambda_: float | None = None,
    tier_haircuts: dict[AttestationTier, float] | None = None,
    tier_blending_coefficients: dict[AttestationTier, float] | None = None,
) -> IndexConfig:
    """Return a copy of ``base`` with the supplied fields substituted.

    Convenience wrapper around ``BaseModel.model_copy(update=...)`` that
    keeps the keyword names aligned with ``IndexConfig`` field names. Pass
    ``None`` for parameters not being overridden.
    """
    update: dict[str, Any] = {}
    if lambda_ is not None:
        update["lambda_"] = float(lambda_)
    if tier_haircuts is not None:
        update["tier_haircuts"] = dict(tier_haircuts)
    if tier_blending_coefficients is not None:
        update["tier_blending_coefficients"] = dict(tier_blending_coefficients)
    if not update:
        return base.model_copy()
    return base.model_copy(update=update)


def recompute_indices_under_override(
    *,
    constituent_decisions: pd.DataFrame,
    original_indices: dict[str, pd.DataFrame],
    new_config: IndexConfig,
) -> dict[str, pd.DataFrame]:
    """Recompute all 8 IndexValueDF outputs from audit under a new config.

    ``constituent_decisions`` must be a long-format ConstituentDecisionDF
    (Phase 7H Batch B shape). ``original_indices`` is the dict returned by
    ``run_full_pipeline.indices`` — used as the suspension skeleton and for
    invariant fields (``n_constituents``, ``version``, ``ordering``).
    ``new_config`` carries the post-override ``lambda_``, ``tier_haircuts``,
    ``tier_blending_coefficients``.

    Suspended rows in ``original_indices`` pass through with the new lambda
    field; the recompute does not change suspension semantics. FPR/SER
    recompute from the new F/S/E rather than from audit (audit has no
    rows for ratio indices).

    Returns a dict matching ``original_indices.keys()`` (8 codes — F/S/E,
    FPR/SER, B_F/B_S/B_E). Output IndexValueDFs match the input's dtype
    contract column-for-column (Phase 11 writeup will join across
    sweeps; schema drift is a contract violation).
    """
    out: dict[str, pd.DataFrame] = {}
    for code in CORE_INDEX_CODES:
        if code not in original_indices:
            continue
        original = original_indices[code]
        if original.empty:
            out[code] = original
            continue
        audit_slice = constituent_decisions[constituent_decisions["index_code"] == code]
        out[code] = _recompute_core_index(
            audit_df=audit_slice,
            original_df=original,
            new_config=new_config,
        )

    if "TPRR_F" in out and "TPRR_S" in out:
        fpr, _ = compute_fpr(
            out["TPRR_F"],
            out["TPRR_S"],
            new_config,
            version=_first_str(original_indices.get("TPRR_FPR"), "version", "v0_1"),
            ordering=_first_str(
                original_indices.get("TPRR_FPR"), "ordering", new_config.default_ordering
            ),
        )
        out["TPRR_FPR"] = fpr
    if "TPRR_S" in out and "TPRR_E" in out:
        ser, _ = compute_ser(
            out["TPRR_S"],
            out["TPRR_E"],
            new_config,
            version=_first_str(original_indices.get("TPRR_SER"), "version", "v0_1"),
            ordering=_first_str(
                original_indices.get("TPRR_SER"), "ordering", new_config.default_ordering
            ),
        )
        out["TPRR_SER"] = ser
    return out


def _first_str(df: pd.DataFrame | None, col: str, fallback: str) -> str:
    if df is None or df.empty or col not in df.columns:
        return fallback
    return str(df[col].iloc[0])


def _recompute_core_index(
    *,
    audit_df: pd.DataFrame,
    original_df: pd.DataFrame,
    new_config: IndexConfig,
) -> pd.DataFrame:
    """Recompute one tier's IndexValueDF from audit + skeleton.

    Walks dates from ``original_df`` in ascending order, threading the
    most recent recomputed ``raw_value_usd_mtok`` as the carry-forward for
    suspended rows (matches ``run_tier_pipeline``'s behavior). Calls
    ``rebase_index_level`` at the end so ``index_level`` reflects the new
    raw_value trajectory.
    """
    if original_df.empty:
        return original_df.copy()

    audit_by_date: dict[pd.Timestamp, pd.DataFrame] = {}
    if not audit_df.empty:
        for ts, g in audit_df.groupby("as_of_date"):
            audit_by_date[pd.Timestamp(cast(Any, ts))] = g

    new_lambda = float(new_config.lambda_)
    rows: list[dict[str, Any]] = []
    prior_raw_value: float | None = None

    for original_row in cast(
        list[dict[str, Any]],
        original_df.sort_values("as_of_date").to_dict("records"),
    ):
        as_of_ts = pd.Timestamp(original_row["as_of_date"])
        if bool(original_row["suspended"]):
            new_row = dict(original_row)
            new_row["lambda"] = new_lambda
            new_row["raw_value_usd_mtok"] = (
                float(prior_raw_value)
                if prior_raw_value is not None
                else float(original_row["raw_value_usd_mtok"])
            )
            new_row["index_level"] = float("nan")
            rows.append(new_row)
            continue

        included_audit = audit_by_date.get(as_of_ts)
        if included_audit is None or included_audit.empty:
            new_row = dict(original_row)
            new_row["lambda"] = new_lambda
            new_row["index_level"] = float("nan")
            rows.append(new_row)
            continue
        included_audit = included_audit[included_audit["included"]]
        included_audit = included_audit[
            included_audit["attestation_tier"].isin([t.value for t in AttestationTier])
        ]
        if included_audit.empty:
            new_row = dict(original_row)
            new_row["lambda"] = new_lambda
            new_row["index_level"] = float("nan")
            rows.append(new_row)
            continue

        recomputed = _recompute_one_day_active(
            day_audit=included_audit,
            new_config=new_config,
            original_row=original_row,
        )
        recomputed["lambda"] = new_lambda
        rows.append(recomputed)
        if not bool(recomputed["suspended"]) and np.isfinite(
            float(recomputed["raw_value_usd_mtok"])
        ):
            prior_raw_value = float(recomputed["raw_value_usd_mtok"])

    out = pd.DataFrame(rows)
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).astype("datetime64[ns]")
    rebased, _ = rebase_index_level(out, base_date=new_config.base_date)
    return _coerce_index_value_dtypes(rebased, original_df)


def _recompute_one_day_active(
    *,
    day_audit: pd.DataFrame,
    new_config: IndexConfig,
    original_row: dict[str, Any],
) -> dict[str, Any]:
    """Recompute a single (date, index_code) IndexValue row from audit.

    The audit is filtered to ``included == True`` and a non-empty
    ``attestation_tier`` upstream. One row per (constituent, contributing
    tier). ``raw_volume_mtok`` and ``tier_collapsed_price_usd_mtok`` are
    invariant under sweep parameters; everything else is recomputed.
    """
    coef_defaults = new_config.tier_blending_coefficients

    volumes_by_tier: dict[AttestationTier, dict[str, float]] = {
        AttestationTier.A: {},
        AttestationTier.B: {},
        AttestationTier.C: {},
    }
    per_constituent_tiers: dict[str, dict[AttestationTier, dict[str, float]]] = {}
    for rec in cast(list[dict[str, Any]], day_audit.to_dict("records")):
        cid = str(rec["constituent_id"])
        tier_t = AttestationTier(str(rec["attestation_tier"]))
        raw_volume = float(rec["raw_volume_mtok"])
        tier_price = float(rec["tier_collapsed_price_usd_mtok"])
        contributor_count = int(rec["contributor_count"])
        volumes_by_tier[tier_t][cid] = raw_volume
        per_constituent_tiers.setdefault(cid, {})[tier_t] = {
            "raw_volume": raw_volume,
            "tier_price": tier_price,
            "contributor_count": float(contributor_count),
        }

    shares_by_tier: dict[AttestationTier, dict[str, float]] = {
        tier_t: _within_tier_share(volumes) for tier_t, volumes in volumes_by_tier.items()
    }

    # Tier-eligibility threshold (DL 2026-05-01 Phase 10 Batch 10A) — must
    # apply identically to compute_tier_index so recompute at the same
    # config matches the pipeline byte-for-byte. Tiers with constituent
    # count < threshold are dormant globally; their coefficients
    # redistribute over remaining eligible tiers.
    eligible_tiers: set[AttestationTier] = {
        tier_t
        for tier_t, vols in volumes_by_tier.items()
        if len(vols) >= new_config.tier_min_constituents_for_blending
    }

    rows: list[dict[str, Any]] = []
    for cid, per_tier in per_constituent_tiers.items():
        eligible_in_per_tier = {t for t in per_tier if t in eligible_tiers}
        if not eligible_in_per_tier:
            # Constituent has only ineligible tiers — TIER_INELIGIBLE_FOR_BLENDING
            # case from compute_tier_index. Skip from rows; pipeline emits a
            # separate audit row for this, but recompute reads audit and
            # produces the IndexValueDF only.
            continue
        coefficients = redistribute_blending_coefficients(
            available_tiers=eligible_in_per_tier,
            default_coefficients=coef_defaults,
        )
        combined_w_vol = 0.0
        combined_price = 0.0
        for tier_t, info in per_tier.items():
            share = shares_by_tier[tier_t][cid]
            if tier_t in eligible_tiers:
                coef = coefficients[tier_t]
                w_vol_contribution = coef * volume_weight(share, tier_t, new_config)
            else:
                coef = 0.0
                w_vol_contribution = 0.0
            combined_w_vol += w_vol_contribution
            combined_price += coef * float(info["tier_price"])
            info["share"] = share
            info["coefficient"] = coef
            info["w_vol_contribution"] = w_vol_contribution
        rows.append(
            {
                "constituent_id": cid,
                "per_tier_data": per_tier,
                "w_vol": combined_w_vol,
                "price": combined_price,
            }
        )

    if len(rows) < new_config.min_constituents_per_tier:
        return _suspended_passthrough_row(
            original_row=original_row,
            new_config=new_config,
            n_active=len(rows),
            volumes_by_tier=volumes_by_tier,
        )

    tier_median = float(np.median(np.array([float(r["price"]) for r in rows], dtype=np.float64)))

    for r in rows:
        if tier_median <= 0:
            r["w_exp"] = float("nan")
            r["weight"] = float("nan")
            continue
        r["w_exp"] = exponential_weight(float(r["price"]), tier_median, float(new_config.lambda_))
        r["weight"] = float(r["w_vol"]) * float(r["w_exp"])

    weights = [float(r["weight"]) for r in rows]
    total_weight = float(sum(weights))
    if total_weight <= 0 or not np.isfinite(total_weight):
        return _suspended_passthrough_row(
            original_row=original_row,
            new_config=new_config,
            n_active=len(rows),
            volumes_by_tier=volumes_by_tier,
        )

    raw_value = float(sum(float(r["weight"]) * float(r["price"]) for r in rows) / total_weight)

    weight_a = _tier_share(rows, AttestationTier.A, total_weight)
    weight_b = _tier_share(rows, AttestationTier.B, total_weight)
    weight_c = _tier_share(rows, AttestationTier.C, total_weight)

    # Eligibility-aware n_a/n_b/n_c (DL 2026-05-01 Phase 10 Batch 10A): only
    # eligible tiers contribute to active counts; ineligible tiers report 0.
    n_a = (
        sum(1 for r in rows if AttestationTier.A in r["per_tier_data"])
        if AttestationTier.A in eligible_tiers
        else 0
    )
    n_b = (
        sum(1 for r in rows if AttestationTier.B in r["per_tier_data"])
        if AttestationTier.B in eligible_tiers
        else 0
    )
    n_c = (
        sum(1 for r in rows if AttestationTier.C in r["per_tier_data"])
        if AttestationTier.C in eligible_tiers
        else 0
    )

    return {
        "as_of_date": original_row["as_of_date"],
        "index_code": original_row["index_code"],
        "version": original_row["version"],
        "lambda": float(new_config.lambda_),
        "ordering": original_row["ordering"],
        "raw_value_usd_mtok": raw_value,
        "index_level": float("nan"),
        "n_constituents": int(original_row["n_constituents"]),
        "n_constituents_active": len(rows),
        "n_constituents_a": n_a,
        "n_constituents_b": n_b,
        "n_constituents_c": n_c,
        "tier_a_weight_share": weight_a,
        "tier_b_weight_share": weight_b,
        "tier_c_weight_share": weight_c,
        "suspended": False,
        "suspension_reason": "",
        "notes": str(original_row.get("notes", "")),
    }


def _within_tier_share(raw_volumes: dict[str, float]) -> dict[str, float]:
    if not raw_volumes:
        return {}
    total = sum(raw_volumes.values())
    if total <= 0:
        return {cid: 0.0 for cid in raw_volumes}
    return {cid: v / total for cid, v in raw_volumes.items()}


def _tier_share(
    rows: list[dict[str, Any]],
    tier_t: AttestationTier,
    total_weight: float,
) -> float:
    if total_weight <= 0:
        return 0.0
    contribution = sum(
        float(r["per_tier_data"][tier_t]["w_vol_contribution"]) * float(r["w_exp"])
        for r in rows
        if tier_t in r["per_tier_data"]
    )
    return float(contribution) / float(total_weight)


def _suspended_passthrough_row(
    *,
    original_row: dict[str, Any],
    new_config: IndexConfig,
    n_active: int,
    volumes_by_tier: dict[AttestationTier, dict[str, float]],
) -> dict[str, Any]:
    """Build a suspended IndexValue row matching ``_suspended_row``'s shape.

    Used when the recompute path itself surfaces a suspension that the
    original audit did not (e.g., new coefficients drive total weight to
    zero on a previously-active day). Carries the original row's
    ``raw_value_usd_mtok`` as the prior fallback so the rebase trajectory
    behaves like a real run.
    """
    return {
        "as_of_date": original_row["as_of_date"],
        "index_code": original_row["index_code"],
        "version": original_row["version"],
        "lambda": float(new_config.lambda_),
        "ordering": original_row["ordering"],
        "raw_value_usd_mtok": float(original_row["raw_value_usd_mtok"]),
        "index_level": float("nan"),
        "n_constituents": int(original_row["n_constituents"]),
        "n_constituents_active": n_active,
        "n_constituents_a": len(volumes_by_tier[AttestationTier.A]),
        "n_constituents_b": len(volumes_by_tier[AttestationTier.B]),
        "n_constituents_c": len(volumes_by_tier[AttestationTier.C]),
        "tier_a_weight_share": 0.0,
        "tier_b_weight_share": 0.0,
        "tier_c_weight_share": 0.0,
        "suspended": True,
        "suspension_reason": str(original_row.get("suspension_reason", "")),
        "notes": str(original_row.get("notes", "")),
    }


def _coerce_index_value_dtypes(df: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Force dtype-equality with ``reference`` column-for-column.

    The Phase 11 writeup pipeline joins across sweep outputs; column
    dtypes drifting between (e.g.) string and object on ``index_code``
    breaks downstream concat. ``reference`` is the original IndexValueDF
    for this code from ``run_full_pipeline``.
    """
    out = df.copy()
    for col in reference.columns:
        if col not in out.columns:
            continue
        target_dtype = reference[col].dtype
        if out[col].dtype == target_dtype:
            continue
        with contextlib.suppress(ValueError, TypeError):
            out[col] = out[col].astype(target_dtype)
    return out[list(reference.columns)] if set(reference.columns).issubset(out.columns) else out
