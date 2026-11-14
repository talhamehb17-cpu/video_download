"""Age labels and age checks: who decides, what the visitor is asked, and what happens next.

The platform decides, and the visitor answers once. A video that a platform gives to
everybody is public, whatever rating its metadata carries: it is processed without a
question. A video that is for adults only — the platform asked for an age, or the reader
answered that question by itself — is offered after the visitor confirms that they are 18
or older, and refused otherwise. The reader may answer the platform's age question once the
visitor has said yes, but Lumora itself never signs in and never invents an answer.

The confirmation travels with the request (a field, or the ``X-Lumora-Age-Confirmed``
header); its memory on the device is the website's business, not the API's.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yt_dlp
from yt_dlp.extractor import gen_extractor_classes
from yt_dlp.extractor.common import InfoExtractor

from app import schemas
from app.config import Settings
from app.errors import ERRORS
from app.platforms.catalog import CATALOG
from app.services.analysis import worker_limits
from app.worker import tasks
from app.worker.classify import classify_message
from app.worker.tasks import (
    AGE_CHECK_NOTICE,
    AGE_QUESTION_ANSWERED_BY_READER,
    TaskError,
    _Log,
    adult_video,
    enforce_content_policy,
)

# The default: an 18+ video is offered after the visitor confirms their age.
CONFIRM: dict[str, Any] = {"block_age_restricted": False, "age_confirmation": True}
# The operator refuses them (BLOCK_AGE_RESTRICTED=true, or AGE_CONFIRMATION=false).
STRICT: dict[str, Any] = {"block_age_restricted": True}
NO_QUESTION: dict[str, Any] = {"block_age_restricted": False, "age_confirmation": False}
PLATFORM_DECIDES = CONFIRM


def video(**fields: Any) -> dict[str, Any]:
    """Metadata of an ordinary video that was read without signing in."""
    return {
        "id": "v1", "title": "A clip", "duration": 60,
        "formats": [{
            "format_id": "18", "url": "https://cdn.example.com/v.mp4", "protocol": "https", "ext": "mp4",
            "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360,
        }],
        **fields,
    }


def refusal(info: dict[str, Any], limits: dict[str, Any], **extra: Any) -> str | None:
    try:
        enforce_content_policy(info, limits, **extra)
    except TaskError as error:
        return error.code
    return None


def offers(info: dict[str, Any], limits: dict[str, Any] = CONFIRM, **extra: Any) -> str | None:
    """``None`` (no age involved), ``"confirm"`` (ask the visitor) or ``"blocked"``."""
    return adult_video(info, limits, **extra)


# ------------------------------------------------------------ a label alone is not a reason
@pytest.mark.parametrize("age_limit", [None, 0, 6, 7, 12, 13, 15, 16, 17])
@pytest.mark.parametrize("limits", [PLATFORM_DECIDES, STRICT, {}])
def test_all_ages_and_teen_ratings_are_never_declined(age_limit: int | None, limits: dict[str, Any]) -> None:
    assert refusal(video(age_limit=age_limit), limits) is None


@pytest.mark.parametrize("age_limit", [18, 19, 21])
@pytest.mark.parametrize("availability", [None, "public", "unlisted"])
def test_an_adult_label_alone_does_not_decline_a_public_video(age_limit: int, availability: str | None) -> None:
    info = video(age_limit=age_limit, availability=availability)
    assert refusal(info, PLATFORM_DECIDES) is None
    assert refusal(info, {}) is None, "a worker that is told nothing behaves like the default"


def test_the_default_asks_the_visitor_instead_of_declining(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, storage_dir=tmp_path / "s", data_dir=tmp_path / "d")
    assert settings.block_age_restricted is False
    assert settings.age_confirmation is True
    assert settings.age_confirmation_ttl_seconds == 21_600
    limits = worker_limits(settings)
    assert limits["block_age_restricted"] is False and limits["age_confirmation"] is True


def test_no_age_video_is_offered_without_the_visitors_confirmation(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, storage_dir=tmp_path / "s", data_dir=tmp_path / "d")
    for limits in (worker_limits(settings), CONFIRM, {}):
        assert refusal(video(age_limit=18, availability="needs_auth"), limits) == "age_confirmation_required"
        assert refusal(video(age_limit=18), limits, age_check=True) == "age_confirmation_required"
        assert refusal(video(availability="needs_auth"), limits) == "login_required"


# ------------------------------------------------------------ the operator's stricter rule
@pytest.mark.parametrize("age_limit", [18, 19])
def test_the_strict_setting_declines_every_adult_label_and_says_whose_rule_it_is(age_limit: int) -> None:
    assert refusal(video(age_limit=age_limit), STRICT) == "age_rating_blocked"
    spec = ERRORS["age_rating_blocked"]
    assert spec.status == 422 and "18+" in spec.message and "This service" in (spec.hint or "")


def test_the_strict_setting_is_read_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLOCK_AGE_RESTRICTED", "true")
    settings = Settings(_env_file=None, storage_dir=tmp_path / "s", data_dir=tmp_path / "d")
    assert settings.block_age_restricted is True, "an explicit setting of an existing installation is honoured"


# ------------------------------------------------------------ the visitor confirms the age
@pytest.mark.parametrize("limits", [CONFIRM, {}])
def test_a_confirmed_visitor_gets_a_video_the_platform_gated_by_age(limits: dict[str, Any]) -> None:
    # YouTube marks an age-restricted video as "needs an account": the sign-in it asks for
    # is its age check. A visitor who said they are 18 or older gets the video.
    gated = video(age_limit=18, availability="needs_auth")
    assert offers(gated, limits) == "confirm"
    assert refusal(gated, limits, age_confirmed=True) is None


def test_a_sign_in_that_is_not_about_age_is_still_a_sign_in() -> None:
    # No label and no age notice: the platform wants an account, and a confirmation of
    # being 18 changes nothing about that.
    assert refusal(video(availability="needs_auth"), CONFIRM) == "login_required"
    assert refusal(video(availability="needs_auth"), CONFIRM, age_confirmed=True) == "login_required"
    assert refusal(video(age_limit=18, availability="private"), CONFIRM) == "private_content"
    assert refusal(video(age_limit=18, availability="subscriber_only"), CONFIRM) == "paywalled"


@pytest.mark.parametrize("limits", [STRICT, {"block_age_restricted": True, "age_confirmation": True}])
def test_the_old_rule_declines_every_adult_label(limits: dict[str, Any]) -> None:
    # BLOCK_AGE_RESTRICTED=true: the operator wants nothing that carries the label, not
    # even a video that needs no age answer. A header cannot overrule it.
    for info in (video(age_limit=18, availability="needs_auth"), video(age_limit=18), video(availability="needs_auth")):
        gated = info.get("age_limit") is None  # an ordinary video that met the platform's age check
        assert offers(info, limits, age_check=gated) == "blocked"
        assert refusal(info, limits, age_check=gated) == "age_rating_blocked"
        assert refusal(info, limits, age_check=gated, age_confirmed=True) == "age_rating_blocked"
    assert offers(video(), limits) is None and refusal(video(), limits) is None, "a video for everybody is untouched"


def test_a_service_without_age_videos_offers_none_of_them() -> None:
    # AGE_CONFIRMATION=false: the question is not asked, and what is only for adults is
    # not offered. A label on a video that everybody gets changes nothing.
    assert offers(video(age_limit=18, availability="needs_auth"), NO_QUESTION) == "blocked"
    assert offers(video(), NO_QUESTION, age_check=True) == "blocked"
    assert refusal(video(age_limit=18, availability="needs_auth"), NO_QUESTION) == "age_rating_blocked"
    assert refusal(video(), NO_QUESTION, age_check=True, age_confirmed=True) == "age_rating_blocked"
    assert offers(video(age_limit=18), NO_QUESTION) is None


def test_the_worker_asks_only_for_a_video_the_platform_gated() -> None:
    """``adult_video`` is what the worker calls before the reader runs: ask, don't ask, or refuse."""
    assert adult_video(video(age_limit=18, availability="needs_auth"), CONFIRM) == "confirm"
    assert adult_video(video(age_limit=18), CONFIRM) is None, "a label on a video for everybody: no question"
    assert adult_video(video(age_limit=18, availability="needs_auth"), STRICT) == "blocked"
    assert adult_video(video(), CONFIRM, age_check=True) == "confirm"


