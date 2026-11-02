from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..utils import ensure_directory, sanitize_filename, validate_url
from ..youtube import (
    audio_choices,
    duration_text,
    ffmpeg_available,
    format_choices,
    format_size,
    is_youtube_url,
    MAX_MP3_BITRATE,
    mp3_estimated_size,
)
from ..youtube_worker import MetadataWorker
from .theme import ACCENT, ACCENT_DARK, BG_CARD, BG_SIDEBAR, BORDER, TEXT_MUTED, TEXT_PRIMARY


class YouTubeDownloadDialog(QDialog):
    _live_metadata_workers: set[MetadataWorker] = set()

    def __init__(
        self,
        url: str,
        folder: str,
        parent=None,
        filename: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Add YouTube download")
        self.setMinimumWidth(600)
        self.setStyleSheet(f"QDialog {{ background: {BG_SIDEBAR}; color: {TEXT_PRIMARY}; }}")
        self._info: dict | None = None
        self._video_formats: list[dict] = []
        self._audio_formats: list[dict] = []
        self._metadata_worker: MetadataWorker | None = None
        self._requested_url = ""

        self.url_edit = QLineEdit(url)
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.textChanged.connect(self._invalidate_metadata)
        self._metadata_debounce = QTimer(self)
        self._metadata_debounce.setSingleShot(True)
        self._metadata_debounce.setInterval(500)
        self._metadata_debounce.timeout.connect(self._fetch_metadata)

        self.thumbnail = QLabel("YouTube")
        self.thumbnail.setFixedSize(160, 90)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setStyleSheet(f"background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 6px;")
        self.title_label = QLabel("Paste a video URL to load its details")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11pt; font-weight: 650;")
        self.channel_label = QLabel("")
        self.channel_label.setStyleSheet(f"color: {TEXT_MUTED};")
        preview = QWidget()
        preview_layout = QHBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(12)
        preview_layout.addWidget(self.thumbnail)
        title_column = QVBoxLayout()
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.channel_label)
        title_column.addStretch(1)
        preview_layout.addLayout(title_column, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Video", "Audio (original)"])
        self.mode_combo.currentIndexChanged.connect(self._update_format_choices)
        self.format_combo = QComboBox()
        self.format_combo.setEnabled(False)
        self.format_combo.currentIndexChanged.connect(self._update_format_details)
        self.format_combo.currentIndexChanged.connect(self._update_start_availability)
        self.formats_loading = QProgressBar()
        self.formats_loading.setAccessibleName("Loading available formats")
        self.formats_loading.setRange(0, 0)
        self.formats_loading.setFixedSize(76, 14)
        self.formats_loading.setTextVisible(False)
        self.formats_loading.setStyleSheet(
            f"QProgressBar {{ background: {BG_CARD}; border: 1px solid {BORDER};"
            " border-radius: 6px; }"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}"
        )
        self.formats_loading.hide()
        formats_row = QWidget()
        formats_layout = QHBoxLayout(formats_row)
        formats_layout.setContentsMargins(0, 0, 0, 0)
        formats_layout.setSpacing(8)
        formats_layout.addWidget(self.format_combo, 1)
        formats_layout.addWidget(self.formats_loading)
        self.size_label = QLabel("Estimated size: —")
        self.codec_label = QLabel("")
        self.codec_label.setWordWrap(True)
        self.codec_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")
        self.filename_edit = QLineEdit(filename)
        self.filename_edit.setPlaceholderText("Video title")
        self.folder_edit = QLineEdit(folder)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(browse_button)
        self.status_label = QLabel("Video details are fetched in the background.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("YouTube URL", self.url_edit)
        form.addRow("Format category", self.mode_combo)
        form.addRow("Available formats (includes MP3)", formats_row)
        form.addRow("", self.size_label)
        form.addRow("", self.codec_label)
        form.addRow("File name", self.filename_edit)
        form.addRow("Save to folder", folder_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.start_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.start_button.setText("Add to queue")
        self.start_button.setEnabled(False)
        self.start_button.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_DARK}; border: 1px solid {ACCENT};"
            f" border-radius: 6px; color: {TEXT_PRIMARY}; font-weight: 600; padding: 8px 18px; }}"
            f"QPushButton:hover {{ background: {ACCENT}; color: #0b1018; }}"
            "QPushButton:disabled { color: #64748b; border-color: #475569; }"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(preview)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self._set_formats_loading(True)
        self._fetch_metadata()

    def _set_formats_loading(self, loading: bool) -> None:
        self.format_combo.setEnabled(not loading)
        self.formats_loading.setVisible(loading)
        if loading:
            self.status_label.setStyleSheet(
                f"color: {ACCENT}; font-weight: 600; padding: 3px 0;"
            )
            self.status_label.setText("Fetching video details and formats. Please wait…")
        else:
            self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")

    def _invalidate_metadata(self) -> None:
        if self.url_edit.text().strip() != self._requested_url:
            self._metadata_debounce.stop()
            self._info = None
            self._video_formats = []
            self._audio_formats = []
            self._set_formats_loading(False)
            self.format_combo.clear()
            self.format_combo.addItem("Paste a video URL to load formats")
            self.format_combo.setEnabled(False)
            self.start_button.setEnabled(False)
            if self.url_edit.text().strip():
                self.status_label.setText("Loading details automatically when the URL is ready…")
                self._metadata_debounce.start()
            else:
                self.status_label.setText("Paste a YouTube video URL to load its details.")

    def _fetch_metadata(self) -> None:
        self._metadata_debounce.stop()
        if self._metadata_worker and self._metadata_worker.isRunning():
            return
        try:
            self.url_edit.setText(validate_url(self.url_edit.text()))
        except ValueError as error:
            self.status_label.setText(str(error))
            self.start_button.setEnabled(False)
            return
        if not is_youtube_url(self.url_edit.text()):
            self.status_label.setText("Enter a supported YouTube video URL.")
            self.start_button.setEnabled(False)
            return
        self.start_button.setEnabled(False)
        self._set_formats_loading(True)
        self.format_combo.clear()
        self.format_combo.addItem("Loading formats…")
        self._requested_url = self.url_edit.text()
        worker = MetadataWorker(self._requested_url)
        self._metadata_worker = worker
        self._live_metadata_workers.add(worker)
        worker.loaded.connect(self._metadata_loaded)
        worker.failed.connect(self._metadata_failed)
        worker.finished.connect(self._release_metadata_worker)
        worker.start()

    def _release_metadata_worker(self) -> None:
        worker = self.sender()
        if isinstance(worker, MetadataWorker):
            self._live_metadata_workers.discard(worker)
            worker.deleteLater()
        if self.url_edit.text().strip() != self._requested_url:
            self._metadata_debounce.start(0)

    def _metadata_loaded(self, info: dict) -> None:
        if self.url_edit.text().strip() != self._requested_url:
            return
        self._info = info
        self._video_formats = format_choices(info)
        self._audio_formats = audio_choices(info)
        self.title_label.setText(str(info.get("title") or "Untitled video"))
        duration = duration_text(info.get("duration"))
        channel = str(info.get("channel") or info.get("uploader") or "Unknown channel")
        self.channel_label.setText(f"{channel}  ·  {duration}")
        thumb = QPixmap()
        if info.get("thumbnail_data"):
            thumb.loadFromData(info["thumbnail_data"])
        if not thumb.isNull():
            self.thumbnail.setPixmap(
                thumb.scaled(
                    self.thumbnail.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.thumbnail.setText("")
        if not self.filename_edit.text().strip():
            self.filename_edit.setText(sanitize_filename(str(info.get("title") or "youtube-video")))
        self._update_format_choices()
        self._set_formats_loading(False)
        available = bool(info.get("formats"))
        self._update_start_availability()
        if not available:
            self.status_label.setText("This video has no downloadable formats.")
        elif not self._video_formats and not self._audio_formats:
            self.status_label.setText(
                "YouTube did not report usable size estimates for individual formats. "
                "Unknown-size formats are hidden; use Best quality or MP3."
            )
        elif info.get("thumbnail_error"):
            self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
            self.status_label.setText(
                f"Video details loaded; thumbnail unavailable. {info['thumbnail_error']}"
            )
        elif not ffmpeg_available():
            self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
            self.status_label.setText(
                "FFmpeg is not installed. MP3 and formats that require stream merging are disabled; "
                "install FFmpeg for these options."
            )
        else:
            self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
            self.status_label.setText("Formats and estimated sizes are reported by YouTube.")
            QTimer.singleShot(0, self.format_combo.showPopup)

    def _metadata_failed(self, message: str) -> None:
        if self.url_edit.text().strip() != self._requested_url:
            return
        if "No module named 'yt_dlp'" in message or "No module named \"yt_dlp\"" in message:
            message = "yt-dlp is not installed. Install it with: python -m pip install yt-dlp"
        self._info = None
        self._video_formats = []
        self._audio_formats = []
        self._set_formats_loading(False)
        self.format_combo.clear()
        self.format_combo.addItem("Formats unavailable")
        self.format_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.status_label.setStyleSheet("color: #dc2626; font-weight: 600;")
        self.status_label.setText(f"Could not load video details: {message}")

    def _update_format_choices(self) -> None:
        mode = self.mode_combo.currentText()
        self.format_combo.clear()
        if self._info is None:
            self.format_combo.addItem("Loading formats…" if self.formats_loading.isVisible()
                                      else "Paste a video URL to load formats")
            self.format_combo.setEnabled(False)
            self._update_format_details()
            self._update_start_availability()
            return
        if mode == "Video":
            has_video = bool(
                self._info
                and any(value.get("vcodec") not in (None, "none") for value in self._info.get("formats", []))
            )
            if has_video:
                sizes = [
                    choice["size"] for choice in self._video_formats if choice["size"] >= 0
                ]
                estimate = max(sizes, default=-1)
                ffmpeg_installed = ffmpeg_available()
                best_label = "Best quality available" if ffmpeg_installed else "Best single-file quality"
                if estimate >= 0:
                    best_label += f" · ~{format_size(estimate)}"
                self.format_combo.addItem(
                    best_label,
                    {
                        "format_id": (
                            "bestvideo*+bestaudio/best" if ffmpeg_installed else "best"
                        ),
                        "size": estimate,
                        "resolution": "Best",
                        "codecs": "Best available video and audio",
                        "audio_only": False,
                        "extension": "mkv",
                        "kind": "video",
                    },
                )
                for choice in self._video_formats:
                    self.format_combo.addItem(choice["label"], choice)
                    if "+" in choice["format_id"] and not ffmpeg_installed:
                        self.format_combo.model().item(self.format_combo.count() - 1).setEnabled(False)
        else:
            for choice in self._audio_formats:
                self.format_combo.addItem(choice["label"], choice)
        mp3_size = self._mp3_size()
        mp3_label = "MP3"
        if mp3_size >= 0:
            mp3_label += f" · ~{format_size(mp3_size)}"
        else:
            mp3_label += " · estimated size unavailable"
        self.format_combo.addItem(
            mp3_label,
            {
                "format_id": "mp3",
                "size": mp3_size,
                "resolution": "Audio",
                "codecs": "Audio: MP3",
                "audio_only": True,
                "extension": "mp3",
                "kind": "mp3",
            },
        )
        mp3_item = self.format_combo.model().item(self.format_combo.count() - 1)
        if not ffmpeg_available():
            mp3_item.setEnabled(False)
        self.format_combo.setEnabled(self.format_combo.count() > 0)
        self._update_format_details()
        self._update_start_availability()

    def _mp3_size(self) -> int:
        if not self._info:
            return -1
        try:
            duration = max(0, int(self._info.get("duration") or 0))
        except (TypeError, ValueError):
            return -1
        return mp3_estimated_size(duration, MAX_MP3_BITRATE)

    def _update_format_details(self) -> None:
        choice = self.format_combo.currentData()
        if not isinstance(choice, dict):
            self.size_label.setText("Estimated size unavailable")
            self.codec_label.setText("")
            return
        size = int(choice.get("size", -1))
        prefix = "~" if choice.get("estimated") or choice.get("kind") == "mp3" else ""
        self.size_label.setText(
            f"Estimated size: {prefix}{format_size(size)}" if size >= 0 else "Estimated size unavailable"
        )
        self.codec_label.setText(str(choice.get("codecs", "")))

    def _update_start_availability(self) -> None:
        choice = self.format_combo.currentData()
        selected_item = self.format_combo.model().item(self.format_combo.currentIndex())
        is_mp3 = isinstance(choice, dict) and choice.get("kind") == "mp3"
        self.start_button.setEnabled(
            self._info is not None
            and bool(self._info.get("formats"))
            and isinstance(choice, dict)
            and selected_item is not None
            and selected_item.isEnabled()
            and (not is_mp3 or ffmpeg_available())
        )

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def accept(self) -> None:
        if not self._info:
            return
        try:
            validate_url(self.url_edit.text())
            if not is_youtube_url(self.url_edit.text()):
                raise ValueError("Enter a supported YouTube video URL.")
            folder = ensure_directory(self.folder_edit.text())
            if not self.filename_edit.text().strip():
                raise ValueError("Enter a file name.")
            self.filename_edit.setText(sanitize_filename(self.filename_edit.text().strip()))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot add YouTube download", str(error))
            return
        self.folder_edit.setText(str(folder))
        super().accept()

    def values(self) -> dict:
        choice = self.format_combo.currentData()
        if not isinstance(choice, dict) or self._info is None:
            raise ValueError("Wait for video metadata and choose an available format.")
        mode = self.mode_combo.currentText()
        selected_format = choice["format_id"]
        is_mp3 = choice.get("kind") == "mp3"
        extension = "mp3" if is_mp3 else str(choice.get("extension") or "mkv")
        if selected_format == "best":
            muxed = next(
                (value for value in self._video_formats if "+" not in value["format_id"]),
                None,
            )
            if muxed:
                extension = str(muxed.get("extension") or extension)
        return {
            "url": self.url_edit.text().strip(),
            "folder": self.folder_edit.text().strip(),
            "filename": self.filename_edit.text().strip(),
            "title": str(self._info.get("title") or self.filename_edit.text()),
            "output_name": self.filename_edit.text().strip(),
            "channel": str(self._info.get("channel") or self._info.get("uploader") or ""),
            "duration": int(self._info.get("duration") or 0),
            "format_selector": selected_format,
            "extension": extension,
            "estimated_size": int(choice.get("size", -1)),
            "audio_only": mode == "Audio (original)" or is_mp3,
            "audio_bitrate": MAX_MP3_BITRATE,
        }
