"""Generate small, synthetic media fixtures with FFmpeg.

Everything here is produced from FFmpeg's built-in test sources (colour bars and a
sine tone), so the fixtures contain no third-party content. They are used by the
integration tests and by ``scripts/sample_source.py`` (a local "public source"
you can point the app at during development).

Layout produced under ``out_dir``::

    media/v720.mp4 v360.mp4 v240.mp4   progressive H.264 + AAC
    media/v360.webm                    VP9 + Opus
    media/poster.jpg
    subs/en.vtt es.vtt fr.srt
    hls/master.m3u8 ...                2 muxed variants + WebVTT subtitle rendition
    dash/manifest.mpd ...              2 video representations + separate audio
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DURATION = 8  # seconds

EN_VTT = """WEBVTT

1
00:00:00.500 --> 00:00:02.500 align:start position:10%
<v Narrator>Welcome to the <i>Lumora</i> sample clip.</v>

2
00:00:03.000 --> 00:00:05.000
This file is generated from test bars
and a 440 Hz tone.

3
00:00:05.500 --> 00:00:07.500
Subtitles &amp; qualities are real.
"""

ES_VTT = """WEBVTT

00:00:00.500 --> 00:00:02.500
Bienvenido al clip de muestra de Lumora.

00:00:03.000 --> 00:00:05.000
Este archivo se genera con barras de prueba
y un tono de 440 Hz.

00:00:05.500 --> 00:00:07.500
Los subtítulos y las calidades son reales.
"""

FR_SRT = """1
00:00:00,500 --> 00:00:02,500
Bienvenue dans le clip d'exemple Lumora.

2
00:00:03,000 --> 00:00:05,000
Ce fichier est généré à partir de mires
et d'une tonalité de 440 Hz.

3
00:00:05,500 --> 00:00:07,500
Les sous-titres et les qualités sont réels.
"""


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment specific
        raise RuntimeError("FFmpeg is required to build fixtures") from exc


def run(ffmpeg: str, *args: str) -> None:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args)}\n{proc.stderr[-2000:]}")


def build(out_dir: Path) -> Path:
    """Build every fixture into ``out_dir`` (idempotent) and return it."""
    marker = out_dir / ".complete"
    if marker.exists():
        return out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    media, subs, hls, dash = (out_dir / n for n in ("media", "subs", "hls", "dash"))
    for d in (media, subs, hls / "subs", dash):
        d.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    source = [
        "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={DURATION}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={DURATION}",
    ]
    x264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60",
            "-sc_threshold", "0"]
    aac = ["-c:a", "aac", "-b:a", "96k", "-ac", "2"]

    # --- progressive MP4 ladder -------------------------------------------------
    run(ffmpeg, *source, *x264, "-crf", "30", *aac, "-movflags", "+faststart", str(media / "v720.mp4"))
    master = str(media / "v720.mp4")
    for height, width in ((360, 640), (240, 426)):
        run(ffmpeg, "-i", master, "-vf", f"scale={width}:{height}", *x264, "-crf", "32", *aac,
            "-movflags", "+faststart", str(media / f"v{height}.mp4"))

    # --- WebM (VP9 + Opus) ------------------------------------------------------
    run(ffmpeg, "-i", master, "-vf", "scale=640:360", "-c:v", "libvpx-vp9", "-deadline", "realtime",
        "-cpu-used", "8", "-b:v", "300k", "-c:a", "libopus", "-b:a", "64k", str(media / "v360.webm"))

    # --- poster -----------------------------------------------------------------
    run(ffmpeg, "-ss", "1", "-i", master, "-frames:v", "1", "-vf", "scale=640:360", "-q:v", "5",
        str(media / "poster.jpg"))

    # --- subtitles --------------------------------------------------------------
    (subs / "en.vtt").write_text(EN_VTT, encoding="utf-8")
    (subs / "es.vtt").write_text(ES_VTT, encoding="utf-8")
    (subs / "fr.srt").write_text(FR_SRT, encoding="utf-8")

    # --- HLS: two muxed variants + a WebVTT subtitle rendition -------------------
    run(
        ffmpeg, "-i", master,
        "-filter_complex", "[0:v]split=2[a][b];[a]scale=640:360[v0];[b]scale=426:240[v1]",
        "-map", "[v0]", "-map", "0:a", "-map", "[v1]", "-map", "0:a",
        *x264, "-b:v:0", "500k", "-b:v:1", "250k", *aac,
        "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
        "-hls_segment_filename", str(hls / "v%v_seg%03d.ts"),
        "-master_pl_name", "master.m3u8",
        "-var_stream_map", "v:0,a:0 v:1,a:1",
        str(hls / "v%v.m3u8"),
    )
    (hls / "subs" / "en.vtt").write_text(
        EN_VTT.replace("WEBVTT\n", "WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:126000,LOCAL:00:00:00.000\n", 1),
        encoding="utf-8",
    )
    (hls / "subs" / "en.m3u8").write_text(
        f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:{DURATION}\n#EXT-X-MEDIA-SEQUENCE:0\n"
        f"#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:{DURATION}.000,\nen.vtt\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    lines = (hls / "master.m3u8").read_text(encoding="utf-8").splitlines()
    patched: list[str] = []
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            line += ',SUBTITLES="subs"'
        patched.append(line)
        if line.startswith("#EXT-X-VERSION"):
            patched.append(
                '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",DEFAULT=YES,'
                'AUTOSELECT=YES,FORCED=NO,LANGUAGE="en",URI="subs/en.m3u8"'
            )
    (hls / "master.m3u8").write_text("\n".join(patched) + "\n", encoding="utf-8")

    # --- DASH: two video representations + separate audio ------------------------
    run(
        ffmpeg, "-i", master,
        "-filter_complex", "[0:v]split=2[a][b];[a]scale=640:360[v0];[b]scale=426:240[v1]",
        "-map", "[v0]", "-map", "[v1]", "-map", "0:a",
        *x264, "-b:v:0", "500k", "-b:v:1", "250k", *aac,
        "-f", "dash", "-seg_duration", "2", "-use_template", "1", "-use_timeline", "1",
        "-adaptation_sets", "id=0,streams=v id=1,streams=a",
        str(dash / "manifest.mpd"),
    )

    marker.write_text("ok", encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "./.fixtures").resolve()
    build(target)
    total = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    print(f"fixtures ready in {target} ({total / 1e6:.1f} MB)")