def test_a_label_from_a_reader_that_answers_still_needs_the_visitor() -> None:
    for reader in ("Reddit", "Dailymotion", "CDA", "PornHub", "VideoPress", "YouPorn", "Murrtube"):
        info = video(extractor_key=reader, age_limit=18)
        assert offers(info) == "confirm", reader
        assert refusal(info, CONFIRM) == "age_confirmation_required", reader
        assert refusal(info, CONFIRM, age_confirmed=True) is None, reader


def test_the_message_says_the_visitor_may_confirm_and_that_lumora_does_not() -> None:
    spec = ERRORS["age_confirmation_required"]
    assert spec.status == 403, "it can be retried with the confirmation, so it is not a 422"
    assert "18 or older" in (spec.hint or "")
    assert "never signs in" in (spec.hint or "")
    # The old rule ("Lumora never answers the platform's age question") is gone: what the
    # reader does after a yes is exactly that, so the hint must not claim otherwise.
    assert "does not answer" not in (spec.hint or "").lower()
    blocked = ERRORS["age_rating_blocked"]
    assert blocked.status == 422 and "18+" in blocked.message and "not set up" in (blocked.hint or "")
    for code in ("age_confirmation_required", "age_rating_blocked"):
        text = f"{ERRORS[code].message} {ERRORS[code].hint}"
        assert "bypass" not in text.lower() and "http" not in text.lower()


