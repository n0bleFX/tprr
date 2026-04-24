# Pricing Model Design — Phase 2a Baseline Generator

**Status**: Pre-implementation design rationale. Validates choices before code lands.
**Scope**: Phase 2a daily baseline prices. Phase 2b intraday change events sit on top.

## Thesis alignment

Noble's product thesis is that AI inference pricing evolves toward commodity
free-float dynamics — bidirectional intraday volatility around trend, step-ups
(version launches, supply constraints, premium pricing) as well as step-downs,
and periods of trendless noise as the market discovers fair value. The TPRR
methodology is being built for that regime, not for the current era's mostly-
declining pattern. The Phase 2a synthetic panel must therefore exercise both
directions of price movement; a unidirectional cuts-only model would let
methodology bugs through that production-era data would expose. Bidirectional
drift volatility plus bidirectional step events are baked into the v0.1
generator for this reason.

## What this layer produces

For each (model, date) over the 480-day backtest window, a single output and
input price. Two stochastic components combine:

1. **Step events** — discrete price moves on specific days, predominantly down
   but with material upward moves (75/25 down/up).
2. **Daily drift** — Gaussian per-day return with negative mean and tier-scaled
   volatility. Bidirectional.

Contributor-level noise enters in Phase 2a.2 (not here). Intraday slot-level
moves enter in Phase 2b.

## Frequency model — independent Poisson per (model)

| Tier | Poisson rate (per year) | Expected count over 480 days | Avg interval |
|---|---:|---:|---:|
| F | 3.0 | ~4 | ~120 days |
| S | 4.0 | ~5 | ~90 days |
| E | 5.0 | ~7 | ~75 days |

project_plan.md 2a says Frontier "every 90–180 days" → 2–4/yr; centred at 3/yr.
project_plan 2b's higher frequencies (4–6, 6–10, 10–20/yr) are for INTRADAY
contributor-level change events — a superset of these baseline step events.

Pure Poisson per (model). No artificial clustering imposed; random clustering
arises naturally from the process. Independent across providers (see
correlation section).

## Magnitude model — bidirectional, uniform within tier

Each step event is bidirectional: 75% probability step-down, 25% probability
step-up. Magnitudes drawn uniform within tier ranges:

| Tier | Step-down range | Step-up range | Mean down | Mean up |
|---|---|---|---:|---:|
| F | 10–25% | +8 to +20% | 17.5% | 14% |
| S | 12–25% | +5 to +15% | 18.5% | 10% |
| E | 20–35% | +5 to +12% | 27.5% | 8.5% |

Step-ups model real-world dynamics absent from a cuts-only generator: version
launches at premium pricing (e.g. Claude Opus pricing held at $75/Mtok output
across multiple version cycles), supply-constrained periods that allow price
firming, and premium-pricing strategies in newly-defended capability tiers.
The 75/25 down/up split reflects an expected continuation of net downward
trend without precluding upward moves.

Down ranges narrowed from initial proposal (S 15–30 → 12–25, E 20–40 → 20–35)
to make room for step-ups in the bidirectional model without runaway decline.

## Daily drift — Gaussian with tier-scaled volatility

Per-day return drawn from `Normal(μ, σ)`, then `price[t+1] = price[t] × (1 + return)`.

| Tier | μ (mean daily return) | σ (daily vol) | Annualised vol |
|---|---:|---:|---:|
| F | -0.005%/day | 0.15%/day | ~2.4% |
| S | -0.010%/day | 0.25%/day | ~4.0% |
| E | -0.015%/day | 0.40%/day | ~6.4% |

Negative mean preserves long-run downward drift. Tier-scaled σ produces
genuinely bidirectional day-to-day moves; on any given day each tier's price
can drift up or down. Per (model, date) seeding ensures determinism.

The σ values are calibrated so that day-to-day noise is visibly bidirectional
without overwhelming the step-event signal. Frontier σ ≈ 0.15%/day means
within-tier daily moves of typically ±10 bps; Efficiency at ±40 bps. This
matches an intuition that lower-tier models have noisier marginal pricing.

