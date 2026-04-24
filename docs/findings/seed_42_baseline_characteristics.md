# Seed-42 Baseline Characteristics

Forensic record of what the Phase 2a.1 baseline price generator actually produced
on the canonical seed (42) over the 478-day window 2025-01-01 to 2026-04-23.
Documented so future Phase 10 findings can quickly factor out single-seed
artifacts from genuine methodology behaviour.

**Step-event totals per tier** (detected via |daily output return| > 4%): F = 20
(vs ~23.6 expected from Poisson rate × n_models × n_days/365), S = 17 (vs ~21.0),
E = 47 (vs ~39.3). F and S come in at ~85% of expected; E at ~120%. All within
Poisson sampling variance at sample sizes of 17–47, no generator bias.

**Per-model distribution within Efficiency**: `alibaba/qwen-3-6-plus` realised 13
step events vs the E-tier per-model mean of ~7.8 — roughly **1.7× the tier average**.
This is a single-seed sampling outcome of the per-(model) RNG seeded by mixing
`seed=42` with `stable_int("alibaba/qwen-3-6-plus")`. Any other seed produces a
different over/under-representation pattern across models. **Forensic note**: if
Phase 10 work surfaces qwen-related stability, manipulation, or weight-share
findings, this seed-42 over-representation is the first confound to rule out —
re-run on at least 5 alternative seeds before attributing any finding to
methodology behaviour rather than seed-specific event timing.

**Day-level clustering**: 84.1% of 478 days have zero step events across all 16
models; 0.2% (one day) have ≥3 step events; max events on any single day = 3.
Comfortably inside the >50% / <5% acceptance targets. Natural Poisson clustering,
no over-clustering symptom in the generator.

**Other notable per-model counts on seed 42**: Frontier shows wide spread (2–5
events across 6 constituents) with claude-opus-4-7, claude-sonnet-4-6, and
gemini-3-pro all at the low end (2 each). Standard's openai/gpt-5-mini sits at
the low end of S with 3 events. None of these are concerning at this sample
size — listed only to support quick triangulation when later findings reference
specific constituents.
