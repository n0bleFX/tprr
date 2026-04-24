"""Phase 3 outlier-injection primitives.

Six pure mutation operations on the synthetic panel + change-events, one
convenience wrapper, and a ScenarioManifest dataclass for audit trail. Phase
3.2 composes these into the ten scenarios locked in the design review
(docs/findings/pricing_model_design.md; scenarios locked per 2026-04-24
decision log entries).

Primitives:
  1. inject_change_events          append outlier-tagged ChangeEvent rows
  2. suppress_events               remove ChangeEvent rows matching a filter
  3. remove_panel_rows             drop panel rows matching a filter
  4. override_panel_prices         replace input/output prices via callable
  5. mutate_registry               change ModelMetadata (tier / new model / active_from)
  6. regenerate_constituent_slice  re-run Phase 2 slice for one constituent
                                   over a date range, with optional param
                                   overrides (new-constituent bootstrap OR
                                   existing-constituent dynamics override)

Wrapper:
  freeze_pair_in_window   composes (suppress_events + override_panel_prices)
                          into one semantic call. Used by scenarios 3, 6.

All primitives are pure: they return new DataFrames/objects; no in-place
mutation. Each call returns a ``(new_state, op_record)`` tuple where
``op_record`` is a dict summarising what the operation did. Scenario
composers (Phase 3.2) record these into a ``ScenarioManifest``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tprr.config import ContributorPanel, ContributorProfile, ModelMetadata, ModelRegistry
from tprr.mockdata.change_events import apply_twap_to_panel, generate_change_events
from tprr.mockdata.contributors import generate_contributor_panel
from tprr.mockdata.pricing import TIER_PARAMS, _stable_int, generate_baseline_prices
from tprr.mockdata.volume import generate_volumes
from tprr.schema import AttestationTier

_CHANGE_EVENT_COLUMNS = [
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


# ---------------------------------------------------------------------------
# ScenarioManifest
# ---------------------------------------------------------------------------


@dataclass
class ScenarioManifest:
    """Audit record of what a scenario's composed operations changed.

    Populated by a scenario composer (Phase 3.2) via ``record()`` per operation.
    Persisted via ``write()`` to
    ``data/raw/scenarios/{scenario_id}_seed{seed}_manifest.json``.
    """

    scenario_id: str
    seed: int
    operations_applied: list[dict[str, Any]] = field(default_factory=list)
    panel_rows_modified: int = 0
    events_injected: int = 0
    events_suppressed: int = 0
    panel_rows_removed: int = 0
    registry_mutations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def record(self, op_record: dict[str, Any]) -> None:
        """Append an operation record and update the relevant counter."""
        self.operations_applied.append(op_record)
        op = op_record.get("op")
        if op == "inject_change_events":
            self.events_injected += int(op_record.get("n_injected", 0))
        elif op == "suppress_events":
            self.events_suppressed += int(op_record.get("n_suppressed", 0))
        elif op == "remove_panel_rows":
            self.panel_rows_removed += int(op_record.get("n_removed", 0))
        elif op == "override_panel_prices":
            self.panel_rows_modified += int(op_record.get("n_modified", 0))
        elif op == "mutate_registry":
            self.registry_mutations.append(op_record.get("mutation", {}))
        elif op == "regenerate_constituent_slice":
            self.panel_rows_modified += int(
                op_record.get("n_panel_rows_regenerated", 0)
            )
            self.events_injected += int(op_record.get("n_events_added", 0))
            self.events_suppressed += int(op_record.get("n_events_suppressed", 0))

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=_json_default, indent=2)

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = (
            output_dir
            / f"{self.scenario_id}_seed{self.seed}_manifest.json"
        )
        path.write_text(self.to_json(), encoding="utf-8")
        return path


def _json_default(obj: Any) -> str:
    """JSON fallback for dates, Timestamps, etc."""
    if hasattr(obj, "isoformat"):
        return str(obj.isoformat())
    return str(obj)


# ---------------------------------------------------------------------------
# Filter helper (shared by primitives 2, 3, 4)
# ---------------------------------------------------------------------------


def _build_filter_mask(
    df: pd.DataFrame,
    date_col: str,
    contributor_id: str | None,
    constituent_id: str | None,
    date_range: tuple[Any, Any] | None,
) -> pd.Series:
    """Boolean mask matching rows meeting all provided filter criteria.

    ``date_col`` is ``observation_date`` for panel_df, ``event_date`` for events_df.
    Raises if no filter criterion is supplied (would match all rows — dangerous).
    """
    if contributor_id is None and constituent_id is None and date_range is None:
        raise ValueError(
            "at least one filter (contributor_id, constituent_id, date_range) required"
        )
    mask = pd.Series(True, index=df.index)
    if contributor_id is not None:
        mask &= df["contributor_id"] == contributor_id
    if constituent_id is not None:
        mask &= df["constituent_id"] == constituent_id
    if date_range is not None:
        start = pd.Timestamp(date_range[0])
        end = pd.Timestamp(date_range[1])
        mask &= (df[date_col] >= start) & (df[date_col] <= end)
    return mask


def _filter_record(
    contributor_id: str | None,
    constituent_id: str | None,
    date_range: tuple[Any, Any] | None,
) -> dict[str, Any]:
    """Serializable filter description for op_record."""
    return {
        "contributor_id": contributor_id,
        "constituent_id": constituent_id,
        "date_range": (
            [str(pd.Timestamp(date_range[0]).date()), str(pd.Timestamp(date_range[1]).date())]
            if date_range is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Primitive 1: inject_change_events
# ---------------------------------------------------------------------------


def inject_change_events(
    events_df: pd.DataFrame,
    new_events: list[dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Append new ChangeEvent rows to ``events_df``.

    Each dict in ``new_events`` must have the ChangeEventDF schema fields.
    ``reason`` defaults to ``"outlier_injection"`` if omitted. Returns
    ``(combined_events_df, op_record)``.
    """
    if not new_events:
        return events_df.copy().reset_index(drop=True), {
            "op": "inject_change_events",
            "n_injected": 0,
        }

    rows: list[dict[str, Any]] = []
    for ev in new_events:
        row = dict(ev)
        row.setdefault("reason", "outlier_injection")
        row["event_date"] = pd.Timestamp(row["event_date"])
        rows.append(row)

    new_df = pd.DataFrame(rows)
    new_df["event_date"] = new_df["event_date"].astype("datetime64[ns]")
    new_df["change_slot_idx"] = new_df["change_slot_idx"].astype("int64")

    column_order = events_df.columns.tolist() if len(events_df.columns) else _CHANGE_EVENT_COLUMNS
    new_df = new_df[column_order]

    combined = pd.concat([events_df, new_df], ignore_index=True)
    return combined, {
        "op": "inject_change_events",
        "n_injected": len(new_events),
    }


