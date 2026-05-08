| NOBLE Argon · Token Price Reference Rate Index Methodology Specification v1.3 | Confidential noble.markets |
| :---- |

**Effective date**: 2026-05-06

**Implementation reference**: v0.1 reference codebase, commit `efa5e0e`, tag `v0.1-phase-10-complete`

**Revision history**: see §6

**Document scope**: This document is the canonical TPRR Methodology Specification. The accompanying TPRR Development and Validation document (`docs/tprr_development.md`) covers methodology development history, empirical validation findings, future product architecture, and forward roadmap. The pre-Phase-7H methodology document is preserved in git history; the v1.3 specification supersedes it as the canonical methodology of record.

# **1. Executive Summary**

The Token Price Reference Rate (TPRR) is a family of standardized benchmark indices published by Noble that measure the real-time and historical cost of AI inference across the leading large language models. TPRR provides the financial industry's first independently governed, transparent, and replicable pricing standard for the AI inference market.

TPRR is denominated in dollars per million tokens (Mtok), following the industry standard of how inference is currently sold today. A token is a small number of characters (~4) that is ingested, or produced, by an LLM. It is the core economic unit of inference, and as such is the smallest possible denomination by which to measure the cost of AI operations.

As enterprise AI adoption moves from experimentation to operational scale, AI inference costs have become a material and growing line item on corporate balance sheets. Despite this, no standardized pricing reference exists. This is the gap that Noble is purpose-built to fill. TPRR serves as the foundation for a new asset class: AI inference, with a pricing benchmark to compare realized costs against, and with financial derivative instruments that allow enterprises to hedge token price exposure, and financial institutions to structure, price, and trade those instruments with reference to the trusted benchmark.

However, there is a wide variation in the cost of inference across different LLMs, much like other commodities (e.g. electricity, gasoline) have grades. As such, Noble publishes three TPRR indices, each targeting a distinct layer of the AI model market and the cost of inference across each:

| Index | Name | Description |
| :---- | :---- | :---- |
| TPRR-F | Frontier | **Premium tier**. Highest-capability frontier models. |
| TPRR-S | Standard | **Utility tier**. Mid-tier general-purpose models widely deployed in enterprise production workloads. |
| TPRR-E | Efficiency | **Economy tier**. Small, fast, cost-optimized models suited to high-volume, latency-sensitive tasks. |

Two cross-index analytics series and one blended analytics series are derived from the core indices:

| Metric | Name | Definition |
| :---- | :---- | :---- |
| TPRR-FPR | Frontier Premium Ratio | **TPRR-F divided by TPRR-S**. Measures the cost premium commanded by frontier capability over standard tiers. |
| TPRR-SER | Standard Efficiency Ratio | **TPRR-S divided by TPRR-E**. Measures the cost premium of mid-tier models over economy alternatives. |
| TPRR-B | Blended Analytics Series | **Informational series** only (not used for derivative settlement); blends output and input token prices at a 75:25 (output:input) ratio to support total cost benchmarking. |

The v1.3 methodology is built on four core mechanisms:

1. **Dual-weighted aggregation formula**: volume weight × exponential median-distance weight × constituent price, anchored on output token prices and aggregated via a TWAP daily fix across 32 fifteen-minute slots in the 09:00–17:00 UTC window (§3.3.1, §4.2.1).

2. **Three-tier attestation hierarchy**: Tier A contributor-attested, Tier B revenue-derived, Tier C transaction-verified market proxy, with **continuous blending** across tiers under bias-aware confidence haircuts (§3.3.2).

3. **Slot-level data quality gate**: 15% deviation from 5-day trailing average, coupled with asymmetric bidirectional **suspension / reinstatement** criteria (3-day exclude / 10-day reinstate; §4.2.2).

4. **Exponential median-distance weight**: decay parameter λ=3 that fades constituents whose prices deviate from the tier median (§3.3.3).

# **2. Market Context and Rationale**

## **2.1 The AI Inference Cost Problem**

Enterprise spending on AI inference is growing at a rate that few finance functions were equipped to anticipate. What began as a discretionary R&D line item buried within a larger IT budget has, for many organizations, become a significant and unpredictable operational expense. Leading enterprises are now spending tens of millions of dollars annually on AI inference with limited ability to forecast or benchmark, let alone hedge, that cost.

Unlike cloud compute or software licensing, markets where pricing is broadly transparent and benchmarking infrastructure is mature, the AI inference market lacks standardized pricing. Prices are set unilaterally by providers, agreed to bilaterally between providers and customers, change without notice, vary by model version and tier, and are quoted in unit economics (price per Mtok) that are not comparable across providers without normalization.

This creates three compounding problems for enterprise finance:

1. **Budgeting uncertainty**: forecasted AI costs cannot be reliably anchored to a market reference, creating variance that falls through to earnings.

2. **No hedging instruments**: without a recognized benchmark, there is no basis upon which derivative instruments can be structured or priced.

3. **No performance attribution**: enterprises have no objective basis for evaluating whether the model tier they are consuming represents value relative to alternative tiers and/or models.

## **2.2 The Case for a Benchmark Standard**

TPRR addresses this structural gap by providing what every functioning financial market requires before derivatives and risk transfer instruments can develop: a trusted, transparent, independently governed pricing reference.

