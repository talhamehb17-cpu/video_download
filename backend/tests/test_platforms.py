"""Platforms: the catalog, matching links to platforms, the source policy and compatibility checks."""

from __future__ import annotations

import json
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.errors import AppError
from app.platforms.catalog import CATALOG
from app.platforms.registry import CheckResult, PlatformRegistry, host_matches, normalise_domain
from app.security.url_validation import SourcePolicy, validate_url_syntax
from app.services.compat import interpret


# ------------------------------------------------------------------------------ catalog
def test_catalog_is_consistent() -> None:
    ids = [entry.id for entry in CATALOG]
    assert len(ids) == len(set(ids))
    domains = [domain for entry in CATALOG for domain in entry.domains]
    assert len(domains) == len(set(domains)), "an address belongs to exactly one platform"
    for entry in CATALOG:
        assert entry.domains and entry.name
        if entry.support != "full":
            assert entry.note, f"{entry.id}: limits must be explained"
    names = {entry.name for entry in CATALOG}
    for wanted in ("YouTube", "Instagram", "Facebook", "TikTok", "X (Twitter)", "Vimeo", "Dailymotion", "Reddit",
                   "Pinterest", "Twitch", "Niconico", "Bilibili"):
        assert wanted in names


@pytest.mark.parametrize(("host", "expected"), [
    ("www.youtube.com", "YouTube"), ("m.youtube.com", "YouTube"), ("youtu.be", "YouTube"),
    ("music.youtube.com", "YouTube"), ("vm.tiktok.com", "TikTok"), ("mobile.twitter.com", "X (Twitter)"),
    ("x.com", "X (Twitter)"), ("fb.watch", "Facebook"), ("old.reddit.com", "Reddit"), ("v.redd.it", "Reddit"),
    ("pinterest.com", "Pinterest"), ("pinterest.co.uk", "Pinterest"), ("www.pinterest.de", "Pinterest"),
    ("pin.it", "Pinterest"), ("clips.twitch.tv", "Twitch"), ("www.nicovideo.jp", "Niconico"),
    ("www.bilibili.com", "Bilibili"), ("commons.wikimedia.org", "Wikimedia Commons"),
    ("www.netflix.com", "Netflix"),
    # look-alikes and unrelated names belong to nobody
    ("notyoutube.com", None), ("youtube.com.evil.example", None), ("pinterest.evil.example.com", None),
    ("notpinterest.com", None), ("naver.com", None), ("example.org", None),
])
def test_links_are_matched_to_platforms(host: str, expected: str | None) -> None:
    platform = PlatformRegistry(None).match(host)
    assert (platform.name if platform else None) == expected


def test_host_patterns_and_domain_normalisation() -> None:
    assert host_matches("a.b.example.com", "example.com") and not host_matches("badexample.com", "example.com")
    assert host_matches("pinterest.com.mx", "pinterest.*") and not host_matches("pinterest.example.com", "pinterest.*")
    assert normalise_domain("https://WWW.Example.com/watch?v=1") == "example.com"
    assert normalise_domain("http://user:pw@a.b.example.com:8080/x") == "a.b.example.com"
    assert normalise_domain("m.site.co.uk") == "site.co.uk"
    for bad in ("localhost", "exa mple.com", "1.2.3.4", "-bad.com", "", "http://"):
        assert normalise_domain(bad) is None


# ------------------------------------------------------------------------------- policy
def _code(url: str, policy: SourcePolicy) -> str | None:
    try:
        validate_url_syntax(url, policy)
    except AppError as exc:
        return exc.code
    return None