def test_the_account_field_counts_as_the_confirmation() -> None:
    # The request model accepts the confirmation as a field; the header is the other way.
    assert schemas.AnalyzeRequest(url="https://example.com/v").age_confirmed is False
    assert schemas.AnalyzeRequest(url="https://example.com/v", age_confirmed=True).age_confirmed is True
    assert schemas.JobCreateRequest(analysis_id="a" * 16, quality_id="q1").age_confirmed is False
    assert schemas.AGE_CONFIRMATION_HEADER == "X-Lumora-Age-Confirmed"
    from app.api.routes import _age_confirmed
    assert _age_confirmed("true") is True and _age_confirmed("1") is True
    for other in (None, "", "false", "0", "yes", "TRUE-ish"):
        assert _age_confirmed(other) is False, other


def test_a_sign_in_wall_without_an_age_label_stays_a_sign_in_wall() -> None:
    assert refusal(video(availability="needs_auth"), PLATFORM_DECIDES) == "login_required"
    assert refusal(video(age_limit=0, availability="needs_auth"), PLATFORM_DECIDES) == "login_required"
    assert refusal(video(age_limit=18, availability="private"), PLATFORM_DECIDES) == "private_content"
    assert refusal(video(age_limit=18, availability="subscriber_only"), PLATFORM_DECIDES) == "paywalled"


def test_the_readers_own_notice_of_an_age_check_asks_the_visitor() -> None:
    # The age markers can be missing from the metadata. The reader still says so when
    # the platform answered with its age check and another player was used instead.
    log = _Log()
    log.debug("[youtube] dQw4w9WgXcQ: Downloading webpage")
    assert log.age_check is False
    log.debug("[youtube] dQw4w9WgXcQ: This video is age-restricted; some formats may be missing "
              "without authentication. Use --cookies-from-browser or --cookies for the authentication.")
    assert log.age_check is True
    assert refusal(video(), CONFIRM, age_check=log.age_check) == "age_confirmation_required"
    assert refusal(video(), CONFIRM, age_check=log.age_check, age_confirmed=True) is None
    assert refusal(video(), CONFIRM, age_check=False) is None


