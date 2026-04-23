

| NOBLE Argon  ·  Token Price Intelligence Token Price Reference Rate Index Methodology Version 1.2  |  Confidential noble.markets |
| :---- |

# **1\. Executive Summary**

The Token Price Reference Rate (TPRR) is a family of standardised benchmark indices published by Noble that measure the real-time and historical cost of AI inference across the world's leading large language model providers. TPRR provides the financial industry's first independently governed, transparent, and replicable pricing standard for the AI inference token market.

As enterprise AI adoption moves from experimentation to operational scale, AI inference costs have become a material and growing line item on corporate balance sheets. Despite this, no standardised pricing reference exists — a gap that Noble is purpose-built to fill. TPRR serves as the foundation for a new asset class: AI inference derivatives that allow enterprises to hedge token price exposure, and financial institutions to structure, price, and trade those instruments with reference to a trusted benchmark.

Noble publishes three core TPRR indices, each targeting a distinct segment of the AI model market:

| Index | Name | Description | Tier |
| :---- | :---- | :---- | :---- |
| TPRR-F | Frontier | Highest-capability frontier models; GPT-4o, Claude 3.7 Sonnet, Gemini 1.5 Pro class and above | Premium |
| TPRR-S | Standard | Mid-tier general-purpose models widely deployed in enterprise production workloads | Mid-market |
| TPRR-E | Efficiency | Small, fast, cost-optimised models suited to high-volume, latency-sensitive tasks | Economy |

Two cross-index analytics series and one blended analytics series are derived from the core indices:

| Metric | Name | Definition |
| :---- | :---- | :---- |
| TPRR-FPR | Frontier Premium Ratio | TPRR-F divided by TPRR-S; measures the cost premium commanded by frontier capability over standard tiers |
| TPRR-SER | Standard Efficiency Ratio | TPRR-S divided by TPRR-E; measures the cost premium of mid-tier models over economy alternatives |
| TPRR-B | Blended Analytics Series | Informational series only (not used for derivative settlement); blends output and input token prices at a 25:75 output/input ratio to support total cost benchmarking |

| *TPRR is not merely a data product. It is the pricing standard — anchored in output token economics, the scarce and compute-intensive unit of AI production — upon which the AI inference derivatives market will be built.* |
| :---- |

# **2\. Market Context and Rationale**

## **2.1  The AI Inference Cost Problem**

Enterprise spending on AI inference is growing at a rate that few finance functions were equipped to anticipate. What began as a discretionary R\&D line item has, for many organisations, become a significant and unpredictable operational expense. Leading enterprises are now spending tens of millions of dollars annually on API-based AI inference — with limited ability to forecast, hedge, or benchmark that cost.

Unlike cloud compute or software licensing — markets where pricing is broadly transparent and benchmarking infrastructure is mature — the AI inference market lacks any standardised pricing reference. Prices are set unilaterally by providers, change without notice, vary by model version and tier, and are quoted in unit economics (price per million tokens) that are not comparable across providers without normalisation.

This creates three compounding problems for enterprise finance:

* Budgeting uncertainty: forecast AI costs cannot be reliably anchored to a market reference, creating variance that falls through to earnings.

* No hedging instruments: without a recognised benchmark, there is no basis upon which derivative instruments can be structured or priced.

* No performance attribution: enterprises have no objective basis for evaluating whether the model tier they are consuming represents value relative to alternatives.

## **2.2  The Case for a Benchmark Standard**

TPRR addresses this structural gap by providing what every functioning financial market requires before derivatives and risk transfer instruments can develop: a trusted, transparent, independently governed pricing reference.

The historical precedent is clear. LIBOR created the interest rate derivatives market. ICE Brent created the oil derivatives market. Henry Hub created the natural gas derivatives market. In each case, the index preceded the derivatives, not the other way around. TPRR is designed to serve precisely this foundational role for the AI inference asset class.

| *Noble's strategic position: by establishing TPRR as the market standard before any competing benchmark emerges, Noble secures the first-mover advantage that defines index businesses — where the winning standard is, by network effect, the only standard.* |
| :---- |

