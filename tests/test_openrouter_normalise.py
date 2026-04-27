"""Tests for tprr.reference.openrouter normalisers — Phase 4 Batch B.

Unit-level tests use synthetic JSON fixtures (no network). The match-rate
verification test against real OpenRouter data lives in
tests/test_openrouter_match_rate.py and is run during Batch B development
to surface match rate + price discrepancies; it is fixture-cached after
first run.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
import pytest

from tprr.config import ModelMetadata, ModelRegistry
from tprr.reference.openrouter import (
    enrich_with_rankings_volume,
    normalise_endpoints_to_panel,
    normalise_models_to_panel,
)
from tprr.schema import PanelObservationDF, Tier

AS_OF = date(2026, 4, 27)


def _registry(*entries: tuple[str, Tier]) -> ModelRegistry:
    """Build a minimal ModelRegistry from (constituent_id, tier) tuples."""
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/", 1)[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=4.0,
            )
            for cid, tier in entries
        ]
    )


def _models_payload(*entries: tuple[str, str, str]) -> dict[str, Any]:
    """Build a /models response from (id, prompt_per_token, completion_per_token)."""
    return {
        "data": [
            {
                "id": cid,
                "pricing": {"prompt": prompt, "completion": completion},
            }
            for cid, prompt, completion in entries
        ]
    }


# ---------------------------------------------------------------------------
# normalise_models_to_panel
# ---------------------------------------------------------------------------


def test_normalise_models_basic_happy_path() -> None:
    payload = _models_payload(
        ("openai/gpt-5-pro", "0.000015", "0.000075"),
        ("openai/gpt-5", "0.00001", "0.00004"),
    )
    registry = _registry(
        ("openai/gpt-5-pro", Tier.TPRR_F),
        ("openai/gpt-5", Tier.TPRR_F),
    )
    df = normalise_models_to_panel(payload, registry, AS_OF)

    assert len(df) == 2
    assert set(df["constituent_id"]) == {"openai/gpt-5-pro", "openai/gpt-5"}
    PanelObservationDF.validate(df)


def test_known_per_token_converts_to_per_mtok_via_1e6() -> None:
    """OpenRouter $/token x 1e6 -> $/Mtok. 0.0000050 USD/token -> 5.0 USD/Mtok."""
    payload = _models_payload(("openai/gpt-5", "0.0000050", "0.0000150"))
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)

    assert df.iloc[0]["input_price_usd_mtok"] == pytest.approx(5.0)
    assert df.iloc[0]["output_price_usd_mtok"] == pytest.approx(15.0)


def test_unmatched_registry_models_logged_at_info_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = _models_payload(("openai/gpt-5", "0.00001", "0.00004"))
    registry = _registry(
        ("openai/gpt-5", Tier.TPRR_F),
        ("forward/projected-model", Tier.TPRR_F),
    )

    caplog.set_level(logging.INFO, logger="tprr.reference.openrouter")
    df = normalise_models_to_panel(payload, registry, AS_OF)

    assert len(df) == 1
    assert df.iloc[0]["constituent_id"] == "openai/gpt-5"
    # The unmatched constituent name appears in the log.
    assert "forward/projected-model" in caplog.text


def test_normalise_models_skips_variant_suffixes() -> None:
    payload = _models_payload(
        ("openai/gpt-5-pro", "0.000015", "0.000075"),
        ("openai/gpt-5-pro:free", "0.0", "0.0"),
        ("openai/gpt-5-pro:nitro", "0.00003", "0.00015"),
        ("openai/gpt-5-pro:floor", "0.000010", "0.000050"),
        ("openai/gpt-5-pro:online", "0.00002", "0.0001"),
    )
    registry = _registry(("openai/gpt-5-pro", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)

    # Only the base model matches.
    assert len(df) == 1
    # And it's the un-suffixed price, not a variant's.
    assert df.iloc[0]["input_price_usd_mtok"] == pytest.approx(15.0)
    assert df.iloc[0]["output_price_usd_mtok"] == pytest.approx(75.0)


def test_normalise_models_skips_openrouter_auto() -> None:
    payload = _models_payload(
        ("openrouter/auto", "0.0", "0.0"),
        ("openai/gpt-5", "0.00001", "0.00004"),
    )
    # openrouter/auto is filtered from OR response before matching.
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)
    assert len(df) == 1
    assert df.iloc[0]["constituent_id"] == "openai/gpt-5"


def test_normalise_models_no_matches_returns_empty_valid_df() -> None:
    payload: dict[str, Any] = {"data": []}
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)

    assert len(df) == 0
    PanelObservationDF.validate(df)


def test_normalise_models_all_rows_have_correct_attestation_and_source() -> None:
    payload = _models_payload(("openai/gpt-5", "0.00001", "0.00004"))
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)

    assert (df["attestation_tier"] == "C").all()
    assert (df["source"] == "openrouter_models").all()
    assert (df["contributor_id"] == "openrouter:aggregate").all()


def test_normalise_models_tier_code_from_registry() -> None:
    payload = _models_payload(
        ("openai/gpt-5-pro", "0.000015", "0.000075"),
        ("google/gemini-flash-lite", "0.0000001", "0.0000004"),
    )
    registry = _registry(
        ("openai/gpt-5-pro", Tier.TPRR_F),
        ("google/gemini-flash-lite", Tier.TPRR_E),
    )
    df = normalise_models_to_panel(payload, registry, AS_OF)
    assert dict(zip(df["constituent_id"], df["tier_code"], strict=False)) == {
        "openai/gpt-5-pro": "TPRR_F",
        "google/gemini-flash-lite": "TPRR_E",
    }


def test_normalise_models_volume_initially_zero() -> None:
    payload = _models_payload(("openai/gpt-5", "0.00001", "0.00004"))
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)
    assert (df["volume_mtok_7d"] == 0.0).all()


def test_normalise_models_handles_missing_pricing_field() -> None:
    """A model entry missing pricing fields does not crash; defaults to 0."""
    payload = {"data": [{"id": "openai/gpt-5"}]}  # no pricing
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)
    assert len(df) == 1
    assert df.iloc[0]["input_price_usd_mtok"] == 0.0
    assert df.iloc[0]["output_price_usd_mtok"] == 0.0


def test_normalise_models_handles_non_dict_data_entries() -> None:
    payload: dict[str, Any] = {
        "data": [
            "not a dict",
            {"id": "openai/gpt-5", "pricing": {"prompt": "0.00001", "completion": "0.00004"}},
            None,
        ]
    }
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    df = normalise_models_to_panel(payload, registry, AS_OF)
    assert len(df) == 1
    assert df.iloc[0]["constituent_id"] == "openai/gpt-5"


# ---------------------------------------------------------------------------
# normalise_endpoints_to_panel
# ---------------------------------------------------------------------------


def _endpoints_payload(*providers: tuple[str, str, str]) -> dict[str, Any]:
    """Build endpoints response from (provider_name, prompt, completion)."""
    return {
        "data": {
            "id": "openai/gpt-5",
            "endpoints": [
                {
                    "provider_name": name,
                    "pricing": {"prompt": prompt, "completion": completion},
                }
                for name, prompt, completion in providers
            ],
        }
    }


def test_normalise_endpoints_one_row_per_provider() -> None:
    payload = _endpoints_payload(
        ("OpenAI", "0.00001", "0.00004"),
        ("Azure", "0.000012", "0.000045"),
    )
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)
    assert len(df) == 2


def test_normalise_endpoints_distinct_contributor_id_per_provider() -> None:
    payload = _endpoints_payload(
        ("OpenAI", "0.00001", "0.00004"),
        ("Azure", "0.000012", "0.000045"),
        ("DeepInfra", "0.0000095", "0.000035"),
    )
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)
    assert set(df["contributor_id"]) == {
        "openrouter:openai",
        "openrouter:azure",
        "openrouter:deepinfra",
    }


def test_normalise_endpoints_provider_names_with_spaces_and_underscores() -> None:
    payload = _endpoints_payload(
        ("Lambda Labs", "0.00001", "0.00004"),
        ("fireworks_ai", "0.0000095", "0.000035"),
    )
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)
    assert set(df["contributor_id"]) == {
        "openrouter:lambda-labs",
        "openrouter:fireworks-ai",
    }


def test_normalise_endpoints_attestation_and_source() -> None:
    payload = _endpoints_payload(("OpenAI", "0.00001", "0.00004"))
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)

    assert (df["attestation_tier"] == "C").all()
    assert (df["source"] == "openrouter_endpoints").all()
    assert (df["constituent_id"] == "openai/gpt-5").all()


def test_normalise_endpoints_price_conversion() -> None:
    payload = _endpoints_payload(("OpenAI", "0.0000050", "0.0000150"))
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)
    assert df.iloc[0]["input_price_usd_mtok"] == pytest.approx(5.0)
    assert df.iloc[0]["output_price_usd_mtok"] == pytest.approx(15.0)


def test_normalise_endpoints_tier_code_from_arg() -> None:
    payload = _endpoints_payload(("OpenAI", "0.00001", "0.00004"))
    df = normalise_endpoints_to_panel(
        payload, "openai/gpt-5", Tier.TPRR_S, AS_OF
    )
    assert (df["tier_code"] == "TPRR_S").all()


def test_normalise_endpoints_empty_returns_empty_valid_df() -> None:
    payload: dict[str, Any] = {"data": {"endpoints": []}}
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)
    assert len(df) == 0
    PanelObservationDF.validate(df)


def test_normalise_endpoints_skips_missing_provider_name() -> None:
    payload: dict[str, Any] = {
        "data": {
            "endpoints": [
                {"pricing": {"prompt": "0.00001", "completion": "0.00004"}},
                {
                    "provider_name": "OpenAI",
                    "pricing": {"prompt": "0.00001", "completion": "0.00004"},
                },
            ]
        }
    }
    df = normalise_endpoints_to_panel(payload, "openai/gpt-5", Tier.TPRR_F, AS_OF)
    assert len(df) == 1
    assert df.iloc[0]["contributor_id"] == "openrouter:openai"


# ---------------------------------------------------------------------------
# enrich_with_rankings_volume — Batch B stub
# ---------------------------------------------------------------------------


def test_enrich_with_rankings_volume_returns_dataframe_unchanged() -> None:
    """Batch B: structural pass-through. Volume populated in Batch C."""
    payload = _models_payload(("openai/gpt-5", "0.00001", "0.00004"))
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    panel = normalise_models_to_panel(payload, registry, AS_OF)

    rankings_json: dict[str, Any] = {"data": []}
    enriched = enrich_with_rankings_volume(panel, rankings_json)

    pd.testing.assert_frame_equal(panel, enriched)


def test_enrich_with_rankings_volume_returns_independent_copy() -> None:
    """Mutating the returned df should not affect the input df."""
    payload = _models_payload(("openai/gpt-5", "0.00001", "0.00004"))
    registry = _registry(("openai/gpt-5", Tier.TPRR_F))
    panel = normalise_models_to_panel(payload, registry, AS_OF)

    enriched = enrich_with_rankings_volume(panel, {"data": []})
    enriched.loc[0, "volume_mtok_7d"] = 999.0
    assert panel.loc[0, "volume_mtok_7d"] == 0.0
