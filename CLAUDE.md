# CLAUDE.md — TPRR Index MVP

> Auto-loaded by Claude Code. Defines project context, conventions, and guardrails. Keep current.

## Who you're working with

You are working with **Matt**, founder of Noble Markets. Relevant context:

- ~15 years in FX trading and derivatives. Fluent in ISDA, CFTC, IOSCO, ASC 815 / IFRS 9.
- Building **Noble Argon** — the product line this repo supports. Argon's flagship is the **TPRR Index** (Token Price Reference Rate), an institutional-grade benchmark for AI inference token prices. Strategy compares it to ICE Brent or Henry Hub for the AI inference asset class.
- Treats AI collaborators like senior analysts: prefers pushback over validation. If a methodology choice is weak, say so. If a simpler approach beats the clever one, say so.
- Publishes the **Noble FX Market Monitor** (Substack). Every interesting finding from this repo is potential content.

**Tone for code, docstrings, commits, and responses**: plain, direct, practitioner-voiced. No hedging. No emojis. No preambles.

## What this project is (and isn't)

### Is

A validation MVP for the TPRR methodology. The only question this codebase exists to answer:

> **Does the TPRR dual-weighted formula — specifically exponential median-distance weighting at λ=3 combined with the three-tier volume hierarchy, over a TWAP daily fixing — produce a stable, credible, manipulation-resistant index when run on realistic data?**

Three core indices:

- **TPRR-F** (Frontier) — top-capability models (~$10+ per M output tokens)
- **TPRR-S** (Standard) — mid-tier workhorses (~$1–$10 per M)
- **TPRR-E** (Efficiency) — economy tier (sub-$1 per M)

Three derived series:

- **TPRR-FPR** = F / S (Frontier Premium Ratio)
- **TPRR-SER** = S / E (Standard Efficiency Ratio)
- **TPRR-B** — blended analytics: `0.25 × P_out + 0.75 × P_in` (informational only, never for derivative settlement)

### Isn't

Not any of the following. Proposing them is a scope-creep red flag:

- Production infrastructure, real-time service, web app, API, dashboard
- User auth, multi-tenant anything
- Cloud deployment
- FX-hedged variants (defers to Noble Xenon — out of scope for this repo)
- Transaction cross-validation via live API probing (production only)
- Multi-currency (USD only)
- Governance scaffolding beyond a methodology decision log
- Intraday spot or monthly-average publication

**Discipline check**: if you're about to write auth code, a React component, a FastAPI route, or a Dockerfile, stop. That's not this repo.

## The methodology in one page

The canonical methodology lives in `docs/tprr_methodology.md` (Matt maintains — current version 1.2). Code matches that document. This section is the working summary for Claude Code context; if it conflicts, the canonical doc wins and this file gets updated.

### Core formula (Section 3.3.1)

```
TPRR_tier(t) = Σᵢ [ w_volᵢ × w_expᵢ × P̃ᵢᵒᵘᵗ(t) ]  /  Σᵢ [ w_volᵢ × w_expᵢ ]
```

Where:
- `P̃ᵢᵒᵘᵗ(t)` = **daily TWAP** of constituent i's output token price, USD per million tokens
- `w_volᵢ` = volume weight from three-tier attestation
- `w_expᵢ` = exponential median-distance weight

### TWAP daily fix (Section 4.2.1) — TWAP-then-weight ordering

**Fixing window**: 09:00–17:00 UTC. 96 fifteen-minute observation slots per day.

**Intraday price model**: real-world providers don't change prices every 15 minutes — they post a price and leave it, often for weeks. Rather than storing 96 rows per constituent per day, we store:

- **Daily panel observations** (one row per contributor per model per date) containing that day's posted price (or daily TWAP on change-event days)
- **Sparse change events** (one row per intraday price change) recording the time and new price

At TWAP computation time, reconstruct the 96 slots on the fly:
- No change event on day D → all 96 slots = posted price → TWAP = posted price
- Change event at slot S → slots `[0, S)` use old price, slots `[S, 96)` use new price → TWAP is slot-weighted

