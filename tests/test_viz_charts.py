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
    GRID_COLOUR,
    SUSPENDED_MARKER_COLOUR,
    TIER_COLOURS,
    build_index_level_subplot,
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
