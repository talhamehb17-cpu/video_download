"""Map extractor / downloader failures to the service's stable error codes.

The raw upstream text is never shown to users; it only selects a code (and is kept
as ``detail`` for the server log). URLs are stripped before matching so a word in
the address ("/login", "/premium") can't influence the result.
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://\S+", re.I)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (code, re.compile(pattern, re.I))
    for code, pattern in (
        ("blocked_destination", r"blocked by network policy"),
        ("file_too_large", r"file too large|errno 27|larger than max-filesize"),
        ("subtitle_unavailable", r"unable to download video subtitles|subtitle"),
        ("drm_protected", r"\bdrm\b|widevine|fairplay|playready"),
        ("verification_required",
         r"not a bot|captcha|cloudflare|unusual traffic|human verification|verify (that )?you(.re| are) (a )?human"
         r"|anti-?bot|challenge"),
        ("age_restricted",
         r"confirm your age|age[- ]?restrict|age[- ]?gate|age verification|inappropriate for some users"
         r"|adult content|18 years"),
        ("private_content", r"private video|is private|private (post|account|media|content|group)|only visible to"),
        ("paywalled",
         r"premium|paywall|subscri(ption|ber)|purchas|rental|\brent\b|pay[- ]per[- ]view|paid content|members"
         r"|join this channel|requires payment"),
        ("geo_restricted",
         r"geo[- ]?(restrict|block)|not available (in|from) your (country|region|location)|in your country"
         r"|region[- ]?lock|your region|your location"),
        ("login_required",
         r"log ?in|sign ?in|logged[- ]in|authenticat|account (is )?required|requires? (an )?account|cookies"
         r"|credentials|registered users|--username|--netrc|http error 401"),
        ("live_stream", r"live event|premiere|is live|live ?stream|will begin|not yet started|is upcoming"),
        ("unsupported_source", r"unsupported url|no suitable (info ?)?extractor|not a valid url|no media found"),
        ("format_unavailable", r"requested format is not available"),
        ("no_formats", r"no video formats found|no formats found"),
        ("source_rate_limited", r"http error 429|too many requests|rate[- ]?limit"),
        ("not_found",
         r"http error 40[04]|http error 410|not found|video unavailable|been removed|been deleted|does not exist"
         r"|no longer available|is unavailable|unavailable"),
        ("source_forbidden", r"http error 403|forbidden|access denied"),
        ("source_timeout", r"timed out|timeout"),
        ("source_unreachable",
         r"unable to download (webpage|json|api)|name or service not known|name resolution|nodename nor servname"
         r"|getaddrinfo|connection (refused|reset|aborted)|network is unreachable|no route to host|\bssl\b"
         r"|certificate|remote end closed|incomplete ?read|http error 5\d\d|unable to connect|connection error"),
        ("processing_failed", r"ffmpeg|ffprobe|postprocess|conversion failed|merg"),
    )
)


def classify_message(message: str, *, default: str) -> str:
    text = _URL_RE.sub(" ", message or "")
    for code, pattern in _PATTERNS:
        if pattern.search(text):
            return code
    return default
