"""Canonical data contracts for the TPRR Index MVP.

Pydantic record types and pandas DataFrame validators for the three core data
shapes that flow through the pipeline:

- PanelObservation: daily posted price per contributor per model
- ChangeEvent:      sparse intraday price change record
- IndexValue:       daily fix output

Schema changes here require an entry in docs/decision_log.md (CLAUDE.md
non-negotiable #1).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar

import pandas as pd
from pandas.api import types as pdt
from pydantic import BaseModel, ConfigDict, Field


class Tier(StrEnum):
    """TPRR tier classification (methodology Section 3.2)."""

    TPRR_F = "TPRR_F"
    TPRR_S = "TPRR_S"
    TPRR_E = "TPRR_E"


class AttestationTier(StrEnum):
    """Volume attestation tier (methodology Section 3.3.2)."""

    A = "A"
    B = "B"
    C = "C"


class PanelObservation(BaseModel):
    """Daily posted price per contributor per model.

    On change-event days the price fields hold the daily TWAP rather than the
    post-change price, per the sparse change-event storage model.
    """

    observation_date: date
    constituent_id: str
    contributor_id: str
    tier_code: Tier
    attestation_tier: AttestationTier
    input_price_usd_mtok: float
    output_price_usd_mtok: float
    volume_mtok_7d: float
    source: str
    submitted_at: datetime
    notes: str = ""


class ChangeEvent(BaseModel):
    """Sparse intraday price change record.

    Slots ``[0, change_slot_idx)`` use the old price; slots
    ``[change_slot_idx, 32)`` use the new price.
    """

    event_date: date
    contributor_id: str
    constituent_id: str
    change_slot_idx: int = Field(ge=0, le=31)
    old_input_price_usd_mtok: float
    new_input_price_usd_mtok: float
    old_output_price_usd_mtok: float
    new_output_price_usd_mtok: float
    reason: str


class IndexValue(BaseModel):
    """Daily fix output — one row per (date, index_code, version, ordering).

    The ``n_constituents_a/b/c`` and ``suspension_reason`` fields were added in
    Phase 7 for cross-tier dominance characterisation (decision_log.md
    2026-04-30 "Phase 7 IndexValue schema additions"). The
    ``n_constituents_a + b + c == n_constituents_active`` invariant is
    enforced in ``tprr.index.aggregation``, not at the pydantic layer —
    pydantic field-level validators don't compose well across multiple
    columns. ``suspension_reason`` is free ``str`` here; the
    ``SuspensionReason`` StrEnum in ``tprr.index.aggregation`` defines the
    closed value set producers use (``insufficient_constituents``,
    ``tier_data_unavailable``, ``quality_gate_cascade``).
    """

    model_config = ConfigDict(populate_by_name=True)

    as_of_date: date
    index_code: str
    version: str
    lambda_: float = Field(alias="lambda")
    ordering: str
    raw_value_usd_mtok: float
    index_level: float
    n_constituents: int
    n_constituents_active: int
    n_constituents_a: int = Field(ge=0)
    n_constituents_b: int = Field(ge=0)
    n_constituents_c: int = Field(ge=0)
    tier_a_weight_share: float
    tier_b_weight_share: float
    tier_c_weight_share: float
    suspended: bool
    suspension_reason: str = ""
    notes: str = ""


def _check_dtype_family(
    series: pd.Series[Any],  # column element types vary by family being checked
    family: str,
    col_name: str,
    schema_name: str,
) -> None:
    """Raise if ``series`` does not belong to the expected dtype ``family``.

    Families: ``datetime``, ``int``, ``float``, ``string``, ``bool``. ``string``
    accepts object, pandas ``string``, or ``category`` dtypes (CLAUDE.md
    permits categorical for tier_code, contributor_id, etc.).
    """
    ok: bool
    if family == "datetime":
        ok = pdt.is_datetime64_any_dtype(series)
    elif family == "int":
        ok = pdt.is_integer_dtype(series)
    elif family == "float":
        ok = pdt.is_float_dtype(series)
    elif family == "string":
        ok = pdt.is_string_dtype(series) or isinstance(
            series.dtype, pd.CategoricalDtype
        )
    elif family == "bool":
        ok = pdt.is_bool_dtype(series)
    else:
        raise ValueError(f"{schema_name}: unknown dtype family '{family}'")
    if not ok:
        raise ValueError(
            f"{schema_name}: column '{col_name}' has dtype {series.dtype!r}, "
            f"expected dtype family '{family}'"
        )


class _DFValidator:
    """Base class for column / dtype / non-null DataFrame validators."""

    SCHEMA_NAME: ClassVar[str] = ""
    REQUIRED_COLUMNS: ClassVar[dict[str, str]] = {}

    @classmethod
    def validate(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Validate ``df`` matches the schema. Returns ``df`` on success.

        Checks: required columns present, no nulls in any required column,
        each required column belongs to the expected dtype family. Extra
        columns beyond the schema are tolerated.
        """
        missing = set(cls.REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(
                f"{cls.SCHEMA_NAME}: missing required columns: {sorted(missing)}"
            )
        for col, family in cls.REQUIRED_COLUMNS.items():
            if df[col].isna().any():
                raise ValueError(
                    f"{cls.SCHEMA_NAME}: column '{col}' contains null values"
                )
            _check_dtype_family(df[col], family, col, cls.SCHEMA_NAME)
        return df


class PanelObservationDF(_DFValidator):
    """DataFrame validator for PanelObservation rows."""

    SCHEMA_NAME: ClassVar[str] = "PanelObservationDF"
    REQUIRED_COLUMNS: ClassVar[dict[str, str]] = {
        "observation_date": "datetime",
        "constituent_id": "string",
        "contributor_id": "string",
        "tier_code": "string",
        "attestation_tier": "string",
        "input_price_usd_mtok": "float",
        "output_price_usd_mtok": "float",
        "volume_mtok_7d": "float",
        "source": "string",
        "submitted_at": "datetime",
        "notes": "string",
    }


class ChangeEventDF(_DFValidator):
    """DataFrame validator for ChangeEvent rows."""

    SCHEMA_NAME: ClassVar[str] = "ChangeEventDF"
    REQUIRED_COLUMNS: ClassVar[dict[str, str]] = {
        "event_date": "datetime",
        "contributor_id": "string",
        "constituent_id": "string",
        "change_slot_idx": "int",
        "old_input_price_usd_mtok": "float",
        "new_input_price_usd_mtok": "float",
        "old_output_price_usd_mtok": "float",
        "new_output_price_usd_mtok": "float",
        "reason": "string",
    }


class IndexValueDF(_DFValidator):
    """DataFrame validator for IndexValue rows."""

    SCHEMA_NAME: ClassVar[str] = "IndexValueDF"
    REQUIRED_COLUMNS: ClassVar[dict[str, str]] = {
        "as_of_date": "datetime",
        "index_code": "string",
        "version": "string",
        "lambda": "float",
        "ordering": "string",
        "raw_value_usd_mtok": "float",
        "index_level": "float",
        "n_constituents": "int",
        "n_constituents_active": "int",
        "n_constituents_a": "int",
        "n_constituents_b": "int",
        "n_constituents_c": "int",
        "tier_a_weight_share": "float",
        "tier_b_weight_share": "float",
        "tier_c_weight_share": "float",
        "suspended": "bool",
        "suspension_reason": "string",
        "notes": "string",
    }