## **2.3  Currency Dimension: FX-Hedged TPRR Variants**

For enterprises operating outside the United States, AI inference cost is a dual exposure: token price risk denominated in USD, compounded by currency translation risk. A European company paying for GPT-4o tokens in USD faces both the risk of OpenAI increasing its per-token price and the risk of EUR/USD movement widening its effective cost.

Noble publishes currency-hedged TPRR variants for EUR, GBP, and JPY — the three largest non-USD enterprise AI spending geographies. These variants translate TPRR into local currency terms using mid-market FX rates sourced from Noble's Xenon FX intelligence layer, enabling non-USD enterprises to track, benchmark, and ultimately hedge their total AI inference cost in home currency terms.

This cross-product architecture — Argon token indices layered with Xenon FX intelligence — is a structural differentiator unique to Noble and creates the foundation for the first currency-hedged AI inference derivative instruments.

# **3\. Index Architecture**

## **3.1  Index Universe and Constituent Eligibility**

TPRR indices are constructed from a defined universe of AI inference providers whose models meet eligibility criteria across five dimensions:

| Criterion | Requirement |
| :---- | :---- |
| Commercial Availability | Model must be available via a publicly documented API with programmatic access. Internal or research-preview models are excluded. |
| Pricing Transparency | Provider must publish explicit per-token pricing (input and output, in USD per million tokens) on a publicly accessible pricing page. |
| Enterprise Adoption | Model must demonstrate material enterprise production usage, evidenced by disclosed customer counts, third-party usage attestation, or Noble founding contributor data. |
| Operational Stability | Provider must have demonstrated continuous API availability of at least 99.5% over the preceding 90 days, as measured by Noble's monitoring infrastructure. |
| Version Governance | Provider must maintain stable versioned model endpoints; models subject to silent capability updates without version increments are ineligible. |

## **3.2  Tier Classification**

Each eligible model is classified into one of three tiers. Tier classification is determined by Noble's Index Committee, applying the following criteria:

| Tier | Capability Profile | Pricing Profile | Representative Models |
| :---- | :---- | :---- | :---- |
| Frontier (TPRR-F) | State-of-the-art reasoning, multimodal, long-context; highest benchmark performance | Highest per-token cost; typically \>$10/M output tokens | GPT-4o, Claude 3.7 Sonnet, Gemini 1.5 Pro |
| Standard (TPRR-S) | Strong general-purpose performance; production-grade for most enterprise tasks | Mid-range; typically $1–$10/M output tokens | GPT-4o Mini, Claude 3.5 Haiku, Gemini 1.5 Flash |
| Efficiency (TPRR-E) | Optimised for speed and volume; lower capability ceiling but highly cost-effective | Sub-$1/M output tokens; often sub-cent for input | Llama 3.1 8B (hosted), Mistral 7B (hosted), Gemini Flash 8B |

## **3.3  Weighting Methodology**

### **3.3.1  Principle: Output Token Price as the TPRR Basis**

TPRR is calculated using output token prices only. Output tokens — the tokens generated by the model in response to a query — are the scarce, compute-intensive resource that drives AI inference economics. Generating each output token requires a full forward pass through the model; this is the cost that scales directly with enterprise AI workload volume and cannot be reduced through operational behaviour such as prompt optimisation.

Input token costs, by contrast, are primarily a function of prompt engineering discipline and context management — operational levers within the enterprise's direct control, not financial risks requiring derivative hedging. Mixing input token costs into a settlement benchmark would introduce basis risk between the hedge and the actual exposure being managed, since input consumption varies by workload design rather than by market price alone.

By anchoring TPRR exclusively to output token pricing, Noble produces a benchmark with a clear and defensible economic rationale: TPRR measures the cost of AI-generated work, the unit that scales with production volume and is subject to provider pricing decisions outside the enterprise's control.

Each constituent's contribution to the index is determined by a dual-weighted formula: volume weight (how much of the market the model represents) multiplied by an exponential median-distance weight (how consistent the model's price is with the rest of its tier). The dual-weighted TPRR index is:

**TPRR(t) \= Σ \[ w\_volᵢ × w\_expᵢ × Pᵢᵒᵘᵗ(t) \]  /  Σ \[ w\_volᵢ × w\_expᵢ \]**

Where Pᵢᵒᵘᵗ(t) is the published output token price for constituent i in USD per million tokens, w\_volᵢ is the volume weight derived from Noble's tiered attestation hierarchy (see Section 3.3.2), and w\_expᵢ is the exponential median-distance weight that fades price outliers within each tier (see Section 3.3.3).

A constituent must carry material market volume and price consistently with its tier peers to contribute meaningfully to the index. This dual-weighting structure makes TPRR robust to both low-volume constituents with anomalous prices and high-volume constituents that deviate from the tier's core pricing economics.

### **3.3.2  Volume Attestation — Three-Tier Data Hierarchy**

AI inference providers do not publicly disclose per-model token volumes. This is the central methodological challenge facing any AI inference index: without reliable volume data, an index must default to equal weighting or proxy weighting, both of which reduce accuracy. Noble addresses this through a three-tier data hierarchy that provides defensible volume weights from launch and improves in accuracy as the contributor network scales.

| Tier | Name | Source | Confidence | Haircut |
| :---- | :---- | :---- | :---- | :---- |
| A | Contributor-Attested | Direct API pull from contributor billing systems (Anthropic Admin API, OpenAI Usage API, GCP Cloud Billing, AWS CloudWatch/Cost Explorer). Provider-attested billing data that matches the contributor's invoice. See Noble Argon PRD Section 4 for integration detail. | Highest | None (100%) |
| B | Revenue-Derived Proxy | Publicly disclosed provider revenue data (Anthropic, OpenAI, Google quarterly/annual reports), supplemented by third-party analyst estimates (Menlo Ventures, IDC, Gartner enterprise AI spend reports). Provider-level revenue allocated across models using disclosed product mix and market share data. | Moderate | 90% of face value |
| C | Transaction-Verified Market Proxy | OpenRouter's publicly available, transaction-derived model volume data. OpenRouter processes over 20 trillion tokens per week across hundreds of models, logged as structured metadata at the generation event level. Data is filtered by Noble's Index Committee to exclude free-tier models and non-enterprise-relevant usage before application. | Indicative | 80% of face value |

Noble applies the highest-confidence data available for each constituent. Where Tier A data exists (3 or more contributors with attested volumes for a model), Tier A is used at full face value. Where Tier A coverage is insufficient, Tier B supplements it. Tier C is used only where Tier A and Tier B are both insufficient — primarily at index launch and for newly eligible constituents.

The haircuts applied to Tier B and Tier C data (90% and 80% respectively) reflect the declining confidence in each data source's accuracy as a proxy for enterprise production volume. These haircuts are conservative by design: they penalise proxy-weighted constituents slightly in the index, creating an incentive for Noble to replace proxy data with attested data as quickly as possible. Haircut levels are reviewed quarterly by the Index Committee and disclosed in all index publications.

Every index publication includes a transparency disclosure: the percentage of each tier's total weight that is Tier A (attested), Tier B (revenue proxy), and Tier C (market proxy). The target is for Tier A coverage to exceed 70% of total index weight within 12 months of launch.

| *The three-tier hierarchy serves a dual purpose: it makes TPRR publishable from day one with defensible weights (via Tier B and Tier C), while creating a structural incentive to grow the contributor network (because Tier A data is both more accurate and more fully weighted). As the Noble Argon contributor pipeline scales, the index becomes progressively more precise — and Noble's data moat deepens with each contributor onboarded.* |
| :---- |

### **3.3.3  Exponential Median-Distance Weighting**

Within each TPRR tier, constituent prices are further weighted by their distance from the tier's median output token price. This mechanism — adapted from established commodity benchmark methodology — ensures that constituents whose pricing is inconsistent with the rest of their tier carry proportionally less influence on the index, without requiring hard exclusion thresholds.

