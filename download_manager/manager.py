from __future__ import annotations

import os
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .database import DownloadDatabase
from .logging import get_logger
from .models import DownloadItem, DownloadStatus, TransferResult, utc_now
from .utils import (
    allocate_destination,
    create_partial,
    ensure_directory,
    filename_from_url,
    partial_size,
    sanitize_filename,
    validate_url,
)
from .worker import DownloadWorker
from .youtube import (
    is_youtube_url,
    release_destination_reservation,
    remove_staging,
    staging_size,
)
from .youtube_worker import YouTubeDownloadWorker

logger = get_logger()


class DownloadManager(QObject):
    item_added = Signal(object)
    item_updated = Signal(object)
    item_removed = Signal(str)
    notification = Signal(str, str)
    active_count_changed = Signal(int)
    all_stopped = Signal()

    def __init__(self, database: DownloadDatabase, max_concurrent: int = 3, parent=None):
        super().__init__(parent)
        self.database = database
        self.max_concurrent = max(1, min(8, max_concurrent))
        self._items: dict[str, DownloadItem] = {}
        self._workers: dict[str, DownloadWorker | YouTubeDownloadWorker] = {}
        self._started = False
        self._shutting_down = False
        for item in self.database.load_all():
            if item.status in {DownloadStatus.DOWNLOADING, DownloadStatus.PAUSING}:
                item.status = DownloadStatus.PAUSED
                item.speed = 0.0
                item.updated_at = utc_now()
                self.database.save(item)
            elif item.status == DownloadStatus.CANCELLING:
                item.status = DownloadStatus.CANCELLED
                item.speed = 0.0
                item.updated_at = utc_now()
                self.database.save(item)
            self._items[item.id] = item

    def items(self) -> list[DownloadItem]:
        return [item.copy() for item in self._items.values()]

    def get(self, item_id: str) -> DownloadItem | None:
        item = self._items.get(item_id)
        return item.copy() if item else None

    def remove(self, item_id: str, *, delete_file: bool = False) -> None:
        item = self._items.pop(item_id, None)
        if item is None:
            return
        worker = self._workers.pop(item_id, None)
        if worker is not None:
            worker.cancel()
        if delete_file:
            for path in {item.destination, item.temp_path}:
                try:
                    Path(path).unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            if item.source_type == "youtube":
                remove_staging(item.temp_path)
                release_destination_reservation(item.destination)
        self.database.delete(item_id)
        self.item_removed.emit(item_id)

    def has_active_workers(self) -> bool:
        return bool(self._workers)

    def start(self) -> None:
        if self._shutting_down:
            return
        self._started = True
        self._schedule()

    def add_download(
        self,
        url: str,
        folder: str,
        filename: str = "",
        *,
        browser_origin: bool = False,
    ) -> str:
        if self._shutting_down:
            raise ValueError("The download manager is shutting down.")
        normalized_url = validate_url(url)
        safe_name = sanitize_filename(filename) if filename.strip() else filename_from_url(normalized_url)
        destination, partial = allocate_destination(folder, safe_name)
        timestamp = utc_now()
        item = DownloadItem(
            id=uuid.uuid4().hex,
            url=normalized_url,
            destination=str(destination),
            temp_path=str(partial),
            created_at=timestamp,
            updated_at=timestamp,
            browser_origin=browser_origin,
        )
        self.database.save(item)
        self._items[item.id] = item
        self.item_added.emit(item.copy())
        self._schedule()
        return item.id

    def add_youtube_download(
        self,
        url: str,
        folder: str,
        *,
        title: str,
        output_name: str = "",
        channel: str,
        duration: int,
        format_selector: str,
        filename_extension: str,
        estimated_size: int = -1,
        audio_only: bool = False,
        audio_bitrate: int = 320,
        browser_origin: bool = False,
    ) -> str:
        if self._shutting_down:
            raise ValueError("The download manager is shutting down.")
        normalized_url = validate_url(url)
        if not is_youtube_url(normalized_url):
            raise ValueError("Enter a supported YouTube video URL.")
        if not format_selector.strip():
            raise ValueError("Choose an available media format.")
        safe_title = sanitize_filename(output_name or title, fallback="youtube-video")
        extension = sanitize_filename(filename_extension.strip().lstrip("."), fallback="mkv")
        if not extension.isalnum():
            raise ValueError("The selected media format has an invalid file extension.")
        filename = f"{Path(safe_title).stem}.{extension}"
        destination, allocated_partial = allocate_destination(folder, filename)
        item_id = uuid.uuid4().hex
        staging_prefix = str(destination.parent / f".litedm-{item_id}" / "media")
        timestamp = utc_now()
        item = DownloadItem(
            id=item_id,
            url=normalized_url,
            destination=str(destination),
            temp_path=staging_prefix,
            total_bytes=estimated_size,
            created_at=timestamp,
            updated_at=timestamp,
            source_type="youtube",
            browser_origin=browser_origin,
            media_format=format_selector,
            audio_only=audio_only,
            audio_bitrate=320,
            media_title=title,
            media_channel=channel,
            media_duration=max(0, int(duration)),
        )
        try:
            self.database.save(item)
        except Exception:
            try:
                destination.with_name(f"{destination.name}.part").unlink()
            except OSError:
                pass
            raise
        self._items[item.id] = item
        self.item_added.emit(item.copy())
        self._schedule()
        return item.id

    def _save_and_emit(self, item: DownloadItem) -> None:
        item.updated_at = utc_now()
        self.database.save(item)
        self.item_updated.emit(item.copy())

    def _set_status(self, item: DownloadItem, status: DownloadStatus, *, persist: bool = True) -> None:
        if not item.status.can_transition_to(status):
            raise ValueError(f"Invalid status transition: {item.status.value} -> {status.value}")
        item.status = status
        item.speed = 0.0
        item.updated_at = utc_now()
        if persist:
            self._save_and_emit(item)

    def pause(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        if item.status == DownloadStatus.QUEUED:
            self._set_status(item, DownloadStatus.PAUSED)
        elif item.status == DownloadStatus.DOWNLOADING:
            worker = self._workers.get(item_id)
            if worker:
                self._set_status(item, DownloadStatus.PAUSING)
                worker.pause()

    def resume(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if item and item.status == DownloadStatus.PAUSED:
            self._enqueue_existing(item)

    def retry(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if item and item.status in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
            self._enqueue_existing(item)

    def cancel(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        if item.status in {DownloadStatus.QUEUED, DownloadStatus.PAUSED, DownloadStatus.FAILED}:
            self._set_status(item, DownloadStatus.CANCELLED)
        elif item.status in {DownloadStatus.DOWNLOADING, DownloadStatus.PAUSING}:
            worker = self._workers.get(item_id)
            if worker:
                self._set_status(item, DownloadStatus.CANCELLING)
                worker.cancel()

    def _enqueue_existing(self, item: DownloadItem) -> None:
        if self._shutting_down:
            return
        try:
            ensure_directory(Path(item.destination).parent)
            if item.source_type == "youtube":
                item.downloaded_bytes = staging_size(item.temp_path)
                if os.path.lexists(item.destination):
                    release_destination_reservation(item.destination)
                    destination, _partial = allocate_destination(item.folder, item.filename)
                    item.destination = str(destination)
                    item.temp_path = str(destination.parent / f".litedm-{item.id}" / "media")
            elif not os.path.lexists(item.temp_path):
                if os.path.lexists(item.destination):
                    destination, partial = allocate_destination(item.folder, item.filename)
                    item.destination = str(destination)
                    item.temp_path = str(partial)
                else:
                    create_partial(item.temp_path)
                item.downloaded_bytes = 0
                item.total_bytes = -1
            else:
                item.downloaded_bytes = (
                    staging_size(item.temp_path)
                    if item.source_type == "youtube"
                    else partial_size(item.temp_path)
                )
        except (OSError, ValueError) as error:
            item.status = DownloadStatus.FAILED
            item.error = str(error)
            item.speed = 0.0
            self._save_and_emit(item)
            self.notification.emit(f"{item.filename}: {item.error}", "error")
            return
        self._set_status(item, DownloadStatus.QUEUED)
        item.error = ""
        item.speed = 0.0
        item.completed_at = ""
        self._started = True
        self._schedule()

    def set_max_concurrent(self, value: int) -> None:
        self.max_concurrent = max(1, min(8, int(value)))
        self._schedule()

    def pause_all(self) -> None:
        for item_id, item in list(self._items.items()):
            if item.status in {DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING}:
                self.pause(item_id)

    def resume_all(self) -> None:
        for item_id, item in list(self._items.items()):
            if item.status == DownloadStatus.PAUSED:
                self.resume(item_id)

    def shutdown(self) -> None:
        self._shutting_down = True
        self._started = False
        self.pause_all()

    def _schedule(self) -> None:
        if not self._started or self._shutting_down:
            return
        for item in self._items.values():
            if len(self._workers) >= self.max_concurrent:
                break
            if item.status == DownloadStatus.QUEUED and item.id not in self._workers:
                self._launch(item)

    def _launch(self, item: DownloadItem) -> None:
        try:
            item.downloaded_bytes = (
                staging_size(item.temp_path)
                if item.source_type == "youtube"
                else partial_size(item.temp_path)
            )
        except OSError as error:
            item.status = DownloadStatus.FAILED
            item.error = str(error)
            self._save_and_emit(item)
            self.notification.emit(f"{item.filename}: {item.error}", "error")
            return
        self._set_status(item, DownloadStatus.DOWNLOADING, persist=False)
        item.error = ""
        item.speed = 0.0
        worker = (
            YouTubeDownloadWorker(item, self)
            if item.source_type == "youtube"
            else DownloadWorker(item, self)
        )
        self._workers[item.id] = worker
        worker.progress.connect(self._on_progress)
        worker.result.connect(self._on_result)
        worker.finished.connect(lambda item_id=item.id: self._on_thread_finished(item_id))
        self._save_and_emit(item)
        self.active_count_changed.emit(len(self._workers))
        worker.start()

    def _on_progress(self, item_id: str, downloaded: int, total: int, speed: float) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        item.downloaded_bytes = downloaded
        item.total_bytes = total
        item.speed = speed
        self.item_updated.emit(item.copy())

    def _on_result(self, result: TransferResult) -> None:
        item = self._items.get(result.id)
        if not item:
            return
        self._set_status(item, result.status, persist=False)
        item.downloaded_bytes = result.downloaded_bytes
        item.total_bytes = result.total_bytes
        item.destination = result.destination
        item.speed = 0.0
        item.error = result.error
        if result.status == DownloadStatus.COMPLETED:
            item.completed_at = utc_now()
            self.notification.emit(f"Completed: {item.filename}", "info")
        elif result.status == DownloadStatus.FAILED:
            self.notification.emit(f"{item.filename}: {result.error}", "error")
        self._save_and_emit(item)

    def _on_thread_finished(self, item_id: str) -> None:
        worker = self._workers.pop(item_id, None)
        if worker:
            worker.deleteLater()
        self.active_count_changed.emit(len(self._workers))
        self._schedule()
        if not self._workers:
            self.all_stopped.emit()
