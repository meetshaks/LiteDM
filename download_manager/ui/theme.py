from __future__ import annotations

import re

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

# ── Background tones ──
BG_APP = "#0b1018"
BG_SIDEBAR = "#0f1520"
BG_CONTENT = "#0d1117"
BG_HEADER = "#0d1219"
BG_CARD = "#131c27"
BG_CARD_HOVER = "#172333"
BG_CARD_SELECTED = "#122236"
BG_INPUT = "#131c27"
BG_BUTTON = "#182535"
BG_BUTTON_HOVER = "#223042"
BG_INSPECTOR = "#0f1520"
BG_PROGRESS = "#1c2736"
BG_BADGE = "#0f1a24"

# ── Borders ──
BORDER = "#1c2a3a"
BORDER_LIGHT = "#253444"
BORDER_SELECTED = "#22d3ee"
BORDER_INPUT = "#253444"

# ── Text ──
TEXT_PRIMARY = "#e5e7eb"
TEXT_SECONDARY = "#8b9bb0"
TEXT_MUTED = "#5a6a7e"
TEXT_DIM = "#3d4f63"

# ── Accent ──
ACCENT = "#22d3ee"
ACCENT_DARK = "#0e7490"

# ── Status palettes keyed by DownloadStatus.value ──
STATUS_COLORS: dict[str, str] = {
    "downloading": "#22d3ee",
    "completed": "#34d399",
    "paused": "#22c55e",
    "pausing": "#fbbf24",
    "queued": "#94a3b8",
    "cancelled": "#f87171",
    "cancelling": "#fb923c",
    "failed": "#f87171",
}

PROGRESS_COLORS: dict[str, str] = {
    "downloading": "#22d3ee",
    "completed": "#10b981",
    "paused": "#f59e0b",
    "pausing": "#f59e0b",
    "queued": "#475569",
    "cancelled": "#ec4899",
    "cancelling": "#fb923c",
    "failed": "#ef4444",
}

BADGE_BG: dict[str, str] = {
    "downloading": "#0c3644",
    "completed": "#0c3626",
    "paused": "#0c3620",
    "pausing": "#3b2f0a",
    "queued": "#1e293b",
    "cancelled": "#3b1414",
    "cancelling": "#3b2014",
    "failed": "#3b1414",
}

BADGE_TEXT: dict[str, str] = {
    "downloading": "#22d3ee",
    "completed": "#34d399",
    "paused": "#22c55e",
    "pausing": "#fbbf24",
    "queued": "#94a3b8",
    "cancelled": "#f87171",
    "cancelling": "#fb923c",
    "failed": "#f87171",
}

STATUS_LABELS: dict[str, str] = {
    "queued": "Queued",
    "downloading": "Downloading",
    "pausing": "Pausing",
    "paused": "Paused",
    "cancelling": "Cancelling",
    "cancelled": "Cancelled",
    "completed": "Completed",
    "failed": "Failed",
}

# ── Icon circle colors (darker shades for icon background) ──
ICON_BG: dict[str, str] = {
    "downloading": "#0c3040",
    "completed": "#1a2a30",
    "paused": "#1a2a30",
    "pausing": "#2a2a1a",
    "queued": "#1a2030",
    "cancelled": "#2a1a20",
    "cancelling": "#2a2018",
    "failed": "#2a1a20",
}

ICON_FG: dict[str, str] = {
    "downloading": "#22d3ee",
    "completed": "#64748b",
    "paused": "#22d3ee",
    "pausing": "#fbbf24",
    "queued": "#64748b",
    "cancelled": "#64748b",
    "cancelling": "#fb923c",
    "failed": "#f87171",
}


_LIGHT_COLORS = {
    "#0b1018": "#f3f6fa",
    "#0f1520": "#fdfefe",
    "#0d1117": "#f1f5f9",
    "#0d1219": "#eef2f6",
    "#131c27": "#ffffff",
    "#172333": "#eaf1f8",
    "#122236": "#dbeafe",
    "#131c27": "#ffffff",
    "#182535": "#e8eef5",
    "#223042": "#dce5ef",
    "#1c2736": "#e2e8f0",
    "#0f1a24": "#f1f5f9",
    "#1c2a3a": "#d6dee8",
    "#253444": "#cbd5e1",
    "#e5e7eb": "#1f2937",
    "#8b9bb0": "#475569",
    "#5a6a7e": "#64748b",
    "#3d4f63": "#94a3b8",
    "#2a3a52": "#cbd5e1",
    "#2a3a50": "#cbd5e1",
    "#3b4a5e": "#94a3b8",
    "#1e2d40": "#ffffff",
    "#0c3644": "#cffafe",
    "#0c3626": "#d1fae5",
    "#0c3620": "#dcfce7",
    "#3b2f0a": "#fef3c7",
    "#1e293b": "#e2e8f0",
    "#3b1414": "#fee2e2",
    "#3b2014": "#ffedd5",
}