For each constituent i in a tier, the exponential weight is calculated as:

**w\_expᵢ \= exp( –λ × |Pᵢ – P\_median| / P\_median )**

Where Pᵢ is the constituent's output token price, P\_median is the median output token price across all constituents in the tier, and λ (lambda) is the decay parameter controlling how aggressively outliers are faded.

Noble sets λ \= 3 at index inception. The effect at representative distances from the tier median:

| Distance from Tier Median | Exponential Weight (w\_exp) | Effect |
| :---- | :---- | :---- |
| 0% (at median) | 1.000 | Full weight |
| 5% | 0.861 | Minimal fade |
| 10% | 0.741 | Moderate fade |
| 20% | 0.549 | Material fade |
| 30% | 0.407 | Substantial fade |
| 50% | 0.223 | Largely marginalised |
| 100% | 0.050 | Effectively zero weight |

The exponential mechanism is superior to hard threshold exclusion for two reasons. First, it is continuous rather than binary: there is no cliff edge at which a constituent is suddenly included or excluded. This eliminates a manipulation vector in which a provider positions its price just inside a hard threshold. Second, it is self-calibrating: as the tier's constituent set evolves and the median shifts, each constituent's weight adjusts automatically without requiring the Index Committee to revise thresholds.

Because the exponential weight multiplies against the volume weight, a constituent must be both widely used (high volume weight) and competitively priced (high exponential weight) to materially influence the index. A provider seeking to move TPRR in its favour by adjusting its price away from the tier median would see its exponential weight decline — making manipulation self-defeating by construction.

The λ parameter is reviewed quarterly by the Index Committee. The AI inference market is still maturing, and price dispersion within tiers may be wider than in established commodity markets. If λ \= 3 proves too aggressive (fading legitimate but premium-priced models excessively), the Committee may reduce it. If it proves too permissive, the Committee may increase it. The current λ value is disclosed in every index publication.

| *The dual-weighting structure — volume attestation (Section 3.3.2) times exponential median-distance (Section 3.3.3) — produces a benchmark that is robust to both data quality variation and strategic price manipulation. A constituent needs real market share and competitive pricing to move TPRR. Neither alone is sufficient. This is the central design principle of the TPRR weighting methodology.* |
| :---- |

### **3.3.4  TPRR-B — The Blended Analytics Series**

Separately from the core TPRR indices, Noble publishes TPRR-B: a blended analytics series that combines output and input token prices for enterprises who wish to benchmark their total AI inference cost inclusive of input consumption. TPRR-B is an informational series only and is not used as a settlement reference for any Noble derivative instrument.

TPRR-B is calculated using the following blended price formula:

**TPRR-Bᵢ(t) \= \[P\_out × 0.25 \+ P\_in × 0.75\]**

The 25:75 output/input weighting reflects the observed average token consumption ratio across Noble's founding contributor dataset. The ratio is reviewed quarterly by the Index Committee. As contributor data matures, Noble may publish workload-specific TPRR-B variants (e.g. RAG workloads vs. agentic workflows) as supplementary analytics series.

| *TPRR-B is published for benchmarking and total cost intelligence purposes only. All Noble derivative instruments — inference swaps, caps, floors, forwards, and currency-hedged structures — reference the output-only TPRR indices (TPRR-F, TPRR-S, TPRR-E). This separation eliminates basis risk between hedge performance and the provider-driven pricing risk that derivatives are designed to transfer.* |
| :---- |

# **4\. Calculation and Publication**

## **4.1  Data Collection and Integrity Framework**

Noble's automated pricing ingestion layer polls provider pricing pages and API endpoints at 15-minute intervals. Where a provider publishes pricing changes via changelog or API versioning events, Noble's system detects and timestamps these changes within the polling window. All raw pricing data is stored in Noble's immutable data ledger with full audit trail.

Pricing data is validated against three integrity checks before incorporation into index calculation:

1. Continuity check: price changes exceeding 25% from the prior observation trigger a manual verification step before the update is incorporated.

