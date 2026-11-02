from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

DEFAULT_THEME = "dark"
DEFAULT_MAX_CONCURRENT = 3
MIN_MAX_CONCURRENT = 1
MAX_MAX_CONCURRENT = 8


class AppSettings:
    def __init__(self, organization: str = "LiteDM", application: str = "LiteDM", settings: QSettings | None = None):
        self._settings = settings or QSettings(organization, application)

    @property
    def raw(self) -> QSettings:
        return self._settings

    def sync(self) -> None:
        self._settings.sync()

    def is_light_theme(self) -> bool:
        return self._settings.value("appearance/theme", DEFAULT_THEME) == "light"

    def set_theme(self, light: bool) -> None:
        self._settings.setValue("appearance/theme", "light" if light else DEFAULT_THEME)
        self._settings.sync()

    def max_concurrent(self) -> int:
        try:
            value = int(self._settings.value("downloads/maxConcurrent", DEFAULT_MAX_CONCURRENT))
        except (TypeError, ValueError):
            value = DEFAULT_MAX_CONCURRENT
        return max(MIN_MAX_CONCURRENT, min(MAX_MAX_CONCURRENT, value))

    def set_max_concurrent(self, value: int) -> None:
        clamped = max(MIN_MAX_CONCURRENT, min(MAX_MAX_CONCURRENT, int(value)))
        self._settings.setValue("downloads/maxConcurrent", clamped)
        self._settings.sync()

    def last_folder(self) -> str:
        return str(self._settings.value("downloads/lastFolder", "") or "")

    def set_last_folder(self, folder: str) -> None:
        self._settings.setValue("downloads/lastFolder", folder)
        self._settings.sync()

    def geometry(self) -> QByteArray | None:
        return self._settings.value("window/geometry")

    def set_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)
        self._settings.sync()
