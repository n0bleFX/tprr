"""Tests for tprr.viz.charts — Phase 9 chart builder primitives.

Convention: test figure JSON shape (n traces, axis labels, subplot
layout) rather than pixel diffs. Pixel comparisons are brittle across
Plotly versions; structural assertions catch the regressions that
matter (missing trace, wrong axis label, wrong colour).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import pytest
from plotly.subplots import make_subplots

from tprr.viz.charts import (
    ATTESTATION_TIER_COLOURS,
    BLENDED_REFERENCE_RATIO,
    GRID_COLOUR,
    SUSPENDED_MARKER_COLOUR,
    TIER_COLOURS,
    build_blended_overlay_subplot,
    build_index_level_subplot,
    build_n_constituents_subplot,
    build_ratio_subplot,
    build_scenario_overlay_subplot,
    build_tier_share_subplot,
)


def _index_value_row(
    *,
    as_of_date: date,
    index_code: str = "TPRR_F",
    index_level: float = 100.0,
    raw_value: float = 56.0,
    suspended: bool = False,
    suspension_reason: str = "",
) -> dict[str, Any]:
    return {
        "as_of_date": pd.Timestamp(as_of_date),
        "index_code": index_code,
        "version": "v0_1",
        "lambda": 3.0,
        "ordering": "twap_then_weight",
        "raw_value_usd_mtok": raw_value,
        "index_level": index_level,
        "n_constituents": 6,
        "n_constituents_active": 6,
        "n_constituents_a": 6,
        "n_constituents_b": 0,
        "n_constituents_c": 0,
        "tier_a_weight_share": 1.0,
        "tier_b_weight_share": 0.0,
        "tier_c_weight_share": 0.0,
        "suspended": suspended,
        "suspension_reason": suspension_reason,
        "notes": "",
    }


def _three_day_indices_df(
    *,
    index_code: str = "TPRR_F",
    suspended_dates: list[date] | None = None,
) -> pd.DataFrame:
    suspended_set = set(suspended_dates or [])
    rows = []
    levels = [98.0, 100.0, 102.0]
    for offset, lvl in enumerate(levels):
        d = date(2025, 12, 30) + pd.Timedelta(days=offset)
        d = d.date() if hasattr(d, "date") else d
        is_suspended = d in suspended_set
        rows.append(
            _index_value_row(
                as_of_date=d,
                index_code=index_code,
                index_level=float("nan") if is_suspended else lvl,
                suspended=is_suspended,
                suspension_reason=(
                    "insufficient_constituents" if is_suspended else ""
                ),
            )
        )
    return pd.DataFrame(rows)


def _empty_subplot_fig() -> go.Figure:
    """Single-cell make_subplots fig — emulates the dashboard composer."""
    return make_subplots(rows=1, cols=1)


# ---------------------------------------------------------------------------
# build_index_level_subplot
# ---------------------------------------------------------------------------


def test_build_index_level_subplot_adds_one_line_trace_on_clean_df() -> None:
    """Clean data (no suspended days) → one Scatter trace, mode='lines'."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df()
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    assert len(fig.data) == 1
    trace = fig.data[0]
    assert trace.type == "scatter"
    assert trace.mode == "lines"
    assert trace.name == "TPRR_F"


def test_build_index_level_subplot_uses_tier_colour() -> None:
    """Trace colour comes from TIER_COLOURS dict for the supplied index_code."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(index_code="TPRR_F")
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    assert fig.data[0].line.color == TIER_COLOURS["TPRR_F"]


def test_build_index_level_subplot_adds_marker_for_suspended_days() -> None:
    """Suspended day → second Scatter trace with markers + red colour."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(suspended_dates=[date(2025, 12, 31)])
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    assert len(fig.data) == 2
    line_trace, marker_trace = fig.data
    assert line_trace.mode == "lines"
    assert marker_trace.mode == "markers"
    assert marker_trace.marker.color == SUSPENDED_MARKER_COLOUR


def test_build_index_level_subplot_no_marker_when_no_suspension() -> None:
    fig = _empty_subplot_fig()
    df = _three_day_indices_df()
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    assert len(fig.data) == 1


