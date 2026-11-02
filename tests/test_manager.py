from __future__ import annotations

import time
from pathlib import Path

import pytest

from download_manager.app import normalize_max_concurrent
from download_manager.database import DownloadDatabase
from download_manager.manager import DownloadManager
from download_manager.models import DownloadItem, DownloadStatus
from download_manager.utils import partial_size

from conftest import PAYLOAD, SECOND_PAYLOAD, SLOW_PAYLOAD


def wait_until(application, predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    application.processEvents()
    if not predicate():
        raise AssertionError("Timed out waiting for download state")


def wait_status(application, manager, item_id, status):
    try:
        wait_until(application, lambda: manager.get(item_id).status == status)
    except AssertionError:
        item = manager.get(item_id)
        raise AssertionError(
            f"Expected {status.value}, got {item.status.value}; "
            f"bytes={item.downloaded_bytes}/{item.total_bytes}; error={item.error}"
        ) from None
    if status in {
        DownloadStatus.PAUSED,
        DownloadStatus.CANCELLED,
        DownloadStatus.COMPLETED,
        DownloadStatus.FAILED,
    }:
        wait_until(application, lambda: not manager.has_active_workers())


@pytest.fixture
def manager(tmp_path: Path, application):
    instance = DownloadManager(DownloadDatabase(tmp_path / "history.db"), max_concurrent=1)
    instance.download_folder = tmp_path / "downloads"
    instance.download_folder.mkdir()
    yield instance
    instance.shutdown()
    wait_until(application, lambda: not instance.has_active_workers(), timeout=5)
    application.processEvents()


def add(manager, http_server, route="/payload.bin", name="payload.bin"):
    return manager.add_download(http_server.base_url + route, str(manager.download_folder), name)


def test_state_machine_rejects_invalid_transitions(tmp_path: Path):
    database = DownloadDatabase(tmp_path / "state.db")
    manager = DownloadManager(database, max_concurrent=1)
    item = DownloadItem(
        id="state-1",
        url="https://example.com/file.bin",
        destination=str(tmp_path / "file.bin"),
        temp_path=str(tmp_path / "file.bin.part"),
        status=DownloadStatus.QUEUED,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )
    manager._items[item.id] = item
    with pytest.raises(ValueError, match="Invalid status transition"):
        manager._set_status(item, DownloadStatus.COMPLETED)
    assert normalize_max_concurrent("0", 3) == 1
    assert normalize_max_concurrent("10", 3) == 8
    assert normalize_max_concurrent("abc", 3) == 3


@pytest.mark.parametrize(
    ("route", "expected"),
    (
        pytest.param("/payload.bin", PAYLOAD, id="payload"),
        pytest.param("/redirect.bin", PAYLOAD, id="redirect"),
        pytest.param("/unknown.bin", PAYLOAD, id="unknown-length"),
        pytest.param("/empty.bin", b"", id="empty"),
    ),
)
def test_complete_protocol_variants(manager, http_server, application, route, expected):
    item_id = add(manager, http_server, route)
    manager.start()
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    item = manager.get(item_id)
    assert Path(item.destination).read_bytes() == expected
    assert not Path(item.temp_path).exists()
    assert item.total_bytes == len(expected)
    assert item.downloaded_bytes == len(expected)
    assert item.speed == 0


def test_pause_resume_uses_http_range(manager, http_server, application):
    item_id = add(manager, http_server, "/slow.bin", "slow.bin")
    manager.start()
    wait_until(application, lambda: manager.get(item_id).downloaded_bytes >= 131072)
    wait_until(application, lambda: manager.get(item_id).speed > 0)
    manager.pause(item_id)
    wait_status(application, manager, item_id, DownloadStatus.PAUSED)
    paused_size = partial_size(manager.get(item_id).temp_path)
    assert 0 < paused_size < len(SLOW_PAYLOAD)
    assert manager.get(item_id).downloaded_bytes == paused_size
    manager.resume(item_id)
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    item = manager.get(item_id)
    assert Path(item.destination).read_bytes() == SLOW_PAYLOAD
    assert any(route == "/slow.bin" and offset == paused_size for route, offset in http_server.state.ranges)


def test_pause_all_and_resume_all(manager, http_server, application):
    manager.set_max_concurrent(2)
    first = add(manager, http_server, "/slow.bin", "all-one.bin")
    second = add(manager, http_server, "/slow-two.bin", "all-two.bin")
    manager.start()
    wait_until(
        application,
        lambda: manager.get(first).downloaded_bytes > 0 and manager.get(second).downloaded_bytes > 0,
    )

    manager.pause_all()
    wait_until(
        application,
        lambda: manager.get(first).status == DownloadStatus.PAUSED
        and manager.get(second).status == DownloadStatus.PAUSED,
    )
    manager.resume_all()
    wait_status(application, manager, first, DownloadStatus.COMPLETED)
    wait_status(application, manager, second, DownloadStatus.COMPLETED)


def test_paused_download_resumes_after_manager_restart(manager, http_server, application):
    item_id = add(manager, http_server, "/slow.bin", "restart.bin")
    manager.start()
    wait_until(application, lambda: manager.get(item_id).downloaded_bytes >= 65536)
    manager.pause(item_id)
    wait_status(application, manager, item_id, DownloadStatus.PAUSED)
    paused_size = partial_size(manager.get(item_id).temp_path)
    restarted = DownloadManager(manager.database)
    try:
        assert restarted.get(item_id).status == DownloadStatus.PAUSED
        restarted.resume(item_id)
        wait_status(application, restarted, item_id, DownloadStatus.COMPLETED)
        assert Path(restarted.get(item_id).destination).read_bytes() == SLOW_PAYLOAD
        assert any(offset == paused_size for _, offset in http_server.state.ranges)
    finally:
        restarted.shutdown()
        wait_until(application, lambda: not restarted.has_active_workers(), timeout=5)


def test_resume_restarts_safely_when_server_ignores_range(manager, http_server, application):
    item_id = add(manager, http_server, "/no-range.bin", "no-range.bin")
    manager.start()
    wait_until(application, lambda: manager.get(item_id).downloaded_bytes >= 131072)
    manager.pause(item_id)
    wait_status(application, manager, item_id, DownloadStatus.PAUSED)
    manager.resume(item_id)
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    item = manager.get(item_id)
    assert Path(item.destination).read_bytes() == SLOW_PAYLOAD
    assert item.downloaded_bytes == len(SLOW_PAYLOAD)


def test_cancel_preserves_partial_and_retry_completes(manager, http_server, application):
    item_id = add(manager, http_server, "/slow.bin", "cancel.bin")
    manager.start()
    wait_until(application, lambda: manager.get(item_id).downloaded_bytes >= 65536)
    manager.cancel(item_id)
    wait_status(application, manager, item_id, DownloadStatus.CANCELLED)
    item = manager.get(item_id)
    assert Path(item.temp_path).exists()
    assert partial_size(item.temp_path) > 0
    manager.retry(item_id)
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    assert Path(manager.get(item_id).destination).read_bytes() == SLOW_PAYLOAD


def test_http_error_can_be_retried(manager, http_server, application):
    item_id = add(manager, http_server, "/flaky.bin", "flaky.bin")
    manager.start()
    wait_status(application, manager, item_id, DownloadStatus.FAILED)
    assert "503" in manager.get(item_id).error
    manager.retry(item_id)
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    assert http_server.state.attempts["/flaky.bin"] == 2
    assert Path(manager.get(item_id).destination).read_bytes() == PAYLOAD


def test_queue_preserves_order_with_one_slot(manager, http_server, application):
    events = []
    manager.item_updated.connect(lambda item: events.append((item.id, item.status)))
    first = add(manager, http_server, "/slow.bin", "first.bin")
    second = add(manager, http_server, "/slow-two.bin", "second.bin")
    manager.start()
    wait_until(application, lambda: manager.get(first).status == DownloadStatus.DOWNLOADING)
    assert manager.get(second).status == DownloadStatus.QUEUED
    wait_status(application, manager, first, DownloadStatus.COMPLETED)
    wait_status(application, manager, second, DownloadStatus.COMPLETED)
    first_complete = events.index((first, DownloadStatus.COMPLETED))
    second_start = events.index((second, DownloadStatus.DOWNLOADING))
    assert first_complete < second_start
    assert Path(manager.get(second).destination).read_bytes() == SECOND_PAYLOAD


def test_parallel_downloads_use_multiple_qthreads(manager, http_server, application):
    manager.set_max_concurrent(2)
    active_counts = []
    manager.active_count_changed.connect(active_counts.append)
    first = add(manager, http_server, "/slow.bin", "parallel-one.bin")
    second = add(manager, http_server, "/slow-two.bin", "parallel-two.bin")
    manager.start()
    wait_until(
        application,
        lambda: manager.get(first).status == DownloadStatus.DOWNLOADING
        and manager.get(second).status == DownloadStatus.DOWNLOADING,
    )
    assert 2 in active_counts
    wait_status(application, manager, first, DownloadStatus.COMPLETED)
    wait_status(application, manager, second, DownloadStatus.COMPLETED)


def test_download_collision_never_overwrites_existing_file(manager, http_server, application):
    existing = manager.download_folder / "payload.bin"
    existing.write_bytes(b"valuable user data")
    item_id = add(manager, http_server)
    item = manager.get(item_id)
    assert item.destination != str(existing)
    manager.start()
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    assert existing.read_bytes() == b"valuable user data"
    assert Path(manager.get(item_id).destination).read_bytes() == PAYLOAD


def test_extensionless_image_url_gets_extension_from_response_content_type(
    manager, http_server, application
):
    item_id = manager.add_download(
        f"{http_server.base_url}/images?q=thumbnail",
        str(manager.download_folder),
    )
    assert manager.get(item_id).filename == "images"

    manager.start()
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)

    item = manager.get(item_id)
    assert item.filename == "images.jpg"
    assert Path(item.destination).read_bytes() == PAYLOAD


def test_history_and_interrupted_state_recover(manager, http_server, application):
    item_id = add(manager, http_server)
    manager.start()
    wait_status(application, manager, item_id, DownloadStatus.COMPLETED)
    recovered = DownloadManager(manager.database)
    item = recovered.get(item_id)
    assert item.status == DownloadStatus.COMPLETED
    item.status = DownloadStatus.DOWNLOADING
    manager.database.save(item)
    restarted = DownloadManager(manager.database)
    assert restarted.get(item_id).status == DownloadStatus.PAUSED
