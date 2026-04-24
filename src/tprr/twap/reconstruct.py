"""TWAP reconstructor — builds 32-slot intraday price arrays from panel + events.

Used downstream by:
- Phase 6 slot-level quality gate (per-(contributor, constituent, date) slot
  reconstruction for 15% deviation checks against the 5-day trailing average).
- Phase 7 aggregation (daily TWAP values feed the dual-weighted cross-
  constituent formula).

Three functions:
- ``reconstruct_slots`` — returns the 32-element slot array for one
  (contributor, constituent, date). Public standalone API.
- ``compute_daily_twap`` — arithmetic mean over surviving slots (excluded
  slots dropped from the mean). Raises when every slot is excluded.
- ``compute_panel_twap`` — adds ``twap_output_usd_mtok`` and
  ``twap_input_usd_mtok`` columns to a panel DataFrame, optionally honouring
  an excluded-slots DataFrame (Phase 6 output).

Slot semantics: slots ``[0, change_slot_idx)`` use ``old_{price_field}``;
slots ``[change_slot_idx, 32)`` use ``new_{price_field}``. Change events
provide the old/new prices directly — the panel's price column already
stores the daily TWAP on event days (written by ``apply_twap_to_panel``),
so the reconstructor doesn't read panel prices on event days.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

_TWAP_SLOTS = 32


def reconstruct_slots(
    contributor_id: str,
    constituent_id: str,
    date: Any,  # observation date; datetime64 / Timestamp / date all accepted
    panel_df: pd.DataFrame,
    change_events_df: pd.DataFrame,
    price_field: str = "output_price_usd_mtok",
) -> npt.NDArray[np.float64]:
    """Build 32-slot intraday price array for one (contributor, constituent, date).

    No change event on that date → all 32 slots equal the panel's posted
    price for ``price_field``.

    Change event exists → slots ``[0, change_slot_idx)`` use the event's
    ``old_{price_field}`` value; slots ``[change_slot_idx, 32)`` use
    ``new_{price_field}``.
    """
    ts = pd.Timestamp(date)
    event_mask = (
        (change_events_df["event_date"] == ts)
        & (change_events_df["contributor_id"] == contributor_id)
        & (change_events_df["constituent_id"] == constituent_id)
    )
    matches = change_events_df.loc[event_mask]

    if len(matches) == 0:
        panel_mask = (
            (panel_df["observation_date"] == ts)
            & (panel_df["contributor_id"] == contributor_id)
            & (panel_df["constituent_id"] == constituent_id)
        )
        panel_match = panel_df.loc[panel_mask]
        if len(panel_match) == 0:
            raise KeyError(
                f"no panel row for ({contributor_id!r}, {constituent_id!r}, "
                f"{ts.date()})"
            )
        posted = float(panel_match.iloc[0][price_field])
        return np.full(_TWAP_SLOTS, posted, dtype=np.float64)

    event = matches.iloc[0]
    slot_idx = int(event["change_slot_idx"])
    old_price = float(event[f"old_{price_field}"])
    new_price = float(event[f"new_{price_field}"])

    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    slots[:slot_idx] = old_price
    slots[slot_idx:] = new_price
    return slots


def compute_daily_twap(
    slot_prices: npt.NDArray[np.float64],
    excluded_slots: set[int] | None = None,
) -> float:
    """Arithmetic mean over surviving slots. Raises if every slot is excluded."""
    if len(slot_prices) != _TWAP_SLOTS:
        raise ValueError(
            f"expected {_TWAP_SLOTS} slot prices, got {len(slot_prices)}"
        )

    if excluded_slots is None or len(excluded_slots) == 0:
        return float(slot_prices.mean())

    surviving_idx = [i for i in range(_TWAP_SLOTS) if i not in excluded_slots]
    if not surviving_idx:
        raise ValueError(
            f"all {_TWAP_SLOTS} slots excluded; no valid observations for TWAP"
        )
    return float(slot_prices[surviving_idx].mean())


def compute_panel_twap(
    panel_df: pd.DataFrame,
    change_events_df: pd.DataFrame,
    excluded_slots_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add ``twap_output_usd_mtok`` and ``twap_input_usd_mtok`` to panel.

    Pre-builds an event-lookup dict once to keep the 44k-row pipeline loop
    fast (avoids per-row DataFrame filtering that the public
    ``reconstruct_slots`` does). Honours ``excluded_slots_df`` when provided
    — the DataFrame must have columns ``(contributor_id, constituent_id,
    date, slot_idx)``, one row per excluded slot.
    """
    event_lookup = _build_event_lookup(change_events_df)
    exclusions = _build_exclusions_lookup(excluded_slots_df)

    n = len(panel_df)
    twap_output = np.empty(n, dtype=np.float64)
    twap_input = np.empty(n, dtype=np.float64)

    for i, rec in enumerate(panel_df.to_dict("records")):
        cid = str(rec["contributor_id"])
        const_id = str(rec["constituent_id"])
        obs_date = pd.Timestamp(rec["observation_date"])
        key = (cid, const_id, obs_date)
        excluded = exclusions.get(key)

        if key in event_lookup:
            slot, old_out, new_out, old_in, new_in = event_lookup[key]
            out_slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
            out_slots[:slot] = old_out
            out_slots[slot:] = new_out
            in_slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
            in_slots[:slot] = old_in
            in_slots[slot:] = new_in
        elif excluded is None or len(excluded) == 0:
            # No event, no exclusions — TWAP is just the posted price.
            twap_output[i] = float(rec["output_price_usd_mtok"])
            twap_input[i] = float(rec["input_price_usd_mtok"])
            continue
        else:
            posted_out = float(rec["output_price_usd_mtok"])
            posted_in = float(rec["input_price_usd_mtok"])
            out_slots = np.full(_TWAP_SLOTS, posted_out, dtype=np.float64)
            in_slots = np.full(_TWAP_SLOTS, posted_in, dtype=np.float64)

        twap_output[i] = compute_daily_twap(out_slots, excluded)
        twap_input[i] = compute_daily_twap(in_slots, excluded)

    out = panel_df.copy()
    out["twap_output_usd_mtok"] = twap_output
    out["twap_input_usd_mtok"] = twap_input
    return out


