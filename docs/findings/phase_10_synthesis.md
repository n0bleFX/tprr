# Phase 10 Synthesis — Validation Outcomes Across the Phase 7H Design Space

**Source**: Phase 10 Batch 10D — synthesis of all Phase 10 sensitivity / validation outputs (Batches 10A in-memory, 10B pipeline-rerun, 10C multi-seed + scenarios cross-product). Aggregates 13 sweeps in `data/indices/sweeps/manifest.csv` and 7 standalone Phase 10 finding docs into a single internal scaffold for Phase 11 publication authoring.

**Status**: Internal scaffolding. Not publication prose. Phase 11 author lifts content forward, expanding [PUBLICATION-GRADE] items into prose and folding [METHODOLOGY-DOC] items into the methodology specification rewrite (deferred to Phase 11). [AUDIT-TRAIL] items remain referenced from the audit narrative without being lifted as prose.

**Tagging convention used throughout**:
- **[PUBLICATION-GRADE]** — content that should lift forward into Phase 11 prose
- **[AUDIT-TRAIL]** — content that supports Phase 11 but stays as supporting documentation
- **[METHODOLOGY-DOC]** — content that should populate the methodology doc rewrite (deferred)

---

## 1. Introduction and validation scope

### 1.1 Primary research question (verbatim)

From [CLAUDE.md](../../CLAUDE.md) (project canonical statement, mirrored in [project_plan.md](../../project_plan.md)):

> Does the TPRR dual-weighted formula — specifically exponential median-distance weighting at λ=3 combined with the three-tier volume hierarchy, over a TWAP daily fixing — produce a stable, credible, manipulation-resistant index when run on realistic data?

**[PUBLICATION-GRADE]** Phase 11 introduction should anchor on this question verbatim, then summarise: the answer landed in v0.1 is **"yes, with modifications to canonical Section 3.3.2 priority fall-through that the validation work itself surfaced and tested."** The methodology refinement is the deliverable, not just the index numbers.

### 1.2 v0.1 validation scope as completed

| Element | What v0.1 tested | Source |
|---|---|---|
| Synthetic Tier A panel | 10 contributors × 16 constituents, calibrated to plausible 2025 enterprise-segment prices, deterministic at seed | [pricing_model_design.md](pricing_model_design.md), [seed_42_baseline_characteristics.md](seed_42_baseline_characteristics.md) |
| Tier B implied volumes | Disclosed provider revenue × OpenRouter within-provider split, 0.5 haircut | DL 2026-04-29 Tier B entry, DL 2026-04-30 Phase 7H Batch C |
| Tier C rankings | OpenRouter top-9 rankings snapshot, 1 of 16 constituents covered (deepseek-v3-2 alone) | DL 2026-04-29 Phase 4 close-out |
| Backtest range | 366 days, 2025-01-01 → 2026-01-01, base_date 2026-01-01 (presentation convenience; production v1.0 will anchor at index launch date) | DL 2026-05-01 base date convention |
| Scenarios | 6 v0.1 scenarios authored alongside the methodology: fat_finger_high, intraday_spike, correlated_blackout, stale_quote, shock_price_cut, sustained_manipulation | `config/scenarios.yaml` |
| Single-seed sensitivity | 7 single-seed sweeps at seed 42, with parameter ranges: λ ∈ [1, 2, 3, 5, 10] (5 values); Tier B haircut ∈ [0.4, 0.5, 0.6, 0.7] (4 values); blending coefficient × 4 variants; suspension threshold ∈ [2, 3, 5, 7] (4 values); reinstatement threshold ∈ [5, 10, 15, 20] (4 values); gate threshold ∈ [5%, 10%, 15%, 20%, 25%, 30%] (6 values); TWAP ordering × 7 panels × 2 orderings = 14 runs | Manifest rows 1–7 (Batches 10A, 10B) |
| Multi-seed × Phase 7H configs | 6 multi-seed sweeps (3 Phase 7H configs × {clean panel, clean + 6 scenarios}). Clean trio: 60 panel runs total; with-scenarios trio: 420 panel runs total | Manifest rows 8–13 (Batch 10C) |

### 1.3 What v0.1 demonstrably tests vs what it does not test

**[PUBLICATION-GRADE]** Frame the scope precisely. v0.1 demonstrably tests:

- **Methodology behaviour on a synthetic but realistically-calibrated panel** with all three tiers populated according to v0.1's tier-coverage assumptions
- **Sensitivity to all four downstream parameters** (λ, Tier B haircut, blending coefficients, suspension/reinstatement) plus the upstream gate threshold
- **Stability across panel realisations** (20 seeds at each of three Phase 7H configs)
- **Manipulation resistance against the v0.1 scenario suite** at every Phase 7H downstream design point swept

v0.1 does **not** test:

- **Real provider price dynamics** — synthetic Tier A panel with calibrated baseline prices, not actual contributor billing data
- **Real volume attribution** — Tier B revenue inputs are analyst-triangulation point estimates per quarter, not audited disclosures
- **Real Tier C coverage breadth** — only top-9 OpenRouter rankings ingested; full models endpoint deferred to v0.2+
- **Adversarial scenarios beyond v0.1 suite** — scenarios were authored alongside the methodology with the gate-and-suspension mechanisms in mind, not by an independent red team
- **Upstream parameter × scenario interaction** — gate threshold × scenarios × seeds cross-product was not run (Batch 10C scope was Phase 7H downstream design space)
- **Real-time / production publication dynamics** — single-shot backtest, not live publication with intraday revision discipline

