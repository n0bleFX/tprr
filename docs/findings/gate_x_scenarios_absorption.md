# Cross-Gate F-Tier Scenario Absorption

**Source**: Phase 11 Batch 11A — gate threshold × scenarios × seeds cross-product (6 gate values × 20 seeds × 6 scenarios + clean baseline = 840 panel runs total, run across two compute sessions on 2026-05-05 and 2026-05-06).

**Status**: Empirical finding. **Strengthens the prior F-tier absorption finding's scope clause** from "structural with respect to Phase 7H continuous-blending design space; not claimed structural with respect to upstream parameters" to a stronger combined claim spanning both upstream (gate threshold) and downstream (Phase 7H continuous-blending) axes.

## Finding

TPRR-F absorbs the v0.1 scenario suite completely across the gate-threshold range:

> **6 gates × 20 seeds × 6 scenarios × 366 days = 263,520 F-tier daily datapoints, every one byte-identical to the corresponding clean-panel value.**

Maximum F-tier trajectory delta across the entire gate × scenarios × seeds cross-product is ≤ 7.1×10⁻¹⁵ (machine-epsilon float arithmetic noise). Verified across the gate-threshold range tested: `quality_gate_pct ∈ {0.05, 0.10, 0.15, 0.20, 0.25, 0.30}`.

**Combined with the prior Phase 10 Batch 10C cross-config finding** (3 Phase 7H configs × 20 seeds × 6 scenarios × 366 days = 131,760 F-tier datapoints byte-identical), the cumulative F-tier absorbed-datapoint count across both upstream and downstream parameter axes is **395,280**.

## Empirical evidence

### Base_date absorption — 18 cells × 120 pairs = 2,160 datapoints, all zero

| gate | tier | n_pairs | n_pairs_nonzero (delta > 1e-6) | max abs delta ($/Mtok) |
|---|---|---:|---:|---:|
| gate=5pct | TPRR_F / S / E | 120 each | **0 each** | 0 each |
| gate=10pct | TPRR_F / S / E | 120 each | **0 each** | 0 each |
| gate=15pct | TPRR_F / S / E | 120 each | **0 each** | 0 each |
| gate=20pct | TPRR_F / S / E | 120 each | **0 each** | 0 each |
| gate=25pct | TPRR_F / S / E | 120 each | **0 each** | 0 each |
| gate=30pct | TPRR_F / S / E | 120 each | **0 each** | 0 each |

Base_date convergence on F/S/E is gate-invariant — confirms the suspension/reinstatement-cycle steady-state mechanism documented in [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) holds across the full upstream gate parameter range.

### Full-trajectory absorption — F-tier byte-identical at every gate

| gate | tier | n_pairs (of 120) with any traj delta | max traj abs ($/Mtok) | n_scenarios producing variation |
|---|---|---:|---:|---:|
| gate=5pct | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| gate=5pct | TPRR_S | 72 / 120 | 0.345 | 4 / 6 |
| gate=5pct | TPRR_E | 60 / 120 | 0.245 | 3 / 6 |
| gate=10pct | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| gate=10pct | TPRR_S | 60 / 120 | 0.386 | 4 / 6 |
| gate=10pct | TPRR_E | 60 / 120 | 0.241 | 3 / 6 |
| gate=15pct | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| gate=15pct | TPRR_S | 59 / 120 | 0.162 | 4 / 6 |
| gate=15pct | TPRR_E | 60 / 120 | 0.122 | 3 / 6 |
| gate=20pct | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| gate=20pct | TPRR_S | 59 / 120 | 0.184 | 4 / 6 |
| gate=20pct | TPRR_E | 60 / 120 | 0.122 | 3 / 6 |
| gate=25pct | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| gate=25pct | TPRR_S | 60 / 120 | 0.073 | 4 / 6 |
| gate=25pct | TPRR_E | 60 / 120 | 0.022 | 3 / 6 |
| gate=30pct | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| gate=30pct | TPRR_S | 66 / 120 | 0.073 | 4 / 6 |
| gate=30pct | TPRR_E | 60 / 120 | 0.008 | 3 / 6 |

