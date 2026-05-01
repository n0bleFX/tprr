"""OpenRouter API client + normalisation — Phase 4 Tier C reference.

Three fetchers, all unauthenticated, with daily caching:

  fetch_models                         GET /api/v1/models
  fetch_model_endpoints(author, slug)  GET /api/v1/models/{author}/{slug}/endpoints
  fetch_rankings                       GET (jampongsathorn mirror) latest.json

Three normalisers turning raw JSON into PanelObservationDF rows:

  normalise_models_to_panel       one row per registry-matched OR model
                                  (contributor_id = "openrouter:aggregate")
  normalise_endpoints_to_panel    one row per hosting provider for a model
                                  (contributor_id = "openrouter:{provider_slug}")
  enrich_with_rankings_volume     populate volume_mtok_7d on a panel from
                                  rankings data (Batch C: full integration;
                                  Batch B: structural pass-through stub)

Every fetched response is cached to
``data/raw/openrouter/{kind}/{YYYY-MM-DD}.json``; cache hit returns the
cached payload without HTTP. The optional ``client`` keyword argument
accepts an ``httpx.Client`` for testing (with ``MockTransport``); when
omitted, a 30-second-timeout client is created internally with the
proper ``User-Agent`` header.

Per CLAUDE.md OpenRouter integration rules:
  * Read-only, no auth (these endpoints are public).
  * 30-second timeout, single retry on 5xx, no retry on 4xx.
  * User-Agent: ``Noble-Argon-TPRR/0.1 research``.
  * Never re-fetch the same day for the same kind.
  * ``$/token`` -> ``$/Mtok`` via x 1e6.
  * Ignore ``:free`` / ``:nitro`` / ``:floor`` / ``:online`` variant suffixes.
  * Skip ``openrouter/auto``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from tprr.config import ModelRegistry
from tprr.schema import AttestationTier, Tier

logger = logging.getLogger(__name__)

# Match a trailing -YYYYMMDD suffix on a rankings slug (the OpenRouter rankings
# mirror suffixes the dated variant of each model). Stripping yields the base
# slug for matching against /api/v1/models conventions.
_DATE_SUFFIX_PATTERN = re.compile(r"-\d{8}$")
_NO_RANKINGS_NOTE = "no_rankings_data"

USER_AGENT = "Noble-Argon-TPRR/0.1 research"
TIMEOUT_SECONDS = 30.0
API_BASE = "https://openrouter.ai/api/v1"
RANKINGS_URL = (
    "https://raw.githubusercontent.com/jampongsathorn/openrouter-rankings/main/data/latest.json"
)

# repo root / data / raw / openrouter — independent of cwd.
DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "raw" / "openrouter"


def fetch_models(
    *,
    as_of_date: date | None = None,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch the global model catalogue. Cached by date under ``models/``."""
    as_of = as_of_date or date.today()
    cache_path = (cache_dir or DEFAULT_CACHE_DIR) / "models" / f"{as_of.isoformat()}.json"
    return _fetch_with_cache(
        cache_path=cache_path,
        url=f"{API_BASE}/models",
        client=client,
    )


