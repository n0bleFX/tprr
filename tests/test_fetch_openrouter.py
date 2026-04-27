"""Integration tests for scripts/fetch_openrouter.py.

Module-scoped end-to-end fixture: runs the script once against the
production config + cached OpenRouter responses (cache populated during
Phase 4 development), verifies output shape, summary, and schema.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tprr.schema import PanelObservationDF

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "fetch_openrouter.py"
AS_OF = date(2026, 4, 27)


def _load_script_main() -> object:
    spec = importlib.util.spec_from_file_location(
        "fetch_openrouter_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_openrouter_under_test"] = module
    spec.loader.exec_module(module)
    return module.main  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def end_to_end_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the script once and reuse output across all tests."""
    output_dir = tmp_path_factory.mktemp("fetch_openrouter_run")
    main = _load_script_main()
    rc = main(  # type: ignore[operator]
        [
            "--as-of",
            AS_OF.isoformat(),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert rc == 0, f"script exited with {rc}"
    return output_dir


def test_writes_panel_parquet(end_to_end_run: Path) -> None:
    panel_path = end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    assert panel_path.exists()


def test_panel_validates_schema(end_to_end_run: Path) -> None:
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    PanelObservationDF.validate(panel)


def test_all_rows_are_tier_c(end_to_end_run: Path) -> None:
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    assert (panel["attestation_tier"] == "C").all()


def test_aggregate_rows_have_openrouter_aggregate_contributor_id(
    end_to_end_run: Path,
) -> None:
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    aggregate_rows = panel[panel["source"] == "openrouter_models"]
    assert len(aggregate_rows) > 0
    assert (aggregate_rows["contributor_id"] == "openrouter:aggregate").all()


def test_endpoint_rows_have_per_provider_contributor_ids(
    end_to_end_run: Path,
) -> None:
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    endpoint_rows = panel[panel["source"] == "openrouter_endpoints"]
    assert len(endpoint_rows) > 0
    # Each contributor_id starts with 'openrouter:' and is NOT 'openrouter:aggregate'
    for cid in endpoint_rows["contributor_id"].unique():
        assert cid.startswith("openrouter:")
        assert cid != "openrouter:aggregate"


def test_match_rate_15_of_16(end_to_end_run: Path) -> None:
    """15 of 16 registry constituents produce an aggregate row."""
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    aggregate_rows = panel[panel["source"] == "openrouter_models"]
    assert aggregate_rows["constituent_id"].nunique() == 15


def test_meta_llama_4_70b_hosted_unmatched(end_to_end_run: Path) -> None:
    """The one documented unmatched constituent has no panel row."""
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    assert "meta/llama-4-70b-hosted" not in set(panel["constituent_id"])


def test_only_aggregate_rows_carry_rankings_volume(end_to_end_run: Path) -> None:
    """Per-provider endpoint rows carry volume_mtok_7d = 0; only aggregate
    rows can carry rankings-derived volume.

    Rationale (decision-log 2026-04-28 'Tier C rankings sparseness'):
    rankings is a constituent-level aggregate; assigning it to all 1+N
    Tier C rows for a constituent would double-count.
    """
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    endpoint_rows = panel[panel["source"] == "openrouter_endpoints"]
    assert (endpoint_rows["volume_mtok_7d"] == 0).all()


def test_at_least_one_constituent_has_rankings_derived_volume(
    end_to_end_run: Path,
) -> None:
    """deepseek/deepseek-v3-2 should have non-zero rankings-derived volume."""
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    deepseek_aggregate = panel[
        (panel["constituent_id"] == "deepseek/deepseek-v3-2")
        & (panel["source"] == "openrouter_models")
    ]
    assert len(deepseek_aggregate) == 1
    assert deepseek_aggregate.iloc[0]["volume_mtok_7d"] > 0


def test_unmatched_aggregate_rows_have_no_rankings_data_flag(
    end_to_end_run: Path,
) -> None:
    """Aggregate rows for constituents not in rankings get the flag in notes."""
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    unmatched_aggregate = panel[
        (panel["source"] == "openrouter_models")
        & (panel["volume_mtok_7d"] == 0)
    ]
    assert len(unmatched_aggregate) > 0
    assert (unmatched_aggregate["notes"] == "no_rankings_data").all()


def test_prices_post_x1e6_are_reasonable_magnitude(end_to_end_run: Path) -> None:
    """Spot check: GPT-5 output ~$10/Mtok, not 0.00001 or 10000000."""
    panel = pd.read_parquet(
        end_to_end_run / f"openrouter_panel_{AS_OF.isoformat()}.parquet"
    )
    gpt5_aggregate = panel[
        (panel["constituent_id"] == "openai/gpt-5")
        & (panel["source"] == "openrouter_models")
    ]
    assert len(gpt5_aggregate) == 1
    output_price = gpt5_aggregate.iloc[0]["output_price_usd_mtok"]
    # Reasonable magnitude check: $0.10 - $1000/Mtok
    assert 0.1 < output_price < 1000.0
