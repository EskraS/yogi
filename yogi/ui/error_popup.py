"""Red error toast at the top of the Yogi window. Click to dismiss."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

MAX_MESSAGES = 3
SHOW_MS = 2000
TOP_MARGIN = 12
SIDE_MARGIN = 40


class ErrorPopup(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._messages = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "background-color: #dc2626; color: #ffffff; border-radius: 8px;"
            " padding: 10px 18px; font-family: Inter; font-size: 13px; font-weight: 600;"
            " border: none;"
        )
        layout.addWidget(self._label)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def show_message(self, message: str):
        if message in self._messages:
            self._messages.remove(message)
        self._messages.append(message)
        self._messages = self._messages[-MAX_MESSAGES:]
        self._label.setText("\n\n".join(self._messages))
        self._label.setMaximumWidth(max(200, self.parent().width() - SIDE_MARGIN * 2))
        self._label.adjustSize()
        self.adjustSize()
        x = (self.parent().width() - self.width()) // 2
        self.move(x, TOP_MARGIN)
        self.raise_()
        self.show()
        self._timer.start(SHOW_MS)

    def dismiss(self):
        self._timer.stop()
        self._messages = []
        self.hide()

    def mousePressEvent(self, event):
        self.dismiss()
        event.accept()
