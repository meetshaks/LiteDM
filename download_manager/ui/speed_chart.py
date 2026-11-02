from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .theme import ACCENT, BG_CONTENT


class SpeedChart(QWidget):
    """Tiny sparkline showing recent download speed history."""

    MAX_SAMPLES = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: deque[float] = deque(maxlen=self.MAX_SAMPLES)
        self.setMinimumSize(140, 40)
        self.setMaximumHeight(50)

    def add_sample(self, speed: float) -> None:
        self._samples.append(max(0.0, speed))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if len(self._samples) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_bottom = 2
        margin_top = 4
        draw_h = h - margin_top - margin_bottom

        peak = max(self._samples) or 1.0
        n = len(self._samples)
        step = w / max(n - 1, 1)

        # Build the line path
        path = QPainterPath()
        points: list[QPointF] = []
        for i, val in enumerate(self._samples):
            x = i * step
            y = margin_top + draw_h * (1.0 - val / peak)
            points.append(QPointF(x, y))

        path.moveTo(points[0])
        for pt in points[1:]:
            path.lineTo(pt)

        # Draw filled area
        fill_path = QPainterPath(path)
        fill_path.lineTo(QPointF(points[-1].x(), h))
        fill_path.lineTo(QPointF(points[0].x(), h))
        fill_path.closeSubpath()

        gradient = QLinearGradient(0, 0, 0, h)
        accent = QColor(ACCENT)
        accent.setAlpha(60)
        gradient.setColorAt(0.0, accent)
        bg = QColor(BG_CONTENT)
        bg.setAlpha(0)
        gradient.setColorAt(1.0, bg)
        painter.fillPath(fill_path, gradient)

        # Draw the line
        pen = QPen(QColor(ACCENT), 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

        painter.end()

