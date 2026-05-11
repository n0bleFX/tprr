| NOBLE Argon · TPRR Development and Validation | Confidential noble.markets |
| :---- |

**Effective date**: 2026-05-08

**Companion document**: This document is the TPRR Development and Validation companion to the canonical methodology specification at [`docs/tprr_methodology.md`](tprr_methodology.md). Where the methodology specification states *what* TPRR is, this document covers *why* it took its v1.3 form: the strategic origin that motivated the index, the methodology refinement arc through Phase 7H and Phase 10A, the empirical validation findings produced across thirteen sweeps in the v0.1 reference codebase, and Noble's forward roadmap toward production publication.

**Document scope**: This is Noble's internal engineering and validation companion to the canonical methodology specification. It is structured around the build history (Phase 7H + Phase 10A methodology refinement, Phase 10 + Phase 11A empirical validation) and serves as institutional-memory infrastructure for Noble engineers, future contributors, and Index Committee members. The external-facing TPRR Methodology White Paper, prepared for academic readers and external Index Committee audiences, is published separately as `docs/tprr_white_paper.md` (Phase 12 deliverable).

# **1. Origin and Strategic Context**

TPRR exists because no commercial pricing reference for AI inference exists, and because the market that needs one has grown to the point where the absence is now structurally costly. This section sets out the gap we identified, the historical precedent for resolving it, the strategic position we built TPRR to occupy, and the derivative-market formation we expect TPRR to enable. The technical specification of how TPRR is calculated lives in [methodology spec §3](tprr_methodology.md); this section addresses why we built it.

## **1.1 The AI inference cost gap**

Over the past three years, AI inference has moved from R&D experimentation into operational scale. Enterprises that started by routing a handful of internal queries through GPT-3 are now spending tens of millions of dollars annually on production-grade API calls across multiple providers. What started as a discretionary IT line item buried within larger cloud and software budgets is now a top-twenty operating expense for many large adopters, and a top-five line item for the AI-native cohort. Forward enterprise spending estimates from the major cloud providers suggest that aggregate AI inference spend will exceed several major cloud-native software categories within two years.

This growth has outpaced the financial infrastructure that exists to manage it. Other operationally significant enterprise costs (cloud compute, software licensing, energy procurement, FX exposure, commodity inputs) have established benchmarking and risk-transfer infrastructure. CFOs hedging energy costs reference established benchmarks; FX exposures hedge against published reference rates; even cloud compute is increasingly procured under reserved-capacity contracts whose pricing is anchored to published list prices. Token-priced AI inference has none of this: no benchmark, no derivative instruments, no risk-transfer framework, no objective basis for performance attribution.

The gap manifests in three distinct ways at the enterprise level. First, **budget uncertainty**: forecasted AI spend cannot be anchored to any external reference, so variance between forecast and actual flows directly through to earnings. Second, **no hedging instrument**: even where a CFO would prefer to lock in token prices for a forward period, no derivative instrument exists, because no settlement reference exists. Third, **no performance attribution**: when an enterprise switches between providers or model tiers, it has no benchmark against which to evaluate whether the change represents a value improvement or a value destruction. Each of these is a discrete cost, borne in real budgets and real earnings volatility today, and each grows as AI inference spend grows.

## **1.2 Why no benchmark exists today**

The reason no benchmark exists is not for lack of data. AI inference prices are publicly posted. The reason is that the data is structurally incomparable.

First, **prices are set unilaterally by providers**, with no mechanism for market-wide reference. Each provider publishes its own pricing page; the prices change without notice; the per-token rates differ by model version, by usage tier, by enterprise volume commitment. There is no analogue of the bilaterally-negotiated, broker-cleared, published-quote market structure that produced LIBOR or the physical-cargo market structure that produced Brent.

Second, **prices vary by model version and tier within each provider**. A reference to "GPT-5" or "Claude Opus" without version and tier is operationally meaningless; the same provider will price the same family at different rates for different deployment contexts. A benchmark that aggregates across providers must first normalize across this internal variation.

Third, **prices are quoted in unit economics that aren't directly comparable across providers without normalization**. Per-Mtok rates are quoted in USD, but the units of denomination (what counts as one token, how input tokens are distinguished from output tokens, how reasoning or vision modalities are priced) vary across providers' tokenizer implementations and pricing taxonomies.

Fourth, the **producer-of-record problem**: there is no independent third-party producer with a credible market-wide view of inference token volumes. Providers self-report user-counts and revenue figures in earnings calls and investor materials; analyst firms triangulate; OpenRouter and other transaction-aggregators capture a subset of the market. None of these is suitable as a sole basis for market-weighted indexation, because none has the cross-provider audit credibility that benchmark methodologies require.

These four obstacles are not insurmountable, but each requires a methodological response. We built the v1.3 methodology specifically to handle them: the three-tier attestation hierarchy ([methodology spec §3.3.2](tprr_methodology.md)) addresses the producer-of-record problem through triangulation across independent data sources; the slot-level data quality gate ([methodology spec §4.2.2.1](tprr_methodology.md)) addresses the unilateralism by neutralizing single-source price excursions; the version-confirmation rule ([methodology spec §4.1](tprr_methodology.md)) addresses the model-version variation. The development of these mechanisms was not theoretical; it was driven by what the v0.1 implementation work surfaced (see §2 below).

## **1.3 Benchmark precedent for new asset classes**

Where the AI inference market sits today is structurally similar to where several other commodity and rate markets sat at the beginning of their derivative-formation arcs. In each historical case, bilateral contract-based pricing existed first, an index was built to standardize that pricing into a market-wide reference, and only then did derivative instruments form against the index.

LIBOR's history is the clearest analogue. The British Bankers' Association did not invent interest rate swaps; bilateral fixed-for-floating arrangements existed before LIBOR. What LIBOR provided was a daily, published, multi-bank reference rate that allowed those bilateral arrangements to settle against a common standard rather than against each counterparty's individual cost-of-funds estimate. Once that reference existed, the swap market expanded by orders of magnitude, and futures and options markets formed against the rate.

WTI and Brent followed similar arcs in oil. Bilateral cargo contracts existed long before either reference; the indices emerged to standardize pricing across geographically and qualitatively heterogeneous physical deliveries. Once the references were established, NYMEX WTI and ICE Brent futures formed, and the modern oil derivatives market followed.

Henry Hub did the same for natural gas. Bilateral pipeline contracts existed; what was missing was a delivery-point benchmark that could anchor financial settlement. The CME natural gas futures contract referenced Henry Hub from 1990 onward; the gas derivatives market grew from that anchor.

The pattern is robust: index precedes derivative. The index does not displace bilateral contracting (that continues, often in larger volumes than the index-referenced market). The index provides the third-party measurement that makes risk transfer possible across counterparties who do not share contract terms.

We expect the AI inference market to follow this arc. Bilateral arrangements between large enterprises and specific providers already exist; volume commitments, capacity reservations, and negotiated discount structures are common at the enterprise tier. What is missing is the index. Once TPRR exists as a published, audited, independently-governed reference, the derivative instruments that allow cross-counterparty risk transfer can form against it.

## **1.4 Noble's strategic positioning**

We built TPRR with a specific strategic position in mind: the first-mover institutional reference rate for AI inference token pricing. Indices have strong network-effect economics. The reference rate that achieves widespread institutional adoption first becomes the reference rate that derivatives are written against, that financial reporting is anchored to, that regulatory disclosure compares against. Once a reference is established as *the* reference for an asset class, displacement is structurally hard: every contract that exists, every reporting framework that has incorporated it, every derivative book that hedges against it raises the switching cost for the next entrant.

LIBOR illustrates the durability: even after the regulatory disclosure of LIBOR's manipulation problems, the multi-year reform process to replace LIBOR with overnight rates required global coordination across regulators, ISDA, and the entire derivative dealer community. The replacement process did not happen because LIBOR was technically inferior; it happened because regulators forced the transition. Absent a manipulation crisis, established reference rates persist by network effect.

We built TPRR to be the institutional reference rate for AI inference token pricing in advance of any competing benchmark. The v1.3 methodology is designed to satisfy IOSCO Principles for Financial Benchmarks ([methodology spec §5.3](tprr_methodology.md)) so that the regulatory positioning is in place before the asset class matures. The three-tier hierarchy is designed for credibility with institutional reviewers, not for ease of construction. The dual-weighted formula's manipulation-resistance properties are designed for derivative-settlement use, not just informational publication.

This is a deliberately patient strategy. The v0.1 reference codebase is internal validation infrastructure, not the production publication. The methodology will go public, under the IOSCO disclosure framework, concurrent with production launch ([methodology spec §5.3](tprr_methodology.md)). The intermediate steps are the validation work that builds the methodology's credibility before disclosure. We treat the validation as load-bearing for the strategic position; an institutional reference rate built without validation against scenario suites and parameter sensitivity sweeps would not survive its first sophisticated reviewer (see §3 below for the validation findings).

## **1.5 Derivative applications**

TPRR exists to enable a derivative market that does not yet exist. Once an institutional-grade pricing reference for AI inference token costs is in place, the OTC derivatives that allow enterprises to hedge token-price exposure, and that allow financial institutions to take the other side of those hedges, become structurable. Without the reference, derivative counterparties have no common settlement basis; with the reference, the same risk-transfer infrastructure that exists for interest rates, currencies, and physical commodities can be built for AI inference.

Three instrument types follow naturally from established commodity-derivative conventions, each addressing a distinct enterprise hedging need. **Fixed-for-floating inference swaps** allow an enterprise to lock in a fixed token-cost rate against floating TPRR for a defined notional and tenor, neutralizing the budget-uncertainty problem documented in §1.1. The structure mirrors the interest rate swap: counterparty A pays a fixed rate per Mtok, counterparty B pays the published TPRR fixing on each settlement date, net cash settlement based on the difference. **Cap and floor structures** provide one-sided protection (a cap protects the enterprise against token-cost increases above a strike, a floor protects a provider against rate decreases), analogous to interest-rate caps and commodity collars. These are useful for enterprises that want upside on their existing pricing relationships while protecting against catastrophic moves. **Forward TPRR contracts** allow an enterprise to lock in a token-cost rate for a defined future period, settled against the average TPRR over that period: the structure used for forward commodity procurement.

The availability of these instruments depends on the prior existence of TPRR. This is the strategic-positioning loop identified in §1.3 and §1.4: the index must exist before the derivatives can form, and the index must be institutional-grade before derivative counterparties will use it for settlement reference. We are building TPRR specifically to satisfy the governance, methodology audit, manipulation resistance, and regulatory positioning requirements that derivative counterparties demand. The Argon-Xenon currency-hedged variant (§1.6 below) extends the structurable instrument set further by enabling joint token-price + FX-translation hedging in a single contract, a structure with no current market precedent.

## **1.6 Currency dimension and currency-hedged inference swaps**

