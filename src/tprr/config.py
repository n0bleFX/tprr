"""Typed config loaders for the TPRR Index MVP.

Loads YAML files in the project's ``config/`` directory into pydantic models.
``load_all()`` cross-validates that every contributor's ``covered_models``
exists in the model registry.

Schema changes here require an entry in docs/decision_log.md (CLAUDE.md
non-negotiable #1).
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tprr.schema import AttestationTier, Tier

# Project config directory: src/tprr/config.py → src/tprr → src → repo root → config
CONFIG_DIR: Path = Path(__file__).resolve().parent.parent.parent / "config"

_PERIOD_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")
_QUARTER_END_MONTH_DAY: dict[int, tuple[int, int]] = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}


class VolumeScale(StrEnum):
    """Coarse volume scale for synthetic Tier A contributors (mockdata only)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class IndexConfig(BaseModel):
    """Per-run index calculation parameters."""

    model_config = ConfigDict(populate_by_name=True)

    lambda_: float = Field(default=3.0, alias="lambda")
    base_date: date = date(2026, 1, 1)
    backtest_start: date = date(2025, 1, 1)
    quality_gate_pct: float = 0.15
    continuity_check_pct: float = 0.25
    min_constituents_per_tier: int = 3
    """Index-tier activation threshold: the number of active constituents
    required across ALL attestation tiers in a single index tier (TPRR_F /
    TPRR_S / TPRR_E). Below this, the tier suspends with
    ``insufficient_constituents``. Acts at the (date, index_code) layer."""

    tier_min_constituents_for_blending: int = 3
    """Per-attestation-tier eligibility threshold under continuous blending:
    the number of constituents within an index tier that must have data in
    a given attestation tier (A / B / C) for that attestation tier to
    contribute to the dual-weighted aggregation. Below this, the tier is
    dormant and its blending coefficient redistributes to the remaining
    eligible tiers via the existing ``redistribute_blending_coefficients``
    rule. Acts at the (date, index_code, attestation_tier) layer.

    Distinct from ``min_constituents_per_tier`` (DL 2026-05-01 Phase 10
    Batch 10A tier-eligibility threshold): same epistemic principle (≥N
    independent observations) applied at different aggregation layers —
    contributor → constituent (Tier A's existing rule) and constituent →
    attestation-tier (this rule)."""

    staleness_max_days: int = 3
    suspension_threshold_days: int = 3
    reinstatement_threshold_days: int = 10
    tier_haircuts: dict[AttestationTier, float] = Field(
        default_factory=lambda: {
            AttestationTier.A: 1.0,
            AttestationTier.B: 0.5,
            AttestationTier.C: 0.8,
        }
    )
    tier_blending_coefficients: dict[AttestationTier, float] = Field(
        default_factory=lambda: {
            AttestationTier.A: 0.6,
            AttestationTier.B: 0.1,
            AttestationTier.C: 0.3,
        }
    )
    twap_window_utc: tuple[int, int] = (9, 17)
    twap_slots: int = 32
    default_ordering: str = "twap_then_weight"


class ModelMetadata(BaseModel):
    """Eligibility-passed model in the index universe (methodology Section 3.1)."""

    constituent_id: str
    tier: Tier
    provider: str
    canonical_name: str
    baseline_input_price_usd_mtok: float
    baseline_output_price_usd_mtok: float
    openrouter_author: str | None = None
    openrouter_slug: str | None = None
    active_from: date | None = None
    active_until: date | None = None


class ModelRegistry(BaseModel):
    """The full set of TPRR-eligible models."""

    models: list[ModelMetadata]

    def __len__(self) -> int:
        return len(self.models)


class ContributorProfile(BaseModel):
    """A simulated Tier A contributor's price/volume profile."""

    contributor_id: str
    profile_name: str
    volume_scale: VolumeScale
    price_bias_pct: float
    daily_noise_sigma_pct: float
    error_rate: float
    covered_models: list[str]


class ContributorPanel(BaseModel):
    """The full mock contributor panel."""

    contributors: list[ContributorProfile]

    def __len__(self) -> int:
        return len(self.contributors)


class TierBRevenueEntry(BaseModel):
    """One quarter of disclosed provider API revenue.

    ``period`` must be ``"YYYY-Qn"`` with n in 1..4 — the loader's interpolation
    logic relies on this. Malformed periods fail at load time, not later.
    """

    provider: str
    period: str
    amount_usd: float
    source: str

    @field_validator("period")
    @classmethod
    def _validate_period_format(cls, v: str) -> str:
        if not _PERIOD_PATTERN.fullmatch(v):
            raise ValueError(f"period must match 'YYYY-Qn' (n in 1..4), got {v!r}")
        return v