def fetch_model_endpoints(
    author: str,
    slug: str,
    *,
    as_of_date: date | None = None,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch a model's per-provider hosting endpoints.

    Cached by ``(author, slug, date)`` under ``endpoints/{author}/{slug}/``.
    """
    as_of = as_of_date or date.today()
    cache_path = (
        (cache_dir or DEFAULT_CACHE_DIR) / "endpoints" / author / slug / f"{as_of.isoformat()}.json"
    )
    return _fetch_with_cache(
        cache_path=cache_path,
        url=f"{API_BASE}/models/{author}/{slug}/endpoints",
        client=client,
    )


def fetch_rankings(
    *,
    as_of_date: date | None = None,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch the jampongsathorn rankings-mirror latest snapshot.

    Cached by date under ``rankings/``. Per CLAUDE.md, this mirror exposes
    weekly snapshots dated from a recent point in time; for the Jan 2025 →
    today backtest, Tier C historical backfill uses the current snapshot
    as a static structural proxy across the full window (decision log
    2026-04-27 entry on Tier C historical backfill).
    """
    as_of = as_of_date or date.today()
    cache_path = (cache_dir or DEFAULT_CACHE_DIR) / "rankings" / f"{as_of.isoformat()}.json"
    return _fetch_with_cache(
        cache_path=cache_path,
        url=RANKINGS_URL,
        client=client,
    )


# ---------------------------------------------------------------------------
# Internals — cache + HTTP
# ---------------------------------------------------------------------------


def _fetch_with_cache(
    *,
    cache_path: Path,
    url: str,
    client: httpx.Client | None,
) -> dict[str, Any]:
    """Read from cache if present; otherwise GET ``url`` and populate."""
    if cache_path.exists():
        return _load_cached_json(cache_path)

    payload = _http_get_json(url, client)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _http_get_json(url: str, client: httpx.Client | None) -> dict[str, Any]:
    """GET ``url``, parse JSON, single retry on 5xx, no retry on 4xx."""
    own_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
    try:
        response = client.get(url)
        if 500 <= response.status_code < 600:
            response = client.get(url)  # single retry
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError(f"OpenRouter response from {url} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"OpenRouter response from {url} expected a JSON object at "
                f"top level, got {type(payload).__name__}"
            )
        return payload
    finally:
        if own_client:
            client.close()


def _load_cached_json(path: Path) -> dict[str, Any]:
    """Load cached JSON; raise ``ValueError`` clearly if the file is malformed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"cached OpenRouter response at {path} is malformed: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"cached OpenRouter response at {path} expected a JSON object "
            f"at top level, got {type(payload).__name__}"
        )
    return payload


# ---------------------------------------------------------------------------
# Normalisation — raw JSON to PanelObservationDF rows
# ---------------------------------------------------------------------------

# Per CLAUDE.md OpenRouter integration rules.
_VARIANT_SUFFIXES: tuple[str, ...] = (":free", ":nitro", ":floor", ":online")
_SKIP_IDS: frozenset[str] = frozenset({"openrouter/auto"})

_OPENROUTER_AGGREGATE_CONTRIB = "openrouter:aggregate"
_PROVIDER_SLUG_NORMALISE_FROM = (" ", "_")
_PROVIDER_SLUG_REPLACE_TO = "-"

_PANEL_COLUMNS = [
    "observation_date",
    "constituent_id",
    "contributor_id",
    "tier_code",
    "attestation_tier",
    "input_price_usd_mtok",
    "output_price_usd_mtok",
    "volume_mtok_7d",
    "source",
    "submitted_at",
    "notes",
]


def normalise_models_to_panel(
    models_json: dict[str, Any],
    model_registry: ModelRegistry,
    as_of_date: date,
) -> pd.DataFrame:
    """Normalise OpenRouter ``/api/v1/models`` response to panel rows.

    One row per registry-matched constituent. Matching strategy:

      1. **Primary** — if ``ModelMetadata.openrouter_author`` and
         ``openrouter_slug`` are both populated, match on
         ``f"{author}/{slug}" == openrouter_entry["id"]``. This is the
         canonical path; the registry's openrouter_* fields are populated
         per docs/decision_log.md 2026-04-27 ("OpenRouter coverage: 11/16
         registry models mapped").
      2. **Fallback** — if either openrouter_* field is unset, fall back
         to ``constituent_id == openrouter_entry["id"]`` and log INFO
         flagging the registry entry as unpopulated. Defensive: catches
         future registry entries that have not yet been mapped.

    Variant suffixes (``:free``, ``:nitro``, ``:floor``, ``:online``) and
    ``openrouter/auto`` are filtered from the OpenRouter response BEFORE
    matching, so a registry constituent can never resolve to a variant.
    Unmatched registry constituents are logged at INFO and skipped — they
    are NOT raised. Five v0.1 registry constituents have no OpenRouter
    analogue (claude-opus-4-7, claude-sonnet-4-6, meta/llama-4-70b-hosted,
    mistral/mistral-large-3, alibaba/qwen-3-6-plus); see decision log.

    Output rows:
      * ``contributor_id = "openrouter:aggregate"`` — single per-constituent row
      * ``attestation_tier = "C"``
      * ``source = "openrouter_models"``
      * ``volume_mtok_7d = 0.0`` (populated later by
        ``enrich_with_rankings_volume``)
      * Prices: OpenRouter's ``pricing.prompt`` and ``pricing.completion``
        (strings in ``$/token``) parsed and multiplied by ``1e6`` to give
        ``$/Mtok``.
    """
    or_entries = models_json.get("data", [])
    or_lookup: dict[str, dict[str, Any]] = {}
    for entry in or_entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id", "")
        if not isinstance(model_id, str) or not model_id:
            continue
        if model_id in _SKIP_IDS:
            continue
        if any(model_id.endswith(suffix) for suffix in _VARIANT_SUFFIXES):
            continue
        or_lookup[model_id] = entry

    submitted_at = pd.Timestamp(as_of_date)
    rows: list[dict[str, Any]] = []
    for m in model_registry.models:
        or_id, used_fallback = _resolve_openrouter_id(m)
        or_entry = or_lookup.get(or_id) if or_id is not None else None
        if or_entry is None:
            logger.info(
                "OpenRouter normalise: registry constituent %r has no match in "
                "OpenRouter /models (resolved id=%r, fallback=%s) — skipped",
                m.constituent_id,
                or_id,
                used_fallback,
            )
            continue
        if used_fallback:
            logger.info(
                "OpenRouter normalise: registry constituent %r matched via "
                "constituent_id fallback (openrouter_author/slug unpopulated) — "
                "consider populating explicitly",
                m.constituent_id,
            )
        prompt_per_tok, completion_per_tok = _extract_pricing(or_entry)
        rows.append(
            _panel_row(
                as_of_date=as_of_date,
                submitted_at=submitted_at,
                constituent_id=m.constituent_id,
                contributor_id=_OPENROUTER_AGGREGATE_CONTRIB,
                tier=m.tier,
                input_price_per_token=prompt_per_tok,
                output_price_per_token=completion_per_tok,
                source="openrouter_models",
            )
        )
    return _build_panel_df(rows)


def _resolve_openrouter_id(meta: Any) -> tuple[str | None, bool]:
    """Return ``(openrouter_id, used_fallback)`` for a ModelMetadata.

    Primary: ``f"{openrouter_author}/{openrouter_slug}"`` when both fields
    are populated. Fallback: ``meta.constituent_id`` when either field is
    missing — the caller logs the fallback as INFO so unpopulated registry
    entries stay visible. ``Any`` used because importing ModelMetadata here
    would create an import cycle (config imports from schema, which is
    indirectly imported by this module).
    """
    author = getattr(meta, "openrouter_author", None)
    slug = getattr(meta, "openrouter_slug", None)
    if author and slug:
        return f"{author}/{slug}", False
    cid = getattr(meta, "constituent_id", None)
    return (cid if isinstance(cid, str) else None), True


def normalise_endpoints_to_panel(
    endpoints_json: dict[str, Any],
    constituent_id: str,
    tier: Tier,
    as_of_date: date,
) -> pd.DataFrame:
    """Normalise per-model ``/endpoints`` response to one row per hosting provider.

    OpenRouter's endpoints payload shape: ``{"data": {"id": ..., "endpoints":
    [{"provider_name": ..., "pricing": {...}}, ...]}}``. Each endpoint is
    one provider hosting this model; we emit one panel row per endpoint
    with ``contributor_id = "openrouter:{provider_slug}"`` (provider name
    lowercased with spaces and underscores collapsed to ``-``). Tier is
    passed in by the caller (typically iterating ``model_registry.models``).
    Same price unit conversion as ``normalise_models_to_panel``.
    """
    data = endpoints_json.get("data", {})
    endpoints = data.get("endpoints", []) if isinstance(data, dict) else []
    submitted_at = pd.Timestamp(as_of_date)
    rows: list[dict[str, Any]] = []
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        provider_name = ep.get("provider_name") or ep.get("name") or ""
        if not isinstance(provider_name, str) or not provider_name:
            continue
        provider_slug = _provider_slug(provider_name)
        prompt_per_tok, completion_per_tok = _extract_pricing(ep)
        rows.append(
            _panel_row(
                as_of_date=as_of_date,
                submitted_at=submitted_at,
                constituent_id=constituent_id,
                contributor_id=f"openrouter:{provider_slug}",
                tier=tier,
                input_price_per_token=prompt_per_tok,
                output_price_per_token=completion_per_tok,
                source="openrouter_endpoints",
            )
        )
    return _build_panel_df(rows)


def enrich_with_rankings_volume(
    panel_df: pd.DataFrame,
    rankings_json: dict[str, Any],
    model_registry: ModelRegistry,
) -> pd.DataFrame:
    """Populate ``volume_mtok_7d`` from rankings data via model-level matching.

    Per docs/decision_log.md 2026-04-28 ("Tier C rankings sparseness"):
    model-level matching only. A panel row's ``constituent_id`` resolves
    to its registry entry's ``(openrouter_author, openrouter_slug)``;
    rankings entries are matched via exact ``(author, slug)`` after
    stripping the trailing ``-YYYYMMDD`` date suffix from the rankings
    slug. Constituents without a model-level rankings match receive
    ``volume_mtok_7d = 0`` and a ``"no_rankings_data"`` flag in
    ``notes``. Author-level fallback is NOT used.

    Tokens conversion: rankings ``tokens`` field is the trailing weekly
    aggregate per the mirror's documentation, converted to ``mtok``
    via ``tokens / 1e6``. Rankings ``tokens`` covers combined input +
    output traffic — using it as ``volume_mtok_7d`` (output volume by
    schema) slightly overstates output, accepted MVP simplification.

    Variant-suffixed rankings entries (``:free`` etc.) are filtered out
    consistent with ``/api/v1/models`` normalisation.

    Only Tier C panel rows are touched. Other-tier rows pass through
    unchanged.
    """
    volume_by_constituent = _build_rankings_volume_lookup(rankings_json, model_registry)

    out = panel_df.copy()
    if len(out) == 0 or "attestation_tier" not in out.columns:
        return out

    tier_c_mask = out["attestation_tier"] == AttestationTier.C.value
    matched_constituents: set[str] = set()
    unmatched_constituents: set[str] = set()

    for idx in out.index[tier_c_mask]:
        cid = str(out.at[idx, "constituent_id"])
        if cid in volume_by_constituent:
            out.at[idx, "volume_mtok_7d"] = volume_by_constituent[cid]
            matched_constituents.add(cid)
        else:
            existing = str(out.at[idx, "notes"]) if "notes" in out.columns else ""
            out.at[idx, "notes"] = (
                _NO_RANKINGS_NOTE if not existing else f"{existing};{_NO_RANKINGS_NOTE}"
            )
            unmatched_constituents.add(cid)

    n_matched = len(matched_constituents)
    n_total = n_matched + len(unmatched_constituents)
    logger.info(
        "OpenRouter rankings: %d of %d Tier C constituents matched to rankings",
        n_matched,
        n_total,
    )
    return out


def _build_rankings_volume_lookup(
    rankings_json: dict[str, Any],
    model_registry: ModelRegistry,
) -> dict[str, float]:
    """Map registry constituent_ids to ``volume_mtok_7d`` via rankings match.

    1. Build ``(rankings_author, stripped_rankings_slug) -> tokens`` from
       ``rankings_json["models"]``, stripping trailing ``-YYYYMMDD`` and
       skipping variant suffixes.
    2. For each registry model with ``openrouter_author/slug`` populated,
       look up ``(openrouter_author, openrouter_slug)`` in step 1's map
       and emit ``constituent_id -> tokens / 1e6`` if found.
    """
    rankings_volume: dict[tuple[str, str], float] = {}
    models = rankings_json.get("models", [])
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            author = entry.get("author")
            slug = entry.get("slug")
            tokens = entry.get("tokens")
            if not (
                isinstance(author, str)
                and isinstance(slug, str)
                and isinstance(tokens, int | float)
            ):
                continue
            if any(slug.endswith(suffix) for suffix in _VARIANT_SUFFIXES):
                continue
            stripped_slug = _DATE_SUFFIX_PATTERN.sub("", slug)
            rankings_volume[(author, stripped_slug)] = float(tokens) / 1e6

    out: dict[str, float] = {}
    for m in model_registry.models:
        if m.openrouter_author and m.openrouter_slug:
            key = (m.openrouter_author, m.openrouter_slug)
            if key in rankings_volume:
                out[m.constituent_id] = rankings_volume[key]
    return out


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _extract_pricing(entry: dict[str, Any]) -> tuple[float, float]:
    """Return ``(prompt_per_token, completion_per_token)`` as floats.

    OpenRouter prices are JSON strings in ``$/token``; missing or invalid
    fields default to ``0.0`` so a row still emits (the caller can decide
    whether a $0 price is a quality issue downstream).
    """
    pricing = entry.get("pricing", {})
    if not isinstance(pricing, dict):
        return 0.0, 0.0
    return _to_float(pricing.get("prompt")), _to_float(pricing.get("completion"))


def _to_float(value: Any) -> float:  # OpenRouter returns strings; tolerate floats too
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _provider_slug(provider_name: str) -> str:
    """Lowercase, collapse spaces and underscores to hyphens."""
    slug = provider_name.lower()
    for ch in _PROVIDER_SLUG_NORMALISE_FROM:
        slug = slug.replace(ch, _PROVIDER_SLUG_REPLACE_TO)
    return slug


def _panel_row(
    *,
    as_of_date: date,
    submitted_at: pd.Timestamp,
    constituent_id: str,
    contributor_id: str,
    tier: Tier,
    input_price_per_token: float,
    output_price_per_token: float,
    source: str,
) -> dict[str, Any]:
    return {
        "observation_date": pd.Timestamp(as_of_date),
        "constituent_id": constituent_id,
        "contributor_id": contributor_id,
        "tier_code": tier.value,
        "attestation_tier": AttestationTier.C.value,
        "input_price_usd_mtok": input_price_per_token * 1e6,
        "output_price_usd_mtok": output_price_per_token * 1e6,
        "volume_mtok_7d": 0.0,
        "source": source,
        "submitted_at": submitted_at,
        "notes": "",
    }


def _build_panel_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Assemble PanelObservationDF-compatible DataFrame (empty or populated)."""
    if not rows:
        return pd.DataFrame(
            {
                "observation_date": pd.Series([], dtype="datetime64[ns]"),
                "constituent_id": pd.Series([], dtype="object"),
                "contributor_id": pd.Series([], dtype="object"),
                "tier_code": pd.Series([], dtype="object"),
                "attestation_tier": pd.Series([], dtype="object"),
                "input_price_usd_mtok": pd.Series([], dtype="float64"),
                "output_price_usd_mtok": pd.Series([], dtype="float64"),
                "volume_mtok_7d": pd.Series([], dtype="float64"),
                "source": pd.Series([], dtype="object"),
                "submitted_at": pd.Series([], dtype="datetime64[ns]"),
                "notes": pd.Series([], dtype="object"),
            }
        )
    df = pd.DataFrame(rows)
    df["observation_date"] = pd.to_datetime(df["observation_date"]).astype("datetime64[ns]")
    df["submitted_at"] = pd.to_datetime(df["submitted_at"]).astype("datetime64[ns]")
    return df[_PANEL_COLUMNS].reset_index(drop=True)
