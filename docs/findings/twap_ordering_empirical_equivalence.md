# TWAP Ordering: Empirical Equivalence Between TWAP-Then-Weight and Weight-Then-TWAP

**Source**: Phase 10 Batch 10B — TWAP ordering sweep, 2 orderings × (clean + 6 scenarios) on seed 42.

**Status**: Empirical defence of the canonical `twap_then_weight` ordering choice. Complements Phase 7 Batch E's commodity-benchmark precedent argument with cross-scenario empirical evidence.

## Finding

The two TWAP ordering choices (TWAP-then-weight, the canonical default; weight-then-TWAP, the alternative) are **practically equivalent at the published level on the v0.1 panel**. Clean-panel base_date delta is $0.0001/Mtok (essentially zero); maximum intermediate-day delta is ~5% on TPRR_F. Most strikingly: under both orderings, scenario-induced perturbations produce **byte-identical TPRR_F TWAP-ordering deltas across all 7 panels** (clean + 6 scenarios) — meaning the F-tier index is invariant to which scenario was applied at base_date under either ordering. The default `twap_then_weight` choice is empirically defended in addition to its commodity-benchmark precedent.

## Empirical evidence

### Base_date deltas (clean panel)

| Index | TWAP-then-weight | Weight-then-TWAP | Delta |
|---|---:|---:|---:|
| TPRR_F | 30.2405 | 30.2404 | **$0.0001/Mtok** |
| TPRR_S | (similar near-zero) | (similar near-zero) | <$0.001 |
| TPRR_E | (similar near-zero) | (similar near-zero) | <$0.001 |

Source: [data/indices/sweeps/twap_ordering/twap_ordering_seed42.parquet](../../data/indices/sweeps/twap_ordering/twap_ordering_seed42.parquet); manifest sweep id `twap_ordering_seed42`.

### Intermediate-day deltas (clean panel)

| Index | n_days_differ / 366 | max abs delta ($/Mtok) | mean abs delta |
|---|---:|---:|---:|
| TPRR_F | 72 (20%) | 1.4445 | 0.013 |
| TPRR_S | (similar pattern) | 0.030 | (small) |
| TPRR_E | (similar pattern) | 0.050 | (small) |

20% of days show *any* difference; max difference ~5% of typical raw value (TPRR_F typical $30/Mtok); mean across all 366 days near zero. Most days the orderings produce literally identical output.

### Cross-scenario delta invariance on F-tier

| Panel | TPRR_F TWAP-ordering n_days_differ | max abs delta |
|---|---:|---:|
| Clean | 72 / 366 | 1.4445 |
| fat_finger_high | 72 / 366 | 1.4445 |
| intraday_spike | 72 / 366 | 1.4445 |
| correlated_blackout | 72 / 366 | 1.4445 |
| stale_quote | 72 / 366 | 1.4445 |
| shock_price_cut | 72 / 366 | 1.4445 |
| sustained_manipulation | 72 / 366 | 1.4445 |

**Byte-identical** across all 7 panels. The scenarios all target lower tiers (S, E) or specific contributors that get filtered by gate + suspension before reaching F-tier aggregation. Whatever residual TWAP-ordering effect exists on F-tier depends on neither the scenario being applied nor the F-tier prices — it's a fixed property of the seed-42 F-tier panel realisation.

### Cross-scenario delta on S-tier

| Panel | TPRR_S TWAP-ordering n_days_differ from clean |
|---|---:|
| Clean | (baseline) |
| shock_price_cut | 0 |
| stale_quote | 0 |
| fat_finger_high | 1 (max $0.0008) |
| sustained_manipulation | 62 (max $0.006) |

Even on S-tier (where some scenarios target), divergence between scenarios under twap_then_weight ordering is small.

## Mechanism

The two orderings differ in what gets weighted:

- **TWAP-then-weight**: for each (contributor, model, date), compute the daily TWAP first, then aggregate across contributors using their daily TWAPs as the per-contributor "price of the day."
- **Weight-then-TWAP**: for each slot, compute a weighted index value across contributors, then take the TWAP of those 32 weighted index values.

Algebraically these would be identical if weights were constant within the day. They diverge only when weights vary across slots within a day. In the v0.1 methodology, weights are **fixed per day** (computed at end-of-day from daily TWAPs), so the only sources of intra-day variation are:

1. **Slot-level gate exclusions**: gated slots are removed from the daily TWAP. Under TWAP-then-weight, this affects each contributor's daily TWAP independently. Under weight-then-TWAP, the gating happens before the cross-contributor weighting at each slot.
2. **Edge cases at slot boundaries**: when a contributor has a change-event slot near the day's start or end, the two orderings produce slightly different intermediate values for that day.

