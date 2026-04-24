"""Tests for tprr.schema — pydantic record types and DataFrame validators."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from tprr.schema import (
    AttestationTier,
    ChangeEvent,
    ChangeEventDF,
    IndexValue,
    IndexValueDF,
    PanelObservation,
    PanelObservationDF,
    Tier,
)


def _valid_panel_obs() -> dict[str, object]:
    return {
        "observation_date": date(2025, 1, 15),
        "constituent_id": "openai/gpt-5-pro",
        "contributor_id": "contrib_alpha",
        "tier_code": Tier.TPRR_F,
        "attestation_tier": AttestationTier.A,
        "input_price_usd_mtok": 15.0,
        "output_price_usd_mtok": 75.0,
        "volume_mtok_7d": 12_500.0,
        "source": "contributor_mock",
        "submitted_at": datetime(2025, 1, 15, 17, 0, 0),
        "notes": "",
    }


def _valid_change_event() -> dict[str, object]:
    return {
        "event_date": date(2025, 6, 3),
        "contributor_id": "contrib_alpha",
        "constituent_id": "openai/gpt-5-pro",
        "change_slot_idx": 16,
        "old_input_price_usd_mtok": 15.0,
        "new_input_price_usd_mtok": 12.0,
        "old_output_price_usd_mtok": 75.0,
        "new_output_price_usd_mtok": 60.0,
        "reason": "baseline_cut",
    }


def _valid_index_value() -> dict[str, object]:
    return {
        "as_of_date": date(2026, 1, 1),
        "index_code": "TPRR_F",
        "version": "v0_1",
        "lambda": 3.0,
        "ordering": "twap_then_weight",
        "raw_value_usd_mtok": 65.0,
        "index_level": 100.0,
        "n_constituents": 5,
        "n_constituents_active": 5,
        "tier_a_weight_share": 0.7,
        "tier_b_weight_share": 0.2,
        "tier_c_weight_share": 0.1,
        "suspended": False,
        "notes": "",
    }


def test_panel_observation_accepts_valid_row() -> None:
    obs = PanelObservation(**_valid_panel_obs())
    assert obs.tier_code == Tier.TPRR_F
    assert obs.attestation_tier == AttestationTier.A


def test_change_event_accepts_valid_row() -> None:
    ev = ChangeEvent(**_valid_change_event())
    assert ev.change_slot_idx == 16
    assert ev.reason == "baseline_cut"


def test_index_value_accepts_valid_row() -> None:
    iv = IndexValue(**_valid_index_value())
    assert iv.lambda_ == 3.0
    assert iv.index_code == "TPRR_F"


def test_index_value_lambda_serialises_via_alias() -> None:
    iv = IndexValue(**_valid_index_value())
    dumped = iv.model_dump(by_alias=True)
    assert "lambda" in dumped
    assert "lambda_" not in dumped
    assert dumped["lambda"] == 3.0


def test_panel_observation_notes_defaults_to_empty_string() -> None:
    payload = _valid_panel_obs()
    del payload["notes"]
    obs = PanelObservation(**payload)
    assert obs.notes == ""


def test_index_value_notes_defaults_to_empty_string() -> None:
    payload = _valid_index_value()
    del payload["notes"]
    iv = IndexValue(**payload)
    assert iv.notes == ""


def test_panel_observation_rejects_missing_field() -> None:
    payload = _valid_panel_obs()
    del payload["output_price_usd_mtok"]
    with pytest.raises(ValidationError):
        PanelObservation(**payload)


def test_panel_observation_rejects_invalid_tier_code() -> None:
    payload = _valid_panel_obs()
    payload["tier_code"] = "TPRR_XYZ"
    with pytest.raises(ValidationError):
        PanelObservation(**payload)


def test_panel_observation_rejects_invalid_attestation_tier() -> None:
    payload = _valid_panel_obs()
    payload["attestation_tier"] = "Z"
    with pytest.raises(ValidationError):
        PanelObservation(**payload)


def test_change_event_rejects_slot_idx_above_range() -> None:
    payload = _valid_change_event()
    payload["change_slot_idx"] = 32
    with pytest.raises(ValidationError):
        ChangeEvent(**payload)


def test_change_event_rejects_slot_idx_below_range() -> None:
    payload = _valid_change_event()
    payload["change_slot_idx"] = -1
    with pytest.raises(ValidationError):
        ChangeEvent(**payload)


def test_change_event_accepts_slot_idx_at_boundaries() -> None:
    payload = _valid_change_event()
    payload["change_slot_idx"] = 0
    assert ChangeEvent(**payload).change_slot_idx == 0
    payload["change_slot_idx"] = 31
    assert ChangeEvent(**payload).change_slot_idx == 31


def test_change_event_rejects_missing_field() -> None:
    payload = _valid_change_event()
    del payload["old_output_price_usd_mtok"]
    with pytest.raises(ValidationError):
        ChangeEvent(**payload)


def test_index_value_rejects_missing_field() -> None:
    payload = _valid_index_value()
    del payload["raw_value_usd_mtok"]
    with pytest.raises(ValidationError):
        IndexValue(**payload)


def _valid_panel_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2025-01-15", "2025-01-16"]),
            "constituent_id": ["openai/gpt-5-pro", "openai/gpt-5-pro"],
            "contributor_id": ["contrib_alpha", "contrib_beta"],
            "tier_code": ["TPRR_F", "TPRR_F"],
            "attestation_tier": ["A", "A"],
            "input_price_usd_mtok": [15.0, 15.0],
            "output_price_usd_mtok": [75.0, 76.0],
            "volume_mtok_7d": [12_500.0, 8_000.0],
            "source": ["contributor_mock", "contributor_mock"],
            "submitted_at": pd.to_datetime(
                ["2025-01-15 17:00", "2025-01-16 17:00"]
            ),
            "notes": ["", ""],
        }
    )


def _valid_change_event_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_date": pd.to_datetime(["2025-06-03"]),
            "contributor_id": ["contrib_alpha"],
            "constituent_id": ["openai/gpt-5-pro"],
            "change_slot_idx": [16],
            "old_input_price_usd_mtok": [15.0],
            "new_input_price_usd_mtok": [12.0],
            "old_output_price_usd_mtok": [75.0],
            "new_output_price_usd_mtok": [60.0],
            "reason": ["baseline_cut"],
        }
    )


def _valid_index_value_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "as_of_date": pd.to_datetime(["2026-01-01"]),
            "index_code": ["TPRR_F"],
            "version": ["v0_1"],
            "lambda": [3.0],
            "ordering": ["twap_then_weight"],
            "raw_value_usd_mtok": [65.0],
            "index_level": [100.0],
            "n_constituents": [5],
            "n_constituents_active": [5],
            "tier_a_weight_share": [0.7],
            "tier_b_weight_share": [0.2],
            "tier_c_weight_share": [0.1],
            "suspended": [False],
            "notes": [""],
        }
    )


def test_panel_observation_df_accepts_valid_dataframe() -> None:
    df = _valid_panel_df()
    out = PanelObservationDF.validate(df)
    assert out is df


def test_change_event_df_accepts_valid_dataframe() -> None:
    out = ChangeEventDF.validate(_valid_change_event_df())
    assert len(out) == 1


def test_index_value_df_accepts_valid_dataframe() -> None:
    out = IndexValueDF.validate(_valid_index_value_df())
    assert "lambda" in out.columns


def test_panel_observation_df_rejects_missing_column() -> None:
    df = _valid_panel_df().drop(columns=["volume_mtok_7d"])
    with pytest.raises(ValueError, match="missing required columns"):
        PanelObservationDF.validate(df)


def test_panel_observation_df_rejects_null_values() -> None:
    df = _valid_panel_df()
    df.loc[0, "output_price_usd_mtok"] = None
    with pytest.raises(ValueError, match="contains null values"):
        PanelObservationDF.validate(df)


def test_panel_observation_df_rejects_wrong_dtype() -> None:
    df = _valid_panel_df()
    df["input_price_usd_mtok"] = df["input_price_usd_mtok"].astype(str)
    with pytest.raises(ValueError, match="expected dtype family 'float'"):
        PanelObservationDF.validate(df)


def test_change_event_df_rejects_wrong_dtype_on_slot_idx() -> None:
    df = _valid_change_event_df()
    df["change_slot_idx"] = df["change_slot_idx"].astype(float)
    with pytest.raises(ValueError, match="expected dtype family 'int'"):
        ChangeEventDF.validate(df)


def test_panel_observation_df_accepts_categorical_string_columns() -> None:
    df = _valid_panel_df()
    df["tier_code"] = df["tier_code"].astype("category")
    df["contributor_id"] = df["contributor_id"].astype("category")
    out = PanelObservationDF.validate(df)
    assert out is df


def test_panel_observation_df_tolerates_extra_columns() -> None:
    df = _valid_panel_df()
    df["scratch_column"] = ["x", "y"]
    out = PanelObservationDF.validate(df)
    assert "scratch_column" in out.columns


def test_index_value_df_rejects_missing_lambda_column() -> None:
    df = _valid_index_value_df().drop(columns=["lambda"])
    with pytest.raises(ValueError, match="missing required columns"):
        IndexValueDF.validate(df)