def test_build_index_level_subplot_sets_y_axis_label_and_grid() -> None:
    """Y-axis carries the unit label; both axes use the institutional grid."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df()
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    yaxis_layout = fig.layout.yaxis
    assert "rebased to 100" in yaxis_layout.title.text
    assert yaxis_layout.gridcolor == GRID_COLOUR


def test_build_index_level_subplot_handles_empty_df_silently() -> None:
    """Empty input → no traces added, no exception. Lets the dashboard
    compose missing-data subplots without special-casing in the composer."""
    fig = _empty_subplot_fig()
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=pd.DataFrame(), index_code="TPRR_F"
    )
    assert len(fig.data) == 0


def test_build_index_level_subplot_suspended_marker_carries_reason_in_customdata() -> None:
    """Hovering a suspended-day marker must surface the suspension_reason
    so analysts can see why the line gapped — DL 2026-04-30 Phase 7 schema
    additions exposed n_a/b/c and suspension_reason for exactly this kind
    of audit visualisation."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(suspended_dates=[date(2025, 12, 31)])
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    marker_trace = fig.data[1]
    assert "insufficient_constituents" in list(marker_trace.customdata)


def test_build_index_level_subplot_works_with_multi_subplot_grid() -> None:
    """Builder targets the (row, col) it's told to. Composing two builders
    on a 1x2 grid → each has its own trace in the right subplot.

    Verified via the per-trace ``xaxis``/``yaxis`` reference set by
    make_subplots. Plotly assigns subplot 1 to xaxis/yaxis and subplot 2
    to xaxis2/yaxis2."""
    fig = make_subplots(rows=1, cols=2)
    df = _three_day_indices_df()
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    build_index_level_subplot(
        fig, row=1, col=2, indices_df=df, index_code="TPRR_S"
    )
    assert len(fig.data) == 2
    # First trace targets subplot 1 (xaxis="x"), second targets subplot 2.
    assert fig.data[0].xaxis == "x"
    assert fig.data[1].xaxis == "x2"


def test_tier_colours_dict_covers_all_eight_index_codes() -> None:
    """Every index_code emitted by the pipeline must have a colour assigned;
    missing entries fall back to a default but lose the institutional palette
    consistency. Pin the eight expected codes."""
    expected = {
        "TPRR_F", "TPRR_S", "TPRR_E",
        "TPRR_FPR", "TPRR_SER",
        "TPRR_B_F", "TPRR_B_S", "TPRR_B_E",
    }
    assert expected.issubset(set(TIER_COLOURS.keys()))


def test_build_index_level_subplot_does_not_set_legend_for_marker_trace() -> None:
    """The suspended-day markers are diagnostic, not a real series — they
    must not add legend clutter alongside the main line."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(suspended_dates=[date(2025, 12, 31)])
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_F"
    )
    _line_trace, marker_trace = fig.data
    assert marker_trace.showlegend is False


# ---------------------------------------------------------------------------
# Sanity: hover content
# ---------------------------------------------------------------------------


def test_build_index_level_subplot_hovertemplate_includes_index_code() -> None:
    """Hover labels carry the index_code so multi-panel dashboards remain
    self-describing on hover."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(index_code="TPRR_S")
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_S"
    )
    assert "TPRR_S" in fig.data[0].hovertemplate


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index_code", ["TPRR_F", "TPRR_S", "TPRR_E"])
def test_build_index_level_subplot_each_core_tier(index_code: str) -> None:
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(index_code=index_code)
    build_index_level_subplot(
        fig, row=1, col=1, indices_df=df, index_code=index_code
    )
    assert fig.data[0].name == index_code
    assert fig.data[0].line.color == TIER_COLOURS[index_code]


# ---------------------------------------------------------------------------
# build_ratio_subplot — Batch B
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index_code", ["TPRR_FPR", "TPRR_SER"])
def test_build_ratio_subplot_each_ratio_index(index_code: str) -> None:
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(index_code=index_code)
    build_ratio_subplot(
        fig, row=1, col=1, indices_df=df, index_code=index_code
    )
    assert len(fig.data) == 1
    assert fig.data[0].name == index_code
    assert fig.data[0].line.color == TIER_COLOURS[index_code]


