from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def valid_next_states(self) -> set["DownloadStatus"]:
        transition_map = {
            DownloadStatus.QUEUED: {DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED, DownloadStatus.CANCELLED, DownloadStatus.FAILED},
            DownloadStatus.DOWNLOADING: {DownloadStatus.PAUSING, DownloadStatus.CANCELLING, DownloadStatus.CANCELLED, DownloadStatus.FAILED, DownloadStatus.COMPLETED},
            DownloadStatus.PAUSING: {DownloadStatus.PAUSED, DownloadStatus.CANCELLING, DownloadStatus.CANCELLED, DownloadStatus.FAILED, DownloadStatus.COMPLETED},
            DownloadStatus.PAUSED: {DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.CANCELLED, DownloadStatus.FAILED},
            DownloadStatus.CANCELLING: {DownloadStatus.CANCELLED, DownloadStatus.COMPLETED},
            DownloadStatus.CANCELLED: {DownloadStatus.QUEUED},
            DownloadStatus.COMPLETED: {DownloadStatus.QUEUED},
            DownloadStatus.FAILED: {DownloadStatus.QUEUED, DownloadStatus.CANCELLED},
        }
        return transition_map.get(self, set())

    def can_transition_to(self, other: "DownloadStatus") -> bool:
        return other in self.valid_next_states


@dataclass(slots=True)
class DownloadItem:
    id: str
    url: str
    destination: str
    temp_path: str
    status: DownloadStatus = DownloadStatus.QUEUED
    total_bytes: int = -1
    downloaded_bytes: int = 0
    speed: float = 0.0
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    source_type: str = "http"
    browser_origin: bool = False
    media_format: str = ""
    audio_only: bool = False
    audio_bitrate: int = 320
    media_title: str = ""
    media_channel: str = ""
    media_duration: int = 0

    @property
    def filename(self) -> str:
        return Path(self.destination).name

    @property
    def folder(self) -> str:
        return str(Path(self.destination).parent)

    def copy(self) -> DownloadItem:
        return replace(self)


@dataclass(slots=True)
class TransferResult:
    id: str
    status: DownloadStatus
    downloaded_bytes: int
    total_bytes: int
    destination: str
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