For non-USD enterprises, AI inference cost is a dual exposure. Token prices are USD-denominated and set unilaterally by providers; the enterprise's effective cost in its functional currency depends jointly on the USD per-token rate and the FX translation between USD and the enterprise's reporting currency. A European enterprise paying in USD for frontier-tier inference faces both the risk that the provider raises its per-token rate and the risk that EUR/USD moves adversely.

Today, no single instrument exists to hedge this dual exposure. An enterprise that wished to hedge would need to construct a separate FX hedge (typically EUR/USD forward contracts or swaps) alongside whatever token-cost hedge it could arrange (today: a bilateral commitment with the provider, since no token-cost derivative exists). The operational burden of managing two separate hedging instruments with two separate counterparties is non-trivial, and the basis between the two hedges is unmanaged.

Noble's planned approach is to publish currency-neutral TPRR variants for EUR, GBP, and JPY using mid-market FX rates from the Xenon FX intelligence layer (Noble's companion product line). This enables non-USD enterprises to benchmark their effective token costs in functional currency terms, and, critically, enables the construction of single-instrument currency-hedged inference swaps. Such an instrument would settle the token-price leg against TPRR-F (or -S, -E) and the currency-translation leg against the corresponding Xenon FX reference, all in a single contract with a single counterparty. This is a structural innovation made possible by the integrated Argon-Xenon architecture; we are not aware of any precedent in commodity-derivative markets, where the underlying commodity reference and the FX reference are typically separate ecosystems.

The currency-hedged variants are scoped for production deployment alongside the FX-hedged publication infrastructure flagged in [methodology spec §4.3](tprr_methodology.md). Both the variants and the associated derivative instruments depend on TPRR's establishment as the institutional reference rate; Argon-Xenon integration is a multiplier on TPRR's strategic position, not a substitute for it.

# **2. Methodology Development Arc**

The v1.3 methodology was not a single design step; it was the product of a refinement arc that ran across Phase 7H (April 2026) and Phase 10A (early May 2026). The arc began with the literal-canon implementation of the pre-7H specification, which surfaced cliff-edge dynamics on the v0.1 reference panel. Four substantive methodology modifications proposed in Phase 7H, plus a fifth surfaced in Phase 10A, cumulatively resolved the cliff-edge problem and produced the v1.3 specification documented in the canonical [methodology spec](tprr_methodology.md). Throughout this section, the reference signal for cumulative effect is **TPRR_F base_date `tier_a_weight_share` at seed-42**: the proportion of the F-tier index's volume weight derived from Tier A (contributor-attested) data on the base date, under the v0.1 synthetic panel. Pre-Phase-7H, this signal sat at 0.0012, indicating that 99.88% of the F-tier weight was being driven by Tier B revenue-derived volumes: the cliff-edge problem in concrete form. Post-Phase-7H + Phase-10A, the same signal sits at 0.9261, indicating that 92.61% of F-tier weight is now Tier A. The rest of this section walks the trajectory from one to the other.

## **2.1 Pre-Phase-7H literal-canon implementation and the cliff-edge problem**

The pre-Phase-7H implementation followed Section 3.3.2 of the original methodology specification verbatim. Per-constituent volume weights were computed as `w_vol = raw_volume × confidence_haircut` where the raw volume was the sum of contributor-reported volumes within the constituent's highest-tier coverage. The dual-weighted aggregation then combined `w_vol × w_exp × P̃` across constituents and normalized by Σ(`w_vol × w_exp`). Where multiple tiers had data for a given constituent on a given fixing date, the methodology selected the highest-confidence tier via a priority fall-through ordering (A → B → C); the selected tier's volume was used, the others were ignored.

Two problems surfaced in Phase 7 implementation. The first was a **cross-tier magnitude cascade** documented in DL 2026-04-30 — Phase 7 Batch C empirical: cross-tier magnitude cascade manifests within single-seed backtest. Tier A panel-sum volumes (the sum across the v0.1 reference panel's 10 contributors of each contributor's reported 7-day volume per constituent) ran in the low single-digit thousands of Mtok. Tier B revenue-derived volumes, computed by allocating disclosed provider revenue across that provider's models via OpenRouter within-provider split and dividing by a reference price, ran in the hundreds of millions of Mtok. The magnitude gap on the v0.1 reference panel was approximately 66,000:1 between Tier B and Tier A. Under raw-volume aggregation, Tier B's signal dominated regardless of the confidence haircut applied: a 0.9 haircut on a value 66,000× larger than the alternative still produces a value 59,400× larger.

The second problem was **cliff-edge dynamics at the priority-fall-through threshold**, documented in DL 2026-04-30 — Phase 9 visual diagnostic: cliff-edge weight share dynamics + asymmetric E-tier exclusion paths. Under priority fall-through, a constituent's tier selection on a given date depended discontinuously on the count of contributors meeting the minimum-3 threshold. A constituent with three Tier A contributors used Tier A; the same constituent with two Tier A contributors fell through to Tier B (or C); the resulting volume could differ by orders of magnitude depending on which tier was selected. Across the 366-day backtest, suspension events that pushed contributor counts across the minimum-3 boundary produced sharp discontinuities in the weight-share trajectory.

The cumulative effect on TPRR_F at seed-42 was that the F-tier index's volume weight came almost entirely from Tier B revenue-derived volumes: TPRR_F base_date `tier_a_weight_share` = 0.0012, meaning 0.12% of the F-tier's volume weight derived from contributor-attested data, with the remaining 99.88% from Tier B's compounded-bias revenue-derivation chain. The methodology was producing a volume-weighted index in name but, on the v0.1 reference panel, was essentially a Tier-B-driven index in practice. This was not the intended methodology behavior; it was an emergent consequence of cross-tier magnitude commensurability under raw-volume aggregation.

## **2.2 The Phase 7H proposal**

DL 2026-04-30 — Phase 7H methodology design: continuous blending, within-tier normalization, Tier B confidence recalibration, suspension reinstatement set out four substantive methodology modifications proposed as a candidate v1.3 specification. The four modifications were designed to address distinct issues surfaced by the Phase 7 implementation:

1. **Within-tier-share normalization** to resolve cross-tier magnitude commensurability without requiring tier-specific magnitude calibration.
2. **Continuous blending across all available tiers** to replace priority fall-through, eliminating the threshold-driven discontinuities that produced cliff-edge dynamics.
3. **Tier B confidence haircut recalibration** (0.9 → 0.5) to reflect the bias chain documented in the cross-tier magnitude analysis, plus a reordering of tier confidence (A > C > B rather than A > B > C) to reflect Tier C's lower bias-chain length relative to Tier B.
4. **Bidirectional suspension/reinstatement criteria** with asymmetric thresholds (3-day suspend, 10-day reinstate) to replace the v1.2 one-way ratchet that left suspended pairs permanently excluded absent manual reinstatement.

Each modification was implemented as a single batch (A through D respectively), with empirical effects measured cumulatively on the seed-42 reference panel. The implementation order was chosen to allow each batch's effect to be characterized independently, and to verify that the cumulative trajectory matched the design intent. The remainder of §2 walks each batch in order, then folds in the fifth modification (the tier-eligibility threshold) added in Phase 10A.

## **2.3 Phase 7H Batch A: within-tier-share normalization**

Batch A (DL 2026-04-30 — Phase 7H Batch A: within-tier-share normalization) replaced the raw-volume formulation with within-tier-share normalization. Within each attestation tier, each constituent's contribution is now expressed as the fraction of that tier's total volume that the constituent represents:

```
within_tier_share_{i,t} = volume_{i,t} / Σ_{j ∈ active(t)} volume_{j,t}
```

The result is bounded in [0, 1] regardless of the underlying magnitude. The blended volume contribution then combines this within-tier share with the tier's confidence haircut.

The effect on cross-tier magnitude commensurability is structural. Tier A's panel-sum volumes and Tier B's revenue-derived volumes are no longer in the same units in the aggregation; both are dimensionless fractions summing to 1 within their respective tiers. The 66,000:1 magnitude gap that drove the cliff-edge problem disappears in the within-tier-share representation.

**Empirical effect on TPRR_F base_date `tier_a_weight_share` at seed-42**: 0.0012 → 0.5083. With Tier A and Tier B each represented as fractions of their respective tier totals, applying the canonical blending coefficients (A=0.6, C=0.3, B=0.1) and the canonical haircuts produced an F-tier where Tier A's contribution to the weight share rose from 0.12% to 50.83%. Cross-reference: [methodology spec §3.3.2.3](tprr_methodology.md).

## **2.4 Phase 7H Batch B: continuous blending replaces priority fall-through**

Batch B (DL 2026-04-30 — Phase 7H Batch B audit trail design: long-format per-tier breakdown, with the supporting design rationale in DL 2026-04-30 — Phase 7H methodology design and the symmetric coefficient × tier_price specification in the post-design addendum) replaced priority fall-through with continuous blending. Each constituent on each fixing date now contributes via the weighted sum across all attestation tiers for which data is available, rather than via a single tier selected via priority order.

The blending is symmetric across volume and price contributions:

```
w_vol_i = Σ_t [ coefficient_t × within_tier_share_{i,t} × haircut_t ]
P̃_i    = Σ_t [ coefficient_t × P̃_{i,t} ]
```

Default coefficients are A=0.6, C=0.3, B=0.1; coefficients redistribute proportionally to active tiers when a constituent has data in fewer than all three tiers. The audit trail expanded from one row per (constituent, date) to one row per (constituent, tier, date), allowing per-tier contribution to be inspected directly.

The mechanism resolution is straightforward. Under priority fall-through, a constituent's tier could change abruptly as contributor counts crossed the minimum-3 boundary, producing the threshold-driven discontinuities documented in the pre-7H diagnostics. Under continuous blending, the contribution from each tier is always proportional to its coefficient and within-tier share; there is no threshold at which one tier replaces another. Coverage transitions produce smooth changes in weight share rather than cliff-edge transitions.

**Empirical effect on TPRR_F base_date `tier_a_weight_share` at seed-42**: 0.5083 → 0.6980. Cross-reference: [methodology spec §3.3.2.2](tprr_methodology.md).

## **2.5 Phase 7H Batch C: Tier B confidence recalibration and tier ordering**

Batch C (DL 2026-04-30 — Phase 7H Batch C: Tier B confidence haircut 0.9 → 0.5 + tier ordering A > C > B) recalibrated Tier B's confidence haircut from 0.9 to 0.5 and reordered the tier confidence hierarchy from A > B > C to A > C > B.

The Tier B haircut recalibration reflects the bias chain documented in the same DL entry. Tier B's volume estimates are derived through a four-step chain: (1) the provider's total disclosed revenue, which includes non-API revenue (subscriptions, licensing, professional services) and Enterprise flat-rate API tiers where effective per-token rates differ from published rates; (2) an analyst-triangulated API-revenue share applied to that total; (3) an OpenRouter-derived within-provider model split applied to the API revenue; (4) a reference price used to back out implied volume from implied revenue. Each step compounds bias upward; the cumulative bias on Tier B implied volumes is plausibly 30–50% high for some providers under the v0.1 calibration. The 0.5 haircut reflects this bias chain explicitly; the 0.9 haircut from the prior specification was calibrated against an implicit assumption that Tier B was directly comparable to Tier A in raw form, which the cross-tier magnitude cascade had already invalidated.