class TierBRevenueConfig(BaseModel):
    """Revenue entries for Tier B volume derivation (methodology Section 3.3.2)."""

    entries: list[TierBRevenueEntry]

    def __len__(self) -> int:
        return len(self.entries)

    def get_provider_revenue(self, provider: str, target_date: date) -> float:
        """Linearly-interpolated revenue for ``provider`` at ``target_date``.

        Anchors each quarterly entry at end-of-quarter (Q1→Mar 31, Q2→Jun 30,
        Q3→Sep 30, Q4→Dec 31). Below the earliest anchor → returns earliest
        amount; above the latest anchor → returns latest amount (no
        extrapolation either side). Raises ValueError if the provider has no
        entries.
        """
        provider_entries = sorted(
            (e for e in self.entries if e.provider == provider),
            key=lambda e: _period_to_quarter_end(e.period),
        )
        if not provider_entries:
            raise ValueError(f"no Tier B revenue entries for provider {provider!r}")
        anchors = [_period_to_quarter_end(e.period) for e in provider_entries]
        amounts = [e.amount_usd for e in provider_entries]
        if target_date <= anchors[0]:
            return amounts[0]
        if target_date >= anchors[-1]:
            return amounts[-1]
        for i in range(len(anchors) - 1):
            d0, d1 = anchors[i], anchors[i + 1]
            if d0 <= target_date <= d1:
                fraction = (target_date - d0).days / (d1 - d0).days
                return amounts[i] + fraction * (amounts[i + 1] - amounts[i])
        raise RuntimeError(  # pragma: no cover — bounds checks above are exhaustive
            "Tier B revenue interpolation hit unreachable branch"
        )


# ---------------------------------------------------------------------------
# Scenarios — sub-models reused across scenario kinds
# ---------------------------------------------------------------------------


class _TargetSinglePair(BaseModel):
    """Target a single (contributor, constituent) pair."""

    contributor_id: str
    constituent_id: str