# ---------------------------------------------------------------------------
# Primitive 2: suppress_events
# ---------------------------------------------------------------------------


def suppress_events(
    events_df: pd.DataFrame,
    *,
    contributor_id: str | None = None,
    constituent_id: str | None = None,
    date_range: tuple[Any, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Remove ChangeEvent rows matching the filter. Returns ``(filtered_df, op_record)``."""
    mask = _build_filter_mask(
        events_df, "event_date", contributor_id, constituent_id, date_range
    )
    n_suppressed = int(mask.sum())
    kept = events_df.loc[~mask].copy().reset_index(drop=True)
    return kept, {
        "op": "suppress_events",
        "n_suppressed": n_suppressed,
        "filter": _filter_record(contributor_id, constituent_id, date_range),
    }


# ---------------------------------------------------------------------------
# Primitive 3: remove_panel_rows
# ---------------------------------------------------------------------------


def remove_panel_rows(
    panel_df: pd.DataFrame,
    *,
    contributor_id: str | None = None,
    constituent_id: str | None = None,
    date_range: tuple[Any, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Drop panel rows matching the filter. Returns ``(filtered_df, op_record)``."""
    mask = _build_filter_mask(
        panel_df, "observation_date", contributor_id, constituent_id, date_range
    )
    n_removed = int(mask.sum())
    kept = panel_df.loc[~mask].copy().reset_index(drop=True)
    return kept, {
        "op": "remove_panel_rows",
        "n_removed": n_removed,
        "filter": _filter_record(contributor_id, constituent_id, date_range),
    }


# ---------------------------------------------------------------------------
# Primitive 4: override_panel_prices
# ---------------------------------------------------------------------------


def override_panel_prices(
    panel_df: pd.DataFrame,
    price_fn: Callable[[dict[str, Any]], tuple[float, float]],
    *,
    contributor_id: str | None = None,
    constituent_id: str | None = None,
    date_range: tuple[Any, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Replace ``input_price_usd_mtok`` / ``output_price_usd_mtok`` on matching rows.

    ``price_fn`` receives the current row as a dict and returns
    ``(new_input_price, new_output_price)``. Returns ``(modified_df, op_record)``.
    """
    mask = _build_filter_mask(
        panel_df, "observation_date", contributor_id, constituent_id, date_range
    )
    out = panel_df.copy()
    n_modified = 0
    for idx in out.index[mask]:
        rec = {k: out.at[idx, k] for k in out.columns}
        new_in, new_out = price_fn(rec)
        out.at[idx, "input_price_usd_mtok"] = float(new_in)
        out.at[idx, "output_price_usd_mtok"] = float(new_out)
        n_modified += 1
    return out, {
        "op": "override_panel_prices",
        "n_modified": n_modified,
        "filter": _filter_record(contributor_id, constituent_id, date_range),
    }


# ---------------------------------------------------------------------------
# Primitive 5: mutate_registry
# ---------------------------------------------------------------------------


def mutate_registry(
    registry: ModelRegistry,
    mutation: dict[str, Any],
) -> tuple[ModelRegistry, dict[str, Any]]:
    """Return a new ``ModelRegistry`` with the specified mutation applied.

    Mutation shapes::

        {"type": "tier_change",  "constituent_id": ..., "new_tier": Tier, "effective_date": str/date}
        {"type": "add_model",    "model": ModelMetadata}
        {"type": "active_from",  "constituent_id": ..., "active_from": date}

    Returns ``(new_registry, op_record)``.
    """
    mut_type = mutation.get("type")
    new_models = list(registry.models)

    if mut_type == "tier_change":
        cid = mutation["constituent_id"]
        new_tier = mutation["new_tier"]
        for i, m in enumerate(new_models):
            if m.constituent_id == cid:
                new_models[i] = m.model_copy(update={"tier": new_tier})
                break
        else:
            raise ValueError(f"tier_change: constituent_id {cid!r} not in registry")
    elif mut_type == "add_model":
        model = mutation["model"]
        if not isinstance(model, ModelMetadata):
            raise ValueError("add_model: 'model' must be a ModelMetadata instance")
        existing_ids = {m.constituent_id for m in new_models}
        if model.constituent_id in existing_ids:
            raise ValueError(
                f"add_model: constituent_id {model.constituent_id!r} already in registry"
            )
        new_models.append(model)
    elif mut_type == "active_from":
        cid = mutation["constituent_id"]
        new_from = mutation["active_from"]
        for i, m in enumerate(new_models):
            if m.constituent_id == cid:
                new_models[i] = m.model_copy(update={"active_from": new_from})
                break
        else:
            raise ValueError(f"active_from: constituent_id {cid!r} not in registry")
    else:
        raise ValueError(f"unknown registry mutation type: {mut_type!r}")

    # Normalise mutation for the op_record (serialisable form)
    mut_record: dict[str, Any] = {"type": mut_type}
    for k, v in mutation.items():
        if k == "type":
            continue
        if isinstance(v, ModelMetadata):
            mut_record[k] = v.constituent_id
        elif hasattr(v, "value"):  # Tier enum
            mut_record[k] = v.value
        elif hasattr(v, "isoformat"):
            mut_record[k] = v.isoformat()
        else:
            mut_record[k] = v

    return ModelRegistry(models=new_models), {
        "op": "mutate_registry",
        "mutation": mut_record,
    }


# ---------------------------------------------------------------------------
# Primitive 6: regenerate_constituent_slice
# ---------------------------------------------------------------------------


def regenerate_constituent_slice(
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    model_metadata: ModelMetadata,
    contributor_panel: ContributorPanel,
    date_range: tuple[Any, Any],
    seed: int,
    *,
    sigma_daily: float | None = None,
    mu_daily: float | None = None,
    step_rate_per_year: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Regenerate panel + events for one constituent over a date range.

    Two modes, auto-detected from whether the constituent exists in ``panel_df``:

    * **Existing-constituent** (e.g. scenario 10 regime_shift): walk the
      contributor-level prices forward from the day-before entry price using
      the override params (sigma/mu/rate). Pre-window and post-window panel
      rows for the constituent are byte-identical to the input. In-window
      events for the constituent are suppressed; new events generated per the
      overridden step_rate (0 for scenario 10 = no events in window).

    * **New-constituent** (e.g. scenario 8 new_model_launch): the constituent
      has no rows in ``panel_df``. Full Phase 2 pipeline is executed on a
      mini-registry containing only this constituent, for covering
      contributors over the window. Volumes come from ``generate_volumes``
      (the existing Phase 2a.3 helper).

    A separate seed stream (tagged ``"scenario_regen"``) preserves the
    byte-identity of pre-window rows by not sharing RNG substreams with the
    Phase 2 pricing.py generator.
    """
    constituent_id = model_metadata.constituent_id
    start = pd.Timestamp(date_range[0]).normalize()
    end = pd.Timestamp(date_range[1]).normalize()
    if end < start:
        raise ValueError(f"date_range end {end} is before start {start}")

    covering = [
        p for p in contributor_panel.contributors
        if constituent_id in p.covered_models
    ]
    if not covering:
        raise ValueError(
            f"no contributors cover {constituent_id!r}; nothing to regenerate"
        )

    base_params = TIER_PARAMS[model_metadata.tier]
    effective_sigma = sigma_daily if sigma_daily is not None else base_params.sigma_daily
    effective_mu = mu_daily if mu_daily is not None else base_params.mu_daily
    effective_rate = (
        step_rate_per_year
        if step_rate_per_year is not None
        else base_params.rate_per_year
    )

    constituent_rows = panel_df[panel_df["constituent_id"] == constituent_id]
    is_new = len(constituent_rows) == 0

    if is_new:
        _ = effective_sigma  # reserved for future parameter-injection API (pricing.py)
        _ = effective_mu
        _ = effective_rate
        _ = base_params
        panel_out, events_out, n_panel, n_events = _bootstrap_new_constituent(
            panel_df=panel_df,
            events_df=events_df,
            model_metadata=model_metadata,
            covering=covering,
            start=start,
            end=end,
            seed=seed,
        )
        n_suppressed = 0
    else:
        panel_out, events_out, n_panel, n_suppressed = (
            _regenerate_existing_constituent(
                panel_df=panel_df,
                events_df=events_df,
                model_metadata=model_metadata,
                covering=covering,
                start=start,
                end=end,
                effective_sigma=effective_sigma,
                effective_mu=effective_mu,
                seed=seed,
            )
        )
        n_events = 0  # step_rate=0 is the only supported in-window regen for
        # existing constituents in v0.1; no new events emitted. (Scenario 10
        # explicitly passes step_rate_per_year=0.)

    return panel_out, events_out, {
        "op": "regenerate_constituent_slice",
        "constituent_id": constituent_id,
        "date_range": [str(start.date()), str(end.date())],
        "is_new_constituent": is_new,
        "overrides_applied": {
            "sigma_daily": sigma_daily,
            "mu_daily": mu_daily,
            "step_rate_per_year": step_rate_per_year,
        },
        "n_panel_rows_regenerated": n_panel,
        "n_events_added": n_events,
        "n_events_suppressed": n_suppressed,
    }


def _regenerate_existing_constituent(
    *,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    model_metadata: ModelMetadata,
    covering: list[Any],  # list[ContributorProfile] — Any per CLAUDE.md
    start: pd.Timestamp,
    end: pd.Timestamp,
    effective_sigma: float,
    effective_mu: float,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """Regenerate prices in-window for an existing constituent. Step rate=0."""
    constituent_id = model_metadata.constituent_id
    day_before = start - pd.Timedelta(days=1)
    n_days = int((end - start).days) + 1

    # Suppress in-window events for this constituent
    suppress_mask = (
        (events_df["constituent_id"] == constituent_id)
        & (events_df["event_date"] >= start)
        & (events_df["event_date"] <= end)
    )
    n_suppressed = int(suppress_mask.sum())
    events_out = events_df.loc[~suppress_mask].copy().reset_index(drop=True)

    # Per-contributor price walk
    new_panel_frames: list[pd.DataFrame] = []
    for profile in covering:
        seed_seq = np.random.SeedSequence(
            [
                seed,
                _stable_int("scenario_regen"),
                _stable_int(profile.contributor_id),
                _stable_int(constituent_id),
                start.toordinal(),
            ]
        )
        rng = np.random.default_rng(seed_seq)

        prev = panel_df[
            (panel_df["contributor_id"] == profile.contributor_id)
            & (panel_df["constituent_id"] == constituent_id)
            & (panel_df["observation_date"] == day_before)
        ]
        if len(prev) > 0:
            entry_input = float(prev.iloc[0]["input_price_usd_mtok"])
            entry_output = float(prev.iloc[0]["output_price_usd_mtok"])
        else:
            bias_factor = 1.0 + profile.price_bias_pct / 100.0
            entry_input = model_metadata.baseline_input_price_usd_mtok * bias_factor
            entry_output = model_metadata.baseline_output_price_usd_mtok * bias_factor

        daily_returns = rng.normal(effective_mu, effective_sigma, n_days)
        cumulative = np.cumprod(1.0 + daily_returns)
        new_outputs = entry_output * cumulative
        new_inputs = entry_input * cumulative

        existing = panel_df[
            (panel_df["contributor_id"] == profile.contributor_id)
            & (panel_df["constituent_id"] == constituent_id)
            & (panel_df["observation_date"] >= start)
            & (panel_df["observation_date"] <= end)
        ].sort_values("observation_date").copy()

        if len(existing) == 0:
            continue

        existing["input_price_usd_mtok"] = new_inputs[: len(existing)]
        existing["output_price_usd_mtok"] = new_outputs[: len(existing)]
        new_panel_frames.append(existing)

    panel_out = panel_df[
        ~(
            (panel_df["constituent_id"] == constituent_id)
            & (panel_df["observation_date"] >= start)
            & (panel_df["observation_date"] <= end)
        )
    ].copy()
    n_regenerated = 0
    if new_panel_frames:
        regen = pd.concat(new_panel_frames, ignore_index=True)
        n_regenerated = len(regen)
        panel_out = pd.concat([panel_out, regen], ignore_index=True)

    return panel_out.reset_index(drop=True), events_out, n_regenerated, n_suppressed


def _bootstrap_new_constituent(
    *,
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    model_metadata: ModelMetadata,
    covering: list[ContributorProfile],
    start: pd.Timestamp,
    end: pd.Timestamp,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """Full Phase 2 pipeline bootstrap for a new constituent.

    Uses the existing Phase 2 helpers on a mini-registry containing only
    ``model_metadata`` and a mini-panel where each covering contributor's
    ``covered_models`` is trimmed to only the new constituent (the Phase 2
    cross-validator would otherwise reject profiles covering models absent
    from the mini-registry).

    The new constituent uses its tier's default stochastic parameters.
    Scenario 8 (new_model_launch) uses standard S-tier dynamics, so the
    override params (sigma/mu/rate) aren't threaded through. If a later
    scenario needs overridden params on a new constituent, pricing.py
    will need a parameters-inject API.
    """
    mini_registry = ModelRegistry(models=[model_metadata])
    mini_contributors = [
        ContributorProfile(
            contributor_id=p.contributor_id,
            profile_name=p.profile_name,
            volume_scale=p.volume_scale,
            price_bias_pct=p.price_bias_pct,
            daily_noise_sigma_pct=p.daily_noise_sigma_pct,
            error_rate=p.error_rate,
            covered_models=[model_metadata.constituent_id],
        )
        for p in covering
    ]
    mini_panel_cfg = ContributorPanel(contributors=mini_contributors)

    slice_seed = seed ^ _stable_int(
        f"scenario_regen_bootstrap_{model_metadata.constituent_id}"
    )

    baseline, step_events = generate_baseline_prices(
        mini_registry, start.date(), end.date(), seed=slice_seed
    )
    panel_new = generate_contributor_panel(
        baseline, mini_panel_cfg, mini_registry, seed=slice_seed
    )
    panel_new = generate_volumes(panel_new, mini_panel_cfg, seed=slice_seed)
    events_new = generate_change_events(
        panel_new, step_events, mini_registry, mini_panel_cfg, seed=slice_seed
    )
    panel_new = apply_twap_to_panel(panel_new, events_new)

    panel_out = pd.concat([panel_df, panel_new], ignore_index=True)
    events_out = pd.concat([events_df, events_new], ignore_index=True)
    return panel_out, events_out, len(panel_new), len(events_new)


# ---------------------------------------------------------------------------
# Wrapper: freeze_pair_in_window
# ---------------------------------------------------------------------------


def freeze_pair_in_window(
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
    *,
    contributor_id: str,
    constituent_id: str,
    date_range: tuple[Any, Any],
    freeze_price_source: str = "entry_day",
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Freeze a (contributor, constituent)'s price across a window.

    Composes ``suppress_events`` + ``override_panel_prices`` into one semantic
    call. Used by scenarios 3 (stale_quote) and 6 (sustained_manipulation —
    note scenario 6 overrides with tier-median x 1.25 computed externally,
    not with the frozen entry-day price; this wrapper covers the
    ``"entry_day"`` source only).

    ``freeze_price_source``:
      - ``"entry_day"``: freeze at the (contributor, constituent)'s
        ``observation_date == date_range[0]`` panel price.

    Returns ``(panel_out, events_out, op_records)`` where ``op_records`` is a
    list of the two underlying operations' records.
    """
    if freeze_price_source != "entry_day":
        raise ValueError(
            f"freeze_price_source {freeze_price_source!r} not supported; "
            f"only 'entry_day' implemented in Phase 3.1"
        )

    start = pd.Timestamp(date_range[0]).normalize()
    entry_rows = panel_df[
        (panel_df["contributor_id"] == contributor_id)
        & (panel_df["constituent_id"] == constituent_id)
        & (panel_df["observation_date"] == start)
    ]
    if len(entry_rows) == 0:
        raise ValueError(
            f"no entry-day panel row for ({contributor_id!r}, "
            f"{constituent_id!r}) on {start.date()}"
        )
    entry = entry_rows.iloc[0]
    frozen_input = float(entry["input_price_usd_mtok"])
    frozen_output = float(entry["output_price_usd_mtok"])

    events_out, suppress_rec = suppress_events(
        events_df,
        contributor_id=contributor_id,
        constituent_id=constituent_id,
        date_range=date_range,
    )

    def _freeze_fn(_row: dict[str, Any]) -> tuple[float, float]:
        return frozen_input, frozen_output

    panel_out, override_rec = override_panel_prices(
        panel_df,
        _freeze_fn,
        contributor_id=contributor_id,
        constituent_id=constituent_id,
        date_range=date_range,
    )

    return panel_out, events_out, [suppress_rec, override_rec]


# ---------------------------------------------------------------------------
# Unused AttestationTier import placeholder (for re-export if scenarios need it)
# ---------------------------------------------------------------------------

_ = AttestationTier  # kept in import graph for scenario authors
