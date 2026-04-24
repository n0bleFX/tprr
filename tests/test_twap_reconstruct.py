"""Tests for tprr.twap.reconstruct — 32-slot reconstruction + daily TWAP."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tprr.config import (
    ContributorPanel,
    ContributorProfile,
    ModelMetadata,
    ModelRegistry,
    VolumeScale,
)
from tprr.mockdata.change_events import apply_twap_to_panel, generate_change_events
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.pricing import generate_baseline_prices
from tprr.mockdata.volume import generate_volumes
from tprr.twap.reconstruct import (
    _TWAP_SLOTS,
    compute_daily_twap,
    compute_panel_twap,
    reconstruct_slots,
)


def _registry() -> ModelRegistry:
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id="openai/gpt-5-pro",
                tier=__import__("tprr.schema", fromlist=["Tier"]).Tier.TPRR_F,
                provider="openai",
                canonical_name="GPT-5 Pro",
                baseline_input_price_usd_mtok=15.0,
                baseline_output_price_usd_mtok=75.0,
            ),
            ModelMetadata(
                constituent_id="openai/gpt-5-mini",
                tier=__import__("tprr.schema", fromlist=["Tier"]).Tier.TPRR_S,
                provider="openai",
                canonical_name="GPT-5 Mini",
                baseline_input_price_usd_mtok=0.5,
                baseline_output_price_usd_mtok=4.0,
            ),
        ]
    )


def _panel_config() -> ContributorPanel:
    return ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id="contrib_a",
                profile_name="A",
                volume_scale=VolumeScale.MEDIUM,
                price_bias_pct=0.0,
                daily_noise_sigma_pct=0.5,
                error_rate=0.0,
                covered_models=["openai/gpt-5-pro", "openai/gpt-5-mini"],
            )
        ]
    )


def _build_pipeline(
    n_days: int = 200, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build TWAP-updated panel + change events."""
    registry = _registry()
    contributors = _panel_config()
    baseline, step_events = generate_baseline_prices(
        registry,
        date(2025, 1, 1),
        date(2025, 1, 1) + timedelta(days=n_days - 1),
        seed=seed,
    )
    panel = generate_contributor_panel(baseline, contributors, registry, seed=seed)
    panel = generate_volumes(panel, contributors, seed=seed)
    events = generate_change_events(panel, step_events, registry, contributors, seed=seed)
    panel = apply_twap_to_panel(panel, events)
    return panel, events


def test_reconstruct_no_event_returns_constant_panel_price() -> None:
    panel, events = _build_pipeline(n_days=60)
    # Find a (contributor, constituent, date) with NO event
    event_keys = set(
        zip(
            events["event_date"],
            events["contributor_id"],
            events["constituent_id"],
            strict=True,
        )
    )
    for rec in panel.to_dict("records"):
        key = (
            pd.Timestamp(rec["observation_date"]),
            rec["contributor_id"],
            rec["constituent_id"],
        )
        if key not in event_keys:
            slots = reconstruct_slots(
                rec["contributor_id"],
                rec["constituent_id"],
                rec["observation_date"],
                panel,
                events,
                price_field="output_price_usd_mtok",
            )
            assert slots.shape == (_TWAP_SLOTS,)
            assert np.allclose(slots, rec["output_price_usd_mtok"])
            return
    raise AssertionError("no non-event (contributor, constituent, date) found")


def test_reconstruct_with_event_splits_slots_at_change_idx() -> None:
    panel, events = _build_pipeline(n_days=200)
    ev = events.iloc[0]
    slots = reconstruct_slots(
        ev["contributor_id"],
        ev["constituent_id"],
        ev["event_date"],
        panel,
        events,
        price_field="output_price_usd_mtok",
    )
    slot_idx = int(ev["change_slot_idx"])
    assert np.allclose(slots[:slot_idx], ev["old_output_price_usd_mtok"])
    assert np.allclose(slots[slot_idx:], ev["new_output_price_usd_mtok"])


