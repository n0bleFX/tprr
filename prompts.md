# TPRR MVP — Prompts for Claude Code

A sequenced library of prompts for driving Claude Code (VS Code extension) through the build. Starting points, not scripts — adapt as work reveals surprises.

---

## How to use this file

1. **Open project in VS Code with Claude Code extension active.** Confirm Claude Code sees `CLAUDE.md` at repo root.
2. **Work phase by phase.** Don't jump ahead — each phase builds on prior artefacts.
3. **Per phase**: use `setup`, then `main`, then `verify` / `close out`. Use `troubleshoot` when stuck.
4. **Copy-paste is fine**, but read each prompt first. You know details Claude Code doesn't.
5. **On methodology questions**, don't let Claude Code improvise — use prompt M.1.

If Claude Code seems to have forgotten conventions mid-session: "Before we continue, re-read `CLAUDE.md` and confirm you understand the non-goals, the dual-weighted formula, and TWAP-then-weight ordering."

---

## Pre-flight

### P.1 — Initial orientation

```
Read CLAUDE.md, project_plan.md, and docs/tprr_methodology.md. Confirm understanding by answering four questions briefly (two sentences each):

1. What single question does this repo exist to answer?
2. Why is exponential median-distance weighting the principal manipulation control (as opposed to the slot-level quality gate)?
3. What's the difference between TPRR-F and TPRR-B, and why do derivative instruments never reference TPRR-B?
4. Why did we choose TWAP-then-weight over weight-then-TWAP, and what does Phase 10 do about that choice?

Do NOT start writing code. Do not propose a plan. Just confirm understanding.
```

### P.2 — Environment check

```
Check:
1. Python version available (need 3.11+)
2. Is uv installed?
3. Is git installed and the repo clean?

Report findings. Do not install anything yet.
```

---

## Phase 0 — Project setup

### 0.1 — Scaffold

```
Scaffold the project per the directory structure in CLAUDE.md. Create:

- All directories under src/tprr/ with empty __init__.py files
- config/, data/{raw,processed,indices}/, docs/{findings/}, notebooks/, tests/, scripts/
- pyproject.toml with dependencies from CLAUDE.md's tech stack, targeting Python 3.11+
- .gitignore: Python artifacts, .venv, data/raw/, *.db, .DS_Store
- README.md — 15 lines max: what this is, uv sync, uv run pytest
- tests/test_smoke.py with one passing test
- docs/decision_log.md stub with header + "## 2026-04-22 — Project initialised"
- docs/findings/README.md stub
- Empty docs/tprr_methodology.md — I'll paste canonical content myself

Do NOT:
- Write application code yet
- Create config YAML files yet
- Add license, CI, deployment configs
- Add CONTRIBUTING.md, CODEOWNERS, .editorconfig, pre-commit hooks
```

### 0.2 — Verify

```
Run:
1. uv sync
2. uv run pytest
3. uv run ruff check .
4. uv run mypy src/

All must exit 0. If uv isn't installed, tell me the install command rather than falling back to pip.
```

### 0.3 — Close out

```
Add entry to docs/decision_log.md under today's date summarising:
- Python version chosen
- uv vs alternatives
- Dependency pinning strategy

Commit: "Phase 0: project scaffold".
```

---

## Phase 1 — Schema and config

### 1.1 — Canonical schemas

```
Implement src/tprr/schema.py per CLAUDE.md data contracts:

- PanelObservation (pydantic)
- ChangeEvent (pydantic)  — NEW: intraday price change record
- IndexValue (pydantic)
- Tier: str enum — TPRR_F, TPRR_S, TPRR_E
- AttestationTier: str enum — A, B, C
- PanelObservationDF, ChangeEventDF, IndexValueDF — pandas validators (column + dtype + non-null)

tests/test_schema.py:
- Rejects missing required fields
- Rejects out-of-range tier codes
- Accepts valid rows
- Validates a well-formed DataFrame; rejects malformed

Do NOT:
- Add fields beyond CLAUDE.md — if you think something is missing, ASK
- Use pandera (pydantic + pandas checks are enough)
- Mix dataclasses and pydantic — pick pydantic
```

### 1.2 — Config loaders

```
Implement src/tprr/config.py with:

- IndexConfig (pydantic): lambda_ (default 3.0), base_date (default 2026-01-01), backtest_start (default 2025-01-01), quality_gate_pct (0.15), continuity_check_pct (0.25), min_constituents_per_tier (3), staleness_max_days (3), tier_haircuts (dict: A=1.0, B=0.9, C=0.8), twap_window_utc ([9, 17]), twap_slots (96), default_ordering ("twap_then_weight")
- ModelMetadata: constituent_id, tier, provider, canonical_name, baseline_input_price_usd_mtok, baseline_output_price_usd_mtok, openrouter_author (optional), openrouter_slug (optional), active_from (date, optional), active_until (date, optional)
- ModelRegistry: list[ModelMetadata]
- ContributorProfile: contributor_id, profile_name, volume_scale (enum), price_bias_pct, daily_noise_sigma_pct, error_rate, covered_models (list[str])
- ContributorPanel: list[ContributorProfile]
- TierBRevenueEntry: provider, period (str like "2025-Q1"), amount_usd, source
- TierBRevenueConfig: list[TierBRevenueEntry] + get_provider_revenue(provider, date) with linear interpolation
- Functions: load_index_config(), load_model_registry(), load_contributors(), load_tier_b_revenue(), load_scenarios(), load_all()

tests/test_config.py:
- Valid YAML → typed objects
- Missing required fields → clear error
- Covered models not in registry → load_all() raises
- Defaults apply when optional fields omitted
- get_provider_revenue interpolates between quarterly entries
```

### 1.3 — Seed config files