@pytest.mark.parametrize("line", [
    "[generic] age-restricted-content-rules: Downloading webpage",       # words of the address
    "[generic] Extracting URL: https://example.com/this-video-is-age-restricted",
    "[youtube] dQw4w9WgXcQ: Downloading tv client config",
    "[vimeo] 1: This video is age-restricted in a title somebody chose",   # another reader, not its notice
])
def test_ordinary_log_lines_are_not_taken_for_an_age_check(line: str) -> None:
    log = _Log()
    log.debug(line)
    log.info(line)
    assert log.age_check is False


def test_the_notice_still_exists_in_the_installed_reader() -> None:
    """Fails when an update of yt-dlp rewords the notice, so the rule above is revisited."""
    source = (Path(yt_dlp.__file__).parent / "extractor" / "youtube" / "_video.py").read_text(encoding="utf-8")
    assert "This video is age-restricted; some formats may be missing" in source
    sample = "[youtube] abcdefghijk: This video is age-restricted; some formats may be missing without authentication."
    assert AGE_CHECK_NOTICE.search(sample)
    # and the reader still derives "needs an account" from YouTube's own age marker
    assert re.search(r"needs_auth=info\['age_limit'\] >= 18", source)


# ---------------------------------------------------- the readers that answer an age question
# Reddit asks "are you over 18?" before it shows a post that it marks 18+, and Dailymotion
# keeps explicit videos behind its family filter. Their readers answer both by themselves
# (a cookie), which makes the video one for adults only: the visitor is asked before
# Lumora reads it, and its parts are only handed out to the visitor who said yes.
@pytest.mark.parametrize("info", [
    video(extractor_key="Reddit", age_limit=18, webpage_url="https://www.reddit.com/r/videos/comments/abc/a_clip/"),
    video(extractor_key="Reddit", age_limit=18, webpage_url="https://old.reddit.com/r/videos/comments/abc/"),
    video(extractor_key="Reddit", age_limit=18),
    video(extractor_key="Dailymotion", age_limit=18, webpage_url="https://www.dailymotion.com/video/x8abcde"),
    video(extractor_key="Dailymotion", age_limit=18, original_url="https://dai.ly/x8abcde"),
    # a Reddit post that embeds a video from another website: another reader finishes it,
    # the address of the post and Reddit's label stay
    video(extractor_key="Streamable", age_limit=18, webpage_url="https://www.reddit.com/r/videos/comments/abc/",
          original_url="https://www.reddit.com/r/videos/comments/abc/"),
    video(extractor_key="Generic", age_limit=18, original_url="https://redd.it/abc123"),
    # websites outside the built-in list whose readers confirm an age themselves
    video(extractor_key="CDA", age_limit=18, webpage_url="https://www.cda.pl/video/1"),
    video(extractor_key="VideoPress", age_limit=18, webpage_url="https://videopress.com/embed/abc"),
    video(extractor_key="PornHub", age_limit=18),
    video(extractor_key="YouPorn", age_limit=18),
    video(extractor_key="Murrtube", age_limit=18, webpage_url="https://murrtube.net/v/0J2Q"),
], ids=["reddit", "old-reddit", "reddit-no-address", "dailymotion", "dai.ly", "reddit-embed", "redd.it-embed",
        "cda", "videopress", "pornhub", "youporn", "murrtube"])
