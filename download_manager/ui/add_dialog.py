from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..utils import ensure_directory, validate_url
from .theme import ACCENT, ACCENT_DARK, BG_CARD, BG_SIDEBAR, BORDER, TEXT_MUTED, TEXT_PRIMARY


class AddDownloadDialog(QDialog):
    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add download")
        self.setMinimumWidth(520)
        self.setStyleSheet(
            f"QDialog {{ background: {BG_SIDEBAR}; color: {TEXT_PRIMARY}; }}"
        )

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/file.iso")
        self.url_edit.setClearButtonEnabled(True)

        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("Automatic from URL")
        self.filename_edit.setClearButtonEnabled(True)

        self.folder_edit = QLineEdit(folder)
        browse_button = QPushButton("Browse…")
        browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_button.clicked.connect(self._browse)

        folder_widget = QWidget()
        folder_layout = QHBoxLayout(folder_widget)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(browse_button)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Download URL", self.url_edit)
        form.addRow("Save to folder", folder_widget)
        form.addRow("File name (optional)", self.filename_edit)

        note = QLabel("Existing files are never replaced; a numbered name is chosen automatically.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Start download")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_DARK}; border: 1px solid {ACCENT};"
            f" border-radius: 6px; color: {TEXT_PRIMARY}; font-weight: 600;"
            f" padding: 8px 18px; }}"
            f"QPushButton:hover {{ background: {ACCENT}; color: #0b1018; }}"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.url_edit.setFocus()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def accept(self) -> None:
        try:
            validate_url(self.url_edit.text())
            folder = ensure_directory(self.folder_edit.text())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot add download", str(error))
            return
        self.folder_edit.setText(str(folder))
        super().accept()

    def values(self) -> tuple[str, str, str]:
        return self.url_edit.text().strip(), self.folder_edit.text().strip(), self.filename_edit.text().strip()
