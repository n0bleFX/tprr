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
