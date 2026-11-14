"""Application factory: middleware, error handling and the service lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.api.admin import router as admin_router
from app.api.routes import router
from app.config import Settings, get_settings
from app.errors import ERRORS, AppError
from app.security.client import anonymize_ip, client_ip
from app.state import Services, build_services

log = logging.getLogger("lumora")
access_log = logging.getLogger("lumora.access")

SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"permissions-policy", b"interest-cohort=()"),
)
_STATUS_CODES = {404: "not_found_route", 405: "method_not_allowed", 413: "payload_too_large", 429: "rate_limited"}


def error_response(error: AppError) -> JSONResponse:
    headers = {"Cache-Control": "no-store", **error.headers}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    return JSONResponse({"error": error.to_dict()}, status_code=error.status, headers=headers)


class RequestContextMiddleware:
    """Outermost layer: request ids, security headers and a privacy-friendly access log."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = secrets.token_hex(8)
        started = time.perf_counter()
        status = 500
        docs = scope["path"] in ("/docs", "/redoc", "/openapi.json")

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                headers.append((b"x-request-id", request_id.encode()))
                for name, value in SECURITY_HEADERS:
                    if name == b"content-security-policy" and docs:
                        continue  # the interactive docs need their scripts
                    if name not in present:
                        headers.append((name, value))
                if b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope["path"] != "/health":
                request = Request(scope)
                ip = client_ip(
                    request, header=self.settings.client_ip_header, trusted_hops=self.settings.trusted_proxy_hops
                )
                access_log.info(
                    "%s %s -> %d %.0fms client=%s id=%s",
                    scope["method"], scope["path"], status, (time.perf_counter() - started) * 1000,
                    anonymize_ip(ip), request_id,
                )


class GuardMiddleware:
    """Innermost layer: request-size limit, and JSON (with CORS headers) even for crashes."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_body_bytes):
            await error_response(AppError("payload_too_large"))(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body") or b"")
                if received > self.max_body_bytes:
                    raise StarletteHTTPException(status_code=413)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except Exception:
            log.exception("unhandled error on %s %s", scope["method"], scope["path"])
            if started:
                raise
            await error_response(AppError("internal_error"))(scope, receive, send)


async def _housekeeping(services: Services) -> None:
    """Delete expired files and records for as long as the service runs."""
    interval = services.settings.cleanup_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            expired, forgotten = services.jobs.cleanup()
            analyses = services.analyses.cleanup()
            services.limiter.prune()
            if expired or forgotten or analyses:
                log.info("cleanup: %d file(s) expired, %d job record(s) and %d analysis record(s) removed",
                         expired, forgotten, analyses)
        except Exception:
            log.exception("cleanup failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = build_services(settings)
        app.state.services = services
        log.info(
            "started version=%s env=%s policy=%s ffmpeg=%s storage=%s max_file=%dMB ttl=%ds",
            __version__, settings.environment, settings.source_policy,
            services.ffmpeg_version or "missing", services.storage.root,
            settings.max_file_size_mb, settings.file_ttl_seconds,
        )
        if services.ffmpeg_path is None:
            log.warning("FFmpeg not found: merging, container fixes and subtitle conversion are disabled")
        if not services.admin.configured:
            log.info("admin panel is off: set ADMIN_EMAIL and ADMIN_BOOTSTRAP_PASSWORD to switch it on")
        if settings.unsafe_allow_hosts:
            log.warning("UNSAFE_ALLOW_HOSTS is set (%s): never use this in production", settings.unsafe_allow_hosts)
        housekeeping = asyncio.create_task(_housekeeping(services), name="housekeeping")
        try:
            yield
        finally:
            housekeeping.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await housekeeping
            await services.checker.shutdown()
            await services.jobs.shutdown()
            services.storage.wipe()
            log.info("stopped: workers terminated and temporary files deleted")

    docs = settings.enable_docs
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Validates public video links, reads their metadata and prepares permitted downloads.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Middleware runs outside-in in reverse order of registration.
    app.add_middleware(GuardMiddleware, max_body_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=settings.allowed_origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["Content-Disposition", "Content-Length", "Retry-After", "X-Request-ID",
                        "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, settings=settings)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: list[dict[str, str]] = []
        for item in exc.errors()[:10]:
            location = [str(part) for part in item.get("loc", ()) if part not in ("body", "query", "path")]
            fields.append({"field": ".".join(location) or "body", "message": str(item.get("msg", "Invalid value"))})
        body: dict[str, Any] = AppError("validation_error").to_dict()
        body["fields"] = fields
        return JSONResponse({"error": body}, status_code=422, headers={"Cache-Control": "no-store"})

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code)
        if code is None:
            code = "internal_error" if exc.status_code >= 500 else "validation_error"
        if exc.status_code == 405:
            # Usually someone opened an address in a browser tab (a GET request) that
            # only takes POST. Say which requests work instead of just "no".
            allowed = (exc.headers or {}).get("Allow", "")
            return error_response(AppError(
                code, headers={"Allow": allowed} if allowed else None,
                message=f"This address doesn't accept {request.method} requests.",
                hint=(f"It accepts {allowed.replace(', ', ' or ')}. " if allowed else "")
                + "Opening it in a browser tab sends a GET request; use the website instead.",
            ))
        return error_response(AppError(code, status=exc.status_code if code in ERRORS else None))

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": __version__, "health": "/health",
                **({"docs": "/docs"} if docs else {})}

    app.include_router(router)
    app.include_router(admin_router)
    return app


app = create_app()
