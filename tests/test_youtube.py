from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from download_manager.database import DownloadDatabase
from download_manager.manager import DownloadManager
from download_manager.models import DownloadStatus
from download_manager.ui import youtube_dialog as youtube_dialog_module
from download_manager.ui.youtube_dialog import YouTubeDownloadDialog
from download_manager.utils import finalize_download_from
from download_manager.youtube import (
    audio_choices,
    duration_text,
    ensure_staging_directory,
    format_choices,
    is_bilibili_url,
    is_supported_media_url,
    is_youtube_url,
    is_youtube_playlist_url,
    remove_staging,
    mp3_estimated_size,
)
from download_manager.youtube_worker import MetadataWorker, YouTubeDownloadWorker, _TransferInterrupted
from download_manager.youtube import MAX_MP3_BITRATE


def sample_info() -> dict:
    return {
        "formats": [
            {
                "format_id": "22",
                "height": 720,
                "width": 1280,
                "ext": "mp4",
                "vcodec": "avc1.64001f",
                "acodec": "mp4a.40.2",
                "filesize": 12_000_000,
                "tbr": 1600,
            },
            {
                "format_id": "247",
                "height": 720,
                "width": 1280,
                "ext": "webm",
                "vcodec": "vp9",
                "acodec": "none",
                "filesize_approx": 20_000_000,
                "tbr": 2400,
            },
            {
                "format_id": "248",
                "height": 720,
                "width": 1280,
                "ext": "webm",
                "vcodec": "vp9",
                "acodec": "none",
                "filesize_approx": 19_000_000,
                "tbr": 2200,
            },
            {
                "format_id": "23",
                "height": 720,
                "width": 1280,
                "ext": "mp4",
                "vcodec": "avc1.64001f",
                "acodec": "none",
                "filesize_approx": 11_000_000,
                "tbr": 1500,
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "filesize": 2_000_000,
                "abr": 128,
            },
        ]
    }


def test_youtube_url_detection_accepts_supported_hosts_only():
    assert is_youtube_url("https://www.youtube.com/watch?v=video")
    assert is_youtube_url("https://youtu.be/video")
    assert not is_youtube_url("https://youtube.com.attacker.example/watch?v=video")
    assert not is_youtube_url("https://example.com/watch?v=video")
    assert is_youtube_playlist_url("https://www.youtube.com/playlist?list=playlist")
    assert not is_youtube_playlist_url("https://www.youtube.com/watch?v=video&list=playlist")


def test_bilibili_video_urls_are_supported_without_accepting_lookalikes():
    url = "https://www.bilibili.com/video/BV1234567890"
    assert is_bilibili_url(url)
    assert is_supported_media_url(url)
    assert is_bilibili_url("https://m.bilibili.com/video/BV1234567890")
    assert not is_bilibili_url("https://bilibili.com.attacker.example/video/BV123")
    assert not is_bilibili_url("https://example.com/video/BV123")


def test_format_choices_use_real_metadata_and_unknown_sizes():
    choices = format_choices(sample_info())
    muxed = next(choice for choice in choices if choice["format_id"] == "22")
    assert len([choice for choice in choices if choice["resolution"] == "720p"]) == 1

    assert muxed["label"] == "720p · 11.4 MB"
    assert "best" not in muxed["label"].lower()
    assert muxed["size"] == 12_000_000
    assert muxed["extension"] == "mp4"
    assert all(choice["extension"] == "mp4" for choice in choices)
    assert all("webm" not in choice["label"].lower() for choice in choices)
    assert all("mp4" not in choice["label"].lower() for choice in choices)
    assert not any(choice["format_id"].startswith(("247+", "248+")) for choice in choices)

    unknown = format_choices({"formats": [{"format_id": "x", "vcodec": "av1", "ext": "webm"}]})
    assert unknown == []