These limitations bound every claim in the validation. Phase 11 prose should weave them in section-by-section rather than relegating them to a footer.

### 1.4 The methodology refinement arc

**[PUBLICATION-GRADE]** Phase 10 is the empirical close of an arc that began in Phase 7 and bent through Phase 7H:

1. **Phase 7 (literal-canon implementation)**: implemented Section 3.3.2 priority fall-through verbatim. Surfaced cross-tier magnitude cascade (DL 2026-04-30 Phase 7 Batch C — ~66,000:1 raw-volume gap between Tier A and Tier B) and cliff-edge dynamics (DL 2026-04-30 Phase 9 visual diagnostic — TPRR_F `tier_a_weight_share` = 0.0012 at base_date pre-7H).

2. **Phase 7H (proposed methodology modifications)**: four substantive changes designed to address the issues surfaced — within-tier-share normalisation, continuous blending, Tier B confidence haircut recalibration, symmetric suspension reinstatement. DL 2026-04-30 Phase 7H methodology design entry positions these as a candidate v1.3 specification implemented within v0.1 as the validation experiment.

3. **Phase 10 Batch 10A in-memory sweeps**: surfaced the ninth specification item (the fourth and final methodology gap, classified per §6's 7 methodology + 2 doc-text taxonomy) — single-Tier-C-constituent within-tier-share degeneracy under continuous blending — and added the tier-eligibility threshold to close it.

4. **Phase 10 Batches 10B + 10C**: empirically characterised the modified methodology's response across the Phase 7H design space.

Cumulative TPRR_F base_date `tier_a_weight_share` trajectory across the arc (seed-42 reference; full distribution at default config in §3.4):

| Stage | TPRR_F base_date `tier_a_weight_share` | n_a |
|---|---:|---:|
| Pre-7H literal-canon | 0.0012 | 3 |
| Post-Batch A (within-tier-share normalisation only) | 0.5083 | 3 |
| Post-Batch B (+ continuous blending) | 0.6980 | 3 |
| Post-Batch C (+ Tier B haircut 0.9 → 0.5) | 0.8063 | 3 |
| Post-Batch D (+ symmetric reinstatement) | 0.9261 | 6 |
| Post-Batch 10A (+ tier-eligibility threshold) | 0.9261 | 6 |

Note: Batch 10A's tier-eligibility threshold did not affect TPRR_F (no Tier C constituents in F); it affected TPRR_E by collapsing `tier_c_weight_share` from 0.4883 to 0.0000. The TPRR_F trajectory is shown for cumulative cliff-edge resolution; TPRR_E's separate trajectory is in [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md).

**[PUBLICATION-GRADE]** Phase 11 prose should walk this trajectory explicitly. The cumulative effect is the headline of the methodology-refinement arc — each step contributes; together they resolve cliff-edge dynamics from 0.0012 (degenerate) to 0.9261 (full F-tier activation). Source: DL 2026-04-30 Phase 9 close-out entry, "Empirical resolution" table.

---

## 2. Methodology refinements through validation

### 2.1 Phase 7H Batches A–D — the core modifications

**[METHODOLOGY-DOC]** All four belong in the methodology spec rewrite. v0.1 implementation matches the proposed v1.3 specification.

**Batch A — Within-tier-share normalisation** (DL 2026-04-30 Phase 7H Batch A): replace `w_vol = raw_volume × haircut` with `w_vol = (volume / Σ within-tier volumes) × haircut`. Within-tier shares are bounded in [0, 1] regardless of underlying scale, eliminating the ~66,000:1 cross-tier magnitude gap that caused Tier B to dominate raw-volume aggregation in Phase 7. **Empirical effect on seed 42**: TPRR_F base_date `tier_a_weight_share` 0.0012 → 0.5083. **Methodology section affected**: 3.3.3.

**Batch B — Continuous blending replaces priority fall-through** (DL 2026-04-30 Phase 7H methodology design + Batch B audit trail). Each constituent contributes to potentially multiple tiers per day with coefficients (A=0.6, C=0.3, B=0.1) when all tiers are available; coefficients redistribute proportionally when fewer tiers are available. Audit trail shifts to long-format per-tier breakdown. **Empirical effect**: 0.5083 → 0.6980 on seed 42. Symmetric coefficient × tier_price formula for price aggregation specified in the post-design addendum. **Methodology section affected**: 3.3.2.

**Batch C — Tier B confidence recalibration** (DL 2026-04-30 Phase 7H Batch C): Tier B haircut 0.9 → 0.5. Tier ordering A > C > B (was A > B > C). Documented bias chain: provider total revenue × API_share × OpenRouter within-provider split ÷ reference price, with compounding 30–50% upward bias on implied volumes. **Empirical effect**: 0.6980 → 0.8063 on seed 42. **Methodology section affected**: 3.3.2 (volume weights — Tier B confidence calibration).

**Batch D — Bidirectional suspension reinstatement** (DL 2026-04-30 Phase 7H Batch D): asymmetric thresholds — 3-day exclude / 10-day reinstate. Replaces the one-way ratchet (suspension permanent until manual reinstatement) that DL 2026-04-30 suspension reinstatement gap entry identified as inconsistent with real benchmark practice. Missing-day reset rule preserves "observed on-market" semantics. **Empirical effect**: 0.8063 → 0.9261 on seed 42, with all 6 F-tier constituents back in Tier A (n_a = 6). **Methodology section affected**: 4.2.2 (data quality checks — suspension/reinstatement criteria).

### 2.2 Phase 10 Batch 10A — tier-eligibility threshold

**[METHODOLOGY-DOC]** [tier_eligibility_threshold_mechanism.md](tier_eligibility_threshold_mechanism.md) is the canonical finding doc. Phase 11 prose should treat this as the fourth and final methodology gap closed in v0.1 (per the §6 taxonomy: 7 methodology items + 2 doc-text items = 9 specification items).

The empirical trigger: in implementing Batch 10A's in-memory sensitivity sweeps, a latent bug in `enrich_with_rankings_volume` was fixed (passing `rankings_json` dict instead of flattened `rankings_df`). Once Tier C volumes flowed correctly, deepseek-v3-2 (the v0.1 panel's sole Tier C constituent) drove TPRR_E `tier_c_weight_share` to 48.8% at base_date — a single-source dependency that violates the methodology's "minimum independent observations" principle.

