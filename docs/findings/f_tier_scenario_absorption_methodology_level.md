# Methodology-Level F-Tier Scenario Absorption

**Source**: Phase 10 Batch 10C final (cross-config Phase 7H continuous-blending design space) + **Phase 11 Batch 11A** (cross-gate upstream parameter sweep, 2026-05-06). Combined evidence spans both downstream and upstream parameter axes.

**Status**: Empirical finding. **Headline result for Phase 11 manipulation-resistance section.** Scope is structural across two parameter axes tested: (a) the Phase 7H continuous-blending design space (downstream — λ, Tier B haircut, blending coefficients), and (b) the gate-threshold range (upstream). See [gate_x_scenarios_absorption.md](gate_x_scenarios_absorption.md) for the cross-gate finding's standalone documentation.

## Finding

TPRR-F absorbs the v0.1 scenario suite completely across **both** parameter axes tested:

> **Phase 10 Batch 10C** — 3 configs × 20 seeds × 6 scenarios × 366 days = **131,760 F-tier daily datapoints, byte-identical to clean.**
>
> **Phase 11 Batch 11A** — 6 gates × 20 seeds × 6 scenarios × 366 days = **263,520 F-tier daily datapoints, byte-identical to clean.**
>
> **Cumulative across both axes**: **395,280 F-tier daily datapoints, every one byte-identical to clean** (with the canonical config × gate=15% cell tested in both experiments, providing cross-experiment reproducibility verification of the absorption result).

Not a single F-tier delta exceeds machine precision at any config, gate, seed, scenario, or day. The maximum observed F-tier trajectory delta across both cross-products is ≤ 1.4×10⁻¹⁴ — below float-arithmetic noise floor, well below any methodologically meaningful tolerance.

The absorption is structural across:
- **Phase 7H continuous-blending design space (downstream)**: λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, blending coefficients held at the canonical (A=0.6, C=0.3, B=0.1).
- **Gate-threshold range (upstream)**: `quality_gate_pct ∈ {0.05, 0.10, 0.15, 0.20, 0.25, 0.30}` — the full Batch 10B-swept range, including the strict gates (5%, 10%) where Batch 10B documented material clean-panel TPRR_F base_date level shifts.

Same per-scenario response signature on S-tier and E-tier across all 3 Phase 7H configs and all 6 gate values: same 4 scenarios produce variation on S-tier (correlated_blackout, sustained_manipulation, intraday_spike, fat_finger_high), same 3 on E-tier (correlated_blackout, shock_price_cut, stale_quote). E-tier scenario response magnitude monotonically damps as gate loosens; S-tier swings non-monotonically with gate (per [gate_x_scenarios_absorption.md](gate_x_scenarios_absorption.md) §"Mechanism").

## Empirical evidence

### Base_date absorption — 9 cells × 120 pairs = 1,080 datapoints, all zero

| config | tier | n_(seed, scenario) pairs | n_pairs with abs delta > 1e-6 | Max abs delta ($/Mtok) |
|---|---|---:|---:|---:|
| default | TPRR_F | 120 | 0 | 0 |
| default | TPRR_S | 120 | 0 | 0 |
| default | TPRR_E | 120 | 0 | 0 |
| loose | TPRR_F | 120 | 0 | 0 |
| loose | TPRR_S | 120 | 0 | 0 |
| loose | TPRR_E | 120 | 0 | 0 |
| tight | TPRR_F | 120 | 0 | 0 |
| tight | TPRR_S | 120 | 0 | 0 |
| tight | TPRR_E | 120 | 0 | 0 |

Base_date convergence is methodology-level — a property of the suspension/reinstatement cycle producing identical steady-state constituent sets at base_date regardless of upstream perturbation. Documented separately in [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md).

### Full-trajectory absorption — F-tier byte-identical at every day, every config

