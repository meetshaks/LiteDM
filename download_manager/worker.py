from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

from .models import DownloadItem, DownloadStatus, TransferResult
from .utils import finalize_download, partial_size


class _Paused(Exception):
    pass


class _Cancelled(Exception):
    pass


class DownloadWorker(QThread):
    progress = Signal(str, int, int, float)
    result = Signal(object)

    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item = item.copy()
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._response_lock = threading.Lock()
        self._response: requests.Response | None = None
        self._session = requests.Session()
        self._downloaded = 0
        self._total = item.total_bytes

    def pause(self) -> None:
        self._pause_event.set()
        self._close_response()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._close_response()

    def _close_response(self) -> None:
        with self._response_lock:
            response = self._response
        if response is not None:
            response.close()

    def _check_control(self) -> None:
        if self._cancel_event.is_set():
            raise _Cancelled
        if self._pause_event.is_set():
            raise _Paused

    def _request(self, offset: int) -> requests.Response:
        self._check_control()
        headers = {
            "User-Agent": "LiteDM/1.0",
            "Accept-Encoding": "identity",
        }
        if offset:
            headers["Range"] = f"bytes={offset}-"
        response = self._session.get(
            self.item.url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(10, 20),
        )
        with self._response_lock:
            self._response = response
        self._check_control()
        return response

    @staticmethod
    def _content_length(response: requests.Response) -> int:
        value = response.headers.get("Content-Length")
        if value is None:
            return -1
        try:
            length = int(value)
        except ValueError as exc:
            raise IOError("The server sent an invalid Content-Length header.") from exc
        if length < 0:
            raise IOError("The server sent an invalid Content-Length header.")
        return length

    @staticmethod
    def _content_range(response: requests.Response, offset: int) -> int:
        value = response.headers.get("Content-Range", "")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", value.strip(), re.IGNORECASE)
        if not match:
            raise IOError("The server sent an invalid Content-Range header.")
        start, end, total = match.groups()
        if int(start) != offset or int(end) < int(start):
            raise IOError("The server returned the wrong byte range; the partial file was preserved.")
        return -1 if total == "*" else int(total)

    @staticmethod
    def _destination_from_content_type(destination: str, response: requests.Response) -> str:
        path = Path(destination)
        if path.suffix:
            return destination
        media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        image_extensions = {
            "image/avif": ".avif",
            "image/bmp": ".bmp",
            "image/gif": ".gif",
            "image/heic": ".heic",
            "image/heif": ".heif",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/svg+xml": ".svg",
            "image/tiff": ".tif",
            "image/vnd.microsoft.icon": ".ico",
            "image/webp": ".webp",
            "image/x-icon": ".ico",
        }
        extension = image_extensions.get(media_type)
        return str(path.with_suffix(extension)) if extension else destination

    def _emit_progress(self, downloaded: int, total: int, speed: float) -> None:
        self._downloaded = downloaded
        self._total = total
        self.progress.emit(self.item.id, downloaded, total, speed)

    def _download(self) -> TransferResult:
        offset = partial_size(self.item.temp_path)
        downloaded = offset
        total = self.item.total_bytes
        reset = False
        response = self._request(offset)
        try:
            if response.status_code == 416 and offset:
                response.close()
                with self._response_lock:
                    self._response = None
                offset = 0
                downloaded = 0
                total = -1
                reset = True
                response = self._request(0)
            response.raise_for_status()
            if response.status_code == 206:
                total = self._content_range(response, offset)
                if total < 0:
                    length = self._content_length(response)
                    total = offset + length if length >= 0 else -1
            else:
                if offset:
                    downloaded = 0
                    offset = 0
                    reset = True
                total = self._content_length(response)
            destination = self._destination_from_content_type(
                self.item.destination, response
            )
            self._check_control()
            descriptor = os.open(
                self.item.temp_path,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            )
            with os.fdopen(descriptor, "r+b") as output:
                info = os.fstat(output.fileno())
                if reset:
                    output.seek(0)
                    output.truncate(0)
                    downloaded = 0
                else:
                    if info.st_size != downloaded:
                        raise IOError("The partial file changed unexpectedly; retry with a new download.")
                    output.seek(downloaded)
                self._emit_progress(downloaded, total, 0.0)
                last_time = time.monotonic()
                last_bytes = downloaded
                try:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        self._check_control()
                        if not chunk:
                            continue
                        output.write(chunk)
                        downloaded += len(chunk)
                        self._downloaded = downloaded
                        self._check_control()
                        now = time.monotonic()
                        elapsed = now - last_time
                        if elapsed >= 0.35:
                            speed = (downloaded - last_bytes) / elapsed
                            self._emit_progress(downloaded, total, speed)
                            last_time = now
                            last_bytes = downloaded
                    output.flush()
                    os.fsync(output.fileno())
                except (_Paused, _Cancelled):
                    output.flush()
                    os.fsync(output.fileno())
                    raise
            if total >= 0 and downloaded != total:
                raise IOError(
                    f"Incomplete response: expected {total} bytes but received {downloaded}. Retry the download."
                )
            if total < 0:
                total = downloaded
            final_path = finalize_download(self.item.temp_path, destination)
            self._emit_progress(downloaded, total, 0.0)
            return TransferResult(
                self.item.id,
                DownloadStatus.COMPLETED,
                downloaded,
                total,
                str(final_path),
            )
        finally:
            response.close()
            with self._response_lock:
                if self._response is response:
                    self._response = None

    def run(self) -> None:
        try:
            self._downloaded = partial_size(self.item.temp_path)
            result = self._download()
        except _Paused:
            result = TransferResult(
                self.item.id,
                DownloadStatus.PAUSED,
                self._downloaded,
                self._total,
                self.item.destination,
            )
        except _Cancelled:
            result = TransferResult(
                self.item.id,
                DownloadStatus.CANCELLED,
                self._downloaded,
                self._total,
                self.item.destination,
            )
        except Exception as error:
            try:
                self._downloaded = partial_size(self.item.temp_path)
            except Exception:
                pass
            message = str(error).strip() or error.__class__.__name__
            result = TransferResult(
                self.item.id,
                DownloadStatus.FAILED,
                self._downloaded,
                self._total,
                self.item.destination,
                message[:1000],
            )
        self.result.emit(result)
        self._session.close()
