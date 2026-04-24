# Pricing Model Design — Phase 2a/2b Layering

**Status**: Pre-implementation design rationale. Validates choices before code lands.
**Scope**: Phase 2a daily baseline prices + Phase 2b ChangeEvent materialisation.

## Thesis alignment

Noble's product thesis is that AI inference pricing evolves toward commodity
free-float dynamics — bidirectional intraday volatility around trend, step-ups
(version launches, supply constraints, premium pricing) as well as step-downs,
and periods of trendless noise as the market discovers fair value. The TPRR
methodology is being built for that regime, not for the current era's mostly-
declining pattern. The Phase 2a/2b synthetic panel must therefore exercise
both directions of price movement; a unidirectional cuts-only model would
let methodology bugs through that production-era data would expose.
Bidirectional drift volatility plus bidirectional step events are baked into
the v0.1 generator for this reason.

## The two layers

**Phase 2a** (provider / baseline): for each (model, date) over the 478-day
backtest window, a single pair of baseline input and output prices.
Pre-contributor-noise. `generate_baseline_prices` emits this as a DataFrame
plus a companion `step_events` DataFrame that is the authoritative source of
truth for every baseline jump — its (`constituent_id`, `event_date`, old/new
prices, direction) records drive everything downstream.

**Phase 2b** (contributor / ChangeEvent): for each ChangeEvent record,
per-(contributor, model) and timestamped to a specific intraday slot. Two
stochastic sources compose to match project_plan's pair-level rates:

1. **Provider-driven events** — direct propagation of 2a step events. When a
   baseline jump fires for model M on day D, one ChangeEvent is generated for
   each contributor covering M.
2. **Contributor-specific events** — additional reprices that reflect
   contract / billing / negotiation dynamics unique to a single (contributor,
   model) pair. Drawn at a pair-level Poisson rate calibrated so the *total*
   rate (propagated + contributor-specific) matches project_plan's target.

This layering is why project_plan's 2b pair rates (F 4-6/yr, S 6-10/yr,
E 10-20/yr) are higher than 2a's model-level rates (F 3/yr, S 4/yr, E 5/yr):
2b counts every observation at the per-contributor level, and the propagation
from one baseline event fans out to ~4-7 ChangeEvent records.

## Phase 2a — frequency model

Independent Poisson per (model):

| Tier | Poisson rate (per year) | Expected count over 480 days | Avg interval |
|---|---:|---:|---:|
| F | 3.0 | ~4 | ~120 days |
| S | 4.0 | ~5 | ~90 days |
| E | 5.0 | ~7 | ~75 days |

project_plan 2a says Frontier "every 90-180 days" → 2-4/yr; centred at 3/yr.
Pure Poisson — no artificial clustering imposed; random clustering arises
naturally from the process. Independent across providers (see correlation
section).

## Phase 2a — magnitude model (bidirectional, uniform within tier)

Each 2a step event is bidirectional: 75% probability step-down, 25%
probability step-up. Magnitudes drawn uniform within tier ranges:

| Tier | Step-down range | Step-up range | Mean down | Mean up |
|---|---|---|---:|---:|
| F | 10–25% | +8 to +20% | 17.5% | 14% |
| S | 12–25% | +5 to +15% | 18.5% | 10% |
| E | 20–35% | +5 to +12% | 27.5% | 8.5% |

Step-ups model real-world dynamics absent from a cuts-only generator: version
launches at premium pricing, supply-constrained periods, premium-pricing
strategies in newly-defended capability tiers. The 75/25 split reflects
expected continuation of net downward trend without precluding upward moves.

## Phase 2a — daily drift (Gaussian with tier-scaled volatility)

Per-day return drawn from `Normal(μ, σ)`, then `price[t+1] = price[t] × (1 + return)`.

| Tier | μ (mean daily return) | σ (daily vol) | Annualised vol |
|---|---:|---:|---:|
| F | -0.005%/day | 0.15%/day | ~2.4% |
| S | -0.010%/day | 0.25%/day | ~4.0% |
| E | -0.015%/day | 0.40%/day | ~6.4% |

Negative mean preserves long-run downward drift. Tier-scaled σ produces
genuinely bidirectional day-to-day moves. Per (model, date) seeding ensures
determinism.