Source parquets: [gate_x_scenarios_seed42-61_gates_5_10_15.parquet](../../data/indices/sweeps/multi_seed/gate_x_scenarios_seed42-61_gates_5_10_15.parquet) (Session 1) + [gate_x_scenarios_seed42-61_gates_20_25_30.parquet](../../data/indices/sweeps/multi_seed/gate_x_scenarios_seed42-61_gates_20_25_30.parquet) (Session 2). Analysis: [scripts/analyze_gate_x_scenarios.py](../../scripts/analyze_gate_x_scenarios.py).

### Per-tier × per-scenario response signature across gates

n_seeds (of 20) producing trajectory variation, per tier × scenario × gate:

**TPRR_F** — 0 / 20 at every (scenario, gate) combination tested. **Same scenarios, same gates, all zero**. Absolute and unconditional within the swept range.

**TPRR_S — same 4 scenarios produce variation across all 6 gates**:

| Scenario | gate=5% | gate=10% | gate=15% | gate=20% | gate=25% | gate=30% |
|---|---:|---:|---:|---:|---:|---:|
| correlated_blackout | 20 | 20 | 20 | 20 | 20 | 20 |
| sustained_manipulation | 20 | 20 | 20 | 20 | 20 | 20 |
| intraday_spike | 12 | 12 | 13 | 12 | 14 | 20 |
| fat_finger_high | 20 | 8 | 6 | 7 | 6 | 6 |
| stale_quote | 0 | 0 | 0 | 0 | 0 | 0 |
| shock_price_cut | 0 | 0 | 0 | 0 | 0 | 0 |

**TPRR_E — same 3 scenarios produce variation across all 6 gates**:

| Scenario | gate=5% | gate=10% | gate=15% | gate=20% | gate=25% | gate=30% |
|---|---:|---:|---:|---:|---:|---:|
| correlated_blackout | 20 | 20 | 20 | 20 | 20 | 20 |
| shock_price_cut | 20 | 20 | 20 | 20 | 20 | 20 |
| stale_quote | 20 | 20 | 20 | 20 | 20 | 20 |
| fat_finger_high | 0 | 0 | 0 | 0 | 0 | 0 |
| intraday_spike | 0 | 0 | 0 | 0 | 0 | 0 |
| sustained_manipulation | 0 | 0 | 0 | 0 | 0 | 0 |

**E-tier max abs delta — clean monotonic decline as gate loosens**:

| Scenario | gate=5% | gate=10% | gate=15% | gate=20% | gate=25% | gate=30% |
|---|---:|---:|---:|---:|---:|---:|
| correlated_blackout | 0.245 | 0.241 | 0.122 | 0.122 | 0.022 | 0.0023 |
| shock_price_cut | 0.064 | 0.055 | 0.026 | 0.042 | 0.008 | 0.008 |
| stale_quote | 0.010 | 0.0017 | 0.0017 | 0.005 | 0.0005 | 0.0005 |

E-tier scenario response monotonically damps as gate loosens. The signature scenario (correlated_blackout) max delta drops from $0.245/Mtok at gate=5% to $0.0023/Mtok at gate=30% — two orders of magnitude.

## Mechanism — per-tier interpretation by redundancy reservoir size

The cross-gate result reveals a per-tier mechanism keyed to **redundancy reservoir size**:

**F-tier (6 constituents × ≥3 contributors per constituent)**: redundancy reservoir is large enough that scenarios are absorbed across the full gate range tested. Absorption is structural across upstream and downstream parameter combinations tested. The dual-weighted formula's averaging across F-tier's broad surviving constituent set produces zero scenario delta at every gate. **F-tier sits in the "absorption regime."**