def _build_event_lookup(
    change_events_df: pd.DataFrame,
) -> dict[tuple[str, str, pd.Timestamp], tuple[int, float, float, float, float]]:
    """(contributor, constituent, date) -> (slot, old_out, new_out, old_in, new_in)."""
    lookup: dict[
        tuple[str, str, pd.Timestamp], tuple[int, float, float, float, float]
    ] = {}
    for rec in change_events_df.to_dict("records"):
        key = (
            str(rec["contributor_id"]),
            str(rec["constituent_id"]),
            pd.Timestamp(rec["event_date"]),
        )
        lookup[key] = (
            int(rec["change_slot_idx"]),
            float(rec["old_output_price_usd_mtok"]),
            float(rec["new_output_price_usd_mtok"]),
            float(rec["old_input_price_usd_mtok"]),
            float(rec["new_input_price_usd_mtok"]),
        )
    return lookup


def _build_exclusions_lookup(
    excluded_slots_df: pd.DataFrame | None,
) -> dict[tuple[str, str, pd.Timestamp], set[int]]:
    """(contributor, constituent, date) -> set of excluded slot indices."""
    lookup: dict[tuple[str, str, pd.Timestamp], set[int]] = {}
    if excluded_slots_df is None:
        return lookup
    for rec in excluded_slots_df.to_dict("records"):
        key = (
            str(rec["contributor_id"]),
            str(rec["constituent_id"]),
            pd.Timestamp(rec["date"]),
        )
        lookup.setdefault(key, set()).add(int(rec["slot_idx"]))
    return lookup
