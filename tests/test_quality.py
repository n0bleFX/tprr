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
