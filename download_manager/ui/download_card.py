from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import DownloadItem, DownloadStatus
from ..utils import file_category, format_eta, format_size, format_speed
from .presentation import format_completion_time
from .theme import (
    BADGE_BG,
    BADGE_TEXT,
    BG_CARD,
    BG_CARD_HOVER,
    BG_CARD_SELECTED,
    BORDER,
    BORDER_SELECTED,
    ICON_BG,
    ICON_FG,
    PROGRESS_COLORS,
    BG_PROGRESS,
    STATUS_LABELS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class _CardProgressBar(QProgressBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._track_color = QColor(BG_PROGRESS)
        self._chunk_color = QColor(PROGRESS_COLORS["queued"])
        self._marquee_offset = 0
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(30)
        self._marquee_timer.timeout.connect(self._advance_marquee)
        self.setTextVisible(False)

    def set_colors(self, track: str, chunk: str) -> None:
        self._track_color = QColor(track)
        self._chunk_color = QColor(chunk)
        self.update()

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        super().setRange(minimum, maximum)
        if minimum == 0 and maximum == 0:
            self._marquee_timer.start()
        else:
            self._marquee_timer.stop()
            self._marquee_offset = 0
        self.update()

    def _advance_marquee(self) -> None:
        self._marquee_offset = (self._marquee_offset + 5) % max(self.width(), 1)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track_color)
        painter.drawRoundedRect(rect, radius, radius)

        if self.minimum() == 0 and self.maximum() == 0:
            chunk_width = max(rect.height() * 4, rect.width() // 5)
            chunk_x = self._marquee_offset - chunk_width
            chunk_rect = rect.adjusted(chunk_x, 0, -(rect.width() - chunk_x - chunk_width), 0)
        else:
            span = self.maximum() - self.minimum()
            fraction = (self.value() - self.minimum()) / span if span > 0 else 0
            chunk_rect = rect.adjusted(0, 0, -int(rect.width() * (1 - fraction)), 0)

        painter.setBrush(self._chunk_color)
        painter.drawRoundedRect(chunk_rect, radius, radius)
        painter.end()


class _FileIcon(QWidget):
    """Circular icon painted to match the download status."""

    _GLYPHS = {
        "downloading": "↓",
        "completed": "✓",
        "paused": "⏸",
        "pausing": "⏸",
        "queued": "◷",
        "cancelled": "□",
        "cancelling": "□",
        "failed": "✕",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self._status = "queued"

    def set_status(self, status: str) -> None:
        if self._status != status:
            self._status = status
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(ICON_BG.get(self._status, ICON_BG["queued"]))
        fg = QColor(ICON_FG.get(self._status, ICON_FG["queued"]))

        # Circle background
        painter.setBrush(bg)
        painter.setPen(QPen(bg.lighter(130), 1))
        painter.drawEllipse(2, 2, 32, 32)

        # Glyph
        painter.setPen(fg)
        font = painter.font()
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        glyph = self._GLYPHS.get(self._status, "□")
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()


class _CardControlButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._light_theme = False
        self._hint_text = ""
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        self._hint = QLabel(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(450)
        self._hint_timer.timeout.connect(self._show_hint)

    def set_light_theme(self, light: bool) -> None:
        self._light_theme = light
        self._apply_hint_style()
        self.update()

    def set_hint(self, text: str) -> None:
        self._hint_text = text
        self._hint_timer.stop()
        self._hint.hide()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        if self._hint_text:
            self._hint_timer.start()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hint_timer.stop()
        self._hint.hide()
        super().leaveEvent(event)

    def _show_hint(self) -> None:
        if not self._hint_text:
            return
        self._hint.setText(self._hint_text)
        self._hint.adjustSize()
        self._apply_hint_style()
        window = self.window()
        bounds = window.frameGeometry()
        screen = QGuiApplication.screenAt(self.mapToGlobal(self.rect().center()))
        if screen is not None:
            bounds = bounds.intersected(screen.availableGeometry())
            if bounds.isEmpty():
                bounds = screen.availableGeometry()

        button_top_left = self.mapToGlobal(QPoint(0, 0))
        position = self._hint_position(
            button_top_left,
            self.size(),
            self._hint.size(),
            bounds,
        )
        self._hint.move(position)
        self._hint.show()

    @staticmethod
    def _hint_position(button: QPoint, button_size: QSize, hint_size: QSize, bounds: QRect) -> QPoint:
        x = button.x() - hint_size.width() - 8
        if x < bounds.left():
            x = button.x() + button_size.width() + 8

        y = button.y() - hint_size.height() - 8
        if y < bounds.top():
            y = button.y() + button_size.height() + 8
        if y + hint_size.height() > bounds.bottom() + 1:
            y = button.y() - hint_size.height() - 8

        max_x = max(bounds.left(), bounds.right() - hint_size.width() + 1)
        max_y = max(bounds.top(), bounds.bottom() - hint_size.height() + 1)
        return QPoint(
            max(bounds.left(), min(x, max_x)),
            max(bounds.top(), min(y, max_y)),
        )

    def _apply_hint_style(self) -> None:
        background = "#ffffff" if self._light_theme else "#1e2d40"
        foreground = "#1f2937" if self._light_theme else "#e5e7eb"
        border = "#cbd5e1" if self._light_theme else "#253444"
        self._hint.setStyleSheet(
            f"QLabel {{ background-color: {background}; color: {foreground};"
            f" border: 1px solid {border}; border-radius: 4px; padding: 5px 8px; }}"
        )

    def colors(self, hovered: bool, pressed: bool, enabled: bool) -> tuple[QColor, QColor, QColor]:
        if self._light_theme:
            background = "#ffffff" if hovered or pressed else "#e8eef5"
            foreground = "#0f172a" if hovered or pressed else "#334155"
            border = "#cbd5e1"
            disabled = "#94a3b8"
        else:
            background = BG_CARD_HOVER if hovered or pressed else BG_CARD
            foreground = TEXT_PRIMARY if hovered or pressed else TEXT_SECONDARY
            border = BORDER
            disabled = TEXT_MUTED
        return QColor(background), QColor(foreground if enabled else disabled), QColor(border)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background, foreground, border = self.colors(self.underMouse(), self.isDown(), self.isEnabled())
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawEllipse(rect)
        painter.setPen(foreground)
        font = painter.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class _FolderPathHint(QObject):
    def __init__(self, target: QLabel, parent: QWidget) -> None:
        super().__init__(target)
        self._target = target
        self._parent = parent
        self._light_theme = False
        self._text = ""
        self._popup = QLabel(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._popup.setWordWrap(True)
        self._popup.setMaximumWidth(420)
        self._popup.setStyleSheet("QLabel { padding: 0; }")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._show)
        target.installEventFilter(self)

    def set_text(self, text: str) -> None:
        self._text = text
        self._timer.stop()
        self._popup.hide()

    def set_light_theme(self, light: bool) -> None:
        self._light_theme = light
        self._apply_style()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._target:
            if event.type() == QEvent.Type.Enter and self._text:
                self._timer.start()
            elif event.type() in {QEvent.Type.Leave, QEvent.Type.Hide}:
                self._timer.stop()
                self._popup.hide()
        return False

    def _show(self) -> None:
        if not self._target.underMouse() or not self._text:
            return
        self._popup.setText(self._text)
        self._popup.adjustSize()
        self._apply_style()
        bounds = self._parent.window().frameGeometry()
        screen = QGuiApplication.screenAt(self._target.mapToGlobal(self._target.rect().center()))
        if screen is not None:
            bounds = bounds.intersected(screen.availableGeometry())
            if bounds.isEmpty():
                bounds = screen.availableGeometry()
        top_left = self._target.mapToGlobal(QPoint(0, 0))
        position = _CardControlButton._hint_position(
            top_left,
            self._target.size(),
            self._popup.size(),
            bounds,
        )
        self._popup.move(position)
        self._popup.show()

    def _apply_style(self) -> None:
        if self._light_theme:
            background, foreground, border = "#ffffff", "#1f2937", "#cbd5e1"
        else:
            background, foreground, border = "#1e2d40", "#e5e7eb", "#253444"
        self._popup.setStyleSheet(
            f"QLabel {{ background-color: {background}; color: {foreground};"
            f" border: 1px solid {border}; border-radius: 5px; padding: 7px 10px; }}"
        )


class DownloadCard(QFrame):
    """Styled card widget representing a single download item."""

    clicked = Signal(str)
    control_requested = Signal(str, str)

    def __init__(self, item: DownloadItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item_id = item.id
        self._selected = False
        self._light_theme = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(78)

        # ── Icon ──
        self._icon = _FileIcon(self)
        self._control_button = _CardControlButton(self)
        self._control_button.clicked.connect(self._on_control_clicked)

        # ── Top row: filename, badge, speed, eta, percentage ──
        self._name_label = QLabel()
        self._name_label.setStyleSheet(f"font-weight: 600; font-size: 9.5pt; color: {TEXT_PRIMARY};")

        self._badge = QLabel()
        self._badge.setFixedHeight(19)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._speed_label = QLabel()
        self._speed_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600; font-size: 9pt;")

        self._eta_label = QLabel()
        self._eta_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")

        self._pct_label = QLabel()
        self._pct_label.setStyleSheet(f"font-weight: 700; font-size: 9.5pt; color: {TEXT_PRIMARY};")
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.addWidget(self._name_label)
        top_row.addWidget(self._badge)
        top_row.addStretch(1)
        top_row.addWidget(self._speed_label)
        top_row.addWidget(self._eta_label)
        top_row.addWidget(self._pct_label)

        # ── Progress bar ──
        self._progress = _CardProgressBar()
        self._progress.setFixedHeight(5)

        # ── Bottom row: size and folder ──
        self._size_label = QLabel()
        self._size_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")

        self._completed_at_label = QLabel()
        self._completed_at_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")

        self._folder_label = QLabel()
        self._folder_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")
        self._folder_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._folder_hint = _FolderPathHint(self._folder_label, self)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(6)
        bottom_row.addWidget(self._size_label)
        bottom_row.addWidget(self._completed_at_label)
        bottom_row.addStretch(1)
        folder_icon = QLabel("📁")
        folder_icon.setStyleSheet("font-size: 9pt;")
        folder_icon.setFixedWidth(16)
        bottom_row.addWidget(folder_icon)
        bottom_row.addWidget(self._folder_label)

        # ── Right column layout ──
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(3)
        right_col.addLayout(top_row)
        right_col.addWidget(self._progress)
        right_col.addLayout(bottom_row)

        # ── Main layout ──
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 9, 12, 9)
        main_layout.setSpacing(10)
        main_layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        main_layout.addLayout(right_col, 1)
        main_layout.addWidget(self._control_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.update_item(item)
        self._apply_card_style()

    @property
    def item_id(self) -> str:
        return self._item_id

    @property
    def category(self) -> str:
        return file_category(self._name_label.text())

    def set_selected(self, selected: bool) -> None:
        if self._selected != selected:
            self._selected = selected
            self._apply_card_style()

    def set_light_theme(self, light: bool) -> None:
        if self._light_theme == light:
            return
        self._light_theme = light
        self._control_button.set_light_theme(light)
        self._folder_hint.set_light_theme(light)
        self._apply_progress_style()
        self._apply_badge_style()

    def update_item(self, item: DownloadItem) -> None:
        status = item.status.value
        self._status = status
        if item.status in {DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED}:
            self._control_operation = "pause"
            self._control_button.setText("Ⅱ")
            self._control_button.set_hint("Pause download")
            self._control_button.setEnabled(True)
            self._control_button.show()
        elif item.status == DownloadStatus.PAUSED:
            self._control_operation = "resume"
            self._control_button.setText("▶")
            self._control_button.set_hint("Resume download")
            self._control_button.setEnabled(True)
            self._control_button.show()
        elif item.status in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
            self._control_operation = "retry"
            self._control_button.setText("↻")
            self._control_button.set_hint("Retry download")
            self._control_button.setEnabled(True)
            self._control_button.show()
        elif item.status in {DownloadStatus.PAUSING, DownloadStatus.CANCELLING}:
            self._control_operation = ""
            self._control_button.setText("…")
            self._control_button.set_hint("Waiting for transfer to stop")
            self._control_button.setEnabled(False)
            self._control_button.show()
        else:
            self._control_operation = ""
            self._control_button.hide()
        # Name
        self._name_label.setText(item.filename)
        self._name_label.setToolTip(item.url)

        # Icon
        self._icon.set_status(status)

        # Badge
        label = STATUS_LABELS.get(status, status.title())
        bg = BADGE_BG.get(status, BADGE_BG["queued"])
        fg = BADGE_TEXT.get(status, BADGE_TEXT["queued"])
        self._badge.setText(f"  {label}  ")
        self._badge_background = bg
        self._badge_foreground = fg
        self._apply_badge_style()

        # Speed / ETA
        if item.status == DownloadStatus.DOWNLOADING:
            self._speed_label.setText(format_speed(item.speed))
            eta = format_eta(item.downloaded_bytes, item.total_bytes, item.speed)
            self._eta_label.setText(f"ETA: {eta}" if eta else "")
            self._speed_label.show()
            self._eta_label.show()
        else:
            self._speed_label.hide()
            self._eta_label.hide()

        # Percentage
        if item.total_bytes > 0:
            pct = min(100.0, item.downloaded_bytes / item.total_bytes * 100)
            if item.source_type == "youtube" and item.status == DownloadStatus.DOWNLOADING:
                pct = min(pct, 99.9)
            self._pct_label.setText(f"{pct:.1f}%")
        elif item.status == DownloadStatus.COMPLETED:
            self._pct_label.setText("100.0%")
        else:
            self._pct_label.setText("")

        # Progress bar
        self._progress_color = PROGRESS_COLORS.get(status, PROGRESS_COLORS["queued"])
        self._apply_progress_style()
        if item.total_bytes > 0:
            self._progress.setRange(0, 10000)
            frac = min(1.0, item.downloaded_bytes / item.total_bytes)
            if item.source_type == "youtube" and item.status == DownloadStatus.DOWNLOADING:
                frac = min(frac, 0.999)
            self._progress.setValue(int(frac * 10000))
        elif item.status == DownloadStatus.COMPLETED:
            self._progress.setRange(0, 1)
            self._progress.setValue(1)
        elif item.status == DownloadStatus.DOWNLOADING and item.total_bytes < 0:
            self._progress.setRange(0, 0)  # indeterminate
        else:
            self._progress.setRange(0, 1)
            self._progress.setValue(0)

        # Size
        total = format_size(item.total_bytes)
        dl = format_size(item.downloaded_bytes)
        self._size_label.setText(f"{dl} / {total}")

        completion_time = (
            format_completion_time(item.completed_at)
            if item.status == DownloadStatus.COMPLETED
            else None
        )
        if completion_time is None:
            self._completed_at_label.clear()
            self._completed_at_label.setToolTip("")
            self._completed_at_label.hide()
        else:
            display, tooltip = completion_time
            self._completed_at_label.setText(display)
            self._completed_at_label.setToolTip(tooltip)
            self._completed_at_label.show()

        # Folder
        self._folder_label.setText(item.folder)
        self._folder_hint.set_text(item.folder)

    def _on_control_clicked(self) -> None:
        if self._control_operation:
            self.control_requested.emit(self._item_id, self._control_operation)

    def _apply_progress_style(self) -> None:
        track = "#e2e8f0" if self._light_theme else BG_PROGRESS
        self._progress.set_colors(track, self._progress_color)

    def _apply_badge_style(self) -> None:
        if self._light_theme:
            light_badges = {
                "downloading": ("#cffafe", "#0e7490"),
                "completed": ("#d1fae5", "#047857"),
                "paused": ("#dcfce7", "#15803d"),
                "pausing": ("#fef3c7", "#b45309"),
                "queued": ("#e2e8f0", "#475569"),
                "cancelled": ("#fee2e2", "#b91c1c"),
                "cancelling": ("#ffedd5", "#c2410c"),
                "failed": ("#fee2e2", "#b91c1c"),
            }
            background, foreground = light_badges.get(self._status, ("#e2e8f0", "#475569"))
        else:
            background = self._badge_background
            foreground = self._badge_foreground
        self._badge.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 10px;"
            f" font-size: 7.5pt; font-weight: 600; padding: 1px 8px;"
        )

    def _apply_card_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"DownloadCard {{ background: {BG_CARD_SELECTED}; border: 1px solid {BORDER_SELECTED};"
                f" border-radius: 10px; }}"
            )
        else:
            self.setStyleSheet(
                f"DownloadCard {{ background: {BG_CARD}; border: 1px solid {BORDER};"
                f" border-radius: 10px; }}"
                f"DownloadCard:hover {{ background: {BG_CARD_HOVER}; border-color: {BORDER}; }}"
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._item_id)
        super().mousePressEvent(event)