The tier reordering (A > C > B) reflects that Tier C, direct third-party transaction measurement via OpenRouter, has a single-step bias chain (user-base composition skew) compared to Tier B's four-step chain. Even though Tier B's whole-provider scope is broader than Tier C's developer-segment slice, the bias-chain length argument places Tier C above Tier B in confidence. The numerical haircut values (A=1.0, C=0.8, B=0.5) under v1.3 reflect this reordering.

**Empirical effect on TPRR_F base_date `tier_a_weight_share` at seed-42**: 0.6980 → 0.8063. The lower Tier B haircut reduces Tier B's contribution to the blended weight; Tier A's relative contribution rises correspondingly. Cross-reference: [methodology spec §3.3.2.1](tprr_methodology.md).

## **2.6 Phase 7H Batch D: bidirectional suspension/reinstatement**

Batch D (DL 2026-04-30 — Phase 7H Batch D: suspension reinstatement (3-day exclude / 10-day reinstate)) replaced the v1.2 one-way suspension ratchet with bidirectional, asymmetric criteria. A (contributor, constituent) pair that experiences three consecutive fixing days with at least one slot-level gate firing is suspended; the pair is reinstated only after ten consecutive fixing days with no slot-level gate firings. Days with no panel row reset both counters.

The asymmetry (3-day suspend, 10-day reinstate) creates a stability bias that prevents oscillation near the threshold. A pair that has just been reinstated must accumulate ten clean consecutive days before its next reinstatement could occur; a pair that has been clean for nine days and fires on day ten resets to zero clean days, deferring reinstatement. The missing-day reset preserves the "observed on-market" semantic of reinstatement: a contributor that goes silent does not earn reinstatement progress on those days.

The methodology rationale for replacing the one-way ratchet was practical. Under the v1.2 ratchet, a pair suspended on day 4 of the backtest (say, due to an isolated outlier slot) would remain suspended for the remaining 362 days, contributing nothing to the index, until manually reinstated by a governance process. On the v0.1 reference panel, this produced a steady-state condition where many F-tier (contributor, constituent) pairs were suspended through the back half of the backtest, leaving the F-tier reliant on a small number of never-suspended pairs. The bidirectional criterion allows pairs to recover from isolated suspension events while preserving the gate-firing-based exclusion for sustained data quality issues.

**Empirical effect on TPRR_F base_date `tier_a_weight_share` at seed-42**: 0.8063 → 0.9261. The reinstatement of suspended F-tier pairs by base_date returns the F-tier active constituent count `n_a` from a partial subset to the full set of 6 constituents. This is the cumulative resolution of the cliff-edge problem identified pre-Phase-7H. Cross-reference: [methodology spec §4.2.2.2](tprr_methodology.md).

## **2.7 Phase 10 Batch 10A: tier-eligibility threshold**

Phase 10 Batch 10A (DL 2026-05-01 — Phase 10 Batch 10A: Tier C enrich-call bug fix + tier-eligibility threshold for continuous blending) added a fifth modification surfaced through the Phase 10 in-memory sensitivity sweep work. The empirical trigger was a latent bug in the Tier C enrichment pipeline: the call to `enrich_with_rankings_volume` was passing a `rankings_json` dict instead of the flattened `rankings_df`, with the result that Tier C volumes were not flowing through to the indexer. Fixing the bug exposed a methodological problem: under continuous blending, when a tier has only one active constituent, that constituent automatically receives `within_tier_share = 1.0` by construction. On the v0.1 reference panel, deepseek-v3-2 is the sole Tier C constituent (Tier C coverage in v0.1 is sparse: 1 of 16 constituents). With the Tier C bug fixed and continuous blending applied, deepseek-v3-2 alone drove `tier_c_weight_share` to 0.488 in TPRR_E, meaning 48.8% of the E-tier blended volume weight was derived from a single Tier C constituent. This violated the methodology's minimum-independent-observations principle.

The methodology resolution extended the existing minimum-3-contributors-per-constituent threshold from the contributor → constituent layer to the constituent → tier layer. Under v1.3, an attestation tier within an index tier with fewer than three active constituents is **dormant** for that index tier; its blending coefficient redistributes proportionally to active tiers via the existing redistribution rule. The audit trail preserves dormant-tier rows with `coefficient=0`, `w_vol_contribution=0`, `included=True`, ensuring full reproducibility while making the dormancy decision visible to auditors.

The framing point for this modification is structural rather than corrective. The threshold is not a v0.1-specific patch; it is a specification that ensures the methodology behaves predictably as Tier C coverage expands in subsequent versions. Under v0.1, Tier C is dormant for all three index tiers because deepseek-v3-2 is the only Tier C constituent. Under v0.2+, when Tier C coverage exceeds three constituents per index tier (via OpenRouter full-models endpoint ingestion or complementary third-party data sources, per §4.1 below), Tier C activates automatically without requiring a methodology version increment. The methodology behaves identically pre- and post-coverage-expansion at the published level; only the empirical contribution of Tier C to the blended weights changes. This is the smooth-activation property documented in [methodology spec §3.3.2.4](tprr_methodology.md). Cross-reference: [tier_eligibility_threshold_mechanism.md](findings/tier_eligibility_threshold_mechanism.md).

**Empirical effect on TPRR_F**: no change (0.9261 invariant), because TPRR_F has no Tier C constituents in the v0.1 panel. Empirical effect on TPRR_E base_date `tier_c_weight_share` at seed-42: 0.488 → 0.000, with the redistributed weight flowing primarily back to Tier A (`tier_a_weight_share` rose from 0.4718 to 0.9322 on E-tier).

## **2.8 Cumulative trajectory**