def test_reconstruct_input_field_symmetric_to_output() -> None:
    panel, events = _build_pipeline(n_days=200)
    ev = events.iloc[0]
    slots_in = reconstruct_slots(
        ev["contributor_id"],
        ev["constituent_id"],
        ev["event_date"],
        panel,
        events,
        price_field="input_price_usd_mtok",
    )
    slot_idx = int(ev["change_slot_idx"])
    assert np.allclose(slots_in[:slot_idx], ev["old_input_price_usd_mtok"])
    assert np.allclose(slots_in[slot_idx:], ev["new_input_price_usd_mtok"])


def test_reconstruct_missing_panel_row_raises() -> None:
    panel, events = _build_pipeline(n_days=60)
    with pytest.raises(KeyError, match="no panel row"):
        reconstruct_slots(
            "contrib_nonexistent",
            "openai/gpt-5-pro",
            pd.Timestamp("2025-01-01"),
            panel,
            events,
        )


def test_daily_twap_constant_prices_equals_that_price() -> None:
    slots = np.full(_TWAP_SLOTS, 42.5, dtype=np.float64)
    assert compute_daily_twap(slots) == 42.5


def test_daily_twap_change_at_slot_16_is_midpoint() -> None:
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    slots[:16] = 10.0
    slots[16:] = 20.0
    assert compute_daily_twap(slots) == 15.0


def test_daily_twap_change_at_slot_0_equals_new_price() -> None:
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    slots[:0] = 10.0  # nothing
    slots[0:] = 20.0
    assert compute_daily_twap(slots) == 20.0


def test_daily_twap_change_at_slot_31_matches_formula() -> None:
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    slots[:31] = 10.0
    slots[31:] = 20.0
    expected = (31 * 10.0 + 1 * 20.0) / 32
    assert compute_daily_twap(slots) == expected


def test_daily_twap_exclusions_reduce_denominator() -> None:
    """Hand-compute: 32 slots at [value=1 for 16 slots, value=3 for 16 slots],
    exclude slots 0..5 (six zeros-valued positions). Remaining 26 slots:
    10 of value=1 (slots 6..15) + 16 of value=3 (slots 16..31).
    TWAP = (10*1 + 16*3) / 26 = 58 / 26 ≈ 2.230769..."""
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    slots[:16] = 1.0
    slots[16:] = 3.0
    excluded = set(range(0, 6))  # exclude slots 0..5
    expected = (10 * 1.0 + 16 * 3.0) / 26
    result = compute_daily_twap(slots, excluded)
    assert abs(result - expected) < 1e-12


def test_daily_twap_all_slots_excluded_raises() -> None:
    slots = np.full(_TWAP_SLOTS, 1.0, dtype=np.float64)
    with pytest.raises(ValueError, match="all 32 slots excluded"):
        compute_daily_twap(slots, set(range(32)))


def test_daily_twap_wrong_array_length_raises() -> None:
    slots = np.full(16, 1.0, dtype=np.float64)
    with pytest.raises(ValueError, match="expected 32 slot prices"):
        compute_daily_twap(slots)