def test_build_ratio_subplot_y_axis_label_says_ratio_not_index_level() -> None:
    """The ratio axis label distinguishes ratio panels from level panels —
    a ratio of two indices is dimensionally different from a constituent-
    aggregation level."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(index_code="TPRR_FPR")
    build_ratio_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_FPR"
    )
    yaxis_text = fig.layout.yaxis.title.text
    assert "Ratio" in yaxis_text
    assert "Index level" not in yaxis_text


def test_build_ratio_subplot_handles_empty_df_silently() -> None:
    fig = _empty_subplot_fig()
    build_ratio_subplot(
        fig, row=1, col=1, indices_df=pd.DataFrame(), index_code="TPRR_FPR"
    )
    assert len(fig.data) == 0


def test_build_ratio_subplot_marks_suspended_days() -> None:
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(
        index_code="TPRR_SER", suspended_dates=[date(2025, 12, 31)]
    )
    build_ratio_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_SER"
    )
    assert len(fig.data) == 2
    _line, marker = fig.data
    assert marker.marker.color == SUSPENDED_MARKER_COLOUR
    assert marker.showlegend is False


def test_build_ratio_subplot_hovertemplate_says_ratio_level() -> None:
    """Hover label text reflects the ratio dimension, not 'Index level'."""
    fig = _empty_subplot_fig()
    df = _three_day_indices_df(index_code="TPRR_FPR")
    build_ratio_subplot(
        fig, row=1, col=1, indices_df=df, index_code="TPRR_FPR"
    )
    assert "Ratio level" in fig.data[0].hovertemplate


# ---------------------------------------------------------------------------
# build_blended_overlay_subplot — Batch B
# ---------------------------------------------------------------------------


def _build_paired_dfs(
    *,
    core_raw: list[float],
    blended_raw: list[float],
    suspended: list[bool] | None = None,
    core_code: str = "TPRR_F",
    blended_code: str = "TPRR_B_F",
    n_days: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build (core_df, blended_df) covering n_days at the given raw values.

    Both DataFrames share the same dates so the inner-join in the overlay
    builder produces n_days rows.
    """
    n = n_days if n_days is not None else max(len(core_raw), len(blended_raw))
    suspended = suspended if suspended is not None else [False] * n
    rows_core = []
    rows_blend = []
    for i in range(n):
        d = date(2025, 12, 30) + pd.Timedelta(days=i)
        d = d.date() if hasattr(d, "date") else d
        rows_core.append(
            _index_value_row(
                as_of_date=d,
                index_code=core_code,
                index_level=100.0,
                raw_value=core_raw[i],
                suspended=suspended[i],
            )
        )
        rows_blend.append(
            _index_value_row(
                as_of_date=d,
                index_code=blended_code,
                index_level=100.0,
                raw_value=blended_raw[i],
                suspended=suspended[i],
            )
        )
    return pd.DataFrame(rows_core), pd.DataFrame(rows_blend)


def test_build_blended_overlay_subplot_emits_single_ratio_line_plus_reference() -> None:
    """Overlay panel plots one ratio line (B_X / X) plus a horizontal
    reference line at the methodology baseline (0.80). Two traces total."""
    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0, 100.0, 100.0],
        blended_raw=[80.0, 80.0, 80.0],
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    assert len(fig.data) == 2
    ratio_trace, reference_trace = fig.data
    assert ratio_trace.name == "TPRR_B_F / TPRR_F"
    assert reference_trace.line.dash == "dot"
    assert reference_trace.showlegend is False


def test_build_blended_overlay_subplot_ratio_values_are_blended_div_core() -> None:
    """y values equal blended.raw / core.raw per day — the ratio
    isolation that motivates this redesign."""
    import numpy as np

    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0, 50.0, 25.0],
        blended_raw=[80.0, 40.0, 20.0],
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    ratio_trace = fig.data[0]
    expected = [0.80, 0.80, 0.80]
    assert np.allclose(np.array(ratio_trace.y, dtype=float), expected)