class _TargetContributorList(BaseModel):
    """Target a list of contributors (correlated blackout)."""

    contributor_ids: list[str]

    @field_validator("contributor_ids")
    @classmethod
    def _at_least_two_unique(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("contributor_ids must list at least 2 entries (correlated blackout)")
        if len(set(v)) != len(v):
            raise ValueError("contributor_ids must be unique")
        return v


class _TargetConstituent(BaseModel):
    """Target a single constituent (provider-level shock)."""

    constituent_id: str


class _TargetTierWide(BaseModel):
    """Target an entire tier (regime shift)."""

    tier_wide: bool

    @field_validator("tier_wide")
    @classmethod
    def _must_be_true(cls, v: bool) -> bool:
        if not v:
            raise ValueError("tier_wide must be true if present")
        return v


class _TimingSingleSlot(BaseModel):
    """Single day + single slot."""

    day_offset: int = Field(ge=0)
    slot: int = Field(ge=0, le=31)


class _TimingSlotRange(BaseModel):
    """Single day + INCLUSIVE slot range ``[slot_start, slot_end]``.

    Both endpoints are valid slot indices and are part of the affected
    range. ``slot_start == slot_end`` is permitted (single-slot via the
    range form).

    v0.1 invariant (enforced by the ``intraday_spike`` composer in
    ``mockdata/scenarios.py``): a paired ``revert: { at_slot: N }`` block
    must have ``N == slot_end + 1``, so the spike covers exactly the
    documented inclusive range and no off-by-one window of stale or
    intermediate pricing is implied. Multi-segment intraday patterns
    (multiple discontinuous spikes within a day, hold-then-step, etc.)
    require new scenario kinds rather than parameter generalisation of
    this one — extending ``revert`` semantics here would silently expand
    the scenario's behaviour beyond what the kind name documents.
    """

    day_offset: int = Field(ge=0)
    slot_start: int = Field(ge=0, le=31)
    slot_end: int = Field(ge=0, le=31)

    @model_validator(mode="after")
    def _start_le_end(self) -> _TimingSlotRange:
        if self.slot_start > self.slot_end:
            raise ValueError(
                f"slot_start ({self.slot_start}) must be <= slot_end ({self.slot_end})"
            )
        return self


class _TimingSingleDay(BaseModel):
    """Day offset only (single day, full-day effect)."""

    day_offset: int = Field(ge=0)


class _TimingDateRange(BaseModel):
    """Day offset + duration in days."""

    day_offset_start: int = Field(ge=0)
    duration_days: int = Field(gt=0)


class _MultiplierMagnitude(BaseModel):
    """Positive price multiplier (10.0 = 10x, 0.1 = 1/10x)."""

    multiplier: float = Field(gt=0)


class _RevertAfterSlots(BaseModel):
    """Revert N slots after the spike (fat-finger pattern)."""

    after_slots: int = Field(gt=0)


class _RevertAtSlot(BaseModel):
    """Revert at a fixed slot index (intraday spike pattern)."""

    at_slot: int = Field(ge=0, le=31)


class _TierMedianManipulation(BaseModel):
    """Override price to ``tier-median * multiplier`` daily."""

    type: Literal["tier_median_multiplier"]
    multiplier: float = Field(gt=0)


class _RegimeShiftDynamics(BaseModel):
    """Override pricing dynamics for an existing constituent over a window.

    Schema-vs-composer split: schema accepts ``step_rate_per_year >= 0``
    (permissive for v1.x scenarios), but the v0.1 ``regime_shift`` composer
    enforces ``step_rate_per_year == 0`` because
    ``regenerate_constituent_slice`` does not yet support emitting new
    in-window events for existing constituents (see outliers.py docstring).
    Future v0.2 may relax the composer constraint without a schema change.
    """

    sigma_daily: float = Field(ge=0)
    mu_daily: float
    step_rate_per_year: float = Field(ge=0)


class _NewModelMetadata(BaseModel):
    """ModelMetadata-equivalent for a scenario-launched constituent."""

    constituent_id: str
    tier: Tier
    provider: str
    canonical_name: str
    baseline_input_price_usd_mtok: float = Field(gt=0)
    baseline_output_price_usd_mtok: float = Field(gt=0)


class _CoverageSpec(BaseModel):
    """List of contributor_ids covering a newly launched constituent."""

    contributor_ids: list[str] = Field(min_length=1)

    @field_validator("contributor_ids")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("coverage contributor_ids must be unique")
        return v


# ---------------------------------------------------------------------------
# Scenarios — per-kind specs (discriminated on ``kind``)
# ---------------------------------------------------------------------------


class _ScenarioBase(BaseModel):
    """Common fields shared by every scenario."""

    id: str
    description: str


class FatFingerSpec(_ScenarioBase):
    """Single-slot price spike (fat_finger_high or fat_finger_low)."""

    kind: Literal["fat_finger"]
    tier: Tier
    target: _TargetSinglePair
    timing: _TimingSingleSlot
    magnitude: _MultiplierMagnitude
    revert: _RevertAfterSlots


class StaleQuoteSpec(_ScenarioBase):
    """Freeze a pair's price across a window."""

    kind: Literal["stale_quote"]
    tier: Tier
    target: _TargetSinglePair
    timing: _TimingDateRange
    freeze_price_source: Literal["entry_day"]


class CorrelatedBlackoutSpec(_ScenarioBase):
    """Concurrent contributor outages."""

    kind: Literal["correlated_blackout"]
    target: _TargetContributorList
    timing: _TimingDateRange


class ShockPriceCutSpec(_ScenarioBase):
    """Provider-level step-down propagated to all covering contributors."""

    kind: Literal["shock_price_cut"]
    tier: Tier
    target: _TargetConstituent
    timing: _TimingSingleDay
    magnitude: _MultiplierMagnitude
    notes: list[str] = Field(default_factory=list)


class SustainedManipulationSpec(_ScenarioBase):
    """Contributor sustains off-median pricing over a window."""

    kind: Literal["sustained_manipulation"]
    tier: Tier
    target: _TargetSinglePair
    timing: _TimingDateRange
    manipulation: _TierMedianManipulation


class TierReshuffleSpec(_ScenarioBase):
    """Index Committee reclassification of a constituent."""

    kind: Literal["tier_reshuffle"]
    target: _TargetConstituent
    new_tier: Tier
    timing: _TimingSingleDay


class NewModelLaunchSpec(_ScenarioBase):
    """Mid-period bootstrap of a new constituent."""

    kind: Literal["new_model_launch"]
    new_model: _NewModelMetadata
    coverage: _CoverageSpec
    timing: _TimingSingleDay


class IntradaySpikeSpec(_ScenarioBase):
    """Off-market price across a slot range within one day."""

    kind: Literal["intraday_spike"]
    tier: Tier
    target: _TargetSinglePair
    timing: _TimingSlotRange
    magnitude: _MultiplierMagnitude
    revert: _RevertAtSlot


class RegimeShiftSpec(_ScenarioBase):
    """Elevated dynamics across a tier and window."""

    kind: Literal["regime_shift"]
    tier: Tier
    target: _TargetTierWide
    timing: _TimingDateRange
    dynamics: _RegimeShiftDynamics


ScenarioEntry = Annotated[
    FatFingerSpec
    | StaleQuoteSpec
    | CorrelatedBlackoutSpec
    | ShockPriceCutSpec
    | SustainedManipulationSpec
    | TierReshuffleSpec
    | NewModelLaunchSpec
    | IntradaySpikeSpec
    | RegimeShiftSpec,
    Field(discriminator="kind"),
]


class ScenariosConfig(BaseModel):
    """Phase 3 outlier-injection scenario manifest."""

    scenarios: list[ScenarioEntry] = Field(default_factory=list)

    @field_validator("scenarios")
    @classmethod
    def _ids_unique(cls, v: list[ScenarioEntry]) -> list[ScenarioEntry]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"scenario ids must be unique; duplicates: {duplicates}")
        return v