@pytest.mark.parametrize("limits", [PLATFORM_DECIDES, STRICT, {}])
def test_a_video_behind_an_age_question_is_for_adults_only(info: dict[str, Any], limits: dict[str, Any]) -> None:
    assert refusal(info, limits) == ("age_rating_blocked" if limits == STRICT else "age_confirmation_required")
    assert refusal(info, CONFIRM, age_confirmed=True) is None, "a confirmed visitor gets it"
    assert refusal(info, STRICT, age_confirmed=True) == "age_rating_blocked", "unless the operator refuses adult videos"
    assert refusal(info, NO_QUESTION, age_confirmed=True) == "age_rating_blocked", \
        "nor when the service does not offer them"


@pytest.mark.parametrize("info", [
    video(extractor_key="Reddit", age_limit=0, webpage_url="https://www.reddit.com/r/videos/comments/abc/a_clip/"),
    video(extractor_key="Reddit", age_limit=None, webpage_url="https://www.reddit.com/r/videos/comments/abc/"),
    video(extractor_key="Dailymotion", age_limit=0, webpage_url="https://www.dailymotion.com/video/x8abcde"),
    video(extractor_key="Dailymotion", webpage_url="https://www.dailymotion.com/video/x8abcde"),
    video(extractor_key="Murrtube", age_limit=0, webpage_url="https://murrtube.net/v/0J2Q"),
], ids=["reddit-0", "reddit-none", "dailymotion-0", "dailymotion-unset", "murrtube-0"])
@pytest.mark.parametrize("limits", [PLATFORM_DECIDES, STRICT])
def test_ordinary_videos_of_those_platforms_are_untouched(info: dict[str, Any], limits: dict[str, Any]) -> None:
    assert refusal(info, limits) is None


@pytest.mark.parametrize("info", [
    # a label on a platform whose reader answers nothing: the platform gave the video as it is
    video(extractor_key="Twitter", age_limit=18, webpage_url="https://x.com/user/status/1"),
    video(extractor_key="Kick", age_limit=18, webpage_url="https://kick.com/user/clips/clip_1"),
    video(extractor_key="Generic", age_limit=18, webpage_url="https://podcast.example.org/episode/7"),
    # an address that only looks like one of the two platforms
    video(extractor_key="Generic", age_limit=18, webpage_url="https://notreddit.com/r/videos/1"),
    video(extractor_key="Generic", age_limit=18, webpage_url="https://reddit.com.example.org/r/videos/1"),
    video(extractor_key="Generic", age_limit=18, webpage_url="https://example.org/?from=https://www.reddit.com/r/x"),
    video(extractor_key="Generic", age_limit=18, webpage_url="not an address", original_url=None),
    video(extractor_key="Generic", age_limit=18, webpage_url="http://[reddit.com", original_url=18),
], ids=["x", "kick", "podcast", "lookalike", "lookalike-prefix", "query", "garbage", "malformed"])
def test_the_rule_is_limited_to_the_readers_that_answer_an_age_question(info: dict[str, Any]) -> None:
    assert refusal(info, PLATFORM_DECIDES) is None
    assert refusal(info, STRICT) == "age_rating_blocked"


# What each reader of the installed package does about an age question, and what was
# decided. A name here means: an 18+ label from this reader declines the video.
REVIEWED_READERS: dict[str, str | None] = {
    "reddit.py": "Reddit",            # cookie over18=1 with every request
    "dailymotion.py": "Dailymotion",  # family filter switched off with every request
    "cda.py": "CDA",                  # posts the site's age form when asked
    "pornhub.py": "PornHub",          # cookies age_verified, accessAgeDisclaimer…
    "videopress.py": "VideoPress",    # a made-up birthday with every request
    "youporn.py": "YouPorn",          # cookie age_verified=1
    "murrtube.py": "Murrtube",        # posts the site's age form before every video
    "tube8.py": None,                 # cookie age_verified=1, but the reader is switched off
    "niconico.py": None,              # only after a sign-in, which Lumora never has
    "sonyliv.py": None,               # needs an account, and the streams are DRM-protected
    "iprima.py": None,                # needs an account
    "steam.py": None,                 # confirms for every trailer and labels none (README: known limit)
}
# readers that answer a platform's age question, and are switched on
ANSWERING_KEYS = {name for name in REVIEWED_READERS.values() if name}

