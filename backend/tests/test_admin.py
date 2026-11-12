"""The administrator: sign-in, sessions, password changes, platform management, storage limits."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.api.admin import router as admin_router
from app.platforms.registry import CheckResult, Platform
from app.services.compat import CompatibilityChecker
from app.services.storage import TempStorage

EMAIL = "owner@example.com"
FIRST = "first-password-123"
NEW = "a much better passphrase"
ADMIN = {"admin_email": EMAIL, "admin_bootstrap_password": FIRST}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_in(client: httpx.AsyncClient, password: str = FIRST, email: str = EMAIL) -> httpx.Response:
    return await client.post("/api/v1/admin/login", json={"email": email, "password": password})


async def ready_admin(client: httpx.AsyncClient) -> dict[str, str]:
    """Sign in, replace the initial password, return the headers of the new session."""
    token = (await sign_in(client)).json()["token"]
    changed = await client.post(
        "/api/v1/admin/password", headers=bearer(token), json={"current_password": FIRST, "new_password": NEW}
    )
    assert changed.status_code == 200, changed.text
    return bearer(changed.json()["token"])


# ------------------------------------------------------------------------------ access
async def test_admin_is_off_until_configured(client: httpx.AsyncClient) -> None:
    response = await sign_in(client)
    assert response.status_code == 503 and response.json()["error"]["code"] == "admin_not_configured"
    assert (await client.get("/api/v1/admin/overview", headers=bearer("x" * 43))).status_code == 503
    status = await client.get("/api/v1/admin/status")
    assert status.status_code == 200 and status.json() == {"configured": False}
    assert status.headers["cache-control"] == "no-store"


async def test_status_tells_the_page_whether_signing_in_is_possible(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    status = await client.get("/api/v1/admin/status")
    # nothing but that one fact: no address, no version, no account name
    assert status.status_code == 200 and status.json() == {"configured": True}
    assert "/api/v1/admin" not in (await client.get("/openapi.json")).text


async def test_every_admin_route_needs_a_session(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    checked = 0
    for route in admin_router.routes:
        path = route.path.replace("{platform_id}", "youtube")  # type: ignore[attr-defined]
        for method in route.methods - {"HEAD", "OPTIONS"}:  # type: ignore[attr-defined]
            if path.endswith(("/login", "/status")):
                continue  # the two addresses that exist for people who are not signed in
            for headers in ({}, bearer("not-a-real-token"), {"Authorization": "Basic b3duZXI6eA=="},
                            {"Cookie": "token=abc"}):
                response = await client.request(method, path, headers=headers, json={})
                assert response.status_code == 401, f"{method} {path} answered {response.status_code}"
                assert response.json()["error"]["code"] == "not_authenticated"
                assert response.headers["cache-control"] == "no-store"
            checked += 1
    assert checked >= 9
    # a token in the address is not a session either
    assert (await client.get("/api/v1/admin/overview?token=abc&access_token=abc")).status_code == 401


async def test_sign_in_and_forced_password_change(make_client: Callable[..., Any], tmp_path: Path) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    for attempt in (await sign_in(client, "wrong"), await sign_in(client, FIRST, "other@example.com")):
        assert attempt.status_code == 401 and attempt.json()["error"]["code"] == "invalid_credentials"
        assert "token" not in attempt.text

    response = await sign_in(client, FIRST, "  Owner@Example.COM ")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    session = response.json()
    assert session["email"] == EMAIL and session["must_change_password"] is True and len(session["token"]) >= 40
    first = bearer(session["token"])

    # until the password is replaced, only the session itself can be used
    for path in ("/api/v1/admin/overview", "/api/v1/admin/platforms"):
        blocked = await client.get(path, headers=first)
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"
    assert (await client.patch("/api/v1/admin/platforms/youtube", headers=first, json={"enabled": False})
            ).status_code == 403
    assert (await client.get("/api/v1/admin/session", headers=first)).json()["token"] is None

    async def change(current: str, new: str) -> httpx.Response:
        return await client.post("/api/v1/admin/password", headers=first,
                                 json={"current_password": current, "new_password": new})

    assert (await change("wrong", NEW)).status_code == 401
    for weak in ("short", FIRST, EMAIL, "x" * 200):
        refused = await change(FIRST, weak)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "weak_password", weak
    changed = await change(FIRST, NEW)
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    fresh = bearer(changed.json()["token"])

    assert (await client.get("/api/v1/admin/session", headers=first)).status_code == 401, "old sessions end"
    assert (await client.get("/api/v1/admin/overview", headers=fresh)).status_code == 200
    assert (await sign_in(client, FIRST)).status_code == 401, "the initial password never works again"
    assert (await sign_in(client, NEW)).json()["must_change_password"] is False

    stored = (client.app.state.services.settings.data_dir / "admin.json").read_text()  # type: ignore[attr-defined]
    assert FIRST not in stored and NEW not in stored and "scrypt$" in stored

    assert (await client.post("/api/v1/admin/logout", headers=fresh)).status_code == 204
    assert (await client.get("/api/v1/admin/session", headers=fresh)).status_code == 401


async def test_password_survives_a_restart_and_bootstrap_does_not_return(make_client: Callable[..., Any]) -> None:
    first: httpx.AsyncClient = await make_client(**ADMIN)
    await ready_admin(first)
    data_dir = first.app.state.services.settings.data_dir  # type: ignore[attr-defined]
    second: httpx.AsyncClient = await make_client(**ADMIN, data_dir=data_dir)
    assert (await sign_in(second, FIRST)).status_code == 401
    assert (await sign_in(second, NEW)).status_code == 200


async def test_repeated_failures_pause_sign_in(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN, admin_max_failed_logins=3)
    assert [(await sign_in(client, "bad")).status_code for _ in range(3)] == [401, 401, 401]
    paused = await sign_in(client, FIRST)  # even the right password has to wait now
    assert paused.status_code == 429 and paused.json()["error"]["code"] == "too_many_attempts"
    assert 1 <= int(paused.headers["retry-after"]) <= 61 and paused.json()["error"]["retry_after"] >= 1


async def test_sign_in_is_rate_limited_per_address(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN, rate_limit_enabled=True, rate_limit_admin_login="2/minute")
    codes = [(await sign_in(client, "bad")).json()["error"]["code"] for _ in range(3)]
    assert codes == ["invalid_credentials", "invalid_credentials", "rate_limited"]


async def test_sessions_end_when_unused(make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN, admin_session_minutes=5)
    headers = await ready_admin(client)
    assert 0 < (await client.get("/api/v1/admin/session", headers=headers)).json()["expires_in"] <= 300
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 301)
    assert (await client.get("/api/v1/admin/session", headers=headers)).status_code == 401


async def test_browser_preflight_allows_the_admin_requests(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    for method in ("POST", "PATCH", "DELETE"):
        response = await client.options("/api/v1/admin/platforms/youtube", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        allowed = response.headers["access-control-allow-headers"].lower()
        assert response.status_code == 200 and "authorization" in allowed
    foreign = await client.options("/api/v1/admin/login", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in foreign.headers


# ---------------------------------------------------------------------------- platforms
async def test_switching_platforms_on_and_off(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    headers = await ready_admin(client)
    listing = (await client.get("/api/v1/admin/platforms", headers=headers)).json()
    assert listing["mode"] == "platforms" and listing["persistent"] is True
    youtube = next(p for p in listing["platforms"] if p["id"] == "youtube")
    assert youtube["enabled"] and youtube["active"] and youtube["expected"] == "partial" and youtube["check"] is None

    off = await client.patch("/api/v1/admin/platforms/youtube", headers=headers, json={"enabled": False})
    assert off.status_code == 200 and off.json()["active"] is False
    refused = await client.post("/api/v1/analyze", json={"url": "https://www.youtube.com/watch?v=abc"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "platform_disabled"
    assert "YouTube" in refused.json()["error"]["message"]
    public = {p["id"]: p["enabled"] for p in (await client.get("/api/v1/platforms")).json()["platforms"]}
    assert public["youtube"] is False
    assert "youtube.com" not in (await client.get("/api/v1/config")).json()["sources"]["domains"]
    await client.patch("/api/v1/admin/platforms/youtube", headers=headers, json={"enabled": True})
    assert (await client.get("/api/v1/platforms")).json()["platforms"][5]["enabled"] is True

    drm = await client.patch("/api/v1/admin/platforms/netflix", headers=headers, json={"enabled": True})
    assert drm.status_code == 409 and drm.json()["error"]["code"] == "platform_locked"
    assert "DRM" in drm.json()["error"]["hint"]
    assert (await client.post("/api/v1/admin/platforms/netflix/check", headers=headers, json={})).status_code == 409
    assert (await client.delete("/api/v1/admin/platforms/youtube", headers=headers)).status_code == 409
    assert (await client.patch("/api/v1/admin/platforms/nope", headers=headers, json={"enabled": True})
            ).status_code == 404
    assert (await client.patch("/api/v1/admin/platforms/youtube", headers=headers, json={"enabled": "maybe"})
            ).status_code == 422
    wrong_site = await client.post("/api/v1/admin/platforms/youtube/check", headers=headers,
                                   json={"url": "https://vimeo.com/1"})
    assert wrong_site.status_code == 422 and "doesn't belong to YouTube" in wrong_site.json()["error"]["message"]

    overview = (await client.get("/api/v1/admin/overview", headers=headers)).json()
    assert overview["mode"] == "platforms" and overview["max_file_size_bytes"] == 1536 * 1024 * 1024
    assert overview["counts"]["unsupported"] >= 8 and overview["counts"]["enabled"] >= 40
    assert overview["disk"]["free_bytes"] > 0 and overview["disk"]["floor_bytes"] == 0 and overview["errors"] == []
    assert overview["extractor_version"][:2] == "20"


@pytest.mark.parametrize("target", [
    "localhost", "http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/v",
    "https://intranet.local/video", "not a domain", "ftp://example.org/v.mp4", "https://user:pw@example.org/v",
])
async def test_internal_and_malformed_targets_cannot_be_added(make_client: Callable[..., Any], target: str) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    headers = await ready_admin(client)
    response = await client.post("/api/v1/admin/platforms", headers=headers, json={"target": target})
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] in ("blocked_destination", "invalid_url", "unsupported_scheme")
    if target in ("localhost", "not a domain"):
        # the message asks for a domain or a link; no hint may contradict it
        assert error == {
            "code": "invalid_url", "message": "Enter a domain like example.com, or a link to a video page.",
        }
    assert all(p["builtin"] for p in (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"])


async def wait_for_check(client: httpx.AsyncClient, headers: dict[str, str], platform_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        platforms = (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"]
        platform: dict[str, Any] = next(p for p in platforms if p["id"] == platform_id)
        if not platform["checking"]:
            return platform
        await asyncio.sleep(0.1)
    raise AssertionError("the check did not finish")


async def test_adding_a_website_checks_it_and_leaves_it_off(make_client: Callable[..., Any], source: str) -> None:
    port = source.rsplit(":", 1)[1]
    client: httpx.AsyncClient = await make_client(**ADMIN, unsafe_allow_hosts=[f"127.0.0.1:{port}"])
    headers = await ready_admin(client)

    added = await client.post("/api/v1/admin/platforms", headers=headers,
                              json={"target": f"{source}/watch/demo", "name": "Sample source"})
    assert added.status_code == 201, added.text
    platform = added.json()
    assert platform["builtin"] is False and platform["enabled"] is False and platform["checking"] is True
    assert platform["status"] == "requires_review" and platform["name"] == "Sample source"
    busy = await client.post(f"/api/v1/admin/platforms/{platform['id']}/check", headers=headers, json={})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "check_in_progress"

    checked = await wait_for_check(client, headers, platform["id"])
    check = checked["check"]
    # a plain page with a video: read by the generic reader, so a person has to approve it
    assert checked["status"] == "requires_review" and check["method"] == "generic" and check["qualities"] >= 1
    assert check["max_height"] and check["title"] and check["error_code"] is None
    assert checked["enabled"] is False and checked["can_enable"] is True, "a check never switches anything on"
    public = (await client.get("/api/v1/platforms")).json()["platforms"]
    assert platform["id"] not in {p["id"] for p in public}, "a website under review is not shown to visitors"

    on = await client.patch(f"/api/v1/admin/platforms/{platform['id']}", headers=headers, json={"enabled": True})
    assert on.json()["active"] is True
    shown = next(p for p in (await client.get("/api/v1/platforms")).json()["platforms"] if p["id"] == platform["id"])
    # approved by the administrator, and honest about it: a video was read, but the website is not "supported"
    assert shown["enabled"] and shown["status"] == "partial" and shown["verified"] is True and shown["checked_at"]
    assert "no dedicated integration" in shown["note"]
    again = await client.post("/api/v1/admin/platforms", headers=headers, json={"target": f"{source}/watch/webm"})
    assert again.status_code == 200 and again.json()["id"] == platform["id"], "the same website is not added twice"
    await wait_for_check(client, headers, platform["id"])

    # "Check" without a link: this website has no sample links, so the link of the last check is read again
    repeat = await client.post(f"/api/v1/admin/platforms/{platform['id']}/check", headers=headers, json={})
    assert repeat.status_code == 202
    repeated = (await wait_for_check(client, headers, platform["id"]))["check"]
    assert repeated["url"] == f"{source}/watch/webm" and repeated["qualities"] >= 1 and repeated["conclusive"] is True

    # a link that leads nowhere is reported as an error of that check
    failing = await client.post(f"/api/v1/admin/platforms/{platform['id']}/check", headers=headers,
                                json={"url": f"{source}/gone"})
    assert failing.status_code == 202
    failed = (await wait_for_check(client, headers, platform["id"]))["check"]
    assert failed["error_code"] == "not_found" and failed["error_message"] and failed["status"] == "requires_review"
    shown = next(p for p in (await client.get("/api/v1/platforms")).json()["platforms"] if p["id"] == platform["id"])
    # visitors learn that the last check did not get a video
    assert shown["verified"] is False and shown["checked_at"] == failed["at"]
    assert "last check on this server couldn't read a video" in shown["note"]

    assert (await client.delete(f"/api/v1/admin/platforms/{platform['id']}", headers=headers)).status_code == 204
    assert all(p["builtin"] for p in (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"])
    assert not list((client.app.state.services.storage.root / "analyses").iterdir()), "checks clean up"  # type: ignore[attr-defined]


async def test_a_check_with_nothing_to_test_is_not_a_finding(make_client: Callable[..., Any]) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    headers = await ready_admin(client)
    services = client.app.state.services  # type: ignore[attr-defined]
    site = services.platforms.add("no-integration.invalid", "Nothing to test")
    started = await client.post(f"/api/v1/admin/platforms/{site.id}/check", headers=headers, json={})
    assert started.status_code == 202, started.text
    checked = await wait_for_check(client, headers, site.id)
    check = checked["check"]
    assert check["conclusive"] is False and check["url"] is None and check["error_code"] is None
    assert "Paste a link" in check["summary"]
    assert checked["status"] == "requires_review" and checked["enabled"] is False

    # the same on a platform of the catalog: its status stays, and visitors are told nothing about a check
    nasa = services.platforms.get("nasa")
    services.platforms.set_check(nasa, CheckResult(
        at=time.time(), status="requires_review", summary="There are no sample links.", conclusive=False))
    listed = next(p for p in (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"]
                  if p["id"] == "nasa")
    assert listed["status"] == "partial" and listed["active"] is True and listed["check"]["conclusive"] is False
    public = next(p for p in (await client.get("/api/v1/platforms")).json()["platforms"] if p["id"] == "nasa")
    assert (public["status"], public["verified"], public["checked_at"]) == ("partial", False, None)


async def test_checking_every_enabled_platform_at_once(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client: httpx.AsyncClient = await make_client(**ADMIN)
    headers = await ready_admin(client)
    services = client.app.state.services  # type: ignore[attr-defined]
    seen: list[str] = []
    release = asyncio.Event()

    async def fake_run(self: CompatibilityChecker, platform: Platform, url: str | None) -> None:
        assert url is None, "a check of everything uses sample links"
        seen.append(platform.id)
        await release.wait()
        services.platforms.set_check(platform, CheckResult(
            at=time.time(), status="supported", summary="A public video was read.", method="extractor",
            qualities=4, max_height=1080))

    monkeypatch.setattr(CompatibilityChecker, "_run", fake_run)
    off = await client.patch("/api/v1/admin/platforms/vimeo", headers=headers, json={"enabled": False})
    assert off.status_code == 200

    answer = await client.post("/api/v1/admin/platform-checks", headers=headers)
    assert answer.status_code == 202 and answer.headers["cache-control"] == "no-store"
    active = [p.id for p in services.platforms.all() if p.active]
    assert answer.json() == {"started": len(active), "pending": len(active)} and len(active) > 30
    await asyncio.sleep(0.05)
    assert sorted(seen) == sorted(active)
    assert "vimeo" not in seen, "a platform that is switched off is left alone"
    assert "netflix" not in seen, "a DRM service is never contacted"
    listing = (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"]
    assert {p["id"] for p in listing if p["checking"]} == set(active)

    again = await client.post("/api/v1/admin/platform-checks", headers=headers)
    assert again.json() == {"started": 0, "pending": len(active)}, "nothing is checked twice at the same time"

    release.set()
    for _ in range(100):
        listing = (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"]
        if not any(p["checking"] for p in listing):
            break
        await asyncio.sleep(0.02)
    assert not any(p["checking"] for p in listing)
    public = {p["id"]: p for p in (await client.get("/api/v1/platforms")).json()["platforms"]}
    assert public["internet-archive"]["verified"] is True and public["internet-archive"]["status"] == "supported"
    # one link that worked does not lift the known limits of a platform
    assert public["youtube"]["verified"] is True and public["youtube"]["status"] == "partial"
    assert public["vimeo"]["verified"] is False and public["vimeo"]["enabled"] is False


async def test_failures_are_remembered_without_the_link(make_client: Callable[..., Any], source: str) -> None:
    port = source.rsplit(":", 1)[1]
    client: httpx.AsyncClient = await make_client(**ADMIN, unsafe_allow_hosts=[f"127.0.0.1:{port}"])
    headers = await ready_admin(client)
    assert (await client.post("/api/v1/analyze", json={"url": f"{source}/gone?secret=1"})).status_code == 422
    errors = (await client.get("/api/v1/admin/overview", headers=headers)).json()["errors"]
    assert len(errors) == 1
    assert errors[0] | {"at": 0} == {
        "at": 0, "stage": "analyze", "domain": "127.0.0.1", "platform": None, "code": "not_found",
        "message": "This video is unavailable. It may have been removed or the link is wrong.",
    }
    assert "secret" not in str(errors) and "/gone" not in str(errors)


# ------------------------------------------------------------------------------ storage
GIB = 1024**3


async def _sample(client: httpx.AsyncClient, source: str) -> tuple[dict[str, Any], dict[str, Any]]:
    response = await client.post("/api/v1/analyze", json={"url": f"{source}/watch/demo"})
    assert response.status_code == 200, response.text
    analysis = response.json()
    return analysis, analysis["qualities"][0]


async def test_downloads_are_refused_when_space_is_short(
    make_client: Callable[..., Any], source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = source.rsplit(":", 1)[1]
    client: httpx.AsyncClient = await make_client(unsafe_allow_hosts=[f"127.0.0.1:{port}"], min_free_disk_mb=1024)
    analysis, quality = await _sample(client, source)
    payload = {"analysis_id": analysis["id"], "quality_id": quality["id"], "embed_subtitles": []}

    monkeypatch.setattr(TempStorage, "free_bytes", lambda self: GIB + 1024)  # just above the floor
    refused = await client.post("/api/v1/jobs", json=payload)
    assert refused.status_code == 507 and refused.json()["error"]["code"] == "insufficient_storage"
    assert "smaller quality" in refused.json()["error"]["hint"]
    assert not list((client.app.state.services.storage.root / "jobs").iterdir())  # type: ignore[attr-defined]

    monkeypatch.setattr(TempStorage, "free_bytes", lambda self: 100 * GIB)
    assert (await client.post("/api/v1/jobs", json=payload)).status_code == 202


def test_space_is_reserved_for_running_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.errors import AppError
    from app.services.formats import QualityChoice
    from app.services.jobs import Job, JobManager, JobStatus
    from tests.conftest import make_settings

    settings = make_settings(tmp_path, min_free_disk_mb=1024, max_file_size_mb=1536)
    storage = TempStorage(settings.storage_dir)
    storage.prepare()
    manager = JobManager.__new__(JobManager)
    manager._settings, manager._storage, manager._jobs = settings, storage, {}  # type: ignore[attr-defined]

    def choice(size: int | None, merge: bool = False, estimate: bool = False) -> QualityChoice:
        fields: dict[str, Any] = dict.fromkeys(QualityChoice.__dataclass_fields__)
        fields |= {"id": "q1", "kind": "video", "label": "1080p", "container": "mp4", "size": size,
                   "size_is_estimate": estimate, "requires_merge": merge, "parts": (), "format_spec": "x"}
        return QualityChoice(**fields)

    mib = 1024 * 1024
    assert manager.space_needed(choice(1000 * mib), False) == 1050 * mib + 16 * mib
    assert manager.space_needed(choice(1000 * mib, merge=True), False) == 2000 * mib + 16 * mib, "parts + merged file"
    assert manager.space_needed(choice(1000 * mib), True) == 2000 * mib + 16 * mib, "embedding rewrites the file"
    assert manager.space_needed(choice(None), False) == int(1536 * mib * 1.05) + 16 * mib, "unknown size: the limit"
    assert manager.space_needed(choice(5000 * mib, merge=True), False) == 2 * 1536 * mib + 16 * mib, "never above it"

    monkeypatch.setattr(TempStorage, "free_bytes", lambda self: 6 * GIB)
    big = manager.space_needed(choice(1536 * mib, merge=True), False)          # ~3 GiB
    manager._check_space(big)                                                    # 5 GiB usable: fits
    directory = storage.create("jobs", "running")
    manager._jobs["a"] = Job(id="a", client_key="c", title="t", domain="d", quality=choice(1), embed=[],  # type: ignore[attr-defined]
                             directory=directory, created_at=0.0, status=JobStatus.RUNNING, reserved_bytes=big)
    assert manager.reserved_bytes() == big
    with pytest.raises(AppError) as second:
        manager._check_space(big)                                                # 5 - 3 = 2 GiB left: refused
    assert second.value.code == "insufficient_storage" and second.value.retry_after == 120
    manager._check_space(1 * GIB)                                                # a small file still fits
    (directory / "part").write_bytes(b"x" * mib)
    assert manager.reserved_bytes() == big - mib, "what is already written is no longer reserved"
    manager._jobs["a"].status = JobStatus.COMPLETED  # type: ignore[attr-defined]
    assert manager.reserved_bytes() == 0

    # an explicit budget caps what Lumora may occupy, however much is free
    capped = make_settings(tmp_path / "b", min_free_disk_mb=0, storage_budget_mb=512)
    manager._settings = capped  # type: ignore[attr-defined]
    with pytest.raises(AppError):
        manager._check_space(600 * mib)
    manager._check_space(400 * mib)


def test_worker_stops_before_the_disk_is_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.worker import tasks

    events: list[dict[str, Any]] = []
    progress = tasks._Progress(events.append, [{"format_id": "f", "kind": "media", "size": 1000}], 10**9,
                               work_dir=tmp_path, min_free_bytes=5 * GIB)
    update = {"info_dict": {"format_id": "f"}, "status": "downloading", "downloaded_bytes": 10, "total_bytes": 1000}
    monkeypatch.setattr(tasks, "_free_bytes", lambda directory: 50 * GIB)
    progress.hook(update)
    assert events and events[-1]["downloaded_bytes"] == 10
    monkeypatch.setattr(tasks, "_free_bytes", lambda directory: 4 * GIB)
    progress._last_space_check = 0.0
    with pytest.raises(tasks.TaskError) as stopped:
        progress.hook(update)
    assert stopped.value.code == "insufficient_storage"
    assert tasks.classify_message("OSError: [Errno 28] No space left on device", default="x") == "insufficient_storage"


def test_one_and_a_half_gigabytes_is_the_limit() -> None:
    from app.config import Settings
    from app.services.formats import build_qualities

    limit = Settings(_env_file=None).max_file_size_bytes
    assert limit == 1536 * 1024 * 1024

    def info(size: int) -> dict[str, Any]:
        return {"duration": 600, "formats": [{
            "format_id": "v", "ext": "mp4", "protocol": "https", "vcodec": "avc1", "acodec": "mp4a",
            "height": 1080, "width": 1920, "filesize": size, "url": "https://videos.example.org/v.mp4",
        }]}

    within = build_qualities(info(limit), ffmpeg_available=True, max_bytes=limit).qualities
    beyond = build_qualities(info(limit + 1), ffmpeg_available=True, max_bytes=limit).qualities
    assert within[0].exceeds_limit is False and beyond[0].exceeds_limit is True
