"""Phase 6 — slot-level quality gate, continuity check, staleness rule.

Per ``docs/decision_log.md`` 2026-04-29:

- **Slot-level gate (15%, methodology Section 4.2.2)**: any slot whose
  price deviates by more than 15% from the (contributor, constituent)
  5-day trailing average (calendar days, current excluded) is excluded
  from the daily TWAP. Tier A only — Tier B/C have no slot dimension.
- **Continuity check (25%, methodology Section 4.1)**: day-over-day
  posted-price change exceeding 25% sets ``requires_verification = True``
  on the current row. Tier A only.
- **Staleness rule (3 days, v0.1 operational extension)**: posted price
  unchanged for ``max_stale_days + 1`` consecutive panel-recorded days
  sets ``is_stale = True``. Tier A only. Not in canonical methodology
  v1.2; flagged for v1.3 inclusion.
- **Suspension counter (3 consecutive days)**: ``compute_consecutive_day_suspensions``
  returns the first calendar date on which a (contributor, constituent)
  pair has a 3-consecutive-day run of any-slot-fires. v0.1 simplification
  of methodology Section 4.2.2's "3 consecutive 15-minute intervals"
  human-review trigger; the 3-day variant is what an automated v0.1
  produces in lieu of a Data Governance Officer.

The functions in this module do not modify TWAP values directly; they
emit data structures (excluded-slots DataFrame, flag columns, suspension
list) that Phase 7 aggregation consumes.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from tprr.schema import AttestationTier, Tier
from tprr.twap.reconstruct import _TWAP_SLOTS

DEFAULT_TRAILING_WINDOW_DAYS = 5
DEFAULT_DEVIATION_PCT = 0.15
DEFAULT_CONTINUITY_PCT = 0.25
DEFAULT_STALENESS_MAX_DAYS = 3
DEFAULT_SUSPENSION_THRESHOLD_DAYS = 3
DEFAULT_REINSTATEMENT_THRESHOLD_DAYS = 10
DEFAULT_MIN_CONSTITUENTS_PER_TIER = 3

EXCLUDED_SLOTS_COLUMNS = ["contributor_id", "constituent_id", "date", "slot_idx"]
SUSPENSION_COLUMNS = ["contributor_id", "constituent_id", "suspension_date"]
SUSPENSION_INTERVAL_COLUMNS = [
    "contributor_id",
    "constituent_id",
    "suspension_date",
    "reinstatement_date",
]


# ---------------------------------------------------------------------------
# Slot-level gate
# ---------------------------------------------------------------------------


def apply_slot_level_gate(
    panel_df: pd.DataFrame,
    change_events_df: pd.DataFrame,
    *,
    trailing_window_days: int = DEFAULT_TRAILING_WINDOW_DAYS,
    deviation_pct: float = DEFAULT_DEVIATION_PCT,
) -> pd.DataFrame:
    """Return a DataFrame of (contributor, constituent, date, slot_idx) exclusions.

    Operates only on ``attestation_tier == 'A'`` rows. For each row with
    sufficient trailing history (``trailing_window_days`` prior days of
    panel-recorded data; less → row is skipped), the function reconstructs
    the 32 intraday slot prices from the panel daily price + any change
    events for that day, and emits one exclusion row per slot whose price
    deviates from the trailing average by more than ``deviation_pct``
    (fractional, 0.15 = 15%).

    The exclusions DataFrame's ``date`` column matches the column name
    that ``compute_panel_twap`` consumes — same contract.

    Returns an empty DataFrame (with the right columns and dtypes) when
    no exclusions fire.
    """
    if not (0.0 < deviation_pct < 10.0):
        raise ValueError(
            f"apply_slot_level_gate: deviation_pct must be in (0, 10), got {deviation_pct}"
        )
    if trailing_window_days < 1:
        raise ValueError(
            f"apply_slot_level_gate: trailing_window_days must be >= 1, got {trailing_window_days}"
        )

    panel_a = panel_df[panel_df["attestation_tier"] == AttestationTier.A.value].copy()
    if panel_a.empty:
        return _empty_excluded_slots()

    panel_a = panel_a.sort_values(
        ["contributor_id", "constituent_id", "observation_date"]
    ).reset_index(drop=True)
    panel_a["_trailing_avg"] = panel_a.groupby(["contributor_id", "constituent_id"])[
        "output_price_usd_mtok"
    ].transform(
        lambda s: s.shift(1).rolling(trailing_window_days, min_periods=trailing_window_days).mean()
    )

    event_lookup = _build_multi_event_lookup(change_events_df)

    rows: list[dict[str, Any]] = []
    for rec in panel_a.to_dict("records"):
        trailing_avg = rec["_trailing_avg"]
        if pd.isna(trailing_avg) or float(trailing_avg) <= 0:
            continue
        ts = pd.Timestamp(rec["observation_date"])
        key = (str(rec["contributor_id"]), str(rec["constituent_id"]), ts)
        events = event_lookup.get(key, [])
        slot_prices = _slot_prices_from_panel_row(
            panel_price=float(rec["output_price_usd_mtok"]),
            events=events,
        )
        deviations = np.abs(slot_prices - float(trailing_avg)) / float(trailing_avg)
        failing_idx = np.where(deviations > deviation_pct)[0]
        if failing_idx.size == 0:
            continue
        for slot_idx in failing_idx:
            rows.append(
                {
                    "contributor_id": str(rec["contributor_id"]),
                    "constituent_id": str(rec["constituent_id"]),
                    "date": ts,
                    "slot_idx": int(slot_idx),
                }
            )

    if not rows:
        return _empty_excluded_slots()
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
    return out[EXCLUDED_SLOTS_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Continuity check (Section 4.1)
# ---------------------------------------------------------------------------


def apply_continuity_check(
    panel_df: pd.DataFrame,
    *,
    pct: float = DEFAULT_CONTINUITY_PCT,
) -> pd.DataFrame:
    """Add ``requires_verification`` column flagging Tier A day-over-day jumps > ``pct``.

    Methodology Section 4.1: "price changes exceeding 25% from the prior
    observation trigger a manual verification step before the update is
    incorporated." For v0.1 we flag, log, and continue (not block) per
    the working summary in CLAUDE.md.

    Tier A only — Tier B/C rows pass through with ``requires_verification
    = False``.
    """
    if not (0.0 < pct < 10.0):
        raise ValueError(f"apply_continuity_check: pct must be in (0, 10), got {pct}")

    out = panel_df.copy()
    out["requires_verification"] = False
    if out.empty:
        return out

    sub = (
        out[out["attestation_tier"] == AttestationTier.A.value]
        .sort_values(["contributor_id", "constituent_id", "observation_date"])
        .copy()
    )
    if sub.empty:
        return out

    prev = sub.groupby(["contributor_id", "constituent_id"])["output_price_usd_mtok"].shift(1)
    pct_change = (sub["output_price_usd_mtok"] - prev).abs() / prev
    flag_idx = sub.index[pct_change > pct]
    out.loc[flag_idx, "requires_verification"] = True
    return out


# ---------------------------------------------------------------------------
# Staleness rule (v0.1 operational extension)
# ---------------------------------------------------------------------------


def apply_staleness_rule(
    panel_df: pd.DataFrame,
    *,
    max_stale_days: int = DEFAULT_STALENESS_MAX_DAYS,
) -> pd.DataFrame:
    """Add ``is_stale`` flagging Tier A rows whose price equals the prior ``max_stale_days`` rows.

    A row is flagged when its ``output_price_usd_mtok`` matches the price
    on each of the previous ``max_stale_days`` panel-recorded rows for
    the same (contributor, constituent). With ``max_stale_days = 3``,
    a row is stale iff today equals each of the 3 most recent prior
    posted prices (so today is the 4th-or-later consecutive same-price
    panel row — 4-day-old in the project_plan's wording, while
    2-day-old is not flagged).

    Tier A only.
    """
    if max_stale_days < 1:
        raise ValueError(f"apply_staleness_rule: max_stale_days must be >= 1, got {max_stale_days}")

    out = panel_df.copy()
    out["is_stale"] = False
    if out.empty:
        return out

    sub = (
        out[out["attestation_tier"] == AttestationTier.A.value]
        .sort_values(["contributor_id", "constituent_id", "observation_date"])
        .copy()
    )
    if sub.empty:
        return out

    grp = sub.groupby(["contributor_id", "constituent_id"])["output_price_usd_mtok"]
    is_stale_local = pd.Series(True, index=sub.index)
    for k in range(1, max_stale_days + 1):
        prev_k = grp.shift(k)
        # NaN comparisons yield False — insufficient history → not stale.
        is_stale_local &= sub["output_price_usd_mtok"] == prev_k

    out.loc[sub.index[is_stale_local], "is_stale"] = True
    return out


# ---------------------------------------------------------------------------
# Consecutive-day suspension counter
# ---------------------------------------------------------------------------


def compute_consecutive_day_suspensions(
    excluded_slots_df: pd.DataFrame,
    *,
    threshold_days: int = DEFAULT_SUSPENSION_THRESHOLD_DAYS,
) -> pd.DataFrame:
    """Find the first calendar date on which a (contributor, constituent) hits
    ``threshold_days`` consecutive days of any-slot-fires.

    v0.1 sticky-suspension semantics: emit at most one suspension row per
    (contributor, constituent), corresponding to the day on which the
    threshold is first crossed. Downstream consumers treat the constituent
    as suspended from that date forward.

    Returns an empty DataFrame (with ``contributor_id``,
    ``constituent_id``, ``suspension_date`` columns) when no pair hits
    the threshold.
    """
    if threshold_days < 1:
        raise ValueError(
            f"compute_consecutive_day_suspensions: threshold_days must be "
            f">= 1, got {threshold_days}"
        )

    if excluded_slots_df.empty:
        return _empty_suspensions()

    fired_days = (
        excluded_slots_df.groupby(["contributor_id", "constituent_id", "date"], as_index=False)
        .size()
        .rename(columns={"size": "n_excluded"})
    )

    rows: list[dict[str, Any]] = []
    for (contrib, const), grp in fired_days.groupby(["contributor_id", "constituent_id"]):
        dates = sorted(pd.Timestamp(d).date() for d in grp["date"].tolist())
        if not dates:
            continue
        # threshold_days == 1 short-circuit — any fire day is a suspension day.
        if threshold_days == 1:
            rows.append(
                {
                    "contributor_id": str(contrib),
                    "constituent_id": str(const),
                    "suspension_date": pd.Timestamp(dates[0]),
                }
            )
            continue
        run_len = 1
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                run_len += 1
            else:
                run_len = 1
            if run_len >= threshold_days:
                rows.append(
                    {
                        "contributor_id": str(contrib),
                        "constituent_id": str(const),
                        "suspension_date": pd.Timestamp(dates[i]),
                    }
                )
                break  # sticky — record only first crossing

    if not rows:
        return _empty_suspensions()
    out = pd.DataFrame(rows)
    out["suspension_date"] = pd.to_datetime(out["suspension_date"]).astype("datetime64[ns]")
    return out[SUSPENSION_COLUMNS].reset_index(drop=True)


def compute_suspension_intervals(
    excluded_slots_df: pd.DataFrame,
    panel_df: pd.DataFrame,
    *,
    threshold_days: int = DEFAULT_SUSPENSION_THRESHOLD_DAYS,
    reinstatement_threshold_days: int = DEFAULT_REINSTATEMENT_THRESHOLD_DAYS,
) -> pd.DataFrame:
    """Compute suspension/reinstatement intervals per (contributor, constituent).

    Phase 7H Batch D (DL 2026-04-30 Phase 7H methodology design entry +
    DL 2026-04-30 suspension reinstatement gap entry): bidirectional
    exclude/reinstate criteria replace the v0.1 one-way ratchet from
    ``compute_consecutive_day_suspensions``. Each pair walks chronologically:

    - **Fire day** (gate firing): increment fire_counter; reset clean_counter
      to zero. If pair is currently active and fire_counter reaches
      ``threshold_days``, start a new suspension interval at this date.
    - **Clean day** (panel row exists, no gate firing): increment
      clean_counter (only useful while suspended); reset fire_counter.
      If pair is currently suspended and clean_counter reaches
      ``reinstatement_threshold_days``, end the active interval at this
      date (pair is on-market starting from this date).
    - **Missing day** (no panel row for the pair): reset BOTH counters to
      zero. Treats absence-of-data as "no progress" — neither toward
      suspension nor toward reinstatement. v0.1 conservative choice;
      v1.3 may revisit (DL 2026-04-30 Phase 7H methodology design).

    Returns a DataFrame with columns
    ``[contributor_id, constituent_id, suspension_date, reinstatement_date]``.
    A pair with multiple suspend/reinstate cycles emits multiple rows
    (one per interval). ``reinstatement_date`` is ``NaT`` when the pair
    is still suspended at the end of the date range.

    The aggregation pipeline checks "is suspended on date D" via the
    interval semantic: ``suspension_date <= D < reinstatement_date``
    (treating ``NaT`` as +infinity).

    Backward compatibility: ``compute_consecutive_day_suspensions``
    is retained for tests and external callers that want the simpler
    one-way schema.
    """
    if threshold_days < 1:
        raise ValueError(
            f"compute_suspension_intervals: threshold_days must be >= 1, got {threshold_days}"
        )
    if reinstatement_threshold_days < 1:
        raise ValueError(
            f"compute_suspension_intervals: reinstatement_threshold_days must be "
            f">= 1, got {reinstatement_threshold_days}"
        )

    if excluded_slots_df.empty:
        return _empty_suspension_intervals()

    # Per-(pair, date) flag: did this pair have a gate firing on this date?
    fired_keys: set[tuple[str, str, pd.Timestamp]] = set()
    for rec in (
        excluded_slots_df[["contributor_id", "constituent_id", "date"]]
        .drop_duplicates()
        .to_dict("records")
    ):
        fired_keys.add(
            (
                str(rec["contributor_id"]),
                str(rec["constituent_id"]),
                pd.Timestamp(rec["date"]),
            )
        )

    # Per-(pair, date) presence: did this pair appear in the panel on this
    # date? Used to distinguish missing days from clean days.
    panel_keys: set[tuple[str, str, pd.Timestamp]] = set()
    if not panel_df.empty:
        for rec in (
            panel_df[["contributor_id", "constituent_id", "observation_date"]]
            .drop_duplicates()
            .to_dict("records")
        ):
            panel_keys.add(
                (
                    str(rec["contributor_id"]),
                    str(rec["constituent_id"]),
                    pd.Timestamp(rec["observation_date"]),
                )
            )

    # Full calendar date range (inclusive) from min to max date in either
    # the panel or the excluded-slots frame. This is the universe walked
    # per pair — missing days WITHIN this range get the reset semantic
    # (DL 2026-04-30 Phase 7H methodology design entry: "absence of data
    # shouldn't earn reinstatement progress").
    all_endpoint_dates: set[pd.Timestamp] = set()
    for _, _, d in fired_keys:
        all_endpoint_dates.add(d)
    for _, _, d in panel_keys:
        all_endpoint_dates.add(d)
    if not all_endpoint_dates:
        return _empty_suspension_intervals()
    min_date = min(all_endpoint_dates)
    max_date = max(all_endpoint_dates)
    all_dates: list[pd.Timestamp] = list(pd.date_range(start=min_date, end=max_date, freq="D"))

    # Pairs to evaluate: those that ever fired (no fire = no suspension
    # possible).
    pairs: set[tuple[str, str]] = {(c, k) for c, k, _ in fired_keys}

    rows: list[dict[str, Any]] = []
    for contrib, const in sorted(pairs):
        is_suspended = False
        fire_counter = 0
        clean_counter = 0
        active_suspension_date: pd.Timestamp | None = None

        for d in all_dates:
            key = (contrib, const, d)
            in_panel = key in panel_keys
            had_fire = key in fired_keys

            if had_fire:
                fire_counter += 1
                clean_counter = 0
                if not is_suspended and fire_counter >= threshold_days:
                    is_suspended = True
                    active_suspension_date = d
            elif in_panel:
                # Clean day: panel observation present, no gate firing.
                clean_counter += 1
                fire_counter = 0
                if is_suspended and clean_counter >= reinstatement_threshold_days:
                    rows.append(
                        {
                            "contributor_id": contrib,
                            "constituent_id": const,
                            "suspension_date": active_suspension_date,
                            "reinstatement_date": d,
                        }
                    )
                    is_suspended = False
                    active_suspension_date = None
                    clean_counter = 0
            else:
                # Missing day: no panel row for this pair on this date.
                # Both counters reset — no progress in either direction.
                fire_counter = 0
                clean_counter = 0

        # End of date range: if still suspended, emit interval with NaT
        # reinstatement.
        if is_suspended:
            rows.append(
                {
                    "contributor_id": contrib,
                    "constituent_id": const,
                    "suspension_date": active_suspension_date,
                    "reinstatement_date": pd.NaT,
                }
            )

    if not rows:
        return _empty_suspension_intervals()
    out = pd.DataFrame(rows)
    out["suspension_date"] = pd.to_datetime(out["suspension_date"]).astype("datetime64[ns]")
    out["reinstatement_date"] = pd.to_datetime(out["reinstatement_date"]).astype("datetime64[ns]")
    return out[SUSPENSION_INTERVAL_COLUMNS].reset_index(drop=True)


def _empty_suspension_intervals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contributor_id": pd.Series([], dtype="object"),
            "constituent_id": pd.Series([], dtype="object"),
            "suspension_date": pd.Series([], dtype="datetime64[ns]"),
            "reinstatement_date": pd.Series([], dtype="datetime64[ns]"),
        }
    )


# ---------------------------------------------------------------------------
# Min-constituents count (Section 4.2.4)
# ---------------------------------------------------------------------------


def check_min_constituents(
    panel_day_df: pd.DataFrame,
    *,
    tier: Tier | str,
    min_n: int = DEFAULT_MIN_CONSTITUENTS_PER_TIER,
) -> bool:
    """Return True iff ``panel_day_df`` has ≥ ``min_n`` distinct constituents in ``tier``.

    ``tier`` is the **index tier** (``TPRR_F`` / ``TPRR_S`` / ``TPRR_E``),
    not the attestation tier. The caller is responsible for passing a
    single-day slice; this function does no temporal filtering. It counts
    distinct ``constituent_id`` values whose ``tier_code`` matches ``tier``.

    Methodology Section 4.2.4: a tier fix requires at least three active,
    eligible constituents.
    """
    if min_n < 1:
        raise ValueError(f"check_min_constituents: min_n must be >= 1, got {min_n}")
    tier_value = tier.value if isinstance(tier, Tier) else str(tier)
    if panel_day_df.empty:
        return False
    sub = panel_day_df[panel_day_df["tier_code"] == tier_value]
    return int(sub["constituent_id"].nunique()) >= min_n


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_multi_event_lookup(
    change_events_df: pd.DataFrame,
) -> dict[tuple[str, str, pd.Timestamp], list[dict[str, Any]]]:
    """Pre-group change events by (contributor, constituent, date), sorted by slot.

    Multi-event-aware (Phase 3 outlier-injection scenarios emit ≥2 events
    per day for fat-finger and intraday-spike patterns).
    """
    lookup: dict[tuple[str, str, pd.Timestamp], list[dict[str, Any]]] = {}
    if change_events_df.empty:
        return lookup
    for raw in change_events_df.to_dict("records"):
        rec: dict[str, Any] = {str(k): v for k, v in raw.items()}
        key = (
            str(rec["contributor_id"]),
            str(rec["constituent_id"]),
            pd.Timestamp(rec["event_date"]),
        )
        lookup.setdefault(key, []).append(rec)
    for key in lookup:
        lookup[key].sort(key=lambda r: int(r["change_slot_idx"]))
    return lookup


def _slot_prices_from_panel_row(
    *,
    panel_price: float,
    events: list[dict[str, Any]],
    price_field: str = "output_price_usd_mtok",
) -> npt.NDArray[np.float64]:
    """Build the 32-slot price array for one (contributor, constituent, date).

    Mirrors the segmentation logic in ``tprr.twap.reconstruct.reconstruct_slots``
    but operates on a pre-filtered events list (no per-row DataFrame scan).
    Returns ``[panel_price] * 32`` when ``events`` is empty.
    """
    if not events:
        return np.full(_TWAP_SLOTS, panel_price, dtype=np.float64)
    slots = np.empty(_TWAP_SLOTS, dtype=np.float64)
    first = events[0]
    first_slot = int(first["change_slot_idx"])
    slots[:first_slot] = float(first[f"old_{price_field}"])
    for i, ev in enumerate(events):
        current_slot = int(ev["change_slot_idx"])
        current_new = float(ev[f"new_{price_field}"])
        end_slot = int(events[i + 1]["change_slot_idx"]) if i + 1 < len(events) else _TWAP_SLOTS
        slots[current_slot:end_slot] = current_new
    return slots


def _empty_excluded_slots() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contributor_id": pd.Series([], dtype="object"),
            "constituent_id": pd.Series([], dtype="object"),
            "date": pd.Series([], dtype="datetime64[ns]"),
            "slot_idx": pd.Series([], dtype="int64"),
        }
    )


def _empty_suspensions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contributor_id": pd.Series([], dtype="object"),
            "constituent_id": pd.Series([], dtype="object"),
            "suspension_date": pd.Series([], dtype="datetime64[ns]"),
        }
    )
