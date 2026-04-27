"""Integration tests for scripts/generate_mock_data.py.

Exercises the script end-to-end against the production config (registry,
contributors, scenarios.yaml). Slow by design — the full 480+ day backtest
runs once per test. Tests are kept tight; a single end-to-end run is amortised
across multiple assertions where possible.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from textwrap import dedent

import pandas as pd
import pytest

from tprr.schema import ChangeEventDF, PanelObservationDF

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_mock_data.py"
PRODUCTION_SCENARIOS_YAML = REPO_ROOT / "config" / "scenarios.yaml"

# A backtest end that comfortably covers all production scenario day_offsets
# (latest is tier_reshuffle at day 400; new_model_launch at day 350 extends
# through end). 481 days from 2025-01-01 = 2026-04-27 — matches the
# repository's ambient "today". Pinning here keeps the test reproducible
# regardless of when CI runs.
BACKTEST_START = date(2025, 1, 1)
BACKTEST_END = date(2026, 4, 27)


def _load_script_main() -> object:
    """Load the script as a module without putting scripts/ on sys.path."""
    spec = importlib.util.spec_from_file_location(
        "generate_mock_data_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_mock_data_under_test"] = module
    spec.loader.exec_module(module)
    return module.main  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def end_to_end_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the full script once (clean + 10 scenarios) and reuse output."""
    output_dir = tmp_path_factory.mktemp("generate_mock_data_run")
    main = _load_script_main()
    rc = main(  # type: ignore[operator]
        [
            "--start",
            BACKTEST_START.isoformat(),
            "--end",
            BACKTEST_END.isoformat(),
            "--seed",
            "42",
            "--output-dir",
            str(output_dir),
            "--scenarios",
            str(PRODUCTION_SCENARIOS_YAML),
        ]
    )
    assert rc == 0, f"script exited with {rc}"
    return output_dir


_SCENARIO_IDS = [
    "fat_finger_high",
    "fat_finger_low",
    "stale_quote",
    "correlated_blackout",
    "shock_price_cut",
    "sustained_manipulation",
    "tier_reshuffle",
    "new_model_launch",
    "intraday_spike",
    "regime_shift",
]


def test_end_to_end_writes_clean_artifacts(end_to_end_run: Path) -> None:
    assert (end_to_end_run / "mock_panel_clean_seed42.parquet").exists()
    assert (end_to_end_run / "mock_change_events_clean_seed42.parquet").exists()


def test_end_to_end_writes_per_scenario_panel_and_events(
    end_to_end_run: Path,
) -> None:
    for sid in _SCENARIO_IDS:
        panel_path = end_to_end_run / f"mock_panel_{sid}_seed42.parquet"
        events_path = (
            end_to_end_run / f"mock_change_events_{sid}_seed42.parquet"
        )
        assert panel_path.exists(), f"missing panel for {sid}"
        assert events_path.exists(), f"missing events for {sid}"


def test_end_to_end_writes_per_scenario_manifest(end_to_end_run: Path) -> None:
    manifest_dir = end_to_end_run / "scenarios"
    for sid in _SCENARIO_IDS:
        manifest_path = manifest_dir / f"{sid}_seed42_manifest.json"
        assert manifest_path.exists(), f"missing manifest for {sid}"


def test_end_to_end_total_file_count(end_to_end_run: Path) -> None:
    """3 files per scenario x 10 scenarios = 30 scenario files; +2 clean = 32."""
    panels = list(end_to_end_run.glob("mock_panel_*.parquet"))
    events = list(end_to_end_run.glob("mock_change_events_*.parquet"))
    manifests = list((end_to_end_run / "scenarios").glob("*_manifest.json"))
    assert len(panels) == 11  # 10 scenarios + 1 clean
    assert len(events) == 11
    assert len(manifests) == 10


@pytest.mark.parametrize("sid", _SCENARIO_IDS)
def test_scenario_panel_validates_schema(end_to_end_run: Path, sid: str) -> None:
    panel = pd.read_parquet(end_to_end_run / f"mock_panel_{sid}_seed42.parquet")
    PanelObservationDF.validate(panel)