```
Create all config files per project_plan.md Phase 1. Before writing model_registry.yaml:

1. Summarise the 15 models, their tiers, and baseline output prices in a table. I want to eyeball this before it's committed because these numbers anchor everything downstream.

2. After I approve, write model_registry.yaml, contributors.yaml, and index_config.yaml.

3. Write config/tier_b_revenue.yaml as a STUB with the provider structure present but no revenue data populated yet (we'll populate in Phase 4b). Include a comment at the top explaining the structure.

4. Write config/scenarios.yaml as a STUB — we'll populate in Phase 3.

Do NOT:
- Invent models not in the project_plan proposal
- Add fields not in the schemas
- Populate Tier B revenue with made-up numbers yet
```

### 1.4 — Close out

```
Verify:
1. uv run python -c "from tprr.config import load_all; cfg = load_all(); print(f'{len(cfg.model_registry)} models, {len(cfg.contributors)} contributors')"
2. uv run pytest
3. uv run mypy src/

Add decision log entry summarising: tier haircuts, λ default, base date choice (Jan 1 2026), backtest start (Jan 1 2025), TWAP window (09:00-17:00 UTC, 96 slots), default ordering (twap_then_weight).

Commit: "Phase 1: canonical schema and config".
```

---

## Phase 2a — Mock panel: daily baselines

### 2a.1 — Pricing baselines

```
Implement src/tprr/mockdata/pricing.py.

Requirements:
- Function: generate_baseline_prices(model_registry, start_date, end_date, seed) -> DataFrame with [date, constituent_id, baseline_input_price_usd_mtok, baseline_output_price_usd_mtok]
- For each model:
  - Start from registry baseline
  - Gradual downward drift (models cheaper over time)
  - Step-downs: frontier 10–30% every 90–180 days; efficiency 20–50% more frequent
  - Drift magnitude tier-appropriate (frontier stable, efficiency volatile)
- Positive, finite, float64
- Seeded (every random draw through seeded numpy Generator)
- Start date: 2025-01-01. End date: today.
- No contributor-level noise here (Phase 2a.2)

tests/test_mockdata_pricing.py:
- Output shape is (n_days × n_models) rows, 4 columns
- All prices > 0
- Seeded determinism
- Different seeds → different output
- First day's price ≈ registry baseline
- Mean trend is downward per model over full window

Do NOT:
- Add INFO-level logging (use DEBUG)
- Introduce hidden randomness
- Read files directly — take registry as argument
```

### 2a.2 — Contributor submissions

```
Implement src/tprr/mockdata/contributors.py.

Requirements:
- Function: generate_contributor_panel(baseline_prices, contributor_panel, seed) -> DataFrame matching PanelObservationDF
- Per (contributor, model) in covered_models:
  - Pull baseline for that date
  - Apply contributor's price_bias_pct (systematic)
  - Apply daily_noise_sigma_pct (Gaussian)
  - attestation_tier = "A"
  - source = "contributor_mock"
  - volume_mtok_7d: not yet populated (2a.3)
- Seeded, deterministic

tests/test_mockdata_contributors.py:
- Coverage: contributors only have rows for their covered_models
- High-bias contributor's mean price > low-bias contributor's
- Per-contributor price std matches configured noise (within tolerance)
- Seeded determinism

Do NOT:
- Add "realistic" features not asked for (weekends, holidays)
- Use global random — seeded Generator passed in
```

### 2a.3 — Volumes

```
Implement src/tprr/mockdata/volume.py.

Requirements:
- Function: generate_volumes(panel_df, contributor_panel, seed) -> panel_df with volume_mtok_7d populated
- Base scale per contributor: low=0.1M/day, medium=1M, high=10M, very_high=100M
- Correlated across models within contributor (multiplicative factor moves together)
- Gradual growth / contraction per contributor
- volume_mtok_7d = trailing 7-day sum (expanding window at start)
- Non-negative, seeded

tests:
- Volumes ≥ 0
- 7d trailing sum matches manual spot check
- very_high > low systematically
- Determinism

Do NOT:
- Try to model realistic market share — plausibility is the goal, not accuracy.
```

### 2a.4 — Orchestration

```
Implement scripts/generate_mock_data.py (first cut — will extend in Phase 2b and 3):

- CLI args: --start (ISO date, default 2025-01-01), --end (ISO, default today), --seed (int, default 42), --output-dir (default data/raw)
- Calls: load_all() → generate_baseline_prices → generate_contributor_panel → generate_volumes
- Writes data/raw/mock_panel_clean_seed{seed}.parquet
- Prints summary: rows, date range, unique contributors, unique models, mean price by tier, mean volume by contributor

Do NOT:
- Add progress bars
- Write multiple output files in one run
```

### 2a.5 — Close out

```
Run:
  uv run python scripts/generate_mock_data.py --start 2025-01-01

Expected: ~480 days × ~10 contributors × ~8 covered models ≈ 38K rows.

Show me notebooks/02a_explore_baseline.ipynb with:
1. Load parquet, print shape and head
2. Plot baseline prices for one model per tier (3 lines, full backtest)
3. Plot per-contributor price deviation from baseline for one model

I need to eyeball this before we build on top. Looking for: plausible drift shapes, tier-appropriate volatility, contributor bias visible in plot 3.

Commit after I approve: "Phase 2a: mock panel daily baselines".
```

---

## Phase 2b — Mock panel: intraday change events

### 2b.1 — Change event generator

```
Implement src/tprr/mockdata/change_events.py.

Requirements:
- Function: generate_change_events(panel_df, registry, contributor_panel, seed) -> DataFrame matching ChangeEventDF
- For each (contributor, model) pair:
  - Frontier: ~4–6 changes/year
  - Standard: ~6–10/year
  - Efficiency: ~10–20/year
  - Exact count drawn from Poisson around tier mean
- On each change day:
  - Slot-of-day drawn from business-hours-weighted distribution (Gaussian centred at slot 24 ≈ 11:00 UTC, σ=12 slots, truncated to [0, 95])
  - change_slot_idx is the integer slot index
  - old_price = prior day's posted price for that (contributor, model)
  - new_price = current day's posted price
  - reason = "baseline_cut" for step-downs, "drift_correction" otherwise
- Output: one row per change event

Also: update the panel generation so that on change-event days, the panel's output_price_usd_mtok reflects the daily TWAP (accounting for where in the day the change happened), NOT just the post-change price. This keeps panel observations semantically "the daily reference price" for downstream gate/weighting use.

Wait. Let me think again: per CLAUDE.md, the panel's price field on change-event days is the daily TWAP. Implement that: if there's a change event at slot S, the TWAP = (S × old + (96-S) × new) / 96. Panel output_price_usd_mtok = that TWAP.

tests/test_change_events.py:
- Event frequency per tier within expected range across the full backtest
- Time-of-day distribution matches spec (slot indices cluster around 24)
- Each event references a valid (contributor, constituent, date)
- Change causes panel posted price to shift meaningfully between day-before and change-day
- Seeded determinism

Do NOT:
- Skip change events on weekends — providers deploy any day
- Allow change_slot_idx outside [0, 95]
- Create change events without a corresponding panel row
```

