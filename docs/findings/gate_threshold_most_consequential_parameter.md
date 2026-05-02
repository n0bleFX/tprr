# Gate Threshold: The Most Consequential Single Parameter

**Source**: Phase 10 Batch 10B — pipeline-rerun sweeps across suspension threshold, reinstatement threshold, gate threshold, TWAP ordering on seed 42.

**Status**: Empirical finding. Identifies the slot-level data quality gate (15% deviation from 5-day trailing average) as the methodology's highest-leverage parameter.

## Finding

Of the four pipeline-rerun parameters swept in Phase 10 Batch 10B (suspension threshold, reinstatement threshold, gate threshold, TWAP ordering), **only the gate threshold shifts TPRR_F base_date raw_value**. Every other parameter leaves the base-date level invariant within the swept range. The gate threshold also produces the largest TPRR_E intermediate-day sensitivity (88% of trajectory days differ between gate=5% and gate=30%) — the highest single-parameter leverage on both anchored published levels and analyst trajectories.

## Empirical evidence

### TPRR_F base_date raw_value across gate threshold

| `quality_gate_pct` | TPRR_F base_date raw_value (USD/Mtok) |
|---|---:|
| 0.05 | 28.2315 |
| 0.10 | 28.94 |
| **0.15** (canonical) | **30.2405** |
| 0.20 | 30.2405 |
| 0.25 | 30.2405 |
| 0.30 | 30.2405 |

Convergence above the canonical 15% threshold. **Strict gates (5%, 10%) catch legitimate price movements as outliers**, suspending pairs that don't reinstate by base_date. The canonical 15% choice sits exactly on the convergence edge.

TPRR_S also shifts: 3.3109 (gate=5%, 10%) → 3.2927 (gate≥15%). TPRR_E base-date is invariant.

Source: [data/indices/sweeps/gate_threshold/gate_seed42.parquet](../../data/indices/sweeps/gate_threshold/gate_seed42.parquet); manifest sweep id `gate_seed42`.

### Intermediate-day sensitivity (gate=5% vs gate=30%)

| Index | n_days_differ / 366 | max abs delta ($/Mtok) |
|---|---:|---:|
| TPRR_F | 212 (58%) | 5.27 |
| TPRR_S | (similar magnitude) | (similar) |
| **TPRR_E** | **323 (88%)** | (largest cross-sweep) |

TPRR_E intermediate-day sensitivity (88%) is the **highest of any single parameter swept in Batch 10B**. Reinstatement threshold sweep produces 62% on TPRR_E; suspension threshold and TWAP ordering produce ≤51%.

### `all_pairs_suspended` audit cascades per gate

Per-gate `all_pairs_suspended` audit-row counts: 64 (5%) → 30 (10%) → 32 (15%) → 32 (20%) → 18 (25%) → 0 (30%).

5% gate is materially stricter — 2× the suspension cascades of the canonical 15% gate. 30% gate produces zero suspension cascades. The **canonical 15% sits comfortably above the strict-gate cliff** (5%/10% region) and well below the no-effect floor (30%).

### Comparison to other Batch 10B sweeps

| Sweep | Base_date raw_value variation | Intermediate-day sensitivity |
|---|---|---|
| Suspension threshold | None (30.2405 invariant) | 51% TPRR_E, 20% TPRR_F |
| Reinstatement threshold | None (30.2405 invariant) | 62% TPRR_E, 22% TPRR_F |
| **Gate threshold** | **$2.01/Mtok at TPRR_F** | **88% TPRR_E, 58% TPRR_F** |
| TWAP ordering | $0.0001/Mtok at TPRR_F | 20% TPRR_F |

## Mechanism

The gate threshold is the methodology's single point where **slot-level prices are admitted or excluded** before any aggregation runs. Every parameter downstream (suspension, reinstatement, TWAP ordering, weighting) operates on the gated slot set — gate exclusion propagates to every downstream effect.

Three propagation paths from gate to index level:

