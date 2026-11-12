"""The built-in platform catalog.

``support`` is what to expect *before* anything was checked on this server:

* ``full``        - public videos normally work without signing in.
* ``partial``     - works with known limits, described in ``note``.
* ``unsupported`` - cannot work within the rules of this service (DRM, or
  everything needs an account). Such platforms can never be enabled.

It is a starting point, not a promise: platforms change, and many of them treat
servers differently from home connections. The admin panel's compatibility check
replaces the expectation with what was actually observed.

``full`` is kept for platforms that gave a public video to the project's own
survey (``scripts/live_smoke.py --survey``, run from a GitHub-hosted runner). A
platform that turned that run away, or whose reader failed, is ``partial`` at most.

``domains`` entries match the name itself and its sub-domains. An entry ending in
``.*`` (``pinterest.*``) also matches country versions (``pinterest.co.uk``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Support = Literal["full", "partial", "unsupported"]
Region = Literal["global", "open", "japan", "china", "korea", "russia", "drm"]


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    domains: tuple[str, ...]
    support: Support = "full"
    note: str | None = None
    region: Region = "global"


_LOGIN = "Only public posts. This platform often asks servers to sign in, which Lumora never does."
_DRM = "Protected with DRM. Lumora never circumvents DRM."
_COOKIES = "Needs browser cookies for every video, which Lumora never uses."

CATALOG: tuple[CatalogEntry, ...] = (
    # --- sources that publish their videos for download and reuse -------------------
    CatalogEntry("internet-archive", "Internet Archive", ("archive.org",), region="open"),
    CatalogEntry("wikimedia-commons", "Wikimedia Commons", ("wikimedia.org",), region="open"),
    CatalogEntry("media-ccc", "media.ccc.de", ("media.ccc.de",), region="open"),
    CatalogEntry("nasa", "NASA", ("nasa.gov",), "partial", "Pages that publish a plain video file.", "open"),
    CatalogEntry("blender", "Blender", ("blender.org",), "partial", "Pages that publish a plain video file.", "open"),
    # --- large international platforms ----------------------------------------------
    CatalogEntry(
        "youtube", "YouTube", ("youtube.com", "youtu.be", "youtube-nocookie.com"), "partial",
        "Public videos, usually in fewer qualities than a browser gets. Age-restricted, members-only and "
        "live videos are declined, and YouTube often asks servers to sign in.",
    ),
    CatalogEntry("vimeo", "Vimeo", ("vimeo.com",), "partial",
                 "Public videos. Private, password-protected and some embed-only videos are declined."),
    CatalogEntry("dailymotion", "Dailymotion", ("dailymotion.com", "dai.ly")),
    CatalogEntry("facebook", "Facebook", ("facebook.com", "fb.watch"), "partial", _LOGIN),
    CatalogEntry("instagram", "Instagram", ("instagram.com", "instagr.am"), "partial", _LOGIN),
    CatalogEntry("tiktok", "TikTok", ("tiktok.com",), "partial",
                 "Public videos. Availability depends on the server's country, and TikTok often blocks servers."),
    CatalogEntry("x", "X (Twitter)", ("x.com", "twitter.com"), "partial", _LOGIN),
    CatalogEntry("reddit", "Reddit", ("reddit.com", "redd.it"), "partial",
                 "Videos hosted by Reddit. Reddit often blocks servers."),
    CatalogEntry("pinterest", "Pinterest", ("pinterest.*", "pin.it"), "partial", "Video pins only."),
    CatalogEntry("twitch", "Twitch", ("twitch.tv",), "partial",
                 "Clips and past broadcasts. Live streams and subscriber-only videos are declined."),
    CatalogEntry("kick", "Kick", ("kick.com",), "partial", "Clips and past broadcasts. Live streams are declined."),
    CatalogEntry("rumble", "Rumble", ("rumble.com",), "partial", "Public videos. Rumble often turns servers away."),
    CatalogEntry("odysee", "Odysee", ("odysee.com", "lbry.tv")),
    CatalogEntry("bitchute", "BitChute", ("bitchute.com",)),
    CatalogEntry("streamable", "Streamable", ("streamable.com",)),
    CatalogEntry("ted", "TED", ("ted.com",)),
    CatalogEntry("imgur", "Imgur", ("imgur.com",), "partial", "Video posts only."),
    CatalogEntry("tumblr", "Tumblr", ("tumblr.com",), "partial", "Video posts only."),
    CatalogEntry("linkedin", "LinkedIn", ("linkedin.com",), "partial", _LOGIN),
    CatalogEntry("bluesky", "Bluesky", ("bsky.app",), "partial", "Video posts only."),
    CatalogEntry("snapchat", "Snapchat", ("snapchat.com",), "partial", "Public Spotlight videos only."),
    CatalogEntry("loom", "Loom", ("loom.com",), "partial", "Publicly shared recordings only."),
    CatalogEntry("flickr", "Flickr", ("flickr.com", "flic.kr"), "partial", "Video posts only."),
    CatalogEntry("9gag", "9GAG", ("9gag.com",), "partial", "Video posts only."),
    CatalogEntry("coub", "Coub", ("coub.com",)),
    CatalogEntry("likee", "Likee", ("likee.video",), "partial", "Public videos. Links often cannot be read."),
    # --- Japan --------------------------------------------------------------------------
    CatalogEntry("niconico", "Niconico", ("nicovideo.jp", "nico.ms"), "partial",
                 "Public videos. Many need a Niconico account and are declined.", "japan"),
    CatalogEntry("nhk", "NHK World", ("nhk.or.jp",), "partial", "On-demand programmes of NHK World.", "japan"),
    CatalogEntry("fc2", "FC2 Video", ("video.fc2.com",), "partial", "Free public videos only.", "japan"),
    CatalogEntry("abema", "ABEMA", ("abema.tv",), "unsupported",
                 "Available in Japan only and largely DRM-protected.", "japan"),
    CatalogEntry("tver", "TVer", ("tver.jp",), "unsupported", "Available in Japan only and DRM-protected.", "japan"),
    # --- China ------------------------------------------------------------------------------
    CatalogEntry("bilibili", "Bilibili", ("bilibili.com", "b23.tv", "bilibili.tv"), "partial",
                 "Public videos in the qualities offered without an account.", "china"),
    CatalogEntry("douyin", "Douyin", ("douyin.com",), "unsupported", _COOKIES, "china"),
    CatalogEntry("weibo", "Weibo", ("weibo.com", "weibo.cn"), "partial", _LOGIN, "china"),
    CatalogEntry("xigua", "Xigua Video", ("ixigua.com",), "unsupported", _COOKIES, "china"),
    CatalogEntry("acfun", "AcFun", ("acfun.cn",), region="china"),
    CatalogEntry("youku", "Youku", ("youku.com",), "partial",
                 "Free videos only. Mostly limited to China.", "china"),
    CatalogEntry("tencent-video", "Tencent Video", ("v.qq.com",), "partial",
                 "Free videos only. Mostly limited to China.", "china"),
    CatalogEntry("iqiyi", "iQIYI", ("iqiyi.com", "iq.com"), "unsupported",
                 "Requires an account for almost everything and uses DRM.", "china"),
    # --- Korea, Russia ------------------------------------------------------------------------
    CatalogEntry("naver", "Naver TV", ("tv.naver.com",), "partial",
                 "Public clips. Availability depends on the server's country.", "korea"),
    CatalogEntry("kakao", "Kakao TV", ("tv.kakao.com",), "partial",
                 "Public clips. Availability depends on the server's country.", "korea"),
    CatalogEntry("vk", "VK Video", ("vk.com", "vkvideo.ru", "vk.ru"), "partial", _LOGIN, "russia"),
    CatalogEntry("ok", "OK.ru", ("ok.ru",), region="russia"),
    CatalogEntry("rutube", "Rutube", ("rutube.ru",), region="russia"),
    # --- subscription services: never possible ---------------------------------------------
    CatalogEntry("netflix", "Netflix", ("netflix.com",), "unsupported", _DRM, "drm"),
    CatalogEntry("disney-plus", "Disney+", ("disneyplus.com",), "unsupported", _DRM, "drm"),
    CatalogEntry("prime-video", "Prime Video", ("primevideo.com",), "unsupported", _DRM, "drm"),
    CatalogEntry("hulu", "Hulu", ("hulu.com",), "unsupported", _DRM, "drm"),
    CatalogEntry("max", "Max", ("max.com", "hbomax.com"), "unsupported", _DRM, "drm"),
    CatalogEntry("apple-tv", "Apple TV+", ("tv.apple.com",), "unsupported", _DRM, "drm"),
    CatalogEntry("crunchyroll", "Crunchyroll", ("crunchyroll.com",), "unsupported", _DRM, "drm"),
    CatalogEntry("spotify", "Spotify", ("spotify.com",), "unsupported", _DRM, "drm"),
)


def catalog_by_id() -> dict[str, CatalogEntry]:
    return {entry.id: entry for entry in CATALOG}
