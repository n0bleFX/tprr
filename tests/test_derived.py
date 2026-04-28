"""Tests for tprr.index.derived — FPR + SER ratio indices + TPRR_B blended series."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tprr.config import (
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
)
from tprr.index.derived import (
    BLENDED_INPUT_WEIGHT,
    BLENDED_OUTPUT_WEIGHT,
    BLENDED_PRICE_COLUMN,
    add_blended_twap_column,
    compute_fpr,
    compute_ser,
    compute_tprr_b_indices,
)
from tprr.index.weights import TierBVolumeFn
from tprr.schema import AttestationTier, IndexValueDF, Tier


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


# ---------------------------------------------------------------------------
# TPRR_B blended series
# ---------------------------------------------------------------------------


def _b_panel_row(
    *,
    constituent_id: str,
    contributor_id: str,
    observation_date: date,
    twap_output: float,
    twap_input: float,
    volume: float,
    tier_code: Tier,
    attestation_tier: AttestationTier = AttestationTier.A,
) -> dict[str, Any]:
    return {
        "observation_date": pd.Timestamp(observation_date),
        "constituent_id": constituent_id,
        "contributor_id": contributor_id,
        "tier_code": tier_code.value,
        "attestation_tier": attestation_tier.value,
        "input_price_usd_mtok": float(twap_input),
        "output_price_usd_mtok": float(twap_output),
        "volume_mtok_7d": float(volume),
        "twap_output_usd_mtok": float(twap_output),
        "twap_input_usd_mtok": float(twap_input),
        "source": "test",
        "submitted_at": pd.Timestamp(observation_date),
        "notes": "",
    }


def _b_three_tier_panel(d: date) -> pd.DataFrame:
    """Tier A panel covering 3 F + 3 S + 3 E constituents on date d with both
    output and input prices populated for blended-series testing."""
    rows: list[dict[str, Any]] = []
    f = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    s = [
        ("openai/gpt-5-mini", 4.0, 0.5),
        ("anthropic/claude-haiku-4-5", 5.0, 1.0),
        ("google/gemini-2-flash", 2.5, 0.3),
    ]
    e = [
        ("google/gemini-flash-lite", 0.4, 0.1),
        ("openai/gpt-5-nano", 0.6, 0.15),
        ("deepseek/deepseek-v3-2", 1.0, 0.25),
    ]
    for tier_set, tier in [(f, Tier.TPRR_F), (s, Tier.TPRR_S), (e, Tier.TPRR_E)]:
        for cid, p_out, p_in in tier_set:
            for c in ["c1", "c2", "c3"]:
                rows.append(
                    _b_panel_row(
                        constituent_id=cid,
                        contributor_id=c,
                        observation_date=d,
                        twap_output=p_out,
                        twap_input=p_in,
                        volume=100.0,
                        tier_code=tier,
                    )
                )
    return pd.DataFrame(rows)


def _b_three_tier_registry() -> ModelRegistry:
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=baseline_in,
                baseline_output_price_usd_mtok=baseline_out,
            )
            for cid, tier, baseline_in, baseline_out in [
                ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
                ("anthropic/claude-opus-4-7", Tier.TPRR_F, 14.0, 70.0),
                ("google/gemini-3-pro", Tier.TPRR_F, 5.0, 30.0),
                ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
                ("anthropic/claude-haiku-4-5", Tier.TPRR_S, 1.0, 5.0),
                ("google/gemini-2-flash", Tier.TPRR_S, 0.3, 2.5),
                ("google/gemini-flash-lite", Tier.TPRR_E, 0.1, 0.4),
                ("openai/gpt-5-nano", Tier.TPRR_E, 0.15, 0.6),
                ("deepseek/deepseek-v3-2", Tier.TPRR_E, 0.25, 1.0),
            ]
        ]
    )


def _empty_tier_b_config() -> TierBRevenueConfig:
    return TierBRevenueConfig(entries=[])


def _stub_tier_b_volume_fn() -> TierBVolumeFn:
    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return 0.0

    return _fn


def test_add_blended_twap_column_applies_methodology_weights() -> None:
    """Per-row blended price = 0.25 x output + 0.75 x input."""
    df = pd.DataFrame(
        [
            {"twap_output_usd_mtok": 100.0, "twap_input_usd_mtok": 20.0},
            {"twap_output_usd_mtok": 50.0, "twap_input_usd_mtok": 10.0},
        ]
    )
    out = add_blended_twap_column(df)
    # Row 0: 0.25 x 100 + 0.75 x 20 = 25 + 15 = 40
    # Row 1: 0.25 x 50  + 0.75 x 10 = 12.5 + 7.5 = 20
    assert out.iloc[0][BLENDED_PRICE_COLUMN] == pytest.approx(40.0)
    assert out.iloc[1][BLENDED_PRICE_COLUMN] == pytest.approx(20.0)
    # Methodology weight constants are exposed
    assert BLENDED_OUTPUT_WEIGHT == 0.25
    assert BLENDED_INPUT_WEIGHT == 0.75


def test_add_blended_twap_column_empty_returns_empty_with_column() -> None:
    out = add_blended_twap_column(pd.DataFrame())
    assert BLENDED_PRICE_COLUMN in out.columns
    assert out.empty


def test_compute_tprr_b_indices_emits_three_codes_with_rebase() -> None:
    """All three blended indices land at index_level=100.0 on base_date."""
    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = pd.concat(
        [_b_three_tier_panel(date(2025, 1, 1)), _b_three_tier_panel(date(2025, 1, 2))],
        ignore_index=True,
    )
    result = compute_tprr_b_indices(
        panel_df=panel,
        config=config,
        registry=_b_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert set(result.indices.keys()) == {"TPRR_B_F", "TPRR_B_S", "TPRR_B_E"}
    for code, df in result.indices.items():
        assert (df["index_code"] == code).all()
        anchor_row = df[df["as_of_date"] == pd.Timestamp(date(2025, 1, 1))]
        assert float(anchor_row["index_level"].iloc[0]) == pytest.approx(100.0)
        assert result.rebase_anchors[code] == date(2025, 1, 1)


def test_compute_tprr_b_indices_blended_price_lower_than_output() -> None:
    """Methodology rule of thumb: B_X < TPRR_X for the same tier-day on
    realistic registries where input prices < output prices.

    With F-tier output prices [75, 70, 30] and inputs [15, 14, 5]:
    blended = 0.25 x out + 0.75 x in = [25 - 26.25 range]
    The dual-weighted aggregate will land lower than the output-only
    TPRR_F aggregate (~58 with these inputs)."""
    from tprr.index.aggregation import run_all_core_indices

    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = _b_three_tier_panel(date(2025, 1, 1))

    core = run_all_core_indices(
        panel_df=panel,
        config=config,
        registry=_b_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    blended = compute_tprr_b_indices(
        panel_df=panel,
        config=config,
        registry=_b_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    for tier_code, b_code in (
        ("TPRR_F", "TPRR_B_F"),
        ("TPRR_S", "TPRR_B_S"),
        ("TPRR_E", "TPRR_B_E"),
    ):
        f_raw = float(core.indices[tier_code].iloc[0]["raw_value_usd_mtok"])
        b_raw = float(blended.indices[b_code].iloc[0]["raw_value_usd_mtok"])
        assert b_raw < f_raw, (
            f"{b_code}={b_raw} should be < {tier_code}={f_raw} given input < output prices"
        )


def test_compute_tprr_b_indices_each_row_validates_against_index_value_df() -> None:
    config = IndexConfig(base_date=date(2025, 1, 1))
    panel = _b_three_tier_panel(date(2025, 1, 1))
    result = compute_tprr_b_indices(
        panel_df=panel,
        config=config,
        registry=_b_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    for df in result.indices.values():
        IndexValueDF.validate(df)


def test_compute_tprr_b_indices_empty_panel_emits_empty_dfs() -> None:
    config = IndexConfig(base_date=date(2025, 1, 1))
    result = compute_tprr_b_indices(
        panel_df=pd.DataFrame(),
        config=config,
        registry=_b_three_tier_registry(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    for code in ("TPRR_B_F", "TPRR_B_S", "TPRR_B_E"):
        assert result.indices[code].empty
        assert result.rebase_anchors[code] is None
