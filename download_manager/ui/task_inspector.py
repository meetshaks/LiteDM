from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import DownloadItem, DownloadStatus
from .theme import (
    ACCENT,
    BG_CARD,
    BG_INSPECTOR,
    BG_PROGRESS,
    BORDER,
    PROGRESS_COLORS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class _ChunkBar(QWidget):
    """Paints a visual representation of download thread progress."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setMinimumWidth(200)
        self._chunks = 1
        self._progress = 0.0  # 0..1
        self._color = ACCENT
        self._active = False

    def set_state(self, chunks: int, progress: float, color: str, active: bool) -> None:
        self._chunks = max(1, chunks)
        self._progress = max(0.0, min(1.0, progress))
        self._color = color
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        gap = 3
        chunk_w = max(8, (w - gap * (self._chunks - 1)) / self._chunks)

        for i in range(self._chunks):
            x = int(i * (chunk_w + gap))
            cw = int(chunk_w)

            # Background
            painter.setBrush(QColor(BG_PROGRESS))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, 2, cw, h - 4, 3, 3)

            # Filled portion – for simplicity, use overall progress for all chunks
            fill_w = int(cw * self._progress)
            if fill_w > 0:
                painter.setBrush(QColor(self._color))
                painter.drawRoundedRect(x, 2, fill_w, h - 4, 3, 3)

        painter.end()


class TaskInspector(QFrame):
    """Bottom panel showing details about the selected download."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"TaskInspector {{ background: {BG_INSPECTOR}; border-top: 1px solid {BORDER}; }}"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(76)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(5)

        # ── Header row ──
        self._toggle_btn = QPushButton("+")
        self._toggle_btn.setFixedSize(18, 18)
        self._toggle_btn.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; border: 1px solid {BORDER};"
            f" border-radius: 4px; color: {TEXT_MUTED}; font-size: 10pt;"
            f" padding: 0; font-weight: 700; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; }}"
        )

        self._title_label = QLabel("Task Inspector:")
        self._title_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 9.5pt; font-weight: 600;")

        self._file_label = QLabel()
        self._file_label.setStyleSheet(f"color: {ACCENT}; font-size: 9.5pt; font-weight: 600;")

        self._hash_label = QLabel()
        self._hash_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")
        self._hash_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        header_row.addWidget(self._toggle_btn)
        header_row.addWidget(self._title_label)
        header_row.addWidget(self._file_label)
        header_row.addStretch(1)
        header_row.addWidget(self._hash_label)
        layout.addLayout(header_row)

        # ── Detail row ──
        self._detail_widget = QWidget()
        detail_layout = QHBoxLayout(self._detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)

        # URL section
        url_col = QVBoxLayout()
        url_col.setSpacing(2)
        url_header_row = QHBoxLayout()
        url_lbl = QLabel("Source URL")
        url_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8pt;")
        self._copy_btn = QPushButton("Copy URL")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ACCENT}; border: none;"
            f" font-size: 8pt; font-weight: 600; padding: 0; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; }}"
        )
        self._copy_btn.clicked.connect(self._copy_url)
        url_header_row.addWidget(url_lbl)
        url_header_row.addStretch(1)
        url_header_row.addWidget(self._copy_btn)
        url_col.addLayout(url_header_row)

        self._url_label = QLabel()
        self._url_label.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT_SECONDARY}; padding: 4px 8px;"
            f" border: 1px solid {BORDER}; border-radius: 4px; font-size: 8pt;"
        )
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        url_col.addWidget(self._url_label)
        detail_layout.addLayout(url_col, 3)

        # Thread chunks section
        chunk_col = QVBoxLayout()
        chunk_col.setSpacing(2)
        chunk_header_row = QHBoxLayout()
        self._chunk_title = QLabel("Parallel Thread Chunks (1 Connection)")
        self._chunk_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8pt;")
        self._active_label = QLabel("ACTIVE")
        self._active_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 8pt; font-weight: 700;")
        chunk_header_row.addWidget(self._chunk_title)
        chunk_header_row.addStretch(1)
        chunk_header_row.addWidget(self._active_label)
        chunk_col.addLayout(chunk_header_row)

        self._chunk_bar = _ChunkBar(self)
        chunk_col.addWidget(self._chunk_bar)
        detail_layout.addLayout(chunk_col, 2)

        layout.addWidget(self._detail_widget)

        self._current_url = ""
        self.clear()

    def set_item(self, item: DownloadItem | None) -> None:
        if not item:
            self.clear()
            return

        self._file_label.setText(item.filename)
        self._url_label.setText(item.url)
        self._current_url = item.url
        self._hash_label.setText("")

        status = item.status.value
        active = item.status in {DownloadStatus.DOWNLOADING, DownloadStatus.PAUSING}
        self._active_label.setText("ACTIVE" if active else status.upper())
        label_color = PROGRESS_COLORS.get(status, TEXT_MUTED)
        self._active_label.setStyleSheet(f"color: {label_color}; font-size: 8pt; font-weight: 700;")

        progress = 0.0
        if item.total_bytes > 0:
            progress = min(1.0, item.downloaded_bytes / item.total_bytes)
        elif item.status == DownloadStatus.COMPLETED:
            progress = 1.0
        pcolor = PROGRESS_COLORS.get(status, ACCENT)
        self._chunk_bar.set_state(1, progress, pcolor, active)
        self._chunk_title.setText("Parallel Thread Chunks (1 Connection)")

        self._detail_widget.show()

    def clear(self) -> None:
        self._file_label.setText("No download selected")
        self._url_label.setText("")
        self._current_url = ""
        self._hash_label.setText("")
        self._active_label.setText("")
        self._chunk_bar.set_state(1, 0.0, ACCENT, False)
        self._detail_widget.hide()

    def _copy_url(self) -> None:
        if self._current_url:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(self._current_url)
