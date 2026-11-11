"""The HTTP layer on its own: validation, error shape, limits, headers. No network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

ORIGIN = "http://localhost:5173"


async def test_health_config_and_root(client: httpx.AsyncClient) -> None:
    health = (await client.get("/health")).json()
    assert health["status"] == "ok" and health["active_jobs"] == 0
    config = (await client.get("/api/v1/config")).json()
    assert config["sources"]["mode"] == "allowlist" and "archive.org" in config["sources"]["domains"]
    assert config["limits"]["max_file_size_bytes"] > 0 and config["capabilities"]["subtitle_formats"] == ["srt", "vtt"]
    for example in config["sources"]["examples"]:     # examples only ever point at enabled sources
        host = example["url"].split("/")[2]
        assert any(host == d or host.endswith("." + d) for d in config["sources"]["domains"])
    assert (await client.get("/")).json()["health"] == "/health"
    assert (await client.get("/openapi.json")).status_code == 200


@pytest.mark.parametrize(("url", "code"), [
    ("not a url", "invalid_url"),
    ("ftp://example.com/v.mp4", "unsupported_scheme"),
    ("file:///etc/passwd", "unsupported_scheme"),
    ("http://localhost/admin", "blocked_destination"),
    ("http://169.254.169.254/latest/meta-data/", "blocked_destination"),
    ("http://10.0.0.5/video.mp4", "blocked_destination"),
    ("http://[::1]:8000/", "blocked_destination"),
    ("https://user:pw@archive.org/x", "invalid_url"),
    ("https://www.youtube.com/watch?v=abc", "domain_not_allowed"),
    ("https://archive.org.evil.com/x", "domain_not_allowed"),
])
async def test_analyze_rejects_bad_links_without_touching_the_network(
    client: httpx.AsyncClient, url: str, code: str
) -> None:
    response = await client.post("/api/v1/analyze", json={"url": url})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == code and error["message"]
    assert "Traceback" not in response.text and "yt_dlp" not in response.text


@pytest.mark.parametrize("payload", [{}, {"url": ""}, {"url": "x", "extra": 1}, {"url": ["a"]}, {"url": "h" * 5000}])
async def test_request_validation(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    response = await client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error" and error["fields"]


@pytest.mark.parametrize("payload", [
    {"analysis_id": "short", "quality_id": "q1"},
    {"analysis_id": "A" * 24, "quality_id": "best[height<=720]"},        # no raw format selectors
    {"analysis_id": "A" * 24, "quality_id": "q1", "embed_subtitles": ["en; rm -rf /"]},
    {"analysis_id": "A" * 24, "quality_id": "q1", "embed_subtitles": ["s1"] * 9},
    {"analysis_id": "../../../etc/passwd....", "quality_id": "q1"},
])
async def test_job_request_validation(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    response = await client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


async def test_unknown_resources(client: httpx.AsyncClient) -> None:
    cases = {
        ("GET", "/api/v1/nope"): (404, "not_found_route"),
        ("GET", "/api/v1/jobs/" + "x" * 24): (404, "job_not_found"),
        ("DELETE", "/api/v1/jobs/" + "x" * 24): (404, "job_not_found"),
        ("GET", "/api/v1/jobs/" + "x" * 24 + "/file"): (404, "job_not_found"),
        ("GET", "/api/v1/jobs/..%2F..%2Fetc%2Fpasswdxxxxxxx"): (404, "not_found_route"),
        ("GET", "/api/v1/analyses/" + "x" * 24 + "/thumbnail"): (410, "analysis_expired"),
        ("GET", "/api/v1/analyses/" + "x" * 24 + "/subtitles/s1"): (410, "analysis_expired"),
        ("PUT", "/api/v1/analyze"): (405, "method_not_allowed"),
    }
    for (method, path), (status, code) in cases.items():
        response = await client.request(method, path)
        assert (response.status_code, response.json()["error"]["code"]) == (status, code), path
    missing = await client.post("/api/v1/jobs", json={"analysis_id": "A" * 24, "quality_id": "q1"})
    assert (missing.status_code, missing.json()["error"]["code"]) == (410, "analysis_expired")


async def test_body_size_limit(client: httpx.AsyncClient) -> None:
    big = b'{"url":"' + b"a" * 40_000 + b'"}'
    response = await client.post("/api/v1/analyze", content=big, headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.json()["error"]["code"] == "payload_too_large"

    async def chunks() -> Any:        # no Content-Length: must be stopped while streaming
        for _ in range(40):
            yield b"a" * 1000

    streamed = await client.post("/api/v1/analyze", content=chunks(), headers={"content-type": "application/json"})
    assert streamed.status_code == 413


async def test_security_headers_and_cors(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/analyze", json={"url": "ftp://x"}, headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN       # errors are readable by the frontend
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY" and len(response.headers["x-request-id"]) == 16
    assert "access-control-allow-credentials" not in response.headers

    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    allowed = await client.options("/api/v1/analyze", headers={"Origin": ORIGIN, **preflight})
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == ORIGIN
    denied = await client.options("/api/v1/analyze", headers={"Origin": "https://evil.example", **preflight})
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
    other = await client.post("/api/v1/analyze", json={"url": "ftp://x"}, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


async def test_rate_limit_per_client(make_client: Callable[..., Any]) -> None:
    client = await make_client(rate_limit_enabled=True, rate_limit_analyze="3/minute", trusted_proxy_hops=1)
    alice = {"X-Forwarded-For": "6.6.6.6, 203.0.113.1"}       # the left-most entry is client-controlled
    statuses = [(await client.post("/api/v1/analyze", json={"url": "ftp://x"}, headers=alice)).status_code
                for _ in range(4)]
    assert statuses == [422, 422, 422, 429]
    limited = await client.post("/api/v1/analyze", json={"url": "ftp://x"}, headers=alice)
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1 and limited.headers["x-ratelimit-remaining"] == "0"
    # Changing the spoofable part of the header doesn't help; a different real client is unaffected.
    spoof = {"X-Forwarded-For": "7.7.7.7, 203.0.113.1"}
    assert (await client.post("/api/v1/analyze", json={"url": "ftp://x"}, headers=spoof)).status_code == 429
    bob = {"X-Forwarded-For": "203.0.113.2"}
    assert (await client.post("/api/v1/analyze", json={"url": "ftp://x"}, headers=bob)).status_code == 422


async def test_docs_can_be_disabled(make_client: Callable[..., Any]) -> None:
    client = await make_client(enable_docs=False)
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


async def test_open_policy_lists_no_domains(make_client: Callable[..., Any]) -> None:
    client = await make_client(source_policy="open", blocked_domains=["blocked.example.com"])
    sources = (await client.get("/api/v1/config")).json()["sources"]
    assert sources["mode"] == "open" and sources["domains"] == []
    blocked = await client.post("/api/v1/analyze", json={"url": "https://blocked.example.com/v"})
    assert blocked.json()["error"]["code"] == "domain_not_allowed"
