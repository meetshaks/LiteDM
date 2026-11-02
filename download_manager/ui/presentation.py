from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..models import DownloadItem, DownloadStatus
from ..utils import file_category

ACTIVE_FILTER_STATUSES = {
    DownloadStatus.DOWNLOADING,
    DownloadStatus.PAUSING,
    DownloadStatus.CANCELLING,
    DownloadStatus.QUEUED,
}
PAUSED_STATUSES = {DownloadStatus.PAUSED, DownloadStatus.QUEUED}
FAILED_STATUSES = {DownloadStatus.FAILED, DownloadStatus.CANCELLED}


@dataclass(frozen=True, slots=True)
class QueueSummary:
    total: int
    active: int
    paused: int
    completed: int
    failed: int
    categories: dict[str, int]

    @property
    def status_text(self) -> str:
        parts = []
        if self.active:
            parts.append(f"{self.active} active")
        if self.paused:
            parts.append(f"{self.paused} paused")
        if self.completed:
            parts.append(f"{self.completed} completed")
        return f"·  {' · '.join(parts)}" if parts else ""


def matches_download(item: DownloadItem, query: str, mode: str, category: str) -> bool:
    normalized_query = query.strip().casefold()
    if normalized_query and (
        normalized_query not in item.filename.casefold()
        and normalized_query not in item.url.casefold()
    ):
        return False

    if mode == "active" and item.status not in ACTIVE_FILTER_STATUSES:
        return False
    if mode == "paused" and item.status not in PAUSED_STATUSES:
        return False
    if mode == "completed" and item.status != DownloadStatus.COMPLETED:
        return False
    if mode == "failed" and item.status not in FAILED_STATUSES:
        return False
    return not category or file_category(item.filename) == category


def summarize_downloads(items: Iterable[DownloadItem]) -> QueueSummary:
    item_list = list(items)
    return QueueSummary(
        total=len(item_list),
        active=sum(
            item.status in {
                DownloadStatus.DOWNLOADING,
                DownloadStatus.PAUSING,
                DownloadStatus.CANCELLING,
            }
            for item in item_list
        ),
        paused=sum(item.status in PAUSED_STATUSES for item in item_list),
        completed=sum(item.status == DownloadStatus.COMPLETED for item in item_list),
        failed=sum(item.status in FAILED_STATUSES for item in item_list),
        categories=dict(Counter(file_category(item.filename) for item in item_list)),
    )


def available_queue_actions(items: Iterable[DownloadItem]) -> dict[str, bool]:
    item_list = list(items)
    return {
        "Pause All": any(
            item.status in {DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING}
            for item in item_list
        ),
        "Resume All": any(item.status == DownloadStatus.PAUSED for item in item_list),
    }


def format_completion_time(completed_at: str) -> tuple[str, str] | None:
    if not completed_at:
        return None
    try:
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None

    hour = completed.strftime("%I").lstrip("0") or "12"
    display = (
        f"Downloaded {completed.strftime('%b')} {completed.day}, {completed.year}"
        f" · {hour}:{completed:%M %p}"
    )
    tooltip = (
        f"Completed {completed.strftime('%A, %B')} {completed.day}, {completed.year}"
        f" at {hour}:{completed:%M:%S %p} {completed.tzname()}"
    )
    return display, tooltip
