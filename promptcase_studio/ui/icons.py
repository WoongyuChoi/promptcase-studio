from __future__ import annotations

from math import cos, pi, sin

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _gear_path() -> QPainterPath:
    center = QPointF(16, 16)
    points = QPolygonF()
    for index in range(32):
        angle = (-pi / 2) + (index * 2 * pi / 32)
        radius = 12 if index % 4 in (1, 2) else 9.5
        points.append(
            QPointF(
                center.x() + cos(angle) * radius,
                center.y() + sin(angle) * radius,
            )
        )
    path = QPainterPath()
    path.addPolygon(points)
    path.closeSubpath()
    path.addEllipse(center, 4.2, 4.2)
    path.setFillRule(Qt.OddEvenFill)
    return path


def _draw_icon(name: str, color: str, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / 32, size / 32)
    icon_color = QColor(color)

    if name == "settings":
        painter.fillPath(_gear_path(), icon_color)
    elif name == "download":
        pen = QPen(icon_color, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(16, 6.5), QPointF(16, 20.5))
        arrow = QPainterPath(QPointF(10.5, 15.5))
        arrow.lineTo(16, 21)
        arrow.lineTo(21.5, 15.5)
        painter.drawPath(arrow)
        tray = QPainterPath(QPointF(7.5, 22))
        tray.lineTo(7.5, 25)
        tray.lineTo(24.5, 25)
        tray.lineTo(24.5, 22)
        painter.drawPath(tray)
    else:
        painter.end()
        raise ValueError(f"지원하지 않는 아이콘: {name}")

    painter.end()
    return pixmap


def interface_icon(name: str, color: str = "#526174") -> QIcon:
    icon = QIcon()
    icon.addPixmap(_draw_icon(name, color, 16))
    icon.addPixmap(_draw_icon(name, color, 32))
    return icon
