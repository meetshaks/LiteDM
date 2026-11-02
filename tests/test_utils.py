from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from download_manager.models import DownloadItem, DownloadStatus, utc_now
from download_manager.database import DownloadDatabase
from download_manager.utils import (
    MAX_FILENAME_BYTES,
    allocate_destination,
    app_icon_path,
    finalize_download,
    filename_from_url,
    sanitize_filename,
    validate_url,
)


def test_application_icon_uses_high_resolution_icon_five():
    icon = app_icon_path()
    assert icon.name == "5.png"
    assert icon.is_file()
    with icon.open("rb") as image:
        image.seek(16)
        assert struct.unpack(">II", image.read(8)) == (729, 729)


def test_safe_filenames_and_urls():
    assert sanitize_filename("../../evil.sh") == "evil.sh"
    assert sanitize_filename("%2F..%2F") == "download"
    assert sanitize_filename("..") == "download"
    assert sanitize_filename("name\x00.txt") == "name_.txt"
    assert filename_from_url("https://example.com/files/My%20File.iso?x=1") == "My File.iso"
    long_name = sanitize_filename("é" * 300 + ".bin")
    assert len(long_name.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert long_name.endswith(".bin")
    assert validate_url(" https://example.com/file ") == "https://example.com/file"
    for value in ("file:///tmp/a", "ftp://example.com/a", "example.com/a", "http://"):
        with pytest.raises(ValueError):
            validate_url(value)


def test_existing_files_and_partials_are_never_reused(tmp_path: Path):
    (tmp_path / "payload.bin").write_bytes(b"original")
    (tmp_path / "payload (1).bin.part").write_bytes(b"user partial")
    destination, partial = allocate_destination(tmp_path, "payload.bin")
    assert destination.name == "payload (2).bin"
    assert partial.name == "payload (2).bin.part"
    assert (tmp_path / "payload.bin").read_bytes() == b"original"
    assert (tmp_path / "payload (1).bin.part").read_bytes() == b"user partial"
    assert os.stat(partial).st_mode & 0o777 == 0o600


def test_finalize_collision_uses_numbered_file(tmp_path: Path):
    destination = tmp_path / "report.txt"
    partial = tmp_path / "report.txt.part"
    destination.write_bytes(b"keep me")
    partial.write_bytes(b"new download")
    final = finalize_download(partial, destination)
    assert final.name == "report (1).txt"
    assert destination.read_bytes() == b"keep me"
    assert final.read_bytes() == b"new download"
    assert not partial.exists()


def test_sqlite_history_round_trip(tmp_path: Path):
    database = DownloadDatabase(tmp_path / "history.db")
    now = utc_now()
    item = DownloadItem(
        id="abc123",
        url="https://example.com/file.bin",
        destination=str(tmp_path / "file.bin"),
        temp_path=str(tmp_path / "file.bin.part"),
        status=DownloadStatus.PAUSED,
        downloaded_bytes=42,
        total_bytes=100,
        created_at=now,
        updated_at=now,
    )
    database.save(item)
    loaded = database.load_all()
    assert len(loaded) == 1
    assert loaded[0].id == item.id
    assert loaded[0].status == DownloadStatus.PAUSED
    assert loaded[0].downloaded_bytes == 42
    assert os.stat(tmp_path / "history.db").st_mode & 0o777 == 0o600