### 2b.2 — Extend orchestration

```
Extend scripts/generate_mock_data.py:
- Runs change_events generation after panel generation
- Writes data/raw/mock_change_events_clean_seed{seed}.parquet
- Updates the panel parquet to reflect the TWAP-on-change-days adjustment

After: regenerate mock data from scratch.
```

### 2b.3 — Close out

```
Show me notebooks/02b_change_events_check.ipynb with:
1. Histogram of change events per (contributor, model) pair over full backtest
2. Distribution of change_slot_idx (time-of-day)
3. For one (contributor, model) pair with ≥3 events: plot posted price over time with change events marked

I need this to look realistic before we trust it downstream. Red flags:
- Wildly variable event counts per pair
- Time-of-day distribution flat or wrong-shaped
- Posted prices that don't visibly step at change events

Commit after approval: "Phase 2b: intraday change events".
```

---

## Phase 2c — TWAP reconstructor

### 2c.1 — Implement TWAP reconstruction

```
Implement src/tprr/twap/reconstruct.py.

Functions:
- reconstruct_slots(contributor_id: str, constituent_id: str, date: date, panel_df: DataFrame, change_events_df: DataFrame, price_field: str = "output_price_usd_mtok") -> np.ndarray of shape (96,)
  - If no change event for this (contributor, constituent, date): all 96 slots = panel's posted price
  - If change event at slot S: slots [0, S) = old_price, slots [S, 96) = new_price
  - The panel's stored price on change-event days IS the TWAP, so extract the pre- and post-change prices from the ChangeEvent record, not the panel
- compute_daily_twap(slot_prices: np.ndarray[96], excluded_slots: set[int] | None = None) -> float
  - Arithmetic mean of surviving slots
  - All slots excluded → raise with clear message
- compute_panel_twap(panel_df, change_events_df, excluded_slots_df: DataFrame | None = None) -> panel_df_with_twap_columns
  - Adds twap_output_usd_mtok and twap_input_usd_mtok columns
  - Symmetric for input and output

tests/test_twap_reconstruct.py:
- Constant prices (no change events) → TWAP = that price
- Change at slot 48 → TWAP = (old + new) / 2 (exact)
- Change at slot 0 → TWAP = new price exactly
- Change at slot 95 → TWAP = (95×old + 1×new) / 96
- Exclusions reduce denominator
- All 96 excluded → raises
- Property test (hypothesis): TWAP is monotone in change_slot_idx (higher slot → TWAP closer to old)
- Property test: for any (contributor, constituent, date) with no change event, twap_output == output_price from panel to floating tolerance
```

### 2c.2 — Close out

```
Show me:
1. Test run results
2. An example manual computation I can eyeball: for (contrib_alpha, openai/gpt-5-pro, some change-event date), what are the 96 slot prices and what's the TWAP? Print the first 5, the slot-of-change, and last 5 slots, and the resulting TWAP. I want to see the structure.

Add decision log entry on:
- TWAP-then-weight ordering choice (referenced to methodology section)
- The sparse change-events storage model (instead of 96× rows/day) — this is a design choice worth recording
- The fact that panel's output_price_usd_mtok represents daily TWAP on change-event days, not the post-change price

Commit: "Phase 2c: TWAP reconstructor".
```

---

## Phase 3 — Outlier injection scenarios

### 3.1 — Scenario framework

```
Implement src/tprr/mockdata/outliers.py per project_plan.md Phase 3.

Each scenario is a function: apply_{scenario_name}(panel_df, change_events_df, params: dict, seed: int) -> (panel_df, change_events_df)

All scenarios:
- Operate on copies
- Take (panel, change_events, params, seed) — no config reads inside
- Populate the `notes` column on affected panel rows OR the `reason` field on change events
- Scenarios 1, 2, 9 (fat-finger, intraday spike) inject CHANGE EVENTS within the day — not daily panel changes
- Scenarios 3, 4 (stale quote, blackout) modify panel rows (or omit them)
- Scenarios 5, 6, 8 (shock, manipulation, new launch) modify panel daily prices
- Scenario 7 (tier reshuffle) is a config change — implement as a date-triggered override

Nine scenarios:
1. fat_finger_high: one slot at 10× price (via a momentary change event + reversion)
2. fat_finger_low: one slot at 1/10× price
3. stale_quote: contributor's panel price doesn't update for N days while baseline moves
4. contributor_blackout: contributor has no panel rows for N days
5. shock_price_cut: one (contributor, model) drops 50% on specified date, stays low
6. sustained_manipulation: contributor prices X% above median for N days
7. tier_reshuffle: model moves tiers from specified date
8. new_model_launch: model added mid-period, panel rows begin on launch date
9. intraday_spike: one (contributor, model) has a change event that's off-market for M slots, then reverts in the same day

tests/test_outliers.py:
- Each scenario independently tested on fixture data
- Clean baseline is bitwise equal after any scenario (we copy, not mutate)
- Deterministic given seed
- Affected rows have notes populated
```

### 3.2 — Config + runner

```
Populate config/scenarios.yaml with one instance of each scenario type, using reasonable params. Scenarios pointing to specific dates within the backtest window (Jan 2025 – today).

Extend scripts/generate_mock_data.py:
- Add --scenarios flag taking a YAML path
- When provided: applies scenarios to the clean panel + change_events, produces scenario files
- Output: data/raw/mock_panel_{scenario_set}_seed{seed}.parquet + matching change_events file
- Clean baseline always regenerated first

tests:
- Running with scenarios produces both clean and scenario files
- Scenario file differs from clean file in expected ways (spot-check 2 scenarios)
```

