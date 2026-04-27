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
# enrich_with_rankings_volume — Batch C model-level matching
# ---------------------------------------------------------------------------


def _registry_with_or(
    *entries: tuple[str, Tier, str | None, str | None],
) -> ModelRegistry:
    """Build a ModelRegistry with explicit openrouter_(author, slug) per entry."""
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/", 1)[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=1.0,
                baseline_output_price_usd_mtok=4.0,
                openrouter_author=or_author,
                openrouter_slug=or_slug,
            )
            for cid, tier, or_author, or_slug in entries
        ]
    )


def _rankings_payload(
    *entries: tuple[str, str, int],
) -> dict[str, Any]:
    """Build a rankings payload from (author, slug, tokens) tuples."""
    return {
        "models": [
            {
                "rank": i + 1,
                "model_id": f"{author}/{slug}",
                "name": f"{author}/{slug}",
                "author": author,
                "slug": slug,
                "tokens": tokens,
                "share_pct": 1.0,
            }
            for i, (author, slug, tokens) in enumerate(entries)
        ]
    }


def test_enrich_matches_deepseek_via_date_suffix_stripping() -> None:
    """Rankings 'deepseek/deepseek-v3.2-20251201' matches registry slug 'deepseek-v3.2'."""
    registry = _registry_with_or(
        ("deepseek/deepseek-v3-2", Tier.TPRR_E, "deepseek", "deepseek-v3.2"),
    )
    panel_payload = _models_payload(
        ("deepseek/deepseek-v3.2", "0.0000003", "0.0000010"),
    )
    # Patch the OR id so the panel matches via constituent_id mapping
    or_models = panel_payload["data"]
    or_models[0]["id"] = "deepseek/deepseek-v3.2"  # the registry slug
    panel = normalise_models_to_panel(panel_payload, registry, AS_OF)
    assert len(panel) == 1

    rankings = _rankings_payload(
        ("deepseek", "deepseek-v3.2-20251201", 52_118_570_742),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)

    deepseek_row = enriched[
        enriched["constituent_id"] == "deepseek/deepseek-v3-2"
    ].iloc[0]
    assert deepseek_row["volume_mtok_7d"] == pytest.approx(52_118.570742)
    assert deepseek_row["notes"] == ""  # no flag on matched rows


def test_enrich_unmatched_rows_get_zero_volume_and_no_rankings_note() -> None:
    """All 14-of-15 mapped constituents without rankings match get zero + flag."""
    registry = _registry_with_or(
        ("deepseek/deepseek-v3-2", Tier.TPRR_E, "deepseek", "deepseek-v3.2"),
        ("openai/gpt-5", Tier.TPRR_F, "openai", "gpt-5"),
        ("anthropic/claude-haiku-4-5", Tier.TPRR_S, "anthropic", "claude-haiku-4.5"),
    )
    or_payload = {
        "data": [
            {
                "id": "deepseek/deepseek-v3.2",
                "pricing": {"prompt": "0.0000003", "completion": "0.0000010"},
            },
            {
                "id": "openai/gpt-5",
                "pricing": {"prompt": "0.00001", "completion": "0.00004"},
            },
            {
                "id": "anthropic/claude-haiku-4.5",
                "pricing": {"prompt": "0.000001", "completion": "0.000005"},
            },
        ]
    }
    panel = normalise_models_to_panel(or_payload, registry, AS_OF)
    assert len(panel) == 3

    rankings = _rankings_payload(
        ("deepseek", "deepseek-v3.2-20251201", 52_118_570_742),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)

    matched = enriched[enriched["constituent_id"] == "deepseek/deepseek-v3-2"]
    assert (matched["volume_mtok_7d"] > 0).all()
    assert (matched["notes"] == "").all()

    unmatched = enriched[
        enriched["constituent_id"].isin(["openai/gpt-5", "anthropic/claude-haiku-4-5"])
    ]
    assert (unmatched["volume_mtok_7d"] == 0.0).all()
    assert (unmatched["notes"] == "no_rankings_data").all()