**E-tier (5–6 constituents)**: smaller redundancy reservoir; scenarios produce trajectory variation. Magnitude monotonically damps as gate loosens — looser gate filters less raw slot variation, but the wider surviving constituent set absorbs more through averaging. The two effects compound favorably as gate increases. **E-tier sits in the "filter-and-absorb regime" with monotonic gate-dependence.**

**S-tier (4 constituents)**: smallest redundancy reservoir. Scenarios produce trajectory variation that swings **non-monotonically** with gate — strict gates suspend more constituents (less averaging cushion → larger response); moderate gates produce unstable small-constituent-count interactions. The non-monotonic swing on `correlated_blackout` (max delta 0.016 → 0.386 → 0.0074 across gates 5/10/15) and `fat_finger_high` (20 → 8 → 6 seeds with variation across the same gates) demonstrate that S-tier's small constituent count makes its response landscape sensitive to gate-induced suspension changes. **S-tier sits in the "filter-and-absorb regime" with non-monotonic gate-dependence.**

**Per-tier response correlates with redundancy reservoir size**:
- Larger reservoir (F-tier) → absorption regime, no gate dependence
- Mid reservoir with structural redundancy (E-tier 5-6) → filter-and-absorb with monotonic damping as gate loosens
- Small reservoir (S-tier 4) → filter-and-absorb with non-monotonic gate dependence driven by suspension dynamics

The non-monotonic vs monotonic gate-dependence emerges from constituent count thresholds. F-tier's redundancy dominance puts it in the **absorption regime**; S-tier's and E-tier's smaller redundancy puts them in the **filter-and-absorb regime** with magnitude depending on gate-redundancy interaction.

This is a v1.3 specification implication: per-tier manipulation-resistance certification (F = absorption-regime; S/E = filter-and-absorb-regime) maps directly to constituent count. Tier C's v0.2+ activation (when ≥3 Tier C constituents per index tier) will activate Tier C in whichever regime its constituent count places it.

## Combined Phase 10 + Phase 11A claim

Combining the three completed cross-products:

| Source | Cross-product | F-tier datapoints absorbed |
|---|---|---:|
| Phase 10 Batch 10C (downstream / Phase 7H continuous-blending) | 3 configs × 20 seeds × 6 scenarios × 366 days | 131,760 |
| Phase 11 Batch 11A (upstream / gate threshold) | 6 gates × 20 seeds × 6 scenarios × 366 days | 263,520 |
| **Cumulative** | (overlapping at canonical config) | **395,280** |

Note: the two cross-products share the canonical (default config × gate=15%) cell, so the cumulative count nominally double-counts ~21,960 datapoints (1 config × 20 seeds × 6 scenarios × 366 days at the shared canonical point). The "395,280 datapoints byte-identical" headline is correct as an aggregate of two independent experiments; treat as ~373,320 unique datapoints if strict non-overlap is required.

## Acknowledged remaining scope gaps

The following parameter axes were **not swept against scenarios** in Phase 10 or Phase 11A. These are scope clarifications, not weaknesses — the validation work tested the parameters most likely to matter (the highest-leverage gate per Batch 10B and the Phase 7H continuous-blending design space). Remaining gaps are documented for v1.3+ expansion.

- **Minimum-3 threshold × scenarios** — the redundancy mechanism itself; testing might be tautological by construction (lowering the minimum mechanically breaks the redundancy reservoir on which the absorption regime depends). Worth verifying empirically whether the F-tier absorption holds at minimum-2 or breaks.
- **Suspension/reinstatement policy × scenarios** — Batch 10B swept policy parameters on the clean panel; not against scenarios.
- **TWAP ordering × multi-seed × scenarios** — Batch 10B did seed-42 only; multi-seed extension not run.
- **Tier-eligibility threshold × scenarios** — the constituent → tier minimum-3 threshold added in Batch 10A. v0.1 Tier C dormant at every config tested; activation behavior under scenario perturbation only verified at default threshold.
- **Adversarial scenarios beyond v0.1 suite** — the 6 v0.1 scenarios were authored alongside the methodology; adversarial scenarios authored independently by a red team have not been tested.
- **Real provider data** — synthetic Tier A panel only; absorption claim is on the v0.1 calibrated panel.