### 3.3 — Close out

```
Run scenarios on the full 480-day panel. Show me notebooks/03_scenario_spotcheck.ipynb with one plot per scenario:
- Clean vs scenario (prices and, for intraday scenarios, slot reconstructions) near the injection window
- Visual confirmation that the injection is present and correctly shaped

Before commit, show me these plots. I want to confirm each looks like its methodology description.

Decision log entries:
- Staleness rule (3 days) — methodology gap, this is our default
- Each scenario's default parameters
- The sparse storage model implication: intraday outliers are change events, not panel modifications

Commit: "Phase 3: outlier injection framework".
```

---

## Phase 4 — OpenRouter integration

### 4.1 — API client

```
Implement src/tprr/reference/openrouter.py per CLAUDE.md OpenRouter rules.

- fetch_models() → GET /api/v1/models
- fetch_model_endpoints(author, slug) → GET /api/v1/models/{author}/{slug}/endpoints
- fetch_rankings() → GitHub mirror latest.json + dated snapshot
- Every response cached to data/raw/openrouter/{kind}/{YYYY-MM-DD}.json
- Cache hit returns cached content (no HTTP)
- httpx client, 30s timeout, single retry on 5xx
- User-Agent: "Noble-Argon-TPRR/0.1 research"

tests/test_openrouter_client.py (use httpx MockTransport):
- Cache hit returns cached without request
- Cache miss makes request, populates cache
- Malformed response → clear error (not silent pass)

Do NOT:
- Add API key / auth logic — these endpoints are public
- Exceed one retry
- Fetch endpoints outside these three
```

### 4.2 — Normaliser

```
Extend src/tprr/reference/openrouter.py:

- normalise_models_to_panel(models_json, model_registry, as_of_date) -> DataFrame matching PanelObservationDF
  - Match OR models to registry via (openrouter_author, openrouter_slug)
  - Unmatched → skip, INFO log
  - Prices × 1e6 ($/token → $/Mtok)
  - contributor_id = "openrouter:aggregate"
  - attestation_tier = "C"
  - source = "openrouter_models"
  - volume_mtok_7d = 0 initially
- normalise_endpoints_to_panel(endpoints_json, constituent_id, as_of_date) -> DataFrame
  - One row per hosting provider: contributor_id = f"openrouter:{provider_slug}"
  - Same conversions
- enrich_with_rankings_volume(panel_df, rankings_json) -> panel_df with populated volume

tests:
- Sample JSON → expected rows
- Known $/token → correct $/Mtok
- Unmatched models skipped, not raised
- Endpoints produce distinct contributor_ids per provider
```

### 4.3 — Script

```
Implement scripts/fetch_openrouter.py:
- Fetches all three sources
- Normalises to panel schema
- Writes data/raw/openrouter_panel_{YYYY-MM-DD}.parquet
- Prints summary: N constituents matched, N unmatched, mean output price by tier

Then notebooks/04_openrouter_sanity_check.ipynb:
- Distribution of output prices by tier (should approximately match mock baselines)
- Provider-level price dispersion per constituent (box plot, per constituent with ≥3 providers)
```

### 4.4 — Close out

```
Run the script. Show me summary output + notebook charts before commit.

Key check: do OpenRouter prices land near our mock baselines? If drastically off, the registry baselines need revision. Don't silently continue with mismatched data.

Decision log:
- Which OR models matched to which registry entries
- Volume-derivation assumption from rankings (current snapshot as static proxy for full backtest — this is a flagged MVP limitation)
- Any discrepancies between OR and mock baselines (and how you handled them)

Commit: "Phase 4: OpenRouter integration".
```

---

## Phase 4b — Tier B revenue config

### 4b.1 — Populate revenue data

```
Populate config/tier_b_revenue.yaml with quarterly provider revenue data for Jan 2025 – current quarter.

For each provider with multiple models in the registry (OpenAI, Anthropic, Google, Meta, DeepSeek, Alibaba):
- Collect publicly available quarterly or annualised API revenue
- Sources: reported earnings, analyst triangulations (Menlo, The Information, reported coverage)
- Each entry requires a `source` field labeling it: "reported", "analyst_triangulation", "synthetic_for_mvp"
- For providers without any public revenue data: use synthetic numbers with source="synthetic_for_mvp"

Use web search tools if available to find current public figures. Where numbers are uncertain, use a defensible ballpark and label as analyst_triangulation with the source cited.

Draft the file content for me to review BEFORE writing it. I want to eyeball the numbers and sources.
```

### 4b.2 — Close out

```
After I approve the revenue figures, write config/tier_b_revenue.yaml.

Add decision log entry:
- Tier B implementation approach (Option B: revenue-anchored, OpenRouter-split)
- Revenue data sources cited for each provider
- Synthetic-for-MVP flag for any gaps
- Known weakness: partial correlation with Tier C via OpenRouter within-provider split
- Phase 10 will run haircut sensitivity to test whether the 10-point differential (90% vs 80%) is empirically justified

Commit: "Phase 4b: Tier B revenue configuration".
```

---

## Phase 5a — Weighting module

### 5a.1 — w_vol and w_exp

```
Implement src/tprr/index/weights.py per project_plan.md Phase 5a.

Pure functions (no pandas inside math):
- volume_weight(volume_mtok: float, attestation_tier: str, config: IndexConfig) -> float
- exponential_weight(price: float, tier_median: float, lambda_: float) -> float
  - Returns exp(-lambda_ * abs(price - tier_median) / tier_median)
- compute_tier_median(prices: list[float] | np.ndarray) -> float
- compute_dual_weights(panel_day_df: DataFrame, config: IndexConfig) -> DataFrame with added columns w_vol, w_exp, w_combined

Use the table in CLAUDE.md as test fixtures:
- At 0% distance: w_exp = 1.000 (exact)
- 5% → 0.861
- 10% → 0.741
- 20% → 0.549
- 30% → 0.407
- 50% → 0.223
- 100% → 0.050

All to 3 decimal places at λ=3.

Hypothesis property tests:
- exp_weight monotonic non-increasing in |price - median|
- exp_weight symmetric around median
- volume_weight linear in volume
- exp_weight ∈ (0, 1] for positive λ

Do NOT:
- Add log-space numerical tricks
- Coerce negative prices to zero — raise
- Use scipy just for exp — numpy is enough
```