def test_build_blended_overlay_subplot_reference_line_at_080() -> None:
    """Horizontal reference at y=BLENDED_REFERENCE_RATIO=0.80 spans the
    full date range."""
    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0, 100.0, 100.0],
        blended_raw=[80.0, 80.0, 80.0],
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    reference_trace = fig.data[1]
    assert all(y == BLENDED_REFERENCE_RATIO for y in reference_trace.y)
    assert len(reference_trace.x) == 2  # endpoints only


def test_build_blended_overlay_subplot_y_axis_says_raw_value_ratio() -> None:
    """Y-axis label distinguishes the panel from the index-level panels —
    it's a raw-value ratio, not a rebased-to-100 series."""
    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0], blended_raw=[80.0]
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    yaxis_text = fig.layout.yaxis.title.text
    assert "raw value ratio" in yaxis_text
    # Y range hint: 0 to 1.2 keeps the ~0.80 line mid-chart
    assert tuple(fig.layout.yaxis.range) == (0.0, 1.2)


def test_build_blended_overlay_subplot_handles_empty_dfs() -> None:
    """Either side empty → no traces, no exception."""
    fig = _empty_subplot_fig()
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=pd.DataFrame(), blended_df=pd.DataFrame(),
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    assert len(fig.data) == 0


def test_build_blended_overlay_subplot_one_empty_renders_nothing() -> None:
    """A ratio with only one side defined is undefined — no traces, no
    silent rendering of just the populated side as a misleading line."""
    fig = _empty_subplot_fig()
    core_df, _ = _build_paired_dfs(
        core_raw=[100.0], blended_raw=[80.0]
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=pd.DataFrame(),
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    assert len(fig.data) == 0


def test_build_blended_overlay_subplot_suspended_day_masks_ratio() -> None:
    """If either series is suspended on a date, the ratio is NaN that day."""
    import numpy as np

    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0, 100.0, 100.0],
        blended_raw=[80.0, 80.0, 80.0],
        suspended=[False, True, False],
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    ratio_y = list(fig.data[0].y)
    assert ratio_y[0] == 0.80
    assert np.isnan(ratio_y[1])
    assert ratio_y[2] == 0.80


def test_build_blended_overlay_subplot_hovertemplate_shows_raws_and_ratio() -> None:
    """Hover surfaces both raw values and the computed ratio so a reader
    can sanity-check the formula effect at any point on the line."""
    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0], blended_raw=[80.0]
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code="TPRR_F", blended_code="TPRR_B_F",
    )
    hover = fig.data[0].hovertemplate
    assert "TPRR_B_F raw" in hover
    assert "TPRR_F raw" in hover
    assert "Ratio" in hover


@pytest.mark.parametrize(
    ("core", "blended"),
    [
        ("TPRR_F", "TPRR_B_F"),
        ("TPRR_S", "TPRR_B_S"),
        ("TPRR_E", "TPRR_B_E"),
    ],
)
def test_build_blended_overlay_subplot_each_tier(core: str, blended: str) -> None:
    fig = _empty_subplot_fig()
    core_df, blended_df = _build_paired_dfs(
        core_raw=[100.0], blended_raw=[80.0],
        core_code=core, blended_code=blended,
    )
    build_blended_overlay_subplot(
        fig,
        row=1, col=1,
        core_df=core_df, blended_df=blended_df,
        core_code=core, blended_code=blended,
    )
    # One ratio line + one reference line
    assert len(fig.data) == 2
    assert fig.data[0].name == f"{blended} / {core}"


# ---------------------------------------------------------------------------
# build_tier_share_subplot — Batch C (Group 2)
# ---------------------------------------------------------------------------


