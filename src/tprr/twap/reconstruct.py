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

    One change event → slots ``[0, change_slot_idx)`` use the event's
    ``old_{price_field}``; slots ``[change_slot_idx, 32)`` use
    ``new_{price_field}``.

    Multiple change events on the same ``(contributor, constituent, date)``
    → events are sorted by ``change_slot_idx`` and the day is partitioned
    into segments: ``[0, events[0].slot) = events[0].old`` (pre-first-event
    price); ``[events[i].slot, events[i+1].slot) = events[i].new``
    (between-events segment); ``[events[-1].slot, 32) = events[-1].new``
    (post-last-event segment). Phase 3 outlier-injection scenarios (fat-finger
    spike-and-revert, intraday_spike) emit two events on the same day; this
    revision supports that shape. The Phase 2 generator still emits at most
    one event per key, and this function's output on single-event inputs is
    byte-identical to the prior single-event formula.
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

    records = matches.sort_values("change_slot_idx").to_dict("records")
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)

    first = records[0]
    first_slot = int(first["change_slot_idx"])
    slots[:first_slot] = float(first[f"old_{price_field}"])

    for i, ev in enumerate(records):
        current_slot = int(ev["change_slot_idx"])
        current_new = float(ev[f"new_{price_field}"])
        end_slot = (
            int(records[i + 1]["change_slot_idx"])
            if i + 1 < len(records)
            else _TWAP_SLOTS
        )
        slots[current_slot:end_slot] = current_new

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

    Multi-event aware (Phase 3 outlier-injection scenarios — fat_finger and
    intraday_spike — emit two events per day; the same segmentation logic
    used in ``reconstruct_slots`` is mirrored here so the bulk path agrees
    with the public reconstructor on every input shape). On Phase 2 single-
    event panels the result is byte-identical to the prior implementation.
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
        events = event_lookup.get(key)

        if events:
            out_slots = _slots_from_events(events, "output_price_usd_mtok")
            in_slots = _slots_from_events(events, "input_price_usd_mtok")
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
) -> dict[tuple[str, str, pd.Timestamp], list[dict[str, Any]]]:
    """(contributor, constituent, date) -> list of event records sorted by slot.

    Multi-event aware. The Phase 2 generator dedupes by key (one event per
    cell) but Phase 3 outlier-injection scenarios (fat_finger, intraday_spike)
    emit two events on the same day; the lookup preserves both, sorted by
    ``change_slot_idx`` so segmentation is straightforward.
    """
    lookup: dict[tuple[str, str, pd.Timestamp], list[dict[str, Any]]] = {}
    for raw in change_events_df.to_dict("records"):
        rec: dict[str, Any] = {str(k): v for k, v in raw.items()}
        key = (
            str(rec["contributor_id"]),
            str(rec["constituent_id"]),
            pd.Timestamp(rec["event_date"]),
        )
        lookup.setdefault(key, []).append(rec)
    for k in lookup:
        lookup[k].sort(key=lambda r: int(r["change_slot_idx"]))
    return lookup


def _slots_from_events(
    events: list[dict[str, Any]],
    price_field: str,
) -> npt.NDArray[np.float64]:
    """Build the 32-slot price array for one (contributor, constituent, date).

    Mirrors ``reconstruct_slots``' multi-event segmentation: slots
    ``[0, events[0].slot)`` carry ``events[0].old``; slots
    ``[events[i].slot, events[i+1].slot)`` carry ``events[i].new``;
    slots ``[events[-1].slot, 32)`` carry ``events[-1].new``. ``events`` is
    assumed sorted by ``change_slot_idx`` (the lookup builder ensures this).
    """
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    first = events[0]
    first_slot = int(first["change_slot_idx"])
    slots[:first_slot] = float(first[f"old_{price_field}"])
    for i, ev in enumerate(events):
        current_slot = int(ev["change_slot_idx"])
        current_new = float(ev[f"new_{price_field}"])
        end_slot = (
            int(events[i + 1]["change_slot_idx"])
            if i + 1 < len(events)
            else _TWAP_SLOTS
        )
        slots[current_slot:end_slot] = current_new
    return slots


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