@pytest.mark.parametrize("sid", _SCENARIO_IDS)
def test_scenario_events_validate_schema(end_to_end_run: Path, sid: str) -> None:
    events = pd.read_parquet(
        end_to_end_run / f"mock_change_events_{sid}_seed42.parquet"
    )
    ChangeEventDF.validate(events)


@pytest.mark.parametrize("sid", _SCENARIO_IDS)
def test_scenario_manifest_well_formed(end_to_end_run: Path, sid: str) -> None:
    manifest_path = (
        end_to_end_run / "scenarios" / f"{sid}_seed42_manifest.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["scenario_id"] == sid
    assert payload["seed"] == 42
    assert "operations_applied" in payload
    assert isinstance(payload["operations_applied"], list)
    assert len(payload["operations_applied"]) >= 1


def test_clean_artifacts_unchanged_when_scenarios_provided(
    end_to_end_run: Path,
) -> None:
    """Clean panel matches what running without --scenarios would have produced."""
    main = _load_script_main()
    no_scenarios_dir = end_to_end_run.parent / "no_scenarios"
    no_scenarios_dir.mkdir(exist_ok=True)
    rc = main(  # type: ignore[operator]
        [
            "--start",
            BACKTEST_START.isoformat(),
            "--end",
            BACKTEST_END.isoformat(),
            "--seed",
            "42",
            "--output-dir",
            str(no_scenarios_dir),
        ]
    )
    assert rc == 0

    clean_with = pd.read_parquet(
        end_to_end_run / "mock_panel_clean_seed42.parquet"
    )
    clean_without = pd.read_parquet(
        no_scenarios_dir / "mock_panel_clean_seed42.parquet"
    )
    pd.testing.assert_frame_equal(clean_with, clean_without)


def test_end_to_end_preflight_collision_fails_loudly(
    end_to_end_run: Path, tmp_path: Path,
) -> None:
    """A rigged scenario targeting a known event day fails pre-flight loudly.

    Empirical approach: read the clean events from the module-scoped run,
    find the earliest event for ``contrib_atlas x openai/gpt-5-mini``, rig
    a fat_finger scenario at exactly that day, and run a short pipeline
    that covers the collision day. The pre-flight check must raise.
    """
    events = pd.read_parquet(
        end_to_end_run / "mock_change_events_clean_seed42.parquet"
    )
    atlas_mini = events[
        (events["contributor_id"] == "contrib_atlas")
        & (events["constituent_id"] == "openai/gpt-5-mini")
    ].sort_values("event_date")
    assert len(atlas_mini) > 0, (
        "fixture must produce at least one event for contrib_atlas x "
        "openai/gpt-5-mini for the collision test to be meaningful"
    )
    collision_date = pd.Timestamp(atlas_mini.iloc[0]["event_date"]).date()
    collision_day_offset = (collision_date - BACKTEST_START).days

    short_end = BACKTEST_START + timedelta(days=collision_day_offset + 10)
    rigged_yaml = tmp_path / "scenarios_rigged.yaml"
    rigged_yaml.write_text(
        dedent(
            f"""\
            scenarios:
              - id: fat_finger_rigged
                kind: fat_finger
                description: "intentionally non-clear day for pre-flight test"
                tier: TPRR_S
                target:
                  contributor_id: contrib_atlas
                  constituent_id: openai/gpt-5-mini
                timing:
                  day_offset: {collision_day_offset}
                  slot: 16
                magnitude:
                  multiplier: 10.0
                revert:
                  after_slots: 1
            """
        ),
        encoding="utf-8",
    )

    rigged_output_dir = tmp_path / "rigged_out"
    main = _load_script_main()
    with pytest.raises(
        ValueError, match="pre-flight event-clear-day check FAILED"
    ):
        main(  # type: ignore[operator]
            [
                "--start",
                BACKTEST_START.isoformat(),
                "--end",
                short_end.isoformat(),
                "--seed",
                "42",
                "--output-dir",
                str(rigged_output_dir),
                "--scenarios",
                str(rigged_yaml),
            ]
        )
