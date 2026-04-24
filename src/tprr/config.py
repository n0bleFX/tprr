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
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    staleness_max_days: int = 3
    tier_haircuts: dict[AttestationTier, float] = Field(
        default_factory=lambda: {
            AttestationTier.A: 1.0,
            AttestationTier.B: 0.9,
            AttestationTier.C: 0.8,
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
            raise ValueError(
                f"period must match 'YYYY-Qn' (n in 1..4), got {v!r}"
            )
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
            raise ValueError(
                f"no Tier B revenue entries for provider {provider!r}"
            )
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


class ScenariosConfig(BaseModel):
    """Placeholder for Phase 3 — stub YAML accepted with arbitrary content."""

    model_config = ConfigDict(extra="allow")


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
        raise ValueError(
            f"{path}: expected YAML mapping at top level, "
            f"got {type(loaded).__name__}"
        )
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


def _cross_validate_covered_models(
    contributors: ContributorPanel, registry: ModelRegistry
) -> None:
    valid_ids = {m.constituent_id for m in registry.models}
    for profile in contributors.contributors:
        unknown = sorted(set(profile.covered_models) - valid_ids)
        if unknown:
            raise ValueError(
                f"contributor {profile.contributor_id!r} lists covered_models "
                f"{unknown} not in model registry"
            )


def load_all(config_dir: Path | None = None) -> AllConfig:
    """Load every config file, cross-validate, return as ``AllConfig``."""
    if config_dir is None:
        config_dir = CONFIG_DIR
    bundle = AllConfig(
        index=load_index_config(config_dir / "index_config.yaml"),
        model_registry=load_model_registry(config_dir / "model_registry.yaml"),
        contributors=load_contributors(config_dir / "contributors.yaml"),
        tier_b_revenue=load_tier_b_revenue(config_dir / "tier_b_revenue.yaml"),
        scenarios=load_scenarios(config_dir / "scenarios.yaml"),
    )
    _cross_validate_covered_models(bundle.contributors, bundle.model_registry)
    return bundle
