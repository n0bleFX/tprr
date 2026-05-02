# λ Non-Monotonicity in Realised Volatility

**Source**: Phase 10 Batch 10C continuation — multi-seed sweeps at default / loose / tight Phase 7H configs across seeds 42–61.

**Status**: Empirical finding. Worth Phase 11 surfacing because it contradicts the intuition that higher median-distance λ monotonically tightens or loosens the index trajectory.

## Finding

TPRR_F annualised volatility (day-over-day log returns × √252) is **non-monotonic in λ** across the swept Phase 7H design space. Vol-mean across 20 seeds is 24.8% at λ=2 (loose), 33.4% at λ=3 (default), and 32.0% at λ=5 (tight). The vol-minimum is not at either extreme — moderate-λ produces the highest realised vol, with both lower and higher λ reducing it.

## Empirical evidence

| Config | λ | Tier B haircut | Mean vol | Std vol | Min | Max | P5 | P95 |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Loose | 2 | 0.6 | **24.8%** | 4.6% | 18.3% | 34.3% | 19.1% | 32.9% |
| Default | 3 | 0.5 | **33.4%** | 6.7% | 23.4% | 46.6% | 25.6% | 45.6% |
| Tight | 5 | 0.4 | **32.0%** | 7.3% | 20.6% | 46.6% | 21.1% | 42.8% |

Source parquets: [multi_seed_loose_seed42-61.parquet](../../data/indices/sweeps/multi_seed/multi_seed_loose_seed42-61.parquet), [multi_seed_default_seed42-61.parquet](../../data/indices/sweeps/multi_seed/multi_seed_default_seed42-61.parquet), [multi_seed_tight_seed42-61.parquet](../../data/indices/sweeps/multi_seed/multi_seed_tight_seed42-61.parquet).

The non-monotonicity is robust to the seed range:
- **Per-seed minimum vol** sits at λ=2 for all 20 seeds (loose dominates the lower envelope)
- **Per-seed maximum vol** is split between λ=3 and λ=5 — neither config dominates the upper envelope

## Mechanism (hypothesized)

The non-monotonic empirical pattern is observed; the mechanism explanation below is a working hypothesis grounded in how exponential median-distance weighting interacts with finite constituent sets, but has not been independently verified through targeted experiment. Verification is queued for v1.3 specification work.

Two competing effects plausibly drive the relationship between λ and realised vol:

1. **Smoothing effect (lower-λ side)**: at λ=2, the median-distance weighting is gentle. Constituents at ±20% of median still receive 67% of full weight; constituents at ±50% still receive 37%. The aggregation effectively averages across a broad constituent set, which damps any single-constituent move into the index trajectory. Lower λ → more averaging → smoother trajectory → lower realised vol.

2. **Concentration effect (higher-λ side)**: at λ=5, weights drop sharply. ±20% of median gets 36% weight, ±50% gets 8%. The effective constituent set shrinks toward the 1–3 constituents nearest the median. With fewer contributing constituents, idiosyncratic price moves of those near-median constituents pass through to the index without absorption. Higher λ → fewer effective constituents → less averaging → can re-elevate vol.

The two effects cross over somewhere in the middle of the swept range. Default λ=3 happens to sit at or near the local maximum on this design space — both mechanisms are active but neither dominates, leaving the broadest set of constituents contributing meaningfully with enough weight discrimination to retain idiosyncratic move pass-through.

This is **not** a methodology bug; it's an emergent property of exponential median-distance weighting interacting with a finite (n=6) F-tier constituent set.

## Phase 11 narrative implication

The non-monotonicity changes how Noble should communicate λ calibration to institutional reviewers. The default narrative ("higher λ → more manipulation resistance, but also more vol because outliers get cut") needs amendment:

- **Manipulation resistance does increase monotonically with λ** (Phase 10 Batch 10A's lambda sweep at fixed seed 42 confirmed this).
- **Realised vol does not** — it can decrease at the high-λ end because the effective constituent set shrinks.

Phase 11 narrative: "λ tunes the trade-off between manipulation resistance and effective constituent breadth. At λ=2, the index averages across the broadest constituent set with low realised vol. At λ=5, the index becomes more concentrated near the median price with elevated weight discrimination but fewer effective contributors. λ=3 (the canonical choice) sits at the empirical vol peak on the v0.1 design space — chosen for the manipulation-resistance / breadth balance, not for vol minimisation."

This is also a useful **counter-intuitive** finding to surface in conversations with institutional reviewers — it demonstrates Noble has empirically characterised the design space rather than chosen λ by analogy.

## v1.3 specification implication

λ-calibration documentation in the v1.3 methodology specification should:

1. Include the cross-seed vol distribution at each candidate λ (this finding's table) rather than a single seed's vol point estimate.
2. State explicitly that vol is non-monotonic in λ across the empirically-relevant range — committee or Index Committee members should not infer "higher λ → higher vol" or vice versa from intuition.
3. Note that the local vol maximum (~λ=3) coincides with the canonical choice; the choice is defended on manipulation-resistance/breadth grounds, not vol grounds.

This finding also informs the v1.3 sensitivity-sweep documentation pattern: parameter sensitivity should always be reported across multiple seeds, not at a fixed seed, because non-monotonic empirical effects can shift across panel realisations.

## Cross-references

- DL 2026-05-01 Phase 10 Batch 10A — lambda sweep at fixed seed 42 (in-sample sensitivity baseline)
- DL 2026-05-01 Phase 10 Batch 10C (this continuation, append entry) — multi-seed cross-config evidence
- Methodology section 3.3.3 — exponential median-distance weighting; canonical λ=3
- [seed_42_baseline_characteristics.md](seed_42_baseline_characteristics.md) — single-seed forensic baseline (factors out seed-specific artifacts from this cross-seed finding)
