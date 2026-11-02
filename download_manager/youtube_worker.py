from __future__ import annotations

import threading
import shutil
import time
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

from .models import DownloadItem, DownloadStatus, TransferResult
from .utils import finalize_download_from
from .youtube import (
    ensure_staging_directory,
    is_youtube_playlist_url,
    MAX_MP3_BITRATE,
    release_destination_reservation,
    remove_staging,
    staging_size,
    thumbnail_allowed,
)


class MetadataWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self) -> None:
        try:
            if is_youtube_playlist_url(self.url):
                raise ValueError("Playlist URLs are not supported; open a single video instead.")
            import yt_dlp

            options = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "extract_flat": False,
                "socket_timeout": 15,
                "retries": 1,
                "extractor_retries": 1,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.url, download=False)
            if not info:
                raise ValueError("No video information was returned.")
            if info.get("entries") is not None:
                raise ValueError("Playlist URLs are not supported; open a single video instead.")
            if info.get("is_live") or info.get("live_status") == "is_live":
                raise ValueError("Live streams cannot be downloaded.")
            thumbnail = b""
            thumbnail_url = str(info.get("thumbnail") or "")
            if thumbnail_allowed(thumbnail_url):
                try:
                    response = requests.get(
                        thumbnail_url,
                        timeout=(5, 10),
                        stream=True,
                        allow_redirects=False,
                    )
                    try:
                        response.raise_for_status()
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_content(64 * 1024):
                            size += len(chunk)
                            if size > 4 * 1024 * 1024:
                                break
                            chunks.append(chunk)
                        if size <= 4 * 1024 * 1024:
                            thumbnail = b"".join(chunks)
                    finally:
                        response.close()
                except requests.RequestException as error:
                    info["thumbnail_error"] = str(error)
            info["thumbnail_data"] = thumbnail
            self.loaded.emit(info)
        except Exception as error:
            if isinstance(error, ImportError):
                message = "yt-dlp is not installed. Install dependencies with: python -m pip install -r requirements.txt"
            else:
                message = str(error).strip() or error.__class__.__name__
            self.failed.emit(message[:1000])


class _TransferInterrupted(Exception):
    pass


