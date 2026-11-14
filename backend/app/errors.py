"""One error type and one catalogue of user-facing messages.

Every failure the API can report is listed here, so the wording stays consistent
and nothing internal (stack traces, upstream error text, file paths) leaks to
clients. The frontend switches on ``code``; ``message`` is safe to show as is.

Status codes carry one promise the frontend relies on: **422 means the request
itself cannot be fulfilled** (a wrong, private or disallowed link, an oversized
file), so sending it again would fail the same way and no "Try again" is offered.
Anything that may succeed later (rate limits, a busy server, a source that timed
out, a full disk) uses 409, 410, 429 or 5xx instead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    message: str
    hint: str | None = None


ERRORS: dict[str, ErrorSpec] = {
    # --- the link itself ---------------------------------------------------------
    "invalid_url": ErrorSpec(422, "That doesn't look like a valid link.", "Paste the full address, starting with https://"),
    "unsupported_scheme": ErrorSpec(422, "Only http:// and https:// links are supported."),
    "blocked_destination": ErrorSpec(
        422, "This address points to a private or internal network, so it can't be processed.",
        "Only publicly reachable pages are supported.",
    ),
    "domain_not_allowed": ErrorSpec(
        422, "This website isn't enabled on this service.",
        "Only the platforms listed on this site can be processed.",
    ),
    "platform_disabled": ErrorSpec(
        422, "This platform is switched off on this service.",
        "The operator of this service has switched it off.",
    ),
    "platform_unsupported": ErrorSpec(
        422, "Videos from this platform can't be downloaded.",
        "The platform protects its videos, and Lumora never circumvents that.",
    ),
    # --- what the source told us ---------------------------------------------------
    "unsupported_source": ErrorSpec(
        422, "We couldn't find a downloadable video at this link.",
        "Make sure the link opens a single, public video page.",
    ),
    "not_found": ErrorSpec(422, "This video is unavailable. It may have been removed or the link is wrong."),
    "private_content": ErrorSpec(
        422, "This video is private.", "Lumora only processes content that is publicly accessible."
    ),
    "login_required": ErrorSpec(
        422, "This source requires signing in to view the video.",
        "Lumora never signs in or bypasses access controls.",
    ),
    "paywalled": ErrorSpec(
        422, "This video is behind a paywall or subscription.", "Lumora doesn't bypass paid access."
    ),
    # The platform asked visitors for an age, or marked the video 18+. The visitor is
    # asked first; when they say no, or have not said yes yet, this is the answer.
    "age_confirmation_required": ErrorSpec(
        403, "This video is for adults only.",
        "Confirm that you are 18 or older to continue. Lumora never signs in; the answer is yours to give, "
        "in this browser.",
    ),
    # The operator's rule (BLOCK_AGE_RESTRICTED=true, or AGE_CONFIRMATION=false).
    "age_rating_blocked": ErrorSpec(
        422, "This video carries an 18+ label.",
        "This service is not set up to offer videos that a platform marks 18+.",
    ),
    "geo_restricted": ErrorSpec(
        422, "This video isn't available in the server's region.", "Lumora doesn't bypass regional restrictions."
    ),
    "drm_protected": ErrorSpec(
        422, "This video is DRM-protected and can't be downloaded.", "Lumora never circumvents DRM."
    ),
    "verification_required": ErrorSpec(
        422, "The source is asking for a human verification or sign-in check.",
        "Lumora doesn't bypass bot checks. Try a different public source.",
    ),
    "live_stream": ErrorSpec(
        422, "Live streams and upcoming premieres aren't supported.", "Try again once the recording is published."
    ),
    "too_long": ErrorSpec(422, "This video is longer than this service allows."),
    "no_formats": ErrorSpec(422, "The source didn't offer any downloadable formats for this video."),
    "format_unavailable": ErrorSpec(
        409, "That quality is no longer offered by the source.", "Analyze the link again to refresh the options."
    ),
    "unsupported_stream": ErrorSpec(
        422, "This stream uses a delivery method that isn't supported.", "Try a different quality."
    ),
    "subtitle_unavailable": ErrorSpec(422, "That subtitle track couldn't be retrieved from the source."),
    "file_too_large": ErrorSpec(
        422, "This file is larger than this service allows.", "Pick a lower quality and try again."
    ),
    # --- the source misbehaving ----------------------------------------------------
    "source_rate_limited": ErrorSpec(
        502, "The source is rate-limiting requests right now.", "Please wait a little and try again."
    ),
    "source_forbidden": ErrorSpec(502, "The source refused the request.", "It may block automated access."),
    "source_unreachable": ErrorSpec(502, "We couldn't reach the source.", "Check the link, or try again in a moment."),
    "source_timeout": ErrorSpec(504, "The source took too long to respond.", "Please try again."),
    "extraction_failed": ErrorSpec(
        502, "We couldn't read this video from the source.",
        "The site may have changed or may not be supported.",
    ),
    "download_failed": ErrorSpec(502, "The download from the source failed.", "Please try again."),
    "processing_failed": ErrorSpec(500, "The file couldn't be processed after downloading."),
    # --- this service ---------------------------------------------------------------
    "validation_error": ErrorSpec(422, "The request is invalid."),
    "embed_unsupported": ErrorSpec(
        422, "Subtitles can't be embedded into this format.", "Download the subtitle file separately instead."
    ),
    "payload_too_large": ErrorSpec(413, "The request body is too large."),
    "rate_limited": ErrorSpec(429, "You're going a little fast. Please wait a moment and try again."),
    "too_many_jobs": ErrorSpec(
        429, "You already have downloads in progress.", "Wait for one to finish or cancel it first."
    ),
    "server_busy": ErrorSpec(503, "The service is at capacity right now.", "Please try again in a minute."),
    "storage_full": ErrorSpec(503, "The service is out of temporary storage right now.", "Please try again shortly."),
    "insufficient_storage": ErrorSpec(
        507, "The server doesn't have enough free space for this file right now.",
        "Pick a smaller quality, or try again in a few minutes.",
    ),
    "ffmpeg_unavailable": ErrorSpec(503, "Media processing is unavailable on this server."),
    "analysis_expired": ErrorSpec(410, "This analysis has expired.", "Analyze the link again."),
    "option_not_found": ErrorSpec(404, "That option doesn't exist for this video."),
    "job_not_found": ErrorSpec(404, "This download no longer exists.", "It may have expired or the server restarted."),
    "file_not_ready": ErrorSpec(409, "The file isn't ready yet."),
    "file_expired": ErrorSpec(410, "This file has expired and was deleted.", "Start the download again."),
    "job_timeout": ErrorSpec(504, "Processing took longer than this service allows."),
    "cancelled": ErrorSpec(409, "The download was cancelled."),
    "not_found_route": ErrorSpec(404, "Not found."),
    "method_not_allowed": ErrorSpec(405, "This address doesn't accept this kind of request."),
    # --- administration ---------------------------------------------------------------
    "admin_not_configured": ErrorSpec(
        503, "The admin panel isn't set up on this server.",
        "Set ADMIN_EMAIL and ADMIN_BOOTSTRAP_PASSWORD on the server and restart the API.",
    ),
    "invalid_credentials": ErrorSpec(401, "The e-mail address or password is wrong."),
    "too_many_attempts": ErrorSpec(
        429, "Too many failed sign-in attempts.", "Sign-in is paused for a while. Please wait and try again."
    ),
    "not_authenticated": ErrorSpec(401, "Please sign in.", "Your session may have ended."),
    "password_change_required": ErrorSpec(403, "Choose a new password before you continue."),
    "weak_password": ErrorSpec(422, "That password can't be used."),
    "platform_not_found": ErrorSpec(404, "That platform doesn't exist."),
    "platform_exists": ErrorSpec(409, "That website is already on the list."),
    "platform_locked": ErrorSpec(409, "This platform can't be changed that way."),
    "check_in_progress": ErrorSpec(409, "A check is already running for this platform.", "Wait for it to finish."),
    "internal_error": ErrorSpec(500, "Something went wrong on our side.", "Please try again."),
}


class AppError(Exception):
    """An expected failure with a stable ``code`` and a message safe to show users."""

    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        hint: str | None = None,
        status: int | None = None,
        retry_after: int | None = None,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        spec = ERRORS.get(code) or ERRORS["internal_error"]
        self.code = code if code in ERRORS else "internal_error"
        self.message = message or spec.message
        self.hint = hint if hint is not None else spec.hint
        self.status = status or spec.status
        self.retry_after = retry_after
        self.detail = detail  # internal diagnostics; logged, never sent to clients
        self.headers = headers or {}  # extra response headers (e.g. rate-limit counters)
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {"code": self.code, "message": self.message}
        if self.hint:
            body["hint"] = self.hint
        if self.retry_after is not None:
            body["retry_after"] = self.retry_after
        return body


def error_payload(code: str, **kwargs: object) -> dict[str, object]:
    return AppError(code, **kwargs).to_dict()  # type: ignore[arg-type]