## Phase 2b — ChangeEvent materialisation

### Source of truth: no heuristic reconstruction

`generate_baseline_prices` emits a `step_events` DataFrame alongside the
prices frame. Phase 2b consumes that frame directly — it does NOT recover
events via a post-hoc price-return threshold. The earlier 4%-threshold
heuristic was brittle (could miss small up-moves near the 5% lower bound,
could false-fire on high-variance E-tier drift days). Direct emission is the
only reliable source.

### Provider-driven events — tight per-contributor slot jitter

For each 2a step event (constituent M, date D, old/new baseline prices):

1. Draw one **publication slot** for this event from a business-hours-weighted
   distribution — `Normal(mean=16, σ=6)` clipped to `[0, 31]`, where slot 16
   corresponds to 13:00 UTC (midpoint of the 09:00–17:00 fixing window; most
   provider deployments land within the 11:00–15:00 UTC window).
2. For each contributor covering M, generate one ChangeEvent with:
   - `contributor_id = c`, `constituent_id = M`, `event_date = D`
   - `change_slot_idx = publication_slot + Normal(0, 2)` clipped to `[0, 31]`
   - `old_*_price_usd_mtok = contributor-bias-applied old baseline for day D`
   - `new_*_price_usd_mtok = contributor-bias-applied new baseline for day D`
   - `reason = "baseline_move"`. Direction is encoded in the price fields
     (`new_output < old_output` ⇒ step-down; `new_output > old_output` ⇒ step-up) —
     a single reason value lets "all provider-driven events" match via equality
     rather than wildcard. See decision log 2026-04-24 (reason-enum cleanup).

The **tight** per-contributor jitter (σ=2 slots ≈ ±30 minutes 1σ) reflects real
API price propagation: provider pushes an update and billing systems across
enterprises ingest it within minutes, not hours. Broad jitter would manufacture
TWAP variance that doesn't exist in production.

**Calibration note — 32-slot MVP basis**: the publication-slot distribution
(`Normal(16, 6)`) and per-contributor jitter (`Normal(0, 2)`) are calibrated
for the 32-slot 09:00–17:00 UTC fixing window. A v1.3+ window widening to
24 hours (96 slots) would rescale these parameters linearly: σ values multiply
by 3 (σ_pub = 18, σ_jitter = 6) to preserve the same absolute time spread,
and the publication mean shifts to slot-of-midday-UTC in the widened grid
(slot 48 in a 96-slot day ≈ 12:00 UTC). No other structural changes — pure
coordinate transform.

### Contributor-specific events — full business-hours distribution, independent

Additional ChangeEvents beyond propagation, drawn per (contributor, model):

- **Rate** per pair (tier-dependent), calibrated so total pair rate
  (propagated + specific) lands in project_plan's 2b range:

  | Tier | Propagated rate | Target pair rate | Contributor-specific rate |
  |---|---:|---:|---:|
  | F | ~3/yr | 4–6/yr | **1–3/yr** |
  | S | ~4/yr | 6–10/yr | **2–6/yr** |
  | E | ~5/yr | 10–20/yr | **5–15/yr** |

  Efficiency's higher contributor-specific rate reflects more contract churn
  (cheaper models → more negotiation, tier shifts, volume-commitment changes).

- **Slot timing**: drawn independently per event from the business-hours
  distribution `Normal(16, 6)` clipped to `[0, 31]`. These ARE genuinely
  independent events — a billing integration glitch or contract amendment
  can happen any time; the tight publication-slot coupling doesn't apply.

- **Magnitude**: smaller than 2a step events — modest reprices representing
  contract adjustments, not major model launches. Proposed `±2-5%` uniform.

- **Reason**: `contract_adjustment`. Captures the mechanism (MSA amendment,
  tier agreement, volume-commitment update) rather than the effect. Consistent
  with the mechanism-describing pattern of existing reason values
  (`baseline_move`, `outlier_injection`). See decision log 2026-04-24 for the
  naming rationale and the `version_update` removal.

### Panel price on ChangeEvent days

For any (contributor, model, date) with a ChangeEvent record, the panel's
posted price is the daily TWAP reconstructed from the event:

```
TWAP = (change_slot_idx × old_price + (32 - change_slot_idx) × new_price) / 32
```

This overrides the post-step price the 2a.2 contributor-noise layer initially
produced. Implementation in Phase 2b updates the panel after ChangeEvents are
generated.

## Cross-provider correlation — independent in v0.1

Real-world AI inference pricing exhibits competitive response: OpenAI cuts →
Anthropic / Google respond within 30–90 days. The Aug 2024 GPT-4o price cut
was followed by Sonnet 3.5 pricing adjustments and Gemini Flash repricings
over the subsequent quarter.

For v0.1, 2a step events are **independent across providers**. Reasoning:

- Independent Poisson produces enough random clustering to exercise the index.
- Methodology must work under both correlated and independent moves.
- Phase 10 manipulation scenarios test specific extreme cases that don't
  depend on competitive response.

Flagged as **v0.2 enhancement**: induce competitive response by elevating
same-tier rates for 60 days following any step event. Defer until Phase 10
findings indicate it matters.

## Realism check — 1000-path Monte Carlo simulation (Phase 2a only)

Per-tier final-price distribution after 480 days, simulated 1000 paths
starting from `price = 1.0`, seed 42, using the 2a parameters above:

| Tier | p10 final | p50 final | p90 final | Mean | Paths < 5% of start |
|---|---:|---:|---:|---:|---:|
| F | 0.378 | 0.634 | **0.989** | 0.665 | 0 / 1000 |
| S | 0.271 | 0.495 | 0.821 | 0.520 | 0 / 1000 |
| E | 0.082 | 0.227 | 0.524 | 0.273 | 40 / 1000 |

Read:
- **Frontier** — median 37% decline, p90 at 0.989 means ~10% of paths stay
  essentially flat across 480 days. Healthy bidirectional dispersion.
- **Standard** — median 50% decline, p90 18% decline, p10 73% decline.
- **Efficiency** — median 77% decline. Aggressive but plausible for the
  commoditising tier. 40 paths (4%) end below 5% of starting price — the
  blow-up tail. Tier-level index with 6 E constituents sees much smoother
  trajectory than any individual model; joint blow-up is ~10⁻⁹.

## Methodology references

- **Section 3.2** (tier classification) — defines tiers by capability and
  pricing thresholds; does not prescribe price dynamics, leaving the 2a/2b
  design to MVP.
- **Section 3.3.3** (exponential median-distance weighting) — design must
  produce within-tier dispersion that exercises w_exp at λ=3 across the
  backtest. Bidirectional moves widen the distribution exercised.
- **Section 4.2.1** (TWAP daily fix) — intraday price model uses sparse
  change events reconstructed into 32 slots. The ChangeEvent record's
  `change_slot_idx` drives TWAP reconstruction.
- **Phase 4 OpenRouter integration** (deferred): actual snapshots will allow
  validating baseline magnitudes and frequencies against observed market
  behaviour.

## Open items for revisit

1. **Cross-provider correlation** — defer to v0.2 competitive-response model;
   assess after Phase 10.
2. **Magnitude distribution shape** — uniform within ranges in v0.1; bimodal
   (small adjustments + occasional major cuts/jumps) is a v0.2 candidate if
   Phase 10 shows clustering at extremes.
3. **OpenRouter-anchored calibration** — after Phase 4 lands actual price
   snapshots, revisit baseline magnitudes against real-world comparison points.
4. **`regime_shift` scenario (Phase 3 + Phase 10)** — add to
   `config/scenarios.yaml` when Phase 3 populates: a 90-day window of
   sustained bidirectional volatility within a tier (elevated σ, no net
   drift, no step events). Tests index stability under noisy-but-trendless
   underlying data — a regime neither pure unidirectional cuts nor the v0.1
   mixed model exercises in isolation. Critical thesis-alignment check.
5. **E-tier blow-up tail** — 4% of E paths end <5% of starting. Acceptable
   for v0.1 stress testing; revisit if Phase 10 surfaces methodology
   instability driven by these specific tails.
6. **Contributor-specific magnitude distribution** — uniform ±2-5% is a
   starting point for Phase 2b. If Phase 10 finds the quality gate either
   never fires on contributor-specific events (magnitudes too small) or
   fires constantly (too large), retune.