### 5a.2 — Close out

```
Verify: given 5 prices [20, 22, 23, 25, 50] with median 23, compute w_exp at λ=3 for each:
- 20: distance 13.0%, w_exp ≈ ?
- 22: distance 4.3%, w_exp ≈ ?
- 23: distance 0%, w_exp = 1.0
- 25: distance 8.7%, w_exp ≈ ?
- 50: distance 117%, w_exp ≈ ?

Print these. I want to eyeball that they match expectations.

Decision log entry noting λ default (3.0) and reference to methodology Section 3.3.3.

Commit: "Phase 5a: weighting module".
```

---

## Phase 5b — Tier B derivation

### 5b.1 — Implementation

```
Implement src/tprr/index/tier_b.py.

Function: derive_tier_b_volumes(as_of_date, panel_df, openrouter_rankings_df, tier_b_revenue_config, model_registry) -> DataFrame

Algorithm (Option B per 2026-04-22 decision):
1. Group registry models by provider (e.g., openai → all openai/* models)
2. For each provider:
   a. Get disclosed revenue for as_of_date via tier_b_revenue_config.get_provider_revenue (interpolates between quarterly entries)
   b. Get OpenRouter share for each of that provider's models (from rankings)
   c. Compute provider-weighted reference output price: Σ(model_price × or_share) / Σ(or_share) — weighted average
   d. Implied provider token volume (output) = (revenue / reference_price) × 1e6 — expressed in Mtok per period, then normalised to daily (divide by days-in-period)
   e. Allocate across provider's models by OR within-provider share: model_volume = implied_provider_volume × model_or_share / Σ(or_share)
   f. Scale: compute Σ(model_volume × model_price) for the provider, compare to disclosed revenue; if mismatch, normalise volumes by ratio
3. Output one row per (provider, model, as_of_date):
   - attestation_tier = "B"
   - source = "tier_b_derived"
   - volume_mtok_7d populated (or equivalent derived daily volume × 7)
   - model prices from panel

Run this monthly (first day of each month in backtest), then forward-fill within the month for daily use. Not daily — revenue data doesn't support that granularity.

tests/test_tier_b.py:
- Sum of (allocated_volume × model_price) ≈ disclosed_revenue (within tolerance)
- Missing provider → no Tier B rows emitted (fall-through to Tier C)
- Missing OpenRouter coverage for a model → skipped with warning
- Determinism: same inputs → same outputs
```

### 5b.2 — Integrate into weighting

```
Update src/tprr/index/weights.py compute_dual_weights to respect tier preference:
- For each (constituent, date):
  - If ≥3 Tier A contributors exist → use Tier A (contributor-level panel rows, aggregated)
  - Else if Tier B row exists for (provider, model, date) → use Tier B
  - Else → use Tier C (OpenRouter rankings-derived)
- Record chosen tier in the output row's attestation_tier field
- Apply the appropriate haircut from config.tier_haircuts

Tests:
- Constituent with 4 Tier A contributors → Tier A chosen
- Constituent with 2 Tier A + Tier B available → Tier B chosen
- Constituent with 0 Tier A + 0 Tier B + Tier C available → Tier C chosen
- Constituent with no tier data → no weighted row (downstream handles)
```

### 5b.3 — Close out

```
Verify: for one constituent that has all three tiers available on a date, show me:
- The Tier A panel rows (volume, contributors)
- The Tier B derivation (provider revenue, OR share, derived volume)
- The Tier C ranking volume

And: which tier did compute_dual_weights select, why, and what's the final w_vol?

I want to see this end-to-end before we plug it into aggregation.

Decision log:
- Tier B monthly cadence + forward-fill within month
- Tier preference order (A > B > C)
- What happens when a constituent has 1 or 2 Tier A contributors (Tier B fallback, not partial aggregation — confirm this)

Commit: "Phase 5b: Tier B revenue-anchored derivation".
```

---

## Phase 6 — Slot-level quality gate

### 6.1 — Implement

```
Implement src/tprr/index/quality.py per project_plan.md Phase 6.

Functions:
- apply_slot_level_gate(panel_df, change_events_df, trailing_window=5, deviation_pct=0.15) -> DataFrame
  - For each (contributor, constituent, date): compute trailing 5-day average posted price (daily, excluding current day)
  - Reconstruct 96 slots for that (contributor, constituent, date) via twap.reconstruct_slots
  - Compare each slot to trailing average
  - Return DataFrame of excluded slots: columns (contributor_id, constituent_id, date, slot_idx)
  - Also flag: if any slot fails on a given day, record the (contributor, constituent, date) as a "day with gate fires"
  - Track consecutive-day fires per (contributor, constituent); 3 consecutive → suspension flag
- apply_continuity_check(panel_df, pct=0.25) -> panel_df with continuity_flag column
- apply_staleness_rule(panel_df, max_stale_days=3) -> panel_df with is_stale column
- check_min_constituents(panel_day_df, tier: str, min_n=3) -> bool

Key behaviours:
- Trailing average: shift(1) before rolling(5).mean() to exclude current day
- First 5 days of each (contributor, constituent) series: no gate applied
- Suspension is sticky for MVP (once flagged, stays flagged); production would have manual clear
- Slot-level gate only excludes FAILING SLOTS, not whole days (unless all 96 fail)

tests/test_quality.py:
- Edge: 14.99% passes, 15.01% fails
- 3 consecutive fires → suspension; 2 then 1 pass → count resets, no suspension
- First 5 days: gate not applied (no history)
- Stale 2-day-old ok, 4-day-old stale
- Continuity: 26% → flagged, 24% → not flagged
- On a change-event day: only the slots corresponding to the off-market price window fail (if any); slots at the in-market price pass

Do NOT:
- Drop rows when gates fail — flag; aggregation decides
- Use rolling() without excluding current day
```