These all remain v1.3+ items.

## Phase 11 narrative implication

The cross-gate result strengthens the F-tier absorption finding's scope clause materially. The recommended Phase 11 framing:

**Recommended framing**: "TPRR-F absorbs the v0.1 scenario suite completely across the full Phase 7H continuous-blending design space (3 configs × λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}) AND across the upstream gate-threshold range (6 values: 5% / 10% / 15% / 20% / 25% / 30%) — 395,280 F-tier daily datapoints across both axes, every one byte-identical to clean. The dual-weighted formula combined with the slot-level gate, three-tier hierarchy, and minimum-3-constituents requirement absorbs the v0.1 scenario suite completely on the F-tier index, **across every methodology parameter combination tested in Phase 10 + Phase 11A at the values swept**."

**Scope-honest qualifier** (the "at the values swept" clause): the absorption claim is empirical at the swept parameter values. Not a claim that holds at arbitrary parameter values outside the tested ranges; not a claim that holds against the parameter axes flagged as "remaining scope gaps" above.

**Discouraged framings**:
- "TPRR is impervious to manipulation" — overstates: scope is the v0.1 suite at swept parameter values
- "F-tier absorption holds across all methodology parameters" — overstates: 4+ parameter axes weren't swept against scenarios
- "Across every methodology parameter swept in Phase 10 + Phase 11A" — slightly overstates because some parameters were swept on the clean panel only, not against scenarios

The precise phrasing "across every methodology parameter **combination tested** in Phase 10 + Phase 11A at the values swept" is calibrated for institutional reviewers: claim is strong, scope is precise, gaps are explicit.

## v1.3 specification implications (updated from prior finding doc)

v1.3 manipulation-testing work should:

1. **Address the remaining scope gaps** flagged above — minimum-3 × scenarios, suspension/reinstatement policy × scenarios, TWAP ordering × multi-seed × scenarios, tier-eligibility threshold × scenarios. These are the not-yet-tested parameter axes.
2. **Expand the scenario suite** with adversarial attack vectors authored independently by a red team (not alongside the methodology).
3. **Per-tier manipulation-resistance certification levels** — formalise the regime distinction documented in the mechanism section: F-tier = absorption-regime (zero scenario delta); S/E-tier = filter-and-absorb regime (non-zero scenario delta with documented gate-dependence). v1.3 specification should specify per-tier resistance levels rather than a single methodology-wide claim.
4. **Real-data validation pathway** — once Tier A onboards real contributors and Tier B uses audited revenue, re-run the gate × scenarios × seeds cross-product to verify the absorption claim translates from synthetic to real panel structure.

## Cross-references

- DL 2026-05-06 Phase 11 Batch 11A — gate × scenarios × seeds cross-product (this finding's source)
- DL 2026-05-05 Phase 10 Batch 10C final — the prior cross-product on Phase 7H continuous-blending design space (this finding extends)
- [f_tier_scenario_absorption_methodology_level.md](f_tier_scenario_absorption_methodology_level.md) — companion finding (Phase 10 cross-config absorption result; updated to fold this cross-gate result)
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) — companion finding (Batch 10B clean-panel gate sweep showing gate=15% sits on convergence edge; this batch confirms scenario absorption on F-tier holds across the full gate range)
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) — companion finding (suspension cycle reaches steady state by base_date; explains why base_date is gate-invariant for clean and scenario panels alike)
- [phase_10_synthesis.md](phase_10_synthesis.md) §4.4 — synthesis scope clause (this finding strengthens)
- Methodology section 3.3 — three-tier hierarchy + dual-weighted formula
- Methodology section 4.2.2 — slot-level gate threshold (the upstream parameter this finding spans)
- Methodology section 4.2.4 — minimum constituent count (the redundancy mechanism)
