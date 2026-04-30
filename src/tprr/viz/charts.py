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

# Attestation-tier palette: sequential teal gradient. Distinct from the
# tier-index palette (TIER_COLOURS) so a reader doesn't conflate
# "TPRR_F level" with "Tier A weight share". Sequence A>B>C reads as
# decreasing confidence.
ATTESTATION_TIER_COLOURS: dict[str, str] = {
    "A": "#1a5f7a",  # dark teal — highest confidence
    "B": "#4d8a9e",  # medium teal
    "C": "#80b5c2",  # light teal — lowest confidence
}


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


def build_ratio_subplot(
    fig: go.Figure,
    *,
    row: int,
    col: int,
    indices_df: pd.DataFrame,
    index_code: str,
) -> None:
    """Add a ratio time series for FPR or SER.

    Structurally similar to ``build_index_level_subplot`` (line +
    suspended markers) but with a y-axis label that names the dimension
    explicitly: a ratio of two tier indices, not an index of constituent
    prices. The distinction matters when the audience is reading both
    level and ratio panels in the same dashboard — same colour family,
    different semantic.

    SER expansion (DL 2026-04-30 Phase 7 Batch B empirical observation)
    is the headline backtest finding the ratio panels exist to surface;
    a ~3x trajectory across the backtest reads cleanly on a rebased-100
    axis.

    ``indices_df`` is expected to be either ``FullPipelineResults.indices
    ["TPRR_FPR"]`` or ``["TPRR_SER"]``. tier_*_weight_share columns are
    NaN on ratio rows (DL 2026-04-30 Phase 7 Batch D — FPR/SER tier
    weight share semantics: NaN per ratio symmetry); this builder does
    not consume them.
    """
    if indices_df.empty:
        return

    colour = TIER_COLOURS.get(index_code, "#444444")

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
                "Ratio level: %{y:.2f}<br>"
                "<extra></extra>"
            ),
        ),
        row=row,
        col=col,
    )

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
        title_text="Ratio (rebased to 100)",
        showgrid=True,
        gridcolor=GRID_COLOUR,
        linecolor=AXIS_LINE_COLOUR,
        row=row,
        col=col,
    )


BLENDED_REFERENCE_RATIO = 0.80