@given(
    old=st.floats(
        min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
    new=st.floats(
        min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
)
def test_twap_monotone_in_slot_idx(old: float, new: float) -> None:
    """TWAP monotonically shifts from old (slot_idx=31) to new (slot_idx=0)."""
    twaps = []
    for slot in range(32):
        s = np.empty(_TWAP_SLOTS, dtype=np.float64)
        s[:slot] = old
        s[slot:] = new
        twaps.append(compute_daily_twap(s))
    arr = np.array(twaps)
    diffs = np.diff(arr)
    # slot_idx increases → share of old increases.
    if old < new:
        assert (diffs <= 1e-9).all(), f"TWAP not non-increasing in slot_idx: {arr}"
    elif old > new:
        assert (diffs >= -1e-9).all(), f"TWAP not non-decreasing in slot_idx: {arr}"
    else:
        assert np.allclose(arr, old)


def test_reconstruct_panel_without_events_is_constant_panel_price() -> None:
    """Property: reconstruct_slots for (contributor, constituent, date) with no
    change event returns an array where all 32 values equal the panel's
    posted price for that cell, to floating-point tolerance."""
    panel, events = _build_pipeline(n_days=60)
    event_keys = set(
        zip(
            events["event_date"],
            events["contributor_id"],
            events["constituent_id"],
            strict=True,
        )
    )
    checked = 0
    for rec in panel.to_dict("records"):
        key = (
            pd.Timestamp(rec["observation_date"]),
            rec["contributor_id"],
            rec["constituent_id"],
        )
        if key in event_keys:
            continue
        slots = reconstruct_slots(
            rec["contributor_id"],
            rec["constituent_id"],
            rec["observation_date"],
            panel,
            events,
        )
        assert np.allclose(slots, rec["output_price_usd_mtok"])
        checked += 1
        if checked >= 50:
            break
    assert checked > 0


def test_reconstruct_plus_twap_agrees_with_apply_twap_to_panel() -> None:
    """Property: reconstruct_slots + compute_daily_twap on event days reproduces
    apply_twap_to_panel's result to floating-point tolerance. Verifies the two
    code paths agree: panel-update via formula vs. slot reconstruction + mean."""
    panel, events = _build_pipeline(n_days=200)
    for ev in events.to_dict("records"):
        slots_out = reconstruct_slots(
            ev["contributor_id"],
            ev["constituent_id"],
            ev["event_date"],
            panel,
            events,
            price_field="output_price_usd_mtok",
        )
        slots_in = reconstruct_slots(
            ev["contributor_id"],
            ev["constituent_id"],
            ev["event_date"],
            panel,
            events,
            price_field="input_price_usd_mtok",
        )
        reconstructed_twap_out = compute_daily_twap(slots_out)
        reconstructed_twap_in = compute_daily_twap(slots_in)
        panel_row = panel[
            (panel["observation_date"] == pd.Timestamp(ev["event_date"]))
            & (panel["contributor_id"] == ev["contributor_id"])
            & (panel["constituent_id"] == ev["constituent_id"])
        ].iloc[0]
        assert abs(reconstructed_twap_out - panel_row["output_price_usd_mtok"]) < 1e-12
        assert abs(reconstructed_twap_in - panel_row["input_price_usd_mtok"]) < 1e-12


def test_compute_panel_twap_adds_columns_without_exclusions() -> None:
    panel, events = _build_pipeline(n_days=60)
    out = compute_panel_twap(panel, events)
    assert "twap_output_usd_mtok" in out.columns
    assert "twap_input_usd_mtok" in out.columns
    assert len(out) == len(panel)
    # For rows without events: twap == posted price
    # For rows with events: twap == panel's (already TWAP-updated) price
    assert np.allclose(
        out["twap_output_usd_mtok"].to_numpy(),
        panel["output_price_usd_mtok"].to_numpy(),
        atol=1e-12,
    )
    assert np.allclose(
        out["twap_input_usd_mtok"].to_numpy(),
        panel["input_price_usd_mtok"].to_numpy(),
        atol=1e-12,
    )


def test_compute_panel_twap_respects_exclusions() -> None:
    """When a slot is excluded, TWAP for that (contributor, constituent, date)
    shifts vs. the no-exclusion case."""
    panel, events = _build_pipeline(n_days=60)
    # Build an exclusions DataFrame: for one event row, exclude slots 0..7
    ev = events.iloc[0]
    exclusions = pd.DataFrame(
        {
            "contributor_id": [ev["contributor_id"]] * 8,
            "constituent_id": [ev["constituent_id"]] * 8,
            "date": [pd.Timestamp(ev["event_date"])] * 8,
            "slot_idx": list(range(8)),
        }
    )
    out_with = compute_panel_twap(panel, events, excluded_slots_df=exclusions)
    out_without = compute_panel_twap(panel, events)
    key_mask = (
        (out_with["observation_date"] == pd.Timestamp(ev["event_date"]))
        & (out_with["contributor_id"] == ev["contributor_id"])
        & (out_with["constituent_id"] == ev["constituent_id"])
    )
    twap_with_excl = out_with.loc[key_mask, "twap_output_usd_mtok"].iloc[0]
    twap_without_excl = out_without.loc[key_mask, "twap_output_usd_mtok"].iloc[0]
    # Excluding slots should shift the TWAP (unless old == new, which is unlikely)
    assert abs(twap_with_excl - twap_without_excl) > 1e-9


def test_compute_panel_twap_preserves_panel_columns() -> None:
    panel, events = _build_pipeline(n_days=30)
    out = compute_panel_twap(panel, events)
    for col in panel.columns:
        assert col in out.columns
    # Two new columns appended
    assert set(out.columns) - set(panel.columns) == {
        "twap_output_usd_mtok",
        "twap_input_usd_mtok",
    }


# ---------------------------------------------------------------------------
# Multi-event reconstruction (Phase 2c revision)
# ---------------------------------------------------------------------------


def _minimal_panel_row(
    date_str: str = "2025-01-01",
    cid: str = "c",
    const_id: str = "m",
    output_price: float = 50.0,
    input_price: float = 10.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_date": pd.Timestamp(date_str),
                "contributor_id": cid,
                "constituent_id": const_id,
                "output_price_usd_mtok": output_price,
                "input_price_usd_mtok": input_price,
            }
        ]
    )


