"""Phase 3.2 scenario composers — translate ScenarioSpec into primitive calls.

One composer function per scenario kind, mapping the validated YAML
parameters (config.py :: ScenarioEntry subclasses) into calls on
outliers.py primitives. Composers are pure: input DataFrames /
``ModelRegistry`` are not modified in place; new objects are returned.

Usage::

    panel_out, events_out, registry_out = compose_scenario(
        spec, panel_df, events_df, registry, contributors,
        backtest_start, seed, manifest,
    )

The dispatcher ``compose_scenario`` matches on ``spec.kind`` and routes to
the right composer. ``NotImplementedError`` is raised for kinds queued for
later batches.

For multi-event days (fat_finger spike+revert, intraday_spike), composers
inject two ChangeEvent records on the same (contributor, constituent,
date) key, then call ``_retwap_for_key`` to recompute the panel's stored
TWAP via ``reconstruct_slots`` + ``compute_daily_twap``. The panel's price
column on event days carries the TWAP semantic (decision log 2026-04-24),
so this re-TWAP keeps the panel consistent with the post-injection
events_df.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tprr.config import (
    ContributorPanel,
    ContributorProfile,
    CorrelatedBlackoutSpec,
    FatFingerSpec,
    IntradaySpikeSpec,
    ModelMetadata,
    ModelRegistry,
    NewModelLaunchSpec,
    RegimeShiftSpec,
    ScenarioEntry,
    ShockPriceCutSpec,
    StaleQuoteSpec,
    SustainedManipulationSpec,
    TierReshuffleSpec,
)
from tprr.mockdata.change_events import (
    CONTRIB_JITTER_SIGMA,
    PUBLICATION_SLOT_MEAN,
    PUBLICATION_SLOT_SIGMA,
)
from tprr.mockdata.outliers import (
    ScenarioManifest,
    freeze_pair_in_window,
    inject_change_events,
    mutate_registry,
    override_panel_prices,
    regenerate_constituent_slice,
    remove_panel_rows,
    suppress_events,
)
from tprr.mockdata.pricing import _stable_int
from tprr.schema import Tier
from tprr.twap.reconstruct import compute_daily_twap, reconstruct_slots

_MAX_SLOT_IDX = 31

# Pre-flight check half-window: scenarios with event-clear-day annotations
# must have NO natural events for their target pair(s) within +/- this many
# days of the scenario's day_offset, on the current seed.
_PREFLIGHT_WINDOW_DAYS = 5


def preflight_event_clear_check(
    spec: ScenarioEntry,
    events_df: pd.DataFrame,
    contributors: ContributorPanel,
    backtest_start: date,
    *,
    window_days: int = _PREFLIGHT_WINDOW_DAYS,
) -> None:
    """Verify scenario's target day is event-clear within +/- ``window_days``.

    Applies only to scenarios where event-clear-day is load-bearing for the
    design at the (contributor, constituent) pair level — i.e. scenarios
    1 (``fat_finger_high``), 2 (``fat_finger_low``), and 9
    (``intraday_spike``). For other kinds (including
    ``shock_price_cut``, whose day annotation tracks provider-level step
    events at a different semantic layer) this is a no-op. Per Matt's
    Batch E spec: "For scenarios with event-clear-day annotations (1, 2,
    9 today; future scenarios may add)".

    Window semantics — STRICT inequality on both ends. An event is a
    collision iff ``|event_date - target_date| < window_days``. An event
    exactly ``window_days`` away on either side is NOT a collision (this
    matches scenarios.yaml's historical day-203 annotation, which placed
    that scenario exactly 5 days after a natural day-198 step event and
    considered day 203 "clear"). The intent: a window-edge event is far
    enough that the index has absorbed its TWAP impact before the
    scenario's target day; only events strictly closer can confound
    scenario-driven analysis.

    Raises ``ValueError`` on collision with a detailed message naming the
    scenario, target pair(s), and colliding event date(s). Suggests user
    actions: re-verify against current seed, shift the date in
    scenarios.yaml manually, or change seed. **Does NOT silently shift
    dates** — annotation rot must surface as a failure, not be hidden
    behind apparent success.

    Pair selection by kind:
      * ``fat_finger``, ``intraday_spike``: the single
        ``(target.contributor_id, target.constituent_id)`` pair.
    """
    _ = contributors  # kept in signature for future scenarios that may need it
    if isinstance(spec, FatFingerSpec | IntradaySpikeSpec):
        target_pairs = [(spec.target.contributor_id, spec.target.constituent_id)]
        day_offset = spec.timing.day_offset
    else:
        return  # No pre-flight requirement for this kind.

    target_date = backtest_start + timedelta(days=day_offset)
    window_start = target_date - timedelta(days=window_days)
    window_end = target_date + timedelta(days=window_days)

    collisions: list[tuple[str, str, pd.Timestamp]] = []
    for contrib_id, constituent_id in target_pairs:
        # Strict inequalities: an event exactly window_days away is NOT a
        # collision (see docstring).
        mask = (
            (events_df["contributor_id"] == contrib_id)
            & (events_df["constituent_id"] == constituent_id)
            & (events_df["event_date"] > pd.Timestamp(window_start))
            & (events_df["event_date"] < pd.Timestamp(window_end))
        )
        for ev_date in events_df.loc[mask, "event_date"].unique():
            collisions.append((contrib_id, constituent_id, pd.Timestamp(ev_date)))

    if not collisions:
        return

    msg_lines = [
        f"scenario {spec.id!r}: pre-flight event-clear-day check FAILED — "
        f"natural events collide with the day_offset annotation",
        f"  scenario kind:    {spec.kind}",
        f"  target day_offset: {day_offset} ({target_date.isoformat()})",
        f"  +/-{window_days}-day window: [{window_start.isoformat()}, {window_end.isoformat()}]",
        "  colliding events:",
    ]
    for c, m, d in sorted(collisions, key=lambda t: (t[2].toordinal(), t[0], t[1])):
        msg_lines.append(f"    ({c!r}, {m!r}) on {d.date().isoformat()}")
    msg_lines.extend(
        [
            "",
            "Action options (do NOT silently shift the scenario date):",
            "  1. Re-verify scenarios.yaml against the current seed — confirm",
            "     the day_offset annotation is still accurate after any seed",
            "     or registry change.",
            "  2. Shift day_offset in scenarios.yaml manually to a verified-clear day,",
            "     and log the shift in the scenario's `notes` field.",
            "  3. Change seed — but then re-verify ALL scenarios against the",
            "     new seed, since their event-clear-day annotations are seed-",
            "     specific.",
        ]
    )
    raise ValueError("\n".join(msg_lines))


def compose_scenario(
    spec: ScenarioEntry,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    contributors: ContributorPanel,
    backtest_start: date,
    seed: int,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """Dispatch ``spec`` to the right per-kind composer.

    Returns ``(panel_out, events_out, registry_out)`` — new objects, never
    in-place mutations.
    """
    _ = contributors  # reserved for kinds that need full panel context
    _ = seed  # reserved for stochastic kinds (regenerate_constituent_slice)

    if isinstance(spec, FatFingerSpec):
        return _compose_fat_finger(spec, panel_df, events_df, registry, backtest_start, manifest)
    if isinstance(spec, StaleQuoteSpec):
        return _compose_stale_quote(spec, panel_df, events_df, registry, backtest_start, manifest)
    if isinstance(spec, IntradaySpikeSpec):
        return _compose_intraday_spike(
            spec, panel_df, events_df, registry, backtest_start, manifest
        )
    if isinstance(spec, CorrelatedBlackoutSpec):
        return _compose_correlated_blackout(
            spec, panel_df, events_df, registry, backtest_start, manifest
        )
    if isinstance(spec, ShockPriceCutSpec):
        return _compose_shock_price_cut(
            spec,
            panel_df,
            events_df,
            registry,
            contributors,
            backtest_start,
            seed,
            manifest,
        )
    if isinstance(spec, SustainedManipulationSpec):
        return _compose_sustained_manipulation(
            spec, panel_df, events_df, registry, backtest_start, manifest
        )
    if isinstance(spec, NewModelLaunchSpec):
        return _compose_new_model_launch(
            spec,
            panel_df,
            events_df,
            registry,
            contributors,
            backtest_start,
            seed,
            manifest,
        )
    if isinstance(spec, TierReshuffleSpec):
        return _compose_tier_reshuffle(
            spec, panel_df, events_df, registry, backtest_start, manifest
        )
    if isinstance(spec, RegimeShiftSpec):
        return _compose_regime_shift(
            spec,
            panel_df,
            events_df,
            registry,
            contributors,
            backtest_start,
            seed,
            manifest,
        )
    # Defensive: a new ScenarioEntry subclass added without a composer.
    raise NotImplementedError(  # pragma: no cover
        f"no composer dispatch for scenario type {type(spec).__name__}"
    )


# ---------------------------------------------------------------------------
# Per-kind composers
# ---------------------------------------------------------------------------


def _compose_fat_finger(
    spec: FatFingerSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    backtest_start: date,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """fat_finger_{high,low}: spike at ``slot``, revert ``after_slots`` later.

    Injects two ChangeEvents on a single (contributor, constituent, date)
    key — slot S = spike up, slot S+N = revert down. Multiplier applies
    uniformly to input and output prices (single API misconfiguration
    typically affects both axes identically).

    Event-clear-day annotation is enforced by ``preflight_event_clear_check``
    in the script entry point (``scripts/generate_mock_data.py``).
    """
    event_date = backtest_start + timedelta(days=spec.timing.day_offset)
    contrib = spec.target.contributor_id
    constituent = spec.target.constituent_id
    spike_slot = spec.timing.slot
    revert_slot = spike_slot + spec.revert.after_slots

    if revert_slot > _MAX_SLOT_IDX:
        raise ValueError(
            f"scenario {spec.id!r}: revert slot {revert_slot} (= spike "
            f"{spike_slot} + after_slots {spec.revert.after_slots}) exceeds "
            f"maximum slot index {_MAX_SLOT_IDX}"
        )

    base_in, base_out = _get_panel_prices(panel_df, contrib, constituent, event_date)
    spiked_in = base_in * spec.magnitude.multiplier
    spiked_out = base_out * spec.magnitude.multiplier

    events_out, op_record = inject_change_events(
        events_df,
        [
            {
                "event_date": event_date,
                "contributor_id": contrib,
                "constituent_id": constituent,
                "change_slot_idx": spike_slot,
                "old_input_price_usd_mtok": base_in,
                "new_input_price_usd_mtok": spiked_in,
                "old_output_price_usd_mtok": base_out,
                "new_output_price_usd_mtok": spiked_out,
            },
            {
                "event_date": event_date,
                "contributor_id": contrib,
                "constituent_id": constituent,
                "change_slot_idx": revert_slot,
                "old_input_price_usd_mtok": spiked_in,
                "new_input_price_usd_mtok": base_in,
                "old_output_price_usd_mtok": spiked_out,
                "new_output_price_usd_mtok": base_out,
            },
        ],
    )
    manifest.record(op_record)

    panel_out = _retwap_for_key(panel_df, events_out, contrib, constituent, event_date)
    return panel_out, events_out, registry


def _compose_stale_quote(
    spec: StaleQuoteSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    backtest_start: date,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """stale_quote: freeze pair's price across a window via freeze_pair_in_window."""
    start = backtest_start + timedelta(days=spec.timing.day_offset_start)
    end = start + timedelta(days=spec.timing.duration_days - 1)
    panel_out, events_out, op_records = freeze_pair_in_window(
        panel_df,
        events_df,
        contributor_id=spec.target.contributor_id,
        constituent_id=spec.target.constituent_id,
        date_range=(start, end),
        freeze_price_source=spec.freeze_price_source,
    )
    for rec in op_records:
        manifest.record(rec)
    return panel_out, events_out, registry