def _index_value_row_with_shares(
    *,
    as_of_date: date,
    index_code: str = "TPRR_F",
    share_a: float = 1.0,
    share_b: float = 0.0,
    share_c: float = 0.0,
    n_a: int = 6,
    n_b: int = 0,
    n_c: int = 0,
    suspended: bool = False,
) -> dict[str, Any]:
    return {
        "as_of_date": pd.Timestamp(as_of_date),
        "index_code": index_code,
        "version": "v0_1",
        "lambda": 3.0,
        "ordering": "twap_then_weight",
        "raw_value_usd_mtok": 56.0,
        "index_level": 100.0,
        "n_constituents": n_a + n_b + n_c,
        "n_constituents_active": n_a + n_b + n_c,
        "n_constituents_a": n_a,
        "n_constituents_b": n_b,
        "n_constituents_c": n_c,
        "tier_a_weight_share": share_a,
        "tier_b_weight_share": share_b,
        "tier_c_weight_share": share_c,
        "suspended": suspended,
        "suspension_reason": "insufficient_constituents" if suspended else "",
        "notes": "",
    }


def _shares_df_three_days(
    *,
    index_code: str = "TPRR_F",
    daily: list[tuple[float, float, float]] | None = None,
    suspended_dates: list[date] | None = None,
) -> pd.DataFrame:
    """Build a 3-day DF with per-day (share_a, share_b, share_c) tuples.

    Default trajectory shows the cascade: 100% A → 50/50 → 100% B."""
    daily = daily if daily is not None else [
        (1.0, 0.0, 0.0),
        (0.5, 0.5, 0.0),
        (0.0, 1.0, 0.0),
    ]
    suspended_set = set(suspended_dates or [])
    rows = []
    for offset, (sa, sb, sc) in enumerate(daily):
        d = date(2025, 12, 30) + pd.Timedelta(days=offset)
        d = d.date() if hasattr(d, "date") else d
        rows.append(
            _index_value_row_with_shares(
                as_of_date=d,
                index_code=index_code,
                share_a=sa,
                share_b=sb,
                share_c=sc,
                suspended=d in suspended_set,
            )
        )
    return pd.DataFrame(rows)


def test_build_tier_share_subplot_emits_three_stacked_traces() -> None:
    """Three stacked-area traces, one per attestation tier (A/B/C)."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    assert len(fig.data) == 3
    expected_names = {
        "TPRR_F Tier A",
        "TPRR_F Tier B",
        "TPRR_F Tier C",
    }
    assert {t.name for t in fig.data} == expected_names


def test_build_tier_share_subplot_uses_attestation_tier_palette() -> None:
    """Each trace's fillcolor matches ATTESTATION_TIER_COLOURS."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    fillcolors = {t.name.split()[-1]: t.fillcolor for t in fig.data}
    assert fillcolors["A"] == ATTESTATION_TIER_COLOURS["A"]
    assert fillcolors["B"] == ATTESTATION_TIER_COLOURS["B"]
    assert fillcolors["C"] == ATTESTATION_TIER_COLOURS["C"]


def test_build_tier_share_subplot_traces_use_stackgroup() -> None:
    """All three traces share the same stackgroup so Plotly stacks them
    cumulatively rather than drawing them as overlapping fills."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    stackgroups = {t.stackgroup for t in fig.data}
    assert len(stackgroups) == 1
    assert "share_TPRR_F" in stackgroups


def test_build_tier_share_subplot_y_range_clamped_to_0_1() -> None:
    """Weight shares sum to 1.0 by definition; y-axis pinned to that range
    so the panel reads at consistent scale across tiers."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    assert tuple(fig.layout.yaxis.range) == (0.0, 1.0)


def test_build_tier_share_subplot_suspended_day_produces_nan() -> None:
    """Suspended days are NaN'd out so the stacked area gaps rather than
    misleadingly stacking 0+0+0=0 (which would draw a flat baseline)."""
    import numpy as np

    fig = _empty_subplot_fig()
    df = _shares_df_three_days(suspended_dates=[date(2025, 12, 31)])
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    # Day index 1 is suspended → NaN in all three traces
    for trace in fig.data:
        assert np.isnan(list(trace.y)[1])


def test_build_tier_share_subplot_handles_empty_df_silently() -> None:
    fig = _empty_subplot_fig()
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=pd.DataFrame(), tier_code="TPRR_F"
    )
    assert len(fig.data) == 0