AGE_ANSWER = re.compile(
    r"""_set_cookie\([^)]*['"]\w*(?:over_?18|age_?(?:verif|auth|gate|check|confirm|disclaimer)"""
    r"""|adult|mature|birth)\w*['"]"""
    r"""|_set_dailymotion_cookie\('ff'|random_birthday\(|['"]age_?confirm\w*['"]\s*:"""
    # a cookie sent with a request, as the Tube8 reader does
    r"""|['"]Cookie2?['"]\s*:\s*['"][^'"]*(?:over_?18|age_?\w*(?:verif|auth|gate|check|confirm)\w*"""
    r"""|adult|mature)"""
    # the address of a form that confirms an age, as the Murrtube reader posts to
    r"""|https?://[^'"\s]*\b(?:accept|confirm)[_-]?(?:age|adult|mature)""",
    re.IGNORECASE,
)


def test_the_list_of_readers_that_answer_an_age_question_is_complete() -> None:
    """Every reader of the installed package that sends an age confirmation has been looked at.

    Fails when an update of yt-dlp adds one or changes one, so the rule is revisited
    instead of quietly passing a platform's age question.
    """
    extractors = Path(yt_dlp.__file__).parent / "extractor"
    found = {
        path.name for path in extractors.rglob("*.py")
        if path.name != "lazy_extractors.py" and AGE_ANSWER.search(path.read_text(encoding="utf-8"))
    }
    assert found == set(REVIEWED_READERS)
    # yt-dlp still offers a switched-off reader, but skips it unless --ies is given
    switched_on = {reader.ie_key() for reader in gen_extractor_classes() if reader.working()}
    answers = ANSWERING_KEYS & switched_on
    assert answers == set(AGE_QUESTION_ANSWERED_BY_READER), "the list is the readers that answer, switched on ones only"

    reddit = (extractors / "reddit.py").read_text(encoding="utf-8")
    assert re.search(r"_set_cookie\('reddit\.com', 'over18', '1'\)", reddit)
    dailymotion = (extractors / "dailymotion.py").read_text(encoding="utf-8")
    assert "self._set_dailymotion_cookie('ff', 'on' if self._FAMILY_FILTER else 'off')" in dailymotion

    catalogued = {domain for entry in CATALOG for domain in entry.domains}
    for reader in ("Reddit", "Dailymotion"):
        domains = AGE_QUESTION_ANSWERED_BY_READER[reader]
        assert domains and set(domains) <= catalogued, "the rule names the same domains as the platform list"


def test_the_listed_readers_exist_under_those_names() -> None:
    keys = {reader.ie_key() for reader in gen_extractor_classes()}
    assert set(AGE_QUESTION_ANSWERED_BY_READER) <= keys


