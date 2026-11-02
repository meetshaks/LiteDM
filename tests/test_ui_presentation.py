from __future__ import annotations

from datetime import datetime
from pathlib import Path

from download_manager.models import DownloadItem, DownloadStatus
from download_manager.ui.presentation import (
    available_queue_actions,
    format_completion_time,
    matches_download,
    summarize_downloads,
)


def make_item(name: str, status: DownloadStatus) -> DownloadItem:
    return DownloadItem(
        id=name,
        url=f"https://example.com/{name}",
        destination=str(Path("/tmp") / name),
        temp_path=str(Path("/tmp") / f"{name}.part"),
        status=status,
    )


def test_download_filtering_combines_text_status_and_category():
    item = make_item("Linux.iso", DownloadStatus.QUEUED)

    assert matches_download(item, "LINUX", "active", "Linux ISOs & Images")
    assert not matches_download(item, "absent", "active", "Linux ISOs & Images")
    assert not matches_download(item, "linux", "completed", "Linux ISOs & Images")
    assert not matches_download(item, "linux", "active", "Documents")


def test_queue_summary_and_action_availability():
    items = [
        make_item("one.zip", DownloadStatus.DOWNLOADING),
        make_item("two.iso", DownloadStatus.QUEUED),
        make_item("three.pdf", DownloadStatus.COMPLETED),
        make_item("four.bin", DownloadStatus.FAILED),
        make_item("five.tar", DownloadStatus.PAUSED),
    ]

    summary = summarize_downloads(items)

    assert (summary.total, summary.active, summary.paused, summary.completed, summary.failed) == (
        5,
        1,
        2,
        1,
        1,
    )
    assert summary.status_text == "·  1 active · 2 paused · 1 completed"
    assert summary.categories == {
        "Archives (.dat / .zip)": 2,
        "Linux ISOs & Images": 1,
        "Documents": 1,
        "Other": 1,
    }
    assert available_queue_actions(items) == {"Pause All": True, "Resume All": True}
    assert available_queue_actions([make_item("done.bin", DownloadStatus.COMPLETED)]) == {
        "Pause All": False,
        "Resume All": False,
    }


def test_completion_time_is_formatted_in_local_timezone():
    timestamp = "2026-10-26T18:04:05+00:00"
    local_time = datetime.fromisoformat(timestamp).astimezone()
    expected_hour = local_time.strftime("%I").lstrip("0") or "12"
    expected_clock = f"{expected_hour}:{local_time:%M %p}"
    display, tooltip = format_completion_time(timestamp)

    assert display.startswith("Downloaded ")
    assert expected_clock in display
    assert tooltip.startswith("Completed ")
    assert f"{expected_hour}:{local_time:%M:%S %p}" in tooltip
    assert format_completion_time("") is None
    assert format_completion_time("not-a-timestamp") is None