def _compose_intraday_spike(
    spec: IntradaySpikeSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    backtest_start: date,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """intraday_spike: off-market price across [slot_start, slot_end] inclusive.

    Spike begins at ``slot_start`` and reverts at ``revert.at_slot``. The
    composer enforces ``revert.at_slot == slot_end + 1`` so the spike
    covers exactly the documented inclusive slot range. Multiplier applies
    uniformly to input and output prices.

    Event-clear-day annotation is enforced by ``preflight_event_clear_check``
    in the script entry point (``scripts/generate_mock_data.py``).
    """
    expected_revert = spec.timing.slot_end + 1
    if spec.revert.at_slot != expected_revert:
        raise ValueError(
            f"scenario {spec.id!r}: revert.at_slot ({spec.revert.at_slot}) "
            f"must be slot_end + 1 ({expected_revert}) so the spike covers "
            f"exactly the inclusive range "
            f"[{spec.timing.slot_start}, {spec.timing.slot_end}]"
        )

    event_date = backtest_start + timedelta(days=spec.timing.day_offset)
    contrib = spec.target.contributor_id
    constituent = spec.target.constituent_id

    base_in, base_out = _get_panel_prices(panel_df, contrib, constituent, event_date)
    spiked_in = base_in * spec.magnitude.multiplier
    spiked_out = base_out * spec.magnitude.multiplier

    events_out, op_record = inject_change_events(
        events_df,
        [
            {
                "event_date": event_date,
                "contributor_id": contrib,
                "constituent_id": constituent,
                "change_slot_idx": spec.timing.slot_start,
                "old_input_price_usd_mtok": base_in,
                "new_input_price_usd_mtok": spiked_in,
                "old_output_price_usd_mtok": base_out,
                "new_output_price_usd_mtok": spiked_out,
            },
            {
                "event_date": event_date,
                "contributor_id": contrib,
                "constituent_id": constituent,
                "change_slot_idx": spec.revert.at_slot,
                "old_input_price_usd_mtok": spiked_in,
                "new_input_price_usd_mtok": base_in,
                "old_output_price_usd_mtok": spiked_out,
                "new_output_price_usd_mtok": base_out,
            },
        ],
    )
    manifest.record(op_record)

    panel_out = _retwap_for_key(panel_df, events_out, contrib, constituent, event_date)
    return panel_out, events_out, registry


def _compose_correlated_blackout(
    spec: CorrelatedBlackoutSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    backtest_start: date,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """correlated_blackout: drop panel rows + events for two+ contributors in window.

    For each contributor in ``target.contributor_ids``, removes panel rows
    and suppresses change events whose ``date in [start, end]``. Across all
    constituents that contributor covers (the filter does not specify
    ``constituent_id``).
    """
    start = backtest_start + timedelta(days=spec.timing.day_offset_start)
    end = start + timedelta(days=spec.timing.duration_days - 1)

    panel_out = panel_df
    events_out = events_df
    for contrib_id in spec.target.contributor_ids:
        panel_out, panel_rec = remove_panel_rows(
            panel_out,
            contributor_id=contrib_id,
            date_range=(start, end),
        )
        manifest.record(panel_rec)
        events_out, events_rec = suppress_events(
            events_out,
            contributor_id=contrib_id,
            date_range=(start, end),
        )
        manifest.record(events_rec)

    return panel_out, events_out, registry


def _compose_shock_price_cut(
    spec: ShockPriceCutSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    contributors: ContributorPanel,
    backtest_start: date,
    seed: int,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """shock_price_cut: provider-level step propagated to all covering contributors.

    Single provider event fans out to one ChangeEvent per covering
    contributor, each with per-contributor jitter ``Normal(0, 2)`` around a
    shared publication slot drawn from ``Normal(16, 6)`` clipped to
    ``[0, 31]``. Determinism: SeedSequence keys mirror Phase 2b's
    propagated-event scheme but use distinct substream tags
    (``"scenario_shock_cut"``, ``"scenario_shock_cut_jitter"``) so this
    fan-out cannot collide with Phase 2 propagation streams.
    Reason tag: ``outlier_injection`` (default of ``inject_change_events``).
    Multiplier applies uniformly to input and output prices.

    Re-TWAPs each affected (contributor, constituent, date) panel row via
    multi-event-aware reconstruction in case Phase 2 events already exist
    for some contributors on this day.
    """
    if any(spec.notes):
        for note in spec.notes:
            manifest.add_note(note)

    event_date = backtest_start + timedelta(days=spec.timing.day_offset)
    constituent_id = spec.target.constituent_id
    multiplier = spec.magnitude.multiplier

    covering = [
        p.contributor_id for p in contributors.contributors if constituent_id in p.covered_models
    ]
    if not covering:
        raise ValueError(f"scenario {spec.id!r}: no contributors cover {constituent_id!r}")

    publication_slot = _draw_publication_slot(
        seed, constituent_id, event_date, tag="scenario_shock_cut"
    )

    new_events: list[dict[str, Any]] = []
    for contrib_id in covering:
        slot = _draw_jittered_slot(
            seed,
            contrib_id,
            constituent_id,
            event_date,
            publication_slot,
            tag="scenario_shock_cut_jitter",
        )
        base_in, base_out = _get_panel_prices(panel_df, contrib_id, constituent_id, event_date)
        new_in = base_in * multiplier
        new_out = base_out * multiplier
        new_events.append(
            {
                "event_date": event_date,
                "contributor_id": contrib_id,
                "constituent_id": constituent_id,
                "change_slot_idx": slot,
                "old_input_price_usd_mtok": base_in,
                "new_input_price_usd_mtok": new_in,
                "old_output_price_usd_mtok": base_out,
                "new_output_price_usd_mtok": new_out,
            }
        )

    events_out, op_record = inject_change_events(events_df, new_events)
    manifest.record(op_record)

    panel_out = panel_df
    for contrib_id in covering:
        panel_out = _retwap_for_key(panel_out, events_out, contrib_id, constituent_id, event_date)
    return panel_out, events_out, registry


def _compose_sustained_manipulation(
    spec: SustainedManipulationSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    backtest_start: date,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """sustained_manipulation: contributor sustains tier-median * multiplier daily.

    Tier-median proxy at scenario-injection time: for each S constituent
    other than the manipulator's target, the constituent's day-D price is
    the **median across its contributors' panel TWAPs** (mirrors the
    methodology's median-for-robustness choice in Section 3.3.3); the
    tier median is then the **median across those constituent-level
    prices**. The manipulator's panel row for the target constituent is
    overridden daily to ``(median_input * mult, median_output * mult)``.

    Excludes the entire target constituent from the median pool — not just
    the manipulator's individual contribution — to remove the feedback
    path completely (manipulator actions on their constituent shouldn't
    feed back into the reference even via other contributors' aggregate
    on the same constituent).

    Events for the manipulator's pair in window are suppressed so the
    panel-stored override is the day's price (no event-driven re-TWAP
    shifts it off the median target).

    v0.1 raises on any day where median computation fails (e.g., no panel
    rows for a non-target S constituent on that day). Future scenario
    combinations may need forward-fill or skip-day policy; defer until
    needed.
    """
    start = backtest_start + timedelta(days=spec.timing.day_offset_start)
    end = start + timedelta(days=spec.timing.duration_days - 1)
    target_contrib = spec.target.contributor_id
    target_constituent = spec.target.constituent_id
    multiplier = spec.manipulation.multiplier

    s_other = {
        m.constituent_id
        for m in registry.models
        if m.tier == Tier.TPRR_S and m.constituent_id != target_constituent
    }
    if not s_other:
        raise ValueError(
            f"scenario {spec.id!r}: no S constituents other than "
            f"{target_constituent!r} — cannot compute tier median"
        )

    medians_by_date = _compute_daily_tier_medians(
        panel_df, s_other, start, end, scenario_id=spec.id
    )

    events_out, suppress_rec = suppress_events(
        events_df,
        contributor_id=target_contrib,
        constituent_id=target_constituent,
        date_range=(start, end),
    )
    manifest.record(suppress_rec)

    def _manipulation_price_fn(row: dict[str, Any]) -> tuple[float, float]:
        d = pd.Timestamp(row["observation_date"])
        median_in, median_out = medians_by_date[d]
        return median_in * multiplier, median_out * multiplier

    panel_out, override_rec = override_panel_prices(
        panel_df,
        _manipulation_price_fn,
        contributor_id=target_contrib,
        constituent_id=target_constituent,
        date_range=(start, end),
    )
    manifest.record(override_rec)

    return panel_out, events_out, registry


def _compose_new_model_launch(
    spec: NewModelLaunchSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    contributors: ContributorPanel,
    backtest_start: date,
    seed: int,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """new_model_launch: bootstrap a new constituent from launch day to backtest end.

    Adds the new constituent to ``registry`` via ``mutate_registry``, then
    extends the covering contributors' ``covered_models`` lists to include
    the new constituent for the bootstrap. Calls
    ``regenerate_constituent_slice`` in new-constituent mode (auto-detected
    from the constituent being absent from the panel), which runs the full
    Phase 2 pipeline on a mini-registry / mini-panel for the launch window.
    Backtest-end day is derived from the input panel's max
    ``observation_date``.

    Standard tier dynamics — no sigma/mu/rate overrides. New constituent's
    price walk uses its tier's default parameters per
    ``mockdata.pricing.TIER_PARAMS``.
    """
    launch_date = backtest_start + timedelta(days=spec.timing.day_offset)
    backtest_end = pd.Timestamp(panel_df["observation_date"].max()).date()

    new_model = ModelMetadata(
        constituent_id=spec.new_model.constituent_id,
        tier=spec.new_model.tier,
        provider=spec.new_model.provider,
        canonical_name=spec.new_model.canonical_name,
        baseline_input_price_usd_mtok=spec.new_model.baseline_input_price_usd_mtok,
        baseline_output_price_usd_mtok=spec.new_model.baseline_output_price_usd_mtok,
    )

    registry_out, mutate_rec = mutate_registry(registry, {"type": "add_model", "model": new_model})
    manifest.record(mutate_rec)

    coverage_set = set(spec.coverage.contributor_ids)
    extended_contributors = ContributorPanel(
        contributors=[
            ContributorProfile(
                contributor_id=p.contributor_id,
                profile_name=p.profile_name,
                volume_scale=p.volume_scale,
                price_bias_pct=p.price_bias_pct,
                daily_noise_sigma_pct=p.daily_noise_sigma_pct,
                error_rate=p.error_rate,
                covered_models=(
                    [*p.covered_models, new_model.constituent_id]
                    if p.contributor_id in coverage_set
                    else list(p.covered_models)
                ),
            )
            for p in contributors.contributors
        ]
    )

    panel_out, events_out, regen_rec = regenerate_constituent_slice(
        panel_df,
        events_df,
        new_model,
        extended_contributors,
        (launch_date, backtest_end),
        seed=seed,
    )
    manifest.record(regen_rec)
    return panel_out, events_out, registry_out


def _compose_tier_reshuffle(
    spec: TierReshuffleSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    backtest_start: date,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """tier_reshuffle: Index Committee reclassification of a constituent.

    Per docs/decision_log.md 2026-04-27 — panel-as-truth, no warmup
    (Reading A). Composer flow:

      1. ``mutate_registry`` updates the constituent's ``ModelMetadata.tier``
         to the new value.
      2. Panel ``tier_code`` column is rewritten from old to new for that
         constituent on ``observation_date >= effective_date``. Pre-effective
         rows retain the old tier_code (historical truth).

    Events carry no ``tier_code`` so are untouched. The 5-day quality-gate
    trailing window (Section 4.2.2) and tier median (Section 3.3.3) consume
    the panel's per-row ``tier_code`` on each day; no warmup period is
    imposed on a reclassified constituent.

    Known limitation flagged in manifest note: ``ModelMetadata`` carries one
    current tier (no temporal model). Phase 7 must read ``tier_code`` from
    the panel, not the registry, when computing per-day tier membership.
    """
    effective_date = backtest_start + timedelta(days=spec.timing.day_offset)
    constituent_id = spec.target.constituent_id
    new_tier = spec.new_tier

    registry_out, mutate_rec = mutate_registry(
        registry,
        {
            "type": "tier_change",
            "constituent_id": constituent_id,
            "new_tier": new_tier,
            "effective_date": effective_date,
        },
    )
    manifest.record(mutate_rec)

    panel_out = _rewrite_panel_tier_code(panel_df, constituent_id, new_tier, effective_date)

    manifest.add_note(
        f"tier_reshuffle: registry holds single-valued tier "
        f"(post-change={new_tier.value}); per-day tier membership truth is "
        f"panel.tier_code, not registry. Phase 7 must read tier_code from "
        f"the panel for dates < {effective_date.isoformat()}."
    )

    return panel_out, events_df, registry_out


def _compose_regime_shift(
    spec: RegimeShiftSpec,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    registry: ModelRegistry,
    contributors: ContributorPanel,
    backtest_start: date,
    seed: int,
    manifest: ScenarioManifest,
) -> tuple[pd.DataFrame, pd.DataFrame, ModelRegistry]:
    """regime_shift: regenerate target tier's constituents under override dynamics.

    For each constituent in ``spec.tier``, calls
    ``regenerate_constituent_slice`` with the spec's sigma/mu/step_rate
    overrides. In-window events for each target constituent are suppressed
    (handled inside ``regenerate_constituent_slice``). Post-window panel
    rows are byte-identical to pre-composition input — the random walks
    land where they land on the last in-window day, with no re-anchoring
    on day_offset_start + duration_days. Pre-window rows are likewise
    byte-identical.

    Seed independence across the 4 S constituents: each constituent's
    ``regenerate_constituent_slice`` call receives the same ``seed``
    parameter, but the SeedSequence inside that function keys on
    ``(seed, "scenario_regen", contributor_id, constituent_id,
    start_ordinal)``. Different ``constituent_id`` values produce
    different ``_stable_int`` digests and hence independent RNG streams
    per constituent. Verified empirically by the pairwise-correlation test
    in tests/test_scenarios.py.

    v0.1 enforces ``step_rate_per_year == 0`` (matches the
    schema-vs-composer note in ``_RegimeShiftDynamics``):
    ``regenerate_constituent_slice`` does not yet support emitting new
    in-window events for existing constituents. Future v0.2 may relax
    via a parameters-inject API on ``pricing.py``.
    """
    if spec.dynamics.step_rate_per_year != 0:
        raise ValueError(
            f"scenario {spec.id!r}: v0.1 regime_shift composer requires "
            f"step_rate_per_year == 0 (got "
            f"{spec.dynamics.step_rate_per_year}); future versions may "
            f"relax via parameters-inject API on pricing.py"
        )

    start = backtest_start + timedelta(days=spec.timing.day_offset_start)
    end = start + timedelta(days=spec.timing.duration_days - 1)

    target_constituents = [m for m in registry.models if m.tier == spec.tier]
    if not target_constituents:
        raise ValueError(f"scenario {spec.id!r}: no constituents in tier {spec.tier!r}")

    panel_out = panel_df
    events_out = events_df
    for model in target_constituents:
        panel_out, events_out, regen_rec = regenerate_constituent_slice(
            panel_out,
            events_out,
            model,
            contributors,
            (start, end),
            seed=seed,
            sigma_daily=spec.dynamics.sigma_daily,
            mu_daily=spec.dynamics.mu_daily,
            step_rate_per_year=spec.dynamics.step_rate_per_year,
        )
        manifest.record(regen_rec)

    return panel_out, events_out, registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_panel_prices(
    panel_df: pd.DataFrame,
    contributor_id: str,
    constituent_id: str,
    event_date: date,
) -> tuple[float, float]:
    """Return ``(input_price, output_price)`` for the panel row on the given key."""
    ts = pd.Timestamp(event_date)
    mask = (
        (panel_df["observation_date"] == ts)
        & (panel_df["contributor_id"] == contributor_id)
        & (panel_df["constituent_id"] == constituent_id)
    )
    rows = panel_df.loc[mask]
    if len(rows) == 0:
        raise ValueError(
            f"no panel row for ({contributor_id!r}, {constituent_id!r}, {event_date.isoformat()})"
        )
    row = rows.iloc[0]
    return float(row["input_price_usd_mtok"]), float(row["output_price_usd_mtok"])


def _retwap_for_key(
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    contributor_id: str,
    constituent_id: str,
    event_date: date,
) -> pd.DataFrame:
    """Rewrite panel's input/output prices for one key using multi-event TWAP.

    Used after injecting multiple events on the same day. Calls Phase 2c's
    multi-event-aware ``reconstruct_slots`` and ``compute_daily_twap`` to
    recompute the panel's stored TWAP, then writes both back to the
    matching panel row.
    """
    ts = pd.Timestamp(event_date)
    out_slots = reconstruct_slots(
        contributor_id,
        constituent_id,
        ts,
        panel_df,
        events_df,
        price_field="output_price_usd_mtok",
    )
    in_slots = reconstruct_slots(
        contributor_id,
        constituent_id,
        ts,
        panel_df,
        events_df,
        price_field="input_price_usd_mtok",
    )
    twap_out = compute_daily_twap(out_slots)
    twap_in = compute_daily_twap(in_slots)

    out = panel_df.copy()
    mask = (
        (out["observation_date"] == ts)
        & (out["contributor_id"] == contributor_id)
        & (out["constituent_id"] == constituent_id)
    )
    out.loc[mask, "output_price_usd_mtok"] = twap_out
    out.loc[mask, "input_price_usd_mtok"] = twap_in
    return out


def _rewrite_panel_tier_code(
    panel_df: pd.DataFrame,
    constituent_id: str,
    new_tier: Tier,
    effective_date: date,
) -> pd.DataFrame:
    """Rewrite ``tier_code`` for one constituent's rows on/after ``effective_date``.

    Pre-effective rows retain their original tier_code. Defensive against
    categorical-dtyped tier_code columns: adds the new tier value as a
    category before assignment if needed.
    """
    out = panel_df.copy()
    mask = (out["constituent_id"] == constituent_id) & (
        out["observation_date"] >= pd.Timestamp(effective_date)
    )
    if (
        isinstance(out["tier_code"].dtype, pd.CategoricalDtype)
        and new_tier.value not in out["tier_code"].cat.categories
    ):
        out["tier_code"] = out["tier_code"].cat.add_categories([new_tier.value])
    out.loc[mask, "tier_code"] = new_tier.value
    return out


def _draw_publication_slot(seed: int, constituent_id: str, event_date: date, *, tag: str) -> int:
    """Draw a publication slot from ``Normal(16, 6)`` clipped to ``[0, 31]``.

    Mirrors the Phase 2b propagated-event publication-slot draw. ``tag``
    distinguishes scenario substreams from Phase 2's stream so the two
    cannot collide.
    """
    ss = np.random.SeedSequence(
        [seed, _stable_int(tag), _stable_int(constituent_id), pd.Timestamp(event_date).toordinal()]
    )
    rng = np.random.default_rng(ss)
    return int(
        np.clip(
            round(rng.normal(PUBLICATION_SLOT_MEAN, PUBLICATION_SLOT_SIGMA)),
            0,
            _MAX_SLOT_IDX,
        )
    )


def _draw_jittered_slot(
    seed: int,
    contributor_id: str,
    constituent_id: str,
    event_date: date,
    publication_slot: int,
    *,
    tag: str,
) -> int:
    """Per-contributor jitter ``Normal(0, 2)`` around ``publication_slot``."""
    ss = np.random.SeedSequence(
        [
            seed,
            _stable_int(tag),
            _stable_int(contributor_id),
            _stable_int(constituent_id),
            pd.Timestamp(event_date).toordinal(),
        ]
    )
    rng = np.random.default_rng(ss)
    jitter = rng.normal(0.0, CONTRIB_JITTER_SIGMA)
    return int(np.clip(round(publication_slot + jitter), 0, _MAX_SLOT_IDX))


def _compute_daily_tier_medians(
    panel_df: pd.DataFrame,
    constituent_pool: set[str],
    start: date,
    end: date,
    *,
    scenario_id: str,
) -> dict[pd.Timestamp, tuple[float, float]]:
    """Per-day median across constituents of within-constituent contributor medians.

    Methodology mirror (Section 3.3.3 uses median for robustness):
      step 1 — for each (date, constituent) in ``constituent_pool``,
                median across that constituent's contributors' panel TWAPs
      step 2 — for each date, median across constituent-level prices

    Raises ``ValueError`` if any day in ``[start, end]`` lacks a median
    (no panel rows for any constituent in the pool on that day).
    """
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    mask = (
        panel_df["constituent_id"].isin(constituent_pool)
        & (panel_df["observation_date"] >= start_ts)
        & (panel_df["observation_date"] <= end_ts)
    )
    s_window = panel_df.loc[
        mask,
        [
            "observation_date",
            "constituent_id",
            "input_price_usd_mtok",
            "output_price_usd_mtok",
        ],
    ]

    constituent_medians = s_window.groupby(["observation_date", "constituent_id"], observed=True)[
        ["input_price_usd_mtok", "output_price_usd_mtok"]
    ].median()
    date_medians = constituent_medians.groupby(level="observation_date").median()

    expected_days = pd.date_range(start_ts, end_ts, freq="D")
    missing = sorted(set(expected_days) - set(date_medians.index))
    if missing:
        raise ValueError(
            f"scenario {scenario_id!r}: no tier-median data for days "
            f"{[str(d.date()) for d in missing]}"
        )

    out: dict[pd.Timestamp, tuple[float, float]] = {}
    for ts, row in date_medians.iterrows():
        # ts is the observation_date index — guaranteed Timestamp by the
        # groupby on a datetime64 column; cast keeps mypy --strict satisfied
        # since iterrows() types the index as Hashable.
        ts_norm = pd.Timestamp(ts)  # type: ignore[arg-type]
        out[ts_norm] = (
            float(row["input_price_usd_mtok"]),
            float(row["output_price_usd_mtok"]),
        )
    return out
