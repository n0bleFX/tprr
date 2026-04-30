"""Tests for tprr.index.quality — slot-level gate, continuity, staleness, suspension.

Coverage maps to Phase 3 outlier scenarios:
- Scenario 1 (fat_finger_high): apply_slot_level_gate fires on the post-spike
  slots; TWAP is shielded by exclusion.
- Scenario 3 (stale_quote): apply_staleness_rule flags rows where the price
  has held for max_stale_days+1 consecutive panel days.
- Scenario 4 (contributor_blackout): compute_consecutive_day_suspensions
  emits a suspension when a (contributor, constituent) accumulates
  threshold_days consecutive any-slot-fire days.
- Scenario 9 (intraday_spike): apply_slot_level_gate fires on multiple slots
  inside the spike window when fed a two-event day.

Plus edge cases at the gate's parameter boundaries (14% / 16%, first-5-days
insufficient history, run-length resets, sticky suspension semantics).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from tprr.index.quality import (
    apply_continuity_check,
    apply_slot_level_gate,
    apply_staleness_rule,
    check_min_constituents,
    compute_consecutive_day_suspensions,
    compute_suspension_intervals,
)
from tprr.schema import AttestationTier, Tier

DAY = pd.Timedelta(days=1)


# ---------------------------------------------------------------------------
# Test fixtures (handcrafted so each test is self-contained)
# ---------------------------------------------------------------------------


def _panel_row(
    *,
    date: pd.Timestamp,
    contributor_id: str = "contrib_a",
    constituent_id: str = "openai/gpt-5",
    output_price: float = 50.0,
    input_price: float = 10.0,
    attestation_tier: str = AttestationTier.A.value,
    tier_code: str = Tier.TPRR_F.value,
) -> dict[str, Any]:
    return {
        "observation_date": date,
        "contributor_id": contributor_id,
        "constituent_id": constituent_id,
        "output_price_usd_mtok": output_price,
        "input_price_usd_mtok": input_price,
        "attestation_tier": attestation_tier,
        "tier_code": tier_code,
    }


def _series_panel(
    prices: list[float],
    *,
    start: str = "2025-01-01",
    contributor_id: str = "contrib_a",
    constituent_id: str = "openai/gpt-5",
    attestation_tier: str = AttestationTier.A.value,
    tier_code: str = Tier.TPRR_F.value,
) -> pd.DataFrame:
    """Build a panel of N consecutive days for one (contributor, constituent)."""
    rows = []
    for i, p in enumerate(prices):
        rows.append(
            _panel_row(
                date=pd.Timestamp(start) + i * DAY,
                contributor_id=contributor_id,
                constituent_id=constituent_id,
                output_price=p,
                attestation_tier=attestation_tier,
                tier_code=tier_code,
            )
        )
    return pd.DataFrame(rows)


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_date",
            "contributor_id",
            "constituent_id",
            "change_slot_idx",
            "old_input_price_usd_mtok",
            "new_input_price_usd_mtok",
            "old_output_price_usd_mtok",
            "new_output_price_usd_mtok",
            "reason",
        ]
    )


def _event(
    *,
    date: pd.Timestamp,
    slot: int,
    old_out: float,
    new_out: float,
    contributor_id: str = "contrib_a",
    constituent_id: str = "openai/gpt-5",
) -> dict[str, Any]:
    return {
        "event_date": date,
        "contributor_id": contributor_id,
        "constituent_id": constituent_id,
        "change_slot_idx": slot,
        "old_input_price_usd_mtok": old_out / 5.0,
        "new_input_price_usd_mtok": new_out / 5.0,
        "old_output_price_usd_mtok": old_out,
        "new_output_price_usd_mtok": new_out,
        "reason": "outlier_injection",
    }


# ---------------------------------------------------------------------------
# apply_slot_level_gate
# ---------------------------------------------------------------------------


def test_slot_level_gate_constant_prices_no_exclusions() -> None:
    """Constant 50.0 across 10 days → trailing avg = 50.0, no slot deviates."""
    panel = _series_panel([50.0] * 10)
    excl = apply_slot_level_gate(panel, _empty_events())
    assert excl.empty
    assert list(excl.columns) == ["contributor_id", "constituent_id", "date", "slot_idx"]


def test_slot_level_gate_first_five_days_skipped_insufficient_history() -> None:
    """Days 1-5 have <5 prior panel-recorded days; gate cannot fire on them.

    Day 6 sees a +50% jump from day 5; with constant prior it has trailing
    avg = 50.0 and posted = 75.0 (50% deviation > 15%) -> all 32 slots fire.
    Days 1-5 emit nothing because no trailing average is computable.
    """
    panel = _series_panel([50.0] * 5 + [75.0])
    excl = apply_slot_level_gate(panel, _empty_events())
    # All 32 firings should be on day 6 only.
    assert (excl["date"] == pd.Timestamp("2025-01-06")).all()
    assert len(excl) == 32


def test_slot_level_gate_14pct_passes_16pct_fires() -> None:
    """Boundary check: 14% deviation must NOT fire; 16% must fire.

    Trailing avg over 5 prior days @ 50.0 = 50.0. Day-6 posted at 57.0
    (14% above) → all-32 slots within threshold → no firings. Day-6 posted
    at 58.0 (16% above) → 32 firings.
    """
    panel14 = _series_panel([50.0] * 5 + [57.0])
    excl14 = apply_slot_level_gate(panel14, _empty_events())
    assert excl14.empty

    panel16 = _series_panel([50.0] * 5 + [58.0])
    excl16 = apply_slot_level_gate(panel16, _empty_events())
    assert len(excl16) == 32


def test_slot_level_gate_fat_finger_scenario_1() -> None:
    """Scenario 1 - fat_finger_high: a single intraday change to 10x price
    starting at slot 16 fires every post-event slot. The pre-spike slots
    (0..15) carry the old (in-line) price and stay within threshold.
    """
    panel = pd.DataFrame(
        [
            _panel_row(date=pd.Timestamp("2025-01-01") + i * DAY, output_price=50.0)
            for i in range(5)
        ]
        + [
            _panel_row(date=pd.Timestamp("2025-01-06"), output_price=500.0),
        ]
    )
    events = pd.DataFrame(
        [_event(date=pd.Timestamp("2025-01-06"), slot=16, old_out=50.0, new_out=500.0)]
    )
    excl = apply_slot_level_gate(panel, events)
    fired = sorted(excl[excl["date"] == pd.Timestamp("2025-01-06")]["slot_idx"].tolist())
    assert fired == list(range(16, 32))


def test_slot_level_gate_intraday_spike_scenario_9() -> None:
    """Scenario 9 — intraday_spike: two events on the same day form a
    bounded spike window. Only the in-spike slots fire; pre/post slots
    are at the in-line price.
    """
    panel = pd.DataFrame(
        [
            _panel_row(date=pd.Timestamp("2025-01-01") + i * DAY, output_price=50.0)
            for i in range(5)
        ]
        + [
            _panel_row(date=pd.Timestamp("2025-01-06"), output_price=50.0),
        ]
    )
    events = pd.DataFrame(
        [
            _event(date=pd.Timestamp("2025-01-06"), slot=10, old_out=50.0, new_out=200.0),
            _event(date=pd.Timestamp("2025-01-06"), slot=13, old_out=200.0, new_out=50.0),
        ]
    )
    excl = apply_slot_level_gate(panel, events)
    fired = sorted(excl[excl["date"] == pd.Timestamp("2025-01-06")]["slot_idx"].tolist())
    assert fired == [10, 11, 12]


def test_slot_level_gate_ignores_tier_b_and_tier_c() -> None:
    """Tier B / Tier C rows have no slot dimension; gate must not process them
    even when their posted price differs wildly from rolling history.
    """
    panel = _series_panel(
        [50.0] * 5 + [200.0],
        attestation_tier=AttestationTier.B.value,
    )
    excl = apply_slot_level_gate(panel, _empty_events())
    assert excl.empty


def test_slot_level_gate_empty_panel_returns_empty_schema() -> None:
    excl = apply_slot_level_gate(
        pd.DataFrame(columns=["attestation_tier"]), _empty_events()
    )
    assert excl.empty
    assert list(excl.columns) == ["contributor_id", "constituent_id", "date", "slot_idx"]


def test_slot_level_gate_does_not_double_count_two_constituents() -> None:
    """Two contributors, same constituent, both blow through the gate on the
    same day — fire counts must equal slots-fired-per-(contributor, constituent),
    not be merged."""
    a = _series_panel([50.0] * 5 + [200.0], contributor_id="contrib_a")
    b = _series_panel([50.0] * 5 + [200.0], contributor_id="contrib_b")
    excl = apply_slot_level_gate(pd.concat([a, b], ignore_index=True), _empty_events())
    assert (excl["contributor_id"] == "contrib_a").sum() == 32
    assert (excl["contributor_id"] == "contrib_b").sum() == 32


# ---------------------------------------------------------------------------
# apply_continuity_check
# ---------------------------------------------------------------------------


def test_continuity_check_24pct_not_flagged_26pct_flagged() -> None:
    """26% jump → flagged; 24% jump → not. Continuity threshold 25%."""
    panel24 = _series_panel([50.0, 62.0])  # +24%
    out24 = apply_continuity_check(panel24)
    assert not out24["requires_verification"].any()

    panel26 = _series_panel([50.0, 63.0])  # +26%
    out26 = apply_continuity_check(panel26)
    assert out26["requires_verification"].iloc[0] is False or not out26["requires_verification"].iloc[0]
    assert bool(out26["requires_verification"].iloc[1])


def test_continuity_check_first_day_no_prior_not_flagged() -> None:
    panel = _series_panel([50.0])
    out = apply_continuity_check(panel)
    assert not out["requires_verification"].iloc[0]


def test_continuity_check_only_tier_a_flagged() -> None:
    """Tier B / Tier C jumps stay False — verification rule is Tier A only."""
    panel = _series_panel([50.0, 200.0], attestation_tier=AttestationTier.B.value)
    out = apply_continuity_check(panel)
    assert not out["requires_verification"].any()


def test_continuity_check_empty_panel_returns_empty_with_column() -> None:
    out = apply_continuity_check(
        pd.DataFrame(columns=["attestation_tier", "output_price_usd_mtok"])
    )
    assert "requires_verification" in out.columns
    assert out.empty


# ---------------------------------------------------------------------------
# apply_staleness_rule
# ---------------------------------------------------------------------------


def test_staleness_2_day_old_not_stale_4_day_old_stale() -> None:
    """Project plan acceptance: 2-day-old not stale, 4-day-old stale.

    With ``max_stale_days = 3``: today equals each of the prior 3 rows →
    4-consecutive-same panel days flag the 4th. 2 consecutive same → no flag.
    """
    panel = _series_panel([50.0, 50.0, 50.0, 50.0])  # 4 consecutive days
    out = apply_staleness_rule(panel)
    flags = out["is_stale"].tolist()
    # Days 1, 2, 3 → not stale (insufficient history of 3 priors)
    # Day 4 → stale (3 priors all = 50.0)
    assert flags == [False, False, False, True]


def test_staleness_max_stale_days_param_respected() -> None:
    """With max_stale_days=2: 3-consecutive same → flag the 3rd."""
    panel = _series_panel([50.0, 50.0, 50.0])
    out = apply_staleness_rule(panel, max_stale_days=2)
    assert out["is_stale"].tolist() == [False, False, True]


def test_staleness_only_tier_a_flagged() -> None:
    panel = _series_panel(
        [50.0, 50.0, 50.0, 50.0],
        attestation_tier=AttestationTier.B.value,
    )
    out = apply_staleness_rule(panel)
    assert not out["is_stale"].any()


def test_staleness_price_change_resets_run() -> None:
    """A non-matching prior breaks the run: the next 4 same-price days then
    re-flag the 4th of THAT run, not earlier."""
    panel = _series_panel([50.0, 50.0, 51.0, 51.0, 51.0, 51.0])
    out = apply_staleness_rule(panel)
    assert out["is_stale"].tolist() == [False, False, False, False, False, True]


def test_staleness_empty_panel() -> None:
    out = apply_staleness_rule(
        pd.DataFrame(columns=["attestation_tier", "output_price_usd_mtok"])
    )
    assert "is_stale" in out.columns
    assert out.empty


# ---------------------------------------------------------------------------
# compute_consecutive_day_suspensions
# ---------------------------------------------------------------------------


def _excluded_slots(dates: list[str]) -> pd.DataFrame:
    """Helper: one any-slot-fire row per supplied date."""
    return pd.DataFrame(
        {
            "contributor_id": ["contrib_a"] * len(dates),
            "constituent_id": ["openai/gpt-5"] * len(dates),
            "date": [pd.Timestamp(d) for d in dates],
            "slot_idx": [0] * len(dates),
        }
    )


def test_suspension_three_consecutive_fires_emits_third_day() -> None:
    excl = _excluded_slots(["2025-01-10", "2025-01-11", "2025-01-12"])
    out = compute_consecutive_day_suspensions(excl)
    assert len(out) == 1
    assert out["suspension_date"].iloc[0] == pd.Timestamp("2025-01-12")


def test_suspension_gap_resets_run() -> None:
    """2 fires, gap, 2 fires → no suspension (3-day run not achieved)."""
    excl = _excluded_slots(["2025-01-10", "2025-01-11", "2025-01-13", "2025-01-14"])
    out = compute_consecutive_day_suspensions(excl)
    assert out.empty


def test_suspension_sticky_only_first_crossing_emitted() -> None:
    """4 consecutive fires → only one suspension row, on the 3rd day."""
    excl = _excluded_slots(
        ["2025-01-10", "2025-01-11", "2025-01-12", "2025-01-13"]
    )
    out = compute_consecutive_day_suspensions(excl)
    assert len(out) == 1
    assert out["suspension_date"].iloc[0] == pd.Timestamp("2025-01-12")


def test_suspension_threshold_one_emits_first_fire_day() -> None:
    """threshold_days=1 short-circuit: any single fire day suspends."""
    excl = _excluded_slots(["2025-01-10", "2025-01-15"])
    out = compute_consecutive_day_suspensions(excl, threshold_days=1)
    assert len(out) == 1
    assert out["suspension_date"].iloc[0] == pd.Timestamp("2025-01-10")


def test_suspension_empty_input_returns_empty_schema() -> None:
    empty = pd.DataFrame(
        columns=["contributor_id", "constituent_id", "date", "slot_idx"]
    )
    out = compute_consecutive_day_suspensions(empty)
    assert out.empty
    assert list(out.columns) == ["contributor_id", "constituent_id", "suspension_date"]


def test_suspension_independent_per_pair() -> None:
    """Two (contributor, constituent) pairs each with their own 3-day run →
    two suspension rows, one per pair."""
    df = pd.concat(
        [
            _excluded_slots(["2025-01-10", "2025-01-11", "2025-01-12"]),
            _excluded_slots(
                ["2025-02-01", "2025-02-02", "2025-02-03"]
            ).assign(contributor_id="contrib_b"),
        ],
        ignore_index=True,
    )
    out = compute_consecutive_day_suspensions(df).sort_values(
        "contributor_id"
    ).reset_index(drop=True)
    assert len(out) == 2
    assert out["contributor_id"].tolist() == ["contrib_a", "contrib_b"]
    assert out["suspension_date"].tolist() == [
        pd.Timestamp("2025-01-12"),
        pd.Timestamp("2025-02-03"),
    ]


# ---------------------------------------------------------------------------
# check_min_constituents
# ---------------------------------------------------------------------------


def test_min_constituents_three_distinct_passes_default_min_three() -> None:
    panel = pd.concat(
        [
            _series_panel([50.0], constituent_id="m1"),
            _series_panel([50.0], constituent_id="m2"),
            _series_panel([50.0], constituent_id="m3"),
        ],
        ignore_index=True,
    )
    assert check_min_constituents(panel, tier=Tier.TPRR_F)


def test_min_constituents_two_distinct_fails_default() -> None:
    panel = pd.concat(
        [
            _series_panel([50.0], constituent_id="m1"),
            _series_panel([50.0], constituent_id="m2"),
        ],
        ignore_index=True,
    )
    assert not check_min_constituents(panel, tier=Tier.TPRR_F)


def test_min_constituents_filters_by_tier_code() -> None:
    """Counts only rows in the requested tier; rows in other tiers ignored."""
    panel = pd.concat(
        [
            _series_panel([50.0], constituent_id="m1", tier_code=Tier.TPRR_F.value),
            _series_panel([50.0], constituent_id="m2", tier_code=Tier.TPRR_F.value),
            _series_panel([50.0], constituent_id="m3", tier_code=Tier.TPRR_S.value),
            _series_panel([50.0], constituent_id="m4", tier_code=Tier.TPRR_S.value),
            _series_panel([50.0], constituent_id="m5", tier_code=Tier.TPRR_S.value),
        ],
        ignore_index=True,
    )
    assert not check_min_constituents(panel, tier=Tier.TPRR_F)  # 2 in F
    assert check_min_constituents(panel, tier=Tier.TPRR_S)  # 3 in S


def test_min_constituents_empty_panel_returns_false() -> None:
    assert not check_min_constituents(pd.DataFrame(columns=["tier_code"]), tier=Tier.TPRR_F)


def test_min_constituents_accepts_tier_string_alias() -> None:
    panel = pd.concat(
        [
            _series_panel([50.0], constituent_id="m1"),
            _series_panel([50.0], constituent_id="m2"),
            _series_panel([50.0], constituent_id="m3"),
        ],
        ignore_index=True,
    )
    assert check_min_constituents(panel, tier="TPRR_F")


# ---------------------------------------------------------------------------
# compute_suspension_intervals — Phase 7H Batch D (DL 2026-04-30)
# ---------------------------------------------------------------------------


def _panel_row_for_suspension(
    *,
    contributor_id: str,
    constituent_id: str,
    date_value: pd.Timestamp,
) -> dict[str, Any]:
    """Minimal panel row for suspension-interval testing — only the
    columns the function reads."""
    return {
        "contributor_id": contributor_id,
        "constituent_id": constituent_id,
        "observation_date": date_value,
    }


_DEFAULT_PANEL_START = pd.Timestamp("2025-01-01")


def _panel_for_pair(
    contributor_id: str,
    constituent_id: str,
    n_days: int,
    *,
    start: pd.Timestamp = _DEFAULT_PANEL_START,
) -> pd.DataFrame:
    """Build a panel covering n_days consecutive days for one pair."""
    return pd.DataFrame(
        [
            _panel_row_for_suspension(
                contributor_id=contributor_id,
                constituent_id=constituent_id,
                date_value=start + i * DAY,
            )
            for i in range(n_days)
        ]
    )


def _excluded_slot(
    *,
    contributor_id: str,
    constituent_id: str,
    date_value: pd.Timestamp,
    slot_idx: int = 0,
) -> dict[str, Any]:
    return {
        "contributor_id": contributor_id,
        "constituent_id": constituent_id,
        "date": date_value,
        "slot_idx": slot_idx,
    }


def test_compute_suspension_intervals_empty_input_returns_empty() -> None:
    out = compute_suspension_intervals(
        excluded_slots_df=pd.DataFrame(
            columns=["contributor_id", "constituent_id", "date", "slot_idx"]
        ),
        panel_df=pd.DataFrame(
            columns=["contributor_id", "constituent_id", "observation_date"]
        ),
    )
    assert out.empty
    assert list(out.columns) == [
        "contributor_id",
        "constituent_id",
        "suspension_date",
        "reinstatement_date",
    ]


def test_compute_suspension_intervals_single_suspension_no_reinstatement() -> None:
    """3 consecutive fire days → suspension. No reinstatement (only 5 days
    of clean behaviour after, < 10-day threshold). Output: one row with
    reinstatement_date = NaT."""
    start = pd.Timestamp("2025-01-01")
    panel = _panel_for_pair("c1", "k1", 8, start=start)
    excluded_slots = pd.DataFrame(
        [
            _excluded_slot(
                contributor_id="c1",
                constituent_id="k1",
                date_value=start + i * DAY,
            )
            for i in range(3)
        ]
    )
    out = compute_suspension_intervals(excluded_slots, panel, threshold_days=3)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["contributor_id"] == "c1"
    assert row["constituent_id"] == "k1"
    assert pd.Timestamp(row["suspension_date"]) == start + 2 * DAY
    assert pd.isna(row["reinstatement_date"])


def test_compute_suspension_intervals_suspend_then_reinstate() -> None:
    """3 fire days + 10 clean days → suspension at day 3, reinstatement
    at day 13 (10 consecutive clean days reach threshold)."""
    start = pd.Timestamp("2025-01-01")
    panel = _panel_for_pair("c1", "k1", 14, start=start)
    excluded_slots = pd.DataFrame(
        [
            _excluded_slot(
                contributor_id="c1",
                constituent_id="k1",
                date_value=start + i * DAY,
            )
            for i in range(3)
        ]
    )
    out = compute_suspension_intervals(
        excluded_slots, panel,
        threshold_days=3,
        reinstatement_threshold_days=10,
    )
    assert len(out) == 1
    row = out.iloc[0]
    # Suspension fires on day 3 (the 3rd consecutive fire day, 0-indexed
    # day 2).
    assert pd.Timestamp(row["suspension_date"]) == start + 2 * DAY
    # Reinstatement fires on day 13 (10th clean day after suspension; the
    # clean days are days 3..12 = 10 days; 0-indexed day 12).
    assert pd.Timestamp(row["reinstatement_date"]) == start + 12 * DAY


def test_compute_suspension_intervals_multiple_cycles() -> None:
    """Pair suspends, reinstates, then suspends again. Output: 2 rows
    representing the two intervals.

    Panel sized at 25 days so the second suspension (day 17) has only
    7 clean days after (days 18..24) → insufficient for reinstatement,
    second interval stays open at end of range."""
    start = pd.Timestamp("2025-01-01")
    panel = _panel_for_pair("c1", "k1", 25, start=start)
    excluded_slots = pd.DataFrame(
        [
            # First suspension cycle: days 0, 1, 2 fire (suspends day 2)
            _excluded_slot(
                contributor_id="c1",
                constituent_id="k1",
                date_value=start + i * DAY,
            )
            for i in range(3)
        ]
        + [
            # Days 3..12 (10 days) clean → reinstates day 12
            # Days 15, 16, 17 fire → second suspension at day 17
            _excluded_slot(
                contributor_id="c1",
                constituent_id="k1",
                date_value=start + (15 + i) * DAY,
            )
            for i in range(3)
        ]
    )
    out = compute_suspension_intervals(
        excluded_slots, panel,
        threshold_days=3,
        reinstatement_threshold_days=10,
    )
    assert len(out) == 2
    # First interval: suspends day 2, reinstates day 12.
    assert pd.Timestamp(out.iloc[0]["suspension_date"]) == start + 2 * DAY
    assert pd.Timestamp(out.iloc[0]["reinstatement_date"]) == start + 12 * DAY
    # Second interval: suspends day 17. Still suspended at end of range.
    assert pd.Timestamp(out.iloc[1]["suspension_date"]) == start + 17 * DAY
    assert pd.isna(out.iloc[1]["reinstatement_date"])


def test_compute_suspension_intervals_missing_day_resets_clean_counter() -> None:
    """A missing day (no panel row for the pair) resets the clean
    counter to zero — reinstatement requires 10 CONSECUTIVE clean
    panel-recorded days, not 10 calendar days with gaps."""
    start = pd.Timestamp("2025-01-01")
    # 14 days total: panel covers all 14 except day 6 missing.
    panel_dates = [start + i * DAY for i in range(14) if i != 6]
    panel = pd.DataFrame(
        [
            _panel_row_for_suspension(
                contributor_id="c1", constituent_id="k1", date_value=d
            )
            for d in panel_dates
        ]
    )
    excluded_slots = pd.DataFrame(
        [
            _excluded_slot(
                contributor_id="c1",
                constituent_id="k1",
                date_value=start + i * DAY,
            )
            for i in range(3)
        ]
    )
    out = compute_suspension_intervals(
        excluded_slots, panel,
        threshold_days=3,
        reinstatement_threshold_days=10,
    )
    # The missing day at index 6 resets the clean counter. After the
    # missing day, we need another 10 consecutive clean days — but only
    # days 7..13 remain (7 clean days), insufficient for reinstatement.
    # Result: one row, still suspended.
    assert len(out) == 1
    assert pd.isna(out.iloc[0]["reinstatement_date"])


def test_compute_suspension_intervals_fire_during_clean_run_resets_counter() -> None:
    """A fire day mid-clean-run resets the clean counter — does not
    accumulate fire counter from zero unless suspension is currently
    active. Pair stays suspended."""
    start = pd.Timestamp("2025-01-01")
    panel = _panel_for_pair("c1", "k1", 15, start=start)
    # Initial 3-day fire (suspend at day 2), then days 3-9 clean (7 clean),
    # then day 10 fire (resets clean), then days 11-14 clean (4 clean,
    # < 10 threshold).
    fire_days = [0, 1, 2, 10]
    excluded_slots = pd.DataFrame(
        [
            _excluded_slot(
                contributor_id="c1",
                constituent_id="k1",
                date_value=start + i * DAY,
            )
            for i in fire_days
        ]
    )
    out = compute_suspension_intervals(
        excluded_slots, panel,
        threshold_days=3,
        reinstatement_threshold_days=10,
    )
    assert len(out) == 1
    assert pd.Timestamp(out.iloc[0]["suspension_date"]) == start + 2 * DAY
    assert pd.isna(out.iloc[0]["reinstatement_date"])


def test_compute_suspension_intervals_invalid_thresholds_raise() -> None:
    import pytest as _pytest

    excluded_slots = pd.DataFrame(
        columns=["contributor_id", "constituent_id", "date", "slot_idx"]
    )
    panel = pd.DataFrame(
        columns=["contributor_id", "constituent_id", "observation_date"]
    )
    with _pytest.raises(ValueError, match="threshold_days must be"):
        compute_suspension_intervals(
            excluded_slots, panel, threshold_days=0
        )
    with _pytest.raises(ValueError, match="reinstatement_threshold_days"):
        compute_suspension_intervals(
            excluded_slots, panel, reinstatement_threshold_days=0
        )