**Ordering choice — TWAP-then-weight**. For each (contributor, model, date): compute daily TWAP first, then apply dual-weighted aggregation across contributors using each contributor's daily TWAP as their "price of the day." Matches dominant commodity-benchmark convention (ICE, Henry Hub, ASCI); keeps weighting dimensionally consistent.

Phase 10 includes a weight-then-TWAP comparison for documentation and publication.

**Data quality gate applies at slot level**. Each slot compared to constituent's 5-day trailing average posted price. Slots failing gate are excluded from the daily TWAP; if all 96 fail, constituent has no valid price that day.

### Volume weights — three-tier attestation hierarchy (Section 3.3.2)

| Tier | Source | Haircut | Applied |
|---|---|---|---|
| A (Contributor-Attested) | Direct contributor billing API | 0% | `w_vol = volume × 1.00` |
| B (Revenue-Derived Proxy) | Public provider revenue × OpenRouter within-provider split | 10% | `w_vol = volume × 0.90` |
| C (Transaction-Verified Market Proxy) | OpenRouter data, filtered for enterprise relevance | 20% | `w_vol = volume × 0.80` |

**Tier B implementation (Option B, per 2026-04-22 decision)**:
1. Input: disclosed provider total API revenue (quarterly), from `config/tier_b_revenue.yaml`
2. Compute: implied provider-level token volume = revenue ÷ provider-weighted reference output price
3. Split: allocate implied volume across provider's models using OpenRouter's within-provider market share
4. Scale: normalise so Σ(allocated_volume × model_price) = disclosed_revenue

Known weakness: the within-provider split depends on OpenRouter data, creating partial correlation with Tier C. The 10-point haircut differential survives this correlation at MVP scale but is a v1.3 methodology refinement target. Phase 10 runs a haircut sensitivity sweep.

Rules:
- Use highest-confidence tier per constituent.
- Tier A applies when ≥3 contributors with attested volumes exist.
- Proxy weights are flagged in all publications.
- **Provider self-reported volumes are NEVER used** (Section 4.2.5).

### Exponential median-distance weight (Section 3.3.3)

Within each tier, compute median output price across active constituents (their daily TWAPs), then:

```
w_expᵢ = exp( -λ × |P̃ᵢ - P_median| / P_median )
```

With **λ = 3** at inception. Reference points:

| Distance from tier median | w_exp |
|---|---|
| 0% | 1.000 |
| 5% | 0.861 |
| 10% | 0.741 |
| 20% | 0.549 |
| 50% | 0.223 |
| 100% | 0.050 |

Principal manipulation resistance. Continuous (no cliff edge), self-calibrating (follows shifting median), compounds with volume.

### Data quality gate (Section 4.2.2)

Applied at slot level. Any slot deviating > 15% from constituent's 5-day trailing average posted price is excluded from that day's TWAP. 3 consecutive days with any slot-level exclusions → constituent suspended pending review.

### Continuity check (Section 4.1)

Single-observation price change > 25% from prior observation triggers `requires_verification` flag. For MVP: flag and log, include anyway unless also failing 5-day gate.

### Minimum constituent count (Section 4.2.4)

Each tier requires ≥ 3 active constituents (valid daily TWAPs) for a daily fix. Below: tier fix suspended, prior valid fix used as fallback.

### TPRR-B blended series (Section 3.3.4)

```
P_blended_i = 0.25 × P̃_outᵢ + 0.75 × P̃_inᵢ
```

Dual-weighted aggregation using `P_blended`. Analytics only.

### Cross-index analytics

```
TPRR_FPR(t) = TPRR_F(t) / TPRR_S(t)
TPRR_SER(t) = TPRR_S(t) / TPRR_E(t)
```

### Base date

**Index level = 100 on 2026-01-01.** Backtest period Jan 1 2025 → current date (~480 days).

### Eligibility (Section 3.1)

Commercial availability, pricing transparency, material enterprise adoption, ≥99.5% uptime over trailing 90d, stable versioned endpoints. Encoded in `config/model_registry.yaml`.

## MVP scope

