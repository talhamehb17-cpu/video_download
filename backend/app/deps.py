"""FastAPI dependencies: services, caller identity and rate limiting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request, Response

from app.admin.auth import Session
from app.errors import AppError
from app.security.client import ClientIdentity, identify_client
from app.state import Services


def get_services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


ServicesDep = Annotated[Services, Depends(get_services)]


def get_client(request: Request, services: ServicesDep) -> ClientIdentity:
    """The caller. Anonymous (per IP) today; the place to plug accounts in later."""
    settings = services.settings
    return identify_client(request, header=settings.client_ip_header, trusted_hops=settings.trusted_proxy_hops)


ClientDep = Annotated[ClientIdentity, Depends(get_client)]


def rate_limited(bucket: str) -> Callable[..., ClientIdentity]:
    """Dependency factory: enforce the named rate limit and return the caller."""

    def dependency(response: Response, services: ServicesDep, client: ClientDep) -> ClientIdentity:
        decision = services.limiter.check(bucket, client.key)
        counters = {"X-RateLimit-Limit": str(decision.limit), "X-RateLimit-Remaining": str(decision.remaining)}
        if not decision.allowed:
            # Headers set on ``response`` are dropped when an exception is raised,
            # so the error carries them itself.
            raise AppError("rate_limited", retry_after=decision.retry_after, headers=counters)
        response.headers.update(counters)
        return client

    return dependency


# ---------------------------------------------------------------------------- admin
def _bearer(request: Request) -> str | None:
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def admin_session(
    request: Request, services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("admin"))]
) -> Session:
    """A signed-in administrator. Every admin endpoint depends on this (or on the stricter one below)."""
    if not services.admin.configured:
        raise AppError("admin_not_configured")
    return services.admin.authenticate(_bearer(request))


AdminSessionDep = Annotated[Session, Depends(admin_session)]


def admin_ready(session: AdminSessionDep) -> Session:
    """A signed-in administrator who has replaced the initial password."""
    if session.must_change_password:
        raise AppError("password_change_required")
    return session


AdminDep = Annotated[Session, Depends(admin_ready)]