def _make_event(
    slot: int,
    old_out: float,
    new_out: float,
    *,
    date_str: str = "2025-01-01",
    cid: str = "c",
    const_id: str = "m",
    reason: str = "outlier_injection",
) -> dict[str, object]:
    return {
        "event_date": pd.Timestamp(date_str),
        "contributor_id": cid,
        "constituent_id": const_id,
        "change_slot_idx": slot,
        "old_output_price_usd_mtok": old_out,
        "new_output_price_usd_mtok": new_out,
        "old_input_price_usd_mtok": old_out / 5.0,
        "new_input_price_usd_mtok": new_out / 5.0,
        "reason": reason,
    }


def test_two_events_same_day_produces_three_segment_array() -> None:
    """intraday_spike shape: up at slot 10, revert at slot 13."""
    panel = _minimal_panel_row()
    events = pd.DataFrame(
        [
            _make_event(slot=10, old_out=100.0, new_out=125.0),
            _make_event(slot=13, old_out=125.0, new_out=100.0),
        ]
    )
    slots = reconstruct_slots(
        "c", "m", pd.Timestamp("2025-01-01"), panel, events
    )
    assert np.all(slots[:10] == 100.0), "pre-first-event segment"
    assert np.all(slots[10:13] == 125.0), "between-events segment (off-market)"
    assert np.all(slots[13:] == 100.0), "post-last-event segment"


def test_three_events_same_day_cascading_prices() -> None:
    """Three events: price steps 10 → 20 → 30 → 40 at slots 5, 15, 25."""
    panel = _minimal_panel_row()
    events = pd.DataFrame(
        [
            _make_event(slot=5, old_out=10.0, new_out=20.0),
            _make_event(slot=15, old_out=20.0, new_out=30.0),
            _make_event(slot=25, old_out=30.0, new_out=40.0),
        ]
    )
    slots = reconstruct_slots(
        "c", "m", pd.Timestamp("2025-01-01"), panel, events
    )
    assert np.all(slots[:5] == 10.0)
    assert np.all(slots[5:15] == 20.0)
    assert np.all(slots[15:25] == 30.0)
    assert np.all(slots[25:] == 40.0)


def test_events_at_adjacent_slots() -> None:
    """Events at slots 15 and 16 — one-slot mid-segment."""
    panel = _minimal_panel_row()
    events = pd.DataFrame(
        [
            _make_event(slot=15, old_out=1.0, new_out=2.0),
            _make_event(slot=16, old_out=2.0, new_out=3.0),
        ]
    )
    slots = reconstruct_slots(
        "c", "m", pd.Timestamp("2025-01-01"), panel, events
    )
    assert np.all(slots[:15] == 1.0)
    assert np.all(slots[15:16] == 2.0)  # single slot
    assert np.all(slots[16:] == 3.0)


def test_events_at_slot_0_and_slot_31_boundaries() -> None:
    """Event at slot 0 sets the initial price; event at slot 31 sets the final slot only."""
    panel = _minimal_panel_row()
    events = pd.DataFrame(
        [
            _make_event(slot=0, old_out=1.0, new_out=2.0),
            _make_event(slot=31, old_out=2.0, new_out=3.0),
        ]
    )
    slots = reconstruct_slots(
        "c", "m", pd.Timestamp("2025-01-01"), panel, events
    )
    assert np.all(slots[:31] == 2.0), "slot-0 event sets price for slots [0, 31)"
    assert slots[31] == 3.0, "slot-31 event sets last slot only"