The historical precedent is clear. LIBOR created the interest rate derivatives market. WTI and Brent created the oil derivatives market. Henry Hub created the natural gas derivatives market. In each case, bilateral contract-based pricing between supplier and consumer arose first, then an index was developed to create a standard benchmark, then ultimately derivatives were developed. Not the other way around. TPRR is designed precisely to serve as the first step and is the foundational piece of infrastructure set to underpin an emerging AI inference asset class.

| *Noble's strategic position: by establishing TPRR as the market standard before any competing benchmark emerges, Noble secures the first-mover advantage that defines index businesses, where the winning standard is, by network effect, the only standard.* |
| :---- |

## **2.3 Currency Dimension: FX-Hedged TPRR Variants**

For enterprises operating outside the United States, AI inference cost is a dual exposure: token price risk denominated in USD, compounded by currency risk between the user's operating currency and USD. A European company paying for frontier-tier inference tokens in USD faces both the risk of the provider increasing its per-token price (USD per Mtok) and the risk of EUR/USD movement increasing (or decreasing) its effective cost.

Noble will in the future publish currency-neutral TPRR variants for EUR, GBP, and JPY, the three largest non-USD enterprise AI spending geographies. These variants translate TPRR into local currency terms using mid-market FX rates sourced from Noble's Xenon FX intelligence layer, enabling non-USD enterprises to track, benchmark, and ultimately hedge their total AI inference cost in functional currency terms.

This cross-product architecture (TPRR indices layered with Xenon FX intelligence) will be a structural differentiator unique to Noble, creating the foundation for currency-neutral AI inference derivative instruments.

# **3. Index Architecture**

## **3.1 Index Universe and Constituent Eligibility**

TPRR indices are constructed from a defined universe of AI inference providers whose models meet eligibility criteria across five dimensions:

| Criterion | Requirement |
| :---- | :---- |
| Commercial Availability | The model must be available via a publicly documented API with programmatic access. (Internal or research-preview models are excluded.) |
| Pricing Transparency | The model provider must publish explicit per-token pricing (output and input, in USD per Mtok) on a publicly accessible pricing page. |
| Enterprise Adoption | The model must demonstrate material enterprise production usage, evidenced by disclosed customer counts, third-party usage attestation, or Noble contributor data. |
| Operational Stability | The model provider must have demonstrated continuous API availability of at least 99.5% over the preceding 90 days, as measured by Noble's monitoring infrastructure. |
| Version Governance | The provider must maintain stable versioned model endpoints (models subject to silent capability updates without version increments are ineligible). |

## **3.2 Tier Classification**

Each eligible model is classified into one of three index tiers. Tier classification is determined by the Index Committee (§5.1), applying the following criteria:

| Index tier | Capability profile | Pricing profile | Representative models (v0.1 reference registry) |
| :---- | :---- | :---- | :---- |
| Frontier (TPRR-F) | State-of-the-art reasoning, multimodal, long-context; highest benchmark performance | Highest per-token cost; typically >$10/M output tokens | openai/gpt-5-pro, anthropic/claude-opus-4-7, google/gemini-3-pro |
| Standard (TPRR-S) | Strong general-purpose performance; production-grade for most enterprise tasks | Mid-range; typically $1–$10/M output tokens | openai/gpt-5-mini, anthropic/claude-sonnet-4-6, google/gemini-2-flash |
| Efficiency (TPRR-E) | Optimized for speed and volume; lower capability ceiling but highly cost-effective | Sub-$1/M output tokens; often sub-cent for input | google/gemini-flash-lite, deepseek/deepseek-v3-2, openai/gpt-5-nano |

The full v0.1 reference constituent set is documented in `config/model_registry.yaml`. Tier classification is reviewed quarterly by the Index Committee (§5.2); models whose capability or pricing profile materially shifts may be reclassified.

## **3.3 Weighting Methodology**

### **3.3.1 Principle: Output Token Price as the TPRR Basis**

TPRR is calculated using output token prices only. As the tokens generated by the model in response to a query, output tokens are by definition the scarce, compute-intensive resource that drives AI inference economics, with little way to operationally control volume. Generating each output token requires a full forward pass through the model; this is the cost that scales directly with enterprise AI workload volume and cannot be reduced through operational behavior such as prompt optimization.

Input token costs, by contrast, are primarily a function of prompt engineering discipline, context management, and other operational levers within the enterprise's direct control. Input token costs do not present the same level of financial risk requiring derivative hedging. Mixing input token costs into a settlement benchmark would introduce basis risk between the hedge and the actual exposure being managed, since input consumption varies by workload design rather than by market price alone.

By anchoring TPRR-F/S/E exclusively to output token pricing, Noble produces benchmark indices with a clear and defensible economic rationale: **TPRR measures the cost of AI-generated work, the unit that scales with production volume and is subject to provider pricing decisions outside the enterprise's control.**

Each constituent's contribution to its index tier is determined by a dual-weighted formula combining a volume weight (§3.3.2: how much of the market the model represents under continuous blending across the three-tier attestation hierarchy) and an exponential median-distance weight (§3.3.3: how consistent the model's price is with the rest of its index tier).

For index tier T ∈ {F, S, E}, let i ∈ T index the constituents in tier T. The dual-weighted index value on fixing date d is:

**TPRR_T(d) = Σ_{i ∈ T} [ w_vol_i × w_exp_i × P̃_i(d) ] / Σ_{i ∈ T} [ w_vol_i × w_exp_i ]**