| Element | MVP | Deferred |
|---|---|---|
| Output-only core indices (F, S, E) | ✅ | |
| Dual-weighted formula | ✅ | |
| Exponential median-distance weighting (λ=3) | ✅ | |
| Three-tier volume hierarchy — all three tiers | ✅ | Tier B v1.3 refinement |
| TWAP daily fix (96 slots, 09:00–17:00 UTC) | ✅ | Intraday spot publication |
| TWAP-then-weight ordering | ✅ | |
| Weight-then-TWAP comparison (Phase 10) | ✅ | |
| Slot-level 15% data quality gate | ✅ | |
| Continuity check (25%) | ✅ flag only | Manual review workflow |
| Minimum-3-constituents suspension | ✅ | |
| TPRR-FPR / TPRR-SER | ✅ | |
| TPRR-B blended analytics | ✅ | Workload-specific variants |
| Backtest Jan 2025 → today | ✅ | |
| Manipulation scenario suite | ✅ | |
| λ sensitivity sweep | ✅ | |
| Haircut sensitivity sweep | ✅ | |
| FX-hedged variants | ❌ | Requires Xenon |
| Transaction cross-validation | ❌ | Production only |
| Intraday spot, monthly average | ❌ | |
| Index Committee workflows | ❌ | |

## Architecture

```
┌─ Mock Contributor Panel ──────────┐
│  Tier A simulation                │
│  ~10 contributors × ~15 models    │
│  Daily posted prices + sparse     │
│  intraday change events + volumes │
└─────────────────┬─────────────────┘
                  │
┌─ OpenRouter API ──────────────────┤      ┌───────────────────────┐
│  /api/v1/models                   ├─────▶│ Normalise to canonical│
│  /models/{a}/{s}/endpoints        │      │ panel schema          │
│  Rankings mirror → Tier C         │      │                       │
└───────────────────────────────────┤      └──────────┬────────────┘
                                    │                 │
┌─ Tier B Revenue Config ───────────┤                 │
│  Quarterly provider revenue       │                 │
│  → Revenue ÷ ref price × OR split ├─────────────────┤
│  → Implied model-level volume     │                 │
└───────────────────────────────────┘                 ▼
                                            ┌────────────────────┐
                                            │ Reconstruct 96     │
                                            │ intraday slots     │
                                            │ per (contrib,model,│
                                            │ date) from panel + │
                                            │ change events      │
                                            └──────────┬─────────┘
                                                       │
                                                       ▼
                                            ┌────────────────────┐
                                            │ Slot-level quality │
                                            │ gate (15% / 5-day) │
                                            └──────────┬─────────┘
                                                       │
                                                       ▼
                                            ┌────────────────────┐
                                            │ Daily TWAP per     │
                                            │ (contrib, model,   │
                                            │ date)              │
                                            └──────────┬─────────┘
                                                       │
                                                       ▼
                                            ┌────────────────────┐
                                            │ Tier median → w_exp│
                                            │ w_vol from tiered  │
                                            │ hierarchy          │
                                            │ → dual-weighted agg│
                                            └──────────┬─────────┘
                                                       │
                                                       ▼
                                    ┌──────────────────────────────┐
                                    │ TPRR-F/S/E + FPR/SER/B       │
                                    │ → SQLite + Plotly HTML       │
                                    └──────────────────────────────┘
```

## Tech stack (chosen and locked)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Dep mgmt | `uv` |
| Data | pandas + numpy |
| Persistence | SQLite via SQLAlchemy 2.x |
| Config | pydantic v2 + YAML |
| HTTP | httpx |
| Viz | Plotly |
| Tests | pytest + hypothesis |
| Lint/format | ruff |
| Type check | mypy --strict on `src/` |
| Notebooks | Jupyter |

**Do not introduce new dependencies without asking.**

## Directory structure