def test_build_tier_share_subplot_y_axis_label_says_tier_weight_share() -> None:
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    assert "Tier weight share" in fig.layout.yaxis.title.text


@pytest.mark.parametrize("tier_code", ["TPRR_F", "TPRR_S", "TPRR_E"])
def test_build_tier_share_subplot_each_tier(tier_code: str) -> None:
    """Stackgroup is unique per tier so multi-tier rendering on the same
    figure doesn't accidentally cross-stack."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days(index_code=tier_code)
    build_tier_share_subplot(
        fig, row=1, col=1, indices_df=df, tier_code=tier_code
    )
    assert all(t.stackgroup == f"share_{tier_code}" for t in fig.data)


# ---------------------------------------------------------------------------
# build_n_constituents_subplot — Batch C (Group 2)
# ---------------------------------------------------------------------------


def test_build_n_constituents_subplot_emits_four_lines() -> None:
    """Three per-attestation lines (A/B/C) plus one total-active line."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_n_constituents_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    assert len(fig.data) == 4
    names = {t.name for t in fig.data}
    assert names == {
        "TPRR_F n Tier A",
        "TPRR_F n Tier B",
        "TPRR_F n Tier C",
        "TPRR_F n active total",
    }


def test_build_n_constituents_subplot_active_total_line_is_thicker() -> None:
    """The total-active line is the headline series and reads thicker so
    a viewer's eye lands on it first."""
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_n_constituents_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    by_name = {t.name: t for t in fig.data}
    total_width = by_name["TPRR_F n active total"].line.width
    a_width = by_name["TPRR_F n Tier A"].line.width
    assert total_width > a_width


def test_build_n_constituents_subplot_uses_attestation_palette() -> None:
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_n_constituents_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    by_name = {t.name: t for t in fig.data}
    assert by_name["TPRR_F n Tier A"].line.color == ATTESTATION_TIER_COLOURS["A"]
    assert by_name["TPRR_F n Tier B"].line.color == ATTESTATION_TIER_COLOURS["B"]
    assert by_name["TPRR_F n Tier C"].line.color == ATTESTATION_TIER_COLOURS["C"]


def test_build_n_constituents_subplot_handles_empty_df_silently() -> None:
    fig = _empty_subplot_fig()
    build_n_constituents_subplot(
        fig, row=1, col=1, indices_df=pd.DataFrame(), tier_code="TPRR_F"
    )
    assert len(fig.data) == 0


def test_build_n_constituents_subplot_y_axis_says_constituent_count() -> None:
    fig = _empty_subplot_fig()
    df = _shares_df_three_days()
    build_n_constituents_subplot(
        fig, row=1, col=1, indices_df=df, tier_code="TPRR_F"
    )
    assert "constituent count" in fig.layout.yaxis.title.text.lower()


@pytest.mark.parametrize("tier_code", ["TPRR_F", "TPRR_S", "TPRR_E"])
def test_build_n_constituents_subplot_each_tier(tier_code: str) -> None:
    fig = _empty_subplot_fig()
    df = _shares_df_three_days(index_code=tier_code)
    build_n_constituents_subplot(
        fig, row=1, col=1, indices_df=df, tier_code=tier_code
    )
    names = {t.name for t in fig.data}
    assert f"{tier_code} n Tier A" in names
    assert f"{tier_code} n active total" in names


def test_attestation_tier_colours_distinct_from_tier_colours() -> None:
    """The attestation palette must not overlap with the tier-index palette
    so a reader doesn't conflate 'TPRR_F level' with 'Tier A weight share'."""
    attestation_set = set(ATTESTATION_TIER_COLOURS.values())
    tier_set = set(TIER_COLOURS.values())
    assert attestation_set.isdisjoint(tier_set)


# ---------------------------------------------------------------------------
# build_scenario_overlay_subplot — Phase 9 Batch D (DL 2026-04-30)
# ---------------------------------------------------------------------------