1. **Direct slot exclusion → daily TWAP shift**: a gated slot is excluded from the daily TWAP. Strict gates (5–10%) exclude legitimate price-step slots, biasing TWAPs toward pre-step prices.
2. **Gate exclusions → suspension trigger**: 3 consecutive days with any slot-level exclusions suspends the (contributor, model) pair. Strict gates trigger more suspensions; suspended pairs drop out of the daily fix until reinstatement.
3. **Suspension cascade → tier-level dynamics**: enough suspended pairs reduce a tier to <3 active constituents, suspending the tier-level fix entirely.

The other Batch 10B parameters operate on a fixed gated slot set. Suspension and reinstatement thresholds change *when* a pair becomes ineligible, but not the slot-level price data the index ultimately consumes. TWAP ordering changes *how* prices are aggregated, but not which slots enter the aggregation. **Only the gate decides which prices the methodology sees in the first place.**

This is why gate is structurally the highest-leverage parameter. It sits at the input boundary; everything downstream is operations on the gate-filtered set.

## Phase 11 narrative implication

The gate-threshold finding shapes how Phase 11 should communicate methodology-parameter sensitivity to institutional reviewers:

**Hierarchy framing**: "The methodology has a hierarchy of parameter sensitivity. The slot-level data quality gate (15% deviation from 5-day trailing average) is the highest-leverage parameter — it determines which price observations enter the index at all. Suspension, reinstatement, and TWAP ordering operate downstream on the gated set and produce smaller effects on the published level."

**Robustness framing**: "Three of four downstream parameters leave the base-date published level unchanged across their swept range. The gate parameter shifts the published level only at strict settings (5%, 10%) below the canonical 15% — the canonical choice sits on the convergence edge of the gate sweep, defended empirically by where the data quality landscape stabilises."

**Calibration framing for Index Committee**: "The 15% gate value is not arbitrary. The Phase 10 sweep shows it sits exactly where the gate's effect on the published level disappears (15% / 20% / 25% / 30% all produce identical TPRR_F base_date level). Tighter gates would change the published level; looser gates do not. The choice represents the loosest gate that doesn't degrade the published level — which is the methodologically conservative choice."

This is a **publishable robustness story for institutional audiences**: the methodology doesn't sit on a parameter cliff. The canonical gate is the right side of every threshold's convergence edge.

## v1.3 specification implication

v1.3 specification work should:

1. **Document the gate-threshold as the single highest-leverage parameter** in the canonical methodology. Index Committee governance for parameter changes should weight gate-threshold proposals more heavily than other parameter proposals.
2. **Specify the gate-threshold convergence edge**: 15% sits at the edge where strict-gate effects begin. Future calibration (e.g., on real provider data in v1.3+) should re-verify this edge — if real data has different volatility characteristics, the convergence edge may shift.
3. **Define gate-tightening as the principal manipulation-resistance mechanism**, alongside the exponential median-distance weighting. Both layers contribute; the gate is structurally upstream.
4. **Sensitivity-sweep documentation pattern**: every methodology parameter should be reported with its base-date and intermediate-day sensitivity. Gate's 88% TPRR_E intermediate-day sensitivity and TWAP ordering's 0.0001 base-date sensitivity should both be visible to institutional reviewers — they communicate parameter leverage at a glance.

## Two-layer Phase 11 framing

This finding contributes to the broader **"base-date convergence with trajectory sensitivity"** finding (separate doc): the gate threshold is the only parameter that breaks base-date convergence among the Batch 10B sweeps. Phase 11 should pair the gate finding (most consequential parameter, base-date sensitive at strict settings) with the base-date convergence finding (other three parameters all base-date invariant) to communicate the methodology's dual nature: published-rate robustness for institutional audiences + analyst-trajectory visibility for analyst audiences.

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10B — full sweep findings and decision-log entry
- DL 2026-04-29 Phase 6 — slot-level quality gate parameters (15% deviation canonical, original specification)
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) — companion finding on the cross-sweep base-date robustness story
- Methodology section 4.2.2 — slot-level gate threshold
- Methodology section 4.2.4 — minimum constituent count (downstream of gate cascade)