```
tprr/
├── CLAUDE.md
├── project_plan.md
├── prompts.md
├── README.md
├── pyproject.toml
├── .gitignore
├── docs/
│   ├── tprr_methodology.md            # CANONICAL (Matt maintains)
│   ├── decision_log.md
│   └── findings/
├── config/
│   ├── model_registry.yaml
│   ├── contributors.yaml
│   ├── index_config.yaml              # λ, gate %, base date 2026-01-01, haircuts
│   ├── tier_b_revenue.yaml            # Quarterly provider revenue
│   └── scenarios.yaml
├── data/
│   ├── raw/
│   │   ├── mock_panel_*.parquet       # Daily observations
│   │   ├── mock_change_events_*.parquet  # Sparse intraday changes
│   │   └── openrouter/                # Cached API responses by date
│   ├── processed/
│   └── indices/
├── notebooks/
├── src/tprr/
│   ├── __init__.py
│   ├── config.py
│   ├── schema.py
│   ├── mockdata/
│   │   ├── contributors.py
│   │   ├── pricing.py                 # Daily baseline prices
│   │   ├── change_events.py           # Intraday change events
│   │   ├── volume.py
│   │   └── outliers.py
│   ├── reference/
│   │   └── openrouter.py
│   ├── twap/
│   │   └── reconstruct.py             # Reconstruct 96 slots + compute TWAP
│   ├── index/
│   │   ├── __init__.py
│   │   ├── eligibility.py
│   │   ├── quality.py                 # Slot-level quality gate
│   │   ├── weights.py                 # w_vol (tiered), w_exp (exponential)
│   │   ├── tier_b.py                  # Tier B volume derivation
│   │   ├── aggregation.py             # Dual-weighted aggregation
│   │   ├── derived.py                 # FPR, SER, B
│   │   ├── compute.py                 # End-to-end orchestration
│   │   └── versions/v0_1/
│   ├── storage/
│   │   └── db.py
│   └── viz/
│       └── charts.py
├── tests/
└── scripts/
    ├── generate_mock_data.py
    ├── fetch_openrouter.py
    ├── compute_indices.py
    ├── run_scenarios.py
    ├── lambda_sweep.py
    ├── haircut_sweep.py
    ├── twap_ordering_comparison.py
    └── plot_indices.py
```

## Coding conventions

### Types
- Full type hints on every public function. `mypy --strict` passes on `src/`.
- No `Any` without comment.
- Dates as `datetime.date`; ISO strings only at I/O boundaries.

### Naming
- Prices include unit: `price_usd_per_mtok`. `mtok` = million tokens.
- Intraday slot indices: `slot_idx`, integer 0–95.
- TWAP values: `twap_output_usd_mtok`, `twap_input_usd_mtok`.
- Tier codes: `TPRR_F`, `TPRR_S`, `TPRR_E`.
- Version IDs: `v0_1`, `v0_2` (underscore).

### Function design
- Pure functions where possible. Side effects isolated to adapters.
- Config passed in or injected.
- > ~40 lines = probably doing two things.

### Pandas idioms
- `.pipe()` for chained transforms. No `inplace=True`. Validate shape/columns at boundaries.
- Categorical dtype for `tier`, `contributor_id`, `model_id` in large frames.

### Determinism
- **Index computation deterministic**. All randomness in `mockdata/`, seeded.
- Same config + seed + date range → byte-identical output.

### Testing
- Every weighting/aggregation/quality/TWAP/Tier-B function has unit tests.
- Hypothesis property tests covering:
  - `exponential_weight` monotonic in distance
  - TWAP of constant prices = that price
  - TWAP with single change event at slot S = (S × old + (96-S) × new) / 96
  - Sum of final weights > 0 when ≥1 active constituent
  - Scaling all prices by k scales index by k

## Versioning the methodology

Every material methodology change bumps version. Submodules under `src/tprr/index/versions/v0_1/`. Old versions runnable. Every version has a matching entry in `docs/decision_log.md`.

## When to ask, when to act

### Ask first
- Changes altering computed index values (λ, haircuts, blend ratio, TWAP window, formula)
- New dependencies
- Changes to `schema.py`
- Changes to `config/*.yaml`
- TWAP ordering questions
- Scope shifts toward productionisation