The methodology resolution: extend the existing contributor → constituent minimum-3 threshold to the constituent → tier layer. A tier with `n_active < 3` is dormant; its blending coefficient redistributes to eligible tiers. Implementation symmetric across `compute_tier_index` (twap-then-weight), `_compute_weight_then_twap_index` (weight-then-twap), and `_recompute_one_day_active` (Phase 10 sensitivity recompute).

**[PUBLICATION-GRADE]** The Phase 11 framing point: this is **not** a v0.1 patch but a structural specification that activates Tier C smoothly as coverage expands. v0.2+ Tier C coverage growth past 3 constituents per index tier triggers automatic activation — no methodology version bump required.

### 2.3 Cumulative cliff-edge resolution at multi-seed × multi-config scale

**[PUBLICATION-GRADE]** The seed-42 trajectory (§1.4) generalises across the tested seed range (DL 2026-05-01 Phase 10 Batch 10C continuation; [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md)). At all 60 seed × config combinations, every seed reports `n_a = 6` at base_date — zero regression to the pre-Phase-7H 0.0012 baseline. Distribution shape is preserved across configs (mean 0.90 → 0.92 → 0.94 across loose / default / tight; std 0.041 → 0.035 → 0.032). Seed 47 produces the maximum at all three configs; seeds 51 and 57 occupy the lower tail at all three configs.

The cliff-edge resolution is **structural across the Phase 7H design space**, not a seed-42 or default-config artefact.

---

## 3. Robustness story (parameter sensitivity)

### 3.1 Headline — three-of-four downstream parameters produce base-date invariance

**[PUBLICATION-GRADE]** [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) is the canonical doc. The cross-sweep finding from Batch 10B:

| Sweep | Range | TPRR_F base_date raw_value variation |
|---|---|---|
| Suspension threshold | 2 / 3 / 5 / 7 days | None (30.2405 invariant) |
| Reinstatement threshold | 5 / 10 / 15 / 20 days | None (30.2405 invariant) |
| TWAP ordering | twap_then_weight vs weight_then_twap | $0.0001/Mtok (essentially zero) |
| Gate threshold | 0.05 / 0.10 / 0.15 / 0.20 / 0.25 / 0.30 | $2.01/Mtok at strict settings, then converges |

Three of four parameters leave TPRR_F base_date raw_value invariant within their swept ranges. The fourth (gate) shifts the level only at strict settings (5%, 10%) below the canonical 15% — and the canonical 15% sits exactly on the convergence edge.

Source: manifest rows 4–7 (`suspension_seed42`, `reinstatement_seed42`, `gate_seed42`, `twap_ordering_seed42`).

### 3.2 Gate threshold is the methodology's highest-leverage parameter

**[PUBLICATION-GRADE]** [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md). The gate is the only parameter in Batch 10B that shifts TPRR_F base_date raw_value, AND it produces the highest intermediate-day sensitivity (TPRR_E 88% of days differ between gate=5% and gate=30%).

Mechanism: the gate sits at the input boundary; every downstream parameter operates on the gate-filtered slot set. Gate exclusion propagates to suspension, reinstatement, TWAP-ordering, and weighting. **The canonical 15% choice represents the loosest gate that doesn't degrade the published level.**

Per-gate `all_pairs_suspended` audit cascades: 64 (5%) → 30 (10%) → 32 (15%) → 32 (20%) → 18 (25%) → 0 (30%). The 5% gate is materially stricter — 2× the suspension cascades of the 15% canonical. The canonical sits comfortably above the strict-gate cliff and well below the no-effect floor.

**[METHODOLOGY-DOC]** v1.3 should formalise: gate-tightening is the principal manipulation-resistance mechanism alongside exponential median-distance weighting, with the gate sitting structurally upstream. Section 4.2.2.

### 3.3 λ non-monotonicity in realised volatility

**[PUBLICATION-GRADE]** [lambda_non_monotonicity_in_realized_vol.md](lambda_non_monotonicity_in_realized_vol.md). Counter-intuitive finding: TPRR_F annualised vol is **non-monotonic in λ** across the swept range.

| Config | λ | Mean vol | Std vol |
|---|---|---:|---:|
| Loose | 2 | 24.8% | 4.6% |
| Default | 3 | 33.4% | 6.7% |
| Tight | 5 | 32.0% | 7.3% |

Vol-minimum sits at λ=2; vol-maximum is between λ=3 and λ=5 (default is the local maximum on the swept range). Mechanism is **hypothesised**, not verified: smoothing effect at lower λ (broader effective constituent set damps single-constituent moves); concentration effect at higher λ (effective set shrinks toward 1–3 near-median constituents, idiosyncratic moves pass through).

