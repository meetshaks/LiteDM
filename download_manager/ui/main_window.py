from __future__ import annotations

import secrets
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QClipboard, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..manager import DownloadManager
from ..settings import AppSettings
from ..models import DownloadItem, DownloadStatus
from ..utils import (
    app_icon_path,
    default_download_dir,
    filename_from_url,
    format_speed,
    sanitize_filename,
)
from ..youtube import format_choices, is_youtube_url
from ..youtube_worker import MetadataWorker
from .add_dialog import AddDownloadDialog
from .download_card import DownloadCard
from .presentation import available_queue_actions, matches_download, summarize_downloads
from .sidebar import Sidebar
from .task_inspector import TaskInspector
from .theme import (
    ACCENT,
    ACCENT_DARK,
    BG_APP,
    BG_CARD,
    BG_CONTENT,
    BG_HEADER,
    BG_SIDEBAR,
    BORDER,
    BORDER_LIGHT,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    apply_widget_theme,
    apply_theme as apply_application_theme,
)
from .youtube_dialog import YouTubeDownloadDialog

# Re-export for backward compat with app.py
apply_theme = apply_application_theme


class MainWindow(QMainWindow):

    def __init__(self, manager: DownloadManager, settings: AppSettings | object | None = None):
        super().__init__()
        self.manager = manager
        if settings is None:
            self.settings = AppSettings()
        elif isinstance(settings, AppSettings):
            self.settings = settings
        else:
            self.settings = AppSettings(settings=settings)
        self._light_theme = self.settings.is_light_theme()
        self._cards: dict[str, DownloadCard] = {}
        self._selected_id: str | None = None
        self._close_pending = False
        self._close_allowed = False
        self._current_filter = "all"
        self._current_category = ""
        self._global_speed = 0.0
        self._browser_youtube_sessions: dict[str, dict] = {}
        self._browser_youtube_workers: set[MetadataWorker] = set()

        self.setWindowTitle("LiteDM — Linux Download Manager")
        self.setWindowIcon(QIcon(str(app_icon_path())))
        self.resize(1180, 720)
        self.setMinimumSize(900, 560)
        self.setStyleSheet(f"QMainWindow {{ background: {BG_APP}; }}")

        self._build_actions()
        self._build_ui()
        self._connect_signals()

        # Load existing items
        for item in self.manager.items():
            self._add_item(item)

        # Restore geometry
        geometry = self.settings.geometry()
        if geometry:
            self.restoreGeometry(geometry)

        self._update_counts()
        self._update_actions()
        apply_widget_theme(self, self._light_theme)
        self.sidebar.set_light_theme(self._light_theme)

        # Speed tracking timer
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(1000)
        self._speed_timer.timeout.connect(self._push_speed_sample)
        self._speed_timer.start()

    # ── Actions ──

    def _icon(self, theme_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        if QIcon.hasThemeIcon(theme_name):
            return QIcon.fromTheme(theme_name)
        return self.style().standardIcon(fallback)

    def _build_actions(self) -> None:
        self.add_action = QAction("Add", self)
        self.add_action.setShortcut("Ctrl+O")
        self.add_action.triggered.connect(self._add_download)

        self.pause_all_action = QAction("Pause All", self)
        self.pause_all_action.triggered.connect(self.manager.pause_all)

        self.resume_all_action = QAction("Resume All", self)
        self.resume_all_action.triggered.connect(self.manager.resume_all)

        self.quit_action = QAction("Quit", self)
        self.quit_action.setShortcut("Ctrl+Q")
        self.quit_action.triggered.connect(self.close)
        self.addAction(self.quit_action)

    # ── UI build ──

    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet("background: transparent;")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Header bar ──
        header = self._build_header()
        root_layout.addWidget(header)

        # ── Body: sidebar + content ──
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(self.manager.max_concurrent, self)
        body_layout.addWidget(self.sidebar)

        # Vertical separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"background: {BORDER}; max-width: 1px;")
        body_layout.addWidget(sep)

        # Content area
        content = self._build_content()
        body_layout.addWidget(content, 1)

        root_layout.addWidget(body, 1)
        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(42)
        header.setStyleSheet(
            f"background: {BG_HEADER}; border-bottom: 1px solid {BORDER};"
        )

        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        # App icon (styled dot)
        icon_dot = QLabel("⬇")
        icon_dot.setFixedSize(24, 24)
        icon_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_dot.setStyleSheet(
            f"background: {ACCENT_DARK}; border-radius: 14px; color: {ACCENT};"
            f" font-size: 12pt; font-weight: 700;"
        )

        title = QLabel("LiteDM")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 700; font-size: 11pt;")

        subtitle = QLabel("— Linux Download Manager")
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")

        version = QLabel("v1.0 UI")
        version.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT_MUTED}; border: 1px solid {BORDER};"
            f" border-radius: 4px; padding: 1px 6px; font-size: 7.5pt;"
        )

        layout.addWidget(icon_dot)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(version)
        layout.addStretch(1)

        return header

    def _build_content(self) -> QWidget:
        content = QWidget()
        content.setStyleSheet(f"background: {BG_CONTENT};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Action bar ──
        action_bar = self._build_action_bar()
        layout.addWidget(action_bar)

        # ── Queue header ──
        queue_header = self._build_queue_header()
        layout.addWidget(queue_header)

        # ── Card scroll area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._card_container = QWidget()
        self._card_container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(14, 6, 14, 14)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch(1)

        self._scroll.setWidget(self._card_container)
        layout.addWidget(self._scroll, 1)

        # ── Task inspector ──
        self.inspector = TaskInspector(self)
        layout.addWidget(self.inspector)

        return content

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(42)
        bar.setStyleSheet(f"background: {BG_CONTENT};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(2)

        btn_style = (
            f"QPushButton {{ background: transparent; border: none; color: {TEXT_SECONDARY};"
            f" font-size: 9pt; padding: 4px 8px; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; }}"
            f"QPushButton:disabled {{ color: {TEXT_DIM}; }}"
        )

        icons = {
            "Pause All": ("⏸", self.pause_all_action),
            "Resume All": ("▶", self.resume_all_action),
        }

        self._action_buttons: dict[str, QPushButton] = {}
        for label, (glyph, action) in icons.items():
            btn = QPushButton(f" {glyph}  {label}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(action.trigger)
            layout.addWidget(btn)
            self._action_buttons[label] = btn

        layout.addStretch(1)

        self.theme_button = QPushButton()
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_button)
        self._update_theme_button()

        # Search
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search downloads...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(210)
        self.search_edit.setFixedHeight(30)
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD}; border: 1px solid {BORDER};"
            f" border-radius: 5px; padding: 0 8px; color: {TEXT_SECONDARY}; font-size: 8.5pt; }}"
            f"QLineEdit:focus {{ border-color: {ACCENT}; color: {TEXT_PRIMARY}; }}"
        )

        search_shortcut = QLabel("Ctrl+F")
        search_shortcut.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT_DIM}; border: 1px solid {BORDER};"
            f" border-radius: 3px; padding: 1px 5px; font-size: 7.5pt;"
        )

        QShortcut(QKeySequence("Ctrl+F"), self, self.search_edit.setFocus)

        layout.addWidget(self.search_edit)
        layout.addWidget(search_shortcut)

        return bar

    def _build_queue_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet(f"background: {BG_CONTENT};")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 0, 14, 0)

        self._queue_title = QLabel("Downloads Queue")
        self._queue_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 700; font-size: 10pt;")

        self._queue_stats = QLabel()
        self._queue_stats.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")

        self._default_path_label = QLabel()
        self._default_path_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")
        self._default_path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        try:
            self._default_path_label.setText(f"Default Path: {default_download_dir()}")
        except (OSError, ValueError):
            self._default_path_label.setText("")

        layout.addWidget(self._queue_title)
        layout.addSpacing(8)
        layout.addWidget(self._queue_stats)
        layout.addStretch(1)
        layout.addWidget(self._default_path_label)

        return header

    # ── Signal connections ──

    def _connect_signals(self) -> None:
        self.manager.item_added.connect(self._add_item)
        self.manager.item_updated.connect(self._update_item)
        self.manager.item_removed.connect(self._remove_item)
        self.manager.notification.connect(self._show_notification)
        self.manager.active_count_changed.connect(lambda _: self._update_counts())
        self.manager.all_stopped.connect(self._on_all_stopped)

        self.sidebar.add_clicked.connect(self._add_download)
        self.sidebar.filter_changed.connect(self._on_filter_changed)
        self.sidebar.category_changed.connect(self._on_category_changed)
        self.sidebar.parallel_changed.connect(self._parallel_changed)

        self.search_edit.textChanged.connect(self._apply_filter)

    # ── Item management ──

    def _add_item(self, item: DownloadItem) -> None:
        if item.id in self._cards:
            self._update_item(item)
            return

        card = DownloadCard(item, self._card_container)
        apply_widget_theme(card, self._light_theme)
        card.set_light_theme(self._light_theme)
        card.clicked.connect(self._on_card_clicked)
        card.control_requested.connect(self._on_card_control)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, item_id=item.id: self._show_card_context_menu(item_id, pos, card)
        )
        self._cards[item.id] = card

        # Insert before the stretch at the end
        count = self._card_layout.count()
        self._card_layout.insertWidget(count - 1, card)

        self._apply_filter()
        self._update_counts()
        self._update_actions()

    def _update_item(self, item: DownloadItem) -> None:
        card = self._cards.get(item.id)
        if not card:
            self._add_item(item)
            return
        card.update_item(item)
        card.set_light_theme(self._light_theme)

        # Update inspector if this item is selected
        if self._selected_id == item.id:
            self.inspector.set_item(item)
            apply_widget_theme(self.inspector, self._light_theme)

        # Track global speed
        self._global_speed = sum(
            it.speed for it in self.manager.items()
            if it.status == DownloadStatus.DOWNLOADING and it.speed > 0
        )

        self._apply_filter()
        self._update_counts()
        self._update_actions()

    def _on_card_clicked(self, item_id: str) -> None:
        # Deselect previous
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)
            apply_widget_theme(self._cards[self._selected_id], self._light_theme)

        # Select new
        self._selected_id = item_id
        if item_id in self._cards:
            self._cards[item_id].set_selected(True)
            apply_widget_theme(self._cards[item_id], self._light_theme)

        item = self.manager.get(item_id)
        self.inspector.set_item(item)
        apply_widget_theme(self.inspector, self._light_theme)
        self._update_actions()

    def _show_card_context_menu(self, item_id: str, pos, card: QWidget | None = None) -> None:
        item = self.manager.get(item_id)
        if item is None:
            return
        anchor = card if card is not None else self
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open_item(item_id))
        menu.addAction("Show in folder", lambda: self._show_item_in_folder(item_id))
        menu.addAction("Rename", lambda: self._rename_item(item_id))
        menu.addSeparator()
        menu.addAction("Remove from list", lambda: self._remove_item_from_list(item_id))
        menu.addAction("Delete file", lambda: self._delete_item_file(item_id))
        menu.addSeparator()
        menu.addAction("Copy link", lambda: self._copy_item_link(item_id))
        menu.addAction("Move", lambda: self._move_item(item_id))
        if item.status in {
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSING,
            DownloadStatus.PAUSED,
        }:
            menu.addSeparator()
            menu.addAction("Cancel", lambda: self.manager.cancel(item_id))
        if item.status in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
            menu.addSeparator()
            menu.addAction("Retry", lambda: self.manager.retry(item_id))
        menu.exec_(anchor.mapToGlobal(pos))

    def _on_card_control(self, item_id: str, operation: str) -> None:
        if operation == "pause":
            self.manager.pause(item_id)
        elif operation == "resume":
            self.manager.resume(item_id)
        elif operation == "retry":
            self.manager.retry(item_id)

    # ── Filtering ──

    def _on_filter_changed(self, key: str) -> None:
        self._current_filter = key
        self._apply_filter()

    def _on_category_changed(self, category: str) -> None:
        self._current_category = category
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_edit.text().strip().lower() if hasattr(self, "search_edit") else ""

        for item_id, card in self._cards.items():
            item = self.manager.get(item_id)
            if not item:
                card.hide()
                continue
            card.setVisible(
                matches_download(item, query, self._current_filter, self._current_category)
            )

    # ── Counts & summary ──

    def _update_counts(self) -> None:
        items = self.manager.items()
        summary = summarize_downloads(items)
        self.sidebar.update_counts(
            summary.total,
            summary.active,
            summary.paused,
            summary.completed,
            summary.failed,
        )
        self._queue_stats.setText(summary.status_text)
        self.sidebar.update_categories(summary.categories)

    # ── Actions state ──

    def _update_actions(self) -> None:
        for name, enabled in available_queue_actions(self.manager.items()).items():
            btn = self._action_buttons.get(name)
            if btn:
                btn.setEnabled(enabled)

    def _remove_item(self, item_id: str) -> None:
        if self._selected_id == item_id:
            self._selected_id = None
            self.inspector.set_item(None)
        card = self._cards.pop(item_id, None)
        if card is not None:
            card.deleteLater()
        self._update_counts()
        self._update_actions()

    def _open_item(self, item_id: str) -> None:
        item = self.manager.get(item_id)
        if item is None:
            return
        path = Path(item.destination)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif Path(item.temp_path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.temp_path).parent)))
        else:
            self._show_item_in_folder(item_id)

    def _show_item_in_folder(self, item_id: str) -> None:
        item = self.manager.get(item_id)
        if item is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.folder))

    def _rename_item(self, item_id: str) -> None:
        item = self.manager.get(item_id)
        if item is None:
            return
        current_name = Path(item.destination).name if item.destination else Path(item.temp_path).name
        new_name, ok = QInputDialog.getText(
            self,
            "Rename file",
            "New file name:",
            text=current_name,
        )
        if not ok or not new_name.strip():
            return
        target_dir = Path(item.folder)
        candidate = target_dir / sanitize_filename(new_name.strip())
        if candidate.exists():
            stem = candidate.stem
            suffix = candidate.suffix
            index = 1
            while True:
                next_name = target_dir / f"{stem} ({index}){suffix}"
                if not next_name.exists():
                    candidate = next_name
                    break
                index += 1
        source = Path(item.destination)
        if not source.exists() and Path(item.temp_path).exists():
            source = Path(item.temp_path)
        if not source.exists():
            QMessageBox.warning(self, "Rename failed", "The file no longer exists.")
            return
        try:
            target = source.with_name(candidate.name)
            source.replace(target)
            if item.destination == str(source):
                item.destination = str(target)
            if Path(item.temp_path).exists() and Path(item.temp_path) != target:
                temp_target = target.with_name(f"{target.stem}.part{target.suffix}")
                Path(item.temp_path).replace(temp_target)
                item.temp_path = str(temp_target)
            elif item.temp_path == str(source):
                item.temp_path = str(target)
            item.updated_at = item.updated_at or ""
            self.manager.database.save(item)
            self.manager.item_updated.emit(item.copy())
        except OSError as error:
            QMessageBox.warning(self, "Rename failed", str(error))

    def _remove_item_from_list(self, item_id: str) -> None:
        self.manager.remove(item_id)

    def _delete_item_file(self, item_id: str) -> None:
        self.manager.remove(item_id, delete_file=True)

    def _copy_item_link(self, item_id: str) -> None:
        item = self.manager.get(item_id)
        if item is None:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(item.url, QClipboard.Mode.Clipboard)

    def _move_item(self, item_id: str) -> None:
        item = self.manager.get(item_id)
        if item is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Move file to folder", item.folder)
        if not folder:
            return
        source = Path(item.destination)
        if not source.exists() and Path(item.temp_path).exists():
            source = Path(item.temp_path)
        if not source.exists():
            QMessageBox.warning(self, "Move failed", "The file no longer exists.")
            return
        target_name = Path(item.destination).name if item.destination else Path(item.temp_path).name
        target_dir = Path(folder)
        target = target_dir / sanitize_filename(target_name)
        index = 1
        while target.exists():
            name = Path(target_name)
            target = target_dir / f"{name.stem} ({index}){name.suffix}"
            index += 1
        try:
            source.replace(target)
            if item.destination == str(source):
                item.destination = str(target)
            if item.temp_path and Path(item.temp_path).exists() and Path(item.temp_path) != target:
                temp_target = target.with_name(f"{target.stem}.part{target.suffix}")
                Path(item.temp_path).replace(temp_target)
                item.temp_path = str(temp_target)
            elif item.temp_path == str(source):
                item.temp_path = str(target)
            self.manager.database.save(item)
            self.manager.item_updated.emit(item.copy())
        except OSError as error:
            QMessageBox.warning(self, "Move failed", str(error))

    # ── Dialogs & navigation ──

    def _add_download(self) -> None:
        folder = self.settings.last_folder()
        if not folder or not Path(folder).is_dir():
            folder = str(default_download_dir())
        dialog = AddDownloadDialog(folder, self)
        apply_widget_theme(dialog, self._light_theme)
        if not dialog.exec():
            return
        url, folder, filename = dialog.values()
        if is_youtube_url(url):
            youtube_dialog = YouTubeDownloadDialog(url, folder, self, filename)
            apply_widget_theme(youtube_dialog, self._light_theme)
            if not youtube_dialog.exec():
                return
            try:
                values = youtube_dialog.values()
                item_id = self.manager.add_youtube_download(
                    values["url"],
                    values["folder"],
                    title=values["title"],
                    output_name=values["output_name"],
                    channel=values["channel"],
                    duration=values["duration"],
                    format_selector=values["format_selector"],
                    filename_extension=values["extension"],
                    estimated_size=values["estimated_size"],
                    audio_only=values["audio_only"],
                    audio_bitrate=values["audio_bitrate"],
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot add YouTube download", str(error))
                return
            self.settings.set_last_folder(values["folder"])
            return
        try:
            item_id = self.manager.add_download(url, folder, filename)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot add download", str(error))
            return
        self.settings.set_last_folder(folder)

    def handle_browser_download(self, url: str, socket: QLocalSocket) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        folder = self.settings.last_folder()
        if not folder or not Path(folder).is_dir():
            folder = str(default_download_dir())
        if is_youtube_url(url):
            dialog = YouTubeDownloadDialog(url, folder, self)
            apply_widget_theme(dialog, self._light_theme)
            if not dialog.exec():
                self._reply_browser(socket, False, "YouTube download cancelled.")
                return
            try:
                values = dialog.values()
                self.manager.add_youtube_download(
                    values["url"],
                    values["folder"],
                    title=values["title"],
                    output_name=values["output_name"],
                    channel=values["channel"],
                    duration=values["duration"],
                    format_selector=values["format_selector"],
                    filename_extension=values["extension"],
                    estimated_size=values["estimated_size"],
                    audio_only=values["audio_only"],
                    audio_bitrate=values["audio_bitrate"],
                    browser_origin=True,
                )
            except (OSError, ValueError) as error:
                self._reply_browser(socket, False, str(error))
                return
            self.settings.set_last_folder(values["folder"])
            self._reply_browser(socket, True, f"Added to LiteDM: {values['title']}")
            return
        try:
            item_id = self.manager.add_download(
                url,
                folder,
                filename_from_url(url),
                browser_origin=True,
            )
        except (OSError, ValueError) as error:
            self._reply_browser(socket, False, str(error))
            return
        self.settings.set_last_folder(folder)
        item = self.manager.get(item_id)
        name = item.filename if item else "Download"
        self.statusBar().showMessage(f"Added from browser: {name}", 5000)
        self._reply_browser(socket, True, f"Added to LiteDM: {name}")

    def handle_browser_status(self, socket: QLocalSocket) -> None:
        active_statuses = {
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSING,
            DownloadStatus.PAUSED,
            DownloadStatus.CANCELLING,
        }
        downloads = [
            {
                "id": item.id,
                "name": item.filename,
                "status": item.status.value,
                "downloaded_bytes": item.downloaded_bytes,
                "total_bytes": item.total_bytes,
                "speed": item.speed,
            }
            for item in self.manager.items()
            if item.status in active_statuses
        ][:100]
        browser_server = getattr(self, "browser_server", None)
        if browser_server is not None:
            browser_server.reply_payload(
                socket,
                {
                    "ok": True,
                    "controls_supported": True,
                    "downloads": downloads,
                },
            )

    def handle_browser_youtube_formats(self, url: str, socket: QLocalSocket) -> None:
        worker = MetadataWorker(url, self)
        self._browser_youtube_workers.add(worker)
        worker.loaded.connect(
            lambda info, request_url=url, client=socket:
                self._browser_youtube_metadata_loaded(request_url, client, info)
        )
        worker.failed.connect(
            lambda error, client=socket: self._reply_browser(client, False, error)
        )
        worker.finished.connect(self._release_browser_youtube_worker)
        worker.start()

    def _browser_youtube_metadata_loaded(
        self,
        url: str,
        socket: QLocalSocket,
        info: dict,
    ) -> None:
        choices = format_choices(info)
        if not choices:
            self._reply_browser(
                socket,
                False,
                "No supported MP4 video formats with usable size information were found.",
            )
            return
        video_token = secrets.token_hex(16)
        choice_ids = [secrets.token_hex(16) for _ in choices]
        self._browser_youtube_sessions[video_token] = {
            "expires_at": time.monotonic() + 3600,
            "url": url,
            "info": info,
            "choices": dict(zip(choice_ids, choices, strict=True)),
        }
        self._prune_browser_youtube_sessions()
        self._reply_browser_payload(
            socket,
            {
                "ok": True,
                "video_token": video_token,
                "formats": [
                    {"id": choice_id, "label": choice["label"]}
                    for choice_id, choice in zip(choice_ids, choices, strict=True)
                ],
            },
        )

    def _prune_browser_youtube_sessions(self) -> None:
        now = time.monotonic()
        self._browser_youtube_sessions = {
            token: session
            for token, session in self._browser_youtube_sessions.items()
            if session["expires_at"] > now
        }
        if len(self._browser_youtube_sessions) > 32:
            oldest = sorted(
                self._browser_youtube_sessions,
                key=lambda token: self._browser_youtube_sessions[token]["expires_at"],
            )
            for token in oldest[: len(self._browser_youtube_sessions) - 32]:
                self._browser_youtube_sessions.pop(token, None)

    def _release_browser_youtube_worker(self) -> None:
        worker = self.sender()
        if isinstance(worker, MetadataWorker):
            self._browser_youtube_workers.discard(worker)
            worker.deleteLater()

    def handle_browser_youtube_add(
        self,
        video_token: str,
        choice_id: str,
        socket: QLocalSocket,
    ) -> None:
        self._prune_browser_youtube_sessions()
        session = self._browser_youtube_sessions.get(video_token)
        choice = session["choices"].get(choice_id) if session else None
        if not session or not choice:
            self._reply_browser(
                socket,
                False,
                "That format selection expired. Reopen the video format menu and try again.",
            )
            return
        self._browser_youtube_sessions.pop(video_token, None)
        info = session["info"]
        folder = self.settings.last_folder()
        if not folder or not Path(folder).is_dir():
            folder = str(default_download_dir())
        title = str(info.get("title") or "youtube-video")
        try:
            item_id = self.manager.add_youtube_download(
                session["url"],
                folder,
                title=title,
                output_name=title,
                channel=str(info.get("channel") or info.get("uploader") or ""),
                duration=int(info.get("duration") or 0),
                format_selector=str(choice["format_id"]),
                filename_extension=str(choice.get("extension") or "mp4"),
                estimated_size=int(choice["size"]),
                audio_only=False,
                browser_origin=True,
            )
        except (OSError, TypeError, ValueError) as error:
            self._reply_browser(socket, False, str(error))
            return
        self.settings.set_last_folder(folder)
        item = self.manager.get(item_id)
        self._reply_browser(
            socket,
            True,
            f"Added to LiteDM: {item.filename if item else title}",
        )

    def handle_browser_control(
        self,
        item_id: str,
        operation: str,
        socket: QLocalSocket,
    ) -> None:
        item = self.manager.get(item_id)
        if item is None:
            self._reply_browser(socket, False, "That download no longer exists.")
            return
        if operation == "pause" and item.status in {
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
        }:
            self.manager.pause(item_id)
        elif operation == "resume" and item.status == DownloadStatus.PAUSED:
            self.manager.resume(item_id)
        else:
            self._reply_browser(
                socket,
                False,
                f"Cannot {operation} a download that is {item.status.value}.",
            )
            return
        self._reply_browser(socket, True, f"Download {operation} requested.")

    def _reply_browser(self, socket: QLocalSocket, success: bool, message: str) -> None:
        self._reply_browser_payload(socket, {"ok": success, "message": message})

    def _reply_browser_payload(self, socket: QLocalSocket, payload: dict) -> None:
        browser_server = getattr(self, "browser_server", None)
        if browser_server is not None:
            browser_server.reply_payload(socket, payload)

    def _update_theme_button(self) -> None:
        self.theme_button.setText("☀ Light" if not self._light_theme else "☾ Dark")
        self.theme_button.setToolTip(
            "Switch to light theme" if not self._light_theme else "Switch to dark theme"
        )

    def _toggle_theme(self) -> None:
        self._light_theme = not self._light_theme
        self.settings.set_theme(self._light_theme)
        application = QApplication.instance()
        if application:
            apply_application_theme(application, self._light_theme)
        apply_widget_theme(self, self._light_theme)
        for card in self._cards.values():
            card.set_light_theme(self._light_theme)
        self.sidebar.set_light_theme(self._light_theme)
        self._update_theme_button()

    def _parallel_changed(self, value: int) -> None:
        self.manager.set_max_concurrent(value)
        self.settings.set_max_concurrent(value)

    # ── Speed tracking ──

    def _push_speed_sample(self) -> None:
        self.sidebar.update_speed(self._global_speed)

    # ── Notifications ──

    def _show_notification(self, message: str, level: str) -> None:
        self.statusBar().showMessage(message, 10000 if level == "error" else 5000)
        if self._selected_id:
            item = self.manager.get(self._selected_id)
            self.inspector.set_item(item)

    # ── Close handling ──

    def _on_all_stopped(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self._close_allowed = True
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.manager.has_active_workers() and not self._close_allowed:
            event.ignore()
            self._close_pending = True
            self.manager.shutdown()
            return
        self.settings.set_geometry(self.saveGeometry())
        self.settings.sync()
        event.accept()

    # ── Test helpers (backward compat) ──

    @property
    def parallel_spin(self):
        return self.sidebar.parallel_spin

    def card_count(self) -> int:
        return len(self._cards)

    def visible_card_count(self) -> int:
        return sum(1 for card in self._cards.values() if card.isVisible())