The five modifications (Phase 7H Batches A through D plus Phase 10A's tier-eligibility threshold) constitute the v1.3 methodology refinement arc. Cumulatively, on the seed-42 reference panel, they produce the following TPRR_F base_date `tier_a_weight_share` trajectory:

| Stage | TPRR_F base_date `tier_a_weight_share` | F-tier active constituent count `n_a` | Methodology modification |
|---|---:|---:|---|
| Pre-Phase-7H literal-canon | 0.0012 | 3 | (baseline; priority fall-through + raw-volume aggregation) |
| Post-Batch A | 0.5083 | 3 | + within-tier-share normalization |
| Post-Batch B | 0.6980 | 3 | + continuous blending |
| Post-Batch C | 0.8063 | 3 | + Tier B haircut 0.9 → 0.5; tier ordering A > C > B |
| Post-Batch D | 0.9261 | 6 | + bidirectional suspension/reinstatement |
| Post-Batch 10A | 0.9261 | 6 | + tier-eligibility threshold (no F-tier effect) |

Each modification contributes a distinct increment, and the cumulative effect resolves the cliff-edge problem from a 0.0012 baseline (degenerate) to a 0.9261 endpoint (full F-tier activation with Tier A providing the dominant volume signal). The Batch D reactivation of suspended F-tier pairs returns `n_a` from 3 to 6: every F-tier constituent contributes at base_date.

The seed-42 trajectory is the reference signal; the methodology-level cliff-edge resolution holds across the broader Phase 7H continuous-blending design space. Across the 60 seed × Phase 7H-config combinations tested in Batch 10C (3 configs × 20 seeds), every seed reports `n_a = 6` at base_date with no regression to the pre-Phase-7H 0.0012 baseline; the cross-config distribution of `tier_a_weight_share` shifts upward modestly (mean 0.90 → 0.92 → 0.94 across loose / default / tight) while the response shape is preserved. The full multi-seed cross-config evidence is in §3.7 below; the point here is that the seed-42 cumulative trajectory generalizes: the cliff-edge resolution is structural across the design space, not a seed-42 artefact.

![Figure 2.1: TPRR_F base_date tier_a_weight_share trajectory across the Phase 7H + Phase 10A methodology refinement arc, on the seed-42 reference panel. Each modification incrementally relieves cliff-edge dynamics; cumulative refinement produces a 0.0012 → 0.9261 trajectory with full F-tier activation (n_a = 6) at the endpoint. Cross-config range at endpoint shows [loose=0.9002, default=0.9192, tight=0.9387]; default sits inside the envelope, confirming robustness across the Phase 7H continuous-blending design space.](charts/development/cliff_edge_resolution_arc.svg)

*Figure 2.1: TPRR_F base_date tier_a_weight_share trajectory across the Phase 7H + Phase 10A methodology refinement arc, on the seed-42 reference panel. Each modification incrementally relieves cliff-edge dynamics; cumulative refinement produces a 0.0012 → 0.9261 trajectory with full F-tier activation (n_a = 6) at the endpoint. Cross-config range at endpoint shows [loose=0.9002, default=0.9192, tight=0.9387]; default sits inside the envelope, confirming robustness across the Phase 7H continuous-blending design space.*

The cumulative trajectory is the methodology refinement deliverable. It is also the empirical case for taking the v1.3 modifications seriously: the literal-canon implementation produces a degenerate Tier-B-dominated index on the v0.1 reference panel; the v1.3 modifications restore the methodology's intended behavior. The decision to publish v1.3 as the canonical methodology rather than continue with the pre-Phase-7H specification is made on this evidence.

# **3. Empirical Validation Findings**

## **3.1 Validation scope**

The v1.3 methodology has been empirically tested across 13 sensitivity sweeps cataloged in `data/indices/sweeps/manifest.csv`, run against the v0.1 reference panel (10 contributors × 16 constituents × 366 backtest days, January 2025 → January 2026, base_date 2026-01-01). The validation work was organized in three batches, each extending the parameter envelope tested:

- **Phase 10 Batch 10A** (in-memory sweeps): λ ∈ [1, 2, 3, 5, 10]; Tier B haircut ∈ [0.4, 0.5, 0.6, 0.7]; blending coefficient ∈ {default, B-up, C-up, equal}; suspension threshold ∈ [2, 3, 5, 7]; reinstatement threshold ∈ [5, 10, 15, 20]. Single seed (42).
- **Phase 10 Batch 10B** (pipeline-rerun sweeps): suspension threshold, reinstatement threshold, gate threshold ∈ [5%, 10%, 15%, 20%, 25%, 30%], TWAP ordering. Single seed (42), with each parameter swept against the clean panel + 6 scenarios.
- **Phase 10 Batch 10C** (multi-seed × scenarios): three Phase 7H configurations (loose / default / tight) × 20 seeds (42–61) × {clean panel, 6 scenarios}. 480 panel runs total, executed via [`scripts/multi_seed_sweep.py`](../scripts/multi_seed_sweep.py).
- **Phase 11 Batch 11A** (gate × scenarios × seeds): six gate values (5% through 30%) × 20 seeds × {clean panel, 6 scenarios}. 840 panel runs total, executed via [`scripts/gate_x_scenarios_x_seeds_sweep.py`](../scripts/gate_x_scenarios_x_seeds_sweep.py).

Together these cross-products characterize the methodology's response across every primary parameter axis, with multi-seed validation establishing cross-realization robustness on the central axes.

![Figure 3.1: Per-tier TPRR index level across the 366-day backtest, canonical config. Centerline shows per-day median across 20 seeds (42-61); shaded band shows 5th-95th percentile across seeds. All three tiers rebased to index_level=100 at base_date (2026-01-01); convergence at the right edge is an artifact of this rebasing convention rather than an economic phenomenon. Differential decline rates across tiers: TPRR-E declined ~73% from 2025-Q1 to base_date, TPRR-S declined ~49%, and TPRR-F declined ~42%. These differential rates reflect efficiency-tier prices declining faster than frontier-tier prices over the backtest period — a real economic trend distinct from the geometric rebasing artifact.](charts/development/tprr_index_level_over_time_canonical.svg)

*Figure 3.1: Per-tier TPRR index level across the 366-day backtest, canonical config. Centerline shows per-day median across 20 seeds (42-61); shaded band shows 5th-95th percentile across seeds. All three tiers rebased to index_level=100 at base_date (2026-01-01); convergence at the right edge is an artifact of this rebasing convention rather than an economic phenomenon. Differential decline rates across tiers: TPRR-E declined ~73% from 2025-Q1 to base_date, TPRR-S declined ~49%, and TPRR-F declined ~42%. These differential rates reflect efficiency-tier prices declining faster than frontier-tier prices over the backtest period — a real economic trend distinct from the geometric rebasing artifact.*

The validation work demonstrably tests:

- **Methodology behavior on a synthetic but realistically-calibrated panel** with all three tiers populated according to v0.1 coverage assumptions (Tier A: 10 contributors per constituent; Tier B: implied volumes from disclosed revenue × OpenRouter within-provider split; Tier C: OpenRouter top-9 rankings snapshot, deepseek-v3-2 alone covered).
- **Sensitivity to all four downstream parameters** (λ, Tier B haircut, blending coefficients, suspension/reinstatement) and to the upstream gate threshold.
- **Stability across panel realizations**: 60 seed × Phase 7H-config combinations from Batch 10C, plus 120 seed × gate combinations from Batch 11A, totalling 180 multi-seed cells across the central design space.
- **Manipulation resistance against the v0.1 scenario suite**: six scenarios (`fat_finger_high`, `intraday_spike`, `correlated_blackout`, `stale_quote`, `shock_price_cut`, `sustained_manipulation`) at every Phase 7H downstream design point swept and at every gate value swept.

The validation work does not test, and the scope of empirical claims throughout this document reflects these limits:

- **Real provider price dynamics**: the validation runs against synthetic Tier A panels with calibrated baseline prices, not against real contributor billing data.
- **Real volume attribution**: Tier B revenue inputs are analyst-triangulation point estimates per quarter, not audited disclosures with subscription-tier carve-outs.
- **Real Tier C coverage breadth**: only the top-9 OpenRouter rankings snapshot was ingested (1 of 16 v0.1 constituents covered); the OpenRouter full-models endpoint and complementary third-party data sources are deferred to v0.2+.
- **Adversarial scenarios beyond the v0.1 suite**: the six scenarios were authored alongside the methodology, with the gate-and-suspension mechanisms in mind; adversarial scenarios authored independently by a red team have not been tested.
- **Upstream-parameter × scenario interaction beyond gate threshold**: Batch 11A swept gate × scenarios × seeds; minimum-3 threshold × scenarios, suspension/reinstatement policy × scenarios, TWAP ordering × multi-seed × scenarios, and tier-eligibility threshold × scenarios were not run.
- **Real-time / production publication dynamics**: single-shot backtests, not live publication with intraday revision discipline.

These limits bound every claim in §3.3 through §3.10. §3.11 enumerates them as a consolidated scope-gap inventory; the rest of §3 describes what the validation found within the scope tested.

## **3.2 Two-layer narrative and three-regime distinction**

The validation findings organize around a structural framing device that reflects the methodology's dual character: a published reference rate that is robust to methodology parameter choice within reasonable ranges, alongside an intermediate-day trajectory that is genuinely sensitive to methodology parameters. Both behaviors are intentional and complementary.

The two layers serve different consumers. Reference-rate consumers (CFOs, treasurers, regulators, derivative settlement counterparties) need to know that the published level is not an artefact of arbitrary parameter choice; the validation finding that three of four downstream parameters leave TPRR_F base_date raw_value invariant within their swept ranges (§3.3) is the institutional-grade robustness statement that addresses this need. Analyst trajectory consumers (research analysts, traders, derivative designers) need visibility into how the intermediate-day series responds to methodology choice; the same parameter sweeps produce 51–88% of trajectory days differing across the swept ranges, which is the analyst-visibility statement.

The three regimes emerge when scenario absorption is added to the parameter-sensitivity picture. Parameter sweeps on the clean panel produce the two-layer pattern (published-rate robust, trajectory sensitive). F-tier scenario sweeps produce a stronger result: at every (config, seed, scenario, day) tested, TPRR-F is byte-identical to clean (§3.8); both layers are absorbed simultaneously, so neither "needs defending" against the v0.1 scenario suite. S-tier and E-tier scenario sweeps produce the two-layer pattern in attenuated form: the published rate stays robust, while specific scenarios produce trajectory variation that depends on tier-specific structural properties (§3.9). The three regimes (parameter-sweep two-layer, F-tier absorption, S/E-tier filter-and-absorb) are the central organizing distinction for the rest of §3.

## **3.3 Three-of-four downstream parameter base-date invariance**

Phase 10 Batch 10B (DL 2026-05-01 — Phase 10 Batch 10B: pipeline-rerun sweeps (suspension threshold, reinstatement threshold, gate threshold, TWAP ordering)) ran four pipeline-rerun parameter sweeps on the seed-42 reference panel: suspension threshold ∈ {2, 3, 5, 7}, reinstatement threshold ∈ {5, 10, 15, 20}, gate threshold ∈ {5%, 10%, 15%, 20%, 25%, 30%}, and TWAP ordering ∈ {twap_then_weight, weight_then_twap}. The cross-sweep finding from this batch is that **three of four parameters leave TPRR_F base_date raw_value invariant within their swept ranges**.

The suspension-threshold sweep produces TPRR_F base_date raw_value = 30.2405 USD/Mtok at every threshold value tested (2, 3, 5, 7 days). The reinstatement-threshold sweep produces the same invariant value at every threshold (5, 10, 15, 20 days). The TWAP-ordering sweep produces a 0.0001 USD/Mtok base_date delta, practically zero (see §3.6 for the empirical equivalence finding). The gate threshold is the exception: base_date raw_value = 28.23 (5%) → 28.94 (10%) → 30.24 (15%, 20%, 25%, 30% all identical). The canonical 15% sits exactly on the convergence edge: gates at or above 15% produce identical published levels; gates strictly below 15% materially shift the level downward.

The mechanism for the base-date invariance is the suspension/reinstatement cycle. The 366-day backtest is long relative to the suspension cycle (3-day exclude → 10-day reinstate); pairs that get suspended during the backtest typically reinstate before the base_date. The base_date sees the steady-state constituent set under any suspension/reinstatement parameter that admits eventual reinstatement. Only parameters that change the filter at the input boundary (the gate threshold) can change which prices the methodology consumes at base_date. And even then, the canonical 15% sits above the convergence edge.

Trajectory sensitivity is the dual to base-date invariance. The same four sweeps produce material intermediate-day variation: suspension produces 75 / 366 (20%) TPRR_F days differing and 186 / 366 (51%) TPRR_E days differing; reinstatement produces 80 / 366 (22%) and 227 / 366 (62%); gate produces 212 / 366 (58%) and 323 / 366 (88%); TWAP ordering produces 72 / 366 (20%) on TPRR_F. TPRR_E in particular shows 51–88% of days differing across the four sweeps, the most trajectory-sensitive tier across every parameter, consistent with E-tier having the highest underlying volatility in the v0.1 panel (E-tier daily σ ≈ 0.40%/day vs F-tier 0.15%/day).

The combined two-layer story (base-date invariant for three of four parameters, trajectory sensitive for all four) is the central institutional-grade narrative for the parameter sensitivity section. Cross-reference: [base_date_convergence_with_trajectory_sensitivity.md](findings/base_date_convergence_with_trajectory_sensitivity.md).

## **3.4 Gate threshold as most consequential parameter**

The gate threshold is the single highest-leverage parameter in the methodology. Of the four parameters swept in Batch 10B, only the gate shifts TPRR_F base_date raw_value (within the swept range), AND it produces the highest intermediate-day sensitivity (88% of TPRR_E days differ between gate=5% and gate=30%). This combination (base-date sensitive at strict settings + highest trajectory leverage across the range) places the gate structurally upstream of every other parameter.

Per-cell behavior across the swept gate range:

| `quality_gate_pct` | TPRR_F base_date raw_value (USD/Mtok) | `all_pairs_suspended` audit-row count |
| :---- | ----: | ----: |
| 0.05 | 28.2315 | 64 |
| 0.10 | 28.94 | 30 |
| **0.15** (canonical) | **30.2405** | **32** |
| 0.20 | 30.2405 | 32 |
| 0.25 | 30.2405 | 18 |
| 0.30 | 30.2405 | 0 |

The gate exclusion cascade explains both the base-date sensitivity at strict settings and the level convergence above the canonical. At 5% gate, legitimate price-step movements in the synthetic panel are caught as outliers, suspending pairs that don't reinstate by base_date: TPRR_F base_date level 28.23 reflects a partially-suspended F-tier constituent set. At 10%, the cascade attenuates partly. At 15% and above, the gate catches only material outliers; the base-date constituent set is the same regardless of whether the gate is 15%, 20%, 25%, or 30%, so the base_date raw_value is identical across all four. The canonical 15% choice represents the loosest gate that does not degrade the published level: the methodologically conservative choice.

The mechanism is straightforward. The gate sits at the input boundary; every downstream parameter operates on the gate-filtered slot set. Three propagation paths run from gate to index level: (1) direct slot exclusion shifts the daily TWAP for affected constituents; (2) gate-firing accumulation triggers (contributor, constituent) pair suspension, which removes those pairs from the daily fix until reinstatement; (3) sustained suspension cascades reduce a tier's active constituent count, potentially triggering tier-level fix suspension under the minimum-3 threshold. Other parameters (suspension threshold, reinstatement threshold, TWAP ordering) operate on the gate-filtered set; only the gate decides which prices the methodology sees in the first place. Cross-reference: [gate_threshold_most_consequential_parameter.md](findings/gate_threshold_most_consequential_parameter.md).

The gate's structural primacy informs the governance schedule documented in [methodology spec §5.2](tprr_methodology.md): the Index Committee's quarterly parameter review weights gate-threshold proposals more heavily than other parameter proposals; the canonical 15% choice will be re-validated against real provider data when v1.3+ implementation reaches production scope.

## **3.5 λ non-monotonicity in realized volatility**

Phase 10 Batch 10C multi-seed sweeps surfaced a counter-intuitive empirical finding: TPRR_F annualized realized volatility is **non-monotonic in λ** across the swept Phase 7H design space. The intuitive narrative (higher λ produces tighter median-distance weighting which should also produce higher realized vol because outliers get weighted away) is wrong on the realized-vol side for the v0.1 panel.

Across 20 seeds × three Phase 7H configs:

| Config | λ | Tier B haircut | Mean vol | Std vol |
| :---- | ----: | ----: | ----: | ----: |
| Loose | 2 | 0.6 | **24.8%** | 4.6% |
| Default | 3 | 0.5 | **33.4%** | 6.7% |
| Tight | 5 | 0.4 | **32.0%** | 7.3% |

Vol-minimum sits at λ=2; the canonical λ=3 sits at the local maximum on this design space; vol decreases marginally moving from λ=3 to λ=5. The non-monotonicity is robust to the seed range: per-seed minimum vol sits at λ=2 for all 20 seeds; per-seed maximum vol is split between λ=3 and λ=5.

The mechanism is hypothesized, not verified through targeted experiment. Two competing effects plausibly drive the relationship between λ and realized vol. **Smoothing effect at the lower-λ side**: at λ=2, the median-distance weighting is gentle; constituents at ±20% of the median still receive 67% of full weight; the aggregation effectively averages across a broad constituent set, which damps any single-constituent move into the index trajectory. Lower λ → broader effective constituent set → smoother trajectory → lower realized vol. **Concentration effect at the higher-λ side**: at λ=5, weights drop sharply (±20% gets 36% weight; ±50% gets 8%); the effective constituent set shrinks toward the 1–3 constituents nearest the median. With fewer contributing constituents, idiosyncratic price moves of those near-median constituents pass through to the index without absorption. Higher λ → fewer effective constituents → less averaging → can re-elevate vol. The two effects cross over somewhere in the middle of the swept range; canonical λ=3 happens to sit at or near the local maximum.

The implication for λ calibration documentation is direct. The canonical λ=3 choice is defended on **manipulation-resistance and effective-constituent-breadth grounds**, not on volatility-minimization grounds. λ=2 would minimize realized vol but at the cost of weaker median-distance discrimination (more constituent breadth, less manipulation defense). λ=5 would tighten manipulation defense further but at the cost of effective constituent breadth (fewer constituents drive the index). The λ=3 canonical balances these competing pressures; the realized-vol non-monotonicity finding clarifies that the choice is not a vol-optimization choice. The Index Committee's quarterly review (per [methodology spec §5.2](tprr_methodology.md)) may revise λ where market evolution warrants, but the empirical non-monotonicity must be considered: naive intuition does not predict the relationship correctly. Cross-reference: [lambda_non_monotonicity_in_realized_vol.md](findings/lambda_non_monotonicity_in_realized_vol.md).

## **3.6 TWAP ordering empirical equivalence**

Phase 10 Batch 10B's TWAP-ordering sweep tested the canonical TWAP-then-weight ordering against the alternative weight-then-TWAP ordering across the clean panel and 6 scenarios on seed 42. The two orderings produce a **$0.0001/Mtok base_date delta on TPRR_F**, practically zero. Maximum intermediate-day delta on TPRR_F is $1.4445/Mtok (~5% of the typical $30/Mtok level), with 72 of 366 days (20%) showing any difference. Most days the orderings produce literally identical output.

The mechanism for the empirical equivalence is the v0.1 panel's gate-exclusion frequency. The two orderings differ in what gets weighted: TWAP-then-weight computes each contributor's daily TWAP first, then aggregates across contributors; weight-then-TWAP computes a slot-level weighted index across contributors first, then takes the TWAP of those weighted slot values. The two formulations are algebraically identical when weights are constant within the day and no slots are excluded. They diverge only when slot-level gate exclusions or change-event slot boundaries break the within-day uniformity. The 72/366 = 20% pattern matches the seed-42 panel's gate-exclusion frequency; days with no gated slots produce identical output, days with gated slots produce small but nonzero divergence.

A striking sub-finding from the TWAP-ordering sweep: under both orderings, scenario-induced perturbations produce **byte-identical TPRR_F TWAP-ordering deltas across all 7 panels** (clean + 6 scenarios). The F-tier's residual TWAP-ordering effect at seed-42 is invariant to which scenario was applied. This was the single-seed precursor to the methodology-level F-tier scenario absorption finding documented in §3.8: Batch 10B observed that the *difference between orderings* was scenario-invariant on the F-tier; Batch 10C generalized this to *byte-identical absolute output* across 20 seeds.

The framing has two complementary answers to "why TWAP-then-weight rather than weight-then-TWAP". First, **commodity benchmark precedent**: ICE Brent, Henry Hub, and ASCI all use TWAP-then-weight; aligning with established institutional precedent reduces operational complexity for downstream consumers. Second, **empirical equivalence on the v0.1 panel**: the alternative produces nearly identical output, so the choice imposes no informational cost relative to the alternative. The combination is a "no methodology debt" finding: the ordering choice is defensible from both first principles (precedent) and empirical evidence (sensitivity sweep). Cross-reference: [twap_ordering_empirical_equivalence.md](findings/twap_ordering_empirical_equivalence.md).

## **3.7 Cross-config seed signature stability**

Phase 10 Batch 10C ran 20 seeds × three Phase 7H configurations (loose / default / tight) on the clean panel, producing 60 seed×config combinations of the methodology's response. The cross-config finding is that the methodology produces a stable cross-seed *response structure*: not just stable output at any single config, but a stable response shape across configs.

| Config | Mean | Std | Maximum-seed (rank 1) | Lower-tail seeds |
| :---- | ----: | ----: | :---- | :---- |
| Loose (λ=2, B=0.6) | 0.9002 | 0.0405 | seed 47 (0.9313) | seed 51 (min, 0.7840); seed 57 (second-min, 0.8181) |
| Default (λ=3, B=0.5) | 0.9192 | 0.0348 | seed 47 (0.9483) | seed 57 (min, 0.8345); seed 51 (second-min, 0.8466) |
| Tight (λ=5, B=0.4) | 0.9387 | 0.0315 | seed 47 (0.9647) | seed 57 (min, 0.8516); seed 43 (second-min, 0.8702) |

Distribution shape preserved across configs. Seed 47 produces the maximum at all three configs; seeds 51 and 57 occupy the lower tail at all three configs (with rank shifts within the tail: seed 51 minimum at loose, seed 57 minimum at default and tight; the other always second-minimum). Seed 43 emerges as second-minimum at tight only, but still in the lower band across all configs. Mean shifts upward modestly as the config tightens (Tier B haircut tightens from 0.6 to 0.5 to 0.4, reducing Tier B's contribution and raising Tier A's relative share); standard deviation tightens slightly (0.041 → 0.035 → 0.032).

Constituent-activation pattern is identical across all 60 cells: TPRR_F = 6, TPRR_S = 4, TPRR_E ∈ {5, 6}. The same panel realizations that produce the {5, 6} TPRR_E split do so identically across configs. Audit row counts are byte-identical to four significant figures across the three configs (mean 22,134 / std 117 across all 60 combinations). Median suspension intervals (155) and median reinstatement events (153) are identical across the three configs. The Phase 7H Batch D suspension policy is decoupled from λ and Tier B haircut.

The mechanism is that three layers of the methodology produce stable cross-seed signatures regardless of Phase 7H config: (1) the slot-level gate + suspension cascade operates on the panel's volatility structure independent of λ and Tier B haircut; (2) constituent activation is governed by panel constituent count and tier assignments, not by λ or haircut; (3) within-tier-share normalization depends on the contributor-volume distribution and the post-gate-exclusion constituent set, both of which are config-invariant. Configs *do* change Tier B haircut's direct contribution to the blended weight (shifting Tier A's published weight share) and λ's median-distance weight curve (shifting intermediate-day trajectory variation, per §3.5). Configs *do not* change which seeds produce extreme outcomes, the constituent activation pattern, or the suspension/reinstatement frequency.

Two consequences for the development narrative. First, **seed-42 is unremarkable, not special**. Seed 47 is the cross-config maximum; seed 42 sits 0.7σ above the multi-seed mean at default config and mid-distribution at loose and tight. The Phase 7H Batch D seed-42 cliff-edge resolution finding (`tier_a_weight_share` = 0.9261, per §2.6) is empirically representative, not seed-cherry-picked. Second, **the Phase 7H configs are a robustness band, not three discrete options**. The v1.3 canonical methodology lives at default; loose and tight document the empirical envelope within which the methodology behaves stably. Cross-reference: [cross_config_seed_signature_stability.md](findings/cross_config_seed_signature_stability.md).

## **3.8 F-tier scenario absorption: the methodology-level finding**

The headline manipulation-resistance result of the Phase 10 + Phase 11A validation arc combines two cross-products tested on independent parameter axes:

- **Phase 10 Batch 10C** (downstream / Phase 7H continuous-blending design space): 3 configs × 20 seeds × 6 scenarios × 366 days = **131,760 F-tier daily datapoints, byte-identical to the corresponding clean-panel value**.
- **Phase 11 Batch 11A** (upstream / gate threshold): 6 gate values × 20 seeds × 6 scenarios × 366 days = **263,520 F-tier daily datapoints, byte-identical to clean**.
- **Cumulative across both axes**: **395,280 F-tier daily datapoints**, every one byte-identical to clean (with the canonical config × gate=15% cell tested in both experiments providing cross-experiment reproducibility verification of the absorption result).

The maximum F-tier trajectory delta observed across either cross-product is ≤ 1.4×10⁻¹⁴, below float-arithmetic noise floor, well below any methodologically meaningful tolerance. The result was generated by [`scripts/multi_seed_sweep.py`](../scripts/multi_seed_sweep.py) for Batch 10C and [`scripts/gate_x_scenarios_x_seeds_sweep.py`](../scripts/gate_x_scenarios_x_seeds_sweep.py) for Batch 11A.

The absorption is structural across two parameter axes:

- **Phase 7H continuous-blending design space (downstream)**: λ ∈ {2, 3, 5}, Tier B haircut ∈ {0.4, 0.5, 0.6}, blending coefficients held canonical. Verified within the Batch 10C swept envelope.
- **Gate-threshold range (upstream)**: `quality_gate_pct ∈ {0.05, 0.10, 0.15, 0.20, 0.25, 0.30}`: the full Batch 10B-swept range including the strict gates (5%, 10%) where Batch 10B documented material clean-panel TPRR_F base_date level shifts (§3.4). Verified within the Batch 11A swept envelope. The cross-gate result is striking because the strict-gate clean-panel base_date level moves substantially (28.23 vs 30.24 at canonical), but the **scenario delta** stays byte-identical at zero across the full gate range.

Recommended framing for institutional reviewers: the dual-weighted formula combined with the slot-level gate, three-tier hierarchy, and minimum-3-constituents requirement absorbs the v0.1 scenario suite completely on the F-tier index, across every methodology parameter combination tested in Phase 10 + Phase 11A at the values swept. The "at the values swept" qualifier is load-bearing: the absorption claim is empirical at the swept parameter values, not a claim that holds at arbitrary values outside the tested ranges, and not a claim that holds against the parameter axes flagged as scope gaps in §3.11.

The mechanism is **upstream filtering**. The methodology has two parameter regimes operating at different points in the pipeline. **Upstream (filtering layer)**: slot-level gate (15% / 5-day trailing average), minimum-3-contributors-per-constituent threshold, suspension/reinstatement policy. Operates on raw slot-level prices before aggregation. **Downstream (aggregation layer)**: λ, Tier B haircut, blending coefficients, within-tier-share normalization. Operates on the already-filtered signals. The Phase 7H continuous-blending parameters swept in Batch 10C (λ, Tier B haircut, blending coefficients) are all downstream. The gate-cascade + minimum-3 + suspension policy filter scenario perturbations *before* they reach the blending step. Downstream parameters redistribute weight on surviving signals; they cannot reintroduce filtered-out signals. This explains why scenario absorption is invariant to the Phase 7H configs swept: the absorption mechanism operates upstream of the parameters being varied.

The F-tier's structural advantage rests on three properties combining at the upstream layer: (1) **constituent redundancy**: TPRR_F has 6 constituents (vs 4 on TPRR_S); even if a scenario perturbs one constituent's prices, the 5 remaining anchor the F-tier index level; (2) **contributor redundancy per constituent**: each F-tier constituent has ≥3 contributors with valid daily TWAPs at default config; a scenario that perturbs one contributor's slot-level prices gets gated out at the slot level before reaching the per-constituent daily TWAP; (3) **gate-cascade absorption pre-aggregation**: the slot-level gate runs before aggregation; scenarios inject perturbations at specific slots; the gate identifies them as outliers against the 5-day trailing average and excludes them from the daily TWAP; suspended pairs drop out of the daily fix entirely. By the time the dual-weighted formula sees the F-tier constituent prices, scenario perturbations have been filtered three times. Cross-references: [f_tier_scenario_absorption_methodology_level.md](findings/f_tier_scenario_absorption_methodology_level.md), [gate_x_scenarios_absorption.md](findings/gate_x_scenarios_absorption.md).

Honest calibration acknowledgement: the byte-identical result is consistent with the methodology being well-tuned to the specific failure modes the v0.1 scenario suite was designed to test. The six scenarios (`fat_finger_high`, `intraday_spike`, `correlated_blackout`, `stale_quote`, `shock_price_cut`, `sustained_manipulation`) were authored alongside the methodology, with the gate-and-suspension mechanisms in mind; they target perturbation patterns the gate is designed to catch. The finding therefore demonstrates that the methodology absorbs the v0.1 scenarios it was designed to absorb, invariantly across the tested parameter combinations. It does not yet demonstrate absorption of compromised-contributor scenarios with sub-gate price drift, simultaneous multi-tier coordinated attacks, slowly evolving manipulation cumulating below the gate threshold, volume-share manipulation on the within-tier-share normalization, or adversarial scenarios authored independently by a red team. These are v1.4+ scope items per §4.1.

![Figure 3.2: TPRR-F clean panel vs scenario panel under the correlated_blackout v0.1 scenario, canonical config seed-42 across the 366-day backtest. Clean and scenario trajectories are indistinguishable at chart scale. Per-scenario max |Δ| values across all 20 seeds (annotation block, upper right of panel) confirm absorption: three scenarios (fat_finger_high, intraday_spike, shock_price_cut) produce exact zero delta; three scenarios (correlated_blackout, stale_quote, sustained_manipulation) produce maximum |Δ| of 2.84×10⁻¹⁴, within float-arithmetic noise. The methodology's three-tier attestation hierarchy combined with the gated quality filter completely absorbs all six v0.1 scenarios on the F-tier.](charts/development/f_tier_scenario_absorption.svg)

*Figure 3.2: TPRR-F clean panel vs scenario panel under the correlated_blackout v0.1 scenario, canonical config seed-42 across the 366-day backtest. Clean and scenario trajectories are indistinguishable at chart scale. Per-scenario max |Δ| values across all 20 seeds (annotation block, upper right of panel) confirm absorption: three scenarios (fat_finger_high, intraday_spike, shock_price_cut) produce exact zero delta; three scenarios (correlated_blackout, stale_quote, sustained_manipulation) produce maximum |Δ| of 2.84×10⁻¹⁴, within float-arithmetic noise. The methodology's three-tier attestation hierarchy combined with the gated quality filter completely absorbs all six v0.1 scenarios on the F-tier.*

## **3.9 Per-tier mechanism by redundancy reservoir size**

The F-tier scenario absorption is not the only per-tier finding from Batches 10C and 11A. The same cross-products produced trajectory variation on TPRR_S and TPRR_E under specific scenarios, with per-tier response signatures that correlate with **redundancy reservoir size**: constituent count multiplied by contributor depth per constituent. Three regimes emerge:

| Tier | Constituent count | Regime | Gate-dependence shape |
| :---- | ----: | :---- | :---- |
| TPRR_F | 6 | Absorption | None (zero scenario delta across full gate range) |
| TPRR_E | 5 to 6 | Filter-and-absorb | Monotonic: scenario response damps as gate loosens |
| TPRR_S | 4 | Filter-and-absorb | Non-monotonic: small-constituent-count interactions with gate-induced suspension produce non-monotonic response |

**F-tier (6 constituents × ≥3 contributors per constituent)** sits in the **absorption regime**. Redundancy reservoir is large enough that the gate-cascade + suspension mechanism filters scenario perturbations completely; the dual-weighted formula's averaging across the broad surviving constituent set produces zero scenario delta at every gate value tested. Same scenarios, same gates, same zero result.

**E-tier (5–6 constituents)** sits in the **filter-and-absorb regime with monotonic gate-dependence**. Smaller redundancy reservoir; scenarios produce trajectory variation. Response magnitude monotonically damps as gate loosens: looser gates filter less raw slot variation, but the wider surviving constituent set absorbs more through averaging. The two effects compound favorably as gate increases. Three scenarios (`correlated_blackout`, `shock_price_cut`, `stale_quote`) produce variation; three (`fat_finger_high`, `intraday_spike`, `sustained_manipulation`) do not. The scenario set producing variation is gate-invariant; only the magnitude varies with gate.

**S-tier (4 constituents)** sits in the **filter-and-absorb regime with non-monotonic gate-dependence**. Smallest redundancy reservoir. Scenarios produce trajectory variation that swings non-monotonically with gate: strict gates suspend more constituents (less averaging cushion → larger response); moderate gates produce unstable small-constituent-count interactions. Four scenarios (`correlated_blackout`, `sustained_manipulation`, `intraday_spike`, `fat_finger_high`) produce variation; two do not. The non-monotonic swing on `correlated_blackout` (max delta 0.016 → 0.386 → 0.0074 across gates 5/10/15) and `fat_finger_high` (20 → 8 → 6 seeds with variation across the same gates) demonstrates that S-tier's small constituent count makes its response landscape sensitive to gate-induced suspension changes.

The per-tier mechanism is not noise; it is structurally embedded in the relationship between constituent count and the filter-and-absorb dynamics. F-tier's redundancy dominance puts it in the absorption regime; S/E-tier's smaller redundancy puts them in the filter-and-absorb regime with magnitude depending on gate-redundancy interaction. The implication is direct: **per-tier manipulation-resistance certification levels** should be specified as a v1.3+ documentation refinement, mapping the regime distinction to constituent count per index tier. F-tier (6 constituents) certifies as absorption-regime; S-tier (4) and E-tier (5–6) certify as filter-and-absorb-regime with documented gate-dependence shape. As Tier C coverage expands in v0.2+ and additional constituents enter each index tier, the regime classification will adjust accordingly per the smooth-activation property documented in [methodology spec §3.3.2.4](tprr_methodology.md).

![Figure 3.3: Per-tier worst-day |scenario − clean| index difference across the gate threshold range, for correlated_blackout signature scenario (canonical config except gate, mean across 20 seeds). TPRR-F shows complete absorption (zero delta) across the gate range. TPRR-S exhibits a filter-and-absorb non-monotonic response: delta values in the $0.001-$0.02/Mtok range across gates, with no clear monotonic relationship between gate threshold and scenario delta. TPRR-E exhibits a filter-and-absorb monotonic response: delta declines from ~$0.03/Mtok at gate=5% to ~$0.0006/Mtok at gate=30%. The three regimes (absorption / filter-and-absorb non-monotonic / filter-and-absorb monotonic) are visually distinct across the F/S/E semantic palette. TPRR-F clean baseline = $30.11/Mtok; scenario deltas shown are 14+ orders of magnitude smaller for F-tier.](charts/development/per_tier_asymmetry_across_gate_range.svg)

*Figure 3.3: Per-tier worst-day |scenario − clean| index difference across the gate threshold range, for correlated_blackout signature scenario (canonical config except gate, mean across 20 seeds). TPRR-F shows complete absorption (zero delta) across the gate range. TPRR-S exhibits a filter-and-absorb non-monotonic response: delta values in the $0.001-$0.02/Mtok range across gates, with no clear monotonic relationship between gate threshold and scenario delta. TPRR-E exhibits a filter-and-absorb monotonic response: delta declines from ~$0.03/Mtok at gate=5% to ~$0.0006/Mtok at gate=30%. The three regimes (absorption / filter-and-absorb non-monotonic / filter-and-absorb monotonic) are visually distinct across the F/S/E semantic palette. TPRR-F clean baseline = $30.11/Mtok; scenario deltas shown are 14+ orders of magnitude smaller for F-tier.*

## **3.10 Cross-gate scenario sub-finding**

Phase 11 Batch 11A's gate × scenarios × seeds cross-product produced an additional finding worth surfacing separately: **E-tier scenario response magnitude monotonically damps as gate loosens, across the full swept gate range and the three scenarios that produce E-tier variation**.

For the signature E-tier scenario (`correlated_blackout`):

| Gate | E-tier max abs delta ($/Mtok) |
| :---- | ----: |
| 5% | 0.245 |
| 10% | 0.241 |
| 15% | 0.122 |
| 20% | 0.122 |
| 25% | 0.022 |
| 30% | 0.0023 |

The decline is two orders of magnitude, from $0.245/Mtok at the strictest gate to $0.0023/Mtok at the loosest. The same monotonic decline holds for `shock_price_cut` and `stale_quote`. The mechanism aligns with the per-tier interpretation in §3.9: looser gates filter less raw slot variation (which would push the response *up*), but the wider surviving constituent set absorbs more through averaging (which pushes the response *down*); the latter dominates within the swept range, producing the monotonic decline.

S-tier shows the contrasting non-monotonic shape across the same gate range. For `correlated_blackout` on S-tier: max delta swings 0.016 (5%) → 0.386 (10%) → 0.0074 (15%): a 24× variation that does not align with any monotonic gate-dependence story. The mechanism here is small-constituent-count instability: strict gates suspend more S-tier constituents (4 to begin with; suspensions reduce active count materially); moderate gates produce unstable interactions where suspension boundaries cross the minimum-3 threshold non-monotonically across seeds.

The cross-gate sub-finding strengthens the F-tier absorption result documented in §3.8 by establishing that the absorption mechanism does not depend on gate value: F-tier sits at zero scenario delta at every gate from 5% to 30%, even though E-tier and S-tier show substantial gate-dependence within the same cross-product. The result is the strongest empirical evidence available within the v0.1 scope that F-tier's redundancy reservoir is structurally robust to upstream gate-threshold variation.

![Figure 3.4: Gate × scenarios cross-product per-tier scenario response, median across the 6 v0.1 scenarios at each gate value (canonical config except gate). Y-axis shows median worst-day index difference between scenario and clean panels across the 6 scenarios. TPRR-F clean baseline = $30.11/Mtok; scenario deltas shown for TPRR-F are 14+ orders of magnitude smaller, indicating complete absorption across the gate × scenarios cross-product (720 cells per tier: 6 gates × 6 scenarios × 20 seeds). TPRR-S and TPRR-E exhibit filter-and-absorb behavior at sub-$0.01/Mtok magnitudes across the cross-product.](charts/development/gate_x_scenarios_per_tier_overlay.svg)

*Figure 3.4: Gate × scenarios cross-product per-tier scenario response, median across the 6 v0.1 scenarios at each gate value (canonical config except gate). Y-axis shows median worst-day index difference between scenario and clean panels across the 6 scenarios. TPRR-F clean baseline = $30.11/Mtok; scenario deltas shown for TPRR-F are 14+ orders of magnitude smaller, indicating complete absorption across the gate × scenarios cross-product (720 cells per tier: 6 gates × 6 scenarios × 20 seeds). TPRR-S and TPRR-E exhibit filter-and-absorb behavior at sub-$0.01/Mtok magnitudes across the cross-product.*

## **3.11 Acknowledged scope gaps**

§3.1 introduced the validation scope inventory as the upfront framing device. This section consolidates the specific gaps that bound the empirical claims throughout §3, extending §3.1's high-level scope statement into a detailed enumeration that future v1.3+ validation work should address.

**Five upstream-parameter axes were not swept against scenarios** in Phase 10 or Phase 11A. These are not weaknesses per se (the validation work prioritized the parameter most likely to matter, the gate threshold per §3.4, and the Phase 7H continuous-blending design space) but they remain v1.4+ items:

1. **Minimum-3 threshold × scenarios**: the redundancy mechanism itself. Testing might be tautological by construction (lowering the minimum mechanically breaks the redundancy reservoir on which the F-tier absorption regime depends), but worth verifying empirically whether the absorption holds at minimum-2 or breaks.
2. **Suspension/reinstatement policy × scenarios**: Batch 10B swept policy parameters on the clean panel only, not against scenarios.
3. **TWAP ordering × multi-seed × scenarios**: Batch 10B did seed-42 only; multi-seed extension not run.
4. **Tier-eligibility threshold × scenarios**: the constituent → tier minimum-3 threshold added in Phase 10A. v0.1 Tier C dormant at every config tested; activation behavior under scenario perturbation only verified at default threshold.
5. **Adversarial scenarios beyond v0.1 suite**: the six v0.1 scenarios were authored alongside the methodology; adversarial scenarios authored independently by a red team have not been tested.

**v0.1 scenario suite calibration** (per §3.8 honest acknowledgement): the byte-identical F-tier absorption result is consistent with the methodology being well-tuned to the v0.1 scenarios it was designed to absorb. v1.4+ should expand the scenario suite with attack vectors flagged in [gate_x_scenarios_absorption.md](findings/gate_x_scenarios_absorption.md) §"Honest calibration acknowledgement": compromised contributor (extended-window manipulation, sub-gate price drift); simultaneous multi-tier coordinated attacks; slowly evolving manipulation (cumulative drift below 15% gate); volume-share manipulation (attack on within-tier-share rather than price); red-team-authored adversarial scenarios.

**Synthetic Tier A panel constraints**: 10 contributors × 16 constituents calibrated to plausible 2025 enterprise-segment prices, deterministic at seed. Real production deployment requires real contributor billing data ingested via Tier A panel infrastructure. Cross-seed dispersion may tighten on real provider price history (Brent's vol-of-vol over 1-year window is typically 2–3% vs synthetic panel's 6.7% std dev at default config).

**Tier B revenue inputs from `config/tier_b_revenue.yaml`**: analyst-triangulation point estimates per quarter. Real production deployment requires audited disclosed revenue with subscription-tier carve-outs. The 0.5 haircut reflects the bias chain documented in DL 2026-04-30 — Phase 7H Batch C: Tier B confidence haircut 0.9 → 0.5 + tier ordering A > C > B; v1.4+ should refine the calibration against audited revenue and provider-disclosed token volumes when available.

**Tier C coverage in v0.1**: 1 of 16 constituents (deepseek-v3-2 alone). Tier C is dormant for all three index tiers under the tier-eligibility threshold (§2.7). The methodology's smooth-activation property (per [methodology spec §3.3.2.4](tprr_methodology.md)) ensures Tier C activates organically as v0.2+ coverage expands; the scope gap is empirical (real Tier C activation behavior is uncharacterized) rather than methodological (the activation mechanism is specified and tested).

These gaps are scope clarification, not weakness. Each is documented explicitly so that v1.4+ validation work can address them in priority order; the §4.1 roadmap operationalizes this enumeration into a v1.4+ work plan.

# **4. Future Roadmap**

The v1.3 methodology is the canonical specification for production launch, but v1.3 is not the endpoint. The validation work documented in §3 surfaced gaps, both empirical (parameter axes not swept against scenarios; synthetic-panel constraints) and infrastructural (real-data validation pathway; production publication channels), that constitute our v1.4+ work plan. The roadmap below operationalizes our strategic position from §1: we built TPRR to be the institutional reference rate for AI inference token pricing, and the path from v0.1 reference codebase to production publication runs through real-data onboarding, distribution infrastructure, regulatory disclosure, and progressive expansion of methodological scope. Each item below contributes to the strategic thesis articulated in §1; none is decorative.

## **4.1 v1.4+ methodology candidates from validation gaps**

Five methodology candidates were surfaced through the Phase 10 + Phase 11A validation work and queue for v1.4+ specification work:

**1. Tier B value calibration with audited revenue and provider-disclosed token volumes.** The v1.3 Tier B haircut (0.5) reflects the bias chain documented in §2.5: provider revenue × API_share × OpenRouter within-provider split ÷ reference price. Each step uses analyst-triangulated point estimates. v1.4+ should refine the calibration when audited revenue and provider-disclosed token volumes become available, replacing the analyst-triangulation point estimates and API-share assumptions in the derivation chain. The expected refinement reduces Tier B's bias chain length and tightens the calibration of the haircut value itself; it may justify a haircut adjustment or a per-provider haircut differential.

**2. Tier C coverage expansion via OpenRouter full-models endpoint.** v0.1 ingested only the OpenRouter top-9 rankings snapshot, covering 1 of 16 constituents (deepseek-v3-2). v1.4+ should ingest the OpenRouter full-models endpoint to extend coverage past the top-9 cutoff. Complementary third-party data sources (industry surveys, developer-platform analytics, transaction aggregators beyond OpenRouter) should be evaluated as supplementary Tier C inputs. Tier C activates automatically per the smooth-activation property when coverage exceeds 3 constituents per index tier (per §2.7); no methodology version increment is required.

**3. Adversarial scenario suite for manipulation-resistance testing.** The v0.1 scenario suite (6 scenarios) was authored alongside the methodology, sharing its gate-and-suspension assumptions. v1.4+ should expand with attack vectors authored independently by a red team: compromised contributor (extended-window manipulation, sub-gate price drift), simultaneous multi-tier coordinated attacks, slowly evolving manipulation (cumulative drift below the gate), volume-share manipulation, and externally-validated red-team-authored attacks. The expanded scenario suite is the principal test of v1.3's manipulation-resistance properties beyond the well-tuned v0.1 configuration.

**4. Real-data validation pathway.** v0.1 validation runs against synthetic Tier A panels with calibrated baseline prices, not against real contributor billing data. The v0.2 → v0.3 → v1.0 trajectory (per §4.2) onboards real Tier A contributors with audited billing data feeds and re-runs the Phase 10 + Phase 11A validation cross-products against real provider price dynamics. This is the most consequential v1.4+ scope item; the v1.3 specification is empirically defended against the synthetic panel only.

**5. Upstream-parameter × scenario cross-products not yet run.** Per §3.11, four parameter axes were not swept against scenarios in Phase 10 + Phase 11A: minimum-3 threshold × scenarios; suspension/reinstatement policy × scenarios; TWAP ordering × multi-seed × scenarios; tier-eligibility threshold × scenarios. v1.4+ should run these cross-products to complete the upstream-parameter validation envelope.

## **4.2 Real-data validation pathway**

The transition from v0.1 reference codebase to v1.0 production publication runs through three intermediate scope steps:

- **v0.2+**: Tier C coverage expansion via the OpenRouter full-models endpoint and complementary third-party data sources. Tier C activates automatically per the smooth-activation property as coverage exceeds 3 constituents per index tier. The methodology behaves identically pre- and post-coverage-expansion at the published level; only the empirical contribution of Tier C to the blended weights changes.
- **v0.3+**: Real Tier A contributor panel onboarding. One or more anchor contributors with audited billing data feeds replace the synthetic panel; the dual-weighted formula consumes real contributor-attested volumes. The Phase 10 + Phase 11A validation cross-products are re-run against the real panel; cross-config seed signature stability and F-tier scenario absorption claims are re-verified on real provider price dynamics.
- **v1.0**: Production publication. Full real-data three-tier hierarchy operational; daily fix published per the schedule in [methodology spec §4.3](tprr_methodology.md); intraday spot publication, monthly average publication, and FX-hedged variants come online. Backfill to a meaningfully-anchored historical base date (likely GPT-4 API launch, March 2023) using Wayback Machine API archives, analyst reports, and customer-leaked rate cards to reconstruct the Tier A and Tier B panels prior to direct contributor onboarding.

The pathway is sequenced rather than parallel because each step depends on the prior. v0.2 Tier C expansion validates the smooth-activation property under organic coverage growth; v0.3 real Tier A onboarding validates the methodology's behavior against real provider price dynamics; v1.0 production publication ties the validated methodology to the production publication infrastructure and the IOSCO disclosure framework documented in §4.4.

## **4.3 Distribution architecture**

We plan to distribute TPRR through established financial data infrastructure to maximize adoption by institutional users who consume benchmark data through existing terminal and data feed arrangements. Three distribution channels are planned:

- **Major financial data terminals**: Bloomberg, Refinitiv, S&P Capital IQ, providing real-time and historical TPRR series via standard ticker integration. Institutional treasurers, analysts, and traders consume benchmark data through these terminals; TPRR's institutional credibility is conditional on availability through them.
- **Index data infrastructure providers**: FTSE Russell, S&P Dow Jones Indices, MSCI, providing co-branded index licensing and distribution that enables incorporation of TPRR into investment mandates and risk frameworks. The index-platform partnership is the channel through which institutional asset managers get TPRR onto their performance-attribution and risk-management dashboards.
- **Noble Argon Insights API**: direct programmatic access for enterprise users, available as part of our planned SaaS offering. Provides real-time spot data, historical series, and portfolio-level analytics. The API is the channel through which enterprises and fintech developers integrate TPRR into proprietary workflows.

The licensing model is tiered to match consumer use case:

| Tier | User type | Terms |
| :---- | :---- | :---- |
| Benchmark Reference | Enterprises using TPRR for internal budgeting and reporting | Annual subscription; scaled by revenue/AUM |
| Derivative Settlement | Financial institutions using TPRR as settlement reference in OTC instruments | Transaction fee per notional settled; or annual enterprise license |
| Platform | SaaS users of Noble Argon Insights dashboard and API | Monthly SaaS subscription; tiered by seats and API calls |
| Redistribution | Data vendors, terminal providers, index platforms | Custom licensing; subject to redistribution restrictions |

Distribution partner relationships and licensing agreements are in development; the architecture above represents our planned distribution strategy. The v0.1 reference codebase outputs TPRR computations to local audit format (parquet and SQLite); production distribution channels are scoped for v1.0+ deployment alongside the production publication infrastructure documented in §4.2.

## **4.4 IOSCO disclosure trajectory**

The v1.3 methodology specification is currently internal; public disclosure under IOSCO Principles for Financial Benchmarks is scheduled for production launch (post-v1.0 reference codebase deployment), concurrent with our first live OTC transaction or at the IOSCO formal-registration milestone, whichever is earlier. The pre-launch internal phase is consistent with benchmark-development convention: methodologies are validated internally before public disclosure, both to allow refinement against operational evidence and to avoid premature commitment to design choices that may evolve through validation.

Public methodology disclosure under IOSCO Principles requires that the published methodology document satisfy the IOSCO governance, audit, methodology transparency, and conflict-of-interest disclosure requirements. The v1.3 methodology specification is designed to satisfy these requirements; the §5.3 regulatory positioning section of the methodology spec frames our intended compliance posture. We will engage benchmark regulatory counsel ahead of formal registration milestones; the disclosure timing is determined by the production-launch schedule per [methodology spec §5.3](tprr_methodology.md).

Two regulatory frameworks reference IOSCO Principles by incorporation: the EU Benchmark Regulation (BMR) and the UK Financial Conduct Authority's Benchmark Regulation (UK BMR). Our regulatory positioning is designed to satisfy both, with first formal registration likely in the UK given the FCA's established benchmark-administrator regime and the timing of UK BMR's transitional provisions. EU BMR registration follows on a parallel track once TPRR's institutional adoption justifies the additional regulatory overhead.

## **4.5 Existing roadmap items preserved from v1.2**

Four roadmap items predate the Phase 7H + Phase 10A validation arc; they were carried forward from the v1.2 specification and remain in scope for v1.4 and beyond:

- **Workload-specific TPRR-B variants**: publishing separate blended series for distinct workload types (RAG, agentic, code generation) based on contributor data as coverage matures. The v1.3 TPRR-B blended ratio (75:25 output:input, per [methodology spec §3.3.4](tprr_methodology.md)) reflects the observed average across our reference contributor dataset; workload-specific variants would refine this against per-workload consumption ratios as the Tier A panel grows.
- **Multimodal token pricing**: extending TPRR to cover vision, audio, and video token pricing as multimodal inference becomes a material enterprise cost. The methodology's three-tier hierarchy and dual-weighted formula generalize to multimodal pricing; the work item is methodology-extension to incorporate per-modality price observations and per-modality scenario suites.
- **On-premise and private cloud inference**: methodology extension covering self-hosted model inference costs, enabling enterprises to benchmark API vs. self-hosted total cost of ownership. v2.0 target. The methodology extension here is more substantial: self-hosted inference cost is not a published per-token rate but a derived metric incorporating hardware amortization, energy, and operational overhead; the methodology must adapt to this unit-economics shift.
- **TPRR Futures**: working with regulated exchanges to develop a listed TPRR futures contract, contingent on OTC market liquidity development. Medium-term milestone. Listed futures presuppose that the OTC inference-swap market has reached sufficient liquidity to justify exchange-listed standardization; the timing depends on OTC market formation per §1.5.

These items extend our product surface beyond v1.3; they do not modify the v1.3 methodology itself.

## **4.6 Roadmap as operational continuation of strategic thesis**

The v1.4+ roadmap is the operational continuation of our strategic thesis from §1. We built TPRR to be the institutional reference rate for AI inference token pricing; we have validated the methodology within the v0.1 scope; production launch and the supporting derivative market formation depend on completing the validation work against real provider data, building the distribution infrastructure that institutional consumers require, satisfying the IOSCO disclosure framework that regulatory counterparties require, and progressively expanding the scenario suite and scope coverage to defend the methodology against adversarial pressure. Each item in §4.1 through §4.5 advances one of these objectives. The v1.3 specification is the foundation; the roadmap is the pathway from foundation to the first-mover institutional reference rate that §1 describes.

# **5. References and Cross-Index**

## **5.1 Companion methodology specification**

[`docs/tprr_methodology.md`](tprr_methodology.md): canonical TPRR Methodology Specification v1.3. States the technical specification of the TPRR indices: index universe, weighting methodology, calculation procedure, governance framework, publication schedule. Where this development document explains why TPRR took its v1.3 form, the methodology spec states what TPRR is.

## **5.2 Phase 10 synthesis**

[`phase_10_synthesis.md`](findings/phase_10_synthesis.md): Phase 10 internal scaffolding document aggregating 13 sweeps and 7 standalone Phase 10 finding docs into a single internal synthesis. The primary scaffolding source for §2 and §3 of this development document; tagged with [PUBLICATION-GRADE], [AUDIT-TRAIL], and [METHODOLOGY-DOC] markers indicating which content lifts forward into Phase 11 publication prose vs which stays as supporting documentation.

## **5.3 Standalone validation finding docs**

Eight standalone validation finding docs in [`docs/findings/`](findings/), each documenting a specific empirical result from the Phase 10 + Phase 11A validation work:

- [`base_date_convergence_with_trajectory_sensitivity.md`](findings/base_date_convergence_with_trajectory_sensitivity.md): three-of-four downstream parameter base-date invariance, plus the two-layer narrative this document's §3.2 framing device builds on.
- [`gate_threshold_most_consequential_parameter.md`](findings/gate_threshold_most_consequential_parameter.md): gate as highest-leverage parameter; canonical 15% sits on convergence edge.
- [`lambda_non_monotonicity_in_realized_vol.md`](findings/lambda_non_monotonicity_in_realized_vol.md): counter-intuitive λ-vol relationship; canonical λ=3 chosen on manipulation-resistance grounds.
- [`twap_ordering_empirical_equivalence.md`](findings/twap_ordering_empirical_equivalence.md): TWAP-then-weight vs weight-then-TWAP empirical near-equivalence ($0.0001/Mtok base-date delta).
- [`cross_config_seed_signature_stability.md`](findings/cross_config_seed_signature_stability.md): methodology produces stable cross-seed response structure across Phase 7H configs.
- [`tier_eligibility_threshold_mechanism.md`](findings/tier_eligibility_threshold_mechanism.md): Phase 10A ninth specification gap closure; smooth-activation property.
- [`f_tier_scenario_absorption_methodology_level.md`](findings/f_tier_scenario_absorption_methodology_level.md): headline F-tier byte-identical absorption across Phase 7H continuous-blending design space + gate threshold range; cumulative 395,280 datapoints.
- [`gate_x_scenarios_absorption.md`](findings/gate_x_scenarios_absorption.md): Phase 11 Batch 11A cross-gate strengthening; per-tier mechanism by redundancy reservoir size.

## **5.4 Key decision log entries**

[`decision_log.md`](decision_log.md) entries from the Phase 7H + Phase 10 + Phase 11 arc, with line numbers for direct navigation:

| DL Date | Phase Batch | Topic | DL Line |
| :---- | :---- | :---- | ----: |
| 2026-04-30 | Phase 7 Batch C empirical | Cross-tier magnitude cascade manifests within single-seed backtest | 775 |
| 2026-04-30 | Suspension reinstatement criteria | v1.3 specification gap, Phase 7G implementation queued | 894 |
| 2026-04-30 | Phase 9 visual diagnostic | Cliff-edge weight share dynamics + asymmetric E-tier exclusion paths | 926 |
| 2026-04-30 | Phase 7H methodology design | Continuous blending, within-tier normalization, Tier B confidence recalibration, suspension reinstatement | 973 |
| 2026-04-30 | Phase 7H Batch A | Within-tier-share normalization (refactor) | 1038 |
| 2026-04-30 | Phase 7H Batch B audit trail design | Long-format per-tier breakdown | 1051 |
| 2026-04-30 | Phase 7H Batch C | Tier B confidence haircut 0.9 → 0.5 + tier ordering A > C > B | 1074 |
| 2026-04-30 | Phase 7H Batch D | Suspension reinstatement (3-day exclude / 10-day reinstate) | 1114 |
| 2026-04-30 | Phase 9 close-out | Dashboard renders Phase 7H methodology refinements and scenario evidence in 18-panel grid | 1140 |
| 2026-05-01 | Three-tier hierarchy bias profiles | Phase 11 framing | 1201 |
| 2026-05-01 | Phase 10 Batch 10A | Tier C enrich-call bug fix + tier-eligibility threshold for continuous blending | 1258 |
| 2026-05-01 | Phase 10 Batch 10B | Pipeline-rerun sweeps (suspension threshold, reinstatement threshold, gate threshold, TWAP ordering) | 1335 |
| 2026-05-01 | Phase 10 Batch 10C (partial) | Multi-seed runner + default config × 20 seeds × clean panel | 1414 |
| 2026-05-05 | Phase 10 Batch 10C (final) | Loose + tight × 20 seeds × 6 scenarios cross-product — methodology-level F-tier absorption confirmed | 1594 |
| 2026-05-05 | Phase 10 close-out | Validation rigor across Phase 7H design space, manipulation-resistance methodology-level finding established | 1682 |
| 2026-05-06 | Phase 11 Batch 11A | Gate × scenarios × seeds cross-product strengthens F-tier absorption to upstream parameter space | 1761 |
| 2026-05-07 | Phase 11 Batch 11B | Methodology specification document split — canonical methodology spec produced | 1835 |
| 2026-05-08 | Phase 11 Batch 11B amendment | Methodology specification offline review revisions | 1870 |

## **5.5 Sweep manifest**

[`data/indices/sweeps/manifest.csv`](../data/indices/sweeps/manifest.csv): catalog of the 13 Phase 10 sensitivity sweeps + Phase 11 Batch 11A two cross-product runs, with per-sweep parameter ranges, panel set, and source script. Authoritative reference for reproducing any specific empirical claim in §3.