class AllConfig(BaseModel):
    """Bundle of all loaded configs after cross-validation."""

    index: IndexConfig
    model_registry: ModelRegistry
    contributors: ContributorPanel
    tier_b_revenue: TierBRevenueConfig
    scenarios: ScenariosConfig


def _period_to_quarter_end(period: str) -> date:
    """Map ``'YYYY-Qn'`` → last day of that quarter. Assumes pre-validated input."""
    year = int(period[:4])
    quarter = int(period[6])
    month, day = _QUARTER_END_MONTH_DAY[quarter]
    return date(year, month, day)


def _read_yaml(path: Path) -> dict[str, Any]:  # YAML may hold heterogeneous values
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected YAML mapping at top level, got {type(loaded).__name__}")
    return loaded


def load_index_config(path: Path | None = None) -> IndexConfig:
    if path is None:
        path = CONFIG_DIR / "index_config.yaml"
    return IndexConfig.model_validate(_read_yaml(path))


def load_model_registry(path: Path | None = None) -> ModelRegistry:
    if path is None:
        path = CONFIG_DIR / "model_registry.yaml"
    return ModelRegistry.model_validate(_read_yaml(path))


def load_contributors(path: Path | None = None) -> ContributorPanel:
    if path is None:
        path = CONFIG_DIR / "contributors.yaml"
    return ContributorPanel.model_validate(_read_yaml(path))


def load_tier_b_revenue(path: Path | None = None) -> TierBRevenueConfig:
    if path is None:
        path = CONFIG_DIR / "tier_b_revenue.yaml"
    return TierBRevenueConfig.model_validate(_read_yaml(path))


def load_scenarios(path: Path | None = None) -> ScenariosConfig:
    if path is None:
        path = CONFIG_DIR / "scenarios.yaml"
    return ScenariosConfig.model_validate(_read_yaml(path))


def _cross_validate_covered_models(contributors: ContributorPanel, registry: ModelRegistry) -> None:
    valid_ids = {m.constituent_id for m in registry.models}
    for profile in contributors.contributors:
        unknown = sorted(set(profile.covered_models) - valid_ids)
        if unknown:
            raise ValueError(
                f"contributor {profile.contributor_id!r} lists covered_models "
                f"{unknown} not in model registry"
            )


def _scenario_window_bounds(spec: ScenarioEntry) -> tuple[int, int]:
    """Return inclusive (first_day, last_day) for a scenario's effective window.

    For windowed scenarios (``timing: _TimingDateRange``), last_day is
    ``day_offset_start + duration_days - 1``. For single-day scenarios
    (``_TimingSingleDay`` / ``_TimingSingleSlot`` / ``_TimingSlotRange``),
    first_day == last_day == day_offset.
    """
    timing = spec.timing
    if isinstance(timing, _TimingDateRange):
        first = timing.day_offset_start
        last = first + timing.duration_days - 1
    else:
        first = timing.day_offset
        last = timing.day_offset
    return first, last


