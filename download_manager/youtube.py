from __future__ import annotations

import os
import math
import re
import shutil
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .utils import format_size

MAX_MP3_BITRATE = 320


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def _valid_staging_prefix(prefix: str) -> bool:
    base = Path(prefix)
    return base.name == "media" and bool(
        re.fullmatch(r"\.litedm-[0-9a-f]{32}", base.parent.name)
    )


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host in YOUTUBE_HOSTS


def is_youtube_playlist_url(url: str) -> bool:
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return False
    return parsed.path.rstrip("/") == "/playlist" and not parse_qs(parsed.query).get("v")


def _size(format_info: dict, duration: int = 0) -> tuple[int, bool]:
    value = format_info.get("filesize")
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = -1
    if size >= 0:
        return size, False

    value = format_info.get("filesize_approx")
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = -1
    if size >= 0:
        return size, True

    if duration > 0:
        for key in ("tbr", "vbr", "abr"):
            try:
                bitrate = float(format_info.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if math.isfinite(bitrate) and bitrate > 0:
                return int(bitrate * 1000 * duration / 8), True
    return -1, False


def _size_label(size: int, estimated: bool) -> str:
    if size < 0:
        return ""
    return f"~{format_size(size)}" if estimated else format_size(size)


def _codec_label(codec: object) -> str:
    return str(codec) if codec and codec != "none" else "none"


def _resolution(format_info: dict) -> str:
    height = format_info.get("height")
    width = format_info.get("width")
    if height:
        return f"{height}p"
    if width and format_info.get("resolution"):
        return str(format_info["resolution"])
    return str(format_info.get("format_note") or format_info.get("resolution") or "Unknown resolution")


def _estimated_video_size(
    format_info: dict,
    best_audio_size: tuple[int, bool],
    duration: int,
) -> tuple[int, bool]:
    video_size, estimated = _size(format_info, duration)
    if format_info.get("acodec") not in (None, "none"):
        return video_size, estimated
    if video_size >= 0 and best_audio_size[0] >= 0:
        return video_size + best_audio_size[0], estimated or best_audio_size[1]
    return -1, False


def format_choices(info: dict) -> list[dict]:
    formats = info.get("formats") or []
    try:
        duration = max(0, int(info.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    audios = [
        value for value in formats
        if value.get("acodec") not in (None, "none")
        and value.get("vcodec") in (None, "none")
    ]
    known_audio_sizes = [_size(value, duration) for value in audios]
    best_audio_size = max(known_audio_sizes, key=lambda value: value[0], default=(-1, False))
    videos = [
        value for value in formats
        if value.get("vcodec") not in (None, "none")
    ]
    videos.sort(
        key=lambda value: (
            int(value.get("height") or 0),
            int(value.get("tbr") or 0),
            str(value.get("format_id") or ""),
        ),
        reverse=True,
    )
    best_formats: dict[str, dict] = {}
    for value in videos:
        format_id = str(value.get("format_id") or "")
        extension = str(value.get("ext") or "").lower()
        if not format_id or extension != "mp4":
            continue
        key = _resolution(value)
        current = best_formats.get(key)
        try:
            bitrate = float(value.get("tbr") or value.get("vbr") or 0)
        except (TypeError, ValueError):
            bitrate = 0.0
        try:
            current_bitrate = float(
                (current or {}).get("tbr") or (current or {}).get("vbr") or 0
            )
        except (TypeError, ValueError):
            current_bitrate = 0.0
        if current is not None and (
            bitrate < current_bitrate
            or (bitrate == current_bitrate and bool(value.get("acodec") not in (None, "none"))
                <= bool(current.get("acodec") not in (None, "none")))
        ):
            continue
        best_formats[key] = value

    choices: list[dict] = []
    for value in best_formats.values():
        format_id = str(value["format_id"])
        has_audio = value.get("acodec") not in (None, "none")
        selector = format_id if has_audio else f"{format_id}+bestaudio"
        resolution = _resolution(value)
        extension = str(value.get("ext") or "unknown")
        size, estimated = _estimated_video_size(value, best_audio_size, duration)
        if size < 0:
            continue
        codecs = f"Video: {_codec_label(value.get('vcodec'))}"
        if has_audio:
            codecs += f" · Audio: {_codec_label(value.get('acodec'))}"
        else:
            codecs += " · Audio: best available"
        choices.append(
            {
                "label": f"{resolution} · {_size_label(size, estimated)}",
                "format_id": selector,
                "size": size,
                "estimated": estimated,
                "resolution": resolution,
                "codecs": codecs,
                "audio_only": False,
                "extension": extension,
            }
        )
    choices.sort(
        key=lambda value: -next(
            (
                int(fmt.get("height") or 0)
                for fmt in best_formats.values()
                if f"{fmt.get('format_id')}+bestaudio" == value["format_id"]
                or str(fmt.get("format_id")) == value["format_id"]
            ),
            0,
        )
    )
    return choices


def audio_choices(info: dict) -> list[dict]:
    formats = info.get("formats") or []
    try:
        duration = max(0, int(info.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    audios = [
        value for value in formats
        if value.get("acodec") not in (None, "none")
        and value.get("vcodec") in (None, "none")
    ]
    audios.sort(
        key=lambda value: (int(value.get("abr") or 0), int(value.get("tbr") or 0)),
        reverse=True,
    )
    choices: list[dict] = []
    seen: set[str] = set()
    for value in audios:
        format_id = str(value.get("format_id") or "")
        if not format_id or format_id in seen:
            continue
        seen.add(format_id)
        extension = str(value.get("ext") or "unknown")
        bitrate = value.get("abr") or value.get("tbr")
        bitrate_text = f"{int(bitrate)} kb/s" if bitrate else "bitrate unknown"
        size, estimated = _size(value, duration)
        if size < 0:
            continue
        choices.append(
            {
                "label": f"{extension} · {bitrate_text} · {_size_label(size, estimated)}",
                "format_id": format_id,
                "size": size,
                "estimated": estimated,
                "resolution": "Audio",
                "codecs": f"Audio: {_codec_label(value.get('acodec'))}",
                "audio_only": True,
                "extension": extension,
            }
        )
    return choices


def mp3_estimated_size(duration: int, bitrate: int) -> int:
    if duration <= 0 or bitrate <= 0:
        return -1
    return int(duration * bitrate * 1000 / 8)


def duration_text(seconds: object) -> str:
    if seconds is None:
        return "Unknown duration"
    try:
        value = max(0, int(seconds))
    except (TypeError, ValueError):
        return "Unknown duration"
    hours, remainder = divmod(value, 3600)
    minutes, seconds_value = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds_value:02d}" if hours else f"{minutes}:{seconds_value:02d}"


def staging_files(prefix: str) -> list[Path]:
    base = Path(prefix)
    if not _valid_staging_prefix(prefix):
        return []
    try:
        info = base.parent.lstat()
    except FileNotFoundError:
        return []
    if not stat.S_ISDIR(info.st_mode):
        return []
    return [
        path for path in base.parent.glob(f"{base.name}.*")
        if path.is_file() and not path.is_symlink()
    ]


def staging_size(prefix: str) -> int:
    total = 0
    for path in staging_files(prefix):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def remove_staging(prefix: str) -> None:
    if not _valid_staging_prefix(prefix):
        return
    for path in staging_files(prefix):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    directory = Path(prefix).parent
    try:
        directory.rmdir()
    except OSError:
        pass


def ensure_staging_directory(prefix: str) -> None:
    directory = Path(prefix).parent
    if not _valid_staging_prefix(prefix):
        raise OSError("The private YouTube staging path is invalid.")
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("The private YouTube staging path is not a safe directory.")
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(directory, 0o700)


def release_destination_reservation(destination: str | Path) -> None:
    reservation = Path(f"{destination}.part")
    try:
        info = reservation.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_size == 0:
            reservation.unlink()
    except FileNotFoundError:
        pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def thumbnail_allowed(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "ytimg.com"
        or host.endswith(".ytimg.com")
        or host == "googleusercontent.com"
        or host.endswith(".googleusercontent.com")
    )
