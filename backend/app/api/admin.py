"""Administrator endpoints.

Every route except ``/login`` depends on a valid session (``AdminSessionDep``), and
everything beyond the session itself also requires that the initial password was
replaced (``AdminDep``). Nothing here is reachable by knowing an address.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from app import schemas
from app.deps import AdminDep, AdminSessionDep, ClientDep, ServicesDep, rate_limited
from app.errors import AppError
from app.platforms.registry import Platform, normalise_domain
from app.presenters import admin_overview, admin_platform, admin_platforms_response, admin_session
from app.security.client import ClientIdentity
from app.security.url_validation import SourcePolicy, ValidatedUrl, validate_public_url
from app.state import Services

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], include_in_schema=False)

PlatformId = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")]
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _private(response: Response) -> None:
    response.headers.update(NO_STORE)


# ------------------------------------------------------------------------------ session
@router.get("/status", response_model=schemas.AdminAvailability)
async def availability(
    response: Response, services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("admin"))]
) -> schemas.AdminAvailability:
    """Whether signing in is possible at all. Says nothing an anonymous request to any
    other admin address would not also reveal (503 when the panel is off, 401 when it is on)."""
    _private(response)
    return schemas.AdminAvailability(configured=services.admin.configured)


@router.post("/login", response_model=schemas.AdminSession)
async def login(
    body: schemas.AdminLoginRequest, response: Response, services: ServicesDep,
    client: Annotated[ClientIdentity, Depends(rate_limited("admin_login"))],
) -> schemas.AdminSession:
    _private(response)
    # Hashing is slow on purpose; keep it off the event loop.
    token, session = await asyncio.to_thread(
        services.admin.login, body.email, body.password, client=client.log_label
    )
    return admin_session(services, session, token)


@router.get("/session", response_model=schemas.AdminSession)
async def current_session(response: Response, services: ServicesDep, session: AdminSessionDep) -> schemas.AdminSession:
    _private(response)
    return admin_session(services, session)


@router.post("/logout", status_code=204)
async def logout(services: ServicesDep, session: AdminSessionDep) -> Response:
    services.admin.logout(session)
    return Response(status_code=204, headers=NO_STORE)


@router.post("/password", response_model=schemas.AdminSession)
async def change_password(
    body: schemas.AdminPasswordRequest, response: Response, services: ServicesDep, session: AdminSessionDep,
    client: ClientDep,
) -> schemas.AdminSession:
    _private(response)
    token, fresh = await asyncio.to_thread(
        services.admin.change_password, session, body.current_password, body.new_password, client=client.log_label
    )
    return admin_session(services, fresh, token)


# ----------------------------------------------------------------------------- overview
@router.get("/overview", response_model=schemas.AdminOverview)
async def overview(response: Response, services: ServicesDep, _: AdminDep) -> schemas.AdminOverview:
    _private(response)
    return await asyncio.to_thread(admin_overview, services)


# ---------------------------------------------------------------------------- platforms
def _platform(services: Services, platform_id: str) -> Platform:
    platform = services.platforms.get(platform_id)
    if platform is None:
        raise AppError("platform_not_found")
    return platform


def _check_policy(services: Services) -> SourcePolicy:
    """Rules for links the administrator tests: every safety rule, but not the list of
    enabled platforms (a website has to be testable before it is switched on)."""
    settings = services.settings
    return SourcePolicy(
        mode="open", blocked_domains=tuple(settings.blocked_domains),
        allowed_ports=frozenset(settings.allowed_ports), exempt=settings.unsafe_allow_pairs,
    )


async def _validated_link(services: Services, link: str) -> ValidatedUrl:
    return await validate_public_url(link, _check_policy(services))


def _has_path(target: str) -> bool:
    rest = target.split("://", 1)[-1]
    return "/" in rest.rstrip("/") or "?" in rest


@router.get("/platforms", response_model=schemas.AdminPlatformsResponse)
async def list_platforms(response: Response, services: ServicesDep, _: AdminDep) -> schemas.AdminPlatformsResponse:
    _private(response)
    return admin_platforms_response(services)


@router.post("/platforms", response_model=schemas.AdminPlatform, status_code=201)
async def add_platform(
    body: schemas.AdminPlatformCreate, response: Response, services: ServicesDep, _: AdminDep
) -> schemas.AdminPlatform:
    """Add a website (or find the platform it belongs to) and check what can be done with it.

    The website is only put on the list. It stays switched off until the
    administrator has seen the result and switches it on.
    """
    _private(response)
    link: str | None = None
    exempt_host: str | None = None
    if _has_path(body.target):
        validated = await _validated_link(services, body.target)
        link = validated.url
        exempt_host = validated.host if validated.is_exempt else None
    domain = exempt_host or normalise_domain(body.target)
    if domain is None:
        raise AppError("invalid_url", message="Enter a domain like example.com, or a link to a video page.",
                       hint="")  # the usual hint ("paste the full address") would contradict the message
    if exempt_host is None:
        # Run the address through the same checks as any link (internal names, block list).
        await _validated_link(services, link or f"https://{domain}/")

    platform = services.platforms.match(domain)
    if platform is None:
        try:
            platform = services.platforms.add(domain, body.name)
        except ValueError:
            raise AppError("platform_locked", message="The list of added websites is full. Remove one first.") from None
    else:
        response.status_code = 200
    if platform.declared != "unsupported" and not platform.checking:
        services.checker.start(platform, link)
    return admin_platform(platform, services)


@router.post("/platforms/{platform_id}/check", response_model=schemas.AdminPlatform, status_code=202)
async def check_platform(
    platform_id: PlatformId, body: schemas.AdminCheckRequest, response: Response, services: ServicesDep, _: AdminDep
) -> schemas.AdminPlatform:
    _private(response)
    platform = _platform(services, platform_id)
    if platform.declared == "unsupported":
        raise AppError("platform_locked", message=f"{platform.name} can't be checked.", hint=platform.note)
    link: str | None = None
    if body.url:
        validated = await _validated_link(services, body.url)
        if not validated.is_exempt and not platform.matches(validated.host):
            raise AppError("invalid_url", message=f"That link doesn't belong to {platform.name}.",
                           hint=f"Use a link on {', '.join(platform.domains[:3])}.")
        link = validated.url
    services.checker.start(platform, link)
    return admin_platform(platform, services)


@router.post("/platform-checks", response_model=schemas.AdminBulkCheck, status_code=202)
async def check_enabled_platforms(response: Response, services: ServicesDep, _: AdminDep) -> schemas.AdminBulkCheck:
    """Check every platform that is switched on, with sample links, two at a time.

    This is how the administrator finds out what really works from this server's
    network address. Nothing is switched on by it.
    """
    _private(response)
    started = services.checker.start_many([p for p in services.platforms.all() if p.active])
    return schemas.AdminBulkCheck(started=started, pending=services.checker.pending)


@router.patch("/platforms/{platform_id}", response_model=schemas.AdminPlatform)
async def update_platform(
    platform_id: PlatformId, body: schemas.AdminPlatformUpdate, response: Response, services: ServicesDep, _: AdminDep
) -> schemas.AdminPlatform:
    _private(response)
    platform = _platform(services, platform_id)
    if body.enabled and not platform.can_enable:
        raise AppError("platform_locked", message=f"{platform.name} can't be switched on.",
                       hint=platform.note or (platform.check.summary if platform.check else None))
    services.platforms.set_enabled(platform, body.enabled)
    return admin_platform(platform, services)


@router.delete("/platforms/{platform_id}", status_code=204)
async def remove_platform(platform_id: PlatformId, services: ServicesDep, _: AdminDep) -> Response:
    platform = _platform(services, platform_id)
    if platform.builtin:
        raise AppError("platform_locked", message="Built-in platforms can be switched off, but not removed.")
    if platform.checking:
        raise AppError("check_in_progress")
    services.platforms.remove(platform)
    return Response(status_code=204, headers=NO_STORE)