2. Cross-source validation: provider-published prices are cross-referenced against Noble's independent API monitoring to confirm that the stated price is reflected in actual API responses.

3. Version confirmation: price updates are linked to a specific model version endpoint to prevent blended pricing across model versions.

## **4.2  Manipulation Resistance Framework**

Noble's manipulation resistance framework is designed to ensure that TPRR cannot be materially influenced by any single market participant — whether a model provider, a derivative counterparty, or a volume contributor. The framework draws on lessons from the LIBOR reform process, IOSCO Principles for Financial Benchmarks, and contemporaneous best practice from established commodity and energy benchmark administrators. Five structural controls are operative from the index's inception:

### **4.2.1  Time-Weighted Average Price (TWAP) Daily Fix**

The TPRR Daily Fix is not a snapshot price taken at a single moment. It is calculated as the volume-weighted average of all 96 validated price observations recorded during the fixing window (09:00–17:00 UTC), with each observation representing a 15-minute polling interval. This is Noble's primary manipulation-resistance mechanism.

A provider seeking to influence the daily fix would need to sustain a manipulated price continuously across an eight-hour window — representing a real cost in terms of revenue foregone on actual API transactions priced at that level. Point-in-time window-dressing, which was the primary mechanism exploited in the LIBOR manipulation, is structurally precluded by this design.

**TPRR Daily Fix \= TWAP(Pᵢ(t))  over t ∈ \[09:00, 17:00\] UTC  across 96 fifteen-minute intervals**

### **4.2.2  Outlier Detection — Data Quality Gate**

Any constituent price observation that deviates by more than 15% from that constituent's five-day trailing average triggers automatic exclusion from the fixing calculation for that interval. This is a data quality control, not the primary manipulation defence — it catches genuine data errors such as pricing page rendering bugs, version mismatch artifacts, or API misquotations.

Where a constituent's price remains outside the 15% threshold for three or more consecutive 15-minute intervals, the Data Governance Officer convenes an emergency review. The constituent may be suspended from index calculation pending confirmation that the price change is genuine and provider-confirmed, rather than a data error.

For prices that pass the data quality gate but deviate from the tier median by a smaller margin — the more common and more subtle scenario — the exponential median-distance weighting mechanism (Section 3.3.3) provides continuous, proportional fading. The hard threshold catches errors; the exponential weighting handles strategic behaviour. The two mechanisms are complementary, not redundant.

### **4.2.3  Independent Transaction Cross-Validation**

Noble's infrastructure makes randomised API calls to all constituent model endpoints throughout the fixing window, at intervals and volumes designed to generate a statistically meaningful sample without constituting material commercial usage. The effective price observed on these transaction-level calls is compared against the provider's published pricing page price for the same model endpoint.

Any discrepancy exceeding 2% between the published price and the transaction-observed price triggers a validation hold: the affected constituent's price observation is quarantined pending manual review, and the prior validated price is used in its place until the discrepancy is resolved.

This control means that a provider cannot sustain a fictitious published price that does not correspond to the actual price charged to API customers. Unlike LIBOR — where submitted rates were opinions with no transaction verification — TPRR prices are grounded in observable, independently verified transactions.

### **4.2.4  Minimum Constituent Count Per Tier**

A TPRR tier fix requires a minimum of three active, eligible constituents with validated price observations in the fixing window. If a tier falls below this threshold — due to constituent suspension, provider outage, or data validation failure — the tier fix for that day is suspended and flagged as unavailable. Derivative contracts referencing a suspended fix will use the most recent valid fix value, consistent with Noble's published fallback provisions.

This control prevents a situation in which a single provider dominates a tier's constituent set and can therefore single-handedly move the index. It also creates an incentive for maintaining a well-diversified constituent base across each tier.

### **4.2.5  Provider Volume Data Exclusion from Weighting**

Volume weights used in TPRR calculation are derived exclusively from Noble's Founding Contributor dataset and third-party attestation mechanisms. Provider-self-reported volume data is never used as an input to constituent weighting under any circumstances.

