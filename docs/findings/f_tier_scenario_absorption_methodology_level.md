# Methodology-Level F-Tier Scenario Absorption

**Source**: Phase 10 Batch 10C final — cross-product sweep across 3 configs (default / loose / tight) × 20 seeds × 6 scenarios (clean + 6 scenarios per seed × config = 420 panel runs total). Cross-config evidence supersedes the prior default-config-only finding.

**Status**: Empirical finding. **Headline result for Phase 11 manipulation-resistance section.** Scope is structural with respect to the Phase 7H continuous-blending design space; not claimed structural with respect to upstream parameters (gate threshold, minimum-3, suspension policy).

## Finding

TPRR-F absorbs the v0.1 scenario suite completely across the Phase 7H continuous-blending design space:

> **3 configs × 20 seeds × 6 scenarios × 366 days = 131,760 F-tier daily datapoints, every one byte-identical to the corresponding clean-panel value.**

Not a single F-tier delta exceeds machine precision at any config, seed, scenario, or day. The maximum observed F-tier trajectory delta across all 131,760 datapoints is ≤ 1.4×10⁻¹⁴ — below float-arithmetic noise floor, well below any methodologically meaningful tolerance.

The absorption is **invariant to the Phase 7H continuous-blending parameters swept**: λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, blending coefficients held at the canonical (A=0.6, C=0.3, B=0.1). Same per-scenario response signature on S-tier and E-tier across all 3 configs.

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

The absorption claim is **structural with respect to the Phase 7H continuous-blending design space**: λ, Tier B haircut, and blending coefficients within the loose / default / tight envelope. Not a claim that holds for arbitrary parameter values — verification was performed within the swept range.

The claim is **not** structural with respect to upstream parameters (gate threshold, minimum-3 threshold, suspension policy):

- Batch 10B's gate threshold sweep (DL 2026-05-01 Batch 10B; [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md)) confirms strict gate settings (5%, 10%) shift TPRR-F base_date raw_value materially. This hints that upstream parameter changes would affect absorption.
- The cross-product of gate × scenarios × seeds was **not run** as part of Phase 10. The single-config gate sweep on the clean panel showed gate-driven shifts; scenario × gate interaction is uncharacterised.
- Minimum-3 threshold sensitivity has not been swept against scenarios.
- Suspension policy parameters (3-day suspend, 10-day reinstate) have been swept on the clean panel (Batch 10B); not against scenarios.

## Honest calibration acknowledgement

The byte-identical result is consistent with the methodology being well-tuned to the specific failure modes the v0.1 scenario suite was designed to test. The scenarios — fat-finger high, intraday spike, correlated blackout, stale quote, shock price cut, sustained manipulation — were authored alongside the methodology, with the methodology's gate-and-suspension mechanisms in mind. They target specific perturbation patterns the gate is designed to catch.

This finding therefore demonstrates that **the methodology absorbs the v0.1 scenarios it was designed to absorb**, and does so invariantly across the Phase 7H downstream design space. It does not yet demonstrate absorption of:

- **Compromised contributor scenarios**: an attacker controlling a single contributor's slot-level prices over an extended window (not just isolated outlier slots), with prices drifting slowly enough to avoid the 5-day trailing-average gate.
- **Simultaneous multi-tier coordinated attacks**: scenarios that perturb F, S, and E tiers simultaneously to overwhelm the cross-tier blending dynamics.
- **Slowly evolving manipulation**: a multi-week price drift induced across multiple contributors, each move staying below the 15% gate threshold but the cumulative effect material.
- **Scenarios targeting the within-tier-share normalisation specifically**: e.g., volume-share manipulation rather than price manipulation.
- **Adversarial scenarios designed to defeat the gate**: scenarios authored *adversarially* by a red-team rather than alongside the methodology.

These are v1.3+ items. Phase 11 narrative should be precise about what's tested and what isn't.

## Phase 11 narrative implication

This is the **headline manipulation-resistance result** for Phase 11. Phase 11 should frame it precisely:

**Recommended framing**: "Across the Phase 7H continuous-blending design space (λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, 60 seed × config combinations), 6 v0.1 scenarios, and the full 366-day backtest, TPRR-F produces byte-identical output to the corresponding clean panels at every day — 131,760 F-tier daily datapoints, every one identical to clean. The dual-weighted formula combined with the slot-level gate, three-tier hierarchy, and minimum-3-constituents requirement absorbs the v0.1 scenario suite completely on the F-tier index, invariantly to the downstream blending parameters. S-tier and E-tier indices show small trajectory variations under specific scenarios, with per-scenario response signatures that are also essentially config-invariant — reflecting tier-specific structural differences in constituent count and contributor redundancy."

**Discouraged framing**:
- "TPRR is impervious to manipulation." Overstates scope. The attack surface is the v0.1 scenario suite at the swept Phase 7H design points.
- "F-tier absorption holds across all parameter values." Overstates scope. Verified within the Phase 7H design space; upstream parameters (gate, minimum-3, suspension) not swept against scenarios.

**Why this distinction matters**: institutional reviewers will probe scope. Overclaiming invites push-back ("what about a compromised contributor?", "what about a 5% gate?"); underclaiming wastes a strong result. The precise framing — "absorbs the v0.1 scenario suite invariantly across the Phase 7H continuous-blending design space" — is both accurate and impressive.

## v1.3 specification implications

v1.3 manipulation-testing work should:

1. **Run upstream-parameter × scenarios × seeds cross-products** to characterise whether absorption holds across upstream parameter variation, or only within Phase 7H downstream design space:
   - Gate threshold × scenarios × seeds
   - Minimum-3 threshold × scenarios × seeds
   - Suspension/reinstatement policy × scenarios × seeds
2. **Expand the scenario suite** with the attack vectors flagged in the calibration section:
   - Compromised contributor (extended-window manipulation, sub-gate price drift)
   - Simultaneous multi-tier coordinated attack
   - Slowly evolving manipulation (cumulative drift below gate)
   - Volume-share manipulation (attack on within-tier-share rather than price)
   - Red-team adversarial scenarios authored independently of the methodology design
3. **Re-run the multi-seed cross-product at v1.3 scenarios**: any new scenario in v1.3 should be tested across 20 seeds × default config minimum, with loose/tight cross-products as soak tests.
4. **Document the F-tier absorption asymmetry as a design property**: F-tier's 6-constituent breadth + contributor redundancy is the methodology's primary manipulation-resistance reservoir. v1.3 should formalise this — the constituent count threshold (currently ≥3) directly drives manipulation-resistance capacity. Tier C's v0.2+ activation will need careful constituent-count calibration.
5. **Specify per-tier manipulation-resistance certification levels**: F-tier (6 constituents, 100% absorption v0.1 across Phase 7H design space) is the strongest; S-tier (4 constituents, partial absorption with config-invariant per-scenario signature) is intermediate; E-tier (5–6 constituents but lighter contributor redundancy) is partial. v1.3 documentation could specify per-tier resistance levels rather than a single methodology-wide claim.

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10C continuation — Step 3 default-config cross-product (the precursor to the cross-config result this doc captures)
- DL 2026-05-05 Phase 10 Batch 10C final — loose + tight cross-product yielding the methodology-level result
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) — companion finding (the two-layer framing this finding extends)
- [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md) — companion finding (the gate-cascade absorption mechanism, Batch 10B foundation)
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) — companion finding (the upstream gate threshold whose absorption interaction is uncharacterised)
- [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md) — companion finding (cross-seed stability that this absorption depends on)
- DL 2026-04-30 Phase 7H Batch B — continuous blending (the downstream layer this absorption operates above)
- DL 2026-04-30 Phase 7H Batch D — suspension reinstatement criteria (the suspension cycle that produces base_date convergence)
- Methodology section 4.2.2 — slot-level gate threshold (15%)
- Methodology section 4.2.4 — minimum constituent count (≥3 contributors per constituent)
- Methodology section 3.3 — three-tier hierarchy + dual-weighted formula
