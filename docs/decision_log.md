# TPRR Decision Log

Chronological record of methodology and scaffolding decisions. Every material
methodology choice must have an entry here.

## 2026-04-23 — Project initialised

**Decision**: Python 3.13 pinned via uv; uv for dependency management; dependency lower-bounds set per pyproject.toml.

**Context**: Matt's system has Python 3.14.4 available; we pin a specific version to reduce ecosystem-edge risk during MVP development.

**Alternatives considered**:
- Python 3.14 — currently cutting edge; some packages (e.g. Plotly classifiers) haven't been updated to declare 3.14 support even though they work; adds debugging friction.
- Python 3.12 — most conservative, widest compatibility; chose 3.13 as reasonable middle ground with modern type system support.
- Poetry / pip-tools / pipenv — uv is materially faster and has better Python-version management.

**Rationale**: 3.13 is feature-complete, has broad wheel coverage across all planned dependencies, and matches the target Python for production if this MVP graduates. uv's managed-Python model isolates the project from the system interpreter.

**Impact**: None on index values. All tooling (mypy, ruff) targets 3.13. Move to 3.14 can happen post-MVP once ecosystem settles.

## 2026-04-23 — Canonical methodology document imported

**Decision**: `docs/tprr_methodology.md` populated with TPRR methodology v1.2 as maintained by Matt.

**Context**: Methodology v1.2 is the canonical reference for this MVP's implementation. CLAUDE.md's methodology summary is a working subset; the canonical doc is authoritative where they conflict.

**Rationale**: Every implementation decision downstream references this document.

**Impact**: This file is the source of truth for Phase 7.0 pipeline confirmation and all scenario/sensitivity interpretation.

## 2026-04-23 — TWAP ordering resolved to TWAP-then-weight

**Decision**: Daily fix computes each constituent's daily TWAP from 96 fifteen-minute slot observations first, then applies the dual-weighted cross-constituent aggregation once using those daily TWAPs as inputs.

**Context**: Section 4.2.1 specifies TPRR Daily Fix = TWAP(Pᵢ(t)) over 96 intervals between 09:00–17:00 UTC; Section 3.3.1 specifies the dual-weighted instantaneous formula. The composition order is not explicit — TWAP(Pᵢ(t)) admits two readings: (i) TWAP each constituent's price first, then weight (TWAP-then-weight), or (ii) compute the weighted index at each slot, then TWAP the 96 slot-level indices (weight-then-TWAP).

**Alternatives considered**:
- TWAP-then-weight (chosen) — matches dominant commodity-benchmark convention (ICE Brent, Henry Hub, ASCI); tier median and exponential weight operate on one comparable daily price per constituent; dimensionally consistent.
- Weight-then-TWAP — closer to a strict reading of "apply formula at each t then TWAP over t"; more computationally expensive; may behave differently on days when slot-level quality gate fires or constituent membership changes intraday.

**Rationale**: Commodity-benchmark precedent, computational tractability, dimensional consistency of the median operating on comparable daily prices.

**Impact**: Phase 10 includes `scripts/twap_ordering_comparison.py` running the full backtest under both orderings and producing `docs/findings/twap_ordering.md`. If empirical divergence is material, methodology v1.3 should resolve the ambiguity explicitly in Section 4.2.1.

**Methodology section**: 3.3.1, 4.2.1

## 2026-04-23 — Section 4.2.3 (transaction cross-validation) deferred from MVP

**Decision**: The MVP does not implement Section 4.2.3 Independent Transaction Cross-Validation.

**Context**: Section 4.2.3 specifies independent API probing to sample actual transaction prices for cross-validation against contributor-submitted prices, with >2% deviation triggering investigation. This requires live production infrastructure, enterprise API access across all tracked providers, and operational capacity to investigate flagged discrepancies.

**Rationale**: Deferred to post-MVP production build per the "production only" carve-out in CLAUDE.md non-goals. The MVP validates the five manipulation controls that can be exercised against synthetic and observable reference data: 4.2.1 TWAP aggregation, 4.2.2 slot-level quality gate, 4.2.4 minimum-constituent requirement, 4.2.5 prohibition on provider self-reported volumes, 4.2.6 continuous exponential weighting.

**Impact**: Phase 10 scenario and sensitivity coverage is five-of-six controls. Transaction cross-validation enters scope when Noble has enterprise API relationships in place and a dedicated investigation workflow.

**Methodology section**: 4.2.3

## 2026-04-23 — Closed-set string fields left as str in v0.1 schema

**Decision**: index_code, ordering, source fields in pydantic schemas remain typed as str rather than Literal or StrEnum, pending Phase 7 implementation clarity.

**Context**: Some schema fields have closed value sets (index_code: 8 values; ordering: 2 values; source: 4 values) that technically could be Literal-typed for tighter compile-time checks. Version remains str (open-ended); reason remains str (free-text by design).

**Rationale**: Premature closure on these sets means schema changes every time we add an index code or ordering variant. Revisit in Phase 7 when stable sets are settled by the actual compute implementation.

**Impact**: Lose compile-time catches on typos in those fields until Phase 7. Acceptable — tests will catch them instead.

## 2026-04-23 — Tier B revenue interpolation anchored to end-of-quarter

**Decision**: Quarterly revenue entries in TierBRevenueConfig are interpolated linearly between consecutive end-of-quarter dates (Q1→Mar 31, Q2→Jun 30, Q3→Sep 30, Q4→Dec 31).

**Context**: Quarterly revenue disclosures are cumulative-through-period-end accounting figures (matching SEC / Bloomberg / Reuters convention). Mid-period interpolation requires an anchor choice.

**Alternatives considered**:
- End-of-quarter (chosen) — matches financial-disclosure convention; aligns with how analysts cross-reference provider fundamentals.
- Mid-quarter — treats revenue as "attributable to mid-period"; misaligns from reference convention.
- Beginning-of-quarter — uncommon; creates a 3-month lag between disclosure and usage.

**Rationale**: Convention match with financial data sources minimizes friction if/when Tier B graduates to analyst-grade data (Menlo, Gartner, IDC).

**Impact**: Dates before first quarter's end-of-quarter date use the first value (clamped); dates between consecutive quarters interpolate by day count; dates after last quarter's end use the last value (clamped).