def test_platform_policy_decides_per_platform() -> None:
    registry = PlatformRegistry(None)
    policy = SourcePolicy(mode="platforms", platforms=registry)
    assert _code("https://www.youtube.com/watch?v=x", policy) is None
    assert _code("https://vimeo.com/1", policy) is None
    assert _code("https://videos.example.org/1", policy) == "domain_not_allowed"
    assert _code("https://www.netflix.com/watch/1", policy) == "platform_unsupported"

    youtube = registry.get("youtube")
    assert youtube is not None
    registry.set_enabled(youtube, False)
    with pytest.raises(AppError) as refused:
        validate_url_syntax("https://youtu.be/x", policy)
    assert refused.value.code == "platform_disabled" and "YouTube" in refused.value.message
    registry.set_enabled(youtube, True)
    assert _code("https://youtu.be/x", policy) is None

    # a website the administrator added counts only once it is switched on
    site = registry.add("videos.example.org")
    assert _code("https://videos.example.org/1", policy) == "domain_not_allowed"
    registry.set_enabled(site, True)
    assert _code("https://cdn.videos.example.org/1", policy) is None
    # ... and never when a check found that nothing there can be downloaded
    registry.set_check(site, CheckResult(at=time.time(), status="unsupported", summary="nothing"))
    assert site.enabled is False and _code("https://videos.example.org/1", policy) == "domain_not_allowed"


def test_other_modes_and_the_block_list() -> None:
    registry = PlatformRegistry(None)
    youtube = registry.get("youtube")
    assert youtube is not None
    registry.set_enabled(youtube, False)

    allowlist = SourcePolicy(mode="allowlist", allowed_domains=("youtube.com", "netflix.com"), platforms=registry)
    assert _code("https://www.youtube.com/watch?v=x", allowlist) is None, "the allow list ignores the switches"
    assert _code("https://vimeo.com/1", allowlist) == "domain_not_allowed"
    assert _code("https://www.netflix.com/watch/1", allowlist) == "platform_unsupported", "DRM is never possible"

    open_policy = SourcePolicy(mode="open", blocked_domains=("vimeo.com",), platforms=registry)
    assert _code("https://anything.example.org/1", open_policy) is None
    assert _code("https://www.youtube.com/watch?v=x", open_policy) == "platform_disabled"
    assert _code("https://vimeo.com/1", open_policy) == "domain_not_allowed", "the block list always wins"
    blocked = SourcePolicy(mode="platforms", blocked_domains=("vimeo.com",), platforms=registry)
    assert _code("https://player.vimeo.com/video/1", blocked) == "domain_not_allowed"


# ---------------------------------------------------------------------------- registry
def test_settings_survive_a_restart(tmp_path: Path) -> None:
    registry = PlatformRegistry(tmp_path)
    assert registry.persistent and not (tmp_path / "platforms.json").exists()
    tiktok = registry.get("tiktok")
    assert tiktok is not None and tiktok.enabled
    registry.set_enabled(tiktok, False)
    site = registry.add("videos.example.org", "Example Videos")
    registry.set_enabled(site, True)
    registry.set_check(site, CheckResult(at=1.0, status="requires_review", summary="generic", method="generic"))
    path = tmp_path / "platforms.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not list(tmp_path.glob(".platforms-*")), "no temporary file is left behind"

    again = PlatformRegistry(tmp_path)
    assert again.get("tiktok").enabled is False  # type: ignore[union-attr]
    restored = again.match("www.videos.example.org")
    assert restored is not None and restored.name == "Example Videos" and restored.enabled and not restored.builtin
    assert restored.check is not None and restored.check.method == "generic" and restored.status == "requires_review"
    assert again.get("youtube").enabled is True  # type: ignore[union-attr]

    again.remove(restored)
    assert PlatformRegistry(tmp_path).match("videos.example.org") is None
    builtin = again.get("youtube")
    again.remove(builtin)  # type: ignore[arg-type]
    assert again.get("youtube") is not None, "built-in platforms cannot be removed"