Here P̃_i(d) is the constituent's blended TWAP-derived daily output price (§3.3.2.2; §4.2.1 specifies the daily TWAP construction); w_vol_i is the constituent's blended volume weight (§3.3.2.2); w_exp_i is the exponential median-distance weight (§3.3.3); and the formula is evaluated on each daily fix date d.

A constituent must carry material market volume AND price consistently with its index tier peers to contribute meaningfully to the index. This dual-weighting structure makes TPRR robust to both low-volume constituents with anomalous prices and high-volume constituents that deviate from the index tier's core pricing economics.

### **3.3.2 Volume Attestation: Three-Tier Data Hierarchy**

AI inference providers generally do not disclose per-model token volumes publicly. This is the central methodological challenge facing any AI inference index: without reliable volume data, an index must default to equal weighting or proxy weighting, **both of which reduce accuracy**.

The methodology addresses this through a three-tier attestation hierarchy with continuous blending under bias-aware confidence haircuts. The hierarchy comprises three data sources with distinct bias profiles (§3.3.2.1); contributions are blended continuously across tiers (§3.3.2.2); volume contributions are normalized to within-tier shares to make cross-tier blending dimensionally consistent (§3.3.2.3); a tier-eligibility threshold ensures a minimum of three independent observations before a tier contributes to the blended price (§3.3.2.4).

#### **3.3.2.1 Three-Tier Hierarchy with Bias Profiles**

The methodology applies the following three-tier data hierarchy:

| Tier | Name | Source | Confidence haircut |
| :---- | :---- | :---- | :---- |
| A | Contributor-Attested | Direct API pull from contributor billing systems (e.g., Anthropic Admin API, OpenAI Usage API, GCP Cloud Billing, AWS CloudWatch/Cost Explorer). Provider-attested billing data that matches the contributor's invoice. | 1.00 |
| B | Revenue-Derived Proxy | Publicly disclosed provider revenue data (Anthropic, OpenAI, Google quarterly/annual reports), supplemented by third-party analyst estimates. Provider-level revenue allocated across models using disclosed product mix and market share data. | 0.50 |
| C | Transaction-Verified Market Proxy | OpenRouter's publicly available, transaction-derived model volume data, filtered by Noble's Index Committee to exclude free-tier models and non-enterprise-relevant usage. | 0.80 |

No single tier is unbiased; in the present stage of the AI inference market, no single source of truth exists. The three-tier hierarchy is designed around triangulation across sources with distinct bias profiles rather than primacy of any single "ground truth" source. A finding that emerges across all three tiers is more robust than one supported by only one tier; a divergence across tiers signals data-quality investigation rather than methodology failure. This framing is consistent with mature commodity benchmark practice. ICE Brent does not treat physical North Sea cargoes as ground truth against which forward trades are biased; it treats both as legitimate signals with documented coverage and bias profiles.

The haircut ordering is A (1.00) > C (0.80) > B (0.50), reflecting bias-chain length rather than absolute bias magnitude. Tier C is direct third-party measurement (single-step bias from user-base composition); Tier B is multi-step bias from the revenue-allocation chain (provider revenue → API share → within-provider model split). The numerical haircut values are Index Committee judgments calibrated against the bias-chain rationale documented above and are reviewed quarterly per §5.2.

Revenue-derived data is preserved as Tier B, rather than restacking to Tier C, in anticipation of greater future transparency around provider token usage by tier. For example, as private-company AI providers transition to public reporting, tier-level token disclosures are expected to become more readily available, at which point Tier B's bias chain shortens considerably. At this point, provider-reported data will provide a superior signal than Tier C's market proxy data.

Each tier's bias profile is documented per the table below. Bias direction, magnitude (where empirically estimable), strength, and limitation are specified per tier:

| Tier | Bias direction | Bias magnitude | Strength | Limitation |
| :---- | :---- | :---- | :---- | :---- |
| A | Enterprise-segment overweight; smaller-customer underrepresented | Depends on panel composition; reference panel calibrated to plausible enterprise mix | Highest precision on enterprise spend; direct attestation; auditable | Structural sample of enterprise users only; misses developer / research / consumer segments |
| B | Upward bias from non-API revenue inclusion (subscriptions, licensing, professional services); upward bias from Enterprise flat-rate API tiers where effective per-token rates differ from published rates | Plausibly 30–50% upward on Tier B implied volumes for some providers; reflected in 0.5 haircut | Whole-provider scope; auditable revenue data for public companies | Revenue-to-volume derivation chain compounds bias; private-company revenue requires analyst triangulation; "API revenue" definition varies across providers |
| C | Developer / researcher-segment overweight; cost-efficiency-seeking user base; potential APAC / open-source overweight | Reference snapshot indicates substantial non-registry coverage in OpenRouter rankings, reflecting OpenRouter's developer-segment user mix | Direct third-party measurement; no provider influence; verifiable data source | Small slice of total enterprise inference market; user-base self-selection (developers / researchers seeking cost efficiency); regional skew |

The haircut values reflect the relative confidence appropriate to each tier given its bias profile and are reviewed quarterly by the Index Committee (§5.2).

#### **3.3.2.2 Continuous Blending of Tiers**

For each constituent on each fixing date, the index aggregation blends contributions from all attestation tiers for which the constituent has data. Default blending coefficients are:

| Attestation tier | Default coefficient |
| :---- | :---- |
| A | 0.6 |
| C | 0.3 |
| B | 0.1 |

The blending is symmetric across volume and price contributions. Let i index constituents, t index attestation tiers (t ∈ {A, B, C}), and write:

- coefficient_t for the blending coefficient at tier t
- haircut_t for the confidence haircut at tier t (per §3.3.2.1)
- volume_{i,t} for constituent i's raw volume in tier t
- within_tier_share_{i,t} for the within-tier share defined in §3.3.2.3
- P̃_{i,t} for tier t's collapsed (TWAP-derived) daily price for constituent i

The constituent's blended volume contribution is:

**w_vol_i = Σ_t [ coefficient_t × within_tier_share_{i,t} × haircut_t ]**

The constituent's blended price is:

**P̃_i = Σ_t [ coefficient_t × P̃_{i,t} ]**

Both formulas sum over the attestation tiers for which constituent i has data. When a tier has no data for the constituent, that tier's term is zero in both formulas, and the coefficients redistribute proportionally to the tiers with data such that Σ_t coefficient_t = 1 across the contributing tiers. For example, if constituent i has data in tiers A and C but not B, the effective coefficients are coefficient_A' = 0.6 / (0.6 + 0.3) = 0.667 and coefficient_C' = 0.3 / (0.6 + 0.3) = 0.333. The same redistribution applies when a tier is dormant under the tier-eligibility threshold (§3.3.2.4).

The blended values w_vol_i and P̃_i feed the dual-weighted formula in §3.3.1: w_vol_i contributes to the volume-weight side, and P̃_i is the constituent price that combines with the exponential median-distance weight w_exp_i (§3.3.3).

**Tier B price specification**: Tier B's price contribution is the provider's published dollars per Mtok output rate for the constituent on the fixing date, as documented in the provider's public API pricing page. Tier B's bias profile (§3.3.2.1) primarily affects volume estimates rather than price estimates. Tier B prices are observable and verifiable, while volume derivation involves the compounded chain documented above. Tier B price sourcing may be extended in production to include provider-attested rate cards from contributor billing systems where these differ from published rates (e.g., enterprise tier discounts).

Continuous blending across all available tiers, rather than single-tier selection per constituent per day, produces smooth transitions across tier-coverage changes. Cross-tier magnitude differences between Tier A panel-sum volumes and Tier B revenue-derived volumes would otherwise create cliff-edge dynamics if a constituent's selected tier changed abruptly as contributor counts crossed the minimum-3 threshold (§3.3.2.4).

#### **3.3.2.3 Within-Tier-Share Normalization**

Within-tier-share normalizes each (constituent, attestation tier) volume to the proportion of that tier's total volume that the constituent represents, before haircut application:

**within_tier_share_{i,t} = volume_{i,t} / Σ_{j ∈ active(t)} volume_{j,t}**

where active(t) is the set of constituents with valid volume data in attestation tier t for the fixing date. By construction, within_tier_share_{i,t} ∈ [0, 1] for all i, and Σ_{i ∈ active(t)} within_tier_share_{i,t} = 1 within each tier.

The normalization ensures cross-tier blending under §3.3.2.2 is dimensionally consistent. Tier A panel-sum volumes are not directly comparable to Tier B revenue-derived volumes; without within-tier-share normalization, the larger-magnitude tier would dominate the blending sum regardless of haircut application. Within-tier shares remove the magnitude gap by re-expressing each constituent's contribution as a fraction of its own tier's total.

#### **3.3.2.4 Tier-Eligibility Threshold under Continuous Blending**

An attestation tier with fewer than three active constituents within an index tier is **dormant** for that index tier. A dormant tier contributes nothing to either the volume or price blending sums (§3.3.2.2); its blending coefficient redistributes proportionally to active tiers per the redistribution rule in §3.3.2.2.

Formally, for constituent i in index tier T (T ∈ {F, S, E}) on fixing date d, attestation tier t is eligible if and only if:

**| active(t, T, d) | ≥ tier_min_constituents_for_blending**

where active(t, T, d) is the set of constituents in index tier T with valid volume and price data in attestation tier t on date d. The canonical threshold value is tier_min_constituents_for_blending = 3.

The threshold extends the minimum-3 epistemic principle from the contributor → constituent layer (§4.2.4.1) to the constituent → attestation-tier layer. The same principle applies symmetrically: at every aggregation step combining independent observations, a minimum of three observations is required. Without the threshold, a tier with one constituent would have within_tier_share = 1.0 by construction; a degenerate normalization that does not represent a market-wide tier price.

**Audit trail**: dormant-tier per-tier rows are preserved in the constituent-decision audit. Two cases:

- When the constituent has data in at least one eligible tier, dormant-tier rows carry `coefficient = 0`, `w_vol_contribution = 0`, `included = True`. The constituent contributes to the index via its eligible tiers; the dormant-tier rows are visible to auditors as "data observed but did not contribute to the blended output."
- When the constituent has data only in dormant tier(s), dormant-tier rows carry `coefficient = 0`, `w_vol_contribution = 0`, `included = False`, with `exclusion_reason = tier_ineligible_for_blending`. The constituent is not included in the index because it has no eligible-tier coverage.