def _three_day_indices_dict(
    *,
    tier_codes: tuple[str, ...] = ("TPRR_F", "TPRR_S", "TPRR_E"),
) -> dict[str, pd.DataFrame]:
    """Build a dict[tier_code → IndexValueDF] for the scenario overlay tests."""
    return {code: _three_day_indices_df(index_code=code) for code in tier_codes}


def test_build_scenario_overlay_subplot_emits_six_lines_three_tiers_two_series_each() -> None:
    """Six traces total: F/S/E x {clean, scenario}."""
    fig = _empty_subplot_fig()
    clean = _three_day_indices_dict()
    scenario = _three_day_indices_dict()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices=clean,
        scenario_indices=scenario,
        scenario_name="fat_finger_high",
    )
    assert len(fig.data) == 6
    names = {t.name for t in fig.data}
    assert names == {
        "TPRR_F clean", "TPRR_F fat_finger_high",
        "TPRR_S clean", "TPRR_S fat_finger_high",
        "TPRR_E clean", "TPRR_E fat_finger_high",
    }


def test_build_scenario_overlay_subplot_solid_clean_dashed_scenario() -> None:
    """Convention: clean baseline solid, scenario dashed. Same colour per
    tier so the eye groups by tier."""
    fig = _empty_subplot_fig()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices=_three_day_indices_dict(),
        scenario_indices=_three_day_indices_dict(),
        scenario_name="ff",
    )
    by_name = {t.name: t for t in fig.data}
    f_clean = by_name["TPRR_F clean"]
    f_scen = by_name["TPRR_F ff"]
    assert f_clean.line.dash in (None, "solid")
    assert f_scen.line.dash == "dash"
    # Same colour for clean + scenario of one tier.
    assert f_clean.line.color == f_scen.line.color
    # Tier colour matches palette.
    assert f_clean.line.color == TIER_COLOURS["TPRR_F"]


def test_build_scenario_overlay_subplot_handles_empty_inputs() -> None:
    fig = _empty_subplot_fig()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices={},
        scenario_indices={},
        scenario_name="x",
    )
    assert len(fig.data) == 0


def test_build_scenario_overlay_subplot_one_side_only_renders_that_side() -> None:
    """If only the clean baseline is provided (e.g. scenario failed to run),
    render the baseline only — no scenario lines."""
    fig = _empty_subplot_fig()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices=_three_day_indices_dict(),
        scenario_indices={},
        scenario_name="x",
    )
    assert len(fig.data) == 3  # 3 clean lines (F/S/E)
    for trace in fig.data:
        assert "clean" in trace.name


def test_build_scenario_overlay_subplot_legend_groups_by_tier() -> None:
    """Each (clean, scenario) pair shares a legendgroup so clicking a tier
    in the legend toggles both lines together. Useful for an analyst
    isolating one tier's scenario effect."""
    fig = _empty_subplot_fig()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices=_three_day_indices_dict(),
        scenario_indices=_three_day_indices_dict(),
        scenario_name="x",
    )
    by_name = {t.name: t for t in fig.data}
    assert by_name["TPRR_F clean"].legendgroup == "TPRR_F"
    assert by_name["TPRR_F x"].legendgroup == "TPRR_F"
    assert by_name["TPRR_S clean"].legendgroup == "TPRR_S"
    assert by_name["TPRR_E clean"].legendgroup == "TPRR_E"


def test_build_scenario_overlay_subplot_y_axis_says_index_level() -> None:
    fig = _empty_subplot_fig()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices=_three_day_indices_dict(),
        scenario_indices=_three_day_indices_dict(),
        scenario_name="x",
    )
    assert "rebased to 100" in fig.layout.yaxis.title.text


def test_build_scenario_overlay_subplot_subset_of_tiers() -> None:
    """Caller can request a subset of tier codes (e.g. F only). Useful
    for compact scenario overlays where only one tier is the test target."""
    fig = _empty_subplot_fig()
    build_scenario_overlay_subplot(
        fig,
        row=1, col=1,
        clean_indices=_three_day_indices_dict(),
        scenario_indices=_three_day_indices_dict(),
        scenario_name="x",
        tier_codes=("TPRR_F",),
    )
    assert len(fig.data) == 2  # F clean + F scenario only