**[PUBLICATION-GRADE]** The intuitive narrative ("higher λ → more manipulation resistance, also higher vol from outlier cuts") is **wrong on the realised-vol side** for the v0.1 panel. λ-calibration documentation should not assume monotonic vol/λ relationship.

### 3.4 TWAP-ordering empirical equivalence

**[PUBLICATION-GRADE]** [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md). Two orderings produce $0.0001/Mtok base_date delta on TPRR_F at seed 42 (clean panel) and ≤$1.4445/Mtok max intermediate-day delta — practically equivalent. Phase 11 has two answers to "why TWAP-then-weight?":

1. **Commodity benchmark precedent** — ICE Brent, Henry Hub, ASCI all use TWAP-then-weight (DL 2026-04-30 Phase 7 Batch E)
2. **Empirical equivalence** — on the v0.1 panel, the alternative produces near-identical output, so the choice imposes no informational cost relative to the alternative

The cross-scenario invariance result on F-tier (byte-identical TPRR_F TWAP-ordering deltas across all 7 panels — clean + 6 scenarios) was the single-seed precursor to the cross-config F-tier absorption finding (§4).

### 3.5 Cross-config seed signature stability

**[PUBLICATION-GRADE]** [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md). The methodology produces a stable cross-seed *response structure* across the Phase 7H design space:

- Seed 47 is the maximum at all three configs (fully stable)
- Seeds 51 and 57 occupy the lower tail at all three configs (rank shifts within the tail)
- Constituent-activation pattern (TPRR_F = 6, TPRR_S = 4, TPRR_E ∈ {5, 6}) identical across all 60 combinations
- Audit row counts mean 22,134 / std 117 — byte-identical to four sig figs across configs
- Median 155 suspension intervals / 153 reinstatement events across all three configs

**[PUBLICATION-GRADE]** Two consequences for Phase 11 narrative:

- **Seed 42 is unremarkable, not special.** Sits 0.7σ above the multi-seed mean at default; mid-distribution at loose and tight. Phase 7H Batch D's seed-42 cliff-edge resolution finding (w_a = 0.9261) is empirically representative, not seed-cherry-picked.
- **Phase 7H configs are a robustness band, not three discrete options.** v1.3 canonical methodology lives at default; loose and tight are documented as the empirical envelope within which the methodology behaves stably.

### 3.6 Two-layer Phase 11 framing — published rate vs analyst trajectory

**[PUBLICATION-GRADE]** Combined story from §3.1 + §3.2 + §3.4: the methodology has two layers, and Phase 11 should present them as complementary.

**Scope qualifier**: single-seed parameter sensitivity at seed 42 confirms three of four downstream methodology parameters leave the published level invariant. Multi-seed × parameter-sweep cross-product was not run; Phase 7H design space multi-seed (Batch 10C) confirms cross-seed structural consistency at design-space defaults, providing indirect evidence that parameter robustness extends across seeds. The two-layer story is therefore: single-seed parameter robustness + multi-seed methodology robustness.

- **Reference-rate consumer (CFOs, treasurers, regulators)**: "Three of four downstream methodology parameters leave the published level completely unchanged across reasonable ranges (single-seed evidence at seed 42). The fourth (gate) leaves the level unchanged for any setting at or above the canonical 15%. Multi-seed evidence at the canonical config confirms cross-seed methodology consistency. The published reference rate is not parameter-fragile."
- **Analyst trajectory consumer (researchers, traders, derivative designers)**: "The intermediate-day trajectory is genuinely sensitive to methodology parameters — 20–88% of trajectory days differ across the swept ranges. Suspension and reinstatement parameters drive trajectory variation that smooths out by base_date but is visible day-to-day."

Both framings are simultaneously true. The two-layer story is the central institutional-grade narrative for the parameter-sensitivity section.

§4 below extends this into a three-regime story by adding scenario absorption.

---

## 4. Manipulation resistance story (capstone)

### 4.1 Headline — F-tier byte-identical absorption across the Phase 7H design space

**[PUBLICATION-GRADE]** [f_tier_scenario_absorption_methodology_level.md](f_tier_scenario_absorption_methodology_level.md). This is the **headline manipulation-resistance result for Phase 11**.

> **3 configs × 20 seeds × 6 scenarios × 366 days = 131,760 F-tier daily datapoints, every one byte-identical to the corresponding clean-panel value.**

Maximum F-tier trajectory delta across the entire cross-product is ≤ 1.4×10⁻¹⁴ (machine-epsilon float arithmetic noise). Verified across the Phase 7H continuous-blending design space: λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, blending coefficients held canonical.

Source: manifest rows 11–13 (`multi_seed_default_seed42-61_with_scenarios`, `multi_seed_loose_seed42-61_with_scenarios`, `multi_seed_tight_seed42-61_with_scenarios`).

### 4.2 Per-tier asymmetry — config-invariant response signature

**[PUBLICATION-GRADE]** Per-tier scenario response signature is essentially constant across configs:

| Tier | Default | Loose | Tight | Pattern |
|---|---:|---:|---:|---|
| TPRR_F | 0 / 120 pairs | 0 / 120 | 0 / 120 | 100% absorption, 0/6 scenarios produce variation |
| TPRR_S | 59 / 120 | 58 / 120 | 58 / 120 | 4/6 scenarios produce variation (sustained_manipulation, correlated_blackout, intraday_spike, fat_finger_high) |
| TPRR_E | 60 / 120 | 60 / 120 | 60 / 120 | 3/6 scenarios produce variation (correlated_blackout, shock_price_cut, stale_quote) |

