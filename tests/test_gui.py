from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, QSize
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialog, QToolTip

from download_manager.database import DownloadDatabase
from download_manager.manager import DownloadManager
from download_manager.models import DownloadStatus
from download_manager.ui.add_dialog import AddDownloadDialog
from download_manager.ui.main_window import MainWindow


def test_main_window_controls_and_filter(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    item_id = manager.add_download("https://example.com/sample-file.bin", str(tmp_path), "sample.bin")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(manager, settings)
    window.show()
    application.processEvents()
    assert window.card_count() == 1
    assert window._cards[item_id].height() == 78
    assert not hasattr(window._cards[item_id], "_threads_label")
    assert window.sidebar.width() == 190
    assert set(window._action_buttons) == {"Pause All", "Resume All"}
    # Select the card
    window._on_card_clicked(item_id)
    application.processEvents()
    card_control = window._cards[item_id]._control_button
    assert card_control.text() == "Ⅱ"
    card_control.click()
    application.processEvents()
    assert manager.get(item_id).status == DownloadStatus.PAUSED
    assert card_control.text() == "▶"
    assert window.resume_all_action.isEnabled()
    window.theme_button.click()
    card = window._cards[item_id]
    downloading_item = manager.get(item_id)
    downloading_item.status = DownloadStatus.DOWNLOADING
    downloading_item.total_bytes = -1
    card.update_item(downloading_item)
    assert card._progress._track_color.name() == "#e2e8f0"
    assert card._progress._marquee_timer.isActive()
    assert card._progress.minimum() == 0 and card._progress.maximum() == 0
    cancelled_item = manager.get(item_id)
    cancelled_item.status = DownloadStatus.CANCELLED
    card.update_item(cancelled_item)
    retry_requests = []
    card.control_requested.connect(lambda requested_id, operation: retry_requests.append((requested_id, operation)))
    assert card._control_button.isVisible()
    assert card._control_button.text() == "↻"
    hover_background, hover_foreground, _ = card._control_button.colors(True, False, True)
    assert hover_background.name() == "#ffffff"
    assert hover_foreground.name() == "#0f172a"
    card._control_button.click()
    assert retry_requests == [(item_id, "retry")]
    window.parallel_spin.setValue(2)
    assert manager.max_concurrent == 2
    window.search_edit.setText("no-match")
    application.processEvents()
    assert window.visible_card_count() == 0
    window.search_edit.clear()
    application.processEvents()
    assert window.visible_card_count() == 1
    window.close()
    application.processEvents()
    assert not window.isVisible()


def test_completed_download_card_shows_completion_time(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    item_id = manager.add_download(
        "https://example.com/image.jpg",
        str(tmp_path),
        "image.jpg",
    )
    item = manager.get(item_id)
    item.status = DownloadStatus.COMPLETED
    item.completed_at = "2026-10-26T18:04:05+00:00"
    window = MainWindow(manager, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    window._cards[item_id].update_item(item)

    timestamp = window._cards[item_id]._completed_at_label

    assert not timestamp.isHidden()
    assert timestamp.text().startswith("Downloaded ")
    assert timestamp.toolTip().startswith("Completed ")
    window.close()


def test_youtube_progress_does_not_show_complete_before_finalization(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "youtube-progress.db"))
    item_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="Video title",
        channel="Example channel",
        duration=90,
        format_selector="22",
        filename_extension="mp4",
        estimated_size=100,
    )
    item = manager.get(item_id)
    assert item is not None
    item.status = DownloadStatus.DOWNLOADING
    item.downloaded_bytes = 100
    item.total_bytes = 100
    window = MainWindow(
        manager,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )

    card = window._cards[item_id]
    card.update_item(item)

    assert card._pct_label.text() == "99.9%"
    assert card._progress.value() == 9990
    window.close()


def test_youtube_progress_card_shows_aggregated_stream_size(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "youtube-stream-progress.db"))
    item_id = manager.add_youtube_download(
        "https://youtu.be/example",
        str(tmp_path),
        title="Video title",
        channel="Example channel",
        duration=90,
        format_selector="bestvideo+bestaudio",
        filename_extension="mp4",
        estimated_size=8_900_000,
    )
    item = manager.get(item_id)
    assert item is not None
    item.status = DownloadStatus.DOWNLOADING
    item.downloaded_bytes = 121_700_000
    item.total_bytes = 356_200_000
    window = MainWindow(
        manager,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )

    card = window._cards[item_id]
    card.update_item(item)

    assert card._pct_label.text() == "34.2%"
    assert card._progress.value() == 3416
    assert card._size_label.text() == "116.1 MB / 339.7 MB"
    window.close()
