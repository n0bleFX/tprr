# F-Tier Scenario Absorption at Default Config

**Source**: Phase 10 Batch 10C continuation — Step 3 cross-product sweep (default config × 20 seeds × 6 scenarios = 140 panel runs).

**Status**: Empirical finding. Load-bearing for Phase 11 manipulation-resistance narrative. Scope is precise: v0.1 scenario suite at default config across the tested seed range.

## Finding

TPRR-F absorbs the v0.1 scenario suite completely at default config across **20 seeds × 6 scenarios = 120 byte-identical datapoints at base_date and at every intermediate day**. Across all 720 day-level (366 days × 20 seeds × 6 scenarios) F-tier datapoints, every single one is byte-identical to the corresponding clean-panel value. Not a single delta exceeds machine precision at any seed, scenario, or day.

The scope is precise: this characterises the methodology's response to the **v0.1 scenario suite specifically**, at **default config specifically**, across **the tested 20-seed range specifically**. It is not a claim that TPRR-F is impervious to manipulation in general — future scenarios with different attack vectors may produce different results.

## Empirical evidence

### Base_date absorption

| Index | n_(seed, scenario) pairs | n_pairs with abs delta > 1e-6 | Max abs delta |
|---|---:|---:|---:|
| TPRR_F | 120 | **0** | $0.000000/Mtok |
| TPRR_S | 120 | 0 | $0.000000/Mtok |
| TPRR_E | 120 | 0 | $0.000000/Mtok |
| TPRR_B_F, TPRR_B_S, TPRR_B_E | 120 each | 0 each | $0.000000 each |
| TPRR_FPR, TPRR_SER | 120 each | 0 each | $0.000000 each |

**Eight indices × 120 pairs = 960 base_date datapoints, all exactly zero delta.**

Source: [data/indices/sweeps/multi_seed/multi_seed_default_seed42-61_with_scenarios.parquet](../../data/indices/sweeps/multi_seed/multi_seed_default_seed42-61_with_scenarios.parquet); manifest sweep id `multi_seed_default_seed42-61_with_scenarios`.

### Intermediate-day trajectory absorption

| Tier | n_(seed, scenario) pairs | n_pairs with any trajectory delta | Max trajectory abs delta |
|---|---:|---:|---:|
| **TPRR_F** | 120 | **0 / 120** | **$0.000000/Mtok** |
| TPRR_S | 120 | 59 / 120 | $0.1616/Mtok |
| TPRR_E | 120 | 60 / 120 | $0.1215/Mtok |

**TPRR_F is invariant at every day, not just base_date.** Across 720 (seed × scenario × 366 days = 43,920) F-tier daily datapoints, zero deviate from clean.

### Per-tier-per-scenario asymmetry

The asymmetry across tiers is methodologically important and worth surfacing explicitly:

**TPRR_F — 100% absorption**

| Scenario | n_seeds with traj variation |
|---|---:|
| All 6 scenarios | **0 / 20** |

**TPRR_S — 4/6 scenarios produce trajectory variation in some seeds**

| Scenario | n_seeds with traj variation | Max abs delta ($/Mtok) |
|---|---:|---:|
| sustained_manipulation | 20 / 20 | 0.068 |
| correlated_blackout | 20 / 20 | 0.0074 |
| intraday_spike | 13 / 20 | 0.002 |
| fat_finger_high | 6 / 20 | 0.16 |
| stale_quote | 0 / 20 | 0 |
| shock_price_cut | 0 / 20 | 0 |

**TPRR_E — 3/6 scenarios produce trajectory variation in some seeds**

| Scenario | n_seeds with traj variation | Max abs delta ($/Mtok) |
|---|---:|---:|
| correlated_blackout | 20 / 20 | 0.12 |
| stale_quote | 20 / 20 | 0.002 |
| shock_price_cut | 20 / 20 | 0.026 |
| fat_finger_high | 0 / 20 | 0 |
| intraday_spike | 0 / 20 | 0 |
| sustained_manipulation | 0 / 20 | 0 |

The mix differs per tier: F-tier sees nothing; S-tier sees broad-market and contributor-targeting scenarios; E-tier sees lower-tier-targeting scenarios. The per-tier asymmetry tracks scenario design — scenarios that target a specific tier produce trajectory variation in that tier, scenarios that don't target a tier are absorbed cleanly.

## Mechanism

The F-tier's 100% absorption rests on three structural properties combining:

1. **Constituent redundancy**: TPRR_F has 6 constituents. Even if a scenario perturbs one constituent's prices, the 5 remaining constituents continue to anchor the F-tier index level.

2. **Contributor redundancy per constituent**: each F-tier constituent has multiple contributors with valid daily TWAPs (≥3 contributors per constituent at default config). A scenario that perturbs one contributor's slot-level prices gets gated out at the slot level (5-day trailing average gate at 15%) before reaching the per-constituent daily TWAP.

3. **Gate-cascade absorption pre-aggregation**: the slot-level gate runs *before* aggregation. Scenarios inject perturbations at specific slots; the gate identifies them as outliers against the 5-day trailing average and excludes them from the daily TWAP. Suspended pairs (3+ days of slot-level exclusions) drop out of the daily fix entirely. By the time the dual-weighted formula sees the F-tier constituent prices, the scenario perturbations have been filtered three times.