This control applies the core lesson of the SOFR transition: the benchmark must be grounded in independently observable transaction data, not in data submitted by parties with a financial interest in the outcome. AI inference providers have a direct economic interest in the weight their models carry in TPRR, since higher weighting increases their relevance to the derivatives market and may affect how derivative counterparties manage TPRR exposure. Excluding provider volume data from the weighting methodology eliminates this conflict of interest entirely.

Where insufficient contributor-attested data exists for a constituent, Noble applies proxy weights derived from its three-tier attestation hierarchy (see Section 3.3.2). Proxy weights are clearly flagged in all index publications and in Noble's API response metadata.

### **4.2.6  Exponential Median-Distance Weighting**

The exponential median-distance weighting mechanism described in Section 3.3.3 operates as a continuous, self-defeating manipulation control. A provider seeking to move TPRR in its favour by pricing away from the tier median sees its exponential weight decline proportionally — the further the price moves from the median, the less influence it carries.

This mechanism is structurally superior to hard threshold exclusion for manipulation resistance. Hard thresholds create exploitable cliff edges: a provider can position its price just inside the threshold and retain full index weight. The exponential function has no cliff edge — influence fades smoothly with distance from the median, making strategic price positioning continuously self-defeating rather than merely boundary-constrained.

Critically, the exponential weight compounds with volume weighting: a provider must maintain both high market share and competitive pricing to carry meaningful TPRR weight. Adjusting price to gain favourable derivative exposure reduces the exponential weight, offsetting the attempted manipulation. This dual-weighted structure makes TPRR manipulation economically irrational for any market participant.

| *The six controls above are cumulative and interdependent. TWAP makes single-interval manipulation expensive. Data quality gating catches errors. Transaction cross-validation prevents fictitious published prices. Minimum constituent count prevents single-provider dominance. Provider volume exclusion eliminates weighting manipulation. Exponential median-distance weighting makes price-based manipulation self-defeating. Together they make TPRR structurally more robust against manipulation than any existing financial benchmark at inception — not by regulatory mandate, but by design.* |
| :---- |

## **4.3  Publication Schedule**

| Series | Frequency | Publication Window |
| :---- | :---- | :---- |
| TPRR Spot (output) | Continuous (15-min) | Intraday; available via Noble Argon Insights API |
| TPRR Daily Fix | Daily | 17:00 UTC; TWAP of 96 fifteen-minute observations (09:00–17:00 UTC); primary settlement reference for OTC derivatives |
| TPRR Monthly Average | Monthly | Published on the 3rd business day following month-end |
| TPRR-B (Blended Analytics) | Daily | Published concurrently with TPRR Daily Fix; informational only — not a derivative settlement reference |
| TPRR-FPR / TPRR-SER | Daily | Published concurrently with TPRR Daily Fix |
| FX-Hedged Variants (EUR/GBP/JPY) | Daily | Published at 17:30 UTC following FX market close |

## **4.4  Restatement Policy**

Noble operates a strict restatement policy. Published TPRR values are final and will not be restated except in the case of a documented data error that has been reviewed and approved by the Index Committee. Where restatement occurs, Noble publishes a formal correction notice detailing the affected values, the source of the error, and the corrected series. Derivative contracts referencing a restated TPRR value will use the corrected value for settlement purposes, consistent with ISDA fallback provisions referenced in Noble's standard derivative terms.

# **5\. Governance Framework**

## **5.1  Index Committee**

TPRR is governed by Noble's Index Committee, a standing body with the following composition:

| Role | Responsibilities |
| :---- | :---- |
| Chair (Noble Chief Index Officer) | Owns methodology integrity; final authority on constituent decisions and restatement approvals. |
| Independent Members (x2) | External quants or derivatives market practitioners; provide independent challenge to methodology decisions. |
| Data Governance Officer | Oversees volume attestation process, contributor data auditing, and proxy weight review. |
| Legal/Compliance Observer | Non-voting; ensures methodology and publication practices comply with applicable benchmark regulations (EU BMR, FCA BRS). |

## **5.2  Constituent Review**

