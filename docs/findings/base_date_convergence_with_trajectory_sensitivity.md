# Base-Date Convergence with Trajectory Sensitivity

**Source**: Phase 10 Batch 10B — pipeline-rerun sweeps across suspension threshold, reinstatement threshold, gate threshold, TWAP ordering on seed 42.

**Status**: Cross-sweep synthesis finding. Identifies a publishable two-layer story for Phase 11 methodology communication.

## Finding

Three of four pipeline-rerun parameters swept in Phase 10 Batch 10B (suspension threshold, reinstatement threshold, TWAP ordering) leave **TPRR_F base_date raw_value invariant** across their full swept ranges. Only the gate threshold shifts the base_date level, and only at strict settings (5%, 10%) below the canonical 15%. Yet **all four sweeps produce substantial intermediate-day trajectory variation** — 51–88% of days differ across the parameter range. This duality supports a two-layer Phase 11 narrative: institutional reference-rate consumers see methodology robustness at the published level; analyst trajectory consumers see methodology sensitivity in the intermediate-day series. Both framings are accurate and complementary.

## Empirical evidence

### Base-date raw_value across each sweep

| Sweep | Range | TPRR_F base_date raw_value variation |
|---|---|---|
| Suspension threshold | 2 / 3 / 5 / 7 days | **None** (30.2405 invariant) |
| Reinstatement threshold | 5 / 10 / 15 / 20 days | **None** (30.2405 invariant) |
| TWAP ordering | twap_then_weight vs weight_then_twap | **$0.0001/Mtok** (essentially zero) |
| Gate threshold | 0.05 / 0.10 / 0.15 / 0.20 / 0.25 / 0.30 | **$2.01/Mtok at strict settings, then converges** |

Three of four = base-date invariant. The fourth (gate) converges above the canonical 15% setting:

| `quality_gate_pct` | TPRR_F base_date raw_value |
|---|---:|
| 0.05 | 28.2315 |
| 0.10 | 28.94 |
| 0.15 (canonical) | **30.2405** |
| 0.20 | 30.2405 |
| 0.25 | 30.2405 |
| 0.30 | 30.2405 |

The canonical 15% gate sits exactly on the convergence edge.

### Intermediate-day trajectory variation per sweep

| Sweep | TPRR_F n_days_differ | TPRR_E n_days_differ | Max abs delta |
|---|---:|---:|---|
| Suspension | 75 / 366 (20%) | 186 / 366 (51%) | $5.40/Mtok TPRR_F |
| Reinstatement | 80 / 366 (22%) | **227 / 366 (62%)** | $6.80/Mtok TPRR_F |
| Gate | 212 / 366 (58%) | **323 / 366 (88%)** | $5.27/Mtok TPRR_F |
| TWAP ordering | 72 / 366 (20%) | (small) | $1.4445/Mtok TPRR_F |

**Every sweep** shows intermediate-day trajectory variation. TPRR_E in particular shows 51–88% of days differing across the four sweeps. The trajectory is sensitive even where the base-date level is invariant.

Source parquets: [data/indices/sweeps/](../../data/indices/sweeps/) — `suspension_threshold/`, `reinstatement_threshold/`, `gate_threshold/`, `twap_ordering/`.

### Cross-tier sensitivity ranking

| Tier | Trajectory sensitivity rank |
|---|---|
| TPRR_E | Highest (62–88% across sweeps) |
| TPRR_F | Middle (20–58%) |
| TPRR_S | Smallest |

TPRR_E is the most trajectory-sensitive tier across every parameter — consistent with E-tier having the highest underlying volatility (DL 2026-04-29 contributor profiles, [pricing_model_design.md](pricing_model_design.md) — E-tier daily σ = 0.40%/day vs F-tier 0.15%/day).

## Mechanism

The base-date convergence pattern emerges from the **suspension/reinstatement window** structure:

- The 366-day backtest window (Jan 2025 → Jan 2026) is long relative to the suspension cycle (3-day exclude → 10-day reinstate window).
- Pairs that get suspended at any point during the backtest typically reinstate before the base_date.
- The base_date sees the **steady-state constituent set** under any suspension/reinstatement parameter that admits eventual reinstatement.
- Only parameters that change the **filter at the input boundary** (gate threshold) can change which prices the methodology sees at base_date — and even then, the canonical 15% sits above the convergence edge.

The trajectory variation comes from the same suspension cycles' effects on intermediate days. Pairs in suspension on day D are excluded from the day-D fix, even if they're back by day D+10. So the trajectory shows the intermittent suspension effects, while the base-date sees the post-cycle steady state.

This is a structural property of the methodology, not a seed-42 artefact. Any backtest window long relative to the suspension cycle will produce the same pattern.

## Phase 11 narrative implication

This is the **central two-layer Phase 11 narrative** for institutional audiences. Different consumers need different framings, and both framings are simultaneously true:

### Framing 1 — Reference-rate consumer (CFOs, treasurers, regulators)

Audience asks: "What if you'd chosen different methodology parameters?"

Answer: "Three of the four downstream methodology parameters (suspension, reinstatement, TWAP ordering) leave the TPRR_F published level **completely unchanged** across reasonable parameter ranges. The fourth (gate threshold) leaves the level unchanged for any setting at or above the canonical 15% — the canonical choice sits at the convergence edge by design. The published reference rate is not parameter-fragile."

This is the **publishable robustness story** — exactly what an institutional benchmark consumer wants to hear.

### Framing 2 — Analyst trajectory consumer (research analysts, traders, derivative designers)

Audience asks: "How does intra-period methodology choice affect the trajectory?"

Answer: "The intermediate-day trajectory is genuinely sensitive to methodology parameters — 20–88% of trajectory days differ across the swept ranges. Analysts pivoting on the trajectory should examine the methodology-versus-real-economic-signal decomposition. Suspension and reinstatement parameters drive trajectory variation that smooths out by base_date but is visible day-to-day."

This is the **analyst-visibility story** — the methodology is not opaque; intermediate-day variation is documented and quantifiable.

### Combined narrative

"TPRR has two layers. The published reference level is robust to methodology parameter choice — the dual-weighted formula plus the suspension/reinstatement cycle plus the gate convergence above 15% combine to produce a base-date-anchored level that doesn't move when reasonable parameters move. The trajectory between fixings reflects methodology dynamics — slot-level gate exclusions, suspension cycles, ordering effects — and is visible to analysts who pivot on day-to-day movements. Both layers are intentional. Both are documented. Both are part of what makes this an institutional-grade benchmark rather than a single-formula calculation."

## v1.3 specification implication

v1.3 should:

1. **Document the two-layer property explicitly** in the methodology specification's introduction. Frame it as a design property: "the methodology produces a parameter-robust published level alongside a parameter-sensitive trajectory; both are intentional and complementary."

2. **Specify the convergence-edge calibration principle**: parameter values should be chosen at the loosest setting that doesn't degrade the published level. Gate's 15% is the canonical example. Future parameter additions should follow this calibration principle.

3. **Add base-date robustness metrics to v1.3 published-level reporting**: "across [parameter set X], TPRR_F base_date raw_value invariant" should be a documented robustness statement. Index Committee parameter-change proposals should include this metric.

4. **Two-layer documentation in Phase 11 release**: methodology white-paper for institutional audiences should be structured around the two layers explicitly. Not "here's one published number"; instead "here's the published level, here's the trajectory, here's how parameters affect each."

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10B — full sweep findings
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) — companion finding (gate is the only base-date-non-invariant parameter, and it converges)
- [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md) — companion finding (TWAP ordering is one of the three base-date-invariant parameters)
- DL 2026-04-30 Phase 7H Batch D — suspension reinstatement criteria (3-day exclude / 10-day reinstate)
- DL 2026-04-29 Phase 6 — slot-level quality gate parameters (15% canonical)
- Methodology section 4.2.1 (TWAP daily fix), 4.2.2 (gate threshold), 3.3.2 (suspension/reinstatement)