## Cross-provider correlation — independent in v0.1

Real-world AI inference pricing exhibits competitive response: OpenAI cuts →
Anthropic / Google respond within 30–90 days. The Aug 2024 GPT-4o price cut
was followed by Sonnet 3.5 pricing adjustments and Gemini Flash repricings
over the subsequent quarter.

For v0.1, step events are **independent across providers**. Reasoning:
- Independent Poisson produces enough random clustering to exercise the index.
- Methodology must work under both correlated and independent moves.
- Phase 10 manipulation scenarios test specific extreme cases that don't
  depend on competitive response.

Flagged as **v0.2 enhancement**: induce competitive response by elevating
same-tier rates for 60 days following any step event. Defer until Phase 10
findings indicate it matters.

## Realism check — 1000-path Monte Carlo simulation

Per-tier final-price distribution after 480 days, simulated 1000 paths starting
from `price = 1.0`, seed 42, using the parameters above:

| Tier | p10 final | p50 final | p90 final | Mean | Paths < 5% of start |
|---|---:|---:|---:|---:|---:|
| F | 0.378 | 0.634 | **0.989** | 0.665 | 0 / 1000 |
| S | 0.271 | 0.495 | 0.821 | 0.520 | 0 / 1000 |
| E | 0.082 | 0.227 | 0.524 | 0.273 | 40 / 1000 |

Read:
- **Frontier** — median 37% decline, but **p90 at 0.989** means ~10% of paths
  stay essentially flat across 480 days. Healthy bidirectional dispersion;
  matches "Frontier pricing can hold or recover."
- **Standard** — median 50% decline, p90 18% decline, p10 73% decline. Wide
  distribution, all paths positive.
- **Efficiency** — median 77% decline. Aggressive but plausible for the
  commoditising tier. **40 paths (4%) end below 5% of starting price** — the
  blow-up tail. With 6 E-tier constituents in the registry running independent
  random seeds, joint blow-up of all six is negligible (~10⁻⁹), so the tier
  index won't blow up; but individual constituents may approach implausibly
  low absolute prices on a small minority of seeds. The methodology should
  handle this — these constituents simply get faded by the exponential weight
  as they pull away from the tier median.

## Methodology references

- **Section 3.2** (tier classification) — defines tiers by capability and
  pricing thresholds; does not prescribe price dynamics, leaving this layer's
  design to MVP.
- **Section 3.3.3** (exponential median-distance weighting) — design must
  produce within-tier dispersion that exercises w_exp at λ=3 across the
  backtest. Bidirectional moves widen the distribution exercised.
- **Phase 4 OpenRouter integration** (deferred): actual snapshots will allow
  validating baseline magnitudes and frequencies against observed market
  behaviour. No OpenRouter observations available yet at this writing.

## Open items for revisit

1. **Cross-provider correlation** — defer to v0.2 competitive-response model;
   assess after Phase 10.
2. **Magnitude distribution shape** — uniform within ranges in v0.1; bimodal
   (small adjustments + occasional major cuts/jumps) is a v0.2 candidate if
   Phase 10 shows clustering at extremes.
3. **OpenRouter-anchored calibration** — after Phase 4 lands actual price
   snapshots, revisit baseline magnitudes against real-world comparison points.
4. **`regime_shift` scenario (Phase 3 + Phase 10)** — add to `config/scenarios.yaml`
   when Phase 3 populates: a 90-day window of sustained bidirectional
   volatility within a tier (elevated σ, no net drift, no step events). Tests
   index stability under noisy-but-trendless underlying data — a regime that
   neither pure unidirectional cuts nor the v0.1 mixed model exercises in
   isolation. Critical thesis-alignment check.
5. **E-tier blow-up tail** — 4% of E paths end <5% of starting. Acceptable for
   v0.1 stress testing; revisit if Phase 10 surfaces methodology instability
   driven by these specific tails.
