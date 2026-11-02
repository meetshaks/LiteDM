from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .models import DownloadItem, DownloadStatus


class DownloadDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    temp_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL DEFAULT -1,
                    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(downloads)").fetchall()
            }
            media_columns = {
                "source_type": "TEXT NOT NULL DEFAULT 'http'",
                "browser_origin": "INTEGER NOT NULL DEFAULT 0",
                "media_format": "TEXT NOT NULL DEFAULT ''",
                "audio_only": "INTEGER NOT NULL DEFAULT 0",
                "audio_bitrate": "INTEGER NOT NULL DEFAULT 320",
                "media_title": "TEXT NOT NULL DEFAULT ''",
                "media_channel": "TEXT NOT NULL DEFAULT ''",
                "media_duration": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in media_columns.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE downloads ADD COLUMN {name} {declaration}")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at)")
            connection.execute("PRAGMA user_version=3")
        os.chmod(self.path, 0o600)

    def load_all(self) -> list[DownloadItem]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM downloads ORDER BY created_at, rowid").fetchall()
        return [
            DownloadItem(
                id=row["id"],
                url=row["url"],
                destination=row["destination"],
                temp_path=row["temp_path"],
                status=DownloadStatus(row["status"]),
                total_bytes=row["total_bytes"],
                downloaded_bytes=row["downloaded_bytes"],
                error=row["error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                completed_at=row["completed_at"],
                source_type=row["source_type"],
                browser_origin=bool(row["browser_origin"]),
                media_format=row["media_format"],
                audio_only=bool(row["audio_only"]),
                audio_bitrate=row["audio_bitrate"],
                media_title=row["media_title"],
                media_channel=row["media_channel"],
                media_duration=row["media_duration"],
            )
            for row in rows
        ]

    def save(self, item: DownloadItem) -> None:
        values = (
            item.id,
            item.url,
            item.destination,
            item.temp_path,
            item.status.value,
            item.total_bytes,
            item.downloaded_bytes,
            item.error,
            item.created_at,
            item.updated_at,
            item.completed_at,
            item.source_type,
            int(item.browser_origin),
            item.media_format,
            int(item.audio_only),
            item.audio_bitrate,
            item.media_title,
            item.media_channel,
            item.media_duration,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO downloads (
                    id, url, destination, temp_path, status, total_bytes,
                    downloaded_bytes, error, created_at, updated_at, completed_at,
                    source_type, browser_origin, media_format, audio_only, audio_bitrate,
                    media_title, media_channel, media_duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    url=excluded.url,
                    destination=excluded.destination,
                    temp_path=excluded.temp_path,
                    status=excluded.status,
                    total_bytes=excluded.total_bytes,
                    downloaded_bytes=excluded.downloaded_bytes,
                    error=excluded.error,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at,
                    source_type=excluded.source_type,
                    browser_origin=excluded.browser_origin,
                    media_format=excluded.media_format,
                    audio_only=excluded.audio_only,
                    audio_bitrate=excluded.audio_bitrate,
                    media_title=excluded.media_title,
                    media_channel=excluded.media_channel,
                    media_duration=excluded.media_duration
                """,
                values,
            )

    def delete(self, item_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM downloads WHERE id = ?", (item_id,))