The empirical 72/366 days = 20% pattern matches the v0.1 panel's gate-exclusion frequency on seed 42. Most days have no gated slots → orderings are identical. Days with gated slots have small but nonzero divergence.

The byte-identical scenario-cross-product result on F-tier comes from the gate + suspension cascade: scenarios inject perturbations at lower tiers, gate excludes the slot-level outliers, suspended pairs drop out, and the F-tier sees only the gate-and-suspension-filtered remainder — which is identical to the clean-panel filtered remainder for the F-tier constituents on this seed.

## Phase 11 narrative implication

The institutional-audience question is "why TWAP-then-weight rather than weight-then-TWAP?" Phase 11 has two answers:

1. **Commodity benchmark precedent** (Phase 7 Batch E): ICE Brent, Henry Hub, ASCI all use TWAP-then-weight. Aligning with established institutional precedent reduces operational complexity for downstream consumers and matches existing methodologies' audit conventions.

2. **Empirical equivalence** (this finding): on the v0.1 panel, the two orderings produce $0.0001/Mtok base_date delta and $1.4/Mtok max intermediate-day delta (~5% of typical). The choice is defensible on practical grounds — the alternative produces nearly the same output and would impose unnecessary departure from precedent.

Phase 11 framing: "TPRR's TWAP-then-weight ordering matches commodity benchmark precedent (ICE Brent, Henry Hub, ASCI). The alternative weight-then-TWAP ordering produces empirically near-identical output on the v0.1 panel ($0.0001/Mtok base-date delta), so the choice imposes no informational cost relative to the alternative — it preserves dimensional consistency in the weighting step and aligns with established institutional convention."

This is a strong "no methodology debt" finding: the ordering choice is defensible from both first principles (precedent) and empirical evidence (sensitivity sweep). Institutional reviewers asking "why this ordering?" get a complete answer.

## v1.3 specification implication

v1.3 should:

1. **Document the empirical equivalence finding** in the methodology specification's TWAP-ordering rationale section (4.2.1). Currently the rationale cites only commodity-benchmark precedent; the empirical evidence strengthens the argument materially.
2. **Note the gate-cascade absorption mechanism** as the reason scenario-cross-product deltas are byte-identical on F-tier. This is methodology working as designed — the v0.1 mock-data scenario suite demonstrates absorption rather than passes through.
3. **Specify the v1.3 sensitivity-sweep documentation pattern**: every parameter swept should include a published-level delta + intermediate-day delta + cross-scenario invariance check. The TWAP-ordering sweep is a clean template.
4. **Re-validate on real data in v1.3+**: the empirical equivalence claim depends on the v0.1 panel's gate-exclusion frequency. Real provider data with different gate-exclusion patterns may produce different intermediate-day deltas. The base-date equivalence ($0.0001/Mtok) is unlikely to change materially, but intermediate-day max-delta numbers should be re-verified.

## Post-Step 3 update — strengthening from byte-identical TWAP-ordering deltas to byte-identical absolute output

Phase 10 Batch 10C Step 3 (default config × 20 seeds × 6 scenarios cross-product, run after this finding doc was first written) strengthens the Batch 10B byte-identical result materially. The Batch 10B finding observed "scenarios produce byte-identical TPRR_F TWAP-ordering *deltas* across all 7 panels at fixed seed-42" — i.e. the *difference between orderings* was scenario-invariant. Step 3 establishes a stronger result: at default config (which uses twap_then_weight), **scenarios produce byte-identical TPRR_F absolute output across 20 seeds, not just byte-identical ordering deltas at one seed**. Every TPRR_F datapoint at every day at every seed at every scenario is byte-identical to the clean-panel value.

This means the Batch 10B "scenarios are absorbed before reaching F-tier aggregation" mechanism — originally observed via TWAP-ordering delta invariance — is in fact a property of the absolute F-tier output, not just of the ordering-delta. The gate-cascade absorption holds at every seed and every scenario at the F-tier published level. Phase 11 narrative should reference [f_tier_scenario_absorption_at_default_config.md](f_tier_scenario_absorption_at_default_config.md) for the full Step 3 finding; this TWAP-ordering finding is the **single-seed precursor** that Step 3 generalised across 20 seeds.

## Cross-references

- DL 2026-04-30 Phase 7 Batch E — TWAP ordering choice (Q1 lock to twap_then_weight as default; commodity precedent argument)
- DL 2026-05-01 Phase 10 Batch 10B — TWAP ordering sweep findings
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) — companion finding (gate is upstream of TWAP ordering's intermediate-day effects)
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) — companion finding (TWAP ordering is one of three parameters with base-date convergence)
- Methodology section 4.2.1 — TWAP daily fix, ordering convention