Auditors can therefore distinguish three audit states for any (constituent, attestation tier, fixing date) triple: contributing (`included = True`, `coefficient > 0`); dormant-but-observed (`included = True`, `coefficient = 0`); and ineligible-only (`included = False`, `exclusion_reason = tier_ineligible_for_blending`).

**Smooth-activation property**: as Tier C coverage expands past three constituents per index tier, Tier C activates automatically without requiring a methodology version increment. The methodology behaves identically pre- and post-coverage-expansion at the published level; only the empirical contribution of Tier C to the blended weights changes.

### **3.3.3 Exponential Median-Distance Weighting**

Within each TPRR index tier (F, S, E), constituent prices are weighted by their distance from the index tier's median output token price. This mechanism is adapted from established commodity benchmark methodology and ensures that constituents whose pricing is inconsistent with the rest of their index tier carry proportionally *less* influence on the index, without requiring hard exclusion thresholds.

Given the AI inference market is still in its infancy, this is a superior method for handling disparate pricing than enforcing a hard exclusion such as via a trimmed or Winsorized mean.

For each constituent i in an index tier, the exponential weight is:

**w_exp_i = exp( –λ × | P̃_i – P̃_median | / P̃_median )**

where P̃_i is the constituent's blended (continuous-blending-weighted) output token price (§3.3.2.2), P̃_median is the median across the index tier's blended prices on the fixing date, and λ (lambda) is the decay parameter controlling how aggressively outliers are faded. v1.3 sets λ = 3 at inception. The effect at representative distances from the index tier's median:

| Distance from index tier median | w_exp |
| :---- | :---- |
| 0% (at median) | 1.000 |
| 5% | 0.861 |
| 10% | 0.741 |
| 20% | 0.549 |
| 30% | 0.407 |
| 50% | 0.223 |
| 100% | 0.050 |

The exponential mechanism is preferred over hard threshold exclusion for two reasons. First, it is continuous rather than binary: there is no cliff edge at which a constituent is suddenly included or excluded. This eliminates a manipulation vector in which a provider positions its price just inside a hard threshold. Second, it is self-calibrating: as the index tier's constituent set evolves and the median shifts, each constituent's weight adjusts automatically without requiring the Index Committee to revise thresholds.

Because the exponential weight multiplies against the volume weight in the dual-weighted formula (§3.3.1), a constituent must be both widely used (high volume weight) and competitively priced (high exponential weight) to materially influence the index. A provider or participant seeking to move TPRR in its favor by adjusting price away from the index tier's median sees its exponential weight decline, making manipulation self-defeating by design.

The λ parameter is reviewed quarterly by the Index Committee (§5.2). The canonical λ=3 setting is calibrated on manipulation-resistance and effective-constituent-breadth grounds; future Committee review may revise λ where market evolution warrants.

| *The dual-weighting structure (volume attestation under continuous blending [§3.3.2] times exponential median-distance [§3.3.3]) produces a benchmark robust to both data-quality variation and strategic price manipulation. A constituent needs both real market share and competitive pricing to move TPRR; neither alone is sufficient.* |
| :---- |

### **3.3.4 TPRR-B: The Blended Analytics Series**

Separately from the core TPRR indices, Noble publishes TPRR-B: a blended analytics series that combines output and input token prices for enterprises seeking to benchmark total AI inference cost inclusive of input consumption. TPRR-B is an informational series only and is not intended for use as a settlement reference.

TPRR-B is calculated using the following blended price formula:

**P_blended_i = 0.25 × P̃_in_i + 0.75 × P̃_out_i**

The 75:25 (output:input) weighting reflects the observed average token consumption ratio across Noble's reference contributor dataset. The ratio is reviewed quarterly by the Index Committee (§5.2). As contributor data matures, Noble may publish workload-specific TPRR-B variants (RAG, agentic, code generation) as supplementary analytics series.

# **4. Calculation and Publication**

## **4.1 Data Collection and Integrity Framework**

Noble's automated pricing ingestion layer polls provider pricing pages and API endpoints at 15-minute intervals across the fixing window. Where a provider publishes pricing changes via changelog or API versioning events, Noble's system detects and timestamps these changes at the next polling event within the window. All raw pricing data is stored in Noble's immutable data ledger with a full audit trail.

Pricing data is validated against three integrity checks before incorporation into index calculation:

1. **Continuity check**: price changes exceeding 25% from the prior observation trigger a manual verification step, to be performed by Noble, before the update is incorporated.

2. **Cross-source validation**: provider-published prices are cross-referenced against Noble's independent API monitoring to confirm that the stated price is reflected in actual API responses.

3. **Version confirmation**: price updates are linked to a specific model version endpoint to prevent blended pricing across model versions.

## **4.2 Manipulation Resistance Framework**

Noble's manipulation resistance framework is designed to ensure that TPRR cannot be materially influenced by any single market participant, whether a model provider, a derivative counterparty, or a volume contributor. The framework draws on lessons from the LIBOR reform process, IOSCO Principles for Financial Benchmarks, and contemporaneous best practice from established commodity and energy benchmark administrators. v1.3 specifies six structural controls; five are operational at first publication, and one (Independent Transaction Cross-Validation, §4.2.3) is scheduled for production launch.

### **4.2.1 Manipulation Control 1: Time-Weighted Average Price (TWAP) Daily Fix**