@pytest.mark.parametrize(
    "rankings_slug,registry_slug",
    [
        ("deepseek-v3.2-20251201", "deepseek-v3.2"),
        ("kimi-k2.6-20260420", "kimi-k2.6"),
        ("gemini-3-flash-preview-20251217", "gemini-3-flash-preview"),
        ("claude-4.7-opus-20260416", "claude-4.7-opus"),
    ],
)
def test_enrich_strips_observed_date_suffix_patterns(
    rankings_slug: str, registry_slug: str
) -> None:
    """Date-suffix stripping handles all observed -YYYYMMDD patterns."""
    registry = _registry_with_or(
        ("test/constituent", Tier.TPRR_F, "test-author", registry_slug),
    )
    or_payload = {
        "data": [
            {
                "id": "test/constituent",
                "pricing": {"prompt": "0.00001", "completion": "0.00004"},
            }
        ]
    }
    # Patch the registry-to-OR matching: align constituent_id with what the
    # /models response provides (we control both above).
    panel = normalise_models_to_panel(or_payload, registry, AS_OF)
    # /models matcher uses (openrouter_author, openrouter_slug) primary; the
    # constituent gets matched to /models id "test/constituent" via fallback.
    # Force-populate the panel with a matched row instead, since we control
    # both sides:
    panel = _build_synthetic_panel_row(
        constituent_id="test/constituent", tier=Tier.TPRR_F
    )

    rankings = _rankings_payload(("test-author", rankings_slug, 1_000_000_000))
    enriched = enrich_with_rankings_volume(panel, rankings, registry)
    assert enriched.iloc[0]["volume_mtok_7d"] == pytest.approx(1_000.0)


def _build_synthetic_panel_row(
    *, constituent_id: str, tier: Tier
) -> pd.DataFrame:
    """Build a single-row Tier C panel for tests that bypass /models matching."""
    return pd.DataFrame(
        {
            "observation_date": pd.Series(
                [pd.Timestamp(AS_OF)], dtype="datetime64[ns]"
            ),
            "constituent_id": pd.Series([constituent_id], dtype="object"),
            "contributor_id": pd.Series(["openrouter:aggregate"], dtype="object"),
            "tier_code": pd.Series([tier.value], dtype="object"),
            "attestation_tier": pd.Series(["C"], dtype="object"),
            "input_price_usd_mtok": pd.Series([1.0], dtype="float64"),
            "output_price_usd_mtok": pd.Series([4.0], dtype="float64"),
            "volume_mtok_7d": pd.Series([0.0], dtype="float64"),
            "source": pd.Series(["openrouter_models"], dtype="object"),
            "submitted_at": pd.Series(
                [pd.Timestamp(AS_OF)], dtype="datetime64[ns]"
            ),
            "notes": pd.Series([""], dtype="object"),
        }
    )


def test_enrich_skips_variant_suffixed_rankings_entries() -> None:
    """Rankings entries ending in :free / :nitro / etc. are filtered out."""
    registry = _registry_with_or(
        ("test/foo", Tier.TPRR_E, "test", "foo-v1"),
    )
    panel = _build_synthetic_panel_row(
        constituent_id="test/foo", tier=Tier.TPRR_E
    )
    rankings = _rankings_payload(
        ("test", "foo-v1-20260101:free", 999_999_999),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)
    # Variant-suffixed entry filtered → no match → zero + note
    assert enriched.iloc[0]["volume_mtok_7d"] == 0.0
    assert enriched.iloc[0]["notes"] == "no_rankings_data"


def test_enrich_unknown_rankings_entries_silently_skipped() -> None:
    """Rankings entries with no registry match don't raise or get flagged."""
    registry = _registry_with_or(
        ("test/foo", Tier.TPRR_E, "test", "foo-v1"),
    )
    panel = _build_synthetic_panel_row(
        constituent_id="test/foo", tier=Tier.TPRR_E
    )
    rankings = _rankings_payload(
        ("unknown-author", "unknown-slug-20260101", 999_999_999),
        ("another", "another-slug", 111_111_111),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)
    # Our registry constituent gets no_rankings_data (not in rankings).
    # The unknown rankings entries are silently ignored — no errors.
    assert enriched.iloc[0]["volume_mtok_7d"] == 0.0
    assert enriched.iloc[0]["notes"] == "no_rankings_data"