| config | tier | n_pairs (of 120) with any trajectory delta | Max trajectory abs delta ($/Mtok) | n_scenarios producing variation |
|---|---|---:|---:|---:|
| default | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| default | TPRR_S | 59 / 120 | 0.1616 | 4 / 6 |
| default | TPRR_E | 60 / 120 | 0.1215 | 3 / 6 |
| loose | **TPRR_F** | **0 / 120** | 7.1×10⁻¹⁵ (float noise) | **0 / 6** |
| loose | TPRR_S | 58 / 120 | 0.1613 | 4 / 6 |
| loose | TPRR_E | 60 / 120 | 0.1238 | 3 / 6 |
| tight | **TPRR_F** | **0 / 120** | 1.4×10⁻¹⁴ (float noise) | **0 / 6** |
| tight | TPRR_S | 58 / 120 | 0.1731 | 4 / 6 |
| tight | TPRR_E | 60 / 120 | 0.1054 | 3 / 6 |

Source: `data/indices/sweeps/multi_seed/multi_seed_{config}_seed42-61_with_scenarios.parquet` for `config ∈ {default, loose, tight}`; manifest sweep ids `multi_seed_{config}_seed42-61_with_scenarios`. Analysis: [scripts/analyze_claim2_cross_config.py](../../scripts/analyze_claim2_cross_config.py).

### Per-tier × per-scenario response signature — invariant across configs

n_seeds (of 20) producing trajectory variation, per tier × scenario × config:

| Tier | Scenario | default | loose | tight |
|---|---|---:|---:|---:|
| TPRR_F | all 6 scenarios | 0 | 0 | 0 |
| TPRR_S | correlated_blackout | 20 | 20 | 20 |
| TPRR_S | fat_finger_high | 6 | 6 | 6 |
| TPRR_S | intraday_spike | 13 | 12 | 12 |
| TPRR_S | shock_price_cut | 0 | 0 | 0 |
| TPRR_S | stale_quote | 0 | 0 | 0 |
| TPRR_S | sustained_manipulation | 20 | 20 | 20 |
| TPRR_E | correlated_blackout | 20 | 20 | 20 |
| TPRR_E | fat_finger_high | 0 | 0 | 0 |
| TPRR_E | intraday_spike | 0 | 0 | 0 |
| TPRR_E | shock_price_cut | 20 | 20 | 20 |
| TPRR_E | stale_quote | 20 | 20 | 20 |
| TPRR_E | sustained_manipulation | 0 | 0 | 0 |

The per-scenario response signature is essentially constant across configs — same scenario set produces variation in S-tier (4 of 6: sustained_manipulation, correlated_blackout, intraday_spike, fat_finger_high) and same scenario set produces variation in E-tier (3 of 6: correlated_blackout, shock_price_cut, stale_quote). Per-scenario seed-counts differ by at most 1 across configs (intraday_spike S-tier: 13 → 12 → 12). Max abs deltas vary modestly (~10–20% per cell) but the qualitative response is identical.

The per-scenario signature is a property of scenario design (which contributors / models / slots each scenario perturbs) intersected with the slot-level gate filtering — not a property of the downstream blending parameters. λ and Tier B haircut redistribute weight on the surviving signals; they do not change *which* signals survive.

## Mechanism — upstream vs downstream

The methodology has two parameter regimes that operate at different points in the pipeline:

**Upstream (filtering layer)** — operates on raw slot-level prices before aggregation:
- Slot-level data quality gate (15% / 5-day trailing average) — excludes outlier slots
- Minimum-3-contributors-per-constituent threshold — excludes constituents with insufficient contributor redundancy
- Suspension/reinstatement policy (3-day suspend, 10-day reinstate) — excludes constituents with persistent gate exclusions

**Downstream (aggregation layer)** — operates on the already-filtered signals:
- Median-distance exponential weighting (λ)
- Tier volume haircuts (A=1.0, B=0.5, C=0.8 default)
- Within-tier-share normalisation
- Tier blending coefficients (A=0.6, C=0.3, B=0.1)

**The Phase 7H continuous-blending parameters swept here (λ, Tier B haircut, blending coefficients) are all downstream parameters.** The gate-cascade + minimum-3 + suspension policy filter scenario perturbations *before* they reach the blending step. λ and Tier B haircut are downstream operations on the surviving signals; they redistribute weight but cannot reintroduce filtered-out signals.