The TPRR Daily Fix is calculated as the time-weighted average across 32 fifteen-minute slots in the 09:00–17:00 UTC fixing window. This is Noble's primary manipulation-resistance mechanism. A provider seeking to influence the daily fix would need to sustain a manipulated price continuously across an eight-hour window, representing a real cost in revenue foregone on actual API transactions priced at that level. Point-in-time window-dressing, the primary mechanism exploited in the LIBOR manipulation, is structurally precluded by this design.

For each (contributor, constituent, fixing date), the 32 slot prices are reconstructed from the day's posted price and any intraday change events recorded for that pair on that date. On a day with no change event, all 32 slots equal the posted price; the daily TWAP equals the posted price. On a day with a change event at slot S (S ∈ [0, 32)), slots [0, S) carry the pre-change price and slots [S, 32) carry the post-change price; the daily TWAP is slot-weighted accordingly. Multiple change events on a single day are ordered by slot index and applied sequentially.

While pricing observations are collected at 15-minute polling intervals, a price change can occur between two polling events. The system treats each slot's price as constant from the slot's start polling event until the next polling event; a price change occurring mid-slot (e.g. at minute 7 of 15) is therefore reflected in the slot beginning with the next polling event, not in the slot during which the change actually occurred. This convention attenuates the impact of intra-day price changes by up to 15 minutes (i.e. the new price's effective contribution to the daily TWAP is delayed by the fraction of the slot before the next polling event). The attenuation is bounded by the polling interval (15 minutes); for daily TWAP construction across 32 slots, the maximum systematic understatement is one slot-length out of 32, or approximately 3% of the daily fixing window.

Slot-level data quality gating (§4.2.2.1) is applied per slot; gated slots are excluded from the TWAP. The daily TWAP is the arithmetic mean of the surviving (non-gated) slot prices. If all 32 slots fail the gate, the (contributor, constituent, date) triple has no valid TWAP for that day.

**TPRR Daily Fix (per contributor, constituent, date) = arithmetic mean of surviving slot prices across the 32 fifteen-minute slots in the 09:00–17:00 UTC fixing window**

**Ordering convention**: TPRR uses **TWAP-then-weight** ordering. For each (contributor, constituent, fixing date), the daily TWAP is computed first; then the dual-weighted aggregation across constituents (§3.3.1) consumes each constituent's daily TWAP as the per-constituent price. This matches dominant commodity benchmark precedent (ICE Brent, Henry Hub, ASCI).

### **4.2.2 Manipulation Control 2: Slot-Level Data Quality Gate**

#### **4.2.2.1 Slot-Level Gate**

Notation: in this section, c indexes contributors, i indexes constituents, d is the fixing date, and s ∈ [0, 32) is the slot index within the fixing window.

A slot-level price observation that deviates by more than 15% from the constituent's five-day trailing average posted price is automatically excluded from the TWAP calculation (§4.2.1) for the affected (contributor, constituent, fixing date). Formally, for constituent i and contributor c on fixing date d at slot s, let P_{c,i}(d, s) denote the slot price (reconstructed per §4.2.1) and trailing_avg_{c,i}(d) denote the arithmetic mean of constituent i's posted output prices for contributor c over the five panel-recorded calendar days strictly preceding date d. The slot is excluded if:

**| P_{c,i}(d, s) – trailing_avg_{c,i}(d) | / trailing_avg_{c,i}(d) > 0.15**

The gate operates on Tier A rows only. Tier B and Tier C contributions do not have slot-level prices: Tier B contributes one synthesized price per (constituent, date) at the registry rate (§3.3.2.2); Tier C contributes via the rankings snapshot mechanism. The 5-day trailing window requires five panel-recorded prior days of data for the (contributor, constituent) pair; rows with insufficient history are skipped (no exclusions emitted). This affects the first five fixing dates of each (contributor, constituent) pair's coverage, the per-pair cold-start window during which gate enforcement does not yet apply.

The 15% threshold reflects the loosest data-quality gate that does not degrade the published level, making it a methodologically conservative choice. The threshold is reviewed quarterly by the Index Committee (§5.2).

The 15% gate is a data-quality control, not the primary manipulation defense. It catches data errors such as pricing-page rendering bugs, version-mismatch artifacts, and API misquotations. For prices that pass the gate but deviate from the index-tier median by a smaller margin (the more common scenario), the exponential median-distance weighting (§3.3.3) provides continuous, proportional fading.

#### **4.2.2.2 Suspension and Reinstatement Criteria**

A (contributor, constituent) pair that experiences three consecutive fixing days with at least one slot-level gate firing is **suspended** from index calculation; the pair contributes nothing to subsequent daily fixes until reinstated.

A pair is **reinstated** when it accumulates ten consecutive fixing days with no slot-level gate firings. The asymmetric thresholds (3-day exclude / 10-day reinstate) create a stability bias preventing oscillation near the threshold.

Walking the calendar date range for a pair, three states per day are tracked:

- **Fire day** (panel row exists with at least one slot-level gate firing): increment `fire_counter`; reset `clean_counter` to zero. If the pair is currently active and `fire_counter ≥ 3`, the pair is suspended on this date.
- **Clean day** (panel row exists with no slot-level gate firings): increment `clean_counter`; reset `fire_counter` to zero. If the pair is currently suspended and `clean_counter ≥ 10`, the pair is reinstated on this date.
- **Missing day** (no panel row for the pair on this date): reset BOTH counters to zero.

The missing-day reset preserves the "observed on-market" semantic of reinstatement: a contributor that goes silent earns no reinstatement progress on those days. Reinstated pairs contribute from the reinstatement date forward with no backfill of contributions during the suspended interval.

Suspension status is interval-aware: a pair is "active suspended on date d" when `suspension_date ≤ d AND (reinstatement_date is NaT OR d < reinstatement_date)`, with `reinstatement_date = NaT` indicating the pair is still suspended at the end of the panel range. Multiple suspension/reinstatement cycles are recorded as separate intervals.

### **4.2.3 Manipulation Control 3: Independent Transaction Cross-Validation**

Noble's infrastructure makes randomized API calls to all constituent model endpoints throughout the fixing window, at intervals and volumes designed to generate a statistically meaningful sample without constituting material commercial usage. The effective price observed on these transaction-level calls is compared against the provider's published pricing-page price for the same model endpoint. Any discrepancy exceeding 2% between the published price and the transaction-observed price triggers a validation hold: the affected constituent's price observation is quarantined pending manual review, and the prior validated price is used in its place until the discrepancy is resolved.

This control means that a provider cannot sustain a fictitious published price that does not correspond to the actual price charged to API customers. Unlike LIBOR, where submitted rates were in actuality opinions with no firm transaction verification, TPRR prices are grounded in observable, independently verified transactions.

**Production scope**: Independent transaction cross-validation is specified as part of the v1.3 methodology and is scheduled for implementation prior to TPRR's production launch.

### **4.2.4 Manipulation Control 4: Minimum Constituent Count**

The minimum-3 epistemic principle (every aggregation step combining independent observations requires at least three observations) applies symmetrically at distinct layers of the methodology. v1.3 specifies two structural threshold layers governing constituent participation in the index, and one operational consequence at the index-tier daily-fix layer.

#### **4.2.4.1 Contributor → Constituent Layer**

A constituent's Tier A activation requires a minimum of three distinct contributors with valid attested volume (`volume_mtok_7d > 0`) on the fixing date. When fewer than three contributors meet the threshold, Tier A does not activate for that constituent on that date; the constituent's contribution is determined by Tier B and Tier C (subject to those tiers' eligibility under §3.3.2.4).

The threshold is structural: a constituent with one or two contributor data points has insufficient redundancy to generate a non-degenerate volume-weighted price collapse. The two-contributor case is a single average of two observations, which has minimal manipulation resistance.

#### **4.2.4.2 Constituent → Attestation-Tier Layer**

An attestation tier within an index tier requires a minimum of three active constituents to contribute under continuous blending. The specification, audit trail (three-state per-tier audit row taxonomy), and smooth-activation property are documented in §3.3.2.4 ("Tier-Eligibility Threshold under Continuous Blending"); see that section for the operational specification.

#### **Operational consequence: index-tier daily-fix suspension**

When the cumulative effect of these threshold-driven exclusions reduces an index tier's active constituent count below three, the daily fix for that index tier is suspended for that fixing date. The most recent valid fix value is used as the published level until the index tier returns to ≥3 active constituents. Derivative contracts referencing a suspended fix use the most recent valid value, consistent with Noble's published fallback provisions.

This index-tier threshold prevents a situation in which a single provider dominates a tier's constituent set and can therefore single-handedly move the index. It also creates an incentive for maintaining a well-diversified constituent base across each index tier.

### **4.2.5 Manipulation Control 5: Provider Volume Data Exclusion from Weighting**

Volume weights used in TPRR calculation are derived exclusively from the contributor attestation panel and third-party transaction-verified sources (per §3.3.2.1). Provider self-reported volume data is never used as an input to constituent weighting under any circumstances.

This control applies the core lesson of post-2012 benchmark reform: the benchmark must be grounded in independently observable transaction data, not in data submitted by parties with a financial interest in the outcome. AI inference providers have a direct economic interest in the weight their models carry in TPRR. Excluding provider volume data from the weighting methodology eliminates this conflict of interest entirely.

Where Tier A is dormant for a constituent, proxy contributions from Tier B and Tier C apply per the continuous-blending coefficient redistribution (§3.3.2.2). Per-tier weight share decomposition for each (constituent, fixing date) is documented in the audit output (`tier_a_weight_share`, `tier_b_weight_share`, `tier_c_weight_share`); production publication will surface these fields in API response metadata.

### **4.2.6 Manipulation Control 6: Exponential Median-Distance Weighting**

The exponential median-distance weighting mechanism specified in §3.3.3 operates as a continuous, self-defeating manipulation control. A provider seeking to move TPRR by pricing away from the index-tier median sees its exponential weight decline proportionally; because the exponential weight multiplies against the volume weight in the dual-weighted formula (§3.3.1), a provider must maintain both high market share and competitive pricing to carry meaningful TPRR weight. See §3.3.3 for the formal specification, the canonical λ=3 decay parameter, and the dual-weighted manipulation-resistance discussion.

## **4.3 Publication Schedule**

| Series | Frequency | Publication window |
| :---- | :---- | :---- |
| TPRR Daily Fix (TPRR-F, TPRR-S, TPRR-E) | Daily | 17:00 UTC; TWAP across 32 fifteen-minute observations 09:00–17:00 UTC |
| TPRR-FPR / TPRR-SER | Daily | Published concurrently with TPRR Daily Fix |
| TPRR-B (Blended Analytics) | Daily | Published concurrently with TPRR Daily Fix; informational only, not a derivative settlement reference |
| TPRR Monthly Average | Monthly | Published on the 3rd business day following month-end (production scope) |
| FX-Hedged Variants (EUR/GBP/JPY) | Daily | Published at 17:30 UTC following FX market close (production scope) |
| TPRR Spot (output) | Continuous (15-min) | Production scope |

At first publication of v1.3, the TPRR Daily Fix and supporting analytics series (TPRR-FPR, TPRR-SER, TPRR-B) are operational. Intraday spot publication, monthly average publication, and FX-hedged variants are scheduled for production deployment.

## **4.4 Restatement Policy**

Noble operates a strict restatement policy. Published TPRR values are final and will not be restated except in the case of a documented data error reviewed and approved by the Index Committee (§5.1). Where restatement occurs, Noble publishes a formal correction notice detailing the affected values, the source of the error, and the corrected series. Derivative contracts referencing a restated TPRR value will use the corrected value for settlement purposes, consistent with ISDA fallback provisions which will be referenced in Noble's standard derivative terms.

# **5. Governance Framework**

## **5.1 Index Committee**

TPRR is governed by Noble's Index Committee, a standing body with the following composition:

| Role | Responsibilities |
| :---- | :---- |
| Chair (Noble Chief Index Officer) | Owns methodology integrity; final authority on constituent decisions and restatement approvals. |
| Independent Members (×2) | External quants or derivatives market practitioners; provide independent challenge to methodology decisions. |
| Data Governance Officer | Oversees volume attestation process, contributor data auditing, and proxy weight review. |
| Legal/Compliance Observer | Non-voting; ensures methodology and publication practices comply with applicable benchmark regulations (EU BMR, FCA BRS). |

## **5.2 Constituent Review**

The Index Committee conducts a formal constituent review on a quarterly basis. Every quarterly review assesses:

- **Eligibility compliance** for all current constituents against the criteria in §3.1.
- **Candidate models** from eligible providers not yet included in the index.
- **Tier re-classification** of constituents whose capability or pricing profile has materially changed (§3.2).
- **Volume attestation coverage**: proportion of Tier A (attested) to Tier B (revenue proxy) to Tier C (market proxy) weighting per index tier; progress toward Tier A coverage targets.
- **Continuous blending parameter calibration**: the tier blending coefficients (default A=0.6, C=0.3, B=0.1; §3.3.2.2), tier confidence haircuts (default A=1.0, C=0.8, B=0.5; §3.3.2.1), and the tier-eligibility threshold (default 3 constituents per attestation tier per index tier; §3.3.2.4) against observed within-tier dispersion and cross-tier coverage evolution.
- **Exponential weighting calibration**: the λ parameter (canonical λ=3; §3.3.3) against observed within-tier price dispersion.
- **Slot-level gate threshold review**: canonical 15% (§4.2.2.1) against observed slot-level deviation patterns.
- **Suspension/reinstatement threshold review**: canonical 3-day exclude / 10-day reinstate (§4.2.2.2) against observed pair-level data quality patterns.
- **Manipulation resistance review**: TWAP outlier exclusion thresholds (§4.2.2), transaction cross-validation sample sizes (§4.2.3), and minimum constituent count thresholds (§4.2.4) against current market conditions.
- **Tier C data source review**: assessment of OpenRouter market proxy data quality, representativeness of enterprise usage patterns (per the bias profile in §3.3.2.1), and identification of alternative or supplementary Tier C sources as the market evolves.
- **TPRR-B blended ratio review**: the 75:25 (output:input) ratio used in TPRR-B (§3.3.4) against the contributor dataset as coverage matures.

Quarterly reviews will produce a formal report, distributed to all current contributors and index distribution partners, and made available publicly on the Noble website.

Ad hoc reviews may be convened between quarterly cycles in response to material market events, including model deprecations, significant pricing restructurings, or the emergence of a new provider with material enterprise adoption.

## **5.3 Regulatory Positioning**

Noble publishes TPRR in compliance with the principles of IOSCO's Principles for Financial Benchmarks (2013), which are incorporated by reference into both the EU Benchmark Regulation (BMR) and the UK Financial Conduct Authority's Benchmark Regulation (UK BMR). Noble's governance framework, methodology documentation, and data audit procedures are designed to satisfy the requirements of a regulated benchmark administrator under these regimes.

Noble intends to engage benchmark regulatory counsel ahead of formal registration milestones. Public methodology disclosure under IOSCO Principles is scheduled for production launch; the v1.3 methodology remains internal during the pre-launch phase.

# **6. Revision History**

v1.3, effective 2026-05-06: first published methodology specification.

# **7. Disclaimers and Legal Notices**

This document is published by Noble for informational purposes. The TPRR indices are provided as reference benchmarks only. Nothing in this document constitutes investment advice, financial advice, or a recommendation to enter into any financial transaction referencing TPRR.

TPRR is based on data sourced from AI model providers and Noble's contributor network. Noble makes reasonable efforts to ensure the accuracy and completeness of the data underlying TPRR but provides no warranty, express or implied, as to its accuracy, completeness, or fitness for any purpose.

Noble, Argon, Xenon, TPRR, and noble.markets are trademarks of Noble. All rights reserved. Unauthorized redistribution of TPRR data is prohibited without a valid redistribution license from Noble.

For licensing and methodology inquiries: contact@noble.markets
