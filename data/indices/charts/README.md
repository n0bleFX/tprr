# TPRR dashboard — what you're looking at

The HTML files in this folder are produced by `scripts/plot_indices.py`. Each
file is one run of the v0.1 pipeline at a fixed parameter set, encoded in the
filename (`v0_1_lambda{λ}_{ordering}_seed{seed}_base{base_date}_dashboard.html`).
Open the file in a browser; Plotly serves the JS via CDN, so a network is needed
on first open.

## Layout — 18 panels, 6 rows × 3 columns

**Row 1 — core tier index levels (Group 1).**
TPRR-F (Frontier) · TPRR-S (Standard) · TPRR-E (Efficiency).
Index level rebased to 100 at the base date (`config.base_date`,
default 2026-01-01). Backtest runs from `config.backtest_start` (2025-01-01)
forward; the level on the base date is exactly 100 and earlier dates are
back-rebased from there.

**Row 2 — derived series (Group 1).**
TPRR-FPR (= F / S, Frontier Premium Ratio) · TPRR-SER (= S / E, Standard
Efficiency Ratio) · TPRR-F vs TPRR-B-F overlay (output-only core in solid,
blended `0.25·P_in + 0.75·P_out` series in dashed; gap is the input-side
contribution at Frontier).

**Row 3 — tier weight share (Group 2).**
For each of F / S / E, the daily share of total weight contributed by each
attestation tier (A / B / C), stacked to 1.0. Reading the Phase 7H story
visually: Tier A share rises smoothly toward ~90%+ over the backtest as the
within-tier-share + continuous blending refinements (Batches A and B) plus
suspension reinstatement (Batch D) restore Tier A constituents that the
literal-canon priority fall-through had previously cliff-edged out.

**Row 4 — active constituent count (Group 2).**
Per-tier line plot of active-constituent counts (`n_constituents_active`)
plus a total line. Drops below 3 trigger tier suspension under the canonical
methodology (Section 4.2.4). Watch for plateau periods at exactly 3 — they
mean the tier is one constituent away from suspension.

**Rows 5-6 — scenario overlays (Group 3).**
Six representative scenarios from `config/scenarios.yaml`, each rendered as
F / S / E levels under that scenario (solid) overlaid on the clean baseline
(dashed). Manipulation resistance reads as small divergence between the two
on each panel:
- `fat_finger_high` — single contributor posts an erroneous high price
- `intraday_spike` — short-duration intraday change event
- `correlated_blackout` — multiple contributors stop posting simultaneously
- `stale_quote` — contributor's posted price holds for an unrealistic period
- `shock_price_cut` — large coordinated downside move
- `sustained_manipulation` — slow drift attempting to game the median

Each scenario was composed via `tprr.mockdata.scenarios.compose_scenario`
on top of the clean Tier A panel + change events; Tier B is re-derived from
the composed Tier A panel; Tier C reuses the cached OpenRouter snapshot.

## Reading the title block

The figure title shows: project name, methodology version, λ, ordering,
base date, and the deterministic `run_id`. Two dashboards with the same
`run_id` were produced from byte-identical inputs (CLAUDE.md non-negotiable
#3). Phase 10 sweeps will produce many dashboards in this folder; the
`run_id` is what disambiguates them.

## Provenance

- Synthetic Tier A contributor panel + change events (seeded mock data).
- Tier B implied volumes from `config/tier_b_revenue.yaml` (Option B
  derivation per DL 2026-04-22 entry); haircut 0.5 (Phase 7H Batch C).
- Tier C from cached OpenRouter snapshot under `data/raw/openrouter/`.

The provenance flag matters: this is an MVP validation backtest on synthetic
data, not a publishable index. Anything sent to a counterparty must be
labelled accordingly (CLAUDE.md non-negotiables #4 and #6).