### 6.2 — Close out

```
Decision log entries:
- Staleness rule (3 days) — methodology gap
- First-5-days-excluded-from-gate rationale
- Sticky suspension choice (vs transient)
- Slot-level gate firing pattern on change-event days

Commit: "Phase 6: slot-level quality gate".
```

---

## Phase 7 — Aggregation and end-to-end compute

### 7.0 — Pre-implementation methodology check

```
Before implementation, confirm understanding of the pipeline for a single day. Answer based on CLAUDE.md, methodology, and previous phases. If uncertain, ASK — don't guess.

1. Exact pipeline order: (a) quality gate on slots, (b) compute daily TWAP per (contributor, constituent) excluding failed slots, (c) determine tier for each constituent (A/B/C), (d) compute tier median using only active constituents' TWAPs, (e) compute w_exp and w_vol per constituent, (f) weighted aggregation. Correct?
2. If all 96 slots for (contributor, constituent) fail the gate, that (contributor, constituent) is excluded from the day — NOT the entire constituent. Correct?
3. For the tier median: use the TWAPs of ACTIVE constituents (those with ≥1 valid slot → valid daily TWAP). Exclude constituents with all slots failed. Correct?
4. For TPRR-B: same pipeline but using blended (0.25×out + 0.75×in) as the "price" in all aggregation steps. Correct?
5. For FPR/SER: computed AFTER core indices are rebased to 100, or using raw $/Mtok values? The methodology implies raw since it's a ratio, but base-100 ratios would give the same number. Confirm.
6. Suspended tiers (< 3 active constituents): use prior day's index level as the fallback. Correct?
7. Rebase: all core and B indices set to 100 on 2026-01-01. FPR/SER are raw ratios (not rebased). Correct?

I'll respond before you start writing.
```

### 7.1 — Aggregation

```
Implement src/tprr/index/aggregation.py and src/tprr/index/compute.py per project_plan.md Phase 7.

aggregation.py:
- compute_tier_index_twap_then_weight(panel_day_df, change_events_df, tier_b_volumes_df, config, excluded_slots_df) -> dict
  - Apply quality gate → excluded slots
  - Compute daily TWAP per (contributor, constituent) excluding failed slots
  - Identify active constituents (≥1 valid slot OR equivalently, has non-NaN daily TWAP)
  - If active_count < min_constituents → return suspended dict with prior value marker
  - Compute tier median across active constituents' TWAPs
  - Determine tier for each active constituent (A/B/C) + apply haircut
  - Compute w_exp per constituent
  - Compute w_combined = w_vol × w_exp
  - Return: {raw_value_usd_mtok, index_level (set later), n_constituents, n_constituents_active, tier_a_weight_share, tier_b_weight_share, tier_c_weight_share, suspended: false, notes}
- compute_tier_index_weight_then_twap(...) — stubbed for Phase 10 comparison; for now, leave body as NotImplementedError with a TODO pointing to Phase 10

compute.py:
- run_full_pipeline(config, panel_df, change_events_df, tier_b_df, openrouter_df, version, ordering) -> indices_df
- Handles suspension fallback (use prior valid value)
- Rebases core/B indices to 100 at base_date (config.base_date)
- Returns long-format DataFrame

src/tprr/index/versions/v0_1/__init__.py: imports and re-exports the compute_tier_index function path — freezes v0.1 behaviour

tests/test_compute_end_to_end.py:
- 30-day synthetic panel → 30 × 3 core tier-days
- F > S > E on all days
- Hand-compute one day manually; code matches
- Suspension test: remove all but 2 constituents for a tier-day → suspension + prior-day fallback
- Determinism: byte-identical across two runs
```

### 7.2 — Rebase + storage

```
In compute.py:
- rebase_to_100(indices_df, base_date) — sets index_level = 100 × raw_value / raw_value_at_base_date for core and B indices
- FPR/SER: not rebased (ratios)

src/tprr/storage/db.py:
- SQLAlchemy 2.x models matching IndexValue schema
- write_indices(indices_df, db_path) with upsert on (as_of_date, index_code, version, ordering)
- read_indices(db_path, filters) returns DataFrame

scripts/compute_indices.py:
- CLI args: --panel-input, --change-events-input, --openrouter-input, --tier-b-config, --version (default v0_1), --lambda (default from config), --ordering (default twap_then_weight), --output-db (default data/indices/tprr.db)
- Runs pipeline, rebases, writes to parquet + SQLite
- Summary output
```

### 7.3 — Close out

```
Run on full backtest (~480 days). Show me:
- Summary output
- First/last 5 rows of indices DataFrame
- Quick matplotlib line chart of three core indices over time

I want to eyeball before proceeding. Red flags:
- Unexpected step-changes
- Volatility inconsistent with underlying price drift
- Ratios (F/S, S/E) with implausible moves
- Unexpected suspension firings

Report anything unusual, even if you're not sure whether it's a problem.

Decision log:
- Suspension fallback choice (prior day)
- Rebase base date behaviour
- Version naming
- Pipeline order confirmation (per 7.0 answers)

Commit after approval: "Phase 7: aggregation and full compute pipeline".
```

---

## Phase 8 — Derived indices

### 8.1 — FPR, SER, B

```
Implement src/tprr/index/derived.py per project_plan.md Phase 8.

- compute_fpr(indices_df) — TPRR_F / TPRR_S per date (raw values, not rebased)
- compute_ser(indices_df) — TPRR_S / TPRR_E per date (raw values)
- compute_tprr_b(panel_df, change_events_df, tier_b_df, openrouter_df, config) — runs the full dual-weighted aggregation but using blended price (twap_input × 0.25 + twap_output × 0.75) in place of twap_output. Produces TPRR_B_F, TPRR_B_S, TPRR_B_E.
  - Rebased to 100 at base_date (matches core index convention)

Update scripts/compute_indices.py to compute derived indices after core.

Tests:
- FPR(t) = F(t) / S(t) to floating tolerance
- SER(t) = S(t) / E(t)
- TPRR_B_F should be LOWER than TPRR_F in raw $/Mtok terms (because input prices are typically well below output, and B weights input 75%) — verify; if wrong, there's a unit error somewhere
- No NaN/inf except where numerator or denominator is NaN
```

