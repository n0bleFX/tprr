"""Tests for tprr.reference.openrouter — Phase 4 Batch A client + cache.

All tests use ``httpx.MockTransport``; no real network calls are made.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from tprr.reference.openrouter import (
    USER_AGENT,
    fetch_model_endpoints,
    fetch_models,
    fetch_rankings,
)

AS_OF = date(2026, 4, 27)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """Build an httpx.Client with MockTransport + TPRR's User-Agent header."""
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": USER_AGENT},
    )


# ---------------------------------------------------------------------------
# fetch_models — cache miss + cache hit
# ---------------------------------------------------------------------------


def test_fetch_models_cache_miss_makes_request_and_populates_cache(
    tmp_path: Path,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"id": "openai/gpt-5"}]})

    client = _client(handler)
    payload = fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert len(captured) == 1
    assert payload == {"data": [{"id": "openai/gpt-5"}]}
    cache_path = tmp_path / "models" / "2026-04-27.json"
    assert cache_path.exists()
    assert json.loads(cache_path.read_text(encoding="utf-8")) == payload


def test_fetch_models_cache_hit_returns_cached_without_http(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "models" / "2026-04-27.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"cached": True, "data": []}), encoding="utf-8")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"should": "not be used"})

    client = _client(handler)
    payload = fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert len(captured) == 0
    assert payload == {"cached": True, "data": []}


def test_two_calls_same_day_only_one_request(tmp_path: Path) -> None:
    """Cache populated on first call; second call hits cache — no second request."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"call": call_count["n"]})

    client = _client(handler)
    p1 = fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)
    p2 = fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert call_count["n"] == 1
    assert p1 == p2 == {"call": 1}


def test_different_dates_separate_cache_files(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    fetch_models(as_of_date=date(2026, 4, 27), cache_dir=tmp_path, client=client)
    fetch_models(as_of_date=date(2026, 4, 28), cache_dir=tmp_path, client=client)

    assert (tmp_path / "models" / "2026-04-27.json").exists()
    assert (tmp_path / "models" / "2026-04-28.json").exists()


# ---------------------------------------------------------------------------
# 5xx retry behaviour
# ---------------------------------------------------------------------------


def test_5xx_retries_once_then_succeeds(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    payload = fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert call_count["n"] == 2
    assert payload == {"data": []}


def test_5xx_persistent_after_one_retry_raises(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503)

    client = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    # Single retry only — total of 2 requests.
    assert call_count["n"] == 2


def test_4xx_no_retry(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404)

    client = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert call_count["n"] == 1  # no retry on 4xx


# ---------------------------------------------------------------------------
# Malformed-response handling
# ---------------------------------------------------------------------------


def test_malformed_response_body_raises_clear_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    client = _client(handler)
    with pytest.raises(ValueError, match="not valid JSON"):
        fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)


def test_response_not_top_level_object_raises(tmp_path: Path) -> None:
    """Top-level JSON must be an object (dict), not list/string/number."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["a", "list"])

    client = _client(handler)
    with pytest.raises(ValueError, match="JSON object at top level"):
        fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)


def test_malformed_cached_file_raises_clear_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "models" / "2026-04-27.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("definitely not json", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)  # never reached

    client = _client(handler)
    with pytest.raises(ValueError, match="malformed"):
        fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)


# ---------------------------------------------------------------------------
# fetch_model_endpoints
# ---------------------------------------------------------------------------


def test_fetch_model_endpoints_uses_author_slug_in_cache_path(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    client = _client(handler)
    fetch_model_endpoints(
        "openai",
        "gpt-5",
        as_of_date=AS_OF,
        cache_dir=tmp_path,
        client=client,
    )

    cache_path = tmp_path / "endpoints" / "openai" / "gpt-5" / "2026-04-27.json"
    assert cache_path.exists()


def test_fetch_model_endpoints_calls_correct_url(tmp_path: Path) -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"data": {}})

    client = _client(handler)
    fetch_model_endpoints(
        "anthropic",
        "claude-opus-4-7",
        as_of_date=AS_OF,
        cache_dir=tmp_path,
        client=client,
    )

    assert (
        captured_urls[0]
        == "https://openrouter.ai/api/v1/models/anthropic/claude-opus-4-7/endpoints"
    )


def test_fetch_model_endpoints_cache_keyed_by_author_slug_pair(
    tmp_path: Path,
) -> None:
    """Different (author, slug) pairs do not collide on cache."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": str(request.url)})

    client = _client(handler)
    fetch_model_endpoints(
        "openai",
        "gpt-5",
        as_of_date=AS_OF,
        cache_dir=tmp_path,
        client=client,
    )
    fetch_model_endpoints(
        "anthropic",
        "claude-opus-4-7",
        as_of_date=AS_OF,
        cache_dir=tmp_path,
        client=client,
    )

    assert (tmp_path / "endpoints" / "openai" / "gpt-5" / "2026-04-27.json").exists()
    assert (tmp_path / "endpoints" / "anthropic" / "claude-opus-4-7" / "2026-04-27.json").exists()


# ---------------------------------------------------------------------------
# fetch_rankings
# ---------------------------------------------------------------------------


def test_fetch_rankings_uses_jampongsathorn_mirror_url(
    tmp_path: Path,
) -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    fetch_rankings(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert "jampongsathorn/openrouter-rankings" in captured_urls[0]
    assert "latest.json" in captured_urls[0]


def test_fetch_rankings_caches_under_rankings_kind(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    fetch_rankings(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert (tmp_path / "rankings" / "2026-04-27.json").exists()


# ---------------------------------------------------------------------------
# User-Agent + URL targeting
# ---------------------------------------------------------------------------


def test_user_agent_header_sent_on_request(tmp_path: Path) -> None:
    captured_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    # httpx normalises header names to lowercase.
    assert captured_headers[0].get("user-agent") == USER_AGENT


def test_fetch_models_calls_correct_url(tmp_path: Path) -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    fetch_models(as_of_date=AS_OF, cache_dir=tmp_path, client=client)

    assert captured_urls[0] == "https://openrouter.ai/api/v1/models"