def _replace_colors(stylesheet: str, colors: dict[str, str]) -> str:
    if not stylesheet:
        return stylesheet
    pattern = re.compile("|".join(re.escape(color) for color in colors), re.IGNORECASE)
    return pattern.sub(lambda match: colors[match.group(0).lower()], stylesheet)


def apply_widget_theme(root: QWidget, light: bool) -> None:
    colors = _LIGHT_COLORS if light else {value: key for key, value in _LIGHT_COLORS.items()}
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        stylesheet = widget.styleSheet()
        if stylesheet:
            widget.setStyleSheet(_replace_colors(stylesheet, colors))


def apply_theme(application: QApplication, light: bool = False) -> None:
    application.setStyle("Fusion")
    if light:
        tooltip_background = "#ffffff"
        tooltip_foreground = "#1f2937"
        tooltip_border = "#cbd5e1"
        stylesheet = _replace_colors(_STYLESHEET, _LIGHT_COLORS)
    else:
        tooltip_background = "#1e2d40"
        tooltip_foreground = TEXT_PRIMARY
        tooltip_border = BORDER_LIGHT
        stylesheet = _STYLESHEET

    tooltip_palette = QPalette()
    tooltip_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tooltip_background))
    tooltip_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(tooltip_foreground))
    QToolTip.setPalette(tooltip_palette)
    application.setStyleSheet(
        stylesheet
        + f"""
        QToolTip {{
            background-color: {tooltip_background};
            color: {tooltip_foreground};
            border: 1px solid {tooltip_border};
        }}
        """
    )


_STYLESHEET = f"""
    /* ── Global ── */
    * {{ color: {TEXT_PRIMARY}; }}
    QMainWindow {{ background: {BG_APP}; }}
    QDialog {{ background: {BG_SIDEBAR}; color: {TEXT_PRIMARY}; }}
    QWidget {{ font-family: 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif; font-size: 9pt; }}

    /* ── Scroll area ── */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    /* ── Inputs ── */
    QLineEdit, QSpinBox {{
        background: {BG_INPUT}; border: 1px solid {BORDER_INPUT};
        border-radius: 5px; padding: 5px 8px;
        selection-background-color: {ACCENT_DARK};
    }}
    QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}

    /* ── Buttons ── */
    QPushButton {{
        background: {BG_BUTTON}; border: 1px solid {BORDER_LIGHT};
        border-radius: 5px; padding: 5px 10px; color: {TEXT_SECONDARY};
    }}
    QPushButton:hover {{ background: {BG_BUTTON_HOVER}; color: {TEXT_PRIMARY}; }}
    QPushButton:pressed {{ background: #2a3a52; }}
    QPushButton:disabled {{ color: {TEXT_DIM}; background: {BG_CARD}; border-color: {BORDER}; }}

    /* ── Scroll bars ── */
    QScrollBar:vertical {{
        background: {BG_CONTENT}; width: 8px; margin: 0; border: none;
    }}
    QScrollBar::handle:vertical {{
        background: #2a3a50; border-radius: 4px; min-height: 30px; margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #3b4a5e; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: {BG_CONTENT}; height: 8px; margin: 0; border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: #2a3a50; border-radius: 4px; min-width: 30px; margin: 2px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ── Tooltips ── */
    QToolTip {{
        background: #1e2d40; color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_LIGHT}; padding: 5px 8px; border-radius: 4px;
    }}

    /* ── Dialog buttons ── */
    QDialogButtonBox QPushButton {{ min-width: 90px; }}
    QDialogButtonBox QPushButton:default {{
        background: {ACCENT_DARK}; border-color: {ACCENT}; color: {TEXT_PRIMARY};
    }}

    /* ── Combo box ── */
    QComboBox {{
        background: {BG_INPUT}; border: 1px solid {BORDER_INPUT};
        border-radius: 5px; padding: 5px 8px;
    }}
    QComboBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {BG_SIDEBAR}; border: 1px solid {BORDER_LIGHT};
        selection-background-color: {BG_CARD_SELECTED};
    }}

    /* ── Context menus ── */
    QMenu {{
        background: {BG_SIDEBAR}; color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_LIGHT}; padding: 4px;
    }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {BG_CARD_SELECTED}; color: {TEXT_PRIMARY}; }}
    QMenu::item:disabled {{ color: {TEXT_MUTED}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

    /* ── Message box ── */
    QMessageBox {{ background: {BG_SIDEBAR}; }}
    QMessageBox QLabel {{ color: {TEXT_PRIMARY}; }}
"""