### 8.2 — Close out

```
Verify DB contains all 8 series: TPRR_F, TPRR_S, TPRR_E, TPRR_FPR, TPRR_SER, TPRR_B_F, TPRR_B_S, TPRR_B_E.

Commit: "Phase 8: derived indices (FPR, SER, B)".
```

---

## Phase 9 — Visualization

### 9.1 — Plotly chart

```
Implement src/tprr/viz/charts.py.

Function plot_tprr_dashboard(indices_df, output_path):
- Top row: 3 subplots for F, S, E — index_level over time, base date annotated
- Middle row: 2 subplots for FPR, SER (raw ratios)
- Bottom: TPRR_B_F overlaid on TPRR_F for comparison
- Title: "TPRR Index — v0.1 Backtest"
- Subtitle: f"Synthetic contributor data · OpenRouter Tier C reference · Methodology v1.2 · λ={lambda_} · Ordering: {ordering} · Base date {base_date}"
- Clean institutional look: dark-on-light, thin lines, subtle grid

scripts/plot_indices.py: reads latest indices, writes HTML to data/indices/charts/tprr_{version}_{date}.html

Do NOT:
- Use emojis
- Add 3D or bubble charts
- Embed logos beyond title
```

### 9.2 — Close out

```
Open the HTML. Describe what you see:
- Shape of each series
- Approximate levels
- Any visible anomalies

After approval: commit "Phase 9: Plotly visualization".
```

---

## Phase 10 — Scenario + sensitivity suite

Budget 3 days. Don't rush.

### 10.1 — Scenario suite

```
Implement scripts/run_scenarios.py.

For each of the 9 scenarios from config/scenarios.yaml:
1. Ensure clean + scenario panel/change-events files exist (regenerate if needed)
2. Run indices pipeline on both (same ordering, same λ)
3. Compute difference series (scenario_level - clean_level) per tier per date
4. Produce docs/findings/scenario_{name}.md with:
   - Brief scenario description
   - Chart: clean vs scenario index (index_level on y, date on x)
   - Chart: difference series
   - Observed impact: max absolute deviation, sustained deviation, suspensions triggered
   - Interpretation: consistent with methodology claim?

Each finding standalone — Matt should be able to screen-share any one without context.
```

### 10.2 — Weight-then-TWAP implementation

```
Now implement the previously-stubbed compute_tier_index_weight_then_twap in aggregation.py.

Algorithm:
1. For each of the 96 slots in the day:
   a. For each active (contributor, constituent): get the slot's price (from reconstruct_slots)
   b. Apply slot-level quality gate (already computed in excluded_slots_df)
   c. Compute tier median over non-excluded slot-prices across constituents
   d. Compute w_exp per constituent using this slot's price and this slot's tier median
   e. w_combined = w_vol × w_exp (w_vol is daily-level, unchanged across slots)
   f. Slot-level tier index = Σ(w_combined × price) / Σ(w_combined)
2. Daily fix = arithmetic mean of the 96 slot-level tier indices (exclude slots where tier was suspended)
3. Return same dict structure as twap_then_weight variant

tests:
- Constant-price day → both orderings give same result (no change events, no outliers)
- Single change-event day → the two orderings may differ; document the difference

This is the work deferred from Phase 7.1.
```

### 10.3 — TWAP ordering comparison

```
Implement scripts/twap_ordering_comparison.py.

Run full backtest twice:
- --ordering twap_then_weight (saved as default series)
- --ordering weight_then_twap (saved as alternative series)

Analysis:
- Correlation between the two series per index
- Mean absolute difference in index_level per index
- Max difference and which date it occurred
- For max-diff date: what was different? (Change events + gate firings are the most likely driver)

docs/findings/twap_ordering.md:
- Explanation of both orderings
- Empirical comparison (charts, correlation, max-diff table)
- Interpretation: do they differ materially?
- Defence of TWAP-then-weight as default (or proposed revision)
```

### 10.4 — λ sensitivity

```
Implement scripts/lambda_sweep.py.

Sweep λ ∈ [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
- For each λ: run clean backtest + sustained-manipulation scenario
- Metrics:
  - Clean-series volatility: std of daily log returns, annualised
  - Manipulation deviation: max absolute difference between manipulated and clean

docs/findings/lambda_sensitivity.md:
- Dual-axis chart: λ on x; volatility on one y; manipulation deviation on other
- Table of values
- Commentary on tradeoff
- Recommendation: keep λ=3 or revise

Be honest. If λ=3 looks wrong empirically, say so — and propose a revised default.
```

### 10.5 — Haircut sensitivity

```
Implement scripts/haircut_sweep.py.

Spacings to test:
- default: A=1.00 / B=0.90 / C=0.80
- tighter: A=1.00 / B=0.95 / C=0.90
- looser: A=1.00 / B=0.85 / C=0.70
- null: A=1.00 / B=1.00 / C=1.00 (no differentiation)

For each: clean backtest + sustained-manipulation scenario. Metrics:
- Clean volatility
- Manipulation deviation
- Divergence of index_level from default spacing

docs/findings/haircut_sensitivity.md:
- Table + chart
- Defence paragraph: "why the default 100/90/80 spacing is justified" (or proposed revision)
- Note on correlation with Tier C (the known Option B weakness)
```

### 10.6 — Close out