This explains why scenario absorption is invariant to the Phase 7H configs swept: the absorption mechanism operates upstream of the parameters being varied.

The F-tier's structural advantage rests on three properties combining at the upstream layer:

1. **Constituent redundancy**: TPRR_F has 6 constituents (vs 4 on S-tier). Even if a scenario perturbs one constituent's prices, the 5 remaining constituents anchor the F-tier index level.

2. **Contributor redundancy per constituent**: each F-tier constituent has multiple contributors with valid daily TWAPs (≥3 contributors per constituent at default config). A scenario that perturbs one contributor's slot-level prices gets gated out at the slot level before reaching the per-constituent daily TWAP.

3. **Gate-cascade absorption pre-aggregation**: the slot-level gate runs *before* aggregation. Scenarios inject perturbations at specific slots; the gate identifies them as outliers against the 5-day trailing average and excludes them from the daily TWAP. Suspended pairs (3+ days of slot-level exclusions) drop out of the daily fix entirely. By the time the dual-weighted formula sees the F-tier constituent prices, scenario perturbations have been filtered three times.

S-tier (4 constituents) and E-tier (5–6 constituents but lighter contributor redundancy) have less filtering capacity at the upstream layer, so trajectory variation passes through for some scenarios. The per-scenario response signature being config-invariant is consistent: changing downstream blending does not change which scenarios get past the upstream filter.

## Scope of the structural claim

The absorption claim is **structural with respect to both swept parameter axes**:

- **Downstream — Phase 7H continuous-blending design space**: λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, blending coefficients within the loose / default / tight envelope. Verified in Phase 10 Batch 10C.
- **Upstream — gate-threshold range**: `quality_gate_pct ∈ {0.05, 0.10, 0.15, 0.20, 0.25, 0.30}`. Verified in Phase 11 Batch 11A. The cross-gate result is striking because Batch 10B documented that the strict gates (5%, 10%) materially shift the clean-panel TPRR_F base_date raw_value (28.23 vs 30.24 at canonical 15%); despite the level shift, the **scenario delta** stays byte-identical at zero across the full gate range. The clean-panel level moves; the scenario response is invariantly absorbed.

Not a claim that holds for arbitrary parameter values — verification was performed within the swept ranges. See [gate_x_scenarios_absorption.md](gate_x_scenarios_absorption.md) §"Acknowledged remaining scope gaps" for the parameter axes that **were not** swept against scenarios:

- Minimum-3 threshold × scenarios (the redundancy mechanism itself; testing might be tautological by construction)
- Suspension/reinstatement policy × scenarios
- TWAP ordering × multi-seed × scenarios (Batch 10B did seed-42 only)
- Tier-eligibility threshold × scenarios

These remain v1.3+ items.

## Honest calibration acknowledgement

The byte-identical result is consistent with the methodology being well-tuned to the specific failure modes the v0.1 scenario suite was designed to test. The scenarios — fat-finger high, intraday spike, correlated blackout, stale quote, shock price cut, sustained manipulation — were authored alongside the methodology, with the methodology's gate-and-suspension mechanisms in mind. They target specific perturbation patterns the gate is designed to catch.

This finding therefore demonstrates that **the methodology absorbs the v0.1 scenarios it was designed to absorb**, and does so invariantly across both swept parameter axes (Phase 7H continuous-blending design space + gate-threshold range). It does not yet demonstrate absorption of:

- **Compromised contributor scenarios**: an attacker controlling a single contributor's slot-level prices over an extended window (not just isolated outlier slots), with prices drifting slowly enough to avoid the 5-day trailing-average gate.
- **Simultaneous multi-tier coordinated attacks**: scenarios that perturb F, S, and E tiers simultaneously to overwhelm the cross-tier blending dynamics.
- **Slowly evolving manipulation**: a multi-week price drift induced across multiple contributors, each move staying below the 15% gate threshold but the cumulative effect material.
- **Scenarios targeting the within-tier-share normalisation specifically**: e.g., volume-share manipulation rather than price manipulation.
- **Adversarial scenarios designed to defeat the gate**: scenarios authored *adversarially* by a red-team rather than alongside the methodology.