def test_theme_toggle_persists_and_restores_colors(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(manager, settings)
    window.sidebar.update_categories({"Archives": 1})

    assert window.theme_button.text() == "☀ Light"
    assert "#0b1018" in window.styleSheet()

    window.theme_button.click()
    assert settings.value("appearance/theme") == "light"
    assert window.theme_button.text() == "☾ Dark"
    assert "#f3f6fa" in window.styleSheet()
    assert "QMenu" in application.styleSheet()
    assert "background: #fdfefe; color: #1f2937" in application.styleSheet()
    assert "QMenu::item:selected { background: #dbeafe" in application.styleSheet()
    assert QToolTip.palette().color(QPalette.ColorRole.ToolTipBase) == QColor("#ffffff")
    assert QToolTip.palette().color(QPalette.ColorRole.ToolTipText) == QColor("#1f2937")
    assert "QToolTip" in application.styleSheet()
    assert "background-color: #ffffff" in application.styleSheet()
    category_button = window.sidebar._category_buttons[0]
    active_filter = window.sidebar._filters["active"]
    assert "#475569" in category_button.styleSheet()
    assert "QPushButton:hover { color: #0f172a; background: #eaf1f8; }" in active_filter.styleSheet()
    assert "QPushButton:hover { color: #0f172a; }" in category_button.styleSheet()
    assert "background: #dbeafe; color: #0e7490" in window.sidebar._add_btn.styleSheet()
    assert "background: #bfdbfe; color: #0f172a" in window.sidebar._add_btn.styleSheet()
    assert not window.sidebar._reset_cat._active
    active_filter.click()
    assert "#dbeafe" in active_filter.styleSheet()
    assert "color: #0e7490" in active_filter.styleSheet()
    window.sidebar._filters["all"].click()
    assert "#dbeafe" in window.sidebar._filters["all"].styleSheet()

    window.theme_button.click()
    assert settings.value("appearance/theme") == "dark"
    assert window.theme_button.text() == "☀ Light"
    assert "#0b1018" in window.styleSheet()
    assert QToolTip.palette().color(QPalette.ColorRole.ToolTipBase) == QColor("#1e2d40")
    assert QToolTip.palette().color(QPalette.ColorRole.ToolTipText) == QColor("#e5e7eb")
    assert "#5a6a7e" in category_button.styleSheet()
    assert "background: #0e7490; color: #e5e7eb" in window.sidebar._add_btn.styleSheet()
    active_filter.click()
    assert "#122236" in active_filter.styleSheet()
    window.close()


def test_card_control_uses_light_popup_tooltip(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    item_id = manager.add_download("https://example.com/sample-file.bin", str(tmp_path), "sample.bin")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(manager, settings)
    window.theme_button.click()
    button = window._cards[item_id]._control_button
    button._show_hint()
    application.processEvents()

    assert button._hint.isVisible()
    assert button._hint.text() == "Pause download"
    assert "background-color: #ffffff; color: #1f2937" in button._hint.styleSheet()
    button._hint.hide()
    window.close()


def test_folder_path_uses_theme_aware_popup(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    item_id = manager.add_download("https://example.com/sample-file.bin", str(tmp_path), "sample-file.bin")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(manager, settings)
    card = window._cards[item_id]

    assert card._folder_hint._text == str(tmp_path)
    assert card._folder_label.toolTip() == ""
    window.theme_button.click()
    card._folder_hint._apply_style()
    assert "background-color: #ffffff; color: #1f2937" in card._folder_hint._popup.styleSheet()

    window.theme_button.click()
    card._folder_hint._apply_style()
    assert "background-color: #1e2d40; color: #e5e7eb" in card._folder_hint._popup.styleSheet()
    window.close()


def test_card_control_tooltip_position_flips_and_stays_inside_bounds():
    from download_manager.ui.download_card import _CardControlButton

    bounds = QRect(100, 100, 500, 300)
    position = _CardControlButton._hint_position(
        QPoint(560, 360),
        QSize(30, 30),
        QSize(120, 32),
        bounds,
    )
    hint_rect = QRect(position, QSize(120, 32))
    assert bounds.contains(hint_rect)
    assert position.x() < 560
    assert position.y() + 32 <= 360

    above_position = _CardControlButton._hint_position(
        QPoint(300, 105),
        QSize(30, 30),
        QSize(120, 32),
        bounds,
    )
    assert above_position.y() > 105
    assert above_position.x() < 300
    assert bounds.contains(QRect(above_position, QSize(120, 32)))


def test_add_download_dialog_accepts_url_folder_and_filename(application, tmp_path: Path):
    dialog = AddDownloadDialog(str(tmp_path))
    dialog.url_edit.setText("https://example.com/example.iso")
    dialog.filename_edit.setText("custom.iso")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values() == ("https://example.com/example.iso", str(tmp_path), "custom.iso")
    dialog.close()