Same scenario set produces variation in S-tier and E-tier across all three configs. Per-scenario seed-counts differ by at most 1 across configs (intraday_spike S-tier: 13 → 12 → 12). Max abs deltas vary modestly (~10–20% per cell).

### 4.3 Mechanism — upstream vs downstream parameter regime distinction

**[PUBLICATION-GRADE]** Phase 11 should articulate the upstream/downstream split explicitly. The methodology has two parameter regimes operating at different points in the pipeline:

- **Upstream (filtering layer)**: slot-level gate (15% / 5-day trailing average), minimum-3-contributors-per-constituent threshold, suspension/reinstatement policy. Operates on raw slot-level prices before aggregation.
- **Downstream (aggregation layer)**: λ, Tier B haircut, blending coefficients, within-tier-share normalisation. Operates on already-filtered signals.

The Phase 7H continuous-blending parameters swept (λ, Tier B haircut, blending coefficients) are all downstream. The gate-cascade + minimum-3 + suspension policy filter scenario perturbations *before* they reach the blending step. Downstream parameters redistribute weight on surviving signals; they cannot reintroduce filtered-out signals. This is why scenario absorption is invariant to the swept Phase 7H configs.

The F-tier's structural advantage rests on three properties combining at the upstream layer: (1) constituent redundancy (6 constituents), (2) contributor redundancy per constituent (≥3 contributors), (3) gate-cascade absorption pre-aggregation. Perturbations pass through three filtering layers before reaching the dual-weighted formula: slot-level gate exclusion (catches outlier prices), contributor-pair suspension (catches sustained gate firings), and constituent activation threshold (≥3 contributors per constituent). Each layer filters at a different aggregation step; together they produce the structural F-tier absorption.

### 4.4 Scope of the structural claim

**[PUBLICATION-GRADE]** Phase 11 prose must be precise about scope to earn institutional credibility. The absorption claim is:

- **Structural with respect to the Phase 7H continuous-blending design space**: λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}. Verified within the swept envelope.
- **Not** structural with respect to upstream parameters (gate threshold, minimum-3, suspension policy). Batch 10B's gate threshold sweep confirms strict gate settings shift TPRR-F base_date materially. The cross-product of gate × scenarios × seeds was **not run** as part of Phase 10. Scenario × upstream-parameter interaction is uncharacterised.

### 4.5 Acknowledged calibration — v0.1 scenario suite specifically

**[PUBLICATION-GRADE]** The byte-identical result is consistent with the methodology being well-tuned to the specific failure modes the v0.1 scenario suite was designed to test. The scenarios were authored alongside the methodology, with the gate-and-suspension mechanisms in mind. They target perturbation patterns the gate is designed to catch.

The finding demonstrates that **the methodology absorbs the v0.1 scenarios it was designed to absorb**, invariantly across the Phase 7H downstream design space. It does not yet demonstrate absorption of:

- Compromised contributor scenarios (extended-window manipulation, sub-gate price drift)
- Simultaneous multi-tier coordinated attacks
- Slowly evolving manipulation (cumulative drift below gate)
- Volume-share manipulation (attack on within-tier-share rather than price)
- Adversarial scenarios authored independently by a red team

These are v1.3+ items.

### 4.6 Recommended Phase 11 framing — overclaim vs underclaim

**[PUBLICATION-GRADE]** Three framings calibrated for institutional reviewers:

**Recommended**: "Across the Phase 7H continuous-blending design space (λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, 60 seed × config combinations), 6 v0.1 scenarios, and the full 366-day backtest, TPRR-F produces byte-identical output to the corresponding clean panels at every day. The dual-weighted formula combined with the slot-level gate, three-tier hierarchy, and minimum-3-constituents requirement absorbs the v0.1 scenario suite completely on the F-tier index, invariantly to the downstream blending parameters."

**Discouraged**: "TPRR is impervious to manipulation" (overstates: scope is the v0.1 suite at swept Phase 7H design points). "F-tier absorption holds across all parameter values" (overstates: verified within Phase 7H envelope; upstream not swept against scenarios).

The precise framing earns credibility; the imprecise framing invites push-back ("what about a 5% gate?", "what about a compromised contributor?"). Phase 11 author should resist any temptation to lift only the headline 131,760-datapoint figure without the scope clauses.

### 4.7 Three-regime distinction (with cross-config evidence)

**[PUBLICATION-GRADE]** Combining §3.6's two-layer framing with §4 yields a three-regime distinction:

- **Parameter sweeps (Batch 10B)**: published-rate robust (3 of 4 dimensions), trajectory sensitive (all 4) — the two-layer story
- **F-tier scenario sweeps (Batch 10C, 3 configs × 20 seeds × 6 scenarios)**: both robust at every day — the absorption story, structural across the Phase 7H downstream design space
- **S/E-tier scenario sweeps (Batch 10C)**: published-rate robust, trajectory variation under specific scenarios with config-invariant per-scenario response signature — the two-layer story holds in attenuated form, with the specific tier × scenario response pattern itself empirically established as a methodology property

Phase 11's manipulation-resistance section should distinguish all three regimes. This is the most publishable scope-precise framing the validation has produced.

---

## 5. Data quality story (three-tier hierarchy)

### 5.1 Three-tier bias profiles framing

