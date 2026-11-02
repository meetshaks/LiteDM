from __future__ import annotations

import errno
import os
import re
import shutil
import stat
import sys
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

APP_ID = "litetdm"
MAX_FILENAME_BYTES = 240


def app_icon_path() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir) / "icons" / "5.png"
    return Path(__file__).resolve().parents[1] / "icons" / "5.png"


def validate_url(url: str) -> str:
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a valid HTTP or HTTPS URL.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("The URL contains an invalid port.") from exc
    if any(ord(char) < 32 for char in value):
        raise ValueError("The URL contains control characters.")
    return value


def _truncate_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def sanitize_filename(name: str, fallback: str = "download") -> str:
    decoded = unquote(name).replace("\\", "/").split("/")[-1]
    normalized = unicodedata.normalize("NFC", decoded)
    cleaned = "".join("_" if ord(char) < 32 or char == "/" else char for char in normalized)
    cleaned = cleaned.strip().strip("\x00")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    suffix = Path(cleaned).suffix
    if len(suffix.encode("utf-8")) > 32 or suffix == cleaned:
        suffix = ""
    stem = cleaned[: -len(suffix)] if suffix else cleaned
    stem = _truncate_utf8(stem, MAX_FILENAME_BYTES - len(suffix.encode("utf-8")))
    cleaned = f"{stem}{suffix}".rstrip()
    return cleaned or fallback


def filename_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return sanitize_filename(parsed.path, fallback="download")


def default_data_dir() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_ID
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def default_download_dir() -> Path:
    configured = None
    user_dirs = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "user-dirs.dirs"
    try:
        for line in user_dirs.read_text(encoding="utf-8").splitlines():
            match = re.match(r'^XDG_DOWNLOAD_DIR="([^"]+)"', line.strip())
            if match:
                configured = match.group(1).replace("$HOME", str(Path.home()))
                break
    except OSError:
        pass
    path = Path(configured).expanduser() if configured else Path.home() / "Downloads"
    return ensure_directory(path)


def ensure_directory(path: str | Path) -> Path:
    if not str(path).strip():
        raise ValueError("Choose a download folder.")
    directory = Path(path).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    if not directory.is_dir():
        raise ValueError("The download location is not a directory.")
    if not os.access(directory, os.W_OK | os.X_OK):
        raise ValueError("The download folder is not writable.")
    return directory


def _numbered_path(destination: Path, number: int) -> Path:
    if number == 0:
        return destination
    stem, suffix = os.path.splitext(destination.name)
    return destination.with_name(f"{stem} ({number}){suffix}")


def _open_flags(base: int) -> int:
    return base | getattr(os, "O_NOFOLLOW", 0)


def create_partial(path: str | Path) -> Path:
    partial = Path(path)
    if os.path.lexists(partial):
        info = partial.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"Partial path is not a regular file: {partial}")
        return partial
    descriptor = os.open(partial, _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
    os.close(descriptor)
    return partial


def allocate_destination(folder: str | Path, filename: str) -> tuple[Path, Path]:
    directory = ensure_directory(folder)
    safe_name = sanitize_filename(filename)
    requested = directory / safe_name
    for number in range(100000):
        destination = _numbered_path(requested, number)
        partial = Path(f"{destination}.part")
        if os.path.lexists(destination) or os.path.lexists(partial):
            continue
        try:
            descriptor = os.open(partial, _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
        except FileExistsError:
            continue
        os.close(descriptor)
        if os.path.lexists(destination):
            try:
                partial.unlink()
            except OSError:
                pass
            continue
        return destination, partial
    raise OSError("Could not allocate a unique download filename.")


def partial_size(path: str | Path) -> int:
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Partial path is not a regular file: {path}")
    return info.st_size


def _copy_without_overwrite(partial: Path, destination: Path) -> None:
    descriptor = os.open(destination, _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
    created = True
    try:
        source_fd = os.open(partial, _open_flags(os.O_RDONLY))
        with os.fdopen(source_fd, "rb") as source, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        raise


def finalize_download(partial_path: str | Path, requested_path: str | Path) -> Path:
    partial = Path(partial_path)
    requested = Path(requested_path)
    if partial.parent != requested.parent:
        raise ValueError("Partial and final files must be in the same folder.")
    partial_size(partial)
    for number in range(100000):
        destination = _numbered_path(requested, number)
        alternate_partial = Path(f"{destination}.part")
        if number and (os.path.lexists(destination) or os.path.lexists(alternate_partial)):
            continue
        try:
            os.link(partial, destination, follow_symlinks=False)
        except FileExistsError:
            continue
        except OSError as error:
            if error.errno in {errno.EMLINK, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV}:
                try:
                    _copy_without_overwrite(partial, destination)
                except FileExistsError:
                    continue
            else:
                raise
        try:
            partial.unlink()
        except OSError:
            pass
        return destination
    raise OSError("Could not finalize without overwriting an existing file.")


def finalize_download_from(source_path: str | Path, requested_path: str | Path) -> Path:
    source = Path(source_path)
    requested = Path(requested_path)
    partial_size(source)
    if source.parent == requested.parent:
        return finalize_download(source, requested)
    for _ in range(10):
        temporary = requested.parent / f".litedm-publish-{uuid.uuid4().hex}.part"
        try:
            descriptor = os.open(
                temporary,
                _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
                0o600,
            )
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "wb") as output:
                source_descriptor = os.open(source, _open_flags(os.O_RDONLY))
                with os.fdopen(source_descriptor, "rb") as input_file:
                    shutil.copyfileobj(input_file, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            return finalize_download(temporary, requested)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    raise OSError("Could not allocate a private file for finalization.")


def format_size(size: int | float) -> str:
    if size < 0:
        return "Unknown"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def format_speed(speed: float) -> str:
    return f"{format_size(speed)}/s" if speed > 0 else "—"


def format_eta(downloaded: int, total: int, speed: float) -> str:
    if speed <= 0 or total <= 0 or downloaded >= total:
        return ""
    remaining = total - downloaded
    seconds = remaining / speed
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes:02d}m"


_CATEGORY_MAP: dict[str, str] = {}
for _ext in (".iso", ".img", ".dmg", ".raw"):
    _CATEGORY_MAP[_ext] = "Linux ISOs & Images"
for _ext in (".dat", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".zst", ".tgz"):
    _CATEGORY_MAP[_ext] = "Archives (.dat / .zip)"
for _ext in (".deb", ".rpm", ".appimage", ".snap", ".flatpak"):
    _CATEGORY_MAP[_ext] = "Packages"
for _ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"):
    _CATEGORY_MAP[_ext] = "Videos"
for _ext in (".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a"):
    _CATEGORY_MAP[_ext] = "Audio"
for _ext in (".pdf", ".doc", ".docx", ".txt", ".odt"):
    _CATEGORY_MAP[_ext] = "Documents"


def file_category(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return _CATEGORY_MAP.get(ext, "Other")
