"""Match-rate verification against real OpenRouter /models data — Phase 4 Batch B.

One-time real fetch; cached to ``data/raw/openrouter/models/{date}.json``
via the ``fetch_models`` cache mechanism. Subsequent runs hit cache.

Goals (per Matt's Batch B spec):
  1. How many of our 16 registry models match an OpenRouter author/slug?
  2. Names of any unmatched models.
  3. For matched models: do OpenRouter prices land within 50 percent
     multiplier of registry baselines?

Uses ``date.today()`` so the cache key auto-rolls daily; cached data from
prior days is preserved as historical record.
"""

from __future__ import annotations

from datetime import date

import pytest

from tprr.config import load_all
from tprr.reference.openrouter import fetch_models, normalise_models_to_panel


@pytest.fixture(scope="module")
def real_models_panel():  # type: ignore[no-untyped-def]
    """Real OpenRouter /models response, normalised against the production registry."""
    cfg = load_all()
    models_json = fetch_models()  # cached after first call
    df = normalise_models_to_panel(
        models_json, cfg.model_registry, date.today()
    )
    return cfg, models_json, df


EXPECTED_MATCHED = {
    "openai/gpt-5-pro",
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "openai/gpt-5-nano",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-opus-4-6",
    "anthropic/claude-opus-4-7",
    "anthropic/claude-sonnet-4-6",
    "google/gemini-3-pro",
    "google/gemini-2-flash",
    "google/gemini-flash-lite",
    "deepseek/deepseek-v3-2",
    "alibaba/qwen-3-6-plus",
    "mistral/mistral-large-3",
    "xiaomi/mimo-v2-pro",
}
EXPECTED_UNMATCHED = {
    "meta/llama-4-70b-hosted",
}


def test_match_rate_fifteen_of_sixteen_per_decision_log(
    real_models_panel,
) -> None:  # type: ignore[no-untyped-def]
    """Per docs/decision_log.md 2026-04-27 ("OpenRouter coverage"): exactly
    15/16 mapped, 1/16 documented unmatched. Either number off needs
    investigation — the registry's openrouter_author/slug populations are
    audited against this expectation."""
    cfg, _, df = real_models_panel
    matched = set(df["constituent_id"])
    all_registry = {m.constituent_id for m in cfg.model_registry.models}
    unmatched = all_registry - matched

    print(f"\nMatch rate: {len(matched)}/{len(all_registry)}")
    print(f"Matched constituents: {sorted(matched)}")
    print(f"Unmatched constituents: {sorted(unmatched)}")

    assert matched == EXPECTED_MATCHED, (
        f"Matched set differs from decision-log expectation.\n"
        f"  Expected: {sorted(EXPECTED_MATCHED)}\n"
        f"  Actual:   {sorted(matched)}\n"
        f"  Missing from actual: {sorted(EXPECTED_MATCHED - matched)}\n"
        f"  Unexpected in actual: {sorted(matched - EXPECTED_MATCHED)}"
    )
    assert unmatched == EXPECTED_UNMATCHED, (
        f"Unmatched set differs from decision-log expectation.\n"
        f"  Expected: {sorted(EXPECTED_UNMATCHED)}\n"
        f"  Actual:   {sorted(unmatched)}"
    )


def test_matched_prices_within_50pct_of_registry_baselines(
    real_models_panel,
) -> None:  # type: ignore[no-untyped-def]
    """Spot-check matched models: OR price within 50 percent multiplier of baseline.

    50 percent multiplier ~= half-to-double range. Major discrepancies (more
    than 2x off either side) are flagged loudly so price-unit conversion
    or registry baselines can be revisited.
    """
    cfg, _, df = real_models_panel
    baselines = {
        m.constituent_id: m.baseline_output_price_usd_mtok
        for m in cfg.model_registry.models
    }

    discrepancies: list[tuple[str, float, float, float]] = []  # (cid, baseline, or_price, ratio)
    spot_checks: list[tuple[str, float, float]] = []

    for _, row in df.iterrows():
        cid = str(row["constituent_id"])
        baseline = baselines[cid]
        or_price = float(row["output_price_usd_mtok"])
        if baseline <= 0:
            continue
        ratio = or_price / baseline
        spot_checks.append((cid, baseline, or_price))
        if ratio < 0.5 or ratio > 2.0:
            discrepancies.append((cid, baseline, or_price, ratio))

    print("\nPrice spot-check (output, USD/Mtok):")
    print(f"  {'constituent':<35} {'baseline':>10} {'OR':>10} {'ratio':>8}")
    for cid, baseline, or_price in spot_checks[:10]:
        ratio = or_price / baseline if baseline > 0 else float("nan")
        flag = " (off)" if ratio < 0.5 or ratio > 2.0 else ""
        print(
            f"  {cid:<35} {baseline:>10.4f} {or_price:>10.4f} "
            f"{ratio:>8.2f}{flag}"
        )

    if discrepancies:
        formatted = "\n".join(
            f"  {cid}: baseline={baseline:.4f}, OR={or_price:.4f}, ratio={ratio:.2f}"
            for cid, baseline, or_price, ratio in discrepancies
        )
        print(f"\nDiscrepancies (>2x off either side):\n{formatted}")

    # Spot-check at least 3 matched constituents stayed within band, per Matt's spec.
    n_within = len(spot_checks) - len(discrepancies)
    assert n_within >= 3, (
        f"Fewer than 3 matched constituents within 0.5x-2.0x baseline. "
        f"Got {n_within}. Discrepancies: {discrepancies}"
    )