def build_blended_overlay_subplot(
    fig: go.Figure,
    *,
    row: int,
    col: int,
    core_df: pd.DataFrame,
    blended_df: pd.DataFrame,
    core_code: str,
    blended_code: str,
) -> None:
    """Plot the per-day raw-value ratio ``B_X / X`` for one tier.

    Both core and blended series are independently rebased to 100 on the
    same anchor date, so plotting their index_levels overlaid would force
    convergence at the anchor by construction — the formula's ~20%
    blended-to-output gap would be invisible. Plotting the **raw-value
    ratio** isolates the formula effect from the rebase: under the
    methodology's output-heavy 0.75/0.25 weighting (Section 3.3.4), the
    ratio sits near 0.80 on a panel where input prices run ~5x cheaper
    than output, slowly varying as the input/output spread evolves.

    A horizontal reference line at y=0.80 with annotation surfaces the
    methodology baseline so analysts can read deviation directly.

    On suspended days for either series, the ratio is NaN (no published
    raw value). Inner-join on ``as_of_date`` keeps the ratio well-defined
    only where both series produced a daily fix.
    """
    if core_df.empty or blended_df.empty:
        return

    merged = core_df[["as_of_date", "raw_value_usd_mtok", "suspended"]].merge(
        blended_df[["as_of_date", "raw_value_usd_mtok", "suspended"]],
        on="as_of_date",
        suffixes=("_core", "_blended"),
        how="inner",
    ).sort_values("as_of_date").reset_index(drop=True)

    if merged.empty:
        return

    # Mask suspended days on either side: ratio is undefined.
    suspended_mask = merged["suspended_core"] | merged["suspended_blended"]
    core_raw = merged["raw_value_usd_mtok_core"].astype(float)
    blended_raw = merged["raw_value_usd_mtok_blended"].astype(float)
    ratio = blended_raw / core_raw
    ratio_masked = ratio.where(~suspended_mask & core_raw.gt(0))

    blended_colour = TIER_COLOURS.get(blended_code, "#444444")

    fig.add_trace(
        go.Scatter(
            x=merged["as_of_date"],
            y=ratio_masked,
            mode="lines",
            name=f"{blended_code} / {core_code}",
            line={"color": blended_colour, "width": 1.5},
            customdata=list(
                zip(
                    blended_raw.tolist(),
                    core_raw.tolist(),
                    strict=True,
                )
            ),
            hovertemplate=(
                f"<b>{blended_code} / {core_code}</b><br>"
                "Date: %{x|%Y-%m-%d}<br>"
                f"{blended_code} raw: %{{customdata[0]:.4f}}<br>"
                f"{core_code} raw: %{{customdata[1]:.4f}}<br>"
                "Ratio: %{y:.4f}<br>"
                "<extra></extra>"
            ),
        ),
        row=row,
        col=col,
    )

    # Horizontal reference line at y=0.80. Plotly's add_hline doesn't
    # accept (row, col) for a subplot in older versions of make_subplots,
    # so add it as a flat Scatter trace spanning the same x-range.
    fig.add_trace(
        go.Scatter(
            x=[merged["as_of_date"].iloc[0], merged["as_of_date"].iloc[-1]],
            y=[BLENDED_REFERENCE_RATIO, BLENDED_REFERENCE_RATIO],
            mode="lines",
            name=f"reference {BLENDED_REFERENCE_RATIO:.2f}",
            line={"color": "#888888", "width": 1.0, "dash": "dot"},
            showlegend=False,
            hovertemplate=(
                "Reference: %{y:.2f}<br>"
                "(Section 3.3.4 expected with input/output ~1:5)<br>"
                "<extra></extra>"
            ),
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
        title_text=f"{blended_code} / {core_code} (raw value ratio)",
        range=[0.0, 1.2],
        showgrid=True,
        gridcolor=GRID_COLOUR,
        linecolor=AXIS_LINE_COLOUR,
        row=row,
        col=col,
    )


def build_tier_share_subplot(
    fig: go.Figure,
    *,
    row: int,
    col: int,
    indices_df: pd.DataFrame,
    tier_code: str,
) -> None:
    """Stacked area chart of tier_a/b/c weight share over time for one tier.

    Visualises the cross-tier dominance cascade (DL 2026-04-30 Phase 7
    Batch C empirical entry): the seed-42 backtest transitions from
    100% Tier A weight share at first valid fix to 99-100% Tier B by
    base_date as pair-level suspensions push Tier A constituents below
    the min-3 threshold and force fall-through.

    Three stacked areas in attestation-tier order (A, B, C) — the
    A-on-bottom convention reads "highest confidence at the floor". Sum
    is 1.0 on every non-suspended day; suspended days have NaN shares
    (DL 2026-04-30 Phase 7 Batch D — FPR/SER carry NaN, but core tier
    indices populate the share columns even when suspended → check
    tier_a + tier_b + tier_c == 0 vs 1 to distinguish).
    """
    if indices_df.empty:
        return

    df = indices_df.sort_values("as_of_date").copy()

    # Mask suspended rows: NaN out the shares so the stacked area
    # produces a gap rather than a misleading 0-stack.
    suspended_mask = df["suspended"]
    for col_name in ("tier_a_weight_share", "tier_b_weight_share", "tier_c_weight_share"):
        df.loc[suspended_mask, col_name] = float("nan")

    for attestation, share_col in [
        ("A", "tier_a_weight_share"),
        ("B", "tier_b_weight_share"),
        ("C", "tier_c_weight_share"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df["as_of_date"],
                y=df[share_col],
                mode="lines",
                name=f"{tier_code} Tier {attestation}",
                line={"color": ATTESTATION_TIER_COLOURS[attestation], "width": 0},
                stackgroup=f"share_{tier_code}",
                fillcolor=ATTESTATION_TIER_COLOURS[attestation],
                hovertemplate=(
                    f"<b>{tier_code} Tier {attestation}</b><br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    "Weight share: %{y:.3f}<br>"
                    "<extra></extra>"
                ),
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
        title_text="Tier weight share",
        range=[0.0, 1.0],
        showgrid=True,
        gridcolor=GRID_COLOUR,
        linecolor=AXIS_LINE_COLOUR,
        row=row,
        col=col,
    )


def build_n_constituents_subplot(
    fig: go.Figure,
    *,
    row: int,
    col: int,
    indices_df: pd.DataFrame,
    tier_code: str,
) -> None:
    """Lines for n_constituents_a/b/c plus n_constituents_active for one tier.

    Companion to ``build_tier_share_subplot``: weight share captures the
    aggregation-level dominance signal; constituent counts capture the
    underlying coverage. A tier can have ≥3 active constituents but with
    most weight in Tier B (cascade); or have many Tier A constituents
    near the median with limited weight (median-distance dampening).

    The total ``n_constituents_active`` line is plotted last (on top) and
    in black so it reads as the "headline" series with the per-attestation
    counts below it.
    """
    if indices_df.empty:
        return

    df = indices_df.sort_values("as_of_date").copy()

    for attestation, count_col in [
        ("A", "n_constituents_a"),
        ("B", "n_constituents_b"),
        ("C", "n_constituents_c"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df["as_of_date"],
                y=df[count_col],
                mode="lines",
                name=f"{tier_code} n Tier {attestation}",
                line={"color": ATTESTATION_TIER_COLOURS[attestation], "width": 1.2},
                hovertemplate=(
                    f"<b>{tier_code} Tier {attestation}</b><br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    "Count: %{y}<br>"
                    "<extra></extra>"
                ),
            ),
            row=row,
            col=col,
        )

    # Total active count, plotted in black on top of the per-tier lines.
    fig.add_trace(
        go.Scatter(
            x=df["as_of_date"],
            y=df["n_constituents_active"],
            mode="lines",
            name=f"{tier_code} n active total",
            line={"color": "#222222", "width": 1.8},
            hovertemplate=(
                f"<b>{tier_code} active total</b><br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Count: %{y}<br>"
                "<extra></extra>"
            ),
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
        title_text="Active constituent count",
        showgrid=True,
        gridcolor=GRID_COLOUR,
        linecolor=AXIS_LINE_COLOUR,
        row=row,
        col=col,
    )