### Act without asking
- Bug fixes, behavior-preserving refactors, tests, logging, formatting, docs

### Always do
- Methodology decisions → entry in `docs/decision_log.md`
- Surprising findings → stub in `docs/findings/`

## OpenRouter integration rules

### Endpoints (no auth for reads)
- `GET https://openrouter.ai/api/v1/models` — full model list
- `GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints` — per-model provider pricing
- `GET https://raw.githubusercontent.com/jampongsathorn/openrouter-rankings/main/data/latest.json` — weekly rankings (then dated snapshot)

### Normalisation
- `$/token` → `$/Mtok` (× 1e6)
- Ignore `:free`, `:nitro`, `:floor`, `:online` variant suffixes
- Skip `openrouter/auto`
- Cache to `data/raw/openrouter/{kind}/{YYYY-MM-DD}.json`. Never re-fetch same day.

## Data contracts

### PanelObservation — daily posted price per contributor per model

| Field | Type | Notes |
|---|---|---|
| `observation_date` | date | |
| `constituent_id` | str | `openai/gpt-5-pro` |
| `contributor_id` | str | `contrib_alpha` (A/B) or `openrouter:provider` (C) |
| `tier_code` | str | `TPRR_F` / `TPRR_S` / `TPRR_E` |
| `attestation_tier` | str | `A` / `B` / `C` |
| `input_price_usd_mtok` | float | Daily posted price (pre-TWAP) |
| `output_price_usd_mtok` | float | Same |
| `volume_mtok_7d` | float | Trailing 7-day output volume |
| `source` | str | `contributor_mock` / `openrouter_*` / `tier_b_derived` |
| `submitted_at` | datetime | |
| `notes` | str | |

### ChangeEvent — sparse intraday price change

| Field | Type | Notes |
|---|---|---|
| `event_date` | date | |
| `contributor_id` | str | |
| `constituent_id` | str | |
| `change_slot_idx` | int | 0–95. Slots `[0, idx)` old, `[idx, 96)` new. |
| `old_input_price_usd_mtok` | float | |
| `new_input_price_usd_mtok` | float | |
| `old_output_price_usd_mtok` | float | |
| `new_output_price_usd_mtok` | float | |
| `reason` | str | `baseline_cut` / `outlier_injection` / `version_update` |

### IndexValue — daily fix output

| Field | Type | Notes |
|---|---|---|
| `as_of_date` | date | |
| `index_code` | str | TPRR_F/S/E/FPR/SER/B_F/B_S/B_E |
| `version` | str | `v0_1` |
| `lambda` | float | |
| `ordering` | str | `twap_then_weight` / `weight_then_twap` |
| `raw_value_usd_mtok` | float | $/Mtok or ratio |
| `index_level` | float | Rebased to 100 at 2026-01-01 for core+B |
| `n_constituents` | int | |
| `n_constituents_active` | int | |
| `tier_a_weight_share` | float | |
| `tier_b_weight_share` | float | |
| `tier_c_weight_share` | float | |
| `suspended` | bool | |
| `notes` | str | |

## Non-negotiables

1. Every methodology choice documented in `docs/decision_log.md`.
2. Every version reproducible — byte-identical given same inputs/seed.
3. Index computation deterministic.
4. Mock data clearly labelled — `source` populated everywhere.
5. Provider self-reported volumes NEVER used for weighting.
6. Nothing published externally without Matt's sign-off.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy src/

uv run python scripts/generate_mock_data.py --start 2025-01-01 --end today --seed 42
uv run python scripts/fetch_openrouter.py
uv run python scripts/compute_indices.py --version v0_1 --lambda 3.0 --ordering twap_then_weight
uv run python scripts/run_scenarios.py
uv run python scripts/lambda_sweep.py
uv run python scripts/haircut_sweep.py
uv run python scripts/twap_ordering_comparison.py
uv run python scripts/plot_indices.py

uv run jupyter lab
```

## One final rule

If you find yourself writing complex code to work around a methodology ambiguity, **stop and ask**. Pause for 10 minutes rather than build 3 hours on a wrong assumption.