**Methodology section**: 3.3.2 (Tier B implementation specifics are MVP-scoped; methodology doesn't prescribe anchor)

## 2026-04-23 — Model tier assignments refined from project_plan baseline

**Decision**: Reclassified claude-sonnet-4-6 from S→F and meta/llama-4-70b-hosted from S→E per economic pricing. Added mistral/mistral-large-3 to Standard to preserve tier depth (4 constituents, above 3-constituent minimum with safety margin).

**Context**: During Phase 1.3 registry review, λ=3 weight analysis revealed two project_plan Standard constituents would carry near-zero weight given their actual output prices: Sonnet 4.6 at $15 (w_exp ≈ 0.0003 vs median $4) and Llama 4 70B at $0.80 (w_exp ≈ 0.091). Methodology Section 3.2 places Frontier at >$10/Mtok output and Efficiency at <$1/Mtok; these two models qualify for F and E respectively under the stated tier definitions.

**Alternatives considered**:
- Keep project_plan registry verbatim — preserves list integrity but creates two "ghost" Standard constituents and leaves Standard at 3 active members (exactly at suspension floor).
- Reclassify both without adding — clean tier economics but Standard drops to 3 constituents, no safety margin for the min-3 suspension rule.
- Partial reclassification (Llama only) — retains Sonnet ghost, inconsistent treatment.

**Rationale**: The exponential weighting is designed to fade strategic manipulation and within-tier dispersion, not absorb permanent tier misclassifications. Correctly tiering at inception preserves the mechanism's intended function. Adding Mistral to Standard buys safety margin against suspension firings.

**Impact**: Frontier grows from 5→6, Standard stays 4 (was 5 nominal / 3 effective), Efficiency grows 5→6. Tier medians shift: F median moves from $75 to $57.50 (Sonnet at $15 pulls down, plus 6-constituent median falls between 40 and 75 cluster); S median moves from $4 to $4.50; E median stays $0.80 (Llama addition lands at median).

**Methodology section**: 3.1 (eligibility), 3.2 (tier definitions). The v1.2 methodology's representative-models table (Section 3.2) cites era-appropriate examples; actual tier assignment for the MVP follows the definitional rules, not the illustrative list.

**Frontier tier weight distribution note**: The reclassified Frontier tier has bimodal pricing (three constituents at $75, three below). At λ=3, this produces a distributed w_exp profile — maximum 20.6%, minimum 5.6%, no single constituent at full weight. This is the methodology working as designed: the exponential weighting distributes influence across constituents in proportion to their proximity to the observed tier price level, rather than concentrating it on whichever constituent happens to sit at the median. A healthy Frontier tier in a dispersed market should look like this, not like a tier with one dominant constituent at w_exp = 1.0.

## 2026-04-23 — w_exp distribution observations at registry inception

**Decision**: Accept the λ=3 weight distributions produced by the final registry without adjusting baseline prices to target specific w_exp values.

**Context**: Initial weight analysis shows gemini-2-flash (Standard, $2.50 output) at w_exp = 0.264 given Standard median of $4.50. Below the 0.3 threshold applied to the Mistral addition, but within acceptable range.

**Rationale**: Adjusting baseline prices to engineer desired w_exp values would reverse-engineer the methodology from its intended function. Baseline prices are anchored to approximate real market pricing per project_plan.md; the exponential weighting produces whatever distribution those prices generate. Phase 10 sensitivity analysis will surface whether the resulting distribution is stable under shocks.

**Alternatives considered**:
- Raise gemini-2-flash baseline to $3.00 to narrow the gap to median — rejected as price engineering.
- Lower mistral-large-3 to bring median closer to $4 — same rejection.
- Accept current distribution — chosen.

**Impact**: gemini-2-flash carries 12.8% Standard share at inception. If Phase 10 surfaces concerns, registry revisit is cheaper than methodology revisit.

**Methodology section**: 3.3.3

## 2026-04-23 — Mock contributor panel design rationale

**Decision**: 10-contributor mock panel with heterogeneous profiles, bias-symmetric around zero, volume-mix representative of enterprise distributions, one deliberately high-error-rate contributor for quality-gate stress.

**Context**: Phase 2a synthesizes a Tier A contributor panel. Profile choices affect every index value downstream, so the panel's design encodes methodology choices even though it's technically configuration.

**Rationale**:
- 10 contributors: large enough for Tier A's ≥3 threshold to be exceedable on all models with safety margin; small enough to debug and eyeball individual contributions in notebooks.
- Bias symmetry (exact zero sum): neutralises systematic panel-level bias so the aggregate index reflects underlying price movements, not panel composition. Individual contributor bias exercises exponential weighting.
- Volume mix (1 very_high / 3 high / 4 medium / 2 low): approximates enterprise API spend distribution — platform resellers concentrate usage, mid-size enterprises are the bulk, small users are numerous but thin.
- Heterogeneous coverage: every contributor covers 4–16 models; each model covered by ≥5 contributors. Tests the aggregation under realistic per-contributor coverage gaps.
- One high-error contributor (zeta at 6%): exercises slot-level quality gate reliably. Other contributors at 0.5–2% error rate match realistic billing-integration reliability.

**Alternatives considered**: Homogeneous 10-contributor panel (rejected — doesn't stress exp-weighting), 15-20 contributor panel (rejected — debugging cost), 5-contributor panel (rejected — insufficient margin above Tier A ≥3 threshold).

**Impact**: This panel design is the baseline for all Phase 2–10 work. Any change requires re-running the full backtest. Panel itself stored in config/contributors.yaml and tracked in git.

**Methodology section**: 3.3.2 (three-tier hierarchy, Tier A definition)

## 2026-04-23 — Volume correlation refactor: per-(contributor, model) idiosyncratic factor

**Decision**: Each (contributor, model) pair has an independent random-walk idiosyncratic noise component layered on top of the contributor-level shared daily multiplier. Target median within-contributor cross-model correlation is 0.5-0.85 over the full window; individual pair correlations are path-dependent and may range from negative to near-unity.

**Context**: The original 2a.3 implementation produced perfect 1.0 correlation across all of a contributor's covered models, which would have broken Tier B derivation testing (degenerate constant within-provider splits), trivialised Phase 10 scenario 3 (stale quote has no mix-shift dynamic to expose), and contradicted Noble's free-float pricing thesis (which implies fluid model-mix shifts, not frozen ratios). Identified during Phase 2a.3 spot-check.

**Alternatives considered**:
- AR(1) mean-reverting idiosyncratic noise — kills negative cross-pair correlations but also kills ratio drift; incompatible with thesis.
- Larger shared-component σ to dominate — tightens per-pair correlation but re-introduces near-lockstep movement, weakens Tier B stress-test.
- Random walk (chosen) — preserves ratio drift and model-mix fluidity; single-pair correlations are path-dependent; median-of-pairs is the stable diagnostic.

**Rationale**: Thesis alignment is load-bearing. The volume panel must exercise fluid model-mix shifts over time to stress-test Tier B derivation and Phase 10 scenarios correctly. Random-walk noise is the only option that preserves that property.

**Impact**: Panel now exhibits realistic within-contributor cross-model variance. Verified: atlas cross-model volume ratio drifts 0.58 → 0.52 → 0.72 across day 0/100/300/477. Median pair-correlation 0.72 (target band 0.5-0.85).

**Methodology section**: 3.3.2 (Tier A volume attestation), thesis alignment with free-float pricing dynamics.

## 2026-04-24 — Phase 2b ChangeEvent layering and "contract_adjustment" reason naming

**Decision**: Phase 2b ChangeEvent records come from two independent sources: (i) propagated 2a baseline step events, one per covering contributor, with tight slot jitter (σ=2 slots on the corrected 32-slot basis — see slot-count erratum entry below) around a single publication slot, all emitted with `reason = "baseline_move"` (direction encoded in price fields, not duplicated in reason); and (ii) contributor-specific reprices drawn independently per (contributor, model) pair, full business-hours slot distribution, smaller magnitude (±2-5%), named **`contract_adjustment`**.

**Context**: Resolving the 2a/2b relationship (see design note at `docs/findings/pricing_model_design.md`). project_plan 2b rates (F 4-6/yr, S 6-10/yr, E 10-20/yr per pair) are higher than 2a model-level rates (F 3/yr, S 4/yr, E 5/yr) because 2b fans out each baseline event to ~4-7 ChangeEvents (one per covering contributor) PLUS adds contributor-specific reprices. The naming of the contributor-specific `reason` value was a design choice between `contributor_reprice` and `contract_adjustment`.

**Alternatives considered**:
- `drift_correction` (prompts.md 2b.1 draft) — rejected: implies returning to a baseline, which isn't what these events model. They're non-reversing reprices driven by external (contract-level) triggers.
- `contributor_reprice` — rejected: agent-neutral ("reprice" sounds market-driven); doesn't name the mechanism.
- `contract_adjustment` (chosen) — names the underlying mechanism (MSA amendment, tier agreement, volume-commitment update). Reads unambiguously to a finance practitioner; consistent with the existing mechanism-describing pattern in the `reason` enum (`baseline_move`, `outlier_injection`).

**Rationale**: ChangeEvent `reason` values describe what HAPPENED in the world — the mechanism that caused the price to move — not the agent or the effect. `contract_adjustment` fits that pattern and is precise about the underlying driver. It also positions Phase 10 analysis cleanly: scenario logic can distinguish provider-driven moves (`baseline_move`) from contract-level moves (`contract_adjustment`) with a single equality filter. Direction of the provider-driven move is encoded in the price fields (`new_output < old_output` ⇒ down, `new_output > old_output` ⇒ up); duplicating direction in the `reason` field would create drift risk and force "all provider-driven events" queries into wildcard matches rather than equality checks.

**Also logged here**: the tight per-contributor slot jitter for propagated events (σ=2 slots ≈ ±30 min on the 32-slot basis) reflects real-world API price propagation taking minutes rather than hours. Broad jitter (e.g., independent draws from full business-hours) would manufacture TWAP variance that doesn't reflect production.

**Impact**: Phase 2b's change_events generator emits `baseline_move` for propagated events (direction implicit in old/new price fields) and `contract_adjustment` for contributor-specific events. The `reason` enum is now three live values: `baseline_move`, `contract_adjustment`, `outlier_injection`. Phase 10 scenarios filter by `reason` via single equality to isolate provider-driven vs contributor-level dynamics. `version_update` removed from the reason enum as dead code — no firing path exists in Phase 2a/2b/3 (version changes are handled as distinct constituent_ids, not ChangeEvents on existing constituents).

**Methodology section**: 4.2.1 (TWAP daily fix and intraday price model).

## 2026-04-24 — Methodology Section 4.2.1 slot arithmetic corrected: 32 slots × 15 min × 8-hour window

**Decision**: Resolve the arithmetic inconsistency in methodology Section 4.2.1 (which simultaneously asserts 96 observations, 15-minute polling intervals, and a 09:00–17:00 UTC fixing window — only two of those three can be true) by keeping **15-minute polling cadence** and the **8-hour fixing window** and correcting "96 observations" to **32 observations**. The MVP and all downstream code use 32 slots indexed [0, 31].

**Context**: During Phase 2b design review, the combination 96 × 15-minute = 24 hours was flagged as incompatible with the "09:00–17:00 UTC fixing window" and "eight-hour window" statements that appear multiple times in the same section. One of the three values had to be wrong; the question was which.

**Alternatives considered**:
- **Keep 96 slots, change polling to 5-minute**: matches the arithmetic (96 × 5 min = 8h) but drops methodology's explicit "15-minute polling interval" statement. Rejected — 15-min polling cadence is the load-bearing operational constant for a benchmark whose prices barely move intraday; tighter cadence creates polling density that adds no index value and costs more to run at scale.
- **Keep 96 slots, reinterpret as 24-hour daily grid with fixing-window subset of 32**: preserves all three stated values by introducing a "day-grid vs fixing-subset" distinction. Rejected — adds conceptual complexity without benefit; pre/post-fixing changes aren't modelled in v0.1.
- **Keep 15-min and 8-hour window, correct 96 → 32** (chosen): fixes the arithmetic outlier and preserves the two values the methodology repeatedly anchors on.

**Rationale — why 15-minute interval is the load-bearing constant, not the slot count**: The polling interval is an OPERATIONAL choice that defines data-collection infrastructure cost and matches real-world provider pricing-page update rhythm. The slot count is a DERIVED value (slots = window / interval). If the Index Committee later widens the fixing window — e.g., to 24 hours in v1.3+ to capture APAC activity — the correction is purely `32 → 96` slots at the same 15-minute cadence, with no change to polling infrastructure, schema granularity, or per-slot processing cost. Tightening to 5-minute polling would mean 96 slots today AND 288 slots in a future 24-hour window — polling density unnecessary for AI inference benchmark data and expensive to run at scale.

**Rationale — why the 8-hour window is preserved for MVP despite APAC activity consideration**: Section 4.2.1's manipulation-resistance argument ("a provider seeking to influence the daily fix would need to sustain a manipulated price continuously across an eight-hour window") depends on the CONCENTRATION of the fixing window in a single liquid segment of the global trading day. Widening to 24 hours dilutes the revenue-foregone cost during thin APAC hours — a manipulator could hold a stale price through low-activity periods at lower real cost. MVP preserves the 8-hour concentrated window; window widening remains a v1.3+ methodology consideration pending observed APAC activity volumes.

**Future evolution path**: A v1.3+ window widening is a linear change — `twap_slots: 32 → 96`, `change_slot_idx: [0, 31] → [0, 95]`, no schema redesign, no polling cadence change, no TWAP formula change. Per-slot economics unchanged.

**Impact**:
- Methodology v1.2 Section 4.2.1 corrected in-place as a defect (erratum, not a v1.3 revision — fixes arithmetic without altering methodological substance).
- CLAUDE.md: working-summary slot counts, TWAP reconstruction examples, and ChangeEvent schema `change_slot_idx` range all updated 96 → 32 and [0, 95] → [0, 31].
- `src/tprr/schema.py`: `Field(ge=0, le=95)` → `Field(ge=0, le=31)`.
- `config/index_config.yaml`: `twap_slots: 96` → `twap_slots: 32`.
- `src/tprr/config.py`: `IndexConfig.twap_slots` default `96 → 32`.
- Phase 2b jitter recalibration to 32-slot basis: publication-slot distribution `Normal(μ=16, σ=6)` clipped `[0, 31]` (midpoint ~13:00 UTC, 1σ covers ~10:30–15:30); per-contributor jitter σ=2 slots (= ±30 minutes 1σ, realistic API ingestion propagation spread).
- Tests and design doc references follow.

**Methodology section**: 4.2.1 (TWAP daily fix).

## 2026-04-24 — TWAP semantic of panel's price columns on change-event days

**Decision**: On change-event days for a (contributor, constituent) pair, the panel's output_price_usd_mtok and input_price_usd_mtok fields store the daily TWAP — the weighted average of pre-change and post-change prices across the 32 intraday slots — not the pre-change or post-change posted price. On non-event days, these fields store the single posted price for that day.

**Context**: The panel schema has one row per (contributor, constituent, date). On days with intraday price changes, the schema cannot distinguish pre-change from post-change without a slot dimension. Three readings of what the panel's price column should mean on such days: (a) pre-change price, (b) post-change price, (c) daily TWAP.

**Alternatives considered**:
- Store post-change price (end-of-day convention) — matches how many price feeds conventionally display "close price" for a day. Rejected — leaves the intraday TWAP derivable only through reconstruction, creating redundancy with what the ChangeEvent records already encode.
- Store pre-change price — symmetric alternative to above, same drawback.
- Store daily TWAP (chosen) — the panel's price column on change-event days IS the reconstructed TWAP. Consumers reading the panel directly get the day's benchmark-consistent price without needing to reconstruct slots. Consumers needing slot-level granularity reconstruct from ChangeEvent records via reconstruct_slots.

**Rationale**: The panel is the primary aggregate reference; Phase 7 (aggregation) reads the panel, not the change events. Storing daily TWAP directly aligns the panel with the downstream benchmark-computation semantic. The slot-level detail remains recoverable from ChangeEvent records, preserved by the invariant (verified in Phase 2c property tests) that reconstruct_slots + compute_daily_twap reproduces the panel's stored TWAP exactly.

**Impact**: Phase 6 quality gate reconstructs slots from ChangeEvent records, applies gate, computes slot-level-gated TWAP via compute_daily_twap. The panel's stored TWAP is the un-gated reference; the gated TWAP computed via reconstruction is what flows into Phase 7 aggregation. Difference between panel TWAP and gated TWAP is a direct signal of whether the quality gate fired on that (contributor, constituent, date).

**Methodology section**: 4.2.1 (TWAP daily fix), 4.2.2 (quality gate)

## 2026-04-27 — Tier reshuffle handling: panel as source of per-day tier membership truth

**Decision**: Index Committee tier reclassifications (e.g. scenario 7's F→S move of anthropic/claude-sonnet-4-6 on day 400) are encoded as: (i) `mutate_registry` updates the `ModelMetadata.tier` to the new value; (ii) the panel's `tier_code` column is rewritten from old to new for that constituent on `observation_date >= effective_date`. Pre-effective-date panel rows retain the old `tier_code` (historical truth — the constituent was in the old tier on those days). The 5-day quality-gate trailing window (Section 4.2.2) and tier median (Section 3.3.3) consume the panel's per-row `tier_code` on each day; no warmup period is imposed on a reclassified constituent.

**Context**: Methodology Sections 3.3.3 (tier median) and 4.2.2 (slot-level quality gate, 5-day trailing average) do not explicitly address the case where a constituent's tier_code changes mid-window. The question is: when sonnet-4-6 reclassifies F→S on day 400, does the new tier's median computation on days 401+ use sonnet's pre-day-400 (F-tagged) prices for the 5-day trailing window in the data quality gate? Or is sonnet treated as a "new entrant" to S tier requiring a 5-day warmup before contributing?

**Alternatives considered**:
- **Reading A — panel-as-truth, no warmup (chosen)**: gate walks back 5 days of (contributor, constituent) prices regardless of `tier_code`; panel-row tier rewrite is sufficient. Tier median includes the reclassified constituent on `day_offset >= effective_date`.
- **Reading B — tier change triggers warmup**: sonnet contributes to S median starting day 405 (first day with 5 days of S-tagged trailing data). Imposes a 5-day hole in the constituent's contribution to its new tier.

**Rationale**:
- The 5-day trailing window in Section 4.2.2 is per-(contributor, constituent), not per-tier. Its purpose is detecting slot-level outliers against the constituent's recent pricing baseline. The constituent's actual prices are continuous across the reclassification boundary; only the tier label changes. Forcing a 5-day warmup imposes conservatism the methodology doesn't ask for.
- The tier median (Section 3.3.3) is a snapshot of day-t active members' prices. It has no memory of pre-day-t tier history. On day t the constituent is in tier X by Index Committee fiat; the median uses its day-t price.
- Reading B introduces a "tier residency duration" concept absent from both methodology sections, and creates an awkward operational gap (Index Committee has reclassified, but the index pretends the change hasn't taken effect for 5 days). Harder to defend to a reviewer than "Index Committee decisions take effect on the effective date".

**Impact**:
- `mutate_registry` is single-tier-valued — `ModelMetadata` carries one current tier, no temporal model. After scenario 7 composition the registry says sonnet is in S; reading the registry alone for a date < day_400 would return the post-reclassification tier, which is wrong-for-that-date.
- **Phase 7 must read `tier_code` from the panel**, not from the registry, when computing per-day tier membership. The panel is the source of truth for historical tier state; the registry holds the current state only.
- Scenario 7 composer records a manifest note flagging this so downstream consumers see it in the audit trail: "tier_reshuffle: registry holds single-valued tier (post-change=…); per-day tier membership truth is panel.tier_code, not registry. Phase 7 must read tier_code from the panel for dates < {effective_date}."
- This is a v0.1 simplification. v0.2+ may add a temporal `ModelRegistry` (e.g. `tier_history: list[TierAtDate]` on `ModelMetadata`) if Index Committee mechanics become operationally significant beyond MVP scope.

**Methodology section**: 3.3.3, 4.2.2 — Section 3.2 (tier classification rules) does not prescribe the temporal interface but is consistent with Reading A.

## 2026-04-27 — Scenario 4 (correlated_blackout) two-contributor target rationale

**Decision**: Scenario 4 (correlated_blackout) blacks out contrib_sirius + contrib_polaris concurrently for 10 days (days 250–259). A single-contributor blackout was rejected because the production contributor panel does not produce a min-3 floor breach with a one-contributor outage.

**Context**: Phase 3.1 design reviewed contributor coverage against the methodology's minimum-3-active-constituents-per-tier suspension rule (Section 4.2.4). Least-covered Efficiency-tier model on the production panel has 5 covering contributors; dropping any single contributor leaves 4 active — above the suspension floor.

**Alternatives considered**:
- **Single-contributor blackout** — does not exercise the suspension mechanism on any model with current coverage. Rejected as it would test only "panel partially missing" rather than "tier suspension fired".
- **Three-contributor concurrent blackout** — would over-test, dropping multiple models below the floor on multiple tiers simultaneously. Rejected as too aggressive for a calibration scenario.
- **Two-contributor concurrent blackout (chosen)** — sirius + polaris share coverage of three E models (gemini-flash-lite, qwen-3-6-plus, mimo-v2-pro), each currently at 5 contributors; concurrent removal drops all three to exactly 3 contributors, hitting the suspension boundary precisely.

**Rationale**: Correlated outages model real-world phenomena: shared cloud-provider outage, billing-system upstream issue, auth-provider outage affecting multiple enterprise consumers simultaneously. The two-contributor concurrent design exercises both the cross-contributor outage pattern (realistic) and the min-3 suspension boundary (the methodology mechanism we want to test).

**Impact**: Three E-tier models hit the min-3 boundary during the 10-day window. If any of them additionally has a quality-gate exclusion or another contributor drops out for any reason during the window, the floor is breached and the tier suspension fallback (prior-day value) fires. This is the intended exercise.

**Methodology section**: 3.3.2 (Tier A volume attestation), 4.2.4 (minimum-constituent-count suspension)

## 2026-04-27 — Scenario 5 (shock_price_cut) day shift from 200 to 203

**Decision**: Scenario 5 (shock_price_cut) targets day 203 of the backtest, shifted +3 days from the originally planned day 200 due to a natural deepseek-v3-2 baseline step event landing on day 198 on seed 42 with the production registry.

**Context**: Phase 3.1 design originally targeted day 200 for the 50% provider-level step-down on deepseek-v3-2. Pre-flight verification on seed 42 showed a natural Phase 2 baseline_move event at day 198 — within the ±5 event-clear window of the originally planned day. The natural event was a step-down drawn from the E-tier step-down range (20–35%); landing a 50% scenario-driven step-down two days later would have made it harder to attribute index movements to the scenario alone.

**Alternatives considered**:
- **Keep day 200, accept overlapping events** — rejected because attribution becomes muddied; Phase 10 finding would have to disentangle scenario-driven and natural step-down effects.
- **Change seed** — rejected because every other scenario's event-clear-day annotation is also seed-specific; re-verifying all annotations on a new seed is more disruptive than shifting one date.
- **Shift to day 203 (chosen)** — places the scenario exactly 5 days after the natural day-198 event. With strict ±5 window semantics in the pre-flight check, day 203 is clear at the constituent level for baseline_move events.

**Rationale**: The ±5 buffer is sufficient for the index to absorb the prior step-down's TWAP impact before the scenario's day. Shift logged in scenarios.yaml `notes` field for traceability; the manifest captures the note via `add_note()` so the audit trail is preserved through composition.

**Impact**: Phase 10 scenario 5 analysis can attribute index movement on/after day 203 to the scenario step-down without confounding from the natural day-198 step. Scenario 5's per-contributor-level event-clear status is documented separately (see "Pre-flight scope finding: scenario 5 day 203 has nova contract_adjustment collision" entry, same date) — the day-shift rationale here is constituent-level only.

**Methodology section**: 4.2.1 (TWAP daily fix), 4.2.2 (slot-level quality gate, 5-day trailing window)

## 2026-04-27 — Scenario 6 (sustained_manipulation) target contributor: lyra not rigel

**Decision**: Scenario 6 (sustained_manipulation) targets contrib_lyra × anthropic/claude-haiku-4-5, not contrib_rigel × claude-haiku-4-5. Same constituent preserved across alternatives; only the contributor differs.

**Context**: Phase 3.1 design considered both rigel (+1.5% systematic bias) and lyra (-0.5% systematic bias) as candidates for the manipulation contributor. Both cover claude-haiku-4-5. The scenario sustains an off-median price (tier-median × 1.25) for 60 days; the manipulator's normal bias affects how cleanly the sustained off-median signal is attributed to manipulation vs to pre-existing bias drift.

**Alternatives considered**:
- **rigel (+1.5% bias)** — rejected. rigel's positive bias would conflate the manipulation signal with rigel's already-elevated normal pricing. The sustained tier-median × 1.25 manipulation would partially overlap with the +1.5% bias, making attribution noisier.
- **lyra (-0.5% bias) (chosen)** — near-neutral bias gives a cleaner manipulation signal. The 25% sustained over-pricing is unambiguously above lyra's normal price level (which is slightly below baseline).

**Rationale**: Scenario 6 tests the methodology's exponential median-distance weighting under sustained off-median pricing. The cleaner the signal-to-bias ratio, the cleaner the test. lyra's −0.5% bias means the sustained over-pricing is ~25.5% above lyra's normal price — versus ~23.5% above rigel's, with rigel's pre-existing positive bias as background noise that would have to be separated out in interpretation.

**Impact**: Phase 10 scenario 6 analysis can attribute index responses to the manipulation cleanly; the manipulator's normal pricing pattern doesn't pre-bias the result. Same constituent (claude-haiku-4-5) preserved across alternatives so the tier-median computation pool is unchanged.

**Methodology section**: 3.3.3 (exponential median-distance weighting), 4.2.6 (continuous exponential weighting as manipulation control)

## 2026-04-27 — Scenario 7 (tier_reshuffle) tests committee mechanics, not adversarial pricing

**Decision**: Scenario 7 (tier_reshuffle) is classified as a methodology-administration scenario, not an adversarial- or erroneous-pricing scenario. Distinct threat surface from scenarios 1–6 and 9.

**Context**: Phase 3.1 scenario taxonomy review distinguished two threat surfaces:
- **Adversarial / erroneous pricing** (scenarios 1–6, 9) — tests exponential weighting, quality gate, TWAP under bad or manipulated prices.
- **Methodology administration** (scenario 7) — tests Index Committee actions: tier reclassification, constituent reshuffling.

The two surfaces exercise different methodology controls and should be reasoned about separately.

**Rationale**: Methodology Section 3.2 (tier classification) explicitly contemplates quarterly Index Committee constituent review — a constituent's price evolution can move it across tier boundaries (e.g., a Frontier model whose price drops below $10/Mtok would be reclassified to Standard). Scenario 7 validates that the implementation handles this correctly:
- Pre-effective-date panel rows retain the old tier_code (historical truth).
- Post-effective-date panel rows carry the new tier_code (current truth).
- No retroactive contamination of pre-change index values: if Phase 7 reads tier_code from the panel per-row (not from the registry), per-day tier membership is correct for every day.

**Impact**: Phase 10's scenario 7 finding tests methodology administration mechanics independently of the pricing-driven scenarios. Companion decision: "Tier reshuffle handling: panel as source of per-day tier membership truth" (same date) — that entry covers the implementation details (Reading A vs Reading B; the Phase 7 contract that tier_code comes from panel rows, not from the registry).

**Methodology section**: 3.2 (tier classification, quarterly review), 3.3.3 (tier median computation per-day)

## 2026-04-27 — Pre-flight scope finding: scenario 5 day 203 has nova contract_adjustment collision

**Decision**: Pre-flight event-clear check applied to scenarios 1, 2, 9 only (fat_finger × 2, intraday_spike). Scenario 5 (shock_price_cut) excluded from pre-flight despite its event-clear annotation in scenarios.yaml.

**Context**: During Batch E implementation, attempt to extend pre-flight to scenario 5 (using its day-203 verified-clear annotation) revealed that on seed 42, the per-contributor event level shows contract_adjustment events for helios and nova × deepseek-v3-2 within the strict ±5 window of day 203 — including ON day 203 itself for nova. The historical "day-203 is event-clear" annotation (originally established when scenario 5 was shifted from day 200 to day 203) was based on baseline_move events at the constituent layer; per-contributor contract_adjustment events were not part of that verification.

**Behaviour under v0.1**: scenario 5's composer is multi-event-aware (per Phase 2c.1 multi-event reconstruction support) and correctly handles the stacking via re-TWAP. Index values produced are mathematically correct. Conceptually, the scenario tests provider-shock dynamics on a day where one covering contributor (nova) also has a natural contract adjustment — a legitimate edge case rather than a methodology defect.

**Alternatives considered**:
- Shift scenario 5 to a day clear of all event types per-contributor — requires re-running event-clear analysis at per-contributor granularity across days 195-220, picking a new day, updating scenarios.yaml. Defensible but cosmetic for v0.1.
- Accept the stacking as realistic and document (chosen) — composer is mathematically correct, scenario still tests methodology behaviour under price shock, real markets do see coincident events.
- Extend pre-flight to scenario 5 with strict per-contributor granularity — would force a re-verification cycle and currently rejects day 203. Deferred to v0.2.

**Rationale**: For v0.1, the composer's correctness is sufficient. The "verified clear day" concept is a scenario-design convenience, not a methodology requirement. Phase 10 findings can revisit if the day-203 collision distorts scenario 5's results.

**Future work**: v0.2 may extend pre-flight to per-contributor event granularity for shock_price_cut and other propagated-event scenarios. The pre-flight infrastructure already supports this; only the scope filter needs broadening. Defer until Phase 10 findings indicate it matters.

**Methodology section**: 3.3 (aggregation), 4.2 (validation framework — scenario design)

## 2026-04-28 — OpenRouter coverage: 15/16 registry models mapped; 1 documented unmatched

**Decision**: Tier C reference data covers 15 of 16 registry constituents via `openrouter_author/openrouter_slug` mapping in `config/model_registry.yaml`. The remaining 1 (`meta/llama-4-70b-hosted`) is documented as having no OpenRouter analogue at the same architectural-variant granularity.

**Context**: Phase 4 Batch B match-rate verification revealed three naming-convention mismatches between the TPRR registry and OpenRouter: separator differences (dot vs hyphen), family-component reordering / minor version bumps, and absent-or-different authors. Initial inspection underestimated coverage at 5/16 due to truncated investigation of the OpenRouter response — first iteration looked at `+N more`-summarised author lists rather than full enumeration. Two follow-up rounds refined the mapping: Pattern 2 (family-rename judgment for the gemini variants) lifted to 11/16, then Pattern 3 (author-naming convention differences for mistral ↔ mistralai, alibaba ↔ qwen, and the missed anthropic dotted-version entries) lifted to 15/16. The iterative-discovery audit trail is recorded in conversation-context for Batch B and in feedback memory `feedback_grep_full_lists_not_truncated.md`. Tier C coverage of 15/16 (94%) is well above design floor.

**Resolution path chosen**: Populate `openrouter_author/slug` fields explicitly in `model_registry.yaml` for the 15 mappable models. Use case-by-case judgment for family-rename cases. Minor version bumps within the same series are accepted as legitimate mappings (`gemini-2-flash` → `gemini-2.5-flash`, `gemini-3-pro` → `gemini-3.1-pro-preview`); the rationale is that within-series minor versions represent the same model lineage at a more recent release cadence than our registry's projected names. Author-naming convention differences (`alibaba` ↔ `qwen`, `mistral` ↔ `mistralai`) are accepted as legitimate mappings when the model lineage is clear. Architectural variant differences (`llama-4-70b-hosted` ↔ `llama-4-maverick`) are NOT accepted — these are different model variants in the same family rather than naming-convention or version-level differences, and forcing a map would distort what Tier C reference data represents for that constituent.

**Unmatched models**: Only `meta/llama-4-70b-hosted` remains unmatched. Its registry entry leaves `openrouter_author/slug` unset; the `/api/v1/models` matcher logs INFO at fetch time and skips. This constituent will have no Tier C reference data; Phase 5 weighting falls through to Tier A (contributor panel) and Tier B (revenue proxy) for it.

**Impact**: 15/16 (94%) coverage. OpenAI + Anthropic + Google + DeepSeek + Mistral + Alibaba/Qwen + Xiaomi all covered. Pattern: forward-projected registry names mostly map cleanly to OpenRouter via small convention adjustments. The single unmatched constituent (Llama 4 hosted variant) reflects an architectural-naming gap rather than absence of the model family from OpenRouter.

**Future work**: v0.2 may revisit `meta/llama-4-70b-hosted` if OpenRouter publishes a 70B-parameter hosted variant that matches the registry's intent more precisely than maverick or scout. Re-run mapping audit during Phase 4 maintenance cycles when registry constituents are revised or OpenRouter model availability shifts.

**Methodology section**: 3.3.2 (three-tier volume hierarchy)

## 2026-04-28 — xAI / Grok excluded from v0.1 universe; queued for v0.2

**Decision**: The v0.1 TPRR registry covers 16 constituents across OpenAI, Anthropic, Google, DeepSeek, Alibaba, Xiaomi, Mistral, and Meta. xAI / Grok is not included in v0.1; addition is queued for the v0.2 universe expansion.

**Context**: During Phase 4b drafting, the absence of xAI / Grok from the registry was raised. xAI is materially active in the institutional AI inference market with Grok-class models that would qualify for either Frontier or Standard tier depending on current pricing. The methodology Section 3.2 explicitly anticipates universe evolution through quarterly Index Committee review.

**Alternatives considered**:
- Retrofit v0.1 to add xAI now: requires regenerating mock data (480 days × per-contributor coverage), updating contributor profiles, refreshing decision-log entries that reference "16 models," potential adjustments to Phase 3 scenario coverage. ~2-3 hours of rework with no methodology benefit (validation already robust at 16 constituents).
- Add xAI to Tier B revenue config only without mock data: creates a half-measure where Tier B has 9 providers but the registry has 16 models with no xAI rows; index doesn't actually reflect xAI in v0.1.
- Document v0.1 omission, add in v0.2 (chosen): cleanest forward path; v0.1 validation is unaffected; v0.2 universe expansion is normal benchmark evolution per methodology Section 3.2.

**Rationale**: The MVP's job is methodology validation, not market completeness. The exponential weighting, three-tier hierarchy, and manipulation resistance arguments all stress-test fully on 16 constituents. Adding a 17th constituent doesn't change what the validation proves. Retrofitting six phases of completed work for one additional constituent is real cost without methodology benefit.

**Impact**:
- v0.1 backtest results will reference a 16-constituent universe; this should be stated in Phase 11 summary materials
- v0.2 universe expansion is queued to add xAI alongside any other emerging providers (e.g., new Chinese frontier labs, additional European providers)
- Tier B revenue config in Phase 4b covers the 8 v0.1 providers only; xAI revenue data will be added in v0.2

**Methodology section**: 3.1 (eligibility), 3.2 (tier classification — quarterly committee review)

## 2026-04-28 — Tier B revenue config: 6 providers covered; Meta and Xiaomi excluded as Tier-A-only

**Decision**: Tier B revenue config covers 6 of the 8 v0.1 providers (OpenAI, Anthropic, Google, DeepSeek, Alibaba, Mistral). Meta (Llama) and Xiaomi (MiMo) are intentionally excluded; their constituents (`meta/llama-4-70b-hosted` and `xiaomi/mimo-v2-pro`) fall through to Tier A only (mock contributor panel) for v0.1.

**Context**: Tier B's methodology (Section 3.3.2) requires "disclosed provider total API revenue × OpenRouter within-provider split". This pattern presumes a centralized "provider" running a paid API at material scale where revenue is the volume proxy. Two of the v0.1 providers do not satisfy this presumption.

**Methodology question raised**: when does free-distribution / open-weight or zero-public-data fall outside Tier B's revenue-proportional model?

**Decision criteria for Tier B inclusion** (v0.1):
- (a) Provider runs a paid hosted API at material scale, AND
- (b) Revenue is publicly disclosed or analyst-triangulatable.

**Meta excluded** because Llama is free-distributed open-weight; revenue accrues to hosting partners (AWS Bedrock, Azure, GCP, Together, Fireworks, Groq, Cerebras), not to Meta. Meta's own Llama API service launched April 2025 (LlamaCon) but has not reached the SEC-mandated separate-reporting threshold (~5-10% of total Meta revenue, i.e., $8B+). Synthesising a "Meta Llama API revenue" number would claim provider-level economics that don't exist; the within-provider OpenRouter split would also be ambiguous (Meta's OR models span `meta-llama/...` author with multiple variants).

**Xiaomi excluded** because no public revenue disclosure for MiMo API service exists. MiMo-7B launched April 2025; commercial pricing only emerges late 2025 with V2-Flash. Xiaomi's $8.7B/3yr AI investment announcement (March 2026) is a capex commitment, not a revenue datapoint. Including symbolic ($2M-$25M) numbers would claim false precision; omission is more honest.

**Impact**:
- v0.1 Tier B has 6 providers × 5 quarters = 30 revenue datapoints in `config/tier_b_revenue.yaml`
- `meta/llama-4-70b-hosted` and `xiaomi/mimo-v2-pro` get Tier C (where they have mappings — note meta is unmatched per Phase 4 close-out, Xiaomi is matched) and Tier A only; their Tier B contribution is zero by design
- `TierBRevenueConfig.get_provider_revenue('meta', date)` and `get_provider_revenue('xiaomi', date)` will raise `ValueError("no Tier B revenue entries")` — same error path as any unknown provider
- Phase 5b weighting must handle "no Tier B for this provider" as a tier-priority fall-through to Tier A, same path as "no Tier C data" handled in Phase 5b

**v0.2 enhancement paths**:
- **Meta**: if Llama paid hosting becomes material, either (a) add Meta to Tier B with explicit Llama API revenue disclosure when Meta starts reporting it, OR (b) create a new aggregated-host-revenue dimension that sums revenue across Llama hosts proportional to OpenRouter share. Option (b) is more accurate to Llama's actual economics but adds a methodology dimension.
- **Xiaomi**: revisit when Xiaomi or analyst coverage starts disclosing MiMo API revenue. Likely v0.3+ given current opacity.

**Methodology section**: 3.3.2 (three-tier volume hierarchy, Tier B definition)

## 2026-04-28 — Tier B API share assumptions for v0.1

**Decision**: Per-provider API-revenue-as-share-of-total-revenue assumptions for v0.1 Tier B are explicit and per-provider, not uniform. Each share is sourced from analyst commentary where available; estimated where not. The estimated splits are v0.1 simplifications subject to v0.2 revisit if finer-grained disclosure becomes available.

**Context**: Tier B input is "disclosed provider total API revenue", but most providers do not disclose API revenue separately from total/cloud revenue. A per-provider API-share assumption is required to extract the API portion from the disclosed total.

**Per-provider assumptions**:

| Provider | API share of disclosed total | Source / rationale |
|---|---:|---|
| OpenAI | 17% | Sacra-disclosed 15-20% range (midpoint 17%); reflects ChatGPT consumer revenue dominance |
| Anthropic | 72% | Sacra-disclosed 70-75% (API + enterprise API); midpoint 72%; reflects API-first business model |
| Google (Gemini API) | 8% | Estimated; Google Cloud is mostly non-AI workloads (compute / storage / BigQuery / Workspace); Gemini API is a small slice. v0.1 simplification. |
| DeepSeek | 60% | Estimated; web/app are free, API is the primary monetised stream. v0.1 simplification. |
| Alibaba (Qwen) | 10% | Estimated; "AI revenue" reported only qualitatively as "triple-digit YoY growth"; Qwen API is one piece of Alibaba Cloud's AI offerings. v0.1 simplification. |
| Mistral | 70% | Sacra-disclosed; reflects API + on-prem licensing + consultancy mix |

**Alternatives considered**:
- Uniform 20% across all providers: rejected because it loses the materially different API-vs-consumer mix (OpenAI ChatGPT-heavy vs Anthropic API-heavy vs Google Cloud-mostly-non-AI). Uniform-20% would systematically overweight OpenAI/Google relative to actual API economics.
- Use Sacra figures only, omit estimated splits: would limit v0.1 to OpenAI, Anthropic, Mistral. Loses Google, DeepSeek, Alibaba — each material providers per registry. Rejected.
- Use per-provider as drafted (chosen): preserves the per-provider economic differences, with explicit flagging of estimated vs disclosed splits.

**Rationale**: The methodology test rests on Tier B providing differentiated volume signals across providers. Uniform splits would flatten that signal. Per-provider splits preserve it; the estimation uncertainty on Google/DeepSeek/Alibaba is documented and bounded.

**Impact**:
- Each provider's quarterly entry in `config/tier_b_revenue.yaml` is `total_revenue × api_share`, with the api_share rationale documented inline as a YAML comment
- Phase 10 sensitivity sweeps could include API-share variations (e.g., Google 5% vs 8% vs 12%) to confirm the index is robust to this assumption
- v0.2 may revisit with finer-grained disclosure if available

**Methodology section**: 3.3.2 (Tier B implementation specifics — MVP scope per the May 2026 decision)

## 2026-04-28 — Tier B quarterly revenue interpolation provenance

**Decision**: Each provider's quarterly Tier B entry derives from ARR or total-revenue progression × the provider's API share. End-of-quarter anchor convention per decision log 2026-04-23 ("Tier B revenue interpolation anchored to end-of-quarter"). Sources are cited per-provider; values flagged `analyst_triangulation` cross-reference multiple analyst sources, `synthetic_for_mvp` flagged where no analyst breakdown exists.

**Context**: The methodology requires quarterly disclosed revenue per provider. Most providers report ARR (annualized) at irregular cadences (monthly press releases, earnings calls, fundraising disclosures), not quarterly revenue directly. A provenance method is required to convert ARR datapoints into quarterly revenue values.

**Method**:
1. **Collect ARR datapoints** at known dates (monthly or quarterly) from public reporting + analyst commentary.
2. **Interpolate to mid-quarter** ARR via linear interpolation between adjacent datapoints.
3. **Convert to quarterly revenue** as `mid_quarter_ARR / 4`.
4. **Apply API share** per the API-share assumption (decision log entry "Tier B API share assumptions for v0.1").
5. **Anchor to end-of-quarter date** per the anchor convention; the loader interpolates linearly between consecutive end-of-quarter anchors when consumers query mid-quarter dates.

**Sources** (per provider):
- **OpenAI**: Sacra ARR profile, CFO-reported $20B end-2025, $25B Feb 2026 (Yahoo Finance / The Information). API share: Sacra 15-20%.
- **Anthropic**: Sacra ARR profile ($1B Jan 2025, $4B Jun, $9B Dec, $19B Mar 2026), SaaStr commentary, Anthropic press releases. API share: Sacra 70-75%.
- **Google (Gemini API)**: Pichai Cloud Next 2026 keynote ($70B annual run rate, 48% YoY). API share: estimated 8% based on Cloud composition.
- **DeepSeek**: Latka ($1.1B FY 2025), TechCrunch (theoretical 545% margin commentary), official mid-2025 ARR $220M datapoint. API share: estimated 60%.
- **Alibaba (Qwen)**: BusinessWire / Constellation Research / Bloomberg coverage of Q3 2025 ($5.6B Cloud revenue, 34% YoY) and Q4 2025 (36% YoY). API share: estimated 10%.
- **Mistral**: Sacra ARR profile ($60M Mar 2025, $100M Nov, $312M Dec, $400M Jan 2026), mlq.ai. API share: Sacra 70%.

**Impact**: Phase 5b's `derive_tier_b_volumes` will consume `config/tier_b_revenue.yaml` directly via `TierBRevenueConfig.get_provider_revenue(provider, date)`. The loader's linear-interpolation contract is unchanged; this entry documents how the YAML's quarterly amounts were derived in v0.1.

**Methodology section**: 3.3.2 (Tier B implementation specifics)

## 2026-04-28 — Tier C historical backfill: option (a) static current snapshot

**Decision**: Tier C historical backfill across the Jan 2025 → today backtest uses the current OpenRouter snapshot's structure (matched models, market shares, current prices) applied to all backtest days. No attempt is made to reconstruct historical OpenRouter snapshots. Documented as an MVP limitation.

**Context**: OpenRouter's `/api/v1/models` endpoint and the per-model `/endpoints` endpoint both return current data with no historical version. The rankings mirror at jampongsathorn/openrouter-rankings publishes weekly snapshots from a relatively recent date, but does not extend back to Jan 2025. The MVP backtest covers ~480 days and needs Tier C reference data on every backtest day.

**Alternatives considered**:
- **Option (a) — static current snapshot (chosen)**: apply current prices, match list, and rankings-derived volumes uniformly across the full backtest. Simple to implement; honest about Tier C's proxy-by-design nature; aligned with project_plan recommendation.
- **Option (b) — Tier C only when historical mirror data is available**: would leave Jan 2025 → mid-2025 with no Tier C data. Phase 5 weighting falls through to A/B for those days. Creates a discontinuity in Tier C coverage at the date the rankings mirror starts publishing.
- **Option (c) — hybrid (historical mirror where available, current snapshot before)**: most "honest" representation but introduces a discontinuity at the boundary, adds source-tracking complexity, and the marginal benefit over (a) is small given Tier C's 20% haircut and proxy-by-design framing.

**Rationale**: The MVP's validation question is whether the algorithm computes correctly on panel-shaped multi-source input. Historical OpenRouter market structure is not load-bearing for that question. Tier C's 20% haircut already discounts its confidence; (b) and (c) would add complexity without unlocking a methodology question this MVP needs to answer.

**Impact and known consequence**: Tier C carries current OR prices applied to early-2025 backtest days, while Tier A carries the mock historical price evolution. The dual-weighted aggregation will blend these on each day. On early-backtest days, Tier C and Tier A may price the same constituent at materially different levels (current 2026-era prices vs simulated Jan 2025 baselines). This is an inherent property of (a), not a defect. Phase 10 findings will surface whether the early-backtest blend produces interpretive noise; if so, the v0.2 fix is option (c) using historical rankings-mirror snapshots where available — NOT a "price-syncing" variant of (a) that aligns Tier C prices to Tier A baselines, which would defeat the data-source independence Tier C is supposed to provide.

**v0.2 enhancement path**: option (c) using historical rankings-mirror snapshots, when the rankings mirror has accumulated enough history to backfill meaningfully.

**Methodology section**: 3.3.2 (three-tier volume hierarchy), 4.2.5 (Tier C as transaction-verified market proxy)

## 2026-04-28 — Tier C rankings sparseness: model-level only with author fallback rejected

**Decision**: Tier C volume is populated from OpenRouter rankings ONLY when a constituent matches a rankings entry at the model level (via date-suffix stripping). Constituents without a model-level match receive `volume_mtok_7d = 0` with a `"no_rankings_data"` flag in the panel row's `notes` field. Author-level proportional splits are NOT used.

**Context**: OpenRouter's rankings mirror returns ~9 entries at the per-model granularity, with dated-version naming (e.g., `anthropic/claude-4.7-opus-20260416`). Of the 15 registry constituents mapped to OpenRouter, only 1 (`deepseek/deepseek-v3-2`) has a discoverable model-level rankings match via date-suffix stripping. The remaining 14 have no model-level rankings data.

**Alternatives considered**:
- Option A (author-share split): equal split within author. Rejected — distorts within-author volume relationships (GPT-5-Pro vs GPT-5-Nano carry vastly different real-world volumes).
- Option B (model-level + author fallback): mixed semantics under one variable. Rejected — creates audit-trail confusion in Phase 10 findings analysis.
- Option C (chosen): model-level matching only; missing data is honestly missing.

**Rationale**: The three-tier hierarchy is designed to handle this. Tier C is the lowest-confidence proxy; when its data is sparse, Phase 5b's tier-priority logic falls through to Tier B (revenue-derived) or Tier A (contributor panel). Synthesising volume that doesn't exist in the source data corrupts the manipulation-resistance argument.

**Impact**:
- Tier C is effectively a price-reference tier in v0.1 with negligible weight contribution.
- Phase 5b implementation must handle "Tier C volume is zero" as a fall-through condition, not as "constituent has no weight" — the constituent gets weight from Tier A or Tier B instead.
- Phase 10 findings should report Tier C contribution percentage; if it's near-zero, that's expected for v0.1 and the methodology validation rests on Tier A weighting working correctly.

**v0.2 enhancement paths queued**:
- Historical rankings snapshots with proper time-series (current is single snapshot)
- Author-level distribution refinement using observed constituent prominence within author from secondary sources
- Supplementary volume sources (Menlo enterprise spend reports, analyst-provided model-mix estimates)
- Date-suffix matcher generalisation: match the most recent dated variant of a base slug rather than exact match

**Methodology section**: 3.3.2 (three-tier volume hierarchy)

## 2026-04-29 — Three-tier volume hierarchy: priority fall-through, literal-canon haircuts

**Decision**: For each (constituent, date), exactly one tier is selected per Section 3.3.2's priority ordering: Tier A used when ≥3 contributors with attested non-zero volume; Tier B used when A is insufficient and the provider has revenue config; Tier C used only when A and B are both insufficient and rankings data exists. Tier-haircut multipliers (1.0/0.9/0.8) apply to the selected tier's volume as confidence discounts. No cross-tier blending.

**Context**: Phase 5 implementation requires precise w_vol formula. Section 3.3.2 specifies tier hierarchy with priority language ("highest-confidence data available", "Tier C only where A and B are both insufficient"). Implementation tested whether haircuts could be read as cross-tier blend coefficients vs. confidence discounts on a selected tier. Methodology language consistently supports the latter reading.

**Cross-tier magnitude question — surfaced and deferred**: Tier A volumes (per-contributor panel sum, ~1-520 mtok/7d) and Tier C volumes (OpenRouter whole-market rankings, ~50,000+ mtok/7d for mapped constituents) operate on fundamentally different scales — Tier A is a panel slice, Tier C is whole-market estimate. After haircutting, Tier-C-attested constituents could carry 100-1000× the w_vol of Tier-A-attested constituents in mixed-tier indices.

This is a real methodology question, not a v0.1 data artefact. Even with full Phase 4 data, Tier A's panel-sum denominator differs structurally from Tier C's whole-market denominator. Section 3.3.2 implicitly assumes the three tiers are commensurable; in v0.1 data, they aren't.

**v0.1 treatment**: Literal-canon application of Section 3.3.2 (apply haircuts as written, accept any cross-tier magnitude gap that emerges). Engineering rescaling factors not supported by methodology language would foreclose discovering whether the gap is real.

**Phase 10 obligation**: explicitly measure Tier-C dominance in mixed-tier indices. If TPRR-F (or any tier index) is materially shifted by Tier-C-attested constituents, that's a methodology finding, not a defect.

**v0.2/v1.3+ enhancement paths queued**:
- Path 2 (rescale to common basis): introduce panel_share_estimate parameter so Tier C volume converts to "panel-equivalent" magnitude before haircutting. Requires panel_share_estimate parameter to be itself defended; introduces methodology dimension v1.2 doesn't define.
- Path 3 (within-tier share): replace raw_volume with constituent's share of its attestation tier's total before haircutting. Eliminates magnitude differences mathematically; loses absolute-volume signal.
- Either path is a v1.3+ methodology revision, not an MVP shim.

**Methodology section**: 3.3.2 (three-tier volume hierarchy)

**Phase 5b empirical finding (added 2026-04-29 post-Batch-B)**: With v0.1 data and Option δ price-implied prior, projected Tier B implied volumes for Tier-B-attested constituents are ~20M mtok/7d, vs ~300 mtok/7d for Tier-A-attested constituents (3 contributors × ~100 mtok each on the synthetic panel). Cross-tier magnitude ratio is approximately 66,000:1 in v0.1. Tier B will dominate any constituent where it's the selected tier, by a margin the haircut multipliers cannot offset. This confirms the methodology question raised at the entry's drafting; Phase 10 will quantify and Phase 11 writeup will address.

## 2026-04-29 — Tier A "attested volume" interpretation: strict > 0 required

**Decision**: A panel row with `attestation_tier='A'` and `volume_mtok_7d == 0` does NOT count toward the ≥3-contributors threshold for Tier A selection. Tier A requires ≥3 contributors with strictly positive `volume_mtok_7d`.

**Context**: Section 3.3.2 specifies "≥3 contributors with attested volumes" for Tier A eligibility. Implementation question: does a contributor reporting zero volume satisfy "attested"? Two readings: (a) row exists = attestation, regardless of volume; (b) attestation requires positive volume.

**Reading chosen**: (b). Reasoning: zero volume from a panel contributor functionally means "no market activity reported," which is informationally equivalent to no attestation. Including zero-volume rows in the threshold would let a constituent technically meet the ≥3 floor while contributing no actual volume signal — defeating the threshold's purpose (ensuring Tier A volume is materially based on real usage data, not contributor-count theatre).

**Impact**: Constituents covered by ≥3 contributors where one or more report zero volume on a given date may fall through to Tier B/C on that date.

**Methodology section**: 3.3.2 (three-tier hierarchy, Tier A threshold)

## 2026-04-29 — Tier B price-implied within-provider split for sparse OR rankings

**Decision**: Tier B's Option B within-provider allocation step (Section 3.3.2) requires per-model OR rankings shares to split disclosed provider revenue across the provider's models. The v0.1 OR rankings mirror's top-9 limit means 5 of 6 Tier B providers (openai, anthropic, google, alibaba, mistral) have zero model-level rankings coverage; only deepseek/deepseek-v3-2 has a model-level match. Strict literal-canon application of Option B would emit Tier B rows for only 1 of 16 constituents, cascading to permanent index suspension.

For v0.1, Tier B uses a **price-implied within-provider split (Option δ)** as the default fallback when model-level rankings are absent. Volume per model = (R/n) / p_i — equal-revenue share across the provider's registered models, which (because revenue = volume × price) implies cheap models receive proportionally more volume than expensive models within the provider. Configurable via a `prior` parameter so Phase 10 can run sensitivity comparison against the equal-volume alternative (Option β).

**Context**: prompts.md 5b.1's algorithm spec assumed model-level rankings would be sufficiently dense to support canonical Option B for most providers. The actual OR rankings mirror exposes only the top-9 models globally, of which exactly one — `deepseek/deepseek-v3.2-20251201` — matches a TPRR registry constituent (after date-suffix stripping per the 2026-04-28 entry). The other 8 entries in the rankings top-9 are non-registry models or registry models with naming conventions that don't match the registry's `openrouter_author/openrouter_slug` (e.g. rankings has `claude-4.6-sonnet-20260217` while the registry's anthropic/claude-sonnet-4-6 has OR slug `claude-sonnet-4.6` — different family-component ordering).

The structural sparseness affects Tier B differently than Tier C. Tier C uses OR rankings for VOLUME ATTRIBUTION on a per-constituent basis; the sparseness was already documented (decision log 2026-04-28 "Tier C rankings sparseness model-level only with author fallback rejected") — Tier C constituents without rankings get volume_mtok_7d = 0 and the tier hierarchy falls through to A or B for those constituents. But Tier B itself uses OR rankings for the WITHIN-PROVIDER ALLOCATION step. With zero coverage, the algorithm has no allocation signal.

**Three approaches considered**:

- **α (strict literal-canon)**: emit no Tier B rows for providers without model-level rankings. Result: only deepseek/deepseek-v3-2 gets Tier B; all other Tier-B-eligible constituents fall through to Tier C (also sparse) and are excluded entirely from aggregation. TPRR-F + TPRR-S near-permanently suspended (min-3 unmet). Defensible to the canon, but produces a degenerate v0.1 backtest that validates nothing about the formula's behaviour on plausible data.

- **β (equal-volume fallback)**: provider revenue split equally as VOLUME across registered models when rankings absent. Implies all models within a provider have the same usage volume regardless of their price. Empirically counter to observed enterprise behaviour — within a provider, cheap models (gpt-5-nano, gemini-flash-lite) typically see far higher volume than premium models (gpt-5-pro, gemini-3-pro). Bakes a directionally-incorrect prior.

- **δ (price-implied within-provider split, chosen)**: provider revenue split equally as REVENUE share across registered models when rankings absent. Volume per model = (R/n) / p_i. Cheap models receive proportionally more volume than expensive models within the provider. Empirically closer to observed enterprise API usage patterns where high-volume tasks (summarisation, classification, extraction, RAG, agentic loops) gravitate to cheap-fast models, with premium models reserved for harder tasks at lower volume share.

**Rationale (β vs δ)**: Both are wrong in different directions; the question is which prior is closer to enterprise reality. A flat-volume prior (β) would have a small efficiency-tier model and a flagship reasoning model carrying identical volume — clearly false. A price-implied prior (δ) recovers the observed pattern that provider revenue mix is roughly balanced across products while volume mix is skewed cheap. Phase 10 sensitivity will run the β alternative as comparison data — if δ produces a materially different index from β, that's a methodology finding worth documenting; if not, it's evidence that within-provider mix doesn't drive the index much. Either way, the empirical question gets answered. Picking the "neutral-feeling" prior (β) and never testing the alternative would be the worse discipline.

**Implementation algorithm (per-provider)**:

For each provider P with revenue R(t) on `as_of_date`:

1. registered_models = registry models with `provider == P`.
2. covered = subset with model-level OR rankings entry; uncovered = the rest.
3. n_total = |registered_models|; n_covered = |covered|; n_uncovered = |uncovered|.
4. **Coverage-share assumption**: R_covered = R × n_covered / n_total; R_uncovered = R × n_uncovered / n_total. Equal-revenue assumption across registry models within provider — same prior used to allocate uncovered volumes, applied symmetrically across the partition.
5. **For covered models** — canonical Option B within the covered group:
   - ref_price = Σ(p × s) / Σ(s) where s is per-model rankings token count
   - total_covered_vol = R_covered / ref_price (in mtok per quarterly period)
   - vol_i = total_covered_vol × s_i / Σ(s) for each covered model
6. **For uncovered models** — by `prior`:
   - **"price_implied" (default, δ)**: each model gets R_uncovered/n_uncovered revenue share; vol_i = (R_uncovered / n_uncovered) / p_i
   - **"equal_volume" (β, Phase 10 comparison)**: ref_price = mean(p) over uncovered; total_uncovered_vol = R_uncovered / ref_price; vol_i = total_uncovered_vol / n_uncovered
7. **Scale normalisation** (canonical step 2.f): factor = R / Σ(vol × p) across the union of covered + uncovered. By construction with steps 5 + 6 the factor is ≈ 1.0; the step is a safety check against accumulated floating-point drift, applied uniformly across all models so the revenue identity holds exactly post-scaling.
8. **Convert quarterly → 7-day**: vol_7d_i = vol_quarterly_i × 7 / 91.25 (calendar-stable: 365.25/4 days per quarter).
9. **Emit one panel row per (provider, model, as_of_date)** with attestation_tier="B", source="tier_b_derived", volume_mtok_7d populated, prices from panel (median across rows on `as_of_date`) with registry baseline as fallback.

**Why steps 5/6 split provider revenue between covered and uncovered fractions, rather than skipping uncovered**: prompts.md 5b.1's "Missing OpenRouter coverage for a model → skipped with warning" describes the behaviour for a single uncovered model in an otherwise-covered provider. Applied literally to a provider with mixed coverage, "skipping uncovered" loses the revenue allocation for those models entirely — Σ(vol × p) over the emitted rows < R, and the methodology's revenue-identity invariant breaks. Step 4's coverage-share assumption preserves the identity by giving uncovered models a defined revenue share, which the prior (price_implied or equal_volume) then converts to per-model volume. The "skip with warning" path in prompts.md is now interpreted as "log a warning that coverage was incomplete" rather than "drop the model from the output".

**Phase 10 obligation**: `derive_tier_b_volumes(..., prior="equal_volume")` runs as a sensitivity comparison alongside the default "price_implied" run. Phase 10 finding `tier_b_prior_sensitivity.md` reports the index divergence and informs whether v1.3 should adopt one prior canonically.

**v0.2/v1.3+ enhancement paths queued**:
- **Replace fallback prior with author-level market_share + secondary signals** (analyst-published model-mix estimates; e.g. Sacra's "60-70% of OpenAI API revenue from frontier-class"). The rankings JSON's `market_share` field provides author-level totals for top-9 providers; mistral and alibaba currently fall outside even that.
- **Generalise model-level rankings matching to the most recent dated variant of a base slug** — currently only exact base-slug match works (deepseek). Loosened matching (e.g. `claude-4.7-opus` → `claude-opus-4.7` with reordering) could lift from 1/16 to 4/16 model coverage.
- Either path is a v1.3+ methodology refinement, not an MVP shim.

**Methodology section**: 3.3.2 (three-tier volume hierarchy, Tier B implementation specifics — MVP scope per the May 2026 decision and the prior choice clarified for v0.1 here).

## 2026-04-29 — Phase 6 slot-level quality gate parameters

**Decision**: `apply_slot_level_gate` runs Tier A only with deviation_pct=0.15, trailing_window_days=5, current-day excluded from the rolling mean (shift before rolling), gate computed against the (contributor, constituent) 5-day trailing average of posted output prices indexed by `observation_date` (panel-recorded calendar days, not 5 actual calendar days — equivalent for daily-cadence Phase 2 panels). Insufficient-history rows (fewer than 5 prior panel days) are skipped without firing.

**Context**: Methodology Section 4.2.2 specifies "any [slot] price deviation exceeding 15% from the constituent's 5-day trailing average ... is excluded from that day's TWAP." The methodology does not specify (a) whether the trailing window is calendar days or panel-recorded days, (b) whether current-day-self is included in the trailing average, or (c) what to do with rows whose history is shorter than 5 days.

**Alternatives considered**:
- **Calendar-day rolling with NaN-fill on missing panel days** — most literal. Rejected because Phase 2 panels are daily-cadence with no gaps; the implementations are equivalent here, but panel-day rolling avoids a future production-data assumption (continuous calendar coverage) the MVP doesn't need.
- **Include current day in trailing mean** — biases the threshold toward "today is normal" by definition; today's outlier slot would influence its own threshold. Rejected.
- **Apply gate from day 1 with a bootstrap (e.g. registry baseline as prior)** — adds complexity, requires a baseline-prior decision per constituent, and mixes synthetic-prior contamination into early-period firings. Rejected — first 5 days simply don't get gated, accepted limitation.

**Rationale**: shift(1).rolling(5, min_periods=5) is the canonical "trailing average excluding self" pandas idiom; it preserves the methodology's "vs trailing average" semantic without ambiguity. First-5-days exclusion is a known acceptance criterion in project_plan Phase 6 ("First 5 days of each (contributor, constituent) series: gate not applied"). Documented here so future readers don't trip on the absence of firings on early-period rows.

**Impact**: Slot-level gate fires only on Tier A rows with ≥5 prior panel days. Tier B/C rows are unprocessed (no slot dimension by construction). Boundary behaviour: a 14% deviation passes (`abs(dev) > 0.15` is the firing condition, not `>=`), 16% fires.

**Tier A scope clarification**: The gate operates only on Tier A panel rows. Tier B is derived from quarterly revenue with no slot dimension; Tier C is OpenRouter aggregate with no slot dimension. Both rely on tier haircuts (0.9 / 0.8) as confidence discounts and structural defenses (revenue disclosure for B, third-party-source for C) for manipulation resistance, not slot-level gating. Section 4.2.2 doesn't explicitly state tier scope; the gate's mechanics — comparing 32 reconstructed intraday slots — are only well-defined for Tier A panel data.

**Phase 10 obligation**: Phase 10 should report Tier A vs Tier B vs Tier C contribution percentages per index. If Tier B/C dominate (per the cross-tier magnitude finding in the 2026-04-29 priority fall-through entry), the absence of slot-level gating on the dominant tier is a methodology gap worth surfacing.

**v1.3+ enhancement path**: If real Tier C data evolves to provide intraday granularity (per-minute or per-hour rankings updates from OpenRouter), Section 4.2.2 should be revisited for whether the gate extends to Tier C. Tier B is unlikely to ever have intraday data given its quarterly revenue derivation.

**Methodology section**: 4.2.2 (data quality checks).

## 2026-04-29 — Phase 6 continuity check: Tier A flag-only at 25%

**Decision**: `apply_continuity_check` adds a `requires_verification` boolean column flagging Tier A rows whose day-over-day posted output price changes by more than 25% from the prior panel-recorded day's posted price. The flag is informational; the row is included in TWAP and aggregation regardless of flag state.

**Context**: Methodology Section 4.1 specifies: "price changes exceeding 25% from the prior observation trigger a manual verification step before the update is incorporated." Strict reading would block the update pending review. CLAUDE.md's working-summary states v0.1 behaviour as "flag and log, include anyway unless also failing 5-day gate."

**Alternatives considered**:
- **Block until manual verification** — production-correct per Section 4.1, but the MVP has no Index Committee or Data Governance Officer; "verification" has no actor. Rejected.
- **Block + auto-clear after N days** — adds time-window logic the methodology doesn't authorise. Rejected.
- **Flag + include** (chosen) — preserves the methodology's signal (flag is recorded, downstream readers see which rows would have triggered verification) without inventing an unauthorised auto-clear mechanism. The slot-level gate provides the operative outlier defence; the continuity flag is a secondary diagnostic.

**Rationale**: The slot-level gate (15% threshold against 5-day trailing average) is a narrower test than the continuity check (25% day-over-day). A row that fails continuity but not the slot gate is a directionally-large but plausibly-real move; flagging it without blocking allows v0.1 backtests to run while preserving the audit trail for v1.3+ verification-workflow design.

**Impact**: `requires_verification` column added downstream. Tier B/C rows always False (continuity check is Tier A semantic). v1.3+ may convert this to a blocking check once governance is implemented.

**Methodology section**: 4.1 (price continuity check).

## 2026-04-29 — Phase 6 staleness rule: v0.1 operational extension at 3 days

**Decision**: `apply_staleness_rule` adds an `is_stale` boolean column flagging Tier A rows whose posted output price has not changed across the prior `max_stale_days` panel-recorded rows (default 3). With max_stale_days=3, a row is stale iff today's price equals each of the prior 3 panel rows for the same (contributor, constituent) — equivalently, the 4th-or-later consecutive same-price panel day.

**Context**: Methodology v1.2 does not specify a staleness rule. CLAUDE.md's working summary lists `staleness_max_days: 3` as a v0.1 operational extension (config/index_config.yaml). The motivation is detection of contributor blackouts and frozen-price scenarios (Phase 3 scenario 3 stale_quote) where a contributor stops updating but continues to submit identical prices.

**Alternatives considered**:
- **Omit staleness rule entirely until v1.3 methodology adds it** — leaves scenario 3 with no detection layer in v0.1. Rejected.
- **Stricter rule (max_stale_days=2)** — a 3-day stale prior is normal for low-activity efficiency-tier models; over-fires. Rejected.
- **Looser rule (max_stale_days=7)** — undetectable scenario 3 across the Phase 10 28-day stale_quote window without staleness firings. Rejected.
- **3-day default** (chosen) — aligns with the suspension threshold (3 consecutive days) and matches realistic enterprise pricing-update cadence (most posted prices change less often than weekly).

**Rationale**: Staleness is a Tier A operational diagnostic, not a methodology test. The v1.3 methodology revision should consider whether staleness graduates to canonical (with a stated threshold) or remains operational. For v0.1 the rule is documented here so the Phase 10 stale_quote scenario has detection coverage and the v1.3 conversation has prior art.

**Impact**: `is_stale` column added downstream. Tier B/C always False (staleness is per-contributor-cadence, doesn't apply to revenue-derived or rankings-derived rows). Flagged for methodology v1.3 inclusion.

**Methodology section**: not in v1.2; v0.1 operational extension.

## 2026-04-29 — Phase 6 suspension counter: 3 consecutive day-level fires, sticky

**Decision**: `compute_consecutive_day_suspensions` emits one row per (contributor, constituent) pair on the first calendar date when that pair accumulates 3 consecutive panel-recorded days each carrying ≥1 slot-level gate firing. Suspension is sticky — only the first crossing date is recorded; downstream consumers treat the constituent as suspended from that date forward.

**Context**: Methodology Section 4.2.2 specifies "Three consecutive intervals failing this check triggers human review of the constituent." The literal reading is 15-minute intervals (3 × 15min = 45 minutes within one day). The MVP has no human reviewer; the literal-interval rule has no actor and would over-fire on any genuine intraday move.

**Alternatives considered**:
- **Literal 3-consecutive-15-minute-slot rule** — fires on any 3-slot run; without an Index Committee to action the trigger, becomes a noise channel. Rejected.
- **3 consecutive 15-min slots within one day, suspending automatically** — aggressive auto-suspension; a single legitimate price move (slot 17, 18, 19 all 15%+ deviations) would suspend a constituent until reset. Rejected — methodology authorises HUMAN review, not auto-suspension, and v0.1 cannot execute the human step.
- **3 consecutive panel days with any-slot-fires, sticky** (chosen) — translates the methodology's "consecutive failures requires review" intent to the day-level cadence v0.1 actually runs at. The threshold (3) is preserved; the unit shifts from intervals to days. Sticky semantics avoid suspend/unsuspend churn that an auto-rearm rule would create.

**Rationale**: This is a v0.1 simplification, not a methodology revision. The methodology's intent — repeated quality failures should trigger investigation — is preserved at a unit appropriate to a daily-fix MVP without an Index Committee. Phase 10 Scenario 4 (correlated_blackout) tests this rule's behaviour under realistic blackout patterns. v1.3+ should clarify whether the "3 consecutive" rule operates on intervals (production-only, requires reviewer) or days (operationally executable in automation).

**Impact**: Suspension rows feed downstream aggregation as a "do not include this constituent's price in tier median or weight from this date forward" signal. Phase 7 implements the consumption side. Sticky semantics: a suspended constituent does not re-enter the index without explicit operational unsuspend (out of scope for v0.1).

**Threat coverage gap**: The canonical 45-minute window (3 × 15-min slots) catches sustained intraday manipulation; the v0.1 day-level window catches sustained inter-day patterns. A manipulator pushing 15%+ for 1 hour intraday is caught by canonical, not v0.1; a manipulator running a 1-hour-per-day pattern for 3 days is caught by v0.1, not canonical. The two readings have meaningfully different threat surfaces, which is why v1.3 should specify which (or both) is the canonical rule.

**Phase 10 sensitivity test**: Run Scenario 1 (fat_finger 1-slot spike) and Scenario 6 (sustained_manipulation 60-day) under both rules. If 45-minute rule catches scenarios that 3-day rule misses (or vice versa), the methodology gap has empirical evidence.

**Methodology section**: 4.2.2 (data quality checks — adapted from interval-cadence to day-cadence for v0.1).

## 2026-04-29 — compute_panel_twap multi-event reconstruction

**Decision**: `tprr.twap.reconstruct.compute_panel_twap` upgraded to honour multiple change events per (contributor, constituent, date), mirroring the segmentation logic of the public `reconstruct_slots` function. The internal `_build_event_lookup` now stores a list of event records per key (sorted by `change_slot_idx`); `compute_panel_twap` builds the 32-slot price array by walking those events the same way `reconstruct_slots` does.

**Context**: The pre-revision `_build_event_lookup` stored at most one event per key; later events overwrote earlier ones on the same day. Phase 2 panels never exercised the multi-event path (the Phase 2b generator dedupes by key), but Phase 3 outlier-injection scenarios (fat_finger, intraday_spike) emit two events per day. Phase 6 testing of those scenarios end-to-end through compute_panel_twap requires multi-event support.

**Alternatives considered**:
- **Defer until Phase 7 aggregation surfaces the bug** — accepts a known incorrect-output region of the input space without test coverage. Rejected; the docstring already committed to the revision and the helper logic is already proven correct in `reconstruct_slots`.
- **Implement separately in compute_panel_twap with a different code path** — duplicates the segmentation logic and risks divergence. Rejected.
- **Mirror `reconstruct_slots` segmentation** (chosen) — single conceptual model for multi-event reconstruction, applied in both the per-row public API and the bulk panel pipeline. Verified byte-identical on Phase 2 single-event panels (`test_revision_preserves_single_event_behaviour_byte_identical` and the new `test_compute_panel_twap_multi_event_byte_identical_to_reconstruct`).

**Rationale**: Bug fix, not a methodology change. Brings the bulk panel-TWAP path into alignment with the canonical per-row reconstructor. No change to computed index values on existing Phase 2 panels; correct behaviour now extends to Phase 3 multi-event scenario panels feeding Phase 7.

**Impact**: Phase 7 aggregation can run end-to-end against scenario 1 (fat_finger) and scenario 9 (intraday_spike) panels without silent overwrite of the second event. No methodology section change.

**Methodology section**: 4.2.1 (TWAP daily fix — implementation correctness).