def test_broken_or_hostile_settings_files_are_survived(tmp_path: Path) -> None:
    (tmp_path / "platforms.json").write_text("{not json")
    assert PlatformRegistry(tmp_path).get("youtube") is not None
    (tmp_path / "platforms.json").write_text(json.dumps({
        "overrides": {"netflix": {"enabled": True}, "nope": {"enabled": True}, "youtube": "x"},
        "custom": [{"domains": ["youtube.com"], "enabled": True}, {"domains": ["localhost"]}, "x",
                   {"domains": ["ok.example.org"], "enabled": True, "check": {"status": "bogus"}}],
    }))
    registry = PlatformRegistry(tmp_path)
    netflix = registry.get("netflix")
    assert netflix is not None and not netflix.active, "a DRM platform cannot be switched on through the file"
    assert [p.domains for p in registry.all() if not p.builtin] == [("ok.example.org",)]
    assert registry.match("ok.example.org").check is None  # type: ignore[union-attr]


def test_read_only_data_directory_is_reported(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    registry = PlatformRegistry(blocker / "data")  # cannot be created: its parent is a file
    registry.set_enabled(registry.get("vimeo"), False)  # type: ignore[arg-type]
    assert registry.persistent is False and registry.get("vimeo").enabled is False  # type: ignore[union-attr]


def test_status_follows_checks_but_respects_known_limits() -> None:
    registry = PlatformRegistry(None)
    youtube, dailymotion = registry.get("youtube"), registry.get("dailymotion")
    assert youtube is not None and dailymotion is not None
    assert youtube.status == "partial" and dailymotion.status == "supported"
    ok = CheckResult(at=1.0, status="supported", summary="ok", method="extractor")
    registry.set_check(youtube, ok)
    registry.set_check(dailymotion, ok)
    assert youtube.status == "partial", "one working link does not lift the known limits"
    assert dailymotion.status == "supported"
    registry.set_check(dailymotion, CheckResult(at=2.0, status="requires_review", summary="turned away"))
    assert dailymotion.status == "requires_review" and dailymotion.active, "it stays on until the admin decides"


def test_a_check_that_learned_nothing_changes_no_status() -> None:
    registry = PlatformRegistry(None)
    nasa, dailymotion = registry.get("nasa"), registry.get("dailymotion")
    assert nasa is not None and dailymotion is not None
    nothing = CheckResult(at=3.0, status="requires_review", summary="no link to test", conclusive=False)
    registry.set_check(nasa, nothing)
    registry.set_check(dailymotion, nothing)
    assert nasa.status == "partial" and dailymotion.status == "supported", "the catalog's expectation stays"
    assert nasa.check is nothing and nasa.active, "the administrator still sees what happened"
    site = registry.add("videos.example.org")
    registry.set_check(site, nothing)
    assert site.status == "requires_review" and not site.enabled


def test_sample_links_are_the_platforms_own_ordinary_pages() -> None:
    from urllib.parse import urlsplit

    from app.worker.tasks import MAX_SAMPLE_LINKS, find_integrations

    names, samples = find_integrations(["archive.org"], None)
    assert names and 1 <= len(samples) <= MAX_SAMPLE_LINKS
    hosts = [urlsplit(link).hostname or "" for link in samples]
    assert all(host_matches(host, "archive.org") for host in hosts)
    assert hosts[0].removeprefix("www.") == "archive.org", "the website's own address before its sub-domains"
    assert len(set(samples)) == len(samples)
    # a website nobody wrote an integration for has nothing to test with
    assert find_integrations(["no-integration.invalid"], None) == ([], [])


# ------------------------------------------------------------------------ check results
def _attempt(**values: Any) -> dict[str, Any]:
    return {"url": "https://videos.example.org/1", **values}


def test_check_results_are_interpreted() -> None:
    def state(
        result: dict[str, Any], url: str | None = "https://videos.example.org/1", catalogued: bool = False
    ) -> CheckResult:
        return interpret(result, given_url=url, seconds=1.2, catalogued=catalogued)

    good = state({"integrations": ["vimeo"], "attempts": [
        _attempt(ok=True, extractor="Vimeo", streams=6, video=5, audio=1, max_height=1080, subtitles=2, title="T"),
    ]})
    assert (good.status, good.method, good.max_height, good.qualities) == ("supported", "extractor", 1080, 6)
    assert "1080p" in good.summary and good.error_code is None

    audio = state({"integrations": ["x"], "attempts": [_attempt(ok=True, extractor="X", streams=1, video=0)]})
    assert audio.status == "partial"

    for reader in ("Generic", "HTML5MediaEmbed", "Vimeo"):  # the last one: a player embedded from elsewhere
        generic = state({"integrations": [], "attempts": [_attempt(ok=True, extractor=reader, streams=1, video=1)]})
        assert (generic.status, generic.method, generic.extractor) == ("requires_review", "generic", None)
        assert "allows" in generic.summary and generic.conclusive
        # a platform of the catalog was already approved by a person: reading a video is what counts
        listed = state({"integrations": [], "attempts": [_attempt(ok=True, extractor=reader, streams=1, video=1)]},
                       catalogued=True)
        assert (listed.status, listed.method, listed.qualities) == ("partial", "generic", 1) and listed.conclusive

    nothing = state({"integrations": [], "attempts": [_attempt(ok=False, code="unsupported_source")]})
    assert nothing.status == "unsupported" and nothing.error_code == "unsupported_source"

    drm = state({"integrations": ["s"], "attempts": [_attempt(ok=False, code="drm_protected")]})
    assert drm.status == "unsupported"

    for code in ("login_required", "verification_required", "geo_restricted", "source_forbidden"):
        away = state({"integrations": ["s"], "attempts": [_attempt(ok=False, code=code)]})
        assert away.status == "requires_review" and away.error_code == code
        assert "turned this server away" in away.summary

    samples = state({"integrations": ["s"], "attempts": [
        _attempt(ok=False, code="not_found"), _attempt(ok=False, code="not_found"),
    ]}, url=None)
    # a video that is gone says nothing about the platform
    assert samples.status == "requires_review" and "2 sample links" in samples.summary and not samples.conclusive
    again = state({"integrations": [], "sample_links": False, "attempts": [_attempt(ok=False, code="not_found")]},
                  url=None)
    assert "behind the link" in again.summary, "the link of an earlier check is not called a sample link"
    both = state({"integrations": ["s"], "previous_link": True, "attempts": [
        _attempt(ok=False, code="login_required"), _attempt(ok=False, code="login_required"),
    ]}, url=None)
    assert "for 2 links" in both.summary and both.conclusive, "an earlier link and a sample link are just links"
    # sample links that ended differently: what happened to most of them is reported, and counted honestly
    mixed = state({"integrations": ["s"], "attempts": [
        _attempt(ok=False, code="not_found"),
        {"url": "https://videos.example.org/2", "ok": False, "code": "login_required"},
        {"url": "https://videos.example.org/3", "ok": False, "code": "login_required"},
    ]}, url=None)
    assert mixed.error_code == "login_required" and mixed.url == "https://videos.example.org/2"
    assert "2 of 3 sample links" in mixed.summary and "turned this server away" in mixed.summary
    tie = state({"integrations": ["s"], "attempts": [
        _attempt(ok=False, code="source_unreachable"), _attempt(ok=False, code="login_required"),
    ]}, url=None)
    assert tie.error_code == "source_unreachable" and "1 of 2 sample links" in tie.summary

    # nothing was tested: nothing was learned
    untested = state({"integrations": ["s"], "attempts": []}, url=None)
    assert untested.status == "requires_review" and not untested.conclusive
    unknown = state({"integrations": [], "attempts": []}, url=None)
    assert unknown.status == "requires_review" and unknown.method == "none" and "Paste a link" in unknown.summary
    assert not unknown.conclusive
    listed = state({"integrations": [], "attempts": []}, url=None, catalogued=True)
    assert not listed.conclusive and "no sample links" in listed.summary
    # no upstream text ever reaches the summary
    odd = state({"integrations": ["s"], "attempts": [_attempt(ok=False, code="extraction_failed", detail="<b>x</b>")]})
    assert "<b>" not in odd.summary and odd.error_message


# -------------------------------------------------------------------------- public API
async def test_public_platform_list(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client()
    body = (await client.get("/api/v1/platforms")).json()
    assert body["mode"] == "platforms"
    by_id = {p["id"]: p for p in body["platforms"]}
    assert by_id["youtube"]["enabled"] and by_id["youtube"]["status"] == "partial" and by_id["youtube"]["note"]
    assert by_id["dailymotion"]["status"] == "supported" and "dai.ly" in by_id["dailymotion"]["domains"]
    assert by_id["netflix"] == {
        "id": "netflix", "name": "Netflix", "domains": ["netflix.com"], "status": "unsupported", "enabled": False,
        "verified": False, "checked_at": None,
        "note": "Protected with DRM. Lumora never circumvents DRM.", "region": "drm",
    }
    assert not any(p["verified"] for p in body["platforms"]), "nothing is verified before a check has run"
    assert (await client.get("/api/v1/config")).json()["capabilities"]["platform_list"] is True
    assert {p["status"] for p in body["platforms"]} <= {"supported", "partial", "unsupported"}

    narrowed = await make_client(source_policy="allowlist", allowed_domains=["archive.org", "videos.example.org"])
    answer = (await narrowed.get("/api/v1/platforms")).json()
    listed = {p["id"]: p["enabled"] for p in answer["platforms"]}
    assert answer["mode"] == "allowlist" and listed["internet-archive"] is True and listed["youtube"] is False
    # a domain the operator allows is accepted even though no platform is known for it, and the list says so
    extra = next(p for p in answer["platforms"] if p["domains"] == ["videos.example.org"])
    assert extra["enabled"] is True and extra["status"] == "partial" and extra["verified"] is False
    assert extra["id"] == "allowed-videos-example-org" and "operator" in extra["note"]
    assert sum(1 for p in answer["platforms"] if p["enabled"]) == 2

    blocked = await make_client(blocked_domains=["tiktok.com"])
    listed = {p["id"]: p["enabled"] for p in (await blocked.get("/api/v1/platforms")).json()["platforms"]}
    assert listed["tiktok"] is False and listed["youtube"] is True


async def test_refusals_name_the_platform(client: httpx.AsyncClient) -> None:
    drm = (await client.post("/api/v1/analyze", json={"url": "https://www.netflix.com/watch/1"}))
    assert drm.status_code == 422
    assert drm.json()["error"] == {
        "code": "platform_unsupported", "message": "Netflix videos can't be downloaded.",
        "hint": "Protected with DRM. Lumora never circumvents DRM.",
    }
    unknown = (await client.post("/api/v1/analyze", json={"url": "https://videos.example.org/1"})).json()["error"]
    assert unknown["code"] == "domain_not_allowed" and "isn't enabled" in unknown["message"]


async def test_wrong_method_says_which_one_works(client: httpx.AsyncClient) -> None:
    """Opening an API address in a browser tab is a GET request; the answer has to say so."""
    response = await client.get("/api/v1/analyze")
    assert response.status_code == 405 and response.headers["allow"] == "POST"
    error = response.json()["error"]
    assert error["code"] == "method_not_allowed" and "GET" in error["message"]
    assert "POST" in error["hint"] and "browser" in error["hint"]
    assert (await client.delete("/api/v1/config")).status_code == 405
    # the website's own request is a POST with a JSON body, and a wrong body is explained field by field
    wrong = await client.post("/api/v1/analyze", json={"link": "https://archive.org/details/x"})
    assert wrong.status_code == 422
    assert {f["field"] for f in wrong.json()["error"]["fields"]} == {"url", "link"}