def test_multi_event_input_field_symmetric() -> None:
    """Multi-event reconstruction honours price_field for input symmetrically."""
    panel = _minimal_panel_row()
    events = pd.DataFrame(
        [
            _make_event(slot=10, old_out=100.0, new_out=125.0),
            _make_event(slot=13, old_out=125.0, new_out=100.0),
        ]
    )
    # Input prices in _make_event are 1/5 of output prices.
    slots_in = reconstruct_slots(
        "c", "m", pd.Timestamp("2025-01-01"), panel, events,
        price_field="input_price_usd_mtok",
    )
    assert np.all(slots_in[:10] == 20.0)
    assert np.all(slots_in[10:13] == 25.0)
    assert np.all(slots_in[13:] == 20.0)


def test_multi_event_sorting_is_by_slot_idx_not_row_order() -> None:
    """Events provided in descending slot order still reconstruct correctly."""
    panel = _minimal_panel_row()
    events = pd.DataFrame(
        [
            _make_event(slot=13, old_out=125.0, new_out=100.0),  # provided first
            _make_event(slot=10, old_out=100.0, new_out=125.0),  # provided second
        ]
    )
    slots = reconstruct_slots(
        "c", "m", pd.Timestamp("2025-01-01"), panel, events
    )
    # Same expected result as the ordered case
    assert np.all(slots[:10] == 100.0)
    assert np.all(slots[10:13] == 125.0)
    assert np.all(slots[13:] == 100.0)


def test_revision_preserves_single_event_behaviour_byte_identical() -> None:
    """Load-bearing invariant: on every single-event day in the Phase 2 panel,
    revised reconstruct_slots produces byte-identical output to the
    pre-revision single-event formula ``slots[:S] = old; slots[S:] = new``.

    The Phase 2 generator dedupes by (contributor, constituent, date) so every
    event in the pipeline's output is a single-event day. This test iterates
    all of them and verifies the revision preserved behaviour exactly.
    """
    panel, events = _build_pipeline(n_days=365)

    for ev in events.to_dict("records"):
        slot = int(ev["change_slot_idx"])

        # Pre-revision formula inlined
        expected_out = np.empty(32, dtype=np.float64)
        expected_out[:slot] = ev["old_output_price_usd_mtok"]
        expected_out[slot:] = ev["new_output_price_usd_mtok"]
        expected_in = np.empty(32, dtype=np.float64)
        expected_in[:slot] = ev["old_input_price_usd_mtok"]
        expected_in[slot:] = ev["new_input_price_usd_mtok"]

        actual_out = reconstruct_slots(
            ev["contributor_id"],
            ev["constituent_id"],
            ev["event_date"],
            panel,
            events,
            price_field="output_price_usd_mtok",
        )
        actual_in = reconstruct_slots(
            ev["contributor_id"],
            ev["constituent_id"],
            ev["event_date"],
            panel,
            events,
            price_field="input_price_usd_mtok",
        )

        assert np.array_equal(expected_out, actual_out), (
            f"output mismatch for {ev['contributor_id']} x "
            f"{ev['constituent_id']} x {ev['event_date']}"
        )
        assert np.array_equal(expected_in, actual_in), (
            f"input mismatch for {ev['contributor_id']} x "
            f"{ev['constituent_id']} x {ev['event_date']}"
        )


def test_revision_preserves_twap_identity_byte_identical() -> None:
    """Second byte-identical check: reconstruct + compute_daily_twap on every
    event day still matches the panel's stored TWAP to 1e-12. This is the
    same invariant verified in test_reconstruct_plus_twap_agrees_with_apply_twap_to_panel,
    run explicitly here to guard against any subtle drift introduced by the
    multi-event revision code path even on single-event inputs.
    """
    panel, events = _build_pipeline(n_days=200)
    for ev in events.to_dict("records"):
        slots = reconstruct_slots(
            ev["contributor_id"],
            ev["constituent_id"],
            ev["event_date"],
            panel,
            events,
            price_field="output_price_usd_mtok",
        )
        reconstructed = compute_daily_twap(slots)
        panel_row = panel[
            (panel["observation_date"] == pd.Timestamp(ev["event_date"]))
            & (panel["contributor_id"] == ev["contributor_id"])
            & (panel["constituent_id"] == ev["constituent_id"])
        ].iloc[0]
        assert abs(reconstructed - panel_row["output_price_usd_mtok"]) < 1e-12