These are v1.3+ items. Phase 11 narrative should be precise about what's tested and what isn't.

## Per-tier mechanism by redundancy reservoir size

The cross-gate cross-product surfaces a per-tier mechanism keyed to **redundancy reservoir size** (constituent count × contributor depth per constituent). Three regimes:

- **F-tier (6 constituents × ≥3 contributors per constituent)** — redundancy reservoir is large enough that scenarios are absorbed across the full gate range tested. Absorption is structural across upstream and downstream parameter combinations tested. The dual-weighted formula's averaging across F-tier's broad surviving constituent set produces zero scenario delta at every gate. **F-tier sits in the "absorption regime."**

- **E-tier (5–6 constituents)** — smaller redundancy reservoir; scenarios produce trajectory variation. Magnitude monotonically damps as gate loosens — looser gate filters less raw slot variation, but the wider surviving constituent set absorbs more through averaging. **E-tier sits in the "filter-and-absorb regime" with monotonic gate-dependence.**

- **S-tier (4 constituents)** — smallest redundancy reservoir. Scenarios produce trajectory variation that swings **non-monotonically** with gate — strict gates suspend more constituents (less averaging cushion → larger response); moderate gates produce unstable small-constituent-count interactions. **S-tier sits in the "filter-and-absorb regime" with non-monotonic gate-dependence.**

Per-tier response correlates with redundancy reservoir size; the non-monotonic vs monotonic gate-dependence emerges from constituent count thresholds. F-tier's redundancy dominance puts it in the absorption regime; S/E-tier's smaller redundancy puts them in the filter-and-absorb regime with magnitude depending on gate-redundancy interaction.

This is a v1.3 specification implication: per-tier manipulation-resistance certification (F = absorption-regime; S/E = filter-and-absorb-regime) maps directly to constituent count. Tier C's v0.2+ activation (when ≥3 Tier C constituents per index tier) will activate Tier C in whichever regime its constituent count places it.

## Phase 11 narrative implication

This is the **headline manipulation-resistance result** for Phase 11. Phase 11 should frame it precisely:

**Recommended framing**: "TPRR-F absorbs the v0.1 scenario suite completely across the full Phase 7H continuous-blending design space (3 configs × λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}) AND across the upstream gate-threshold range (6 values: 5% / 10% / 15% / 20% / 25% / 30%) — 395,280 F-tier daily datapoints across both axes, every one byte-identical to clean. The dual-weighted formula combined with the slot-level gate, three-tier hierarchy, and minimum-3-constituents requirement absorbs the v0.1 scenario suite completely on the F-tier index, **across every methodology parameter combination tested in Phase 10 + Phase 11A at the values swept**. S-tier and E-tier indices show small trajectory variations under specific scenarios, with per-scenario response signatures that are essentially parameter-invariant — reflecting tier-specific structural differences in constituent count and contributor redundancy. Per-tier mechanism: F-tier sits in an absorption regime; S/E-tier sit in a filter-and-absorb regime with magnitude depending on gate-redundancy interaction."

**Discouraged framings**:
- "TPRR is impervious to manipulation." Overstates scope. The attack surface is the v0.1 scenario suite at the swept Phase 7H + gate values.
- "F-tier absorption holds across all parameter values." Overstates scope. Verified across two parameter axes (Phase 7H continuous-blending + gate threshold); other axes (minimum-3, suspension/reinstatement, tier-eligibility, TWAP ordering at multi-seed) were NOT swept against scenarios — see [gate_x_scenarios_absorption.md](gate_x_scenarios_absorption.md) §"Acknowledged remaining scope gaps."
- "Across every methodology parameter swept in Phase 10 + Phase 11A" — slightly overstates because some parameters were swept on the clean panel only, not against scenarios. Use the precise "**combination tested**" qualifier.

