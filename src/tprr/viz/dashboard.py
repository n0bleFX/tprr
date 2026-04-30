"""Phase 9 — dashboard composer.

``plot_tprr_dashboard`` takes a list of ``PanelSpec`` entries describing
which builders fill which (row, col) of the subplot grid, computes grid
size from the panel coordinates, runs each builder, and writes
deterministic HTML output to ``output_path``.

The panels-list pattern lets subsequent Phase 9 batches add panels by
appending to the list — no re-jiggering of grid size or layout literals.
The grid auto-extends from ``max(row), max(col)`` over the panel list.

``run_id`` is part of the title block AND embedded in the HTML output's
filename (caller's responsibility for the filename — the composer just
writes to ``output_path``). Phase 10 will produce dozens of dashboards
under parameter sweeps; trivial visual identification matters.

run_id format: ``v{version}_lambda{λ}_{ordering}_seed{seed}_base{base_date}``
— fields are deterministic from pipeline parameters and parseable for
Phase 10 sweep-tooling lookups.

Static export (PNG/SVG via kaleido) is deferred to Phase 11. When that
lands, the conversion uses the same composed Figure via
``figure.write_image()``; the chart code does not fork.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

PanelBuilder = Callable[[go.Figure, int, int], None]
"""Signature: ``(fig, row, col) -> None``. Builders mutate ``fig`` in place
to add traces and update axes for the (row, col) subplot."""


@dataclass(frozen=True)
class PanelSpec:
    """One subplot in the dashboard grid.

    ``row`` and ``col`` are 1-indexed (Plotly convention). ``builder`` is
    a callable that takes ``(fig, row, col)`` and mutates ``fig`` to add
    its traces. ``title`` is shown above the subplot.
    """

    title: str
    row: int
    col: int
    builder: PanelBuilder


def plot_tprr_dashboard(
    panels: list[PanelSpec],
    *,
    run_id: str,
    output_path: Path,
    title: str = "TPRR Index — v0.1 Backtest",
    subtitle: str = "",
    width_per_col: int = 480,
    height_per_row: int = 360,
) -> go.Figure:
    """Compose ``panels`` into a single Plotly dashboard, write to ``output_path``.

    Grid size is computed from ``max(row)`` x ``max(col)`` over the panel
    list. Any (row, col) without a panel becomes empty whitespace. The
    title block carries ``run_id`` so two runs over different parameter
    sets are visually distinguishable.

    Returns the composed ``Figure`` for downstream inspection / testing.
    Writes HTML to ``output_path`` using ``include_plotlyjs="cdn"`` (~50KB
    output rather than ~3MB inlined bundle).
    """
    if not panels:
        raise ValueError("plot_tprr_dashboard: panels list is empty")

    n_rows = max(p.row for p in panels)
    n_cols = max(p.col for p in panels)

    # Build the title grid in row-major order — make_subplots wants a flat
    # list with empty strings for cells that have no panel.
    titles_grid: list[list[str]] = [
        ["" for _ in range(n_cols)] for _ in range(n_rows)
    ]
    for p in panels:
        if not (1 <= p.row <= n_rows and 1 <= p.col <= n_cols):
            raise ValueError(
                f"PanelSpec out of grid bounds: row={p.row}, col={p.col}, "
                f"grid={n_rows}x{n_cols}"
            )
        titles_grid[p.row - 1][p.col - 1] = p.title
    flat_titles = [t for r in titles_grid for t in r]

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=flat_titles,
        horizontal_spacing=0.08,
        vertical_spacing=0.10,
    )

    for p in panels:
        p.builder(fig, p.row, p.col)

    full_title = title
    if subtitle:
        full_title = f"{title}<br><sup>{subtitle}</sup>"
    full_title += f"<br><sup>run_id={run_id}</sup>"

    fig.update_layout(
        title={"text": full_title, "x": 0.02, "xanchor": "left"},
        width=n_cols * width_per_col,
        height=n_rows * height_per_row + 80,  # +80 for the title block
        plot_bgcolor="white",
        paper_bgcolor="white",
        font={"family": "Helvetica, Arial, sans-serif", "size": 11},
        showlegend=True,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path), include_plotlyjs="cdn")
    return fig