def test_a_post_that_hands_its_video_to_another_reader_keeps_its_address_and_label(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Reddit reader hands a video that is hosted elsewhere to the reader of that website.

    Read here with the real yt-dlp against the sample source: the result then names the
    other reader, but keeps the address and the label of the post. The rule relies on that.
    """
    class PostIE(InfoExtractor):  # type: ignore[misc]
        IE_NAME = "Post"
        _VALID_URL = r"http://127\.0\.0\.1:\d+/post/(?P<id>\w+)"

        def _real_extract(self, url: str) -> dict[str, Any]:
            return {"_type": "url_transparent", "url": f"{source}/watch/demo", "id": self._match_id(url),
                    "title": "A post", "age_limit": 18}

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        ydl.add_info_extractor(PostIE())
        ydl._ies = {"Post": ydl._ies.pop("Post"), **ydl._ies}  # ahead of the built-in readers
        info = ydl.sanitize_info(ydl.extract_info(f"{source}/post/abc", download=False), remove_private_keys=True)

    assert info["extractor_key"] == "HTML5MediaEmbed", "the other reader finished the job"
    assert info["webpage_url"] == f"{source}/post/abc" and info["age_limit"] == 18
    assert refusal(info, CONFIRM) is None, "an ordinary website: the label alone declines nothing"

    monkeypatch.setitem(tasks.AGE_QUESTION_ANSWERED_BY_READER, "Reddit", ("reddit.com", "redd.it", "127.0.0.1"))
    assert refusal(info, CONFIRM) == "age_confirmation_required", "the address of the post decides"
    assert refusal(info, CONFIRM, age_confirmed=True) is None
    assert refusal({**info, "age_limit": 0}, CONFIRM) is None


def test_a_refusal_through_another_reader_is_still_explained_as_an_age_check() -> None:
    # A Reddit post that is not marked 18+ and embeds a YouTube video that is: Reddit's
    # label (0) replaces YouTube's, the reader's notice and "needs an account" remain.
    info = video(extractor_key="Youtube", age_limit=0, availability="needs_auth",
                 webpage_url="https://www.reddit.com/r/videos/comments/abc/")
    assert refusal(info, CONFIRM, age_check=True) == "age_confirmation_required"
    assert refusal(info, CONFIRM, age_check=True, age_confirmed=True) is None
    assert refusal(info, CONFIRM, age_check=False) == "login_required"


# ------------------------------------------------------------ what the visitor is told
@pytest.mark.parametrize("message", [
    "[youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.",
    "[youtube] x: Sign in to confirm your age. Use --cookies-from-browser or --cookies for the authentication.",
    "[niconico] sm1: Login is required to access age-restricted content",
    "[twitter] 1: NSFW tweet requires authentication. Use --cookies, --cookies-from-browser",
    "[x] 1: This content is age restricted",
    "[x] 1: playability status: AGE_VERIFICATION_REQUIRED",
    "[x] 1: age_check_required",
    "[x] 1: This video requires age verification in your region",
    "[x] 1: You must be 18 years or older to watch this video",
    "[x] 1: This video is only available to viewers over 18",
    "[x] 1: Adult content. Log in to view",
    "[x] 1: This video is rated 18+ and needs an account",
    "[pandatv] x: Adult verification is required for this stream",   # a sign-in for the age check
])
def test_refusals_for_age_reasons_are_recognised(message: str) -> None:
    assert classify_message(message, default="fallback") == "age_restricted"


@pytest.mark.parametrize(("message", "code"), [
    # the letters "age" inside other words used to be enough
    ("[x] 1: This page restricts automated access", "fallback"),
    ("[x] 1: Usage restricted by the uploader", "fallback"),
    ("[x] 1: The image verification could not be completed", "fallback"),
    ("[x] 1: Bad message gateway", "fallback"),
    ("[x] 1: Storage restriction reached", "fallback"),
    ("[x] 1: Language restricted stream", "fallback"),
    # numbers that only look like an age
    ("[x] 1: Requires player version 3.18+", "fallback"),
    ("[x] 2018 years of history: Unable to extract video data", "fallback"),
    ("[x] 1: Stream ended after 118 years", "fallback"),
    # other reasons keep their own explanation
    ("[x] 1: This page restricts access. HTTP Error 403: Forbidden", "source_forbidden"),
    ("[youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "verification_required"),
    ("[twitter] 1: You are not authorized to view this protected tweet. Use --cookies", "login_required"),
    ("[instagram] x: Requested content is not available, rate-limit reached or login required", "login_required"),
    ("[nbc] x: sensitive", "fallback"),   # a request parameter, not the platform's message
])
def test_ordinary_failures_are_not_blamed_on_age(message: str, code: str) -> None:
    assert classify_message(message, default="fallback") == code