**Why this distinction matters**: institutional reviewers will probe scope. Overclaiming invites push-back ("what about minimum-2?"); underclaiming wastes a strong result. The precise framing — "absorbs the v0.1 scenario suite across every methodology parameter combination tested in Phase 10 + Phase 11A at the values swept" — is both accurate and impressive.

## v1.3 specification implications

v1.3 manipulation-testing work should:

1. **Address the remaining upstream-parameter-axis gaps** (gate × scenarios × seeds is now done; the rest are not):
   - Minimum-3 threshold × scenarios × seeds — the redundancy mechanism itself; testing might be tautological by construction (lowering the minimum mechanically breaks the redundancy reservoir on which the absorption regime depends), but worth verifying empirically.
   - Suspension/reinstatement policy × scenarios × seeds — Batch 10B swept on clean panel; not against scenarios.
   - TWAP ordering × multi-seed × scenarios — Batch 10B did seed-42 only; multi-seed extension not run.
   - Tier-eligibility threshold × scenarios — only verified at default threshold under v0.1 Tier C dormancy.
2. **Expand the scenario suite** with the attack vectors flagged in the calibration section:
   - Compromised contributor (extended-window manipulation, sub-gate price drift)
   - Simultaneous multi-tier coordinated attack
   - Slowly evolving manipulation (cumulative drift below gate)
   - Volume-share manipulation (attack on within-tier-share rather than price)
   - Red-team adversarial scenarios authored independently of the methodology design
3. **Re-run the multi-seed cross-product at v1.3 scenarios**: any new scenario in v1.3 should be tested across 20 seeds × default config minimum, with loose/tight × full gate range as soak tests.
4. **Document the F-tier absorption asymmetry as a design property**: F-tier's 6-constituent breadth + contributor redundancy is the methodology's primary manipulation-resistance reservoir. v1.3 should formalise this — the constituent count threshold (currently ≥3) directly drives manipulation-resistance capacity. Tier C's v0.2+ activation will need careful constituent-count calibration.
5. **Specify per-tier manipulation-resistance certification levels** based on the regime distinction documented in §"Per-tier mechanism by redundancy reservoir size":
   - F-tier (6 constituents) — **absorption regime**: zero scenario delta across both swept parameter axes
   - E-tier (5-6 constituents) — **filter-and-absorb regime, monotonic gate-dependence**: scenario response damps as gate loosens
   - S-tier (4 constituents) — **filter-and-absorb regime, non-monotonic gate-dependence**: small-constituent-count interactions with gate-induced suspension produce non-monotonic response
   v1.3 documentation should specify per-tier resistance levels rather than a single methodology-wide claim.

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10C continuation — Step 3 default-config cross-product (the precursor to the cross-config result this doc captures)
- DL 2026-05-05 Phase 10 Batch 10C final — loose + tight cross-product yielding the methodology-level result
- DL 2026-05-06 Phase 11 Batch 11A — gate × scenarios × seeds cross-product extending the claim to the upstream gate axis
- [gate_x_scenarios_absorption.md](gate_x_scenarios_absorption.md) — standalone finding doc for the cross-gate result (Phase 11 Batch 11A)
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) — companion finding (the two-layer framing this finding extends)
- [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md) — companion finding (the gate-cascade absorption mechanism, Batch 10B foundation)
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) — companion finding (the upstream gate threshold whose scenario absorption interaction is now characterised in this doc + the cross-gate companion)
- [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md) — companion finding (cross-seed stability that this absorption depends on)
- DL 2026-04-30 Phase 7H Batch B — continuous blending (the downstream layer this absorption operates above)
- DL 2026-04-30 Phase 7H Batch D — suspension reinstatement criteria (the suspension cycle that produces base_date convergence)
- Methodology section 4.2.2 — slot-level gate threshold (15%)
- Methodology section 4.2.4 — minimum constituent count (≥3 contributors per constituent)
- Methodology section 3.3 — three-tier hierarchy + dual-weighted formula