def test_enrich_token_to_mtok_conversion_is_divide_by_1e6() -> None:
    """tokens / 1e6 = mtok. 1B tokens = 1000 mtok."""
    registry = _registry_with_or(
        ("test/foo", Tier.TPRR_E, "test", "foo-v1"),
    )
    panel = _build_synthetic_panel_row(
        constituent_id="test/foo", tier=Tier.TPRR_E
    )
    rankings = _rankings_payload(
        ("test", "foo-v1-20260101", 1_000_000_000),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)
    assert enriched.iloc[0]["volume_mtok_7d"] == pytest.approx(1_000.0)


def test_enrich_logs_match_count_at_info_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = _registry_with_or(
        ("test/matched", Tier.TPRR_E, "test", "matched-v1"),
        ("test/unmatched", Tier.TPRR_E, "test", "unmatched-v1"),
    )
    panel = pd.concat(
        [
            _build_synthetic_panel_row(
                constituent_id="test/matched", tier=Tier.TPRR_E
            ),
            _build_synthetic_panel_row(
                constituent_id="test/unmatched", tier=Tier.TPRR_E
            ),
        ],
        ignore_index=True,
    )
    rankings = _rankings_payload(
        ("test", "matched-v1-20260101", 1_000_000_000),
    )
    caplog.set_level(logging.INFO, logger="tprr.reference.openrouter")
    enrich_with_rankings_volume(panel, rankings, registry)

    assert "1 of 2 Tier C constituents matched to rankings" in caplog.text


def test_enrich_returns_independent_copy() -> None:
    """Mutating the returned df should not affect the input df."""
    registry = _registry_with_or(
        ("test/foo", Tier.TPRR_E, "test", "foo-v1"),
    )
    panel = _build_synthetic_panel_row(
        constituent_id="test/foo", tier=Tier.TPRR_E
    )
    enriched = enrich_with_rankings_volume(panel, {"models": []}, registry)
    enriched.loc[0, "volume_mtok_7d"] = 999.0
    assert panel.loc[0, "volume_mtok_7d"] == 0.0


def test_enrich_non_tier_c_rows_pass_through_unchanged() -> None:
    """Defensive: rows with attestation_tier != 'C' are untouched."""
    registry = _registry_with_or(
        ("test/foo", Tier.TPRR_E, "test", "foo-v1"),
    )
    panel = _build_synthetic_panel_row(
        constituent_id="test/foo", tier=Tier.TPRR_E
    )
    panel.loc[0, "attestation_tier"] = "A"  # pretend this is a Tier A row
    panel.loc[0, "volume_mtok_7d"] = 50.0  # pretend it has its own volume
    rankings = _rankings_payload(
        ("test", "foo-v1-20260101", 1_000_000_000),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)
    # Volume preserved, no notes flag added
    assert enriched.iloc[0]["volume_mtok_7d"] == 50.0
    assert enriched.iloc[0]["notes"] == ""


def test_enrich_resulting_panel_validates_schema() -> None:
    registry = _registry_with_or(
        ("test/matched", Tier.TPRR_E, "test", "matched-v1"),
        ("test/unmatched", Tier.TPRR_E, "test", "unmatched-v1"),
    )
    panel = pd.concat(
        [
            _build_synthetic_panel_row(
                constituent_id="test/matched", tier=Tier.TPRR_E
            ),
            _build_synthetic_panel_row(
                constituent_id="test/unmatched", tier=Tier.TPRR_E
            ),
        ],
        ignore_index=True,
    )
    rankings = _rankings_payload(
        ("test", "matched-v1-20260101", 1_000_000_000),
    )
    enriched = enrich_with_rankings_volume(panel, rankings, registry)
    PanelObservationDF.validate(enriched)


def test_enrich_empty_rankings_models_list_marks_all_unmatched() -> None:
    registry = _registry_with_or(
        ("test/foo", Tier.TPRR_E, "test", "foo-v1"),
    )
    panel = _build_synthetic_panel_row(
        constituent_id="test/foo", tier=Tier.TPRR_E
    )
    enriched = enrich_with_rankings_volume(panel, {"models": []}, registry)
    assert enriched.iloc[0]["volume_mtok_7d"] == 0.0
    assert enriched.iloc[0]["notes"] == "no_rankings_data"
