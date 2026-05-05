# Findings

Index of TPRR MVP findings. Each finding is a standalone document — a reader should
be able to pick up any one during a VC or contributor call without prior context.

Findings are produced primarily in Phase 10 (scenarios, λ sweep, haircut sweep, TWAP
ordering comparison) and any exploratory work that surfaces something publishable.

## Phase 2 — Pricing Model Design

- [pricing_model_design.md](pricing_model_design.md) — Phase 2a/2b layering rationale
  (bidirectional dynamics, baseline frequency / magnitude / drift, ChangeEvent
  materialisation, cross-provider correlation deferral)
- [seed_42_baseline_characteristics.md](seed_42_baseline_characteristics.md) —
  forensic record of what the baseline generator produces on seed 42 (per-tier
  step-event totals, per-model distribution, day-level clustering)

## Phase 10 — Sensitivity / Validation

- [lambda_non_monotonicity_in_realized_vol.md](lambda_non_monotonicity_in_realized_vol.md) —
  TPRR_F annualised vol is non-monotonic in λ (24.8% / 33.4% / 32.0% at λ=2/3/5
  across 20 seeds); vol-min not at either extreme
- [tier_eligibility_threshold_mechanism.md](tier_eligibility_threshold_mechanism.md) —
  Min-3 threshold extends the methodology's minimum-independent-observations
  principle from contributor → constituent layer to constituent → tier layer;
  v0.1 Tier C dormant, v0.2+ activates organically
- [gate_threshold_most_consequential_parameter.md](gate_threshold_most_consequential_parameter.md) —
  Slot-level data quality gate is the highest-leverage methodology parameter;
  only Batch 10B sweep dimension that shifts TPRR_F base_date raw_value
- [twap_ordering_empirical_equivalence.md](twap_ordering_empirical_equivalence.md) —
  TWAP-then-weight vs weight-then-TWAP produce $0.0001/Mtok base-date delta
  on clean panel; canonical choice empirically defended in addition to
  commodity-benchmark precedent
- [base_date_convergence_with_trajectory_sensitivity.md](base_date_convergence_with_trajectory_sensitivity.md) —
  Three of four Batch 10B sweeps leave TPRR_F base_date invariant; all four
  produce 51–88% intermediate-day trajectory variation. Two-layer Phase 11
  framing (published-rate robustness + analyst trajectory sensitivity)
- [cross_config_seed_signature_stability.md](cross_config_seed_signature_stability.md) —
  Same seeds occupy distribution tails across loose / default / tight configs;
  methodology cross-seed response structure is config-invariant
- [f_tier_scenario_absorption_methodology_level.md](f_tier_scenario_absorption_methodology_level.md) —
  TPRR-F absorbs the v0.1 scenario suite completely across the Phase 7H
  continuous-blending design space (3 configs × 20 seeds × 6 scenarios × 366
  days = 131,760 F-tier daily datapoints, every one byte-identical to clean);
  per-scenario S/E-tier response signatures (4/6 and 3/6) invariant across configs.
  Headline result for Phase 11 manipulation-resistance section
