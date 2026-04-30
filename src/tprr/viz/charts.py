"""Phase 9 — chart builder primitives.

Each ``build_*_subplot`` is a pure function that mutates a Plotly
``Figure`` in place by adding traces and updating axes for the (row, col)
subplot it's called against. Builders never own the surrounding
``make_subplots`` grid — that's the dashboard composer's job
(``tprr.viz.dashboard.plot_tprr_dashboard``). Keeping builders pure-and-
local makes each chart unit-testable and lets the composer freely
rearrange the grid without touching the chart code.

Phase 9 batches:
- Batch A: ``build_index_level_subplot`` (this batch)
- Batch B: ``build_ratio_subplot``, ``build_blended_overlay_subplot``
- Batch C: ``build_tier_share_subplot``, ``build_n_constituents_subplot``
- Batch D: ``build_scenario_overlay_subplot``

Static export (PNG/SVG via kaleido) is deferred to Phase 11. When that
lands, the conversion uses the same builders via ``figure.write_image()``
— do not fork the chart code into a separate PNG-export pipeline.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Institutional palette: dark-on-light, thin lines, subtle grid.
# Used uniformly across builders so dashboard panels read as one document.
TIER_COLOURS: dict[str, str] = {
    "TPRR_F": "#1f3a93",   # frontier — deep blue
    "TPRR_S": "#0e8a5f",   # standard — emerald
    "TPRR_E": "#a35200",   # efficiency — burnt orange
    "TPRR_FPR": "#5b2c83",  # ratio — purple
    "TPRR_SER": "#a8326a",  # ratio — magenta
    "TPRR_B_F": "#447ec3",  # blended frontier — lighter blue
    "TPRR_B_S": "#5fb594",  # blended standard — lighter green
    "TPRR_B_E": "#d18b50",  # blended efficiency — lighter orange
}

SUSPENDED_MARKER_COLOUR = "#cc0000"
GRID_COLOUR = "#dddddd"
AXIS_LINE_COLOUR = "#888888"


def build_index_level_subplot(
    fig: go.Figure,
    *,
    row: int,
    col: int,
    indices_df: pd.DataFrame,
    index_code: str,
) -> None:
    """Add an index-level time series for one core/blended tier index.

    Plots ``index_level`` over ``as_of_date``, with suspended days marked
    by red dots on the x-axis. The axis labels make units explicit:
    "Index level (rebased to 100)" rather than a bare number.

    ``indices_df`` is the per-index IndexValueDF-shape DataFrame from
    ``FullPipelineResults.indices[index_code]``. The function does not
    filter by ``index_code`` — it trusts the caller to pass the right
    slice — but uses ``index_code`` for trace labels and colour.
    """
    if indices_df.empty:
        return

    colour = TIER_COLOURS.get(index_code, "#444444")

    # Main line: index_level (NaN on suspended days propagates a gap, which
    # is the correct visual — a suspended day has no published level).
    fig.add_trace(
        go.Scatter(
            x=indices_df["as_of_date"],
            y=indices_df["index_level"],
            mode="lines",
            name=index_code,
            line={"color": colour, "width": 1.5},
            hovertemplate=(
                f"<b>{index_code}</b><br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Index level: %{y:.2f}<br>"
                "<extra></extra>"
            ),
        ),
        row=row,
        col=col,
    )

    # Suspended-day markers: small red dots on the x-axis at y=0 of each
    # subplot's y-range. This is informational — the gap in the line is
    # the primary signal, the markers are confirmation.
    suspended_df = indices_df[indices_df["suspended"]]
    if not suspended_df.empty:
        fig.add_trace(
            go.Scatter(
                x=suspended_df["as_of_date"],
                y=[0.0] * len(suspended_df),
                mode="markers",
                name=f"{index_code} suspended",
                marker={
                    "color": SUSPENDED_MARKER_COLOUR,
                    "size": 5,
                    "symbol": "x",
                },
                showlegend=False,
                hovertemplate=(
                    f"<b>{index_code} suspended</b><br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    "Reason: %{customdata}<br>"
                    "<extra></extra>"
                ),
                customdata=suspended_df["suspension_reason"].to_list(),
            ),
            row=row,
            col=col,
        )

    fig.update_xaxes(
        title_text="",
        showgrid=True,
        gridcolor=GRID_COLOUR,
        linecolor=AXIS_LINE_COLOUR,
        row=row,
        col=col,
    )
    fig.update_yaxes(
        title_text="Index level (rebased to 100)",
        showgrid=True,
        gridcolor=GRID_COLOUR,
        linecolor=AXIS_LINE_COLOUR,
        row=row,
        col=col,
    )
