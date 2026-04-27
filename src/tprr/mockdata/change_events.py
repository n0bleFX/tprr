"""Phase 2b ChangeEvent materialisation — per-(contributor, model, date) price moves.

Two sources:
1. Provider-driven: propagated from pricing.py's step_events DataFrame, one
   event per covering contributor per baseline step; tight per-contributor
   slot jitter (sigma=2) around a single publication slot
   (Normal(16, 6) on the 32-slot 09:00-17:00 UTC basis).
   reason = "baseline_move". Direction is encoded in old/new price fields.
2. Contributor-specific: independent Poisson per (contributor, model) pair
   at tier-specific rates (F 2/yr, S 4/yr, E 10/yr contributor-specific —
   plus ~3/4/5 per-pair-year inherited from propagation to hit the
   project_plan 2b target of 4-6/6-10/10-20 total per pair). Full
   business-hours slot distribution, smaller magnitude (+/- 2-5%).
   reason = "contract_adjustment".

Same-day collisions between sources: propagated wins (deduplicated by
(contributor, constituent, event_date)).

``apply_twap_to_panel`` overrides the panel's output/input prices on
change-event days with the daily TWAP reconstructed from old/new prices
and the slot index: ``(slot * old + (32 - slot) * new) / 32``.

Schema / parameters logged in docs/findings/pricing_model_design.md and
docs/decision_log.md 2026-04-24.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tprr.config import ContributorPanel, ModelRegistry
from tprr.mockdata.pricing import _stable_int
from tprr.schema import Tier

_TWAP_SLOTS = 32
PUBLICATION_SLOT_MEAN = 16
PUBLICATION_SLOT_SIGMA = 6.0
CONTRIB_JITTER_SIGMA = 2.0

_REASON_BASELINE_MOVE = "baseline_move"
_REASON_CONTRACT_ADJUSTMENT = "contract_adjustment"

# Contributor-specific event rates per (contributor, model) pair per year.
# Total pair rate = propagated (from step_events, ~3/4/5 for F/S/E) + these,
# hitting project_plan's 2b target of F 4-6 / S 6-10 / E 10-20 per pair per year.
_CONTRIB_SPEC_RATE_PER_YEAR: dict[Tier, float] = {
    Tier.TPRR_F: 2.0,
    Tier.TPRR_S: 4.0,
    Tier.TPRR_E: 10.0,
}

# Contributor-specific magnitude range (fractional; sign drawn 50/50).
_CONTRIB_SPEC_MAG_LO = 0.02
_CONTRIB_SPEC_MAG_HI = 0.05

# Integer tags distinguishing RNG substreams per (contributor, constituent).
_SUBSTREAM_JITTER = 1
_SUBSTREAM_CONTRIB_SPEC = 2

_OUTPUT_COLUMNS = [
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


def generate_change_events(
    panel_df: pd.DataFrame,
    step_events_df: pd.DataFrame,
    registry: ModelRegistry,
    contributor_panel: ContributorPanel,
    seed: int,
) -> pd.DataFrame:
    """Generate ChangeEvent records. Returns DataFrame matching ChangeEventDF.

    ``step_events_df`` comes from ``generate_baseline_prices`` — the
    authoritative list of baseline step events (no post-hoc reconstruction).

    Signature extends prompt 2b.1 with ``step_events_df`` — required by the
    2a/2b layering where propagated events are derived directly from baseline
    jumps rather than re-detected via threshold heuristic.
    """
    required = {
        "observation_date",
        "contributor_id",
        "constituent_id",
        "input_price_usd_mtok",
        "output_price_usd_mtok",
    }
    missing = required - set(panel_df.columns)
    if missing:
        raise ValueError(f"panel_df missing required columns: {sorted(missing)}")

    coverage = _build_coverage_map(contributor_panel)
    tier_by_constituent = {m.constituent_id: m.tier for m in registry.models}
    panel_lookup = _build_panel_lookup(panel_df)

    propagated = _generate_propagated_events(
        step_events_df=step_events_df,
        coverage=coverage,
        panel_lookup=panel_lookup,
        seed=seed,
    )

    propagated_keys = {
        (ev["event_date"], ev["contributor_id"], ev["constituent_id"])
        for ev in propagated
    }
    all_dates = sorted(panel_df["observation_date"].unique())
    specific = _generate_contributor_specific_events(
        contributor_panel=contributor_panel,
        tier_by_constituent=tier_by_constituent,
        panel_lookup=panel_lookup,
        all_dates=all_dates,
        propagated_keys=propagated_keys,
        seed=seed,
    )

    return _build_change_events_df(propagated + specific)


def apply_twap_to_panel(
    panel_df: pd.DataFrame,
    events_df: pd.DataFrame,
) -> pd.DataFrame:
    """Override panel input/output prices on change-event days with daily TWAP.

    TWAP on an event day: ``(slot * old + (32 - slot) * new) / 32`` for both
    input and output columns. Days without change events are untouched.
    """
    original_columns = panel_df.columns.tolist()
    if len(events_df) == 0:
        return panel_df.copy()

    n = _TWAP_SLOTS
    twap_rows = pd.DataFrame(
        {
            "observation_date": events_df["event_date"].to_numpy(),
            "contributor_id": events_df["contributor_id"].to_numpy(),
            "constituent_id": events_df["constituent_id"].to_numpy(),
            "_twap_output": (
                events_df["change_slot_idx"]
                * events_df["old_output_price_usd_mtok"]
                + (n - events_df["change_slot_idx"])
                * events_df["new_output_price_usd_mtok"]
            )
            / n,
            "_twap_input": (
                events_df["change_slot_idx"]
                * events_df["old_input_price_usd_mtok"]
                + (n - events_df["change_slot_idx"])
                * events_df["new_input_price_usd_mtok"]
            )
            / n,
        }
    )
    merged = panel_df.merge(
        twap_rows,
        on=["observation_date", "contributor_id", "constituent_id"],
        how="left",
    )
    mask = merged["_twap_output"].notna()
    merged.loc[mask, "output_price_usd_mtok"] = merged.loc[mask, "_twap_output"]
    merged.loc[mask, "input_price_usd_mtok"] = merged.loc[mask, "_twap_input"]
    return merged.drop(columns=["_twap_output", "_twap_input"])[original_columns]


def _build_coverage_map(
    contributor_panel: ContributorPanel,
) -> dict[str, list[str]]:
    """constituent_id -> list of contributor_ids covering it."""
    coverage: dict[str, list[str]] = {}
    for profile in contributor_panel.contributors:
        for cid in profile.covered_models:
            coverage.setdefault(cid, []).append(profile.contributor_id)
    return coverage


def _build_panel_lookup(
    panel_df: pd.DataFrame,
) -> dict[tuple[Any, str, str], tuple[float, float]]:
    """(date, contributor_id, constituent_id) -> (input_price, output_price).

    Heterogeneous tuple key dtype (date comes from pandas datetime64) is the
    reason for the ``Any`` in the signature — comment per CLAUDE.md.
    """
    lookup: dict[tuple[Any, str, str], tuple[float, float]] = {}
    for rec in panel_df.to_dict("records"):  # list of dict[Hashable, Any]
        lookup[
            (rec["observation_date"], str(rec["contributor_id"]), str(rec["constituent_id"]))
        ] = (
            float(rec["input_price_usd_mtok"]),
            float(rec["output_price_usd_mtok"]),
        )
    return lookup


def _generate_propagated_events(
    *,
    step_events_df: pd.DataFrame,
    coverage: dict[str, list[str]],
    panel_lookup: dict[tuple[Any, str, str], tuple[float, float]],
    seed: int,
) -> list[dict[str, Any]]:
    """One ChangeEvent per (covering contributor, baseline step event)."""
    out: list[dict[str, Any]] = []  # heterogeneous rows; Any per CLAUDE.md
    for step in step_events_df.to_dict("records"):
        constituent_id = str(step["constituent_id"])
        event_date = step["event_date"]
        step_old_out = float(step["old_output_price_usd_mtok"])
        step_new_out = float(step["new_output_price_usd_mtok"])
        step_old_in = float(step["old_input_price_usd_mtok"])
        step_new_in = float(step["new_input_price_usd_mtok"])

        date_ordinal = pd.Timestamp(event_date).toordinal()
        pub_ss = np.random.SeedSequence(
            [seed, _stable_int(constituent_id), date_ordinal]
        )
        pub_rng = np.random.default_rng(pub_ss)
        publication_slot = int(
            np.clip(
                round(
                    pub_rng.normal(
                        PUBLICATION_SLOT_MEAN, PUBLICATION_SLOT_SIGMA
                    )
                ),
                0,
                _TWAP_SLOTS - 1,
            )
        )

        output_ratio = step_old_out / step_new_out
        input_ratio = step_old_in / step_new_in

        for contrib_id in coverage.get(constituent_id, []):
            jit_ss = np.random.SeedSequence(
                [
                    seed,
                    _stable_int(contrib_id),
                    _stable_int(constituent_id),
                    date_ordinal,
                    _SUBSTREAM_JITTER,
                ]
            )
            jit_rng = np.random.default_rng(jit_ss)
            jitter = jit_rng.normal(0.0, CONTRIB_JITTER_SIGMA)
            contrib_slot = int(
                np.clip(round(publication_slot + jitter), 0, _TWAP_SLOTS - 1)
            )

            key = (event_date, contrib_id, constituent_id)
            if key not in panel_lookup:
                continue  # defensive — covered contributor always has a panel row
            panel_in, panel_out = panel_lookup[key]

            new_output = panel_out
            new_input = panel_in
            old_output = new_output * output_ratio
            old_input = new_input * input_ratio

            out.append(
                {
                    "event_date": event_date,
                    "contributor_id": contrib_id,
                    "constituent_id": constituent_id,
                    "change_slot_idx": contrib_slot,
                    "old_input_price_usd_mtok": old_input,
                    "new_input_price_usd_mtok": new_input,
                    "old_output_price_usd_mtok": old_output,
                    "new_output_price_usd_mtok": new_output,
                    "reason": _REASON_BASELINE_MOVE,
                }
            )
    return out


def _generate_contributor_specific_events(
    *,
    contributor_panel: ContributorPanel,
    tier_by_constituent: dict[str, Tier],
    panel_lookup: dict[tuple[Any, str, str], tuple[float, float]],
    all_dates: list[Any],
    propagated_keys: set[tuple[Any, str, str]],
    seed: int,
) -> list[dict[str, Any]]:
    """Independent Poisson per (contributor, model) at tier-specific rates."""
    out: list[dict[str, Any]] = []  # heterogeneous rows; Any per CLAUDE.md
    n_days = len(all_dates)
    n_years = n_days / 365.0 if n_days > 0 else 0.0
    for profile in contributor_panel.contributors:
        for cid in profile.covered_models:
            tier = tier_by_constituent.get(cid)
            if tier is None:
                continue
            mean_events = _CONTRIB_SPEC_RATE_PER_YEAR[tier] * n_years

            ss = np.random.SeedSequence(
                [
                    seed,
                    _stable_int(profile.contributor_id),
                    _stable_int(cid),
                    _SUBSTREAM_CONTRIB_SPEC,
                ]
            )
            rng = np.random.default_rng(ss)
            n_events = int(rng.poisson(mean_events))

            pair_seen: set[Any] = set()
            for _ in range(n_events):
                day_idx = int(rng.integers(0, n_days)) if n_days > 0 else 0
                event_date = all_dates[day_idx]

                event_key = (event_date, profile.contributor_id, cid)
                if event_key in propagated_keys or event_date in pair_seen:
                    # skip collisions (propagated wins) and within-pair duplicates
                    _ = rng.normal(
                        PUBLICATION_SLOT_MEAN, PUBLICATION_SLOT_SIGMA
                    )  # drain to keep stream deterministic even on skip
                    _ = rng.random()
                    _ = rng.uniform(_CONTRIB_SPEC_MAG_LO, _CONTRIB_SPEC_MAG_HI)
                    continue
                pair_seen.add(event_date)

                slot = int(
                    np.clip(
                        round(
                            rng.normal(
                                PUBLICATION_SLOT_MEAN,
                                PUBLICATION_SLOT_SIGMA,
                            )
                        ),
                        0,
                        _TWAP_SLOTS - 1,
                    )
                )
                sign = 1.0 if rng.random() < 0.5 else -1.0
                magnitude = sign * rng.uniform(
                    _CONTRIB_SPEC_MAG_LO, _CONTRIB_SPEC_MAG_HI
                )

                if event_key not in panel_lookup:
                    continue
                panel_in, panel_out = panel_lookup[event_key]

                old_output = panel_out
                old_input = panel_in
                new_output = old_output * (1.0 + magnitude)
                new_input = old_input * (1.0 + magnitude)

                out.append(
                    {
                        "event_date": event_date,
                        "contributor_id": profile.contributor_id,
                        "constituent_id": cid,
                        "change_slot_idx": slot,
                        "old_input_price_usd_mtok": old_input,
                        "new_input_price_usd_mtok": new_input,
                        "old_output_price_usd_mtok": old_output,
                        "new_output_price_usd_mtok": new_output,
                        "reason": _REASON_CONTRACT_ADJUSTMENT,
                    }
                )
    return out


def _build_change_events_df(
    events: list[dict[str, Any]],  # heterogeneous rows per CLAUDE.md
) -> pd.DataFrame:
    """Assemble ChangeEventDF-compatible DataFrame (empty or populated)."""
    if not events:
        return pd.DataFrame(
            {
                "event_date": pd.Series([], dtype="datetime64[ns]"),
                "contributor_id": pd.Series([], dtype="object"),
                "constituent_id": pd.Series([], dtype="object"),
                "change_slot_idx": pd.Series([], dtype="int64"),
                "old_input_price_usd_mtok": pd.Series([], dtype="float64"),
                "new_input_price_usd_mtok": pd.Series([], dtype="float64"),
                "old_output_price_usd_mtok": pd.Series([], dtype="float64"),
                "new_output_price_usd_mtok": pd.Series([], dtype="float64"),
                "reason": pd.Series([], dtype="object"),
            }
        )
    df = pd.DataFrame(events)
    df["event_date"] = pd.to_datetime(df["event_date"]).astype("datetime64[ns]")
    df["change_slot_idx"] = df["change_slot_idx"].astype("int64")
    return df[_OUTPUT_COLUMNS].reset_index(drop=True)
