from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..utils import format_speed
from .speed_chart import SpeedChart
from .theme import (
    ACCENT,
    ACCENT_DARK,
    BG_SIDEBAR,
    BG_CARD,
    BG_CARD_SELECTED,
    BORDER,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class _FilterButton(QPushButton):
    """Sidebar filter button that highlights when active."""

    def __init__(self, text: str, filter_key: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.filter_key = filter_key
        self._count = 0
        self._active = False
        self._light_theme = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style()

    def set_count(self, count: int) -> None:
        self._count = count
        self._update_text()

    def set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self._apply_style()

    def set_light_theme(self, light: bool) -> None:
        self._light_theme = light
        self._apply_style()
        self.update()

    def _update_text(self) -> None:
        base = self.filter_key.replace("_", " ").title()
        labels = {
            "all": "All Downloads",
            "active": "Active",
            "paused": "Paused / Queued",
            "completed": "Completed",
            "failed": "Cancelled / Error",
        }
        self.setText(labels.get(self.filter_key, base))

    def _apply_style(self) -> None:
        if self._light_theme:
            active_bg = "#dbeafe"
            active_text = "#0e7490"
            inactive_text = "#475569"
            hover_bg = "#eaf1f8"
            hover_text = "#0f172a"
        else:
            active_bg = BG_CARD_SELECTED
            active_text = ACCENT
            inactive_text = TEXT_SECONDARY
            hover_bg = BG_CARD
            hover_text = TEXT_PRIMARY
        if self._active:
            self.setStyleSheet(
                f"QPushButton {{ background: {active_bg}; color: {active_text};"
                f" border: none; border-left: 3px solid {ACCENT};"
                f" border-radius: 0; text-align: left; padding: 0 10px;"
                f" font-weight: 600; font-size: 9pt; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {inactive_text};"
                f" border: none; border-left: 3px solid transparent;"
                f" border-radius: 0; text-align: left; padding: 0 12px;"
                f" font-size: 9pt; }}"
                f"QPushButton:hover {{ color: {hover_text}; background: {hover_bg}; }}"
            )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._count > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            text = str(self._count)
            font = painter.font()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(text) + 14
            th = 20
            x = self.width() - tw - 10
            y = (self.height() - th) // 2

            # Pill background
            if self._light_theme:
                color = QColor(ACCENT) if self._active else QColor("#e2e8f0")
                text_color = QColor("#0b1018") if self._active else QColor("#475569")
            else:
                color = QColor(ACCENT) if self._active else QColor(BG_CARD)
                text_color = QColor("#0b1018") if self._active else QColor(TEXT_MUTED)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, y, tw, th, 10, 10)

            # Text
            painter.setPen(text_color)
            painter.drawText(x, y, tw, th, Qt.AlignmentFlag.AlignCenter, text)
            painter.end()


class _CategoryDot(QPushButton):
    """Sidebar category button with a colored dot."""

    def __init__(self, text: str, color: str = "#22c55e", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._dot_color = color
        self._active = False
        self._light_theme = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style()

    @property
    def category_name(self) -> str:
        return self._text

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def set_light_theme(self, light: bool) -> None:
        self._light_theme = light
        self._apply_style()
        self.update()

    def _apply_style(self) -> None:
        if self._light_theme:
            color = "#0f172a" if self._active else "#475569"
            hover_color = "#0f172a"
        else:
            color = TEXT_PRIMARY if self._active else TEXT_MUTED
            hover_color = TEXT_PRIMARY
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color};"
            f" border: none; text-align: left; padding: 0 8px;"
            f" font-size: 9pt; }}"
            f"QPushButton:hover {{ color: {hover_color}; }}"
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dot
        painter.setBrush(QColor(self._dot_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(12, (self.height() - 8) // 2, 8, 8)

        # Text
        if self._light_theme:
            color = QColor("#0f172a" if self._active else "#475569")
        else:
            color = QColor(TEXT_PRIMARY if self._active else TEXT_MUTED)
        painter.setPen(color)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(28, 0, self.width() - 36, self.height(), Qt.AlignmentFlag.AlignVCenter, self._text)
        painter.end()


class Sidebar(QWidget):
    """Left sidebar with task filters, categories, parallel spinner, and speed chart."""

    filter_changed = Signal(str)
    category_changed = Signal(str)
    add_clicked = Signal()
    parallel_changed = Signal(int)

    def __init__(self, max_concurrent: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(190)
        self.setStyleSheet(f"Sidebar {{ background: {BG_SIDEBAR}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._current_filter = "all"
        self._current_category = ""
        self._light_theme = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        # ── Add button ──
        self._add_btn = QPushButton("  +  Add New Download")
        self._add_btn.setFixedHeight(34)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_add_button_style()
        self._add_btn.clicked.connect(self.add_clicked)
        layout.addWidget(self._add_btn)

        layout.addSpacing(14)

        # ── TASKS header ──
        tasks_header = QLabel("TASKS")
        tasks_header.setStyleSheet(f"color: {TEXT_DIM}; font-size: 8pt; font-weight: 700; letter-spacing: 1px;")
        layout.addWidget(tasks_header)
        layout.addSpacing(6)

        # ── Filter buttons ──
        self._filters: dict[str, _FilterButton] = {}
        for key in ("all", "active", "paused", "completed", "failed"):
            btn = _FilterButton("", key, self)
            btn.set_count(0)
            btn.clicked.connect(lambda checked=False, k=key: self._on_filter(k))
            layout.addWidget(btn)
            self._filters[key] = btn

        self._filters["all"].set_active(True)
        layout.addSpacing(14)

        # ── CATEGORIES header ──
        cat_header = QLabel("CATEGORIES")
        cat_header.setStyleSheet(f"color: {TEXT_DIM}; font-size: 8pt; font-weight: 700; letter-spacing: 1px;")
        layout.addWidget(cat_header)
        layout.addSpacing(6)

        self._category_layout = QVBoxLayout()
        self._category_layout.setContentsMargins(0, 0, 0, 0)
        self._category_layout.setSpacing(2)
        layout.addLayout(self._category_layout)

        self._category_buttons: list[_CategoryDot] = []

        # Reset category
        self._reset_cat = _CategoryDot("Reset Category Filter", "#22c55e", self)
        self._reset_cat.clicked.connect(lambda: self._on_category(""))

        layout.addStretch(1)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {BORDER}; max-height: 1px;")
        layout.addWidget(sep)
        layout.addSpacing(12)

        # ── Parallel tasks ──
        par_label = QLabel("Parallel Tasks")
        par_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 600; font-size: 9.5pt;")
        par_sub = QLabel("Max simultaneous")
        par_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8pt;")

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 8)
        self.parallel_spin.setValue(max_concurrent)
        self.parallel_spin.setFixedWidth(50)
        self.parallel_spin.setFixedHeight(26)
        self.parallel_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.parallel_spin.setStyleSheet(
            f"QSpinBox {{ background: {BG_CARD}; border: 1px solid {BORDER};"
            f" border-radius: 6px; color: {TEXT_PRIMARY}; font-weight: 600; padding: 0 4px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}"
        )
        self.parallel_spin.valueChanged.connect(self.parallel_changed)

        minus_btn = QPushButton("−")
        minus_btn.setFixedSize(24, 24)
        minus_btn.setStyleSheet(
            f"QPushButton {{ background: {BG_CARD}; border: 1px solid {BORDER};"
            f" border-radius: 5px; color: {TEXT_SECONDARY}; font-size: 12pt; padding: 0; }}"
            f"QPushButton:hover {{ background: {BG_CARD_SELECTED}; }}"
        )
        minus_btn.clicked.connect(lambda: self.parallel_spin.setValue(self.parallel_spin.value() - 1))

        plus_btn = QPushButton("+")
        plus_btn.setFixedSize(24, 24)
        plus_btn.setStyleSheet(minus_btn.styleSheet())
        plus_btn.clicked.connect(lambda: self.parallel_spin.setValue(self.parallel_spin.value() + 1))

        spin_row = QHBoxLayout()
        spin_row.setSpacing(6)
        spin_row.addWidget(minus_btn)
        spin_row.addWidget(self.parallel_spin)
        spin_row.addWidget(plus_btn)
        spin_row.addStretch(1)

        par_header_row = QHBoxLayout()
        par_header_row.addWidget(par_label)
        par_header_row.addStretch(1)

        layout.addWidget(par_label)
        layout.addWidget(par_sub)
        layout.addSpacing(4)
        layout.addLayout(spin_row)
        layout.addSpacing(16)

        # ── Download speed ──
        self._speed_header = QLabel("Download Speed")
        self._speed_header.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")

        self._speed_value = QLabel("—")
        self._speed_value.setStyleSheet(f"color: {ACCENT}; font-weight: 700; font-size: 10pt;")

        speed_row = QHBoxLayout()
        speed_row.addWidget(self._speed_header)
        speed_row.addStretch(1)
        speed_row.addWidget(self._speed_value)

        layout.addLayout(speed_row)
        layout.addSpacing(4)

        self.speed_chart = SpeedChart(self)
        layout.addWidget(self.speed_chart)

    def _on_filter(self, key: str) -> None:
        if self._current_filter == key:
            return
        self._current_filter = key
        for k, btn in self._filters.items():
            btn.set_active(k == key)
        self.filter_changed.emit(key)

    def _on_category(self, name: str) -> None:
        self._current_category = name
        for btn in self._category_buttons:
            btn.set_active(btn.category_name == name)
        self._reset_cat.set_active(False)
        self.category_changed.emit(name)

    def set_light_theme(self, light: bool) -> None:
        self._light_theme = light
        self._apply_add_button_style()
        for button in self._filters.values():
            button.set_light_theme(light)
        for button in self._category_buttons:
            button.set_light_theme(light)
        self._reset_cat.set_light_theme(light)

    def _apply_add_button_style(self) -> None:
        background = "#dbeafe" if self._light_theme else ACCENT_DARK
        foreground = "#0e7490" if self._light_theme else TEXT_PRIMARY
        hover_background = "#bfdbfe" if self._light_theme else ACCENT
        hover_foreground = "#0f172a" if self._light_theme else "#0b1018"
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background: {background}; color: {foreground};"
            f" border: none; border-radius: 6px; font-weight: 600; font-size: 9pt; }}"
            f"QPushButton:hover {{ background: {hover_background}; color: {hover_foreground}; }}"
        )

    def update_counts(self, total: int, active: int, paused: int, completed: int, failed: int) -> None:
        self._filters["all"].set_count(total)
        self._filters["active"].set_count(active)
        self._filters["paused"].set_count(paused)
        self._filters["completed"].set_count(completed)
        self._filters["failed"].set_count(failed)

    def update_speed(self, speed: float) -> None:
        self._speed_value.setText(format_speed(speed) if speed > 0 else "—")
        self.speed_chart.add_sample(speed)

    def update_categories(self, categories: dict[str, int]) -> None:
        # Clear existing category buttons
        for btn in self._category_buttons:
            self._category_layout.removeWidget(btn)
            btn.deleteLater()
        self._category_buttons.clear()

        # Remove reset button if present
        self._category_layout.removeWidget(self._reset_cat)

        for name, count in sorted(categories.items()):
            if name == "Other" and count == 0:
                continue
            btn = _CategoryDot(name, "#22c55e", self)
            btn.set_light_theme(self._light_theme)
            btn.set_active(name == self._current_category)
            btn.clicked.connect(lambda checked=False, n=name: self._on_category(n))
            self._category_layout.addWidget(btn)
            self._category_buttons.append(btn)

        self._category_layout.addWidget(self._reset_cat)
        self._reset_cat.set_light_theme(self._light_theme)
        self._reset_cat.set_active(False)
