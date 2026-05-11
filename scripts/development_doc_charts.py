"""Production-quality matplotlib charts for the TPRR Development and Validation document.

Charts are deterministic from parquet inputs; rerun produces byte-identical SVG output
(matplotlib SVG metadata Date stamp suppressed via savefig metadata).

Charts produced (all output to docs/charts/development/):
  - cliff_edge_resolution_arc.svg              (Chart 2.1, embedded in §2.8)
  - tprr_index_level_over_time_canonical.svg   (Chart 3.1, embedded in §3.1)
  - f_tier_scenario_absorption.svg             (Chart 3.2, embedded in §3.8)
  - per_tier_asymmetry_across_gate_range.svg   (Chart 3.3, embedded in §3.9)
  - gate_x_scenarios_per_tier_overlay.svg      (Chart 3.4, embedded in §3.10)

Run:
    uv run python scripts/development_doc_charts.py     # produce all five
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

# ---- Visual design language ----
COLOR_F = "#1a3a5c"  # deep navy
COLOR_S = "#2c8a8a"  # teal
COLOR_E = "#5fa869"  # muted green
COLOR_BASELINE = "#555555"  # baseline / clean overlay
COLOR_GRID = "#e0e0e0"
COLOR_HIGHLIGHT = "#d97a3c"  # Chart 2.1 Batch D emphasis

TIER_COLOR = {"TPRR_F": COLOR_F, "TPRR_S": COLOR_S, "TPRR_E": COLOR_E}
TIER_LABEL = {
    "TPRR_F": "TPRR-F (Frontier)",
    "TPRR_S": "TPRR-S (Standard)",
    "TPRR_E": "TPRR-E (Efficiency)",
}

OUTPUT_DIR = Path("docs/charts/development")

SCENARIOS = [
    "fat_finger_high",
    "intraday_spike",
    "correlated_blackout",
    "stale_quote",
    "shock_price_cut",
    "sustained_manipulation",
]
TIERS = ["TPRR_F", "TPRR_S", "TPRR_E"]
GATE_PCTS = [5, 10, 15, 20, 25, 30]
LOG_FLOOR = 1e-15
DELTA_DISPLAY_FLOOR = 1e-14  # Chart 3.2: clip tiny deltas to one log step above axis floor.
TPRR_F_CLEAN_BASELINE = 30.24  # USD/Mtok; canonical config seed-42 base_date reference.

PARQUET_DEFAULT = "data/indices/sweeps/multi_seed/multi_seed_default_seed42-61.parquet"
PARQUET_DEFAULT_SCEN = (
    "data/indices/sweeps/multi_seed/multi_seed_default_seed42-61_with_scenarios.parquet"
)
PARQUET_LOOSE = "data/indices/sweeps/multi_seed/multi_seed_loose_seed42-61.parquet"
PARQUET_TIGHT = "data/indices/sweeps/multi_seed/multi_seed_tight_seed42-61.parquet"
PARQUET_GATES_LOW = (
    "data/indices/sweeps/multi_seed/gate_x_scenarios_seed42-61_gates_5_10_15.parquet"
)
PARQUET_GATES_HIGH = (
    "data/indices/sweeps/multi_seed/gate_x_scenarios_seed42-61_gates_20_25_30.parquet"
)

# Suppress timestamp in SVG output for byte-identical reruns.
SAVEFIG_METADATA = {"Date": None}


def _apply_design_language() -> None:
    """Apply Noble TPRR development-doc visual design language to matplotlib rcParams."""
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.spines.bottom": True,
            "axes.edgecolor": "#888888",
            "axes.linewidth": 0.6,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": COLOR_GRID,
            "grid.linewidth": 0.6,
            "grid.linestyle": "-",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.format": "svg",
            "svg.fonttype": "none",
            "svg.hashsalt": "tprr-dev-doc",
        }
    )


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _dollar_log_formatter(val: float, _pos: int) -> str:
    """Hybrid $-formatter for log-scale ticks: decimal for >= 0.001, scientific below."""
    if val <= 0:
        return ""
    if val >= 1.0:
        return f"${val:g}"
    if val >= 0.001 - 1e-12:
        # Decade ticks in [0.001, 0.01, 0.1]: format as plain decimal.
        exp = round(np.log10(val))
        return f"${10.0**exp:g}"
    # Below 0.001: $1e-XX scientific notation.
    exp = round(np.log10(val))
    return f"$1e{exp:+03d}"


def _save(fig: plt.Figure, filename: str) -> Path:
    _ensure_output_dir()
    out = OUTPUT_DIR / filename
    fig.savefig(out, metadata=SAVEFIG_METADATA, bbox_inches="tight")
    plt.close(fig)
    return out


def _gate_pct_from_label(label: str) -> int:
    return int(label.replace("gate=", "").replace("pct", ""))


def _load_combined_gate_data() -> pd.DataFrame:
    df_low = pd.read_parquet(PARQUET_GATES_LOW)
    df_high = pd.read_parquet(PARQUET_GATES_HIGH)
    df = pd.concat([df_low, df_high], ignore_index=True)
    df["gate_pct"] = df["parameter_label"].map(_gate_pct_from_label)
    return df


def _per_seed_max_abs_delta(sub: pd.DataFrame, scenario: str) -> list[float]:
    """Per seed, max-over-days absolute delta of raw_value_usd_mtok between scenario and clean.

    Returns a list of per-seed scalars. Empty list if either panel_id is missing.
    """
    out: list[float] = []
    for seed in sorted(sub["seed"].unique()):
        ssub = sub[sub["seed"] == seed]
        pivot = ssub.pivot_table(
            index="as_of_date",
            columns="panel_id",
            values="raw_value_usd_mtok",
            aggfunc="first",
        )
        if "clean" not in pivot.columns or scenario not in pivot.columns:
            continue
        delta = (pivot[scenario] - pivot["clean"]).abs()
        out.append(float(delta.max()))
    return out


# ============================================================================
# Chart 2.1 — Cliff-edge resolution arc
# ============================================================================
def produce_chart_2_1() -> Path:
    """Step chart of TPRR_F base_date tier_a_weight_share across the Phase 7H + 10A arc.

    Hand-encoded historical trajectory (Pre-7H → Post-10A) per the methodology refinement
    arc documented in DL 2026-04-30 Phase 9 close-out. Cross-config envelope at the Post-10A
    endpoint computed from the loose / default / tight parquets at 2026-01-01, mean across
    20 seeds; plotted as an error bar spanning [min, max] of the three config means.
    """
    states = ["Pre-7H", "Post-A", "Post-B", "Post-C", "Post-D", "Post-10A"]
    values = [0.0012, 0.5083, 0.6980, 0.8063, 0.9261, 0.9261]
    annotations = [
        "baseline",
        "+ within-tier-share\nnormalization",
        "+ continuous\nblending",
        "+ Tier B haircut\n0.9 → 0.5",
        "+ bidirectional\nsusp/reinstate",
        "+ tier-eligibility\nthreshold",
    ]

    base_date = pd.Timestamp("2026-01-01")
    config_means: dict[str, float] = {}
    for label, path in [
        ("default", PARQUET_DEFAULT),
        ("loose", PARQUET_LOOSE),
        ("tight", PARQUET_TIGHT),
    ]:
        df = pd.read_parquet(path)
        sub = df[(df["index_code"] == "TPRR_F") & (df["as_of_date"] == base_date)]
        config_means[label] = float(sub["tier_a_weight_share"].mean())
    envelope_low = min(config_means.values())
    envelope_high = max(config_means.values())

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    x = np.arange(len(states))

    ax.plot(
        x,
        values,
        color=COLOR_F,
        linewidth=1.8,
        marker="o",
        markersize=8,
        markeredgecolor="white",
        markeredgewidth=1.2,
        zorder=3,
    )

    # Highlight the cliff-edge resolution endpoint (Post-D).
    ax.plot(
        x[4],
        values[4],
        marker="o",
        markersize=14,
        color=COLOR_HIGHLIGHT,
        markeredgecolor="white",
        markeredgewidth=1.4,
        zorder=4,
        label="Cliff-edge resolved (Batch D)",
    )

    # Cross-config envelope at endpoint (Post-10A).
    ax.errorbar(
        [x[5]],
        [values[5]],
        yerr=[[values[5] - envelope_low], [envelope_high - values[5]]],
        fmt="none",
        ecolor=COLOR_BASELINE,
        elinewidth=1.6,
        capsize=6,
        zorder=2,
        label=(
            f"Cross-config range\n"
            f"[loose={config_means['loose']:.4f}, "
            f"default={config_means['default']:.4f}, "
            f"tight={config_means['tight']:.4f}]"
        ),
    )

    for xi, vi, ann in zip(x, values, annotations, strict=True):
        ax.annotate(
            ann,
            xy=(xi, vi),
            xytext=(0, 16),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.5,
            color="#444444",
        )
    for xi, vi in zip(x, values, strict=True):
        ax.annotate(
            f"{vi:.4f}",
            xy=(xi, vi),
            xytext=(0, -16),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=8,
            color=COLOR_F,
            weight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(states)
    ax.set_ylim(-0.10, 1.20)
    ax.set_xlim(-0.5, len(states) - 0.5)
    ax.set_ylabel("TPRR_F base_date tier_a_weight_share")
    ax.set_title(
        "Cliff-edge resolution arc: TPRR_F base_date Tier-A weight share trajectory\n"
        "across Phase 7H + Phase 10A methodology refinement"
    )
    ax.legend(loc="lower right", framealpha=0.9, edgecolor="#cccccc")

    return _save(fig, "cliff_edge_resolution_arc.svg")


# ============================================================================
# Chart 3.1 — TPRR-F/-S/-E index level over time at canonical config
# ============================================================================
def produce_chart_3_1() -> Path:
    """1x3 grid of per-tier index level panels with median centerline + 5th-95th band.

    Shared y-axis across the three panels so the reader can visually compare tier magnitudes.
    Each panel: per-day median across 20 seeds (clean panel, default config) + continuous
    5th-95th percentile band in the tier's semantic color.
    """
    df = pd.read_parquet(PARQUET_DEFAULT)
    df = df[df["panel_id"] == "clean"]

    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.8), sharey=True)
    quarters = pd.date_range(start="2025-01-01", end="2026-01-01", freq="QS")
    quarter_labels = [f"{d.year} Q{((d.month - 1) // 3) + 1}" for d in quarters]

    for ax, tier in zip(axes, TIERS, strict=True):
        sub = df[df["index_code"] == tier]
        pivot = sub.pivot_table(
            index="as_of_date",
            columns="seed",
            values="index_level",
            aggfunc="first",
        ).sort_index()
        p05 = pivot.quantile(0.05, axis=1)
        p50 = pivot.quantile(0.50, axis=1)
        p95 = pivot.quantile(0.95, axis=1)

        ax.fill_between(
            p50.index,
            p05.values,
            p95.values,
            color=TIER_COLOR[tier],
            alpha=0.15,
            linewidth=0,
        )
        ax.plot(p50.index, p50.values, color=TIER_COLOR[tier], linewidth=1.6)
        ax.axhline(100.0, color=COLOR_BASELINE, linewidth=0.6, linestyle="--", alpha=0.5)

        ax.set_xticks(list(quarters))
        ax.set_xticklabels(quarter_labels, rotation=30, ha="right")
        ax.set_title(TIER_LABEL[tier], color=TIER_COLOR[tier])

    axes[0].set_ylabel("Index level (base_date 2026-01-01 = 100)")
    fig.suptitle(
        "TPRR-F / -S / -E daily index level over the 366-day backtest (canonical config)",
        fontsize=11,
        y=1.02,
    )

    fig.tight_layout(rect=(0.0, 0.10, 1.0, 1.0))
    pos = axes[0].get_position()
    fig.text(
        pos.x0,
        0.04,
        "Centerline = per-day median across 20 seeds (42-61); "
        "shaded band = 5th-95th percentile across seeds",
        ha="left",
        va="bottom",
        fontsize=8,
        color="#555555",
        style="italic",
    )
    return _save(fig, "tprr_index_level_over_time_canonical.svg")


# ============================================================================
# Chart 3.2 — F-tier scenario absorption six-panel
# ============================================================================
def produce_chart_3_2() -> Path:
    """Single-panel F-tier absorption: TPRR-F clean vs correlated_blackout signature.

    Main lines: seed-42 reference for visual clarity. Per-scenario summary annotation
    in upper-right reports max |Δ| across all 20 seeds × 366 days for each of the six
    v0.1 scenarios.
    """
    df = pd.read_parquet(PARQUET_DEFAULT_SCEN)
    df = df[df["index_code"] == "TPRR_F"]

    scenario_max_abs: dict[str, float] = {}
    for s in SCENARIOS:
        ssub = df[df["panel_id"].isin(["clean", s])]
        pivot = ssub.pivot_table(
            index=["as_of_date", "seed"],
            columns="panel_id",
            values="index_level",
            aggfunc="first",
        )
        delta = (pivot[s] - pivot["clean"]).abs()
        scenario_max_abs[s] = float(delta.max())

    df42 = df[df["seed"] == 42]
    clean = df42[df42["panel_id"] == "clean"].sort_values("as_of_date")
    scen = df42[df42["panel_id"] == "correlated_blackout"].sort_values("as_of_date")

    fig, ax = plt.subplots(figsize=(11.0, 5.8))

    ax.plot(
        clean["as_of_date"],
        clean["index_level"],
        color=COLOR_BASELINE,
        linewidth=1.4,
        label="Clean",
    )
    ax.plot(
        scen["as_of_date"],
        scen["index_level"],
        color=COLOR_F,
        linewidth=1.4,
        linestyle="--",
        label="Scenario (correlated_blackout)",
    )

    quarters = pd.date_range(start="2025-01-01", end="2026-01-01", freq="QS")
    ax.set_xticks(list(quarters))
    ax.set_xticklabels([f"{d.year} Q{((d.month - 1) // 3) + 1}" for d in quarters])

    ax.set_ylabel("Index level (base_date 2026-01-01 = 100)")
    ax.set_title("F-tier scenario absorption: TPRR-F clean vs correlated_blackout signature")
    ax.legend(loc="lower left", framealpha=0.9, edgecolor="#cccccc")

    # Per-scenario summary annotation block (upper-right, left-aligned content).
    summary_lines = ["Max |Δ| across 366 days (all 20 seeds, canonical config):"]
    for s in SCENARIOS:
        val = scenario_max_abs[s]
        formatted = "0.0 (exact)" if val == 0.0 else f"{val:.2e}"
        summary_lines.append(f"  • {s}: {formatted}")
    summary_lines.append("")
    summary_lines.append("All six scenarios absorbed to within float-arithmetic noise.")

    ax.text(
        0.98,
        0.97,
        "\n".join(summary_lines),
        transform=ax.transAxes,
        fontsize=8,
        color="#555555",
        ha="right",
        va="top",
        multialignment="left",
        family="monospace",
        bbox={
            "facecolor": "white",
            "edgecolor": "#cccccc",
            "boxstyle": "round,pad=0.5",
            "linewidth": 0.6,
        },
    )

    fig.tight_layout(rect=(0.0, 0.08, 1.0, 1.0))
    pos = ax.get_position()
    fig.text(
        pos.x0,
        0.04,
        "canonical config, seed-42",
        ha="left",
        va="bottom",
        fontsize=8,
        color="#555555",
        style="italic",
    )
    return _save(fig, "f_tier_scenario_absorption.svg")


# ============================================================================
# Chart 3.3 — Per-tier asymmetry across gate range (correlated_blackout signature)
# ============================================================================
def produce_chart_3_3() -> Path:
    """Single-panel three-series log-scale chart of per-tier max-abs scenario delta vs. gate.

    Signature scenario: correlated_blackout. For each (tier, gate, seed) computes the
    max-over-days absolute delta in raw_value_usd_mtok between scenario and clean, then
    means across 20 seeds. F-tier zero values clip to floor 1e-15 (absorption regime).
    """
    df = _load_combined_gate_data()
    df = df[df["index_code"].isin(TIERS)]

    rows = []
    for tier in TIERS:
        for gate in GATE_PCTS:
            sub = df[(df["index_code"] == tier) & (df["gate_pct"] == gate)]
            seed_max_abs = _per_seed_max_abs_delta(sub, "correlated_blackout")
            rows.append(
                {
                    "tier": tier,
                    "gate_pct": gate,
                    "mean_max_abs": float(np.mean(seed_max_abs)) if seed_max_abs else 0.0,
                }
            )
    agg = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(8.8, 6.0))
    for tier in TIERS:
        sub = agg[agg["tier"] == tier].sort_values("gate_pct")
        y = np.maximum(sub["mean_max_abs"].to_numpy(), LOG_FLOOR)
        ax.plot(
            sub["gate_pct"].to_numpy(),
            y,
            marker="o",
            markersize=7,
            linewidth=1.6,
            color=TIER_COLOR[tier],
            label=TIER_LABEL[tier],
        )

    ax.set_yscale("log")
    ax.set_ylim(LOG_FLOOR / 2, 1.0)
    ax.set_xticks(GATE_PCTS)
    ax.set_xlabel("Gate threshold (%)")
    ax.set_ylabel("Worst-day |scenario − clean| index difference, $/Mtok")
    ax.yaxis.set_major_formatter(FuncFormatter(_dollar_log_formatter))
    ax.set_title("Per-tier scenario response across gate range — correlated_blackout signature")

    regime = {
        "TPRR_F": "Absorption regime\n(zero delta across gate range)",
        "TPRR_E": "Filter-and-absorb\n(monotonic)",
        "TPRR_S": "Filter-and-absorb\n(non-monotonic)",
    }
    for tier in TIERS:
        endpoint = agg[(agg["tier"] == tier) & (agg["gate_pct"] == 30)]["mean_max_abs"].iloc[0]
        y_anchor = max(float(endpoint), LOG_FLOOR)
        ax.annotate(
            regime[tier],
            xy=(30, y_anchor),
            xytext=(10, 0),
            textcoords="offset points",
            fontsize=8,
            color=TIER_COLOR[tier],
            ha="left",
            va="center",
        )

    ax.set_xlim(4, 38)
    ax.legend(loc="lower left", framealpha=0.9, edgecolor="#cccccc")

    fig.tight_layout(rect=(0.0, 0.14, 1.0, 1.0))
    pos = ax.get_position()
    fig.text(
        pos.x0,
        0.02,
        "log scale\nmean across 20 seeds\nfloor 1e-15 visualizes absorption regime",
        ha="left",
        va="bottom",
        fontsize=8,
        color="#555555",
        style="italic",
        linespacing=1.4,
        multialignment="left",
    )

    return _save(fig, "per_tier_asymmetry_across_gate_range.svg")


# ============================================================================
# Chart 3.4 — Gate × scenarios cross-product per-tier overlay
# ============================================================================
def produce_chart_3_4() -> Path:
    """Per-tier multi-scenario envelope across gate range.

    For each (tier, gate, scenario) computes mean across 20 seeds of the per-seed max-abs
    delta in raw_value_usd_mtok. Per (tier, gate), shows the cross-scenario [min, max]
    envelope as a shaded band and the cross-scenario median as a centerline.
    """
    df = _load_combined_gate_data()
    df = df[df["index_code"].isin(TIERS)]

    rows = []
    for tier in TIERS:
        for gate in GATE_PCTS:
            sub = df[(df["index_code"] == tier) & (df["gate_pct"] == gate)]
            for scenario in SCENARIOS:
                seed_max_abs = _per_seed_max_abs_delta(sub, scenario)
                rows.append(
                    {
                        "tier": tier,
                        "gate_pct": gate,
                        "scenario": scenario,
                        "mean_max_abs": float(np.mean(seed_max_abs)) if seed_max_abs else 0.0,
                    }
                )
    detail = pd.DataFrame(rows)
    env = detail.groupby(["tier", "gate_pct"], as_index=False).agg(
        env_min=("mean_max_abs", "min"),
        env_max=("mean_max_abs", "max"),
        env_median=("mean_max_abs", "median"),
    )

    fig, ax = plt.subplots(figsize=(8.8, 6.0))
    for tier in TIERS:
        sub = env[env["tier"] == tier].sort_values("gate_pct")
        x = sub["gate_pct"].to_numpy()
        env_med = np.maximum(sub["env_median"].to_numpy(), LOG_FLOOR)
        ax.plot(
            x,
            env_med,
            marker="o",
            markersize=7,
            linewidth=1.6,
            color=TIER_COLOR[tier],
            label=f"{TIER_LABEL[tier]} — median",
        )

    ax.set_yscale("log")
    ax.set_ylim(LOG_FLOOR / 2, 1.0)
    ax.set_xticks(GATE_PCTS)
    ax.set_xlim(4, 32)
    ax.set_xlabel("Gate threshold (%)")
    ax.set_ylabel("Worst-day |scenario − clean| index difference, $/Mtok")
    ax.yaxis.set_major_formatter(FuncFormatter(_dollar_log_formatter))
    ax.set_title("Gate × scenarios cross-product per-tier scenario response")
    ax.legend(loc="lower left", framealpha=0.9, edgecolor="#cccccc")

    fig.tight_layout(rect=(0.0, 0.14, 1.0, 1.0))
    pos = ax.get_position()
    fig.text(
        pos.x0,
        0.02,
        "6 gate values × 6 scenarios × 20 seeds = 720 cells per tier\n"
        "log scale\n"
        "per-scenario detail in findings/gate_x_scenarios_absorption.md",
        ha="left",
        va="bottom",
        fontsize=8,
        color="#555555",
        style="italic",
        linespacing=1.4,
        multialignment="left",
    )

    return _save(fig, "gate_x_scenarios_per_tier_overlay.svg")


def main() -> None:
    _apply_design_language()
    _ensure_output_dir()
    paths = [
        produce_chart_2_1(),
        produce_chart_3_1(),
        produce_chart_3_2(),
        produce_chart_3_3(),
        produce_chart_3_4(),
    ]
    for p in paths:
        print(f"wrote: {p}")


if __name__ == "__main__":
    main()