The Index Committee conducts a formal constituent review on a quarterly basis. Reviews assess:

* Eligibility compliance for all current constituents against the criteria in Section 3.1

* Candidate models from eligible providers not yet included in the index

* Tier re-classification of constituents whose capability or pricing profile has materially changed

* Volume attestation coverage review: proportion of Tier A (attested) to Tier B (revenue proxy) to Tier C (market proxy) weighting per index; progress toward the 70% Tier A coverage target

* Manipulation resistance review: assessment of TWAP outlier exclusion thresholds, transaction cross-validation sample sizes, and minimum constituent count levels against current market conditions

* Exponential weighting calibration: review of the λ parameter (λ=3 at inception) against observed within-tier price dispersion; assessment of whether the current decay rate is appropriately fading outliers without penalising legitimate pricing variation

* Tier C data source review: assessment of OpenRouter market proxy data quality, representativeness of enterprise usage patterns, and identification of alternative or supplementary Tier C sources as the market evolves

* TPRR-B blended ratio review: the output/input ratio used in the TPRR-B analytics series, reviewed against contributor dataset as coverage matures

Ad hoc reviews may be convened between quarterly cycles in response to material market events, including model deprecations, significant pricing restructurings, or the emergence of a new provider with material enterprise adoption.

## **5.3  Regulatory Positioning**

Noble publishes TPRR in compliance with the principles of IOSCO's Principles for Financial Benchmarks (2013), which are incorporated by reference into both the EU Benchmark Regulation (BMR) and the UK Financial Conduct Authority's Benchmark Regulation (UK BMR). Noble's governance framework, methodology documentation, and data audit procedures are designed to satisfy the requirements of a regulated benchmark administrator under these regimes.

Noble's legal counsel is engaged in ongoing assessment of TPRR's classification under applicable benchmark regulations, with a view to formal registration as the index achieves the scale thresholds that trigger mandatory compliance obligations.

# **6\. Derivative Applications**

## **6.1  TPRR as a Settlement Reference**

The TPRR Daily Fix is designed to serve as the reference rate for OTC derivative instruments — specifically AI inference swaps — where counterparties exchange fixed token price commitments for floating TPRR exposure. The structure mirrors established commodity derivative conventions:

* Fixed-for-floating inference swap: Enterprise pays fixed price per million tokens; Noble (or a financial intermediary) pays TPRR-F (or \-S or \-E) at each settlement date. Net cash settlement based on difference between fixed rate and TPRR fix.

* Cap/floor structures: Enterprise purchases a TPRR cap at a specified strike, providing protection against token price increases above the strike level. Analogous to interest rate cap structures.

* Forward TPRR: Enterprise locks in a fixed token price for a future period. Settlement at contract maturity based on TPRR average over the reference period vs. forward rate.

Noble's ISDA-aligned standard derivative terms, referencing TPRR as the defined index, are in development and will be published concurrent with Noble's first live OTC transaction.

## **6.2  Currency-Hedged Inference Swaps**

For non-USD enterprises, Noble's FX-hedged TPRR variants enable a new instrument class: the currency-hedged inference swap. In these structures, token price risk and FX translation risk are hedged simultaneously within a single instrument, using TPRR for the token leg and Noble's Xenon FX reference rates for the currency leg.

This instrument has no existing market precedent and represents a structural innovation made possible by Noble's integrated Argon-Xenon architecture. A European enterprise with EUR-denominated AI inference exposure, for example, can enter a single EUR-denominated TPRR swap that hedges both the dollar cost of tokens and the EUR/USD translation of that cost — eliminating the operational complexity of managing two separate hedging instruments with two separate counterparties.

| *The currency-hedged inference swap is the first genuinely new derivative instrument class created by the rise of enterprise AI — and Noble is the only provider positioned to issue and settle it.* |
| :---- |

# **7\. Data Distribution and Licensing**

## **7.1  Distribution Partners**

Noble targets distribution of TPRR through established financial data infrastructure to maximise adoption by institutional users who consume benchmark data through existing terminal and data feed arrangements:

* Bloomberg Terminal: Real-time and historical TPRR series available via Bloomberg ticker integration, accessible to Bloomberg's 325,000+ terminal subscribers globally.

* FTSE Russell: Co-branded index licensing and distribution through FTSE Russell's institutional index data infrastructure, enabling incorporation of TPRR into investment mandates and risk frameworks.

* Noble Argon Insights API: Direct programmatic access for enterprise users, available as part of Noble's SaaS offering. Provides real-time spot data, historical series, and portfolio-level analytics unavailable through terminal distribution.

## **7.2  Licensing Model**

| Tier | User Type | Terms |
| :---- | :---- | :---- |
| Benchmark Reference | Enterprises using TPRR for internal budgeting and reporting | Annual subscription; scaled by revenue/AUM |
| Derivative Settlement | Financial institutions using TPRR as settlement reference in OTC instruments | Transaction fee per notional settled; or annual enterprise licence |
| Platform | SaaS users of Noble Argon Insights dashboard and API | Monthly SaaS subscription; tiered by seats and API calls |
| Redistribution | Data vendors, terminal providers, index platforms | Custom licensing; subject to redistribution restrictions |

# **8\. Revision History and Forward Roadmap**

## **8.1  Version History**

| Version | Date | Changes |
| :---- | :---- | :---- |
| 1.0 | 2025 | Initial publication. Three core indices (TPRR-F, TPRR-S, TPRR-E), two cross-index analytics (TPRR-FPR, TPRR-SER), and three FX-hedged variants (EUR, GBP, JPY). Volume attestation via founding contributor programme. |
| 1.1 | 2025 | Output-only pricing basis adopted for all core TPRR indices. TPRR-B blended analytics series introduced as informational supplement (not a settlement reference). Manipulation Resistance Framework formalised as Section 4.2: TWAP fixing, outlier detection and trimmed-mean exclusion, transaction cross-validation, minimum constituent count, and provider volume data exclusion. |
| 1.2 | 2025 | Three-tier volume attestation hierarchy introduced (Tier A contributor-attested, Tier B revenue-derived proxy, Tier C transaction-verified market proxy via OpenRouter). Exponential median-distance weighting (λ=3) added as Section 3.3.3 and as sixth manipulation resistance control (Section 4.2.6). Dual-weighted TPRR formula formalised: volume weight × exponential weight. Section 4.2.2 reframed as data quality gate; exponential weighting now serves as primary continuous manipulation defence. Quarterly review scope expanded to include λ calibration and Tier C data source assessment. |

## **8.2  Methodology Development Roadmap**

Noble's Index Committee has identified the following areas of methodology development for future releases:

* Workload-specific TPRR-B variants: Publishing separate blended series for distinct workload types (RAG, agentic, code generation) based on contributor data as coverage matures — Version 1.2 target.

* Multimodal token pricing: Extending TPRR to cover vision, audio, and video token pricing as multimodal inference becomes a material enterprise cost — Version 1.2 target.

* On-premise and private cloud inference: Methodology extension covering self-hosted model inference costs, enabling enterprises to benchmark API vs. self-hosted total cost of ownership — Version 2.0 target.

* TPRR Futures: Working with regulated exchanges to develop a listed TPRR futures contract, contingent on OTC market liquidity development — medium-term milestone.

# **9\. Disclaimers and Legal Notices**

This document is published by Noble for informational purposes. The TPRR indices are provided as reference benchmarks only. Nothing in this document constitutes investment advice, financial advice, or a recommendation to enter into any financial transaction referencing TPRR.

TPRR is based on data sourced from AI model providers and Noble's contributing enterprise network. Noble makes reasonable efforts to ensure the accuracy and completeness of the data underlying TPRR but provides no warranty, express or implied, as to its accuracy, completeness, or fitness for any purpose.

Noble, Argon, Xenon, TPRR, and noble.markets are trademarks of Noble. All rights reserved. Unauthorised redistribution of TPRR data is prohibited without a valid redistribution licence from Noble.

For licensing & methodology enquiries: contact@noble.markets