```
Review all findings:
- 9 scenario markdowns
- twap_ordering.md
- lambda_sensitivity.md
- haircut_sensitivity.md

That's 12 minimum. Any additional surprising findings discovered during the sweeps should also be stubbed.

Each finding:
- Standalone readable
- Chart embedded or referenced
- Interpretation in practitioner voice
- Noble FX Monitor angle noted (one line at the bottom)

Commit individually with meaningful messages:
- "Finding: fat-finger error absorption"
- "Finding: sustained manipulation resistance"
- "Finding: λ sensitivity"
- "Finding: haircut sensitivity"
- "Finding: TWAP ordering comparison"
- etc.

Major commit: "Phase 10: scenario and sensitivity suite".
```

---

## Phase 11 — Decision log and writeup

### 11.1 — Consolidate decision log

```
Read the full repo. Ensure docs/decision_log.md has a chronological entry for every methodology decision. Cross-check this minimum set is present:

- Tier membership (15 models, F/S/E assignment)
- Baseline prices
- Contributor count and profiles
- Staleness rule (3 days)
- λ default + Phase 10 revision (if any)
- Quality gate thresholds (15% slot, 25% continuity)
- Min constituents (3)
- Suspension fallback (prior-day value)
- Tier haircuts (100/90/80) + sensitivity findings
- Blend ratio (25:75 per methodology)
- TWAP window (09:00–17:00 UTC, 96 slots)
- TWAP ordering (twap_then_weight) + comparison finding
- Tier B implementation (Option B revenue-anchored) + cadence (monthly)
- Tier preference order (A > B > C, ≥3 contributors for A)
- Base date (2026-01-01)
- First-5-days gate exclusion
- Sparse change-events storage model
- Any decisions I asked you to make autonomously

Report any gaps.
```

### 11.2 — Summary doc and README

```
Write docs/TPRR_v01_summary.md — strict one page:
- What this MVP validated
- Three headline findings
- Known limitations (numbered)
- v0.2 queue
- Production queue (TWAP real intraday polling, transaction cross-validation, Tier B analyst-grade data, FX-hedged variants)

Prose, not bullets. 400-500 words.

Then rewrite README.md:
- What this is (2 sentences)
- Install + run (4 commands)
- Links to methodology, decision log, findings
- Note on what's synthetic vs real

< 80 lines.
```

### 11.3 — MVP close out

```
Final check:
1. uv run pytest — passes
2. uv run ruff check . — clean
3. uv run mypy src/ — clean
4. uv run python scripts/compute_indices.py — runs, produces output
5. uv run python scripts/plot_indices.py — produces HTML
6. uv run python scripts/run_scenarios.py — runs
7. uv run python scripts/lambda_sweep.py — runs
8. uv run python scripts/haircut_sweep.py — runs
9. uv run python scripts/twap_ordering_comparison.py — runs

All pass.

Commit: "Phase 11: MVP complete".

Then pause. Tell me what's next. Do not start v0.2.
```

---

## Meta prompts (use whenever)

### M.1 — Methodology question

```
Before proposing an implementation, describe the methodology ambiguity:

1. What's the question?
2. Which section of docs/tprr_methodology.md is relevant?
3. 2–3 reasonable resolutions
4. Your recommendation + reasoning

I decide. Do NOT implement until I respond.
```

### M.2 — Decision log entry

```
Add entry to docs/decision_log.md under today's date:

## YYYY-MM-DD — <short title>

**Decision**: <one sentence>

**Context**: <why this came up>

**Alternatives considered**:
- Option A — <brief>
- Option B — <brief>

**Rationale**: <2–4 sentences>

**Impact**: <on index values, code, or future work>

**Methodology section**: <reference if applicable>
```

### M.3 — Finding writeup

```
Create docs/findings/<short_name>.md:

# <Title>

**TL;DR**: <one sentence>

**Setup**: <what was the experiment>

**Result**: <what you saw — include chart>

**Interpretation**: <meaning for TPRR methodology and/or AI inference pricing story>

**Caveat**: <what this finding does NOT establish>

**Noble FX Monitor angle**: <one sentence — publishable hook>

400 words max. Practitioner voice. No hedging.
```

### M.4 — Self-review before phase close

```
Before phase approval, review your own work:

1. Anything added beyond the phase prompt — why?
2. Methodology decisions made without asking — flag for review
3. Weak tests (tautological, not testing claimed behaviour) — list
4. "Ask first" items from CLAUDE.md that you did anyway
5. Uncertainties

Honest list, not defensive. Empty list? Be suspicious of yourself.
```

### M.5 — "Something feels wrong"

```
The index is behaving unexpectedly: <describe>

Before touching code, walk through the pipeline for the specific date/tier:

1. Which constituents are active?
2. Their prices, TWAPs, volumes?
3. Tier median?
4. Individual w_vol and w_exp?
5. Weighted sum?
6. Where does the unexpected behaviour enter?

Show me the numbers. Don't propose a fix yet.
```

### M.6 — Methodology gap update

```
Methodology gap identified during implementation: <describe>

Draft the paragraph(s) you'd propose adding to docs/tprr_methodology.md for version 1.3, and tell me which section.

Do NOT modify the methodology doc directly. Draft → I review → I edit.
```

### M.7 — Scope creep check

```
Review the last 6 commits. For each:
- In scope for the current phase?
- Advanced MVP success criteria?
- Would the MVP be worse without it?

Any "no/no/no" → propose to rip out.
```

---

## Appendix — Troubleshooting

### T.1 — Test failures I don't understand

```
test_<n> is failing with: <paste>

In order:
1. Read the test — is it correct?
2. Read the code — where does it diverge from expectation?
3. Show actual vs expected values
4. Propose the smallest fix that passes without breaking others

If the test is wrong, say so + propose a corrected test.
If the code is wrong, propose fix.
Don't fix and commit in one step — I review.
```

### T.2 — Unexpectedly slow

```
scripts/<n>.py takes > N seconds on the full dataset.

1. cProfile: top 5 by cumulative time
2. For each: inherent (big-O) or incidental (waste)?
3. Smallest change

Do NOT:
- Rewrite in polars/Rust
- Add caching without measurement
- Introduce parallelism — single-threaded for MVP
```

### T.3 — Claude Code went off-script

```
Review your last turn. List:
1. What I asked for
2. What you actually did
3. Delta

For each delta item: necessary? If not, revert.
```
