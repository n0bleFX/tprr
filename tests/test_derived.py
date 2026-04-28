"""Tests for tprr.index.derived — FPR + SER ratio indices."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tprr.config import IndexConfig
from tprr.index.derived import compute_fpr, compute_ser
from tprr.schema import IndexValueDF


def _idx_row(
    *,
    as_of_date: date,
    index_code: str,
    raw_value: float,
    suspended: bool = False,
    suspension_reason: str = "",
    n_a: int = 6,
    n_b: int = 0,
    n_c: int = 0,
    weight_a: float = 1.0,
    weight_b: float = 0.0,
    weight_c: float = 0.0,
) -> dict[str, Any]:
    return {
        "as_of_date": pd.Timestamp(as_of_date),
        "index_code": index_code,
        "version": "v0_1",
        "lambda": 3.0,
        "ordering": "twap_then_weight",
        "raw_value_usd_mtok": raw_value,
        "index_level": float("nan"),
        "n_constituents": n_a + n_b + n_c,
        "n_constituents_active": n_a + n_b + n_c,
        "n_constituents_a": n_a,
        "n_constituents_b": n_b,
        "n_constituents_c": n_c,
        "tier_a_weight_share": weight_a,
        "tier_b_weight_share": weight_b,
        "tier_c_weight_share": weight_c,
        "suspended": suspended,
        "suspension_reason": suspension_reason,
        "notes": "",
    }


def _f_df_clean() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_F", raw_value=56.0),
            _idx_row(as_of_date=date(2026, 1, 2), index_code="TPRR_F", raw_value=57.0),
            _idx_row(as_of_date=date(2026, 1, 3), index_code="TPRR_F", raw_value=58.0),
        ]
    )


def _s_df_clean() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_S", raw_value=4.0),
            _idx_row(as_of_date=date(2026, 1, 2), index_code="TPRR_S", raw_value=4.2),
            _idx_row(as_of_date=date(2026, 1, 3), index_code="TPRR_S", raw_value=4.4),
        ]
    )


def _e_df_clean() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_E", raw_value=0.4),
            _idx_row(as_of_date=date(2026, 1, 2), index_code="TPRR_E", raw_value=0.45),
            _idx_row(as_of_date=date(2026, 1, 3), index_code="TPRR_E", raw_value=0.5),
        ]
    )


def _config() -> IndexConfig:
    return IndexConfig(base_date=date(2026, 1, 1))


# ---------------------------------------------------------------------------
# FPR
# ---------------------------------------------------------------------------


def test_fpr_basic_ratio() -> None:
    """Per-day raw_value = F / S; index_level = 100 x ratio_today / ratio_anchor."""
    fpr_df, anchor = compute_fpr(_f_df_clean(), _s_df_clean(), _config())
    assert anchor == date(2026, 1, 1)
    assert len(fpr_df) == 3
    # Day 1: 56.0/4.0 = 14.0 → index_level 100.
    # Day 2: 57.0/4.2 ≈ 13.571 → index_level 100 x 13.571/14.0 ≈ 96.94.
    # Day 3: 58.0/4.4 ≈ 13.182 → index_level 100 x 13.182/14.0 ≈ 94.16.
    assert float(fpr_df.iloc[0]["raw_value_usd_mtok"]) == pytest.approx(14.0)
    assert float(fpr_df.iloc[0]["index_level"]) == pytest.approx(100.0)
    assert float(fpr_df.iloc[1]["raw_value_usd_mtok"]) == pytest.approx(57.0 / 4.2)
    assert float(fpr_df.iloc[1]["index_level"]) == pytest.approx(
        100.0 * (57.0 / 4.2) / 14.0
    )


def test_fpr_index_code_is_tprr_fpr() -> None:
    fpr_df, _ = compute_fpr(_f_df_clean(), _s_df_clean(), _config())
    assert (fpr_df["index_code"] == "TPRR_FPR").all()


def test_fpr_suspends_when_numerator_suspended_and_carries_prior() -> None:
    """If F is suspended on day t but S is fine, FPR is suspended on t.
    Prior-ratio carry-forward populates raw_value with the last valid ratio."""
    f = pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_F", raw_value=56.0),
            _idx_row(
                as_of_date=date(2026, 1, 2),
                index_code="TPRR_F",
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="insufficient_constituents",
            ),
            _idx_row(as_of_date=date(2026, 1, 3), index_code="TPRR_F", raw_value=58.0),
        ]
    )
    s = _s_df_clean()
    fpr_df, _ = compute_fpr(f, s, _config())
    assert not bool(fpr_df.iloc[0]["suspended"])
    assert bool(fpr_df.iloc[1]["suspended"])
    assert fpr_df.iloc[1]["suspension_reason"] == "insufficient_constituents"
    # Carries day-1 ratio forward.
    assert float(fpr_df.iloc[1]["raw_value_usd_mtok"]) == pytest.approx(56.0 / 4.0)
    assert not bool(fpr_df.iloc[2]["suspended"])


def test_fpr_suspends_when_denominator_suspended() -> None:
    """If S is suspended (denominator), FPR is suspended."""
    s = pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_S", raw_value=4.0),
            _idx_row(
                as_of_date=date(2026, 1, 2),
                index_code="TPRR_S",
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="tier_data_unavailable",
            ),
            _idx_row(as_of_date=date(2026, 1, 3), index_code="TPRR_S", raw_value=4.4),
        ]
    )
    fpr_df, _ = compute_fpr(_f_df_clean(), s, _config())
    assert bool(fpr_df.iloc[1]["suspended"])
    assert fpr_df.iloc[1]["suspension_reason"] == "tier_data_unavailable"


def test_fpr_first_day_suspended_no_prior_emits_nan_ratio() -> None:
    """If day 1 is suspended (no prior), raw_value_usd_mtok is NaN, not the
    fallback. The next valid day picks up cleanly and becomes the rebase
    anchor."""
    f = pd.DataFrame(
        [
            _idx_row(
                as_of_date=date(2026, 1, 1),
                index_code="TPRR_F",
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="insufficient_constituents",
            ),
            _idx_row(as_of_date=date(2026, 1, 2), index_code="TPRR_F", raw_value=57.0),
        ]
    )
    s = pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_S", raw_value=4.0),
            _idx_row(as_of_date=date(2026, 1, 2), index_code="TPRR_S", raw_value=4.2),
        ]
    )
    fpr_df, anchor = compute_fpr(f, s, _config())
    assert bool(fpr_df.iloc[0]["suspended"])
    assert np.isnan(float(fpr_df.iloc[0]["raw_value_usd_mtok"]))
    assert anchor == date(2026, 1, 2)
    assert float(fpr_df.iloc[1]["index_level"]) == pytest.approx(100.0)


def test_fpr_output_validates_against_index_value_df_schema() -> None:
    fpr_df, _ = compute_fpr(_f_df_clean(), _s_df_clean(), _config())
    out = IndexValueDF.validate(fpr_df)
    assert out is fpr_df


# ---------------------------------------------------------------------------
# SER
# ---------------------------------------------------------------------------


def test_ser_basic_ratio() -> None:
    ser_df, anchor = compute_ser(_s_df_clean(), _e_df_clean(), _config())
    assert anchor == date(2026, 1, 1)
    # Day 1: 4.0/0.4 = 10.0 → index_level 100.
    # Day 2: 4.2/0.45 ≈ 9.333 → index_level 100 x 9.333/10.0 ≈ 93.33.
    assert float(ser_df.iloc[0]["raw_value_usd_mtok"]) == pytest.approx(10.0)
    assert float(ser_df.iloc[0]["index_level"]) == pytest.approx(100.0)
    assert float(ser_df.iloc[1]["raw_value_usd_mtok"]) == pytest.approx(4.2 / 0.45)
    assert float(ser_df.iloc[1]["index_level"]) == pytest.approx(
        100.0 * (4.2 / 0.45) / 10.0
    )


def test_ser_index_code_is_tprr_ser() -> None:
    ser_df, _ = compute_ser(_s_df_clean(), _e_df_clean(), _config())
    assert (ser_df["index_code"] == "TPRR_SER").all()


def test_ser_suspends_when_either_input_suspended() -> None:
    e = pd.DataFrame(
        [
            _idx_row(as_of_date=date(2026, 1, 1), index_code="TPRR_E", raw_value=0.4),
            _idx_row(
                as_of_date=date(2026, 1, 2),
                index_code="TPRR_E",
                raw_value=float("nan"),
                suspended=True,
                suspension_reason="quality_gate_cascade",
            ),
        ]
    )
    s = _s_df_clean().iloc[:2].copy()
    ser_df, _ = compute_ser(s, e, _config())
    assert bool(ser_df.iloc[1]["suspended"])
    assert ser_df.iloc[1]["suspension_reason"] == "quality_gate_cascade"


def test_ser_output_validates_against_index_value_df_schema() -> None:
    ser_df, _ = compute_ser(_s_df_clean(), _e_df_clean(), _config())
    out = IndexValueDF.validate(ser_df)
    assert out is ser_df


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------


def test_compute_fpr_empty_inputs_returns_empty() -> None:
    out, anchor = compute_fpr(pd.DataFrame(), pd.DataFrame(), _config())
    assert out.empty
    assert anchor is None


def test_compute_ser_empty_inputs_returns_empty() -> None:
    out, anchor = compute_ser(pd.DataFrame(), pd.DataFrame(), _config())
    assert out.empty
    assert anchor is None