def test_missing_sizes_are_estimated_from_reported_duration_and_bitrate():
    info = {
        "duration": 120,
        "formats": [
            {
                "format_id": "video",
                "height": 480,
                "ext": "mp4",
                "vcodec": "avc1",
                "acodec": "none",
                "tbr": 1000,
            },
            {
                "format_id": "audio",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a",
                "abr": 128,
            },
        ],
    }

    video = format_choices(info)[0]
    audio = audio_choices(info)[0]

    assert video["size"] == 16_920_000
    assert video["estimated"] is True
    assert video["label"] == "480p · ~16.1 MB"
    assert audio["size"] == 1_920_000
    assert audio["estimated"] is True
    assert mp3_estimated_size(120, 192) == 2_880_000


def test_audio_choices_include_codec_size_and_extension():
    choice = audio_choices(sample_info())[0]

    assert choice["format_id"] == "140"
    assert choice["extension"] == "m4a"
    assert choice["size"] == 2_000_000
    assert "Audio: mp4a.40.2" in choice["codecs"]


def test_duration_formatting():
    assert duration_text(65) == "1:05"
    assert duration_text(3661) == "1:01:01"
    assert duration_text(None) == "Unknown duration"


def test_youtube_download_details_persist_and_collision_is_reserved(tmp_path: Path):
    database = DownloadDatabase(tmp_path / "history.db")
    folder = tmp_path / "downloads"
    manager = DownloadManager(database)
    item_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(folder),
        title="Original title",
        output_name="My saved copy",
        channel="Example channel",
        duration=90,
        format_selector="247+bestaudio",
        filename_extension="mkv",
        estimated_size=22_000_000,
    )
    item = manager.get(item_id)

    assert item is not None
    assert item.status == DownloadStatus.QUEUED
    assert Path(item.destination).name == "My saved copy.mkv"
    assert Path(item.destination).with_name("My saved copy.mkv.part").exists()
    assert item.source_type == "youtube"
    assert item.media_format == "247+bestaudio"
    assert item.total_bytes == 22_000_000
    duplicate_id = manager.add_youtube_download(
        "https://youtu.be/another",
        str(folder),
        title="Original title",
        output_name="My saved copy",
        channel="Example channel",
        duration=90,
        format_selector="247+bestaudio",
        filename_extension="mkv",
    )
    duplicate = manager.get(duplicate_id)
    assert duplicate is not None
    assert Path(duplicate.destination).name == "My saved copy (1).mkv"

    restored = DownloadManager(database).get(item_id)
    assert restored is not None
    assert (
        restored.media_title,
        restored.media_channel,
        restored.media_duration,
        restored.audio_bitrate,
    ) == ("Original title", "Example channel", 90, 320)
    assert Path(restored.temp_path).name == "media"
    assert Path(restored.temp_path).parent.name == f".litedm-{item_id}"


def test_bilibili_download_uses_existing_ytdlp_queue(tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "bilibili-history.db"))
    item_id = manager.add_youtube_download(
        "https://www.bilibili.com/video/BV1234567890",
        str(tmp_path / "downloads"),
        title="Bilibili sample",
        channel="Uploader",
        duration=90,
        format_selector="80+bestaudio",
        filename_extension="mp4",
        estimated_size=20_000_000,
        browser_origin=True,
    )

    item = manager.get(item_id)
    assert item is not None
    assert item.url == "https://www.bilibili.com/video/BV1234567890"
    assert item.media_format == "80+bestaudio"
    assert item.browser_origin is True


