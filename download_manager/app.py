from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .browser_ipc import BrowserIpcServer
from .browser_native_host import register_browser_native_host
from .database import DownloadDatabase
from .logging import configure_logging
from .settings import AppSettings
from .manager import DownloadManager
from .ui.main_window import MainWindow, apply_theme
from .utils import app_icon_path, default_data_dir


def normalize_max_concurrent(value: object, default: int = 3) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(1, min(8, default))
    return max(1, min(8, parsed))


def main(argv: list[str] | None = None) -> int:
    logger = configure_logging()
    parser = argparse.ArgumentParser(prog="litetdm", description="Lightweight Linux download manager")
    parser.add_argument("--version", action="version", version=f"LiteDM {__version__}")
    parser.add_argument("--data-dir", type=Path, help="Override the SQLite history directory")
    args = parser.parse_args(argv)
    logger.info("Starting LiteDM %s", __version__)
    try:
        register_browser_native_host()
    except (OSError, ValueError, KeyError):
        logger.exception("Could not automatically register the LiteDM browser extension")
    application = QApplication([sys.argv[0]])
    application.setApplicationName("LiteDM")
    application.setApplicationDisplayName("LiteDM")
    application.setOrganizationName("LiteDM")
    application.setApplicationVersion(__version__)
    application.setDesktopFileName("litetdm")
    application.setWindowIcon(QIcon(str(app_icon_path())))
    settings = AppSettings()
    light_theme = settings.is_light_theme()
    apply_theme(application, light_theme)
    data_dir = args.data_dir.expanduser().resolve() if args.data_dir else default_data_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        database = DownloadDatabase(data_dir / "downloads.db")
    except OSError as error:
        logger.exception("Could not initialize the history database")
        QMessageBox.critical(None, "LiteDM startup error", str(error))
        return 1
    max_concurrent = settings.max_concurrent()
    logger.info("Using %s concurrent workers", max_concurrent)
    manager = DownloadManager(database, max_concurrent=max_concurrent)
    window = MainWindow(manager, settings)
    browser_server = BrowserIpcServer()
    try:
        browser_server.listen()
    except OSError:
        logger.exception("Browser extension integration could not be started")
    else:
        browser_server.download_requested.connect(window.handle_browser_download)
        browser_server.status_requested.connect(window.handle_browser_status)
        browser_server.control_requested.connect(window.handle_browser_control)
        browser_server.youtube_formats_requested.connect(
            window.handle_browser_youtube_formats
        )
        browser_server.youtube_add_requested.connect(window.handle_browser_youtube_add)
        window.browser_server = browser_server
    window.show()
    manager.start()
    exit_code = application.exec()
    browser_server.close()
    return exit_code