class YouTubeDownloadWorker(QThread):
    progress = Signal(str, int, int, float)
    result = Signal(object)

    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item = item.copy()
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._downloaded = 0
        self._total = item.total_bytes
        self._speed = 0.0
        self._last_emit = 0.0
        self._stream_downloaded: dict[str, int] = {}
        self._stream_totals: dict[str, int] = {}
        self._expected_streams: set[str] = set()
        self._invalid_stream_totals: set[str] = set()
        self._final_path = ""
        self._interrupted = ""
        self._lock = threading.Lock()

    def pause(self) -> None:
        self._pause_event.set()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _control_hook(self, data: dict) -> None:
        if self._cancel_event.is_set():
            self._interrupted = "cancelled"
            raise _TransferInterrupted
        if self._pause_event.is_set():
            self._interrupted = "paused"
            raise _TransferInterrupted
        info = data.get("info_dict") or {}
        status = data.get("status")
        if status == "finished":
            filename = data.get("filename")
            if filename:
                self._final_path = str(filename)
        elif status != "downloading":
            return

        requested_formats = info.get("requested_formats") or []
        for index, requested_format in enumerate(requested_formats):
            format_id = str(requested_format.get("format_id") or index)
            key = f"format:{format_id}"
            self._expected_streams.add(key)
            size = self._format_size(requested_format)
            if size > 0 and key not in self._stream_totals:
                self._stream_totals[key] = size

        format_id = info.get("format_id")
        if format_id is not None:
            stream_key = f"format:{format_id}"
        elif len(self._expected_streams) == 1:
            stream_key = next(iter(self._expected_streams))
        else:
            filename = data.get("tmpfilename") or data.get("filename")
            stream_key = f"file:{filename}" if filename else "default"

        downloaded = int(data.get("downloaded_bytes") or 0)
        if status == "finished":
            downloaded = int(data.get("downloaded_bytes") or 0)

        candidate_totals = [
            self._positive_int(data.get("total_bytes")),
            self._positive_int(data.get("total_bytes_estimate")),
            self._format_size(info),
            self._stream_totals.get(stream_key, -1),
        ]
        if not self._expected_streams:
            candidate_totals.append(self.item.total_bytes)
        valid_totals = [
            value for value in candidate_totals
            if value > 0 and value >= downloaded
        ]
        if valid_totals:
            self._stream_totals[stream_key] = valid_totals[0]
            self._invalid_stream_totals.discard(stream_key)
        elif any(value > 0 for value in candidate_totals):
            self._stream_totals.pop(stream_key, None)
            self._invalid_stream_totals.add(stream_key)
        self._stream_downloaded[stream_key] = downloaded

        total = self._aggregate_total()
        downloaded = sum(self._stream_downloaded.values())
        speed = float(data.get("speed") or 0.0)
        now = time.monotonic()
        with self._lock:
            self._downloaded = downloaded
            self._speed = speed
            if now - self._last_emit >= 0.25:
                self._last_emit = now
                self._total = total
                self.progress.emit(self.item.id, downloaded, self._total, speed)

    @staticmethod
    def _positive_int(value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return -1
        return parsed if parsed > 0 else -1

    @classmethod
    def _format_size(cls, info: dict) -> int:
        return max(
            cls._positive_int(info.get("filesize")),
            cls._positive_int(info.get("filesize_approx")),
        )

    def _aggregate_total(self) -> int:
        if self._invalid_stream_totals:
            return -1
        if self._expected_streams:
            if not self._expected_streams.issubset(self._stream_totals):
                return -1
            return sum(self._stream_totals[key] for key in self._expected_streams)
        if self._stream_totals:
            return sum(self._stream_totals.values())
        if self._stream_downloaded:
            return -1
        if self.item.total_bytes > 0:
            return self.item.total_bytes
        return -1

    def _after_move(self, data: dict) -> None:
        filepath = data.get("info_dict", {}).get("filepath")
        if filepath:
            self._final_path = str(filepath)

    def _options(self) -> dict:
        import yt_dlp

        stage_base = Path(self.item.temp_path)
        ensure_staging_directory(str(stage_base))
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "continuedl": True,
            "nopart": False,
            "nooverwrites": True,
            "overwrites": False,
            "socket_timeout": 20,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "outtmpl": f"{stage_base}.%(ext)s",
            "progress_hooks": [self._control_hook],
            "postprocessor_hooks": [self._after_move],
        }
        if self.item.audio_only and self.item.media_format == "mp3":
            if not shutil.which("ffmpeg"):
                raise RuntimeError("FFmpeg is required to create MP3 audio. Install ffmpeg and retry.")
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(MAX_MP3_BITRATE),
                }
            ]
        else:
            options["format"] = self.item.media_format or "bestvideo*+bestaudio/best"
            if "+" in options["format"] and not shutil.which("ffmpeg"):
                raise RuntimeError("FFmpeg is required to merge the selected video and audio streams.")
            if "+" in options["format"]:
                container = Path(self.item.destination).suffix.lstrip(".").lower()
                if container in {"mp4", "webm", "mkv"}:
                    options["merge_output_format"] = container
        return options

    def _download(self) -> TransferResult:
        import yt_dlp

        result_info: dict | None = None
        try:
            with yt_dlp.YoutubeDL(self._options()) as ydl:
                result_info = ydl.extract_info(self.item.url, download=True)
        except Exception:
            if self._interrupted:
                status = DownloadStatus.PAUSED if self._interrupted == "paused" else DownloadStatus.CANCELLED
                return TransferResult(
                    self.item.id,
                    status,
                    max(self._downloaded, staging_size(self.item.temp_path)),
                    self._total,
                    self.item.destination,
                )
            raise
        if self._cancel_event.is_set():
            self._interrupted = "cancelled"
        elif self._pause_event.is_set():
            self._interrupted = "paused"
        if self._interrupted:
            status = DownloadStatus.PAUSED if self._interrupted == "paused" else DownloadStatus.CANCELLED
            return TransferResult(
                self.item.id,
                status,
                max(self._downloaded, staging_size(self.item.temp_path)),
                self._total,
                self.item.destination,
            )
        if not self._final_path and result_info:
            candidate = result_info.get("filepath") or result_info.get("_filename")
            if candidate:
                self._final_path = str(candidate)
        source = Path(self._final_path)
        if not source.is_file():
            raise RuntimeError("yt-dlp finished without producing a media file.")
        file_size = source.stat().st_size
        requested_destination = Path(self.item.destination)
        extension = source.suffix
        if extension and extension[1:].isalnum():
            requested_destination = requested_destination.with_suffix(extension)
        final_path = finalize_download_from(source, requested_destination)
        remove_staging(self.item.temp_path)
        release_destination_reservation(self.item.destination)
        self.progress.emit(self.item.id, file_size, file_size, 0.0)
        return TransferResult(
            self.item.id,
            DownloadStatus.COMPLETED,
            file_size,
            file_size,
            str(final_path),
        )

    def run(self) -> None:
        try:
            result = self._download()
        except Exception as error:
            message = str(error).strip() or error.__class__.__name__
            if "ffmpeg" in message.lower() and "required" not in message.lower():
                message = f"FFmpeg is unavailable: {message}"
            result = TransferResult(
                self.item.id,
                DownloadStatus.FAILED,
                max(self._downloaded, staging_size(self.item.temp_path)),
                self._total,
                self.item.destination,
                message[:1000],
            )
        self.result.emit(result)