def test_database_migrates_existing_http_history(tmp_path: Path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE downloads (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, destination TEXT NOT NULL,
                temp_path TEXT NOT NULL, status TEXT NOT NULL,
                total_bytes INTEGER NOT NULL DEFAULT -1,
                downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            INSERT INTO downloads (id, url, destination, temp_path, status, created_at, updated_at)
            VALUES ('legacy', 'https://example.com/file', '/tmp/file', '/tmp/file.part',
                    'paused', '2024-01-01', '2024-01-01')
            """
        )

    item = DownloadDatabase(path).load_all()[0]

    assert item.id == "legacy"
    assert item.source_type == "http"
    assert item.media_format == ""
    assert item.audio_only is False


def test_private_media_staging_and_safe_cross_directory_finalization(tmp_path: Path):
    item_id = "a" * 32
    prefix = str(tmp_path / f".litedm-{item_id}" / "media")
    ensure_staging_directory(prefix)
    staging_directory = Path(prefix).parent
    assert staging_directory.stat().st_mode & 0o777 == 0o700
    source = staging_directory / "media.mp4"
    source.write_bytes(b"youtube-media")
    requested = tmp_path / "video.mp4"
    requested.write_bytes(b"existing")

    final_path = finalize_download_from(source, requested)

    assert final_path.name == "video (1).mp4"
    assert final_path.read_bytes() == b"youtube-media"
    assert requested.read_bytes() == b"existing"
    assert final_path.stat().st_mode & 0o777 == 0o600
    remove_staging(prefix)
    assert not staging_directory.exists()


def test_youtube_worker_builds_options_from_selected_transfer(tmp_path: Path):
    item = DownloadManager(DownloadDatabase(tmp_path / "worker.db")).add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="247+bestaudio",
        filename_extension="mkv",
    )
    manager = DownloadManager(DownloadDatabase(tmp_path / "worker.db"))
    transfer = manager.get(item)
    assert transfer is not None
    worker = YouTubeDownloadWorker(transfer)
    options = worker._options()

    assert options["format"] == "247+bestaudio"
    assert options["continuedl"] is True
    assert options["noplaylist"] is True
    assert options["outtmpl"] == f"{transfer.temp_path}.%(ext)s"
    assert options["merge_output_format"] == "mkv"
    remove_staging(transfer.temp_path)


def test_youtube_worker_merges_selected_container(tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "container.db"))
    transfer_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="247+bestaudio",
        filename_extension="webm",
    )
    transfer = manager.get(transfer_id)
    assert transfer is not None

    assert YouTubeDownloadWorker(transfer)._options()["merge_output_format"] == "webm"


def test_mp3_worker_uses_maximum_quality_without_user_bitrate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("download_manager.youtube_worker.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    manager = DownloadManager(DownloadDatabase(tmp_path / "mp3.db"))
    transfer_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="mp3",
        filename_extension="mp3",
        audio_only=True,
    )
    transfer = manager.get(transfer_id)
    assert transfer is not None
    worker = YouTubeDownloadWorker(transfer)
    options = worker._options()

    assert options["postprocessors"][0]["preferredquality"] == str(MAX_MP3_BITRATE)


def test_youtube_worker_pause_hook_preserves_interrupt_state(tmp_path: Path):
    item = DownloadManager(DownloadDatabase(tmp_path / "pause.db")).add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="140",
        filename_extension="m4a",
        audio_only=True,
    )
    transfer = DownloadManager(DownloadDatabase(tmp_path / "pause.db")).get(item)
    assert transfer is not None
    worker = YouTubeDownloadWorker(transfer)
    worker.pause()

    with pytest.raises(_TransferInterrupted):
        worker._control_hook({"status": "downloading", "downloaded_bytes": 10})

    assert worker._interrupted == "paused"


def test_youtube_worker_accepts_ytdlp_progress_hook_payload(tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "progress.db"))
    transfer_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="140",
        filename_extension="m4a",
        estimated_size=2048,
        audio_only=True,
    )
    transfer = manager.get(transfer_id)
    assert transfer is not None
    worker = YouTubeDownloadWorker(transfer)
    progress = []
    worker.progress.connect(lambda *values: progress.append(values))

    worker._control_hook(
        {
            "status": "downloading",
            "downloaded_bytes": 1024,
            "total_bytes": 2048,
            "speed": 512.0,
            "info_dict": {"requested_formats": [{"filesize": 2048}]},
        }
    )

    assert worker._downloaded == 1024
    assert worker._total == 2048
    assert worker._speed == 512.0
    assert progress == [(transfer_id, 1024, 2048, 512.0)]


def test_youtube_worker_preserves_zero_downloaded_bytes(tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "zero-progress.db"))
    transfer_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="140",
        filename_extension="m4a",
        estimated_size=2048,
        audio_only=True,
    )
    transfer = manager.get(transfer_id)
    assert transfer is not None
    worker = YouTubeDownloadWorker(transfer)
    progress = []
    worker.progress.connect(lambda *values: progress.append(values))

    worker._control_hook(
        {
            "status": "downloading",
            "downloaded_bytes": 0,
            "total_bytes": 2048,
            "speed": 0,
        }
    )

    assert worker._downloaded == 0
    assert worker._total == 2048
    assert progress == [(transfer_id, 0, 2048, 0.0)]


def test_youtube_worker_uses_per_stream_totals_for_merged_download(tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "inaccurate-progress.db"))
    transfer_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="bestvideo+bestaudio",
        filename_extension="mp4",
        estimated_size=8_900_000,
    )
    transfer = manager.get(transfer_id)
    assert transfer is not None
    ensure_staging_directory(transfer.temp_path)
    staged_file = Path(transfer.temp_path).parent / "media.mp4.part"
    staged_file.touch()
    with staged_file.open("r+b") as output:
        output.truncate(400_000_000)
    worker = YouTubeDownloadWorker(transfer)
    progress = []
    worker.progress.connect(lambda *values: progress.append(values))

    worker._control_hook(
        {
            "status": "downloading",
            "downloaded_bytes": 121_700_000,
            "total_bytes": 354_200_000,
            "speed": 10_000_000,
            "info_dict": {
                "format_id": "video",
                "requested_formats": [
                    {"format_id": "video", "filesize": 8_900_000},
                    {"format_id": "audio", "filesize": 2_000_000},
                ],
            },
        }
    )

    assert worker._downloaded == 121_700_000
    assert worker._total == 356_200_000
    assert progress == [(transfer_id, 121_700_000, 356_200_000, 10_000_000)]


def test_youtube_worker_hides_a_total_smaller_than_downloaded_bytes(tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "unknown-total.db"))
    transfer_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="A title",
        channel="A channel",
        duration=12,
        format_selector="bestvideo+bestaudio",
        filename_extension="mp4",
        estimated_size=8_900_000,
    )
    transfer = manager.get(transfer_id)
    assert transfer is not None
    worker = YouTubeDownloadWorker(transfer)
    progress = []
    worker.progress.connect(lambda *values: progress.append(values))

    worker._control_hook(
        {
            "status": "downloading",
            "downloaded_bytes": 144_300_000,
            "total_bytes": 8_900_000,
            "speed": 10_000_000,
            "info_dict": {"format_id": "video"},
        }
    )

    assert worker._downloaded == 144_300_000
    assert worker._total == -1
    assert progress == [(transfer_id, 144_300_000, -1, 10_000_000)]


def test_youtube_dialog_loads_metadata_and_exposes_format_options(
    application, monkeypatch, tmp_path: Path
):
    class InlineMetadataWorker(MetadataWorker):
        def start(self) -> None:
            info = {
                **sample_info(),
                "title": "Video title",
                "channel": "Example channel",
                "duration": 65,
                "thumbnail_data": b"",
            }
            self.loaded.emit(info)
            self.finished.emit()

    monkeypatch.setattr(youtube_dialog_module, "MetadataWorker", InlineMetadataWorker)
    dialog = YouTubeDownloadDialog("https://youtu.be/example", str(tmp_path))

    assert dialog.title_label.text() == "Video title"
    assert dialog.channel_label.text() == "Example channel  ·  1:05"
    assert dialog.start_button.isEnabled()
    assert dialog.format_combo.count() == len(format_choices(sample_info())) + 2
    assert dialog.format_combo.itemText(1) == "720p · 11.4 MB"
    assert "Best quality available · ~11.4 MB" in [
        dialog.format_combo.itemText(index)
        for index in range(dialog.format_combo.count())
    ]
    assert any(
        dialog.format_combo.itemText(index).startswith("MP3 · ~")
        for index in range(dialog.format_combo.count())
    )
    assert any(
        dialog.format_combo.itemData(index).get("kind") == "mp3"
        for index in range(dialog.format_combo.count())
    )

    dialog.mode_combo.setCurrentText("Audio (original)")
    assert dialog.format_combo.count() == 2
    mp3_index = next(
        index for index in range(dialog.format_combo.count())
        if dialog.format_combo.itemData(index).get("kind") == "mp3"
    )
    dialog.format_combo.setCurrentIndex(mp3_index)
    values = dialog.values()
    assert values["format_selector"] == "mp3"
    assert values["extension"] == "mp3"
    assert values["audio_bitrate"] == 320
    assert dialog.size_label.text() == "Estimated size: ~2.5 MB"
    assert "bitrate" not in dialog.codec_label.text().lower()
    assert not hasattr(dialog, "bitrate_spin")
    dialog.close()


def test_youtube_dialog_shows_loading_then_opens_formats(application, monkeypatch, tmp_path: Path):
    class WaitingMetadataWorker(MetadataWorker):
        def start(self) -> None:
            pass

    monkeypatch.setattr(youtube_dialog_module, "MetadataWorker", WaitingMetadataWorker)
    dialog = YouTubeDownloadDialog("https://youtu.be/example", str(tmp_path))
    worker = dialog._metadata_worker

    assert worker is not None
    assert not dialog.formats_loading.isHidden()
    assert dialog.formats_loading.minimum() == 0
    assert dialog.formats_loading.maximum() == 0
    assert dialog.formats_loading.width() >= 70
    assert "Fetching video details and formats" in dialog.status_label.text()
    assert "font-weight: 600" in dialog.status_label.styleSheet()
    assert dialog.format_combo.isEnabled() is False
    assert dialog.format_combo.currentText() == "Loading formats…"

    dialog.show()
    dialog._metadata_loaded(
        {
            **sample_info(),
            "title": "Video title",
            "channel": "Example channel",
            "duration": 65,
            "thumbnail_data": b"",
        }
    )
    application.processEvents()

    assert dialog.formats_loading.isHidden()
    assert dialog.format_combo.isEnabled()
    assert dialog.format_combo.currentText().startswith("Best quality available")
    assert dialog.format_combo.view().isVisible()
    dialog._live_metadata_workers.discard(worker)
    dialog.close()


def test_youtube_dialog_fetches_pasted_url_automatically_without_button(
    application, monkeypatch, tmp_path: Path
):
    fetched_urls = []

    class InlineMetadataWorker(MetadataWorker):
        def start(self) -> None:
            fetched_urls.append(self.url)
            self.loaded.emit(
                {
                    **sample_info(),
                    "title": "Video title",
                    "channel": "Example channel",
                    "duration": 65,
                    "thumbnail_data": b"",
                }
            )
            self.finished.emit()

    monkeypatch.setattr(youtube_dialog_module, "MetadataWorker", InlineMetadataWorker)
    dialog = YouTubeDownloadDialog("https://youtu.be/first", str(tmp_path))

    assert not hasattr(dialog, "fetch_button")
    assert fetched_urls == ["https://youtu.be/first"]

    dialog.url_edit.setText("https://youtu.be/second")
    assert dialog._metadata_debounce.isActive()
    dialog._metadata_debounce.timeout.emit()

    assert fetched_urls == ["https://youtu.be/first", "https://youtu.be/second"]
    assert dialog.title_label.text() == "Video title"
    dialog.close()
