"""Tests for tprr.viz.dashboard — Phase 9 dashboard composer.

Convention: figure JSON shape assertions, not pixel diffs. The composer's
contract is the panel-list pattern + grid auto-sizing + run_id metadata.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import plotly.graph_objects as go
import pytest

from tprr.viz.dashboard import PanelSpec, plot_tprr_dashboard


def _noop_builder(_fig: go.Figure, _row: int, _col: int) -> None:
    """Builder that does nothing — used for layout-only tests."""
    return None


def _trace_adding_builder(name: str) -> Callable[[go.Figure, int, int], None]:
    """Returns a builder that adds one named scatter trace."""

    def _builder(fig: go.Figure, row: int, col: int) -> None:
        fig.add_trace(
            go.Scatter(x=[1, 2, 3], y=[1, 2, 3], name=name),
            row=row,
            col=col,
        )

    return _builder


# ---------------------------------------------------------------------------
# plot_tprr_dashboard
# ---------------------------------------------------------------------------


def test_plot_tprr_dashboard_writes_html_file(tmp_path: Path) -> None:
    output = tmp_path / "test_dashboard.html"
    panels = [
        PanelSpec(
            title="Test panel",
            row=1,
            col=1,
            builder=_trace_adding_builder("test_trace"),
        )
    ]
    plot_tprr_dashboard(panels=panels, run_id="test_run", output_path=output)
    assert output.exists()
    assert output.stat().st_size > 0


def test_plot_tprr_dashboard_creates_output_directory_if_missing(
    tmp_path: Path,
) -> None:
    output = tmp_path / "nested" / "deeper" / "dashboard.html"
    panels = [
        PanelSpec(
            title="X",
            row=1,
            col=1,
            builder=_trace_adding_builder("a"),
        )
    ]
    plot_tprr_dashboard(panels=panels, run_id="run", output_path=output)
    assert output.exists()


def test_plot_tprr_dashboard_grid_size_from_panel_max_coordinates(
    tmp_path: Path,
) -> None:
    """Grid auto-extends to the max (row, col) over the panel list — adding
    a panel at (3, 2) creates a 3x2 grid even if other cells are empty."""
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a")),
        PanelSpec(title="B", row=3, col=2, builder=_trace_adding_builder("b")),
    ]
    fig = plot_tprr_dashboard(
        panels=panels, run_id="run", output_path=tmp_path / "x.html"
    )
    # Plotly assigns subplot anchors xaxis, xaxis2, ... in row-major order.
    # 3x2 grid → 6 axes total.
    layout_dict = fig.to_dict()["layout"]
    xaxis_keys = [k for k in layout_dict if k.startswith("xaxis")]
    assert len(xaxis_keys) == 6  # 3 rows x 2 cols


def test_plot_tprr_dashboard_run_id_in_title(tmp_path: Path) -> None:
    """run_id is embedded in the title block so dashboards are visually
    self-identifying."""
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a"))
    ]
    fig = plot_tprr_dashboard(
        panels=panels,
        run_id="v0_1_lambda3.0_twap_then_weight_seed42_base2026-01-01",
        output_path=tmp_path / "x.html",
    )
    title_text = fig.layout.title.text
    assert "v0_1_lambda3.0_twap_then_weight_seed42_base2026-01-01" in title_text


def test_plot_tprr_dashboard_subtitle_threaded_through(tmp_path: Path) -> None:
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a"))
    ]
    fig = plot_tprr_dashboard(
        panels=panels,
        run_id="run_x",
        output_path=tmp_path / "x.html",
        subtitle="Methodology v1.2 · λ=3.0",
    )
    title_text = fig.layout.title.text
    assert "Methodology v1.2" in title_text
    assert "λ=3.0" in title_text


def test_plot_tprr_dashboard_empty_panels_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        plot_tprr_dashboard(
            panels=[], run_id="run", output_path=tmp_path / "x.html"
        )


def test_plot_tprr_dashboard_panel_out_of_grid_bounds_raises(
    tmp_path: Path,
) -> None:
    """A PanelSpec with negative row or col raises a clear error rather
    than producing a corrupt figure."""
    panels = [
        PanelSpec(title="X", row=0, col=1, builder=_noop_builder),
    ]
    with pytest.raises(ValueError, match="out of grid bounds"):
        plot_tprr_dashboard(
            panels=panels, run_id="run", output_path=tmp_path / "x.html"
        )


def test_plot_tprr_dashboard_subplot_titles_match_panel_titles(
    tmp_path: Path,
) -> None:
    panels = [
        PanelSpec(title="Top-left", row=1, col=1, builder=_noop_builder),
        PanelSpec(title="Bottom-right", row=2, col=2, builder=_noop_builder),
    ]
    fig = plot_tprr_dashboard(
        panels=panels, run_id="run", output_path=tmp_path / "x.html"
    )
    annotation_texts = {a.text for a in fig.layout.annotations}
    assert "Top-left" in annotation_texts
    assert "Bottom-right" in annotation_texts


def test_plot_tprr_dashboard_returns_figure(tmp_path: Path) -> None:
    """Returning the Figure lets callers do further inspection / testing
    without re-loading from disk."""
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a"))
    ]
    fig = plot_tprr_dashboard(
        panels=panels, run_id="run", output_path=tmp_path / "x.html"
    )
    assert isinstance(fig, go.Figure)


def test_plot_tprr_dashboard_includes_plotlyjs_via_cdn(tmp_path: Path) -> None:
    """HTML output references the Plotly JS bundle via CDN, not inlined.
    Keeps file size ~50KB (cdn) instead of ~3MB (inline) per dashboard;
    Phase 10 sweeps will produce dozens of files."""
    output = tmp_path / "dashboard.html"
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a"))
    ]
    plot_tprr_dashboard(
        panels=panels, run_id="run", output_path=output
    )
    html_text = output.read_text()
    assert "cdn.plot.ly" in html_text or "plotly-latest" in html_text or "plot-latest" in html_text or "cdn.plotly" in html_text


def test_plot_tprr_dashboard_default_layout_is_white_background(
    tmp_path: Path,
) -> None:
    """Institutional look: white plot + paper background, not Plotly's
    default light-grey."""
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a"))
    ]
    fig = plot_tprr_dashboard(
        panels=panels, run_id="run", output_path=tmp_path / "x.html"
    )
    assert fig.layout.plot_bgcolor == "white"
    assert fig.layout.paper_bgcolor == "white"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_plot_tprr_dashboard_deterministic_under_same_inputs(
    tmp_path: Path,
) -> None:
    """Same panels + same run_id → byte-identical figure JSON across two
    invocations. CLAUDE.md non-negotiable: deterministic computation."""
    panels = [
        PanelSpec(title="A", row=1, col=1, builder=_trace_adding_builder("a"))
    ]
    fig_a = plot_tprr_dashboard(
        panels=panels, run_id="r", output_path=tmp_path / "a.html"
    )
    fig_b = plot_tprr_dashboard(
        panels=panels, run_id="r", output_path=tmp_path / "b.html"
    )
    # Compare the JSON dict (skip uid which Plotly may set on traces).
    dict_a = fig_a.to_dict()
    dict_b = fig_b.to_dict()
    for trace in dict_a["data"] + dict_b["data"]:
        trace.pop("uid", None)
    assert dict_a == dict_b