def _cross_validate_scenario_references(
    scenarios: ScenariosConfig,
    contributors: ContributorPanel,
    registry: ModelRegistry,
    index_config: IndexConfig,
    backtest_end: date,
) -> None:
    """Verify scenarios reference real IDs and fall within the backtest window.

    Checks per scenario: (i) every referenced ``contributor_id`` exists in
    the panel; (ii) every referenced ``constituent_id`` exists in the
    registry; (iii) for ``new_model_launch``, the new constituent_id is NOT
    already in the registry; (iv) every scenario's effective window
    (``day_offset`` for single-day forms, ``day_offset_start +
    duration_days - 1`` for windowed forms) lies within
    ``[0, (backtest_end - backtest_start).days]``.
    """
    contrib_ids = {c.contributor_id for c in contributors.contributors}
    constituent_ids = {m.constituent_id for m in registry.models}
    backtest_window_days = (backtest_end - index_config.backtest_start).days
    if backtest_window_days < 0:
        raise ValueError(
            f"backtest_end {backtest_end!s} is before "
            f"backtest_start {index_config.backtest_start!s}"
        )

    for s in scenarios.scenarios:
        refs_contrib: list[str] = []
        refs_constituent: list[str] = []
        new_constituent: str | None = None

        if isinstance(
            s,
            FatFingerSpec | StaleQuoteSpec | SustainedManipulationSpec | IntradaySpikeSpec,
        ):
            refs_contrib.append(s.target.contributor_id)
            refs_constituent.append(s.target.constituent_id)
        elif isinstance(s, CorrelatedBlackoutSpec):
            refs_contrib.extend(s.target.contributor_ids)
        elif isinstance(s, ShockPriceCutSpec | TierReshuffleSpec):
            refs_constituent.append(s.target.constituent_id)
        elif isinstance(s, NewModelLaunchSpec):
            refs_contrib.extend(s.coverage.contributor_ids)
            new_constituent = s.new_model.constituent_id
        elif isinstance(s, RegimeShiftSpec):
            pass  # tier_wide; no specific IDs to resolve

        unknown_contribs = sorted(set(refs_contrib) - contrib_ids)
        if unknown_contribs:
            raise ValueError(
                f"scenario {s.id!r}: contributor_ids {unknown_contribs} not in contributor panel"
            )
        unknown_constituents = sorted(set(refs_constituent) - constituent_ids)
        if unknown_constituents:
            raise ValueError(
                f"scenario {s.id!r}: constituent_ids {unknown_constituents} not in model registry"
            )
        if new_constituent is not None and new_constituent in constituent_ids:
            raise ValueError(
                f"scenario {s.id!r}: new_model.constituent_id "
                f"{new_constituent!r} already in registry"
            )

        first_day, last_day = _scenario_window_bounds(s)
        if first_day > backtest_window_days:
            raise ValueError(
                f"scenario {s.id!r}: day_offset {first_day} exceeds backtest "
                f"window of {backtest_window_days} days "
                f"({index_config.backtest_start!s} -> {backtest_end!s})"
            )
        if last_day > backtest_window_days:
            raise ValueError(
                f"scenario {s.id!r}: window end day {last_day} exceeds "
                f"backtest window of {backtest_window_days} days "
                f"({index_config.backtest_start!s} -> {backtest_end!s})"
            )


def load_all(
    config_dir: Path | None = None,
    *,
    backtest_end: date | None = None,
    scenarios_path: Path | None = None,
) -> AllConfig:
    """Load every config file, cross-validate, return as ``AllConfig``.

    ``backtest_end`` defaults to ``date.today()`` and is used only for
    scenario-window cross-validation (rejects scenarios whose day offsets
    fall outside ``[backtest_start, backtest_end]``). Pass an explicit
    value when running deterministic tests or when validating against a
    fixed end-date for reproducibility.

    ``scenarios_path`` overrides the default ``{config_dir}/scenarios.yaml``
    when provided. Used by ``scripts/generate_mock_data.py --scenarios PATH``
    so the cross-validation runs against the same YAML the script will
    compose from, avoiding double-loading and stale-config-dir collisions
    in tests.
    """
    if config_dir is None:
        config_dir = CONFIG_DIR
    if backtest_end is None:
        backtest_end = date.today()
    scenarios_yaml_path = (
        scenarios_path if scenarios_path is not None else config_dir / "scenarios.yaml"
    )
    bundle = AllConfig(
        index=load_index_config(config_dir / "index_config.yaml"),
        model_registry=load_model_registry(config_dir / "model_registry.yaml"),
        contributors=load_contributors(config_dir / "contributors.yaml"),
        tier_b_revenue=load_tier_b_revenue(config_dir / "tier_b_revenue.yaml"),
        scenarios=load_scenarios(scenarios_yaml_path),
    )
    _cross_validate_covered_models(bundle.contributors, bundle.model_registry)
    _cross_validate_scenario_references(
        bundle.scenarios,
        bundle.contributors,
        bundle.model_registry,
        bundle.index,
        backtest_end,
    )
    return bundle