This is **not** "the methodology absorbs everything" — it's "F-tier's 6 constituents × multi-contributor redundancy × gate-cascade pre-aggregation provides enough filtering to absorb single-perturbation v0.1 scenarios." S-tier (4 constituents) and E-tier (5–6 constituents but less contributor redundancy on the v0.1 panel) have less filtering capacity, so trajectory variation passes through for some scenarios.

The byte-identical base_date result across all 8 indices reflects a stronger version of the same mechanism: at base_date, the suspension cycle has reinstated all suspended pairs (per [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md)), so the steady-state constituent set is identical between clean and scenario panels.

## Honest calibration acknowledgement

The byte-identical result is consistent with the methodology being **well-tuned to the specific failure modes the v0.1 scenario suite was designed to test**. The scenarios — fat-finger high, intraday spike, correlated blackout, stale quote, shock price cut, sustained manipulation — were authored alongside the methodology, with the methodology's gate-and-suspension mechanisms in mind. They target specific perturbation patterns the gate is designed to catch.

This finding therefore demonstrates that **the methodology absorbs the v0.1 scenarios it was designed to absorb**. It does not yet demonstrate absorption of:

- **Compromised contributor scenarios**: an attacker controlling a single contributor's slot-level prices over an extended window (not just isolated outlier slots), with prices drifting slowly enough to avoid the 5-day trailing-average gate.
- **Simultaneous multi-tier coordinated attacks**: scenarios that perturb F, S, and E tiers simultaneously to overwhelm the cross-tier blending dynamics.
- **Slowly evolving manipulation**: a multi-week price drift induced across multiple contributors, each move staying below the 15% gate threshold but the cumulative effect material.
- **Scenarios targeting the within-tier-share normalisation specifically**: e.g., volume-share manipulation rather than price manipulation.
- **Adversarial scenarios designed to defeat the gate**: scenarios authored *adversarially* by a red-team rather than alongside the methodology.

These are v1.3+ items. Phase 11 narrative should be precise about what's tested and what isn't.

## Phase 11 narrative implication

This is the single strongest manipulation-resistance result Phase 10 has produced. Phase 11 should frame it carefully:

**Recommended framing**: "Across 20 panel realisations and 6 distinct scenarios designed to test the v0.1 methodology's failure modes, TPRR-F produces byte-identical output to the corresponding clean panels at every day of the 366-day backtest. The dual-weighted formula combined with the slot-level gate, three-tier hierarchy, and minimum-3-constituents requirement absorbs the v0.1 scenario suite completely on the F-tier index. S-tier and E-tier indices show small trajectory variations under specific scenarios, reflecting tier-specific structural differences in constituent count and contributor redundancy."

**Discouraged framing**: "TPRR is impervious to manipulation." This overstates the result. The scope is the v0.1 scenario suite at default config; v1.3 manipulation testing should expand the suite.

**Why this distinction matters**: institutional reviewers will probe the scope. Overclaiming invites push-back ("what about a compromised contributor?"); underclaiming wastes a strong result. The precise framing — "absorbs the v0.1 scenario suite at default config across the tested seed range" — is both accurate and impressive.

## v1.3 specification implication

v1.3 manipulation-testing work should:

1. **Expand the scenario suite** with the attack vectors flagged above:
   - Compromised contributor (extended-window manipulation, sub-gate price drift)
   - Simultaneous multi-tier coordinated attack
   - Slowly evolving manipulation (cumulative drift below gate)
   - Volume-share manipulation (attack on within-tier-share rather than price)
   - Red-team adversarial scenarios authored independently of the methodology design
2. **Re-run the multi-seed cross-product at v1.3 scenarios**: any new scenario in v1.3 should be tested across 20 seeds × default config minimum, with loose/tight cross-products as soak tests.
3. **Document the F-tier absorption asymmetry as a design property**: F-tier's 6-constituent breadth + contributor redundancy is the methodology's primary manipulation-resistance reservoir. v1.3 should formalise this — the constituent count threshold (currently ≥3) directly drives manipulation-resistance capacity. Tier C's v0.2+ activation will need careful constituent-count calibration.
4. **Consider per-tier manipulation-resistance certification levels**: F-tier (6 constituents, 100% absorption v0.1) is the strongest; S-tier (4 constituents, partial absorption) is intermediate; E-tier (5–6 constituents but lighter contributor redundancy) is partial. v1.3 documentation could specify per-tier resistance levels rather than a single methodology-wide claim.

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10C (continuation) — full Step 3 cross-product findings
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) — companion finding (the two-layer framing that this finding extends)
- [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md) — companion finding (the gate-cascade absorption mechanism, Batch 10B foundation)
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) — companion finding (the gate threshold that drives this absorption)
- [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md) — companion finding (cross-seed stability that this absorption depends on)
- DL 2026-04-30 Phase 7H Batch B — continuous blending (the layer this absorption operates within)
- DL 2026-04-30 Phase 7H Batch D — suspension reinstatement criteria (the suspension cycle that produces base_date convergence)
- Methodology section 4.2.2 — slot-level gate threshold (15%)
- Methodology section 4.2.4 — minimum constituent count (≥3 contributors per constituent)
- Methodology section 3.3 — three-tier hierarchy + dual-weighted formula
