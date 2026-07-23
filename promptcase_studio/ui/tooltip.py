from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _TooltipArrow(QWidget):
    """Left-facing pointer joined to the tooltip card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 14)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        points = QPolygon(
            [
                QPoint(0, self.height() // 2),
                QPoint(self.width(), 1),
                QPoint(self.width(), self.height() - 1),
            ]
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon(points)
        painter.setPen(QPen(QColor("#1F2937"), 1))
        painter.drawLine(points[0], points[1])
        painter.drawLine(points[0], points[2])


class TooltipBubble(QWidget):
    """Rounded white tooltip with a left pointer and drop shadow."""

    CARD_WIDTH = 300
    OUTER_MARGIN = 8

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(
            parent,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.arrow = _TooltipArrow()
        self.card = QFrame()
        self.card.setObjectName("tooltipCard")
        self.card.setFixedWidth(self.CARD_WIDTH)
        self.seam = QWidget(self)
        self.seam.setObjectName("tooltipSeam")
        self.seam.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        title_label = QLabel(title)
        title_label.setObjectName("tooltipTitle")
        title_label.setWordWrap(True)
        body_label = QLabel(body)
        body_label.setObjectName("tooltipBody")
        body_label.setWordWrap(True)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)
        card_layout.addWidget(title_label)
        card_layout.addWidget(body_label)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(14)
        shadow.setOffset(4, 8)
        shadow.setColor(QColor(0, 0, 0, 38))
        self.card.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            self.OUTER_MARGIN,
            self.OUTER_MARGIN,
            self.OUTER_MARGIN + 12,
            self.OUTER_MARGIN + 12,
        )
        layout.setSpacing(0)
        layout.addWidget(self.arrow, 0, Qt.AlignVCenter)
        layout.addWidget(self.card)
        self.ensurePolished()
        layout.activate()
        self.adjustSize()
        self._position_seam()

    def _position_seam(self) -> None:
        if not self.arrow.geometry().isValid() or not self.card.geometry().isValid():
            return
        center_y = self.arrow.geometry().center().y()
        self.seam.setGeometry(self.card.geometry().left() - 1, center_y - 5, 3, 10)
        self.seam.raise_()
        self.arrow.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_seam()

    def show_at(self, anchor: QPoint) -> None:
        self.ensurePolished()
        self.layout().activate()
        self.adjustSize()
        self._position_seam()

        arrow_center = self.arrow.mapTo(self, self.arrow.rect().center())
        target_x = anchor.x() + 4 - arrow_center.x()
        target_y = anchor.y() - arrow_center.y()

        screen = QApplication.screenAt(anchor)
        if screen is not None:
            available = screen.availableGeometry()
            target_x = min(target_x, available.right() - self.width())
            target_x = max(target_x, available.left())
            target_y = min(target_y, available.bottom() - self.height())
            target_y = max(target_y, available.top())

        self.move(target_x, target_y)
        self.show()
        self.raise_()


class HelpTooltipButton(QToolButton):
    """Compact help icon that owns a consistent custom tooltip."""

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.tooltip_title = title
        self.tooltip_body = body
        self._bubble: TooltipBubble | None = None
        self.setText("?")
        self.setObjectName("helpBadge")
        self.setToolTip(body)
        self.setStatusTip(body)
        self.setAccessibleName(f"{title} 도움말")
        self.setAccessibleDescription(body)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(12, 12)
        self.clicked.connect(self.show_bubble)

    def set_help_content(self, title: str, body: str) -> None:
        self.tooltip_title = title
        self.tooltip_body = body
        self.setToolTip(body)
        self.setStatusTip(body)
        self.setAccessibleName(f"{title} 도움말")
        self.setAccessibleDescription(body)
        if self._bubble is not None:
            self._bubble.hide()
            self._bubble.deleteLater()
            self._bubble = None

    def _ensure_bubble(self) -> TooltipBubble:
        if self._bubble is None:
            self._bubble = TooltipBubble(
                self.tooltip_title,
                self.tooltip_body,
                self.window(),
            )
        return self._bubble

    def show_bubble(self) -> None:
        anchor = self.mapToGlobal(QPoint(self.width(), self.height() // 2))
        self._ensure_bubble().show_at(anchor)

    def hide_bubble(self) -> None:
        if self._bubble is not None:
            self._bubble.hide()

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            self.show_bubble()
            return True
        return super().event(event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.show_bubble()

    def leaveEvent(self, event) -> None:
        self.hide_bubble()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.show_bubble()

    def focusOutEvent(self, event) -> None:
        self.hide_bubble()
        super().focusOutEvent(event)
