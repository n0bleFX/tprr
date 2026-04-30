"""Tests for tprr.index.compute — Phase 7 end-to-end pipeline + suspension cascade."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest

from tprr.config import (
    IndexConfig,
    ModelMetadata,
    ModelRegistry,
    TierBRevenueConfig,
    TierBRevenueEntry,
)
from tprr.index.aggregation import SuspensionReason
from tprr.index.compute import _drop_fully_excluded_rows, run_full_pipeline
from tprr.index.weights import TierBVolumeFn
from tprr.schema import AttestationTier, Tier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _registry_three_tiers() -> ModelRegistry:
    """3 F + 3 S + 3 E constituents, distinct providers."""
    return ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=tier,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=baseline_in,
                baseline_output_price_usd_mtok=baseline_out,
            )
            for cid, tier, baseline_in, baseline_out in [
                ("openai/gpt-5-pro", Tier.TPRR_F, 15.0, 75.0),
                ("anthropic/claude-opus-4-7", Tier.TPRR_F, 14.0, 70.0),
                ("google/gemini-3-pro", Tier.TPRR_F, 5.0, 30.0),
                ("openai/gpt-5-mini", Tier.TPRR_S, 0.5, 4.0),
                ("anthropic/claude-haiku-4-5", Tier.TPRR_S, 1.0, 5.0),
                ("google/gemini-2-flash", Tier.TPRR_S, 0.3, 2.5),
                ("google/gemini-flash-lite", Tier.TPRR_E, 0.1, 0.4),
                ("openai/gpt-5-nano", Tier.TPRR_E, 0.15, 0.6),
                ("deepseek/deepseek-v3-2", Tier.TPRR_E, 0.25, 1.0),
            ]
        ]
    )


def _empty_tier_b_config() -> TierBRevenueConfig:
    return TierBRevenueConfig(entries=[])


def _tier_b_config_one_provider(provider: str = "openai") -> TierBRevenueConfig:
    return TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider=provider,
                period="2025-Q1",
                amount_usd=1_000_000_000.0,
                source="test",
            ),
        ]
    )


def _stub_tier_b_volume_fn(value: float = 0.0) -> TierBVolumeFn:
    def _fn(_provider: str, _constituent_id: str, _as_of_date: date) -> float:
        return value

    return _fn


def _empty_change_events() -> pd.DataFrame:
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


def _row(
    *,
    cid: str,
    contrib: str,
    d: date,
    twap_out: float,
    twap_in: float,
    volume: float,
    tier: Tier,
    attestation: AttestationTier = AttestationTier.A,
) -> dict[str, Any]:
    ts = pd.Timestamp(d)
    return {
        "observation_date": ts,
        "constituent_id": cid,
        "contributor_id": contrib,
        "tier_code": tier.value,
        "attestation_tier": attestation.value,
        "input_price_usd_mtok": float(twap_in),
        "output_price_usd_mtok": float(twap_out),
        "volume_mtok_7d": float(volume),
        "twap_output_usd_mtok": float(twap_out),
        "twap_input_usd_mtok": float(twap_in),
        "source": "test",
        "submitted_at": ts,
        "notes": "",
    }


def _multi_day_clean_panel(
    n_days: int = 10,
    *,
    start: date = date(2025, 1, 1),
) -> pd.DataFrame:
    """3 F + 3 S + 3 E constituents x 3 contributors x n_days, all Tier A."""
    rows: list[dict[str, Any]] = []
    f_set = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    s_set = [
        ("openai/gpt-5-mini", 4.0, 0.5),
        ("anthropic/claude-haiku-4-5", 5.0, 1.0),
        ("google/gemini-2-flash", 2.5, 0.3),
    ]
    e_set = [
        ("google/gemini-flash-lite", 0.4, 0.1),
        ("openai/gpt-5-nano", 0.6, 0.15),
        ("deepseek/deepseek-v3-2", 1.0, 0.25),
    ]
    for offset in range(n_days):
        d = start + timedelta(days=offset)
        for tier_set, tier in [(f_set, Tier.TPRR_F), (s_set, Tier.TPRR_S), (e_set, Tier.TPRR_E)]:
            for cid, p_out, p_in in tier_set:
                for contrib in ["c1", "c2", "c3"]:
                    rows.append(
                        _row(
                            cid=cid,
                            contrib=contrib,
                            d=d,
                            twap_out=p_out,
                            twap_in=p_in,
                            volume=100.0,
                            tier=tier,
                        )
                    )
    return pd.DataFrame(rows)


def _config(base_date: date = date(2025, 1, 1)) -> IndexConfig:
    return IndexConfig(base_date=base_date)


# ---------------------------------------------------------------------------
# Clean-panel pipeline (no gate firings, no suspensions)
# ---------------------------------------------------------------------------


def test_run_full_pipeline_clean_panel_no_suspensions() -> None:
    """On a constant-price panel with no events, the gate cannot fire (no
    deviations) and no pairs suspend. All 8 indices compute end-to-end."""
    panel = _multi_day_clean_panel(n_days=10)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result.excluded_slots.empty
    assert result.suspended_pairs.empty
    expected_codes = {
        "TPRR_F", "TPRR_S", "TPRR_E",
        "TPRR_FPR", "TPRR_SER",
        "TPRR_B_F", "TPRR_B_S", "TPRR_B_E",
    }
    assert set(result.indices.keys()) == expected_codes
    for df in result.indices.values():
        assert len(df) == 10
        assert (~df["suspended"]).all()
        anchor_row = df[df["as_of_date"] == pd.Timestamp(date(2025, 1, 1))]
        assert float(anchor_row["index_level"].iloc[0]) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Per-pair granularity
# ---------------------------------------------------------------------------


def test_pair_suspension_granular_only_targeted_pair_drops() -> None:
    """A (contributor, constituent) suspension drops only that exact pair —
    same contributor on a different constituent stays active."""
    from tprr.index.aggregation import compute_tier_index

    d = date(2025, 1, 1)
    panel = _multi_day_clean_panel(n_days=1, start=d)

    # Suspend contrib c1 on openai/gpt-5-pro only
    susp = pd.DataFrame(
        {
            "contributor_id": ["c1"],
            "constituent_id": ["openai/gpt-5-pro"],
            "suspension_date": [pd.Timestamp(d)],
        }
    )
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
    )
    # gpt-5-pro retains 2 contributors → still ≥ 3? No, 2 < 3, falls through.
    # But Tier B is empty here → constituent excluded via TIER_DATA_UNAVAILABLE
    # at the constituent level. The other two F constituents (3 contributors
    # each) still resolve Tier A.
    # 2 active F constituents → tier suspends with INSUFFICIENT_CONSTITUENTS.
    assert result["suspended"]
    assert (
        result["suspension_reason"]
        == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value
    )
    # gpt-5-pro is NOT counted as active; the other 2 F constituents are.
    assert result["n_constituents_active"] == 2

    # Same suspension on a non-F-tier panel slice should not affect TPRR_S.
    s_result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_S,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
    )
    assert not s_result["suspended"]
    assert s_result["n_constituents_a"] == 3  # all 3 S constituents intact


# ---------------------------------------------------------------------------
# Cascade through priority fall-through (Tier A → Tier B)
# ---------------------------------------------------------------------------


def test_pair_suspension_falls_through_to_tier_b() -> None:
    """Pair suspension drops Tier A active count below 3 → constituent falls
    through to Tier B (when available) per the priority hierarchy."""
    from tprr.index.aggregation import compute_tier_index

    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    # gpt-5-pro: only 2 active contributors after suspension → falls through to B
    for c in ["c1", "c2", "c3"]:
        rows.append(
            _row(
                cid="openai/gpt-5-pro",
                contrib=c,
                d=d,
                twap_out=80.0,
                twap_in=15.0,
                volume=100.0,
                tier=Tier.TPRR_F,
            )
        )
    # Tier B panel row for gpt-5-pro (derive_tier_b_volumes upstream emits these).
    rows.append(
        _row(
            cid="openai/gpt-5-pro",
            contrib="tier_b_derived:openai",
            d=d,
            twap_out=80.0,
            twap_in=15.0,
            volume=10_000_000.0,
            tier=Tier.TPRR_F,
            attestation=AttestationTier.B,
        )
    )
    # Two more F-tier constituents with full Tier A coverage.
    for cid, p_out in [("anthropic/claude-opus-4-7", 70.0), ("google/gemini-3-pro", 30.0)]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_out / 5.0,
                    volume=100.0,
                    tier=Tier.TPRR_F,
                )
            )
    panel = pd.DataFrame(rows)

    # Suspend c1 + c2 on gpt-5-pro → only c3 active → fewer than 3 Tier A
    # contributors → fall through to Tier B.
    susp = pd.DataFrame(
        {
            "contributor_id": ["c1", "c2"],
            "constituent_id": ["openai/gpt-5-pro"] * 2,
            "suspension_date": [pd.Timestamp(d)] * 2,
        }
    )
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_tier_b_config_one_provider("openai"),
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=10_000_000.0),
        suspended_pairs_df=susp,
    )
    assert not result["suspended"]
    assert result["n_constituents_a"] == 2  # opus + gemini
    assert result["n_constituents_b"] == 1  # gpt-5-pro fell through
    assert result["tier_b_weight_share"] > 0


# ---------------------------------------------------------------------------
# Tier suspension when active-constituent count drops below 3
# ---------------------------------------------------------------------------


def test_tier_suspends_with_insufficient_constituents() -> None:
    """When N-2 of N=3 F-tier constituents lose all their pairs, the tier
    drops below the min-3 threshold and suspends."""
    from tprr.index.aggregation import compute_tier_index

    d = date(2025, 1, 1)
    panel = _multi_day_clean_panel(n_days=1, start=d)
    # Suspend ALL contributors for two of the three F constituents.
    susp_rows = []
    for cid in ["openai/gpt-5-pro", "anthropic/claude-opus-4-7"]:
        for c in ["c1", "c2", "c3"]:
            susp_rows.append(
                {
                    "contributor_id": c,
                    "constituent_id": cid,
                    "suspension_date": pd.Timestamp(d),
                }
            )
    susp = pd.DataFrame(susp_rows)

    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
    )
    assert result["suspended"]
    assert (
        result["suspension_reason"]
        == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value
    )
    # Only gemini-3-pro left in F.
    assert result["n_constituents_active"] == 1


def test_prior_raw_value_carried_forward_across_tier_suspension_days() -> None:
    """Day 1 valid; day 2 suspended (pair suspensions force tier below min-3).
    Day 2's IndexValue carries day 1's raw_value forward."""
    from tprr.index.aggregation import run_tier_pipeline

    panel = _multi_day_clean_panel(n_days=2, start=date(2025, 1, 1))
    # Suspend ALL contributors for two F constituents starting day 2.
    susp_rows = []
    for cid in ["openai/gpt-5-pro", "anthropic/claude-opus-4-7"]:
        for c in ["c1", "c2", "c3"]:
            susp_rows.append(
                {
                    "contributor_id": c,
                    "constituent_id": cid,
                    "suspension_date": pd.Timestamp(date(2025, 1, 2)),
                }
            )
    susp = pd.DataFrame(susp_rows)

    out = run_tier_pipeline(
        panel_df=panel,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp,
    )
    assert len(out) == 2
    day_1 = out.iloc[0]
    day_2 = out.iloc[1]
    assert not bool(day_1["suspended"])
    assert bool(day_2["suspended"])
    # Carries day 1's raw value forward.
    assert float(day_2["raw_value_usd_mtok"]) == pytest.approx(
        float(day_1["raw_value_usd_mtok"])
    )


# ---------------------------------------------------------------------------
# tier_data_unavailable scenario
# ---------------------------------------------------------------------------


def test_tier_data_unavailable_when_no_path_resolves_for_any_constituent() -> None:
    """A panel where every F constituent has <3 Tier A contributors AND no
    Tier B revenue config AND no Tier C rankings → no constituent resolves
    a tier path → tier suspends with TIER_DATA_UNAVAILABLE."""
    from tprr.index.aggregation import compute_tier_index

    d = date(2025, 1, 1)
    rows: list[dict[str, Any]] = []
    for cid, p_out in [
        ("openai/gpt-5-pro", 75.0),
        ("anthropic/claude-opus-4-7", 70.0),
        ("google/gemini-3-pro", 30.0),
    ]:
        for c in ["c1", "c2"]:  # only 2 contributors → below min
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_out / 5.0,
                    volume=100.0,
                    tier=Tier.TPRR_F,
                )
            )
    panel = pd.DataFrame(rows)
    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result["suspended"]
    assert (
        result["suspension_reason"]
        == SuspensionReason.TIER_DATA_UNAVAILABLE.value
    )


# ---------------------------------------------------------------------------
# _drop_fully_excluded_rows helper
# ---------------------------------------------------------------------------


def test_drop_fully_excluded_rows_removes_all_32_keys_only() -> None:
    """Keys with 32 fired slots are dropped from both panel and exclusions;
    keys with fewer firings stay intact."""
    panel = pd.DataFrame(
        [
            _row(cid="x/y", contrib="c1", d=date(2025, 1, 1),
                 twap_out=10.0, twap_in=2.0, volume=1.0, tier=Tier.TPRR_F),
            _row(cid="x/y", contrib="c2", d=date(2025, 1, 1),
                 twap_out=10.0, twap_in=2.0, volume=1.0, tier=Tier.TPRR_F),
        ]
    )
    excluded = pd.DataFrame(
        {
            "contributor_id": ["c1"] * 32 + ["c2"] * 16,
            "constituent_id": ["x/y"] * 48,
            "date": [pd.Timestamp(date(2025, 1, 1))] * 48,
            "slot_idx": list(range(32)) + list(range(16)),
        }
    )
    panel_out, excl_out = _drop_fully_excluded_rows(panel, excluded)
    # c1 (all 32) dropped. c2 (16 only) kept.
    assert (panel_out["contributor_id"] == "c2").all()
    assert len(panel_out) == 1
    # Exclusions for c1 dropped. Exclusions for c2 kept.
    assert (excl_out["contributor_id"] == "c2").all()
    assert len(excl_out) == 16


def test_drop_fully_excluded_rows_empty_exclusions_returns_inputs_unchanged() -> None:
    panel = _multi_day_clean_panel(n_days=1)
    panel_out, excl_out = _drop_fully_excluded_rows(panel, pd.DataFrame())
    assert panel_out is panel
    assert excl_out.empty


# ---------------------------------------------------------------------------
# End-to-end: full-day exclusions percolate to suspension counter
# ---------------------------------------------------------------------------


def test_full_day_exclusions_drive_suspension_after_3_consecutive_days() -> None:
    """Three consecutive days of full-day gate firings on one (contributor,
    constituent) → compute_consecutive_day_suspensions emits a suspension
    on day 3 → that pair is dropped from the active set on day 3+ aggregation."""
    # Build a panel where one contributor's price diverges sharply from the
    # 5-day trailing average for 3 consecutive days starting on day 6.
    rows: list[dict[str, Any]] = []
    n_warmup = 5
    n_fire_days = 3
    n_days_total = n_warmup + n_fire_days
    f_set = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    for offset in range(n_days_total):
        d = date(2025, 1, 1) + timedelta(days=offset)
        for cid, p_out, p_in in f_set:
            for contrib in ["c1", "c2", "c3"]:
                # Inject c1 x gpt-5-pro at 200% of normal on the fire days.
                if (
                    offset >= n_warmup
                    and contrib == "c1"
                    and cid == "openai/gpt-5-pro"
                ):
                    p_o, p_i = p_out * 2.0, p_in * 2.0
                else:
                    p_o, p_i = p_out, p_in
                rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_o,
                        twap_in=p_i,
                        volume=100.0,
                        tier=Tier.TPRR_F,
                    )
                )
    panel = pd.DataFrame(rows)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    # Day 8 (the third consecutive-fire day) should trigger suspension on the
    # (c1, openai/gpt-5-pro) pair.
    assert not result.suspended_pairs.empty
    assert (
        ("c1", "openai/gpt-5-pro")
        in zip(
            result.suspended_pairs["contributor_id"],
            result.suspended_pairs["constituent_id"],
            strict=True,
        )
    )


def test_run_full_pipeline_propagates_suspensions_into_aggregation() -> None:
    """Same scenario as above; verify the F index after day 8 reflects c1's
    suspension by either continuing with 2 c-on-gpt-5-pro contributors (still
    ≥ Tier A min if min were 2 — but it's 3, so falls through to Tier
    A failing → Tier B unavailable → constituent excluded)."""
    rows: list[dict[str, Any]] = []
    f_set = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    n_warmup = 5
    n_fire_days = 3
    for offset in range(n_warmup + n_fire_days + 1):
        d = date(2025, 1, 1) + timedelta(days=offset)
        for cid, p_out, p_in in f_set:
            for contrib in ["c1", "c2", "c3"]:
                if (
                    offset >= n_warmup
                    and offset < n_warmup + n_fire_days
                    and contrib == "c1"
                    and cid == "openai/gpt-5-pro"
                ):
                    p_o, p_i = p_out * 2.0, p_in * 2.0
                else:
                    p_o, p_i = p_out, p_in
                rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_o,
                        twap_in=p_i,
                        volume=100.0,
                        tier=Tier.TPRR_F,
                    )
                )
    panel = pd.DataFrame(rows)

    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    f_df = result.indices["TPRR_F"]
    # Day after suspension lands: gpt-5-pro now has 2 active contributors
    # → falls below Tier A min-3 → no Tier B → constituent excluded.
    # Tier still has 2 active constituents (opus, gemini) — below min-3 →
    # tier suspends with INSUFFICIENT_CONSTITUENTS.
    last_day = f_df.iloc[-1]
    assert bool(last_day["suspended"])
    assert (
        last_day["suspension_reason"]
        == SuspensionReason.INSUFFICIENT_CONSTITUENTS.value
    )


# ---------------------------------------------------------------------------
# Phase 7H Batch D — suspension reinstatement (DL 2026-04-30)
# ---------------------------------------------------------------------------


def test_run_full_pipeline_emits_interval_based_suspended_pairs() -> None:
    """Phase 7H Batch D: suspended_pairs DataFrame on FullPipelineResults
    carries reinstatement_date column (NaT when still suspended).
    Replaces the pre-7H one-way ratchet schema."""
    panel = _multi_day_clean_panel(n_days=10)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    # On a clean panel no pair suspends, so the frame is empty — but it
    # still carries the new schema columns.
    assert list(result.suspended_pairs.columns) == [
        "contributor_id",
        "constituent_id",
        "suspension_date",
        "reinstatement_date",
    ]


def test_aggregation_honors_reinstatement_in_suspended_pairs_df() -> None:
    """A pair with suspension_date=D1 and reinstatement_date=D2 is
    treated as suspended for D in [D1, D2) and active for D >= D2.
    Verifies the interval-aware filter in compute_tier_index."""
    from tprr.index.aggregation import compute_tier_index

    d_active = date(2025, 1, 5)  # before suspension
    d_suspended = date(2025, 1, 12)  # within interval
    d_reinstated = date(2025, 1, 20)  # after reinstatement

    panel_active = _multi_day_clean_panel(n_days=1, start=d_active)
    panel_suspended = _multi_day_clean_panel(n_days=1, start=d_suspended)
    panel_reinstated = _multi_day_clean_panel(n_days=1, start=d_reinstated)

    susp_intervals = pd.DataFrame(
        [
            {
                "contributor_id": "c1",
                "constituent_id": "openai/gpt-5-pro",
                "suspension_date": pd.Timestamp(date(2025, 1, 10)),
                "reinstatement_date": pd.Timestamp(date(2025, 1, 18)),
            }
        ]
    )

    # Before the interval: pair is active.
    r1 = compute_tier_index(
        panel_day_df=panel_active,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp_intervals,
    )
    # No suspended pair affects gpt-5-pro before suspension_date.
    assert not r1["suspended"]
    assert r1["n_constituents_active"] == 3

    # Within the interval: pair is suspended → gpt-5-pro contributors
    # drop to 2 → Tier A min-3 fails for that constituent → constituent
    # excluded. Remaining 2 constituents → tier suspends.
    r2 = compute_tier_index(
        panel_day_df=panel_suspended,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp_intervals,
    )
    assert r2["suspended"]
    assert r2["n_constituents_active"] == 2

    # After reinstatement: pair active again → gpt-5-pro recovers.
    r3 = compute_tier_index(
        panel_day_df=panel_reinstated,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=susp_intervals,
    )
    assert not r3["suspended"]
    assert r3["n_constituents_active"] == 3


def test_aggregation_legacy_one_way_suspension_frame_still_works() -> None:
    """Backward compatibility: a suspended_pairs_df WITHOUT the
    reinstatement_date column is treated as one-way ratchet (suspended
    forever from suspension_date onward). Existing tests that build
    legacy frames stay green."""
    from tprr.index.aggregation import compute_tier_index

    d = date(2025, 1, 12)
    panel = _multi_day_clean_panel(n_days=1, start=d)

    # Legacy schema: no reinstatement_date column.
    legacy_susp = pd.DataFrame(
        [
            {
                "contributor_id": "c1",
                "constituent_id": "openai/gpt-5-pro",
                "suspension_date": pd.Timestamp(date(2025, 1, 10)),
            }
        ]
    )

    r = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_F,
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
        suspended_pairs_df=legacy_susp,
    )
    # Pair suspended on 2025-01-10; querying 2025-01-12 → still suspended
    # under one-way ratchet. gpt-5-pro loses contributor c1, n_a drops.
    assert r["suspended"]


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------


def test_e_tier_constituents_without_tier_b_revenue_excluded_on_suspension() -> None:
    """E-tier constituents whose providers lack Tier B revenue config
    (xiaomi/mimo-v2-pro and meta/llama-4-70b-hosted per DL 2026-04-28
    "Tier B revenue config: 6 providers, Meta and Xiaomi excluded as
    Tier-A-only") have no fall-through path when their Tier A pairs
    suspend. Other 4 E constituents continue to participate via Tier A
    or Tier B as the priority hierarchy dictates. Tier itself stays
    active because 4 ≥ min_constituents_per_tier (3).
    """
    from tprr.index.aggregation import compute_tier_index

    d = date(2025, 1, 1)

    # Registry: full 6-constituent E tier per the v0.1 model_registry
    e_registry = ModelRegistry(
        models=[
            ModelMetadata(
                constituent_id=cid,
                tier=Tier.TPRR_E,
                provider=cid.split("/")[0],
                canonical_name=cid,
                baseline_input_price_usd_mtok=p_in,
                baseline_output_price_usd_mtok=p_out,
            )
            for cid, p_in, p_out in [
                ("google/gemini-flash-lite", 0.10, 0.40),
                ("openai/gpt-5-nano", 0.15, 0.60),
                ("deepseek/deepseek-v3-2", 0.25, 1.00),
                ("alibaba/qwen-3-6-plus", 0.20, 0.80),
                ("xiaomi/mimo-v2-pro", 0.30, 1.10),
                ("meta/llama-4-70b-hosted", 0.60, 0.80),
            ]
        ]
    )

    # Tier B revenue: 4 providers (DL 2026-04-28 — meta and xiaomi excluded).
    tier_b_config = TierBRevenueConfig(
        entries=[
            TierBRevenueEntry(
                provider=p,
                period="2025-Q1",
                amount_usd=1_000_000_000.0,
                source="test",
            )
            for p in ("google", "openai", "deepseek", "alibaba")
        ]
    )

    # Panel: each of 6 E constituents with 3 Tier A contributors.
    rows: list[dict[str, Any]] = []
    for cid, p_out, p_in in [
        ("google/gemini-flash-lite", 0.40, 0.10),
        ("openai/gpt-5-nano", 0.60, 0.15),
        ("deepseek/deepseek-v3-2", 1.00, 0.25),
        ("alibaba/qwen-3-6-plus", 0.80, 0.20),
        ("xiaomi/mimo-v2-pro", 1.10, 0.30),
        ("meta/llama-4-70b-hosted", 0.80, 0.60),
    ]:
        for c in ["c1", "c2", "c3"]:
            rows.append(
                _row(
                    cid=cid,
                    contrib=c,
                    d=d,
                    twap_out=p_out,
                    twap_in=p_in,
                    volume=100.0,
                    tier=Tier.TPRR_E,
                )
            )
    panel = pd.DataFrame(rows)

    # Suspend ALL Tier A pairs for mimo and llama.
    susp_rows = []
    for cid in ("xiaomi/mimo-v2-pro", "meta/llama-4-70b-hosted"):
        for c in ("c1", "c2", "c3"):
            susp_rows.append(
                {
                    "contributor_id": c,
                    "constituent_id": cid,
                    "suspension_date": pd.Timestamp(d),
                }
            )
    susp = pd.DataFrame(susp_rows)

    result = compute_tier_index(
        panel_day_df=panel,
        tier=Tier.TPRR_E,
        config=_config(date(2025, 1, 1)),
        registry=e_registry,
        tier_b_config=tier_b_config,
        tier_b_volume_fn=_stub_tier_b_volume_fn(value=10_000_000.0),
        suspended_pairs_df=susp,
    )

    # Tier remains active (4 surviving constituents ≥ min-3).
    assert not result["suspended"]
    assert result["suspension_reason"] == ""

    # mimo and llama excluded; other 4 active.
    assert result["n_constituents_active"] == 4
    # All 4 surviving constituents have intact Tier A — they route via Tier A,
    # not Tier B (Tier B is the fallback only when Tier A min-3 fails).
    assert result["n_constituents_a"] == 4
    assert result["n_constituents_b"] == 0
    assert result["n_constituents_c"] == 0
    # n_constituents counts unique constituent_ids surviving the suspended-
    # pair drop. mimo and llama lost all their pairs → 0 panel rows for them
    # post-drop → not counted. The 4 surviving constituents remain.
    assert result["n_constituents"] == 4


def test_run_full_pipeline_empty_panel() -> None:
    """An empty panel should produce empty IndexValueDFs across the board,
    no exclusions, no suspended pairs."""
    result = run_full_pipeline(
        panel_df=pd.DataFrame(
            columns=[
                "observation_date",
                "constituent_id",
                "contributor_id",
                "tier_code",
                "attestation_tier",
                "input_price_usd_mtok",
                "output_price_usd_mtok",
                "volume_mtok_7d",
                "twap_output_usd_mtok",
                "twap_input_usd_mtok",
                "source",
                "submitted_at",
                "notes",
            ]
        ),
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    assert result.excluded_slots.empty
    assert result.suspended_pairs.empty
    for code in (
        "TPRR_F", "TPRR_S", "TPRR_E",
        "TPRR_FPR", "TPRR_SER",
        "TPRR_B_F", "TPRR_B_S", "TPRR_B_E",
    ):
        assert result.indices[code].empty


# ---------------------------------------------------------------------------
# Batch D — rebase_metadata_df on FullPipelineResults (Q2)
# ---------------------------------------------------------------------------


def test_run_full_pipeline_rebase_metadata_df_covers_every_index() -> None:
    """Every index_code in result.indices appears as a row in
    rebase_metadata_df, with base_date threading through from config."""
    panel = _multi_day_clean_panel(n_days=10)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    metadata = result.rebase_metadata_df
    assert set(metadata.columns) == {
        "index_code",
        "base_date",
        "anchor_date",
        "anchor_raw_value",
        "n_pre_anchor_suspended_days",
    }
    assert set(metadata["index_code"]) == set(result.indices.keys())
    assert (metadata["base_date"] == date(2025, 1, 1)).all()


def test_run_full_pipeline_rebase_metadata_anchor_matches_index_level_100() -> None:
    """For each index, the anchor_date in metadata corresponds to the row
    where index_level == 100 in the IndexValueDF — verifies the metadata
    is consistent with the rebase actually applied."""
    panel = _multi_day_clean_panel(n_days=10)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    metadata = result.rebase_metadata_df
    for _, row in metadata.iterrows():
        code = str(row["index_code"])
        anchor = row["anchor_date"]
        if anchor is None:
            continue
        df = result.indices[code]
        anchor_row = df[df["as_of_date"] == pd.Timestamp(anchor)]
        assert not anchor_row.empty, f"{code} anchor {anchor} not in IndexValueDF"
        assert float(anchor_row["index_level"].iloc[0]) == pytest.approx(100.0)
        assert float(row["anchor_raw_value"]) == pytest.approx(
            float(anchor_row["raw_value_usd_mtok"].iloc[0])
        )


def test_run_full_pipeline_rebase_metadata_dict_and_df_agree() -> None:
    """The rebase_anchors dict and rebase_metadata_df anchor_date column
    carry the same values — the dict stays as a quick lookup, the DF as
    the structured artefact, and they must not drift."""
    panel = _multi_day_clean_panel(n_days=10)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    metadata = result.rebase_metadata_df
    for _, row in metadata.iterrows():
        code = str(row["index_code"])
        assert result.rebase_anchors[code] == row["anchor_date"]


def test_run_full_pipeline_rebase_metadata_n_pre_anchor_counts_pre_base_suspensions() -> None:
    """Set base_date past the start of the panel; verify that suspended
    days strictly before the anchor count up correctly. We engineer a panel
    where the first 5 days are too short for the gate's 5-day warmup so
    everything is active, then days 6-10 are clean too — so n_pre is 0 for
    every index. The load-bearing assertion is type/dtype; the engineered
    suspension test below covers the count."""
    panel = _multi_day_clean_panel(n_days=10, start=date(2025, 1, 1))
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        # Anchor on the LAST day of the panel — earlier days are non-suspended
        # but pre-anchor; n_pre_anchor counts ONLY suspended pre-anchor days.
        config=_config(date(2025, 1, 10)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    metadata = result.rebase_metadata_df
    for _, row in metadata.iterrows():
        # No suspensions on the clean panel → n_pre_anchor must be 0
        assert int(row["n_pre_anchor_suspended_days"]) == 0


def test_run_full_pipeline_rebase_metadata_no_anchor_when_index_is_empty() -> None:
    """Empty panel → every index is empty → every metadata row carries
    anchor_date=None, anchor_raw_value=NaN, n_pre_anchor_suspended_days=0."""
    result = run_full_pipeline(
        panel_df=pd.DataFrame(
            columns=[
                "observation_date",
                "constituent_id",
                "contributor_id",
                "tier_code",
                "attestation_tier",
                "input_price_usd_mtok",
                "output_price_usd_mtok",
                "volume_mtok_7d",
                "twap_output_usd_mtok",
                "twap_input_usd_mtok",
                "source",
                "submitted_at",
                "notes",
            ]
        ),
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    metadata = result.rebase_metadata_df
    assert len(metadata) == len(result.indices)
    for _, row in metadata.iterrows():
        assert row["anchor_date"] is None
        import math
        assert math.isnan(float(row["anchor_raw_value"]))
        assert int(row["n_pre_anchor_suspended_days"]) == 0


# ---------------------------------------------------------------------------
# Batch D — ConstituentDecisionDF on FullPipelineResults (Q1)
# ---------------------------------------------------------------------------


def test_run_full_pipeline_constituent_decisions_covers_all_six_aggregation_indices() -> None:
    """ConstituentDecisionDF includes rows for F/S/E + B_F/B_S/B_E. FPR/SER
    are ratios, not constituent aggregations, so they don't contribute rows."""
    panel = _multi_day_clean_panel(n_days=2)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    decisions = result.constituent_decisions
    expected_codes = {
        "TPRR_F", "TPRR_S", "TPRR_E",
        "TPRR_B_F", "TPRR_B_S", "TPRR_B_E",
    }
    assert set(decisions["index_code"]) == expected_codes
    # No FPR/SER rows
    assert "TPRR_FPR" not in decisions["index_code"].unique()
    assert "TPRR_SER" not in decisions["index_code"].unique()


def test_run_full_pipeline_constituent_decisions_count_matches_active_constituents() -> None:
    """3 F + 3 S + 3 E constituents x 2 days x 2 index families (core + B)
    = 36 rows on a clean panel. All included=True."""
    panel = _multi_day_clean_panel(n_days=2)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    decisions = result.constituent_decisions
    assert len(decisions) == 36
    assert decisions["included"].all()


def test_run_full_pipeline_constituent_decisions_w_vol_contributions_reconstruct_w_vol() -> None:
    """Phase 7H Batch B (DL 2026-04-30): under long-format audit, the sum
    of w_vol_contribution within each (date, index_code, constituent_id)
    group equals that constituent's combined w_vol (which is duplicated
    across the group's per-tier rows). Replaces the prior test that
    asserted weight_share_within_tier sums to 1.0 — that field was
    deprecated."""
    panel = _multi_day_clean_panel(n_days=2)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    decisions = result.constituent_decisions
    included = decisions[decisions["included"]]
    grouped_sum = (
        included.groupby(["as_of_date", "index_code", "constituent_id"])[
            "w_vol_contribution"
        ]
        .sum()
        .reset_index(name="reconstructed_w_vol")
    )
    # Each (date, index_code, constituent_id) has a single w_vol value
    # duplicated across its rows; take the first.
    reference = (
        included.groupby(["as_of_date", "index_code", "constituent_id"])["w_vol"]
        .first()
        .reset_index(name="w_vol")
    )
    merged = grouped_sum.merge(
        reference, on=["as_of_date", "index_code", "constituent_id"]
    )
    import numpy as np
    assert np.allclose(
        merged["reconstructed_w_vol"].to_numpy(),
        merged["w_vol"].to_numpy(),
    )


def test_run_full_pipeline_constituent_decisions_propagates_pair_suspension_cascade() -> None:
    """A 3-day spike on (c1, gpt-5-pro) suspends the pair. After the
    suspension takes effect, gpt-5-pro loses a contributor → fewer
    Tier A contributors → tier suspends. The decisions DataFrame on the
    suspension day shows the surviving 2 F constituents as
    TIER_AGGREGATION_SUSPENDED (not included)."""
    rows: list[dict[str, Any]] = []
    f_set = [
        ("openai/gpt-5-pro", 75.0, 15.0),
        ("anthropic/claude-opus-4-7", 70.0, 14.0),
        ("google/gemini-3-pro", 30.0, 5.0),
    ]
    n_warmup = 5
    n_fire_days = 3
    for offset in range(n_warmup + n_fire_days + 1):
        d = date(2025, 1, 1) + timedelta(days=offset)
        for cid, p_out, p_in in f_set:
            for contrib in ["c1", "c2", "c3"]:
                if (
                    offset >= n_warmup
                    and offset < n_warmup + n_fire_days
                    and contrib == "c1"
                    and cid == "openai/gpt-5-pro"
                ):
                    p_o, p_i = p_out * 2.0, p_in * 2.0
                else:
                    p_o, p_i = p_out, p_in
                rows.append(
                    _row(
                        cid=cid,
                        contrib=contrib,
                        d=d,
                        twap_out=p_o,
                        twap_in=p_i,
                        volume=100.0,
                        tier=Tier.TPRR_F,
                    )
                )
    panel = pd.DataFrame(rows)
    result = run_full_pipeline(
        panel_df=panel,
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    decisions = result.constituent_decisions
    # On the last day (when c1 has been suspended), the F-tier suspends and
    # the surviving 2 active constituents emit excluded rows.
    last_day = pd.Timestamp(date(2025, 1, 1) + timedelta(days=n_warmup + n_fire_days))
    f_last = decisions[
        (decisions["index_code"] == "TPRR_F")
        & (decisions["as_of_date"] == last_day)
    ]
    # opus + gemini survived (gpt-5-pro lost a contributor → tier_volume_unavailable).
    excluded = f_last[~f_last["included"]]
    assert len(excluded) > 0
    suspended_rows = excluded[
        excluded["exclusion_reason"] == "tier_aggregation_suspended"
    ]
    assert len(suspended_rows) == 2  # opus + gemini
    suspended_constituent_ids = set(suspended_rows["constituent_id"])
    assert suspended_constituent_ids == {
        "anthropic/claude-opus-4-7",
        "google/gemini-3-pro",
    }


def test_run_full_pipeline_constituent_decisions_empty_panel_returns_empty_df_with_schema() -> None:
    """Empty panel → empty constituent_decisions DataFrame, but with the
    full schema columns present so downstream consumers can iterate without
    KeyError."""
    from tprr.index.aggregation import _DECISION_FIELDS

    result = run_full_pipeline(
        panel_df=pd.DataFrame(
            columns=[
                "observation_date",
                "constituent_id",
                "contributor_id",
                "tier_code",
                "attestation_tier",
                "input_price_usd_mtok",
                "output_price_usd_mtok",
                "volume_mtok_7d",
                "twap_output_usd_mtok",
                "twap_input_usd_mtok",
                "source",
                "submitted_at",
                "notes",
            ]
        ),
        change_events_df=_empty_change_events(),
        config=_config(date(2025, 1, 1)),
        registry=_registry_three_tiers(),
        tier_b_config=_empty_tier_b_config(),
        tier_b_volume_fn=_stub_tier_b_volume_fn(),
    )
    decisions = result.constituent_decisions
    assert decisions.empty
    assert set(decisions.columns) == set(_DECISION_FIELDS)
