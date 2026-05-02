# Tier-Eligibility Threshold Mechanism

**Source**: Phase 10 Batch 10A — in-memory sensitivity sweeps surfaced single-Tier-C-constituent edge case under continuous blending.

**Status**: Resolved methodology refinement. Closes the ninth Phase 7H/Phase 10 v1.3 specification gap. Documented here as the mechanism story, not just the parameter value.

## Finding

Continuous blending under v0.1's sparse Tier C coverage produces a degenerate within-tier-share when a tier has only one active constituent: that constituent automatically receives 100% within-tier-share, and the tier dominates the blended price disproportionately to its bias-weighted-confidence haircut. **Without a tier-eligibility threshold, deepseek-v3-2 (the v0.1 Tier C panel's sole constituent) drove 48.8% of the blended TPRR_E price** — a single-source dependency that violates the methodology's "minimum independent observations" principle. The minimum-3 tier-eligibility threshold resolves this by treating the constituent → tier layer symmetrically with the contributor → constituent layer.

## Empirical evidence

**Pre-threshold behaviour** (continuous blending without tier-eligibility constraint):
- TPRR_E base_date `tier_a_weight_share`: 0.4718
- TPRR_E base_date `tier_c_weight_share`: ~0.488 (deepseek-v3-2 alone, full within-tier-share)
- Single-constituent tier dominance: one Tier C constituent's price drove ~half of the blended index level

**Post-threshold behaviour** (tier requires ≥3 active constituents to contribute):
- TPRR_E base_date `tier_a_weight_share`: 0.9322 (Tier C's would-be weight redistributes back to Tier A)
- TPRR_E base_date `tier_c_weight_share`: 0.0 (deepseek-v3-2 fails threshold; tier dormant)
- TPRR_F base_date `tier_a_weight_share`: 0.9261 (unchanged — F-tier had no Tier C constituents to begin with)
- All 8 indices still rebase to 100.0000 at base_date
- ConstituentDecisionDF preserves all 732 deepseek-v3-2 audit rows (366 dates × TPRR_E + TPRR_B_E) with `coefficient=0`, `w_vol_contribution=0`, `included=True`

Source: DL 2026-05-01 Phase 10 Batch 10A (full discussion + test coverage at [tests/test_tier_eligibility_threshold.py](../../tests/test_tier_eligibility_threshold.py)).

## Mechanism

The TPRR methodology has two layers where "minimum independent observations" matters:

1. **Contributor → constituent layer**: each constituent must have ≥3 contributors with valid daily TWAPs to be included in the daily fix (Methodology Section 4.2.4). This protects against any single contributor's data quality issue propagating to the published level.

2. **Constituent → attestation-tier layer**: under continuous blending (DL 2026-04-30 Phase 7H Batch B), each tier's contribution is normalised by within-tier-share (Σ within-tier weights = 1 per tier). When a tier has 1 constituent, that constituent receives within-tier-share = 1.0 by construction — a degenerate normalisation that doesn't represent a market-wide tier price. The tier-eligibility threshold extends the same minimum-observation principle to this layer.

The principle is **symmetric across layers**: at every aggregation step where prices are combined, ≥3 independent observations are required. Without this, a tier with 1 constituent looks structurally identical to a tier with 100 constituents in the within-tier-share sense — both produce a 1.0 normalisation — even though the methodological confidence is wildly different.

The threshold's formal effect: a tier with `n_active < 3` is **dormant**. Its blending coefficient redistributes proportionally to the tiers that meet the threshold, preserving the dual-weighted formula's denominator while excluding the under-observed tier from the numerator. Audit rows for the dormant tier's constituents are preserved with `coefficient=0` for full reproducibility.

## v0.1 vs v0.2+ activation pattern

This is the key Phase 11 framing point: the threshold is **not** a special v0.1 patch, but a **structural specification** that activates Tier C smoothly as coverage expands.

- **v0.1**: deepseek-v3-2 is the only Tier C panel constituent → fails threshold → Tier C dormant → coefficient redistributes to Tier A and Tier B → published level identical to a no-Tier-C methodology.
- **v0.2+**: when ≥3 Tier C constituents exist for any tier (TPRR_F / TPRR_S / TPRR_E), Tier C activates automatically. The threshold doesn't need to be lowered — coverage growth crosses the threshold organically.

This is the smooth-activation property: the methodology behaves identically pre- and post-Tier-C-coverage-expansion at the published level, with no methodology version bump required to "turn on" Tier C. Tier C constituents that exist in only Tier C (not Tier A or B) contribute via Tier C only when threshold met; else excluded with `TIER_INELIGIBLE_FOR_BLENDING` audit reason.

## Phase 11 narrative implication

The institutional pitch is "TPRR uses three attestation tiers with minimum-independent-observation requirements at every aggregation layer." Phase 11 should explicitly address the v0.1 → v0.2 question that institutional reviewers will ask: **"How does the methodology behave as Tier C coverage expands?"**

Frame: "The methodology has a single eligibility rule that applies at every layer — minimum 3 independent observations. In v0.1 Tier C has 1 constituent, fails the rule, and is dormant. In v0.2+ as coverage expands past 3 Tier C constituents per tier, Tier C activates automatically. No methodology version bump, no governance committee decision required — the threshold formalises the methodology's design principle, the data crosses the threshold, the tier activates."

This is more compelling than framing the threshold as a workaround for v0.1's sparse data. It positions Tier C dormancy as a feature of the design (smooth activation under coverage growth), not a limitation.

## v1.3 specification implication

v1.3 should specify:

1. **Threshold value**: ≥3 active constituents per tier per index. Aligns with the contributor → constituent layer (already ≥3) and produces consistent layer-by-layer behavior.
2. **Audit-row preservation**: dormant-tier constituents retain rows in the audit trail with `coefficient=0`, `w_vol_contribution=0`, `included=True`. Reproducibility is preserved; the constituents are visible to auditors as "evaluated but excluded from blending."
3. **Coefficient redistribution rule**: when a tier is dormant, its blending coefficient redistributes proportionally to active tiers (preserving Σ coefficients = 1). Specified in DL 2026-04-30 Phase 7H Batch B addendum.
4. **Smooth-activation guarantee**: v1.3 should state that the threshold value will not be changed as Tier C coverage expands — coverage expansion is the trigger, not a methodology bump.

This is the **ninth** v1.3 specification gap surfaced through Phase 7H + Phase 10 validation work (cross-reference list at the end of DL 2026-05-01 Phase 10 Batch 10A entry).

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10A — full mechanism documentation + test coverage
- DL 2026-04-30 Phase 7H Batch B — continuous blending introduction (the layer where this gap surfaces)
- DL 2026-04-30 Phase 7H Batch B addendum — coefficient × tier_price symmetric specification (price-aggregation rule that the threshold completes)
- DL 2026-05-01 three-tier hierarchy bias profiles — Tier C structural limitations under v0.1 (the threshold formalises Tier C dormancy)
- DL 2026-04-29 Phase 4 close-out — 1 of 16 Tier C coverage stat (informs why the threshold matters in v0.1)
- Methodology section 3.3.2 — three-tier hierarchy under continuous blending
- Methodology section 3.3.3 — within-tier-share normalisation (the layer where degeneracy surfaces with 1 constituent)
- Methodology section 4.2.4 — minimum constituent count (the contributor → constituent precedent)
