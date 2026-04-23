# TPRR MVP — Project Plan

**Purpose**: validate the TPRR methodology (Noble Argon v1.2) end-to-end on realistic data, producing a reproducible artifact that can be shown to investors and prospective contributors.

**Timeline assumption**: ~14 days of focused work. In evenings + weekends alongside Noble's other workstreams, realistic calendar time is 5–9 weeks. Do not compress. Phases 7 and 10 are where the intellectual work happens.

**Definition of done**: `uv run python scripts/compute_indices.py` produces ~480 days of TPRR-F / TPRR-S / TPRR-E / TPRR-FPR / TPRR-SER / TPRR-B (per tier) values from mock Tier A data, Tier B revenue-anchored proxies, and Tier C OpenRouter reference data — running a TWAP daily fix across 96 intraday slots and dual-weighted aggregation. A scenario test suite demonstrates exponential median-distance weighting behaves as the methodology claims. λ, haircut, and TWAP-ordering sensitivity sweeps produce publishable findings. A Plotly chart renders the result. A decision log documents every methodology choice.

---

## Success criteria

A credible demonstration — to yourself first, then to a CFO or VC — of seven concrete facts:

1. **The algorithm runs end-to-end** on ~480 days of data without manual intervention.
2. **Exponential median-distance weighting (λ=3) performs as the methodology claims** — a constituent 30% above the tier median carries ~41% of the weight of a median-priced constituent. Verified empirically.
3. **Manipulation is self-defeating.** A contributor pricing 50% above the tier median for 30+ days moves the index by less than X bps vs. the no-manipulation baseline. (Measure X, don't predict it.)
4. **Fat-finger errors are absorbed.** A 10× pricing error on one slot is effectively filtered by the slot-level quality gate + TWAP averaging + exponential weighting, combined. Index moves < 0.5% vs. clean baseline.
5. **The three-tier hierarchy works.** Running the same data with only Tier C weights produces a materially different index from the full Tier A+B+C result, in an explainable way — justifying Noble's contributor recruitment strategy.
6. **Parameter sensitivities are understood.** λ sweep, haircut sweep, and TWAP-ordering comparison each produce defensible stories about the tradeoffs.
7. **TWAP ordering choice is defended empirically.** TWAP-then-weight vs. weight-then-TWAP produces materially similar or measurably different results; either way, the choice is documented.

**Corollary success**: ≥ 4 findings worth publishing in `docs/findings/`. These feed Noble FX Monitor during and after the build.

---

## Non-goals

Repeat from CLAUDE.md. **Do not build these.**

- Web app, dashboard, API, FastAPI route, React component
- User auth, multi-tenant architecture
- Cloud deployment (Vercel, AWS, GCP, Docker)
- FX-hedged variants (defers to Xenon)
- Live API probing for transaction cross-validation
- Intraday spot or monthly average series
- Multimodal (image/audio/video) token pricing
- Index Committee governance workflows

If any feel like they'd improve the MVP, stop. The MVP validates the core formula. It is not the product.

---

## Phase overview

| # | Phase | Effort | Exit criterion |
|---|---|---|---|
| 0 | Project setup | 0.5d | Repo exists, deps install, pytest passes |
| 1 | Schema + config | 1d | Pydantic schemas defined; 4 config files loaded |
| 2a | Mock panel: daily baselines | 1.5d | `generate_mock_data.py` produces daily panel |
| 2b | Mock panel: intraday change events | 1d | Change events generator produces realistic frequency |
| 2c | TWAP reconstructor | 0.5d | Function reconstructs 96 slots + computes TWAP |
| 3 | Outlier injection scenarios | 1d | 8 scenario types encodable; deterministic given seed |
| 4 | OpenRouter integration | 1d | Fetch + normalise produces rows matching panel schema |
| 4b | Tier B revenue config | 0.5d | `tier_b_revenue.yaml` populated; loader works |
| 5a | Weighting module | 1d | `w_vol` and `w_exp` pass unit + property tests |
| 5b | Tier B derivation | 1d | `tier_b.py` produces per-model volume from revenue + OR split |
| 6 | Slot-level quality gate | 0.5d | 15% gate + 25% continuity + min-3 suspension tested |
| 7 | Aggregation + end-to-end compute | 1.5d | Full pipeline: raw → TWAP → indices, both orderings runnable |
| 8 | Derived indices | 0.5d | FPR, SER, B_F, B_S, B_E all computed |
| 9 | Visualization | 0.5d | One HTML chart showing all series over full backtest |
| 10 | Scenario + sensitivity suite | 3d | Scenarios + λ sweep + haircut sweep + TWAP-ordering comparison → findings |
| 11 | Decision log + writeup | 1d | `docs/decision_log.md` complete; `docs/findings/` has ≥4 entries |

**Total: ~14d focused work.**

---

## Phase 0 — Project setup

### Tasks
- Repo skeleton per CLAUDE.md directory structure
- `pyproject.toml` with pinned deps: pandas, numpy, pydantic, PyYAML, SQLAlchemy 2.x, httpx, plotly; dev: pytest, pytest-cov, hypothesis, ruff, mypy
- `.gitignore`: Python artifacts, `.venv`, `data/raw/` (large synthetic files), `*.db`, `.env`, `.DS_Store`
- `README.md` — 15 lines: what this is, `uv sync`, `uv run pytest`
- `.python-version` → 3.11+
- Empty `__init__.py` in each `src/tprr/` subpackage
- `tests/test_smoke.py` — `def test_smoke(): assert True`
- `docs/decision_log.md` stub with header + "## 2026-04-22 — Project initialised"
- `docs/findings/README.md` stub
- Empty `docs/tprr_methodology.md` — Matt pastes canonical content

### Exit
- `uv sync` works
- `uv run pytest` passes (1 test)
- `uv run ruff check .` passes
- `uv run mypy src/` returns 0

---

## Phase 1 — Schema and config

### Tasks
- `src/tprr/schema.py`:
  - `PanelObservation` (pydantic)
  - `ChangeEvent` (pydantic)
  - `IndexValue` (pydantic)
  - `Tier` and `AttestationTier` str enums
  - `PanelObservationDF`, `ChangeEventDF`, `IndexValueDF` (pandas validators)
- `src/tprr/config.py`:
  - `IndexConfig`, `ModelMetadata`, `ModelRegistry`, `ContributorProfile`, `ContributorPanel`
  - New: `TierBRevenueEntry`, `TierBRevenueConfig` (see Phase 4b)
  - Functions: `load_index_config()`, `load_model_registry()`, `load_contributors()`, `load_tier_b_revenue()`, `load_scenarios()`, `load_all()`
- Seed config files:
  - `config/index_config.yaml`: `lambda_: 3.0`, `base_date: 2026-01-01`, `backtest_start: 2025-01-01`, `quality_gate_pct: 0.15`, `continuity_check_pct: 0.25`, `min_constituents_per_tier: 3`, `staleness_max_days: 3`, `tier_haircuts: {A: 1.0, B: 0.9, C: 0.8}`, `twap_window_utc: [9, 17]`, `twap_slots: 96`, `default_ordering: twap_then_weight`
  - `config/model_registry.yaml`: 15 models per project_plan proposal below
  - `config/contributors.yaml`: 10 contributors per proposal below
  - `config/tier_b_revenue.yaml`: stub (populated in Phase 4b)

### Model registry content

Current-era frontier models. Mock data uses these as baselines with realistic drift. Real prices are ballpark — confirm or adjust in config.

**Frontier (TPRR-F)** — target: 5 constituents
- `openai/gpt-5-pro` — ~$15/Mtok input, ~$75/Mtok output
- `openai/gpt-5` — ~$10/Mtok input, ~$40/Mtok output
- `anthropic/claude-opus-4-7` — ~$15/Mtok input, ~$75/Mtok output
- `anthropic/claude-opus-4-6` — ~$15/Mtok input, ~$75/Mtok output
- `google/gemini-3-pro` — ~$5/Mtok input, ~$30/Mtok output

**Standard (TPRR-S)** — target: 5 constituents
- `openai/gpt-5-mini` — ~$0.50/Mtok input, ~$4/Mtok output
- `anthropic/claude-sonnet-4-6` — ~$3/Mtok input, ~$15/Mtok output
- `anthropic/claude-haiku-4-5` — ~$1/Mtok input, ~$5/Mtok output
- `google/gemini-2-flash` — ~$0.30/Mtok input, ~$2.50/Mtok output
- `meta/llama-4-70b-hosted` — ~$0.60/Mtok input, ~$0.80/Mtok output

**Efficiency (TPRR-E)** — target: 5 constituents
- `google/gemini-flash-lite` — ~$0.10/Mtok input, ~$0.40/Mtok output
- `openai/gpt-5-nano` — ~$0.15/Mtok input, ~$0.60/Mtok output
- `deepseek/deepseek-v3-2` — ~$0.25/Mtok input, ~$1.00/Mtok output
- `alibaba/qwen-3-6-plus` — ~$0.20/Mtok input, ~$0.80/Mtok output
- `xiaomi/mimo-v2-pro` — ~$0.30/Mtok input, ~$1.10/Mtok output

### Contributor panel

10 heterogeneous contributors, per CLAUDE.md conventions. Each covers a subset of models (typically 6–10).

### Exit
- All config files parse without error
- `uv run python -c "from tprr.config import load_all; load_all()"` returns validated objects
- `mypy --strict` passes

---

## Phase 2a — Mock panel: daily baselines

### Tasks
- `src/tprr/mockdata/pricing.py`:
  - `generate_baseline_prices(registry, start_date, end_date, seed) -> DataFrame`
  - Columns: `date, constituent_id, baseline_input_price_usd_mtok, baseline_output_price_usd_mtok`
  - Realistic patterns: gradual downward drift; step-downs (frontier 10–30%, every 90–180d; efficiency 20–50%, more frequent)
  - Strictly positive, seeded
- `src/tprr/mockdata/contributors.py`:
  - `generate_contributor_panel(baseline_prices, contributor_panel, seed) -> DataFrame`
  - Per-contributor systematic bias + daily Gaussian noise
  - Output matches `PanelObservationDF` (with `volume_mtok_7d` set by Phase 2a completion)
  - All rows: `attestation_tier = "A"`, `source = "contributor_mock"`
- `src/tprr/mockdata/volume.py`:
  - `generate_volumes(panel_df, contributor_panel, seed) -> panel_df` with `volume_mtok_7d` populated
  - Contributor-scale-based base volume; correlated across models within contributor
- `scripts/generate_mock_data.py --start 2025-01-01 --end {today} --seed 42`:
  - Calls the above in sequence
  - Writes `data/raw/mock_panel_clean_seed{seed}.parquet`
  - Prints: N rows, date range, mean price by tier, mean volume by contributor

### Acceptance
- 480 days × ~10 contributors × ~8 covered models ≈ 38K rows
- Prices strictly positive, finite
- Volumes non-negative
- `PanelObservationDF` validation passes
- Seeded determinism: md5sum of two runs with same seed identical
- Notebook `notebooks/02a_explore_baseline.ipynb` renders baseline prices per tier — looks plausible

---

## Phase 2b — Mock panel: intraday change events

### Tasks
- `src/tprr/mockdata/change_events.py`:
  - `generate_change_events(panel_df, registry, contributor_panel, seed) -> DataFrame` matching `ChangeEventDF`
  - Realistic frequency:
    - Frontier: ~4–6 price changes per year per contributor-model pair
    - Standard: ~6–10 per year
    - Efficiency: ~10–20 per year
  - Slot-of-day chosen from business-hours-weighted distribution (most changes during 11:00–15:00 UTC when provider teams deploy)
  - Each change event corresponds to a day where baseline price changed materially — the posted price on that day reflects the *new* price, not the TWAP. Change event records pre-change price.
- Extend `scripts/generate_mock_data.py` to produce `data/raw/mock_change_events_seed{seed}.parquet`
- Update panel generation: on change-event days, set panel's `output_price_usd_mtok` to the post-change price (the "closing" posted price)

### Acceptance
- Change events produced at realistic frequency (eyeball)
- Schema validation passes
- Deterministic given seed
- Change events reference valid (contributor, constituent, date) combinations from panel
- Notebook `notebooks/02b_change_events_check.ipynb` shows distribution: events per model, time-of-day, frequency per year

---

## Phase 2c — TWAP reconstructor

### Tasks
- `src/tprr/twap/reconstruct.py`:
  - `reconstruct_slots(contributor_id, constituent_id, date, panel_df, change_events_df) -> np.ndarray[96]` — returns the 96 slot prices for output (can extend for input)
  - `compute_daily_twap(slot_prices: np.ndarray[96], excluded_slots: set[int] = None) -> float` — simple arithmetic mean, excluding quality-gate failures
  - `compute_panel_twap(panel_df, change_events_df, excluded_slots_df: DataFrame | None) -> panel_df` with `twap_output_usd_mtok`, `twap_input_usd_mtok` columns added

### Key behaviours
- If no change event on day D for (contributor, constituent): all 96 slots equal `output_price_usd_mtok` from panel → TWAP = that price
- If change event at slot S: slots `[0, S)` = `old_output_price`, slots `[S, 96)` = `new_output_price` → TWAP is slot-weighted
- Excluded slots are dropped from the mean (not zeroed)

### Tests
- Constant prices → TWAP equals that price
- Single change at slot 48 (midway) → TWAP = (old + new) / 2
- Single change at slot 0 → TWAP = new price
- Single change at slot 95 → TWAP ≈ (95×old + 1×new) / 96
- Exclusions reduce denominator correctly
- All 96 excluded → NaN or raise (decision: raise with a clear error)

### Acceptance
- Unit tests pass
- Property test: TWAP monotonically shifts from old to new as change_slot_idx decreases
- Extension to input prices works symmetrically

---

## Phase 3 — Outlier injection scenarios

### Scenarios (expanded to include intraday-aware cases)

| # | Scenario | Tests |
|---|---|---|
| 1 | Fat-finger high (10× price) on one slot | Slot-level quality gate + TWAP absorption |
| 2 | Fat-finger low (1/10× price) on one slot | Same |
| 3 | Stale quote — no changes for N days while market moves | Staleness handling |
| 4 | Contributor blackout — no panel rows for N days | Min-constituents suspension |
| 5 | Legitimate 50% price cut shock (one contributor, one model, one day) | Exponential weighting initial fade + recovery |
| 6 | Sustained strategic manipulation — contributor prices X% above median for N days | Exponential weighting makes ineffective |
| 7 | Tier reshuffling — model moves tiers on specified date | Tier change handling |
| 8 | New model launch mid-period | Smooth inclusion |
| 9 | Intraday within-day spike — one contributor posts an off-market price for a short window (e.g. 10 slots) | TWAP averaging + slot-level gate combined |

### Tasks
- `src/tprr/mockdata/outliers.py` with each scenario as pure function
- `config/scenarios.yaml` with default scenario set
- Extend `scripts/generate_mock_data.py` with `--scenarios scenarios.yaml` flag
- Output files: `data/raw/mock_panel_{scenario_set}_seed{seed}.parquet` + matching change events file

### Acceptance
- Each scenario independently testable
- Scenarios mutate a copy — clean baseline always preserved
- Deterministic given seed
- Spot-check notebook `notebooks/03_scenario_spotcheck.ipynb` visualises each injection

### Methodology gap flagged
- Staleness rule (3 days default) — documented in decision log pending Index Committee review

---

## Phase 4 — OpenRouter integration

### Tasks
- `src/tprr/reference/openrouter.py`:
  - `fetch_models()` / `fetch_model_endpoints(author, slug)` / `fetch_rankings()`
  - Caches to `data/raw/openrouter/{kind}/{YYYY-MM-DD}.json`
  - httpx client, 30s timeout, single retry on 5xx
  - User-Agent: "Noble-Argon-TPRR/0.1 research"
- Normalisation:
  - `normalise_models_to_panel(models_json, model_registry, as_of_date) -> DataFrame`
  - `normalise_endpoints_to_panel(endpoints_json, constituent_id, as_of_date) -> DataFrame`
  - `enrich_with_rankings_volume(panel_df, rankings_json) -> panel_df`
  - OpenRouter-sourced rows: `attestation_tier = "C"`, `source = "openrouter_*"`
- `scripts/fetch_openrouter.py`: runs all three, writes `data/raw/openrouter_panel_{YYYY-MM-DD}.parquet`

### Tier C historical backfill
OpenRouter rankings mirror publishes daily snapshots from a recent date. For backfill across Jan 2025 → today: use the current snapshot's market-share structure as a static proxy across the full backtest, with a decision log note. This is acceptable because Tier C is proxy data by design. Don't fabricate historical ranking movements.

### Acceptance
- Parquet matches `PanelObservationDF` schema
- Prices reasonable (spot check: GPT-5 output ~$40, not 0.00004 or 40000)
- Cache hits second time same day
- At least one row per registry model that has an OpenRouter match
- Unmatched models logged as INFO warnings, not errors

---

## Phase 4b — Tier B revenue config

### Tasks
- `config/tier_b_revenue.yaml` structure:
  ```yaml
  providers:
    openai:
      disclosed_revenue_usd:
        - period: 2025-Q1
          amount: 2500000000    # illustrative
          source: "analyst_triangulation"
        - period: 2025-Q2
          amount: 3100000000
          source: "reported_q2"
      # ...
    anthropic:
      # ...
  ```
- Populate with ballpark numbers from public reporting and analyst commentary (Menlo, The Information, reported earnings). Note each entry's source.
- `src/tprr/config.py` loader validates structure, converts to typed objects.
- `TierBRevenueConfig` exposes `get_provider_revenue(provider, date) -> float` with linear interpolation between reported quarters.

### MVP simplification
For MVP it's acceptable to use indicative/synthetic revenue numbers if real ones are uncertain — this is a research MVP. But each number must have a recorded source ("reported", "analyst estimate", "synthetic for MVP"). That trail becomes the audit record when Matt graduates Tier B to production.

### Acceptance
- YAML parses; loader returns typed objects
- Coverage: at least the providers who have multiple models in the registry (OpenAI, Anthropic, Google, Meta, DeepSeek, Alibaba)
- Quarterly cadence: Q1 2025 through most recent closed quarter
- Test: `get_provider_revenue('openai', date(2025, 2, 15))` interpolates between Q1 and Q2

---

## Phase 5a — Weighting module

### Tasks
- `src/tprr/index/weights.py`:
  - `volume_weight(volume_mtok, attestation_tier, config) -> float`
    - Applies haircut from config.tier_haircuts
  - `exponential_weight(price, tier_median, lambda_) -> float`
    - Returns `exp(-lambda_ × abs(price - tier_median) / tier_median)`
  - `compute_tier_median(prices) -> float`
  - `compute_dual_weights(panel_day_df, config) -> panel_day_df_with_weights`

### Tests
- All exp_weight values in the table match to 3 decimal places at λ=3
- Volume haircuts: A=1.0×, B=0.9×, C=0.8×
- Zero volume → zero w_vol (no division issues upstream)

### Property tests (hypothesis)
- exp_weight monotonically non-increasing as distance grows
- exp_weight symmetric around median
- volume_weight linear in volume
- exp_weight ∈ (0, 1]

---

## Phase 5b — Tier B derivation

### Tasks
- `src/tprr/index/tier_b.py`:
  - `derive_tier_b_volumes(as_of_date, panel_df, openrouter_rankings_df, tier_b_revenue_config, model_registry) -> DataFrame`
  - Algorithm (per Option B decision):
    1. Group registry by provider (e.g., openai → [gpt-5-pro, gpt-5, gpt-5-mini, gpt-5-nano])
    2. For each provider: get disclosed revenue for the date (interpolated)
    3. Compute provider-weighted reference output price: weighted average of that provider's models' output prices, weighted by OpenRouter share
    4. Implied provider volume = revenue ÷ reference_price (in token terms, × 1e6 to get Mtok)
    5. Split across provider's models using OR within-provider share
    6. Scale: normalise so Σ(allocated_volume × model_price) = disclosed_revenue
  - Output rows: `attestation_tier = "B"`, `source = "tier_b_derived"`, populated volume
  - One row per (provider, model, date) — monthly cadence is fine; daily interpolation handled downstream

### Tests
- Sum of allocated volumes × prices ≈ disclosed revenue (within tolerance)
- Missing provider in revenue config → Tier B rows not produced (fall back to Tier C)
- Missing OpenRouter coverage → graceful degradation with warning
- Determinism: same inputs → same outputs (no seeding needed; this is deterministic)

### Integration
- `compute_dual_weights` preferences: for each (constituent, date), use highest-tier data available
  - Count contributors with attested volume for that constituent → if ≥3, use Tier A weights
  - Else if provider has Tier B revenue data available → use Tier B
  - Else → use Tier C (OpenRouter rankings)
- Record which tier was used in `attestation_tier` column on each weighted row

### Acceptance
- Unit tests pass
- End-to-end: a constituent with no Tier A contributors still gets a weight via Tier B or C
- Tier share breakdown in output (tier_a_weight_share etc.) sums to 1.0

---

## Phase 6 — Slot-level quality gate

### Tasks
- `src/tprr/index/quality.py`:
  - `apply_slot_level_gate(panel_df, change_events_df, trailing_window=5, deviation_pct=0.15) -> excluded_slots_df`
    - For each (contributor, constituent, date): compute trailing 5-day average posted price (daily level, excluding current day)
    - Reconstruct 96 slots; compare each slot to trailing average
    - Return DataFrame of (contributor, constituent, date, slot_idx) tuples to exclude
  - `apply_continuity_check(panel_df, pct=0.25) -> panel_df` with flag column
  - `apply_staleness_rule(panel_df, max_stale_days=3) -> panel_df` with flag column
  - `check_min_constituents(panel_day_df, tier: str, min_n=3) -> bool`
  - Consecutive-day tracking: 3 consecutive days with any slot-level exclusions for a constituent → suspension flag set

### Tests
- 14% slot deviation passes; 16% fails
- Trailing average correctly excludes current day (shift before rolling)
- First 5 days of each (contributor, constituent) series: gate not applied (insufficient history)
- 3 consecutive fail days → suspension; 2 then 1 pass → count resets
- Stale 2-day-old ok, 4-day-old stale
- Continuity: 26% jump from one day to next → flagged; 24% not flagged

---

## Phase 7 — Aggregation and end-to-end compute pipeline

### 7.0 — Pre-implementation methodology check

Before coding: use prompt M.1 / 7.0 to confirm pipeline order and handle ambiguity. Specifically verify:
- Quality gate → TWAP → tier median computation → weights → aggregation
- If quality gate excludes slots on day T, TWAP on day T uses the surviving slots
- Tier median on day T uses TWAP values of ACTIVE constituents (passing quality gate + having ≥N valid slots)
- Suspended tiers (< 3 active) → use prior day's index level

### Tasks
- `src/tprr/index/aggregation.py`:
  - `compute_tier_index(panel_day_df, config, ordering) -> dict`
  - TWAP-then-weight path (default): operates on daily TWAP values
  - Weight-then-TWAP path (for comparison in Phase 10): runs the weighted aggregation at each of 96 slots, then TWAPs the 96 tier-level index values
- `src/tprr/index/compute.py`:
  - `run_full_pipeline(config, panel_df, change_events_df, tier_b_config, openrouter_df, version, ordering) -> indices_df`
  - Handles suspension fallback (prior day)
  - Rebases to 100 at `base_date = 2026-01-01`
- `src/tprr/index/versions/v0_1/`: frozen module capturing the v0.1 code path
- `src/tprr/storage/db.py`: SQLAlchemy 2.x models, upsert logic
- `scripts/compute_indices.py`:
  - CLI: `--version v0_1`, `--lambda 3.0`, `--ordering {twap_then_weight|weight_then_twap}`, `--panel-input`, `--change-events-input`, `--output-db`
  - Runs pipeline, rebases, writes to SQLite + parquet
  - Prints summary

### Tests
- 30-day synthetic panel produces 30 × 3 = 90 core tier-day observations (plus derived indices in Phase 8)
- All values positive, finite
- F > S > E on every day (sanity)
- Hand-computed single-day match
- Suspension: manually remove all but 2 constituents from a tier → suspension + fallback to prior
- Determinism: two runs identical
- Both orderings runnable; output differs (or doesn't) and is deterministic

---

## Phase 8 — Derived indices

### Tasks
- `src/tprr/index/derived.py`:
  - `compute_fpr(indices_df)` — F / S
  - `compute_ser(indices_df)` — S / E
  - `compute_tprr_b(panel_df, change_events_df, config) -> indices_df`
    - Blended price per constituent: `0.25 × P_out + 0.75 × P_in` (daily TWAPs)
    - Runs dual-weighted aggregation on blended
    - Produces `TPRR_B_F`, `TPRR_B_S`, `TPRR_B_E`
- Update `scripts/compute_indices.py` to run derived after core

### Tests
- FPR = F/S exactly, SER = S/E exactly
- TPRR_B lower than TPRR core (input prices << output prices, and B weights input 75%)
- No NaN/inf in ratios except where numerator or denominator is NaN

---

## Phase 9 — Visualization

### Tasks
- `src/tprr/viz/charts.py`:
  - `plot_tprr_dashboard(indices_df, output_path)`
  - Panels:
    - Three subplots for F, S, E (index_level over time)
    - Two subplots for FPR, SER
    - One subplot overlaying TPRR-B vs TPRR-core for Frontier
  - Title: "TPRR Index — v0.1 Backtest"
  - Subtitle: "Synthetic contributor data · OpenRouter Tier C reference · Methodology v1.2 · λ={X} · Base 2026-01-01"
  - Clean institutional look; dark-on-light, thin lines, subtle grid
- `scripts/plot_indices.py` reads latest indices, writes HTML to `data/indices/charts/`

### Exit
- HTML opens in browser, renders interactively, axes labeled with units
- Methodology version + λ + ordering shown on chart (transparency)

---

## Phase 10 — Scenario + sensitivity suite

Budget 3 days. Do not rush.

### 10.1 Scenario suite — `scripts/run_scenarios.py`

For each of the 9 scenarios from Phase 3:
1. Generate (clean + scenario) panel and change-events pair
2. Compute indices on both
3. Diff series; produce `docs/findings/scenario_{name}.md` with chart + prose

### 10.2 λ sensitivity — `scripts/lambda_sweep.py`

Sweep λ ∈ [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
- Clean run → volatility (std of day-over-day log returns, annualised)
- Sustained manipulation scenario → max sustained deviation

Dual-axis chart: λ on x, volatility on one y, manipulation deviation on other. `docs/findings/lambda_sensitivity.md` with table + commentary + recommendation on λ default.

### 10.3 Haircut sensitivity — `scripts/haircut_sweep.py`

Sweep haircut spacings:
- Default: A=1.0, B=0.9, C=0.8
- Tighter: 1.0 / 0.95 / 0.90
- Looser: 1.0 / 0.85 / 0.70
- No differentiation: 1.0 / 1.0 / 1.0 (null hypothesis)

For each: compute clean backtest; compute sustained-manipulation scenario. Metrics: volatility, manipulation deviation, and divergence from default.

`docs/findings/haircut_sensitivity.md` with: table, chart, and a defensive paragraph on "why the default spacing is justified" (or proposed revision if not).

### 10.4 TWAP ordering comparison — `scripts/twap_ordering_comparison.py`

Run the full backtest twice: `--ordering twap_then_weight` vs `--ordering weight_then_twap`.
- Compare index series: correlation, mean absolute difference, max difference
- Identify days where they diverge most — is it always slot-level gate firings?
- `docs/findings/twap_ordering.md`: explanation of the two approaches, empirical comparison, defence of TWAP-then-weight choice

### Exit
- All 9 scenarios produced finding markdowns
- λ, haircut, and ordering findings each a standalone doc with chart + interpretation
- Total: ≥ 12 finding docs in `docs/findings/`

Each should stand alone — Matt can screen-share any one during a VC call without context.

---

## Phase 11 — Decision log + writeup

### Tasks
- `docs/decision_log.md` consolidated, chronological. Every methodology decision recorded. Specifically verify entries for:
  - Tier membership (15 models, which in F/S/E)
  - Baseline prices
  - Contributor count and profiles
  - Staleness rule (3 days)
  - λ default (and any revision from Phase 10)
  - Quality gate thresholds (15% slot, 25% continuity)
  - Min constituents (3)
  - Suspension fallback (prior-day value)
  - Tier haircuts (100/90/80) + sensitivity findings
  - Blend ratio (25:75 per methodology)
  - TWAP window (09:00–17:00 UTC, 96 slots)
  - TWAP ordering choice (TWAP-then-weight) + comparison finding
  - Tier B implementation (Option B, revenue-anchored)
  - Base date (2026-01-01)
  - First-5-days gate exclusion
- `docs/findings/README.md` — index of all findings with one-line summaries
- `README.md` rewritten
- `docs/TPRR_v01_summary.md` — strict one-page internal summary: outcome, three headline findings, limitations, v0.2 / production queue

### Exit
- Repo coherent end-to-end
- Fresh reader can run `compute_indices.py` and understand the output
- Every methodology assumption explicitly documented

---

## Open methodology questions (carry forward)

- **Staleness rule** — 3 days proposed as default. Confirm via Index Committee.
- **Tier B cadence** — quarterly revenue + linear interpolation. Is this appropriate or should it be stepwise?
- **Tier B haircut differential** — Phase 10 sensitivity should inform whether 10-point vs Tier C is right.
- **Version confirmation** — we treat each versioned model as a separate constituent. Is that the intended behaviour, or should versions within a family be blended?
- **Suspension fallback** — prior-day value for MVP. Confirm vs. alternative (NaN, downstream consumer decides).

---

## Risk register

| Risk | Mitigation |
|---|---|
| Scope creep into dashboard/API territory | CLAUDE.md explicit non-goals; self-review at each phase gate |
| Mock data too idealised | Phase 3 scenarios include cases that *should* move the index |
| OpenRouter schema change mid-build | Every response cached; normaliser isolated |
| λ=3 wrong for this market | Phase 10 explicitly designed to find out |
| Tier B correlation with Tier C distorting weights | Phase 10 haircut sensitivity + decision log entry |
| TWAP ordering choice wrong | Phase 10 explicit comparison |
| Methodology ambiguities silently resolved in code | CLAUDE.md "ask first" rules; decision log every time |
| Phase 10 rushed because schedule pressure | Budgeted 3 days; do not compress |

---

## Cadence and publishing

Candidate Noble FX Monitor posts during the build:
- "How to build synthetic AI-inference pricing data that stresses an institutional benchmark" (post Phase 2–3)
- "Why we chose exponential median-distance weighting over trimmed mean" (post Phase 5a)
- "Revenue-anchored volume proxies: the Tier B problem in an opaque market" (post Phase 5b)
- "What OpenRouter tells us about the AI inference cost curve" (post Phase 4)
- "TWAP-then-weight vs weight-then-TWAP: does the ordering matter?" (post Phase 10)
- "Calibrating λ: the volatility vs manipulation-resistance tradeoff" (post Phase 10)
- "Does a 10-point haircut between Tier B and Tier C matter empirically?" (post Phase 10)

Noble FX Monitor content lives here. Don't lose the posts.