**[PUBLICATION-GRADE]** [DL 2026-05-01 Three-tier hierarchy bias profiles entry](../decision_log.md#L1201). Phase 11 should frame the three-tier hierarchy not as "use the highest-confidence signal" but as **"triangulate across three signals with distinct bias profiles, none unbiased, but each capturing a different slice of the market"**.

| Tier | Bias direction | Bias magnitude | Strength | Limitation |
|---|---|---|---|---|
| Tier A | Enterprise-segment overweight, smaller-customer underrepresented | Calibrated to plausible enterprise mix in v0.1 | Highest precision on enterprise spend; direct attestation; auditable | Structural sample of enterprise users only; v0.1 panel size of 10 is artificially small |
| Tier B | Upward bias from non-API revenue inclusion; flat-rate Enterprise tiers | Plausibly 30–50% upward (basis for 0.5 haircut) | Whole-provider scope; auditable revenue data for public companies | Revenue-to-volume chain compounds bias; private-company revenue requires triangulation |
| Tier C | Developer/researcher-segment overweight; cost-efficiency-seeking user base; potential APAC/open-source overweight | Empirical: top-9 snapshot showed 8/9 from non-registry providers | Direct third-party measurement; no provider influence | Small slice of total enterprise inference market; v0.1 only ingested top-9 rankings |

**[PUBLICATION-GRADE]** Combined rationale for Phase 11: "No single tier is unbiased. The three-tier hierarchy works precisely BECAUSE it triangulates across sources with different bias profiles. A finding that emerges across all three tiers is more robust than one supported by only one tier; a divergence across tiers signals data-quality investigation rather than methodology failure. This is consistent with mature commodity benchmark practice."

### 5.2 Tier-eligibility threshold formalises the minimum-observation principle

**[METHODOLOGY-DOC]** [tier_eligibility_threshold_mechanism.md](tier_eligibility_threshold_mechanism.md). The threshold extends the existing contributor → constituent minimum-3 to the constituent → tier layer. Both layers now apply the same epistemic principle: ≥3 independent observations required at every aggregation step.

**[PUBLICATION-GRADE]** Phase 11 narrative: the methodology has a single eligibility rule that applies at every aggregation layer. In v0.1 Tier C has 1 constituent, fails the rule, is dormant. In v0.2+ as coverage expands past 3 Tier C constituents per index tier, Tier C activates automatically. **The threshold formalises Tier C dormancy as smooth-activation behaviour, not a v0.1 limitation.** This positions the methodology favourably for the v0.1 → v0.2 question institutional reviewers will ask.

### 5.3 v0.1 Tier C dormant; v0.2+ activates organically

**[PUBLICATION-GRADE]** From [tier_eligibility_threshold_mechanism.md](tier_eligibility_threshold_mechanism.md):

- **v0.1**: deepseek-v3-2 is the only Tier C panel constituent → fails threshold → Tier C dormant → coefficient redistributes to Tier A and Tier B → published level identical to a no-Tier-C methodology
- **v0.2+**: when ≥3 Tier C constituents exist for any tier (TPRR_F / TPRR_S / TPRR_E), Tier C activates automatically — no methodology version bump

Audit rows for the dormant tier's constituents are preserved with `coefficient=0`, `w_vol_contribution=0`, `included=True` — visible to auditors as "evaluated but excluded from blending." Reproducibility preserved.

### 5.4 Triangulation as methodology design

**[PUBLICATION-GRADE]** Phase 11 framing implications from [DL 2026-05-01](../decision_log.md#L1233):

- Frame Tier C's structural limitations as "designed signal, not failed primary source"
- Frame Tier B's bias profile as "imprecise but interpretable, with confidence haircut calibrated accordingly"
- Frame Tier A's bias as "enterprise sample bias, the best available but not unbiased"
- The cliff-edge resolution (§1.4, §2.3) is then framed as: "the methodology gracefully handles cross-tier triangulation when no single tier dominates by magnitude, producing stable index dynamics that reflect signal-weighted consensus rather than any single source"

---

## 6. v1.3 specification gaps consolidated

9 specification items surfaced through Phase 7H + Phase 10 validation, per DL 2026-05-01 Phase 10 Batch 10A entry. Split into two categories:

- **Methodology gaps (7)**: items requiring methodology refinement
- **Documentation gaps (2)**: items requiring methodology spec doc text updates (Phase 11 deliverable; implementation already correct)

### Methodology gaps — implemented in v0.1 (4 of 7)

1. **Cliff-edge dynamics under priority fall-through** — resolved by continuous blending (Phase 7H Batch B). DL 2026-04-30 Phase 7H methodology design + Batch B audit trail. Empirical resolution: TPRR_F base_date `tier_a_weight_share` 0.0012 → 0.6980 just from the Batch B step.

2. **Cross-tier magnitude commensurability** — resolved by within-tier-share normalisation (Phase 7H Batch A). DL 2026-04-30 Phase 7H Batch A. Empirical resolution: 0.0012 → 0.5083 from Batch A alone.

3. **One-way suspension ratchet** — resolved by bidirectional reinstatement (Phase 7H Batch D). DL 2026-04-30 Phase 7H Batch D + DL 2026-04-30 suspension reinstatement gap entry. Empirical resolution: enables full F-tier reactivation by base_date (n_a = 6).

4. **Tier-eligibility threshold for continuous blending** — resolved by ≥3-constituents-per-tier minimum (Phase 10 Batch 10A). DL 2026-05-01 Batch 10A. Single-Tier-C-constituent dominance (TPRR_E `tier_c_weight_share` 0.4883 → 0.0000). Smooth activation as Tier C coverage expands in v0.2+.

### Methodology gaps — queued for v1.3 (3 of 7)

5. **Tier B confidence calibration refinement**. v0.1 implements 0.5 haircut (Phase 7H Batch C); the *value* is implemented but the calibration would benefit from real-data validation. v1.3 follow-up: provider-disclosed API token volumes (replaces API_share assumption with measurement); subscription-tier carve-outs in audited revenue (replaces analyst-triangulation top-line); Enterprise-flat-rate detection (corrects per-token rate inference). DL 2026-04-30 Phase 7H Batch C.

6. **Tier B revenue derivation chain — bias profile expansion**. v0.1 documents the 4-step compounding bias chain (provider revenue × API_share × OpenRouter split ÷ reference price). v1.3 follow-up: track temporal drift in API_share assumptions; document Enterprise-mix sensitivity per provider; add per-constituent Tier B confidence scoring rather than single 0.5 haircut. DL 2026-04-30 Phase 7H Batch C bias-chain section.

7. **v0.1 Tier C coverage sparseness** — structural. 1 of 16 constituents in v0.1 (deepseek-v3-2 alone). v0.2+ remediation: ingest OpenRouter full models endpoint instead of top-9 rankings; add complementary third-party data sources (industry surveys, developer platform analytics). DL 2026-04-29 Phase 4 close-out.

### Documentation gaps — Phase 11 spec doc rewrite (2)

8. **Continuous blending price-aggregation formal documentation**. v0.1 implements coefficient × tier_price symmetric with volume per the post-design addendum (DL 2026-04-30 Phase 7H Batch B addendum). v1.3 spec doc rewrite needs to formalise the symmetric coefficient application for both volume and price contributions. Implementation already correct; the spec text is the gap.

9. **Three-tier hierarchy bias profile formal documentation**. v0.1 documents bias profiles in DL 2026-05-01. v1.3 spec doc rewrite needs to fold these into the methodology section as the canonical framing for the hierarchy.

**[PUBLICATION-GRADE]** Phase 11 should present this taxonomy explicitly: 7 methodology items (4 implemented in v0.1, 3 queued for v1.3) plus 2 documentation items (both Phase 11 spec-rewrite deliverables). The completion ratio is itself a story — the load-bearing methodology gaps closed in v0.1, specifications articulated for the rest, and the spec-doc text refresh scoped explicitly as Phase 11 deliverable rather than carried forward as ambiguous "v1.3 work."

---

## 7. Limitations and future work

### 7.1 v0.1 synthetic panel constraints

**[PUBLICATION-GRADE]** Phase 11 prose should acknowledge each limitation distinctly:

- **10 contributors × 16 constituents synthetic panel**, calibrated to plausible 2025 enterprise prices. Real production deployment requires real contributor billing data ingested via Tier A panel infrastructure.
- **Deterministic at seed**: 20-seed multi-seed validation is the dispersion measurement; tighter cross-seed dispersion expected on real provider price history (Brent's vol-of-vol over 1-year window is typically 2–3% vs synthetic panel's 6.7% std dev at default).
- **Tier B revenue inputs from `config/tier_b_revenue.yaml`**: analyst-triangulation point estimates per quarter. Real production deployment requires audited disclosed revenue with subscription-tier carve-outs.

### 7.2 v0.1 scenario suite scope

**[PUBLICATION-GRADE]** §4.5 documented this in the F-tier absorption section. v0.1 has 6 scenarios authored alongside the methodology. v1.3 expansion needed for:

- Compromised contributor (extended-window manipulation, sub-gate price drift)
- Simultaneous multi-tier coordinated attacks
- Slowly evolving manipulation (cumulative drift below 15% gate)
- Volume-share manipulation (attack on within-tier-share rather than price)
- Adversarial scenarios authored independently by a red team

### 7.3 Tier C coverage in v0.1

**[PUBLICATION-GRADE]** 1 of 16 constituents (deepseek-v3-2) covered in v0.1. v0.2+ activates organically per §5.3. Phase 11 prose should frame Tier C's v0.1 dormancy as designed behaviour rather than data-quality failure — the tier-eligibility threshold ensures the methodology does not produce single-source dependencies as coverage expands.

### 7.4 Tier B revenue-attribution challenges

**[PUBLICATION-GRADE]** Bias chain documented in DL 2026-04-30 Phase 7H Batch C bias-chain section. Four compounding sources of bias: top-line revenue includes non-API; API_share is point estimate; "API revenue" includes flat-rate Enterprise tiers; within-provider attribution uses synthetic priors. The 0.5 haircut reflects this; v1.3 should refine value with better data inputs (§6 gap #5).

### 7.5 Real-data validation pathway

**[PUBLICATION-GRADE]** Phase 11 should articulate the pathway from v0.1 (synthetic panel) to v1.0 (production publication):

- **v0.2+**: expanded Tier C via OpenRouter full models endpoint; complementary third-party data sources
- **v0.3+**: real Tier A contributor panel onboarding (one or more anchor contributors with audited billing data feed)
- **v1.0**: production publication with full real-data three-tier hierarchy; backfill to a meaningfully-anchored historical base date (likely GPT-4 API launch, March 2023, per DL 2026-05-01 base date convention) using Wayback Machine API archives + analyst reports + customer-leaked rate cards

### 7.6 Cross-product not run — gate × scenarios × seeds

**[PUBLICATION-GRADE]** Per §4.4. Batch 10C scope was the Phase 7H downstream design space; gate is upstream. Whether F-tier absorption holds at gate ≠ 15% is uncharacterised. v1.3+ work item; reference [f_tier_scenario_absorption_methodology_level.md](f_tier_scenario_absorption_methodology_level.md) §"v1.3 specification implications" item 1.

### 7.7 Methodology specification document gap

**[METHODOLOGY-DOC]** The canonical [docs/tprr_methodology.md](../tprr_methodology.md) has not been updated to reflect Phase 7H + Phase 10A modifications. The decision log captures the design rationale across DL 2026-04-30 Phase 7H entries + DL 2026-05-01 Batch 10A; the methodology spec itself still reflects pre-Phase-7H literal canonical Section 3.3.2.

**This gap encompasses the 2 documentation items from §6's taxonomy** (continuous blending price-aggregation formal documentation; three-tier hierarchy bias profile formal documentation), plus the broader rewrite needed to fold the four Phase 7H batches and the tier-eligibility threshold into the canonical methodology sections (3.3.2, 3.3.3, 4.2.2, 4.2.4).

**Deferred to Phase 11**. The methodology doc rewrite is part of Phase 11 publication preparation; this synthesis flags the gap explicitly so it doesn't get missed.

---

## 8. Conclusion — validation arc summary

**[PUBLICATION-GRADE]** The validation arc, in three sentences for Phase 11:

> The TPRR research question — does the dual-weighted formula combined with the three-tier volume hierarchy produce a stable, credible, manipulation-resistant index — was answered "no" under literal canonical Section 3.3.2 priority fall-through, which produced cliff-edge dynamics at the v0.1 cross-tier magnitude gap. We proposed and implemented modified methodology in Phase 7H (within-tier-share normalisation, continuous blending, Tier B haircut recalibration, symmetric suspension reinstatement) plus a tier-eligibility threshold in Phase 10A, and tested whether the modified methodology produces the index the research question asks about. Across 13 sensitivity sweeps, 60 seed × Phase 7H-config combinations, 6 v0.1 scenarios, and the full 366-day backtest, the modified methodology produces (a) cliff-edge resolution at every config × seed combination, (b) base-date robustness to three of four downstream parameters with the canonical fourth (gate at 15%) sitting on the convergence edge, and (c) byte-identical F-tier scenario absorption across the Phase 7H continuous-blending design space — 131,760 daily datapoints, every one identical to clean.

**Phase 11 publication readiness**:

- Headline manipulation-resistance result (§4) — established at methodology level across the Phase 7H design space
- Two-layer / three-regime parameter sensitivity story (§3.6, §4.7) — empirically documented
- Methodology refinement arc (§1.4, §2) — documented through DL 2026-04-30 Phase 7H entries + DL 2026-05-01 Batch 10A entry
- Three-tier hierarchy bias profile framing (§5) — documented in DL 2026-05-01 entry, ready for Phase 11 prose
- v1.3 specification items list (§6) — 9 specification items (7 methodology + 2 doc-text); 4 of 7 methodology gaps implemented in v0.1, 3 queued for v1.3, 2 doc-text items scoped explicitly as Phase 11 spec-rewrite deliverable

**Outstanding for Phase 11**:

- Methodology specification document rewrite (folds Phase 7H + Phase 10A modifications into the canonical methodology doc; §7.7)
- Phase 11 publication prose itself — lift [PUBLICATION-GRADE] tagged content forward, expand into institutional-audience prose, weave in [AUDIT-TRAIL] cross-references where reviewers will probe scope
- Optional: gate × scenarios × seeds cross-product if added to scope (Phase 11 author judgment call; current absorption claim's scope clauses cover the gap)

**Build status going into Phase 11**: 13 sensitivity sweeps committed and reproducible (manifest at [data/indices/sweeps/manifest.csv](../../data/indices/sweeps/manifest.csv)); 7 standalone Phase 10 finding docs + this synthesis (8 total Phase 10 docs); 711 tests passing, mypy strict clean on src/, ruff clean.

---

## Cross-references

This synthesis aggregates content from:

- 7 Phase 10 finding docs in [docs/findings/](.):
  - [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md)
  - [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md)
  - [f_tier_scenario_absorption_methodology_level.md](f_tier_scenario_absorption_methodology_level.md)
  - [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md)
  - [lambda_non_monotonicity_in_realized_vol.md](lambda_non_monotonicity_in_realized_vol.md)
  - [tier_eligibility_threshold_mechanism.md](tier_eligibility_threshold_mechanism.md)
  - [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md)

- Decision log entries:
  - DL 2026-04-30 Phase 7H methodology design (the four-change rationale)
  - DL 2026-04-30 Phase 7H Batches A / B / C / D (each refinement)
  - DL 2026-04-30 Phase 9 close-out (cumulative empirical resolution)
  - DL 2026-05-01 base date convention (rebase semantics)
  - DL 2026-05-01 three-tier bias profiles (Phase 11 framing)
  - DL 2026-05-01 Phase 10 Batch 10A (tier-eligibility threshold + ninth gap)
  - DL 2026-05-01 Phase 10 Batch 10B (single-seed pipeline-rerun sweeps)
  - DL 2026-05-01 Phase 10 Batch 10C partial + continuation (multi-seed)
  - DL 2026-05-05 Phase 10 Batch 10C final (cross-config scenarios)
  - DL 2026-05-05 Phase 10 close-out (this batch's audit-trail companion)

- Sweep parquets in [data/indices/sweeps/](../../data/indices/sweeps/) — 13 sweeps catalogued in [manifest.csv](../../data/indices/sweeps/manifest.csv).

- Methodology document [docs/tprr_methodology.md](../tprr_methodology.md) (canonical; Phase 11 rewrite pending).
