from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QLineEdit,
    QLabel,
    QComboBox,
    QSlider,
    QPushButton,
    QGraphicsOpacityEffect,
    QDialog,
    QFileDialog,
    QPlainTextEdit,
    QMessageBox,
    QFrame,
    QStyledItemDelegate,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QSizePolicy,
)
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import (
    Qt,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QElapsedTimer,
    QSettings,
    QSize,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
    QTimer,
    Property,
    Signal,
)
import json
import os
import threading

import qtawesome as qta
import requests

from yogi.core import key_store
from yogi.audio import vocal
from yogi.audio.devices import (
    DEFAULT_SPEECH_THRESHOLD,
    MAX_SPEECH_THRESHOLD,
    MIN_SPEECH_THRESHOLD,
    list_input_devices,
    list_output_devices,
    set_input_device,
    set_output_device,
    set_speech_threshold,
)
from yogi.audio.mic_threshold import MicLevelMonitor, MicThresholdSlider, level_to_db_text
from yogi.audio.stt import FOLLOWUP_WINDOW_S
from yogi.ui.theme_helpers import (
    ACCENT_GREEN,
    scrollbar_stylesheet,
    line_edit_stylesheet,
    combo_stylesheet,
    slider_stylesheet,
)

SHIFT_SYMBOL_MAP = {
    "1": "!",
    "2": "@",
    "3": "#",
    "4": "$",
    "5": "%",
    "6": "^",
    "7": "&",
    "8": "*",
    "9": "(",
    "0": ")",
    "`": "~",
    "-": "_",
    "=": "+",
    "[": "{",
    "]": "}",
    "\\": "|",
    ";": ":",
    "'": '"',
    ",": "<",
    ".": ">",
    "/": "?",
}

# Qt may report Key_Dollar, Key_Exclam, etc. when Shift+digit; show the digit in the hotkey label.


def theme_palette(name: str) -> dict:
    if name == "light":
        return {
            "window_bg": "#f4f4f5",
            "card_bg": "#ffffff",
            "card_border": "#e4e4e7",
            "section_title": "#52525b",
            "dim_text": "#71717a",
            "mid_text": "#3f3f46",
            "input_bg": "#fafafa",
            "input_border": "#d4d4d8",
            "input_text": "#3f3f46",
            "scroll_handle": "#cbd5e1",
            "scroll_handle_hover": "#94a3b8",
            "slider_groove": "#e4e4e7",
            "slider_track_rest": "#e5e5e5",
            "slider_handle": "#9ca3af",
            "slider_handle_hover": "#71717a",
            "icon_color": "#71717a",
            "chip_bg": "#ffffff",
            "chip_sel_bg": "#f4f4f5",
            "chip_unsel_border": "#d4d4d8",
            "chip_unsel_text": "#71717a",
        }
    return {
        "window_bg": "#1e1e1e",
        "card_bg": "#252525",
        "card_border": "#333333",
        "section_title": "#A1A1A1",
        "dim_text": "#707070",
        "mid_text": "#A1A1A1",
        "input_bg": "#1e1e1e",
        "input_border": "#333333",
        "input_text": "#A1A1A1",
        "scroll_handle": "#9ca3af",
        "scroll_handle_hover": "#b4bcc8",
        "slider_groove": "#333333",
        "slider_track_rest": "#3a3a3a",
        "slider_handle": "#ffffff",
        "slider_handle_hover": "#b3b3b3",
        "icon_color": "#aaaaaa",
        "chip_bg": "#252525",
        "chip_sel_bg": "#2a2a2a",
        "chip_unsel_border": "#444444",
        "chip_unsel_text": "#888888",
    }


_SHIFT_NUMBER_ROW_KEY_TO_DIGIT = {
    "Exclam": "1",
    "At": "2",
    "NumberSign": "3",
    "Dollar": "4",
    "Percent": "5",
    "AsciiCircum": "6",
    "Ampersand": "7",
    "Asterisk": "8",
    "ParenLeft": "9",
    "ParenRight": "0",
}


_RECORD_GREEN = QColor(0x22, 0xC5, 0x5E)

# "Record" / "Recording..." label - change these to adjust color and size.
_RECORD_LABEL_RECORDING_COLOR = QColor("#ffffff")
_RECORD_LABEL_FONT_PT = 10

# Theme-aware hover fill and idle label colours for the painted buttons below.
_BTN_TOKENS = {
    "light": {"hover": QColor(236, 236, 236), "idle_label": QColor("#52525b"), "icon": "#71717a"},
    "dark": {"hover": QColor(58, 58, 58), "idle_label": QColor("#aaaaaa"), "icon": "#aaaaaa"},
}


class RecordButton(QWidget):
    clicked = Signal()

    def __init__(self, text="Record", parent=None):
        super().__init__(parent)

        self._text = text
        self._hover_t = 0.0
        self._recording = False
        self._pressed = False
        self._theme = "dark"

        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

        self.anim = QPropertyAnimation(self, b"hover_t")
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def get_hover_t(self):
        return self._hover_t

    def set_hover_t(self, t):
        self._hover_t = max(0.0, min(1.0, float(t)))
        self.update()

    hover_t = Property(float, get_hover_t, set_hover_t)

    def setRecording(self, recording: bool):
        self._recording = bool(recording)
        self.anim.stop()
        self._hover_t = 0.0
        if self.underMouse():
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.start()
        self.update()

    def isRecording(self):
        return self._recording

    def setText(self, text):
        self._text = text
        self.update()

    def text(self):
        return self._text

    def set_theme(self, theme: str):
        self._theme = theme if theme in _BTN_TOKENS else "dark"
        self.update()

    def _hover_rgb(self):
        c = _BTN_TOKENS[self._theme]["hover"]
        return (c.red(), c.green(), c.blue())

    def enterEvent(self, e):
        self.anim.stop()
        self.anim.setStartValue(self._hover_t)
        self.anim.setEndValue(1.0)
        self.anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.anim.stop()
        self.anim.setStartValue(self._hover_t)
        self.anim.setEndValue(0.0)
        self.anim.start()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        else:
            self._pressed = False
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._recording:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_RECORD_GREEN)
            p.drawRoundedRect(self.rect(), 4, 4)
            if self._hover_t > 0.0:
                p.setBrush(
                    QColor(255, 255, 255, int(round(40 * self._hover_t)))
                )
                p.drawRoundedRect(self.rect(), 4, 4)
        else:
            r, g, b = self._hover_rgb()
            if self._hover_t > 0.0:
                alpha = int(round(255 * self._hover_t))
                p.setBrush(QColor(r, g, b, alpha))
            else:
                p.setBrush(QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self.rect(), 4, 4)

        p.setFont(QFont("Inter", _RECORD_LABEL_FONT_PT))
        p.setPen(
            _RECORD_LABEL_RECORDING_COLOR
            if self._recording
            else _BTN_TOKENS[self._theme]["idle_label"]
        )
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class CheckButton(RecordButton):
    """RecordButton that stays on or off. Same hover animation."""

    toggled = Signal(bool)

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._checked = False
        width = self.fontMetrics().horizontalAdvance(text) + 28
        self.setFixedWidth(max(width, 32))
        self.clicked.connect(self._flip)

    def isCheckable(self):
        return True

    def isChecked(self):
        return self._checked

    def setChecked(self, on: bool):
        on = bool(on)
        changed = on != self._checked
        self._checked = on
        self.setRecording(on and self.isEnabled())
        if changed and not self.signalsBlocked():
            self.toggled.emit(on)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.setRecording(self._checked and enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def _flip(self):
        if self.isEnabled():
            self.setChecked(not self._checked)

    def paintEvent(self, e):
        if self.isEnabled():
            super().paintEvent(e)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(QFont("Inter", _RECORD_LABEL_FONT_PT))
        color = QColor(_BTN_TOKENS[self._theme]["idle_label"])
        color.setAlpha(90)
        p.setPen(color)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class ClickableLineEdit(QLineEdit):
    """Read-only field that opens an editor when clicked."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PromptEditorDialog(QDialog):
    """Window for pasting the system prompt sent to OpenRouter."""

    def __init__(
        self, parent=None, text="", theme="dark",
        hint_text="Paste the prompt sent with every OpenRouter request.",
    ):
        super().__init__(parent)
        self.setWindowTitle("Prompt")
        self.setModal(True)
        self.setMinimumSize(480, 320)
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("Paste a prompt…")
        self._editor.setPlainText(text)
        layout.addWidget(self._editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setFixedHeight(32)
        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Save")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setFixedHeight(32)
        self._save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self._hint = hint
        self.apply_theme(theme)
        self._editor.setFocus()

    def text(self) -> str:
        return self._editor.toPlainText()

    def apply_theme(self, theme: str):
        p = theme_palette(theme if theme in ("light", "dark") else "dark")
        self.setStyleSheet(f"background-color: {p['window_bg']};")
        self._hint.setStyleSheet(
            f"color: {p['dim_text']}; font-family: Inter; font-size: 12px; border: none;"
        )
        self._editor.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {p['input_bg']};
                border: 1px solid {p['input_border']};
                border-radius: 4px;
                color: {p['input_text']};
                padding: 8px 10px;
                font-family: Inter;
                font-size: 13px;
            }}
            QPlainTextEdit:focus {{
                border-color: {ACCENT_GREEN};
            }}
            """
        )
        self._cancel_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {p['chip_bg']};
                border: 1px solid {p['chip_unsel_border']};
                border-radius: 8px;
                color: {p['chip_unsel_text']};
                padding: 6px 16px;
                font-family: Inter;
                font-size: 13px;
            }}
            QPushButton:hover {{
                border-color: {ACCENT_GREEN};
                color: {ACCENT_GREEN};
            }}
            """
        )
        self._save_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {ACCENT_GREEN};
                border: none;
                border-radius: 8px;
                color: #ffffff;
                padding: 6px 16px;
                font-family: Inter;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #16a34a;
            }}
            """
        )


class NoWheelComboBox(QComboBox):
    """QComboBox that ignores scroll-wheel changes unless its popup is open."""

    def wheelEvent(self, event):
        view = self.view()
        if view is not None and view.isVisible():
            super().wheelEvent(event)
        else:
            # Let the event propagate so the settings scroll area scrolls instead.
            event.ignore()


class IdComboBox(NoWheelComboBox):
    """Editable combo for typed ids.

    Row 0 is the add_label entry; rows after it are saved ids, labelled by
    name with the id as item data. A + button at the right end of the field
    asks to save the typed id. Once an id is saved, any click on the field
    opens the list; "Add a new voice id" clears it for typing.
    """

    add_requested = Signal(str)
    # currentTextChanged minus the add_label row being picked.
    id_text_changed = Signal(str)

    _ADD_SIZE = 24
    _ADD_MARGIN = 2

    def __init__(self, add_label: str, parent=None):
        super().__init__(parent)
        self.add_label = add_label
        self.setEditable(True)
        # New ids are added through the + button, not by QComboBox on Enter.
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._since_popup_closed = QElapsedTimer()
        # Sits over the combo's right end, outside the line edit, so its clicks
        # never reach the popup filter below.
        self._add_btn = QPushButton(self)
        self._add_btn.setFixedSize(self._ADD_SIZE, self._ADD_SIZE)
        self._add_btn.setIconSize(QSize(18, 18))
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_btn.setToolTip("Save voice id")
        self._add_btn.clicked.connect(
            lambda: self.add_requested.emit(self.currentText().strip())
        )
        self.set_theme("dark")
        self.lineEdit().textChanged.connect(lambda _t: self.sync_add_button())
        self.currentTextChanged.connect(self._on_text_changed)
        self.lineEdit().installEventFilter(self)
        self.activated.connect(self._on_activated)
        self.sync_add_button()

    def set_theme(self, theme: str):
        tokens = _BTN_TOKENS[theme]
        self._add_btn.setIcon(qta.icon("mdi.plus-thick", color=tokens["icon"]))
        self._add_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; border-radius: 4px; }"
            f" QPushButton:hover {{ background-color: {tokens['hover'].name()}; }}"
            " QPushButton:disabled { background-color: transparent; }"
        )

    def set_adding(self, busy: bool):
        """Grey out + while a typed id is being checked."""
        self._add_btn.setEnabled(not busy)

    def _place_add_button(self):
        self._add_btn.move(
            self.width() - self._ADD_SIZE - self._ADD_MARGIN - 2,
            (self.height() - self._ADD_SIZE) // 2,
        )
        self._add_btn.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_add_button()

    def _saved_row(self, text: str) -> int:
        """Row of a saved id whose label or id is text; -1 if none."""
        flags = Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive
        row = self.findText(text, flags)
        if row <= 0:
            row = self.findData(text)
        return row if row > 0 else -1

    def sync_add_button(self):
        """Show + only for typed text that isn't saved yet."""
        text = self.currentText().strip()
        visible = bool(text) and text != self.add_label and self._saved_row(text) == -1
        self._add_btn.setVisible(visible)
        self._place_add_button()

    def _on_text_changed(self, text: str):
        """Saved voices show their name; report the id behind it instead."""
        if text == self.add_label:
            return
        row = self._saved_row(text.strip())
        self.id_text_changed.emit(self.itemData(row) if row > 0 else text.strip())

    def _on_activated(self, row: int):
        if row == 0:
            self.setEditText("")
            self.setFocus()

    def eventFilter(self, obj, event):
        if (
            obj is self.lineEdit()
            and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
            and self.count() > 1
        ):
            # A click on the field while the list is open first closes the list,
            # then reaches the field; that click should only close it.
            if not self._since_popup_closed.isValid() or self._since_popup_closed.elapsed() > 200:
                self.setFocus()
                self.showPopup()
            self._since_popup_closed.invalidate()
            return True
        return super().eventFilter(obj, event)

    def hidePopup(self):
        super().hidePopup()
        self._since_popup_closed.start()


class NoWheelSlider(QSlider):
    """QSlider that ignores scroll-wheel events so the page scrolls instead."""

    def wheelEvent(self, event):
        # Ignore so the event propagates to the parent scroll area.
        event.ignore()


class EyeToggleButton(QWidget):
    """Toggle visibility: mdi.eye when masked, mdi.eye-off when plain text (same hover as Record)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_t = 0.0
        self._pressed = False
        self._revealed = False
        self._theme = "dark"

        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

        self.anim = QPropertyAnimation(self, b"hover_t")
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)   

    def get_hover_t(self):
        return self._hover_t

    def set_hover_t(self, t):
        self._hover_t = max(0.0, min(1.0, float(t)))
        self.update()

    hover_t = Property(float, get_hover_t, set_hover_t)

    def setRevealed(self, revealed: bool):
        self._revealed = bool(revealed)
        self.update()

    def isRevealed(self):
        return self._revealed

    def set_theme(self, theme: str):
        self._theme = theme if theme in _BTN_TOKENS else "dark"
        self.update()

    def _hover_rgb(self):
        c = _BTN_TOKENS[self._theme]["hover"]
        return (c.red(), c.green(), c.blue())

    def enterEvent(self, e):
        self.anim.stop()
        self.anim.setStartValue(self._hover_t)
        self.anim.setEndValue(1.0)
        self.anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.anim.stop()
        self.anim.setStartValue(self._hover_t)
        self.anim.setEndValue(0.0)
        self.anim.start()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        else:
            self._pressed = False
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r, g, b = self._hover_rgb()
        if self._hover_t > 0.0:
            alpha = int(round(255 * self._hover_t))
            p.setBrush(QColor(r, g, b, alpha))
        else:
            p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 4, 4)

        pm = qta.icon(self._icon_name(), color=_BTN_TOKENS[self._theme]["icon"]).pixmap(18, 18)
        # pixmap() returns device pixels; use device-independent size so the
        # icon stays centered on high-DPI displays too.
        dpr = pm.devicePixelRatioF() or 1.0
        w = pm.width() / dpr
        h = pm.height() / dpr
        x = (self.width() - w) / 2.0
        y = (self.height() - h) / 2.0
        p.drawPixmap(QPointF(x, y), pm)

    def _icon_name(self):
        return "mdi.eye-off" if self._revealed else "mdi.eye"


_DELETE_RED = "#dc2626"
# Darker than the idle icon so the trash stays readable on the red fill.
_TRASH_ICON_ON_RED = "#450a0a"


class DeletableItemDelegate(QStyledItemDelegate):
    """Wraps a combo's own delegate and paints edit and trash buttons on each row.

    Also filters the popup's mouse events so a click on a button acts on it
    instead of selecting the row.
    """

    delete_requested = Signal(int)
    edit_requested = Signal(int)

    def __init__(self, combo: QComboBox, parts=("edit", "trash")):
        super().__init__(combo)
        self._base = combo.itemDelegate()
        self._view = combo.view()
        self._parts = parts
        self._hover = (-1, None)
        self.theme = "dark"
        self.locked_rows = set()
        combo.setItemDelegate(self)
        # Installed after the combo's own popup filter, so this one runs first.
        self._view.viewport().installEventFilter(self)

    def _button_rects(self, rect: QRect) -> dict:
        side = rect.height() - 6
        trash = QRect(rect.right() - side - 3, rect.top() + 3, side, side)
        rects = {"trash": trash, "edit": trash.translated(-side - 2, 0)}
        return {part: r for part, r in rects.items() if part in self._parts}

    def sizeHint(self, option, index):
        size = self._base.sizeHint(option, index)
        size.setHeight(max(size.height(), 32))
        return size

    def paint(self, painter, option, index):
        self._base.paint(painter, option, index)
        if index.row() in self.locked_rows:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        idle = _BTN_TOKENS[self.theme]["icon"]
        for part, rect in self._button_rects(option.rect).items():
            hovered = self._hover == (index.row(), part)
            color = idle
            if hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                if part == "trash":
                    painter.setBrush(QColor(_DELETE_RED))
                    color = _TRASH_ICON_ON_RED
                else:
                    painter.setBrush(_BTN_TOKENS[self.theme]["hover"])
                painter.drawRoundedRect(QRectF(rect), 4, 4)
            icon = "mdi.trash-can-outline" if part == "trash" else "mdi.pencil-outline"
            pm = qta.icon(icon, color=color).pixmap(16, 16)
            dpr = pm.devicePixelRatioF() or 1.0
            center = QRectF(rect).center()
            painter.drawPixmap(
                QPointF(center.x() - pm.width() / dpr / 2, center.y() - pm.height() / dpr / 2), pm
            )
        painter.restore()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Leave:
            self._set_hover((-1, None))
        elif kind in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            pos = event.position().toPoint()
            index = self._view.indexAt(pos)
            part = None
            if index.isValid() and index.row() not in self.locked_rows:
                rects = self._button_rects(self._view.visualRect(index))
                part = next((k for k, r in rects.items() if r.contains(pos)), None)
            self._set_hover((index.row(), part) if part else (-1, None))
            if part and kind != QEvent.Type.MouseMove:
                if kind == QEvent.Type.MouseButtonRelease:
                    signal = self.delete_requested if part == "trash" else self.edit_requested
                    signal.emit(index.row())
                return True
        return False

    def _set_hover(self, hover: tuple):
        if hover != self._hover:
            self._hover = hover
            self._view.viewport().update()


class ConfirmOverlay(QWidget):
    """Small yes/no box drawn inside the app window over a dimmed backdrop."""

    def __init__(self, host: QWidget, text: str, confirm_text: str, on_confirm, theme="dark"):
        super().__init__(host)
        self._on_confirm = on_confirm
        p = theme_palette(theme if theme in ("light", "dark") else "dark")

        self.setObjectName("confirmOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            #confirmOverlay {{ background-color: rgba(0, 0, 0, 120); }}
            #confirmBox {{
                background-color: {p['card_bg']};
                border: 1px solid {p['card_border']};
                border-radius: 8px;
            }}
            QLabel {{
                color: {p['mid_text']}; font-family: Inter; font-size: 13px;
                background: transparent; border: none;
            }}
            QPushButton {{
                border-radius: 8px; padding: 6px 16px;
                font-family: Inter; font-size: 13px;
            }}
            #confirmCancel {{
                background-color: {p['chip_bg']};
                border: 1px solid {p['chip_unsel_border']};
                color: {p['chip_unsel_text']};
            }}
            #confirmCancel:hover {{ border-color: {p['mid_text']}; color: {p['mid_text']}; }}
            #confirmDelete {{
                background-color: {_DELETE_RED}; border: none;
                color: #ffffff; font-weight: 600;
            }}
            #confirmDelete:hover {{ background-color: #b91c1c; }}
            """
        )

        box = QFrame()
        box.setObjectName("confirmBox")
        box.setFixedWidth(320)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(20, 18, 20, 16)
        box_layout.setSpacing(16)
        label = QLabel(text)
        label.setWordWrap(True)
        box_layout.addWidget(label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        for name, caption, confirmed in (
            ("confirmDelete", confirm_text, True),
            ("confirmCancel", "Cancel", False),
        ):
            btn = QPushButton(caption)
            btn.setObjectName(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _=False, c=confirmed: self._finish(c))
            btn_row.addWidget(btn)
            if not confirmed:
                cancel_btn = btn
        box_layout.addLayout(btn_row)

        layout = QVBoxLayout(self)
        layout.addWidget(box, 0, Qt.AlignmentFlag.AlignCenter)

        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.show()
        self.raise_()
        cancel_btn.setFocus()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._finish(False)
        else:
            super().keyPressEvent(event)

    def _finish(self, confirmed: bool):
        self.parent().removeEventFilter(self)
        self.hide()
        self.deleteLater()
        if confirmed:
            self._on_confirm()


_PROMPTS_SETTINGS_KEY = "saved_prompts"


def load_saved_prompts() -> list:
    """Saved prompt presets: [{"prompt": str, "params": {name: value}}]."""
    raw = QSettings("Yogi", "Yogi").value(_PROMPTS_SETTINGS_KEY, "[]")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        print("Saved prompts are unreadable; starting with none.")
        return []
    if not isinstance(data, list):
        return []
    return [
        p for p in data
        if isinstance(p, dict) and isinstance(p.get("prompt"), str) and p["prompt"].strip()
    ]


def store_saved_prompts(presets: list) -> bool:
    """Persist the presets (Windows registry via QSettings). Returns success."""
    store = QSettings("Yogi", "Yogi")
    store.setValue(_PROMPTS_SETTINGS_KEY, json.dumps(presets))
    store.sync()
    return store.status() == QSettings.Status.NoError


MAX_PROMPT_FILE_BYTES = 1024 * 1024
_PROMPT_TEXT_KEYS = ("prompt", "system_prompt", "system", "content", "text")


def _prompt_from_json(item):
    """One preset from a JSON value, or None. Accepts a plain string, our
    {"prompt", "params"} preset, common keys like "system_prompt", or a
    chat {"messages": [...]} whose system messages are joined."""
    if isinstance(item, str):
        return {"prompt": item.strip(), "params": {}} if item.strip() else None
    if not isinstance(item, dict):
        return None
    text = next(
        (item[k] for k in _PROMPT_TEXT_KEYS if isinstance(item.get(k), str) and item[k].strip()),
        None,
    )
    if text is None and isinstance(item.get("messages"), list):
        system = [
            m["content"] for m in item["messages"]
            if isinstance(m, dict) and m.get("role") == "system" and isinstance(m.get("content"), str)
        ]
        text = "\n\n".join(s.strip() for s in system if s.strip()) or None
    if text is None:
        return None
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    params = {
        k: v for k, v in params.items()
        if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    return {"prompt": text.strip(), "params": params}


def parse_prompt_file(path) -> tuple[list, str | None]:
    """Read a .txt or .json prompt file. Returns (presets, error message)."""
    ext = os.path.splitext(str(path))[1].lower()
    if ext not in (".txt", ".json"):
        return [], "Only .txt and .json prompt files can be imported."
    try:
        if os.path.getsize(path) > MAX_PROMPT_FILE_BYTES:
            return [], "Prompt file is too large (max 1 MB)."
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError as e:
        return [], f"Couldn't read the prompt file: {e.strerror or e}"
    if ext == ".txt":
        text = raw.replace("\r\n", "\n").strip()
        return ([{"prompt": text, "params": {}}], None) if text else ([], "Prompt file is empty.")
    try:
        data = json.loads(raw)
    except ValueError:
        return [], "Prompt file is not valid JSON."
    if isinstance(data, dict) and isinstance(data.get("prompts"), list):
        data = data["prompts"]
    items = data if isinstance(data, list) else [data]
    presets = [p for p in (_prompt_from_json(i) for i in items) if p]
    if not presets:
        return [], "No prompt found in the JSON file."
    return presets, None


_VOICE_IDS_SETTINGS_KEY = "grok_voice_ids"


def load_voice_ids(settings_key: str = _VOICE_IDS_SETTINGS_KEY) -> dict:
    """Saved voices, oldest first: {voice id: display name}.

    Older Grok saves are a plain list of ids; those show the id until a name is looked up.
    """
    try:
        data = json.loads(QSettings("Yogi", "Yogi").value(settings_key, "[]"))
    except (TypeError, ValueError):
        return {}
    if isinstance(data, list):
        data = {v: v for v in data if isinstance(v, str)}
    if not isinstance(data, dict):
        return {}
    return {
        k: v for k, v in data.items()
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
    }


def store_voice_ids(voices: dict, settings_key: str = _VOICE_IDS_SETTINGS_KEY) -> bool:
    store = QSettings("Yogi", "Yogi")
    store.setValue(settings_key, json.dumps(voices))
    store.sync()
    return store.status() == QSettings.Status.NoError


class VoicePicker:
    """State behind one provider's voice dropdown (an IdComboBox)."""

    def __init__(self, name, setting, key_id, key_label, lookup, store_key):
        self.name = name            # "grok" or "fish"
        self.setting = setting      # SettingsTab.settings key holding the voice id
        self.key_id = key_id        # key_store provider id used for lookups
        self.key_label = key_label  # shown in "Connect your ... API key first."
        self.lookup = lookup        # (key, voice id) -> (name, None) | (None, error)
        self.store_key = store_key
        self.saved = load_voice_ids(store_key)  # ids the user added: deletable
        self.account = {}           # voices the account owns: listed, never deleted
        self.combo = None
        self.delegate = None


_SLIDERS_SETTINGS_KEY = "slider_values"


def load_slider_values() -> dict:
    """Last slider values: {settings key: value}."""
    try:
        data = json.loads(QSettings("Yogi", "Yogi").value(_SLIDERS_SETTINGS_KEY, "{}"))
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_MODEL_SETTINGS_KEY = "visual_model"


def load_selected_model() -> str:
    value = QSettings("Yogi", "Yogi").value(_MODEL_SETTINGS_KEY, "")
    return value if isinstance(value, str) else ""


def store_selected_model(model: str):
    QSettings("Yogi", "Yogi").setValue(_MODEL_SETTINGS_KEY, model)


def store_slider_values(values: dict):
    QSettings("Yogi", "Yogi").setValue(_SLIDERS_SETTINGS_KEY, json.dumps(values))


_VOCAL_SETTINGS_KEY = "vocal_settings"


def load_vocal_settings() -> dict:
    """Saved Vocal Model values, keeping only keys whose type matches vocal.DEFAULTS."""
    try:
        data = json.loads(QSettings("Yogi", "Yogi").value(_VOCAL_SETTINGS_KEY, "{}"))
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, default in vocal.DEFAULTS.items():
        value = data.get(key)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, str)
        if ok:
            out[key] = value
    return out


def store_vocal_settings(values: dict):
    QSettings("Yogi", "Yogi").setValue(_VOCAL_SETTINGS_KEY, json.dumps(values))


_APP_SETTINGS_KEY = "app_settings"
FOLLOWUP_MIN_S = 1.0
FOLLOWUP_MAX_S = 15.0


def load_app_settings() -> dict:
    """Saved hotkey, theme, active prompt and audio device names.

    Devices are stored by name: PortAudio indexes can change between launches.
    """
    try:
        data = json.loads(QSettings("Yogi", "Yogi").value(_APP_SETTINGS_KEY, "{}"))
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in ("hotkey", "stop_hotkey"):
        if isinstance(data.get(key), str) and data[key].strip():
            out[key] = data[key]
    if data.get("theme") in ("light", "dark"):
        out["theme"] = data["theme"]
    for key in ("prompt", "input_device_name", "output_device_name"):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    threshold = data.get("mic_threshold")
    if (
        isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
        and MIN_SPEECH_THRESHOLD <= threshold <= MAX_SPEECH_THRESHOLD
    ):
        out["mic_threshold"] = float(threshold)
    followup = data.get("followup_window_s")
    if (
        isinstance(followup, (int, float)) and not isinstance(followup, bool)
        and FOLLOWUP_MIN_S <= followup <= FOLLOWUP_MAX_S
    ):
        out["followup_window_s"] = float(followup)
    return out


def store_app_settings(values: dict):
    QSettings("Yogi", "Yogi").setValue(_APP_SETTINGS_KEY, json.dumps(values))


def _device_index_by_name(devices, name):
    """PortAudio index of the device called name, or None (system default)."""
    if not name:
        return None
    for index, device_name in devices:
        if device_name == name:
            return index
    print(f"audio: saved device {name!r} not found; using system default", flush=True)
    return None


class ApiKeyRow(QWidget):
    """Paste, save, replace and delete one provider's key.

    The full key is never put back into the field once saved; the saved state
    shows only a masked placeholder. Verification is the owner's job: it
    receives submitted() and calls save() once the key checks out.
    """

    submitted = Signal(str)
    deleted = Signal()
    storage_failed = Signal(str)

    EMPTY, SAVED, REPLACING = range(3)

    def __init__(self, provider: key_store.Provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self._state = self.EMPTY
        self._masked = ""
        self._revealed = False

        self.setStyleSheet("background-color: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.hint_label = QLabel(provider.label)
        self.hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        layout.addWidget(self.hint_label)

        row = QWidget()
        row.setStyleSheet("background-color: transparent; border: none;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 20, 0)
        row_layout.setSpacing(8)

        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.EchoMode.Password)
        self.input.returnPressed.connect(self._on_submit_clicked)
        row_layout.addWidget(self.input)

        self.visibility_btn = EyeToggleButton()
        self.visibility_btn.clicked.connect(self._on_visibility_clicked)
        row_layout.addWidget(self.visibility_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        row_layout.addSpacing(8)

        self.submit_btn = self._make_button("Connect", self._on_submit_clicked)
        self.replace_btn = self._make_button("Replace", self._on_replace_clicked)
        self.delete_btn = self._make_button("Delete", self._on_delete_clicked)
        self.cancel_btn = self._make_button("Cancel", self._on_cancel_clicked)
        for btn in (self.submit_btn, self.replace_btn, self.delete_btn, self.cancel_btn):
            row_layout.addWidget(btn)

        layout.addWidget(row)
        self._apply_state()

    def _make_button(self, text, slot):
        btn = RecordButton(text)
        btn.setFixedWidth(110)
        btn.setFixedHeight(32)
        btn.clicked.connect(slot)
        return btn

    def load_saved(self):
        """Show the saved key, if any, and return it. Raises KeyStoreError."""
        key = key_store.get_key(self.provider.id)
        if key:
            self._masked = key_store.mask(key)
            self._state = self.SAVED
        else:
            self._state = self.EMPTY
        self._apply_state()
        return key

    def save(self, key: str):
        """Store a verified key and switch to the masked state. Raises KeyStoreError."""
        key_store.set_key(self.provider.id, key)
        self._masked = key_store.mask(key)
        self._state = self.SAVED
        self._apply_state()

    def set_busy(self, busy: bool):
        self.submit_btn.setText("Checking…" if busy else self._submit_label())
        for widget in (self.input, self.submit_btn, self.cancel_btn, self.replace_btn, self.delete_btn):
            widget.setEnabled(not busy)

    def set_theme(self, theme: str, line_edit_style: str, hint_style: str):
        self.input.setStyleSheet(line_edit_style)
        self.hint_label.setStyleSheet(hint_style)
        self.visibility_btn.set_theme(theme)
        for btn in (self.submit_btn, self.replace_btn, self.delete_btn, self.cancel_btn):
            btn.set_theme(theme)

    def _submit_label(self):
        return "Save" if self._state == self.REPLACING else "Connect"

    def _apply_state(self):
        editing = self._state != self.SAVED
        self.input.clear()
        self.input.setReadOnly(not editing)
        self._set_revealed(False)
        if self._state == self.SAVED:
            self.input.setPlaceholderText(self._masked)
        elif self._state == self.REPLACING:
            self.input.setPlaceholderText("Paste a new API key")
        else:
            self.input.setPlaceholderText("Paste your API key")

        self.visibility_btn.setVisible(editing)
        self.submit_btn.setVisible(editing)
        self.submit_btn.setText(self._submit_label())
        self.cancel_btn.setVisible(self._state == self.REPLACING)
        self.replace_btn.setVisible(self._state == self.SAVED)
        self.delete_btn.setVisible(self._state == self.SAVED)

    def _set_revealed(self, revealed: bool):
        self._revealed = revealed
        self.input.setEchoMode(
            QLineEdit.EchoMode.Normal if revealed else QLineEdit.EchoMode.Password
        )
        self.visibility_btn.setRevealed(revealed)

    def _on_visibility_clicked(self):
        self._set_revealed(not self._revealed)

    def _on_submit_clicked(self):
        if self._state == self.SAVED or not self.submit_btn.isEnabled():
            return
        self.submitted.emit(self.input.text().strip())

    def _on_replace_clicked(self):
        self._state = self.REPLACING
        self._apply_state()
        self.input.setFocus()

    def _on_cancel_clicked(self):
        self._state = self.SAVED
        self._apply_state()

    def _on_delete_clicked(self):
        answer = QMessageBox.question(
            self,
            "Delete API key",
            f"Delete the saved {self.provider.label}?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            key_store.delete_key(self.provider.id)
        except key_store.KeyStoreError as e:
            self.storage_failed.emit(str(e))
            return
        self._masked = ""
        self._state = self.EMPTY
        self._apply_state()
        self.deleted.emit()


_CONTEXT_MIN = 2048
_CONTEXT_MAX = 1_048_576
_CONTEXT_DEFAULT = 131_072
_SEARCH_PARAMS = frozenset({"tools", "web_search_options"})
# Weakest first. OpenRouter lists these strongest first; the dropdown does not.
_REASONING_EFFORTS = (
    ("minimal", "Minimal"),
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "XHigh"),
    ("max", "Max"),
)
_GATEWAY_EFFORTS = tuple(value for value, _label in _REASONING_EFFORTS)


def vision_model_info(m):
    """Pick the catalog fields that drive the context, surf, and reasoning controls."""
    if not isinstance(m, dict):
        return None
    mid = m.get("id")
    if not isinstance(mid, str) or not mid.strip():
        return None
    params = m.get("supported_parameters") if isinstance(m.get("supported_parameters"), list) else []
    ctx = m.get("context_length")
    try:
        ctx = int(ctx) if ctx is not None else None
    except (TypeError, ValueError):
        ctx = None
    if ctx is not None and ctx < 1:
        ctx = None
    reasoning = m.get("reasoning") if isinstance(m.get("reasoning"), dict) else None
    return {
        "id": mid,
        "context_length": ctx,
        "can_search": bool(_SEARCH_PARAMS.intersection(params)),
        "reasoning": reasoning,
    }


def reasoning_efforts(info):
    """(effort ids, mandatory). Empty ids means the combo stays Off and disabled."""
    reasoning = (info or {}).get("reasoning")
    if not isinstance(reasoning, dict):
        return [], False
    mandatory = bool(reasoning.get("mandatory"))
    if "supported_efforts" not in reasoning:
        return [], mandatory
    raw = reasoning["supported_efforts"]
    if raw is None:
        return list(_GATEWAY_EFFORTS), mandatory
    if not isinstance(raw, list):
        return [], mandatory
    allowed = set()
    for item in raw:
        if isinstance(item, str) and item.strip():
            allowed.add(item.strip().lower())
    return [value for value in _GATEWAY_EFFORTS if value in allowed], mandatory


def _fetch_openrouter_models(key: str):
    """Verify the key and list vision models. Returns (ids, None) or (None, error)."""
    headers = {"Authorization": f"Bearer {key}"}

    # The /models endpoint is public and ignores the key, so verify the
    # key first against the authenticated /auth/key endpoint.
    try:
        auth_response = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as e:
        print("Network error:", type(e).__name__)
        return None, "Network error - Check your internet connection."

    if auth_response.status_code in (401, 403):
        print("OpenRouter: invalid API key")
        return None, "Invalid OpenRouter API key"

    if auth_response.status_code != 200:
        print("OpenRouter auth error:", auth_response.status_code)
        return None, f"OpenRouter error (HTTP {auth_response.status_code})"

    url = "https://openrouter.ai/api/v1/models?input_modalities=image"

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        print("Network error:", type(e).__name__)
        return None, "Network error - Check your internet connection."

    if response.status_code != 200:
        print("Openrouter error:", response.status_code)
        return None, f"OpenRouter error (HTTP {response.status_code})"

    models = response.json().get("data", [])
    infos = []
    for m in models:
        info = vision_model_info(m) if isinstance(m, dict) else None
        if info:
            infos.append(info)
    infos.sort(key=lambda m: m["id"])
    return infos, None


MODEL_DOWN = "The provider is down. Try another model"


def _check_openrouter_model_up(key: str, model: str):
    """None when a provider serving model is up, else the message to show.

    Network and API hiccups return None: the check is advisory and stays quiet.
    """
    url = f"https://openrouter.ai/api/v1/models/{model}/endpoints"
    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=15)
        endpoints = response.json().get("data", {}).get("endpoints") or []
    except (requests.RequestException, ValueError, AttributeError):
        return None
    if response.status_code != 200:
        return None
    # status 0 is operational; negative values are degraded or down.
    for e in endpoints:
        if isinstance(e, dict) and e.get("status", 0) == 0 and e.get("uptime_last_5m") != 0:
            return None
    return MODEL_DOWN


class SettingsTab(QWidget):
    settings_changed = Signal(dict)
    theme_changed = Signal(str)
    # check id, vision model ids (None on failure), error message
    _openrouter_checked = Signal(int, object, str)
    # a key-checked provider id ("xai", "openrouter_tts", "fish_audio"), "or_models"
    # ({model: voices}), "or_style" or "voice"; check id, result (None on failure), error
    _vocal_checked = Signal(str, int, object, str)
    # model id, "" when up or the message when its providers are down
    _model_status_checked = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.is_recording = False
        self._openrouter_check_id = 0
        self._pending_key = None
        self._openrouter_checked.connect(self._on_openrouter_checked)
        self._vocal_key_check_ids = {}
        self._pending_vocal_keys = {}
        self._voice_pickers = {}
        self._or_speech_models = {}
        self._vocal_checked.connect(self._on_vocal_checked)
        self._model_status_checked.connect(self._on_model_status_checked)
        self._vision_models = {}
        self._surf_web_wanted = False
        self._reasoning_wanted = "off"
        self.settings = {
            "hotkey": "`",
            "stop_hotkey": "Esc",
            "input_device": None,
            "output_device": None,
            "model": load_selected_model() or "qwen/qwen3-vl-8b-instruct",
            "prompt": "",
            "context_window": _CONTEXT_DEFAULT,
            "max_tokens": 4096,
            "surf_web": False,
            "reasoning_effort": "off",
            "temperature": 0.7,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "top_k": 40,
            "top_p": 0.95,
            "repetition_penalty": 1.1,
            "min_p": 0.0,
            "top_a": 0.0,
            "theme": "dark",
            "font_size": "medium",
            "accent_color": "green",
            **vocal.DEFAULTS,
            **load_vocal_settings(),
        }
        saved_app = load_app_settings()
        for key in ("hotkey", "stop_hotkey", "theme", "prompt"):
            if key in saved_app:
                self.settings[key] = saved_app[key]
        self.settings["mic_threshold"] = saved_app.get("mic_threshold", DEFAULT_SPEECH_THRESHOLD)
        self.settings["followup_window_s"] = saved_app.get("followup_window_s", FOLLOWUP_WINDOW_S)
        set_speech_threshold(self.settings["mic_threshold"])
        input_devices = list_input_devices()
        output_devices = list_output_devices()
        self.settings["input_device"] = _device_index_by_name(
            input_devices, saved_app.get("input_device_name")
        )
        self.settings["output_device"] = _device_index_by_name(
            output_devices, saved_app.get("output_device_name")
        )
        if self.settings["input_device"] is not None:
            set_input_device(self.settings["input_device"])
        if self.settings["output_device"] is not None:
            set_output_device(self.settings["output_device"], notify=False)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            self._scroll_stylesheet_from_palette(theme_palette("dark"))
        )
        outer_layout.addWidget(self._scroll)

        # Top banner - hidden; slides/fades in from the top. Red on API errors, green on success.
        self._error_banner = QLabel(self)
        self._error_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_banner.hide()
        self._error_opacity = QGraphicsOpacityEffect(self._error_banner)
        self._error_banner.setGraphicsEffect(self._error_opacity)
        self._error_opacity.setOpacity(0.0)
        self._error_anim = None
        self._error_timer = QTimer(self)
        self._error_timer.setSingleShot(True)
        self._error_timer.timeout.connect(self._hide_error_banner)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        self._content_h_margin = 40
        content_layout.setContentsMargins(
            self._content_h_margin, 30, self._content_h_margin, 30
        )
        content_layout.setSpacing(32)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)

        # Yogi Settings section: activation hotkey and sound devices
        hotkey_section, hotkey_card = self.make_section("Yogi Settings", "mdi.cog")
        self.hotkey_hint_label = QLabel("Activation Hotkey")
        self.hotkey_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        hotkey_card.addWidget(self.hotkey_hint_label)

        hotkey_row = QWidget()
        hotkey_row.setStyleSheet("background-color: transparent; border: none;")
        hotkey_row_layout = QHBoxLayout(hotkey_row)
        hotkey_row_layout.setContentsMargins(0, 0, 20, 0)
        hotkey_row_layout.setSpacing(8)

        self.hotkey_input = QLineEdit()
        self.hotkey_input.setText(self.settings["hotkey"])
        self.hotkey_input.setReadOnly(True)
        self.hotkey_input.setStyleSheet(
            self._line_edit_style_from_palette(theme_palette("dark"))
        )
        hotkey_row_layout.addWidget(self.hotkey_input)

        self.record_btn = RecordButton("Record")
        self.record_btn.setFixedWidth(110)
        self.record_btn.setFixedHeight(32)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.clicked.connect(self.toggle_recording_hotkey)
        hotkey_row_layout.addWidget(self.record_btn)
        hotkey_card.addWidget(hotkey_row)

        self.stop_hotkey_hint_label = QLabel("Stop Hotkey")
        self.stop_hotkey_hint_label.setToolTip(
            "Cuts Yogi off: stops the answer, the voice and any recording"
        )
        self.stop_hotkey_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        hotkey_card.addWidget(self.stop_hotkey_hint_label)

        stop_hotkey_row = QWidget()
        stop_hotkey_row.setStyleSheet("background-color: transparent; border: none;")
        stop_hotkey_row_layout = QHBoxLayout(stop_hotkey_row)
        stop_hotkey_row_layout.setContentsMargins(0, 0, 20, 0)
        stop_hotkey_row_layout.setSpacing(8)

        self.stop_hotkey_input = QLineEdit()
        self.stop_hotkey_input.setText(self.settings["stop_hotkey"])
        self.stop_hotkey_input.setReadOnly(True)
        self.stop_hotkey_input.setStyleSheet(
            self._line_edit_style_from_palette(theme_palette("dark"))
        )
        stop_hotkey_row_layout.addWidget(self.stop_hotkey_input)

        self.stop_record_btn = RecordButton("Record")
        self.stop_record_btn.setFixedWidth(110)
        self.stop_record_btn.setFixedHeight(32)
        self.stop_record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_record_btn.clicked.connect(
            lambda: self.toggle_recording_hotkey("stop_hotkey")
        )
        stop_hotkey_row_layout.addWidget(self.stop_record_btn)
        hotkey_card.addWidget(stop_hotkey_row)
        sound_card = hotkey_card

        self.input_hint_label = QLabel("Input")
        self.input_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        sound_card.addWidget(self.input_hint_label)

        self.input_select = NoWheelComboBox()
        self.input_select.setEditable(False)
        self.input_select.setFixedHeight(32)
        self.input_select.setStyleSheet(
            self._combo_style_from_palette(theme_palette("dark"))
        )
        self._populate_device_combo(
            self.input_select, input_devices, self.settings["input_device"]
        )
        self.input_select.currentIndexChanged.connect(self._on_input_device_changed)
        sound_card.addWidget(self.input_select)

        self.output_hint_label = QLabel("Output")
        self.output_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        sound_card.addWidget(self.output_hint_label)

        self.output_select = NoWheelComboBox()
        self.output_select.setEditable(False)
        self.output_select.setFixedHeight(32)
        self.output_select.setStyleSheet(
            self._combo_style_from_palette(theme_palette("dark"))
        )
        self._populate_device_combo(
            self.output_select, output_devices, self.settings["output_device"]
        )
        self.output_select.currentIndexChanged.connect(self._on_output_device_changed)
        sound_card.addWidget(self.output_select)

        mic_title_row = QWidget()
        mic_title_row.setStyleSheet("background-color: transparent; border: none;")
        mic_title_layout = QHBoxLayout(mic_title_row)
        mic_title_layout.setContentsMargins(0, 8, 0, 0)
        self.mic_threshold_hint_label = QLabel("Microphone Threshold")
        self.mic_threshold_value_label = QLabel(
            level_to_db_text(self.settings["mic_threshold"])
        )
        for lbl in (self.mic_threshold_hint_label, self.mic_threshold_value_label):
            lbl.setStyleSheet(
                "color: #707070; font-family: Inter; font-size: 12px; border: none;"
            )
        mic_title_layout.addWidget(self.mic_threshold_hint_label)
        mic_title_layout.addStretch()
        mic_title_layout.addWidget(self.mic_threshold_value_label)
        sound_card.addWidget(mic_title_row)

        self.mic_threshold_slider = MicThresholdSlider(self.settings["mic_threshold"])
        self.mic_threshold_slider.threshold_moved.connect(self._on_mic_threshold_moved)
        self.mic_threshold_slider.threshold_changed.connect(self._on_mic_threshold_changed)
        sound_card.addWidget(self.mic_threshold_slider)

        mic_test_row = QWidget()
        mic_test_row.setStyleSheet("background-color: transparent; border: none;")
        mic_test_layout = QHBoxLayout(mic_test_row)
        mic_test_layout.setContentsMargins(0, 0, 0, 0)
        mic_test_layout.addStretch()
        self.mic_test_btn = RecordButton("Test Microphone")
        self.mic_test_btn.setFixedWidth(140)
        self.mic_test_btn.clicked.connect(self._toggle_mic_test)
        mic_test_layout.addWidget(self.mic_test_btn)
        sound_card.addWidget(mic_test_row)

        self._mic_monitor = MicLevelMonitor()
        self._mic_timer = QTimer(self)
        self._mic_timer.setInterval(33)
        self._mic_timer.timeout.connect(self._on_mic_tick)
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)

        followup_title_row = QWidget()
        followup_title_row.setStyleSheet("background-color: transparent; border: none;")
        followup_title_layout = QHBoxLayout(followup_title_row)
        followup_title_layout.setContentsMargins(0, 8, 0, 0)
        self.followup_hint_label = QLabel("Question Follow Up Time")
        self.followup_hint_label.setToolTip(
            "How long Yogi keeps listening for another question after it finishes answering"
        )
        self.followup_value_label = QLabel(f"{self.settings['followup_window_s']:g} s")
        for lbl in (self.followup_hint_label, self.followup_value_label):
            lbl.setStyleSheet(
                "color: #707070; font-family: Inter; font-size: 12px; border: none;"
            )
        followup_title_layout.addWidget(self.followup_hint_label)
        followup_title_layout.addStretch()
        followup_title_layout.addWidget(self.followup_value_label)
        sound_card.addWidget(followup_title_row)

        # Half-second steps: slider value is seconds * 2.
        self.followup_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.followup_slider.setRange(int(FOLLOWUP_MIN_S * 2), int(FOLLOWUP_MAX_S * 2))
        self.followup_slider.setValue(round(self.settings["followup_window_s"] * 2))
        self.followup_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.followup_slider.setStyleSheet(
            self._slider_stylesheet_from_palette(theme_palette("dark"))
        )
        self.followup_slider.valueChanged.connect(self._on_followup_slider_changed)
        self.followup_slider.sliderReleased.connect(self._store_app_settings)
        sound_card.addWidget(self.followup_slider)

        content_layout.addWidget(
            hotkey_section, 0, Qt.AlignmentFlag.AlignHCenter
        )

        # Visual Model & Parameters section
        model_section, model_card = self.make_section("Visual Model & Parameters", "mdi.tune")

        self.api_key_row = ApiKeyRow(key_store.PROVIDERS[0])
        self.api_key_hint_label = self.api_key_row.hint_label
        self.api_key_row.input.setStyleSheet(
            self._line_edit_style_from_palette(theme_palette("dark"))
        )
        self.api_key_row.submitted.connect(self._on_api_key_submitted)
        self.api_key_row.deleted.connect(self._on_api_key_deleted)
        self.api_key_row.storage_failed.connect(self._show_api_error)
        model_card.addWidget(self.api_key_row)

        self.model_hint_label = QLabel("Model")
        self.model_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        model_card.addWidget(self.model_hint_label)

        self.model_select = NoWheelComboBox()
        self.model_select.setEditable(False)
        self.model_select.setFixedHeight(32)
        self.model_select.setStyleSheet(
            self._combo_style_from_palette(theme_palette("dark"))
        )
        # Leave empty for now (API not hooked up yet)
        self.model_select.clear()
        self.model_select.addItem("")
        self.model_select.setCurrentIndex(0)
        model_card.addWidget(self.model_select)
        self.model_select.currentTextChanged.connect(
            lambda value: self.settings.__setitem__("model", value)
        )
        # Only a pick by the user is remembered; list refills set the model silently.
        self.model_select.activated.connect(lambda _i: self._on_model_picked())

        prompt_label_row = QWidget()
        prompt_label_row.setStyleSheet("background-color: transparent; border: none;")
        prompt_label_layout = QHBoxLayout(prompt_label_row)
        prompt_label_layout.setContentsMargins(0, 0, 0, 0)
        self.prompt_hint_label = QLabel("Prompt")
        self.prompt_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        prompt_label_layout.addWidget(self.prompt_hint_label)
        prompt_label_layout.addStretch()
        self.prompt_import_btn = QPushButton()
        self.prompt_import_btn.setFixedSize(22, 22)
        self.prompt_import_btn.setIconSize(QSize(15, 15))
        self.prompt_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prompt_import_btn.setToolTip("Import prompt (.txt or .json)")
        self.prompt_import_btn.clicked.connect(self._on_import_prompt_clicked)
        self._style_prompt_import_btn("dark")
        prompt_label_layout.addWidget(self.prompt_import_btn)
        model_card.addWidget(prompt_label_row)

        self.prompt_field = ClickableLineEdit()
        self.prompt_field.setReadOnly(True)
        self.prompt_field.setFixedHeight(32)
        self.prompt_field.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prompt_field.setPlaceholderText("Click to paste a prompt…")
        self.prompt_field.setStyleSheet(
            self._line_edit_style_from_palette(theme_palette("dark"))
        )
        self.prompt_field.clicked.connect(self._on_prompt_field_clicked)
        model_card.addWidget(self.prompt_field)

        self.prompt_select = NoWheelComboBox()
        self.prompt_select.setEditable(False)
        self.prompt_select.setFixedHeight(32)
        self.prompt_select.setPlaceholderText("Select prompt")
        self.prompt_select.setStyleSheet(
            self._combo_style_from_palette(theme_palette("dark"))
        )
        self._prompt_delegate = DeletableItemDelegate(self.prompt_select)
        self._prompt_delegate.locked_rows = {0}
        # Delegate rows are combo rows; saved prompts start at combo row 1.
        self._prompt_delegate.delete_requested.connect(
            lambda r: self._on_prompt_delete_requested(r - 1)
        )
        self._prompt_delegate.edit_requested.connect(
            lambda r: self._on_prompt_edit_requested(r - 1)
        )
        self.prompt_select.activated.connect(self._on_saved_prompt_selected)
        model_card.addWidget(self.prompt_select)
        self._saved_prompts = load_saved_prompts()
        texts = [p["prompt"] for p in self._saved_prompts]
        if self.settings["prompt"] not in texts:
            self.settings["prompt"] = ""
        self._populate_saved_prompts(
            texts.index(self.settings["prompt"]) if self.settings["prompt"] else -1
        )

        self._slider_title_labels = []
        self._slider_value_labels = []
        self._slider_fields = {}

        def _make_slider_row(title: str, right_text: str):
            row = QWidget()
            row.setStyleSheet("background-color: transparent; border: none;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)

            left = QLabel(title)
            left.setStyleSheet(
                "color: #707070; font-family: Inter; font-size: 12px; border: none;"
            )
            left.setFixedWidth(120)
            self._slider_title_labels.append(left)

            slider = NoWheelSlider(Qt.Orientation.Horizontal)
            slider.setFixedHeight(18)

            right = QLineEdit(right_text)
            right.setStyleSheet(self._slider_value_style(theme_palette("dark")))
            right.setFixedSize(64, 24)
            right.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._slider_value_labels.append(right)
            self._slider_fields[slider] = right

            row_layout.addWidget(left)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(right)

            return row, slider, right

        # Context Window (2,048–model max), default 131,072
        ctx_row, self.context_window_slider, self.context_window_value = _make_slider_row(
            "Context Window", f"{_CONTEXT_DEFAULT:,}"
        )
        self.context_window_slider.setRange(_CONTEXT_MIN, _CONTEXT_MAX)
        self.context_window_slider.setValue(_CONTEXT_DEFAULT)
        model_card.addWidget(ctx_row)

        # Max Tokens (256–262144), default 4096
        tok_row, self.max_tokens_slider, self.max_tokens_value = _make_slider_row(
            "Max Tokens", "4,096"
        )
        self.max_tokens_slider.setRange(256, 262144)
        self.max_tokens_slider.setValue(4096)
        model_card.addWidget(tok_row)

        # Temperature (0.00–1.00), default 0.70
        temp_row, self.temp_slider, self.temp_value = _make_slider_row(
            "Temperature", "0.70"
        )
        self.temp_slider.setRange(0, 100)
        self.temp_slider.setValue(70)
        model_card.addWidget(temp_row)

        # Frequency Penalty (-2.00–2.00), default 0.00
        freq_row, self.freq_pen_slider, self.freq_pen_value = _make_slider_row(
            "Frequency Penalty", "0.00"
        )
        self.freq_pen_slider.setRange(-200, 200)
        self.freq_pen_slider.setValue(0)
        model_card.addWidget(freq_row)

        # Presence Penalty (-2.00–2.00), default 0.00
        pres_row, self.pres_pen_slider, self.pres_pen_value = _make_slider_row(
            "Presence Penalty", "0.00"
        )
        self.pres_pen_slider.setRange(-200, 200)
        self.pres_pen_slider.setValue(0)
        model_card.addWidget(pres_row)

        # Top K (0–100), default 40
        topk_row, self.topk_slider, self.topk_value = _make_slider_row("Top K", "40")
        self.topk_slider.setRange(0, 100)
        self.topk_slider.setValue(40)
        model_card.addWidget(topk_row)

        # Top P (0.00–1.00), default 0.95
        topp_row, self.topp_slider, self.topp_value = _make_slider_row("Top P", "0.95")
        self.topp_slider.setRange(0, 100)
        self.topp_slider.setValue(95)
        model_card.addWidget(topp_row)

        # Repetition Penalty (1.00–2.00), default 1.10
        rep_row, self.rep_pen_slider, self.rep_pen_value = _make_slider_row(
            "Repetition Penalty", "1.10"
        )
        self.rep_pen_slider.setRange(100, 200)
        self.rep_pen_slider.setValue(110)
        model_card.addWidget(rep_row)

        # Min P (0.00–1.00), default 0.00
        minp_row, self.minp_slider, self.minp_value = _make_slider_row(
            "Min P", "0.00"
        )
        self.minp_slider.setRange(0, 100)
        self.minp_slider.setValue(0)
        model_card.addWidget(minp_row)

        # Top A (0.00–1.00), default 0.00
        topa_row, self.topa_slider, self.topa_value = _make_slider_row(
            "Top A", "0.00"
        )
        self.topa_slider.setRange(0, 100)
        self.topa_slider.setValue(0)
        model_card.addWidget(topa_row)

        self.context_window_slider.valueChanged.connect(self._on_context_window_slider_changed)
        self.max_tokens_slider.valueChanged.connect(self._on_max_tokens_slider_changed)
        self._on_context_window_slider_changed(self.context_window_slider.value())
        self.temp_slider.valueChanged.connect(self._on_temperature_slider_changed)
        self.freq_pen_slider.valueChanged.connect(
            self._on_frequency_penalty_slider_changed
        )
        self.pres_pen_slider.valueChanged.connect(
            self._on_presence_penalty_slider_changed
        )
        self.topk_slider.valueChanged.connect(self._on_topk_slider_changed)
        self.topp_slider.valueChanged.connect(self._on_topp_slider_changed)
        self.rep_pen_slider.valueChanged.connect(
            self._on_repetition_penalty_slider_changed
        )
        self.minp_slider.valueChanged.connect(self._on_min_p_slider_changed)
        self.topa_slider.valueChanged.connect(self._on_top_a_slider_changed)

        # settings key -> (slider, slider units per settings unit), saved with prompts
        self._preset_sliders = {
            "context_window": (self.context_window_slider, 1),
            "max_tokens": (self.max_tokens_slider, 1),
            "temperature": (self.temp_slider, 100),
            "frequency_penalty": (self.freq_pen_slider, 100),
            "presence_penalty": (self.pres_pen_slider, 100),
            "top_k": (self.topk_slider, 1),
            "top_p": (self.topp_slider, 100),
            "repetition_penalty": (self.rep_pen_slider, 100),
            "min_p": (self.minp_slider, 100),
            "top_a": (self.topa_slider, 100),
        }
        self._slider_defaults = {s: s.value() for s, _ in self._preset_sliders.values()}
        stored = load_slider_values()
        for key, (slider, scale) in self._preset_sliders.items():
            if isinstance(stored.get(key), (int, float)):
                slider.setValue(round(stored[key] * scale))
            slider.valueChanged.connect(self._store_slider_values)
            field = self._slider_fields[slider]
            field.setToolTip(
                f"{slider.minimum() / scale:,.{0 if scale == 1 else 2}f} – "
                f"{slider.maximum() / scale:,.{0 if scale == 1 else 2}f}"
            )
            field.editingFinished.connect(
                lambda s=slider, sc=scale, f=field: self._on_slider_value_typed(s, sc, f)
            )

        reset_row = QHBoxLayout()
        reset_row.addStretch()
        self.reset_sliders_btn = RecordButton("Reset to defaults")
        self.reset_sliders_btn.setFixedWidth(140)
        self.reset_sliders_btn.clicked.connect(self._reset_sliders)
        reset_row.addWidget(self.reset_sliders_btn)
        model_card.addLayout(reset_row)

        extras = QWidget()
        extras.setStyleSheet("background-color: transparent; border: none;")
        extras_layout = QVBoxLayout(extras)
        extras_layout.setContentsMargins(0, -8, 0, 0)
        extras_layout.setSpacing(4)

        self.reasoning_hint_label = QLabel("Reasoning effort")
        self.reasoning_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        extras_layout.addWidget(self.reasoning_hint_label)

        reason_row = QHBoxLayout()
        reason_row.setContentsMargins(0, 0, 0, 0)
        reason_row.setSpacing(8)

        self.reasoning_combo = NoWheelComboBox()
        self.reasoning_combo.setFixedHeight(32)
        self.reasoning_combo.setMaximumWidth(108)
        self.reasoning_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.reasoning_combo.setToolTip("How hard Yogi thinks before it answers")
        self.reasoning_combo.addItem("Unavailable", "off")
        self.reasoning_combo.setCurrentIndex(0)
        self.reasoning_combo.setEnabled(False)
        self.reasoning_combo.setMaximumWidth(148)
        self.reasoning_combo.setStyleSheet(self._combo_style_from_palette(theme_palette("dark")))
        self.reasoning_combo.currentIndexChanged.connect(self._on_reasoning_changed)
        reason_row.addWidget(self.reasoning_combo)
        reason_row.addStretch()

        self.surf_web_btn = CheckButton("Surf the web")
        self.surf_web_btn.setEnabled(False)
        self.surf_web_btn.setToolTip("This model can't search the web.")
        self.surf_web_btn.toggled.connect(self._on_surf_web_toggled)
        self.surf_web_btn.set_theme("dark")
        reason_row.addWidget(self.surf_web_btn)
        extras_layout.addLayout(reason_row)
        model_card.addWidget(extras)

        stored_extras = load_slider_values()
        if isinstance(stored_extras.get("surf_web"), bool):
            self._surf_web_wanted = stored_extras["surf_web"]
            self.surf_web_btn.blockSignals(True)
            self.surf_web_btn.setChecked(self._surf_web_wanted)
            self.surf_web_btn.blockSignals(False)
            self.settings["surf_web"] = self._surf_web_wanted
            self._style_surf_web_btn("dark")
        effort = stored_extras.get("reasoning_effort")
        if isinstance(effort, str) and effort.strip():
            self._reasoning_wanted = effort.strip().lower()

        self._param_sliders = [
            self.context_window_slider,
            self.max_tokens_slider,
            self.temp_slider,
            self.freq_pen_slider,
            self.pres_pen_slider,
            self.topk_slider,
            self.topp_slider,
            self.rep_pen_slider,
            self.minp_slider,
            self.topa_slider,
        ]

        # Built after the parameter sliders so its speed sliders share their theming.
        voice_section = self._build_vocal_section(_make_slider_row)

        # Appearance section (theme)
        appearance_section, appearance_card = self.make_section("Appearance", "mdi.palette")
        self.theme_hint_label = QLabel("Theme")
        self.theme_hint_label.setStyleSheet(
            "color: #707070; font-family: Inter; font-size: 12px; border: none;"
        )
        appearance_card.addWidget(self.theme_hint_label)

        theme_row = QWidget()
        theme_row.setStyleSheet("background-color: transparent; border: none;")
        theme_row_layout = QHBoxLayout(theme_row)
        theme_row_layout.setContentsMargins(0, 0, 0, 0)
        theme_row_layout.setSpacing(12)

        self._theme_light_btn = QPushButton("Light")
        self._theme_dark_btn = QPushButton("Dark")
        for btn in (self._theme_light_btn, self._theme_dark_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(38)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._theme_light_btn.clicked.connect(lambda: self._apply_theme_selection("light"))
        self._theme_dark_btn.clicked.connect(lambda: self._apply_theme_selection("dark"))

        theme_row_layout.addWidget(self._theme_light_btn, 1)
        theme_row_layout.addWidget(self._theme_dark_btn, 1)
        appearance_card.addWidget(theme_row)

        content_layout.addWidget(model_section, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addWidget(voice_section, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addWidget(
            appearance_section, 0, Qt.AlignmentFlag.AlignHCenter
        )

        self._section_widgets = [
            hotkey_section,
            voice_section,
            model_section,
            appearance_section,
        ]
        self._update_section_card_widths()

        # Runs once the event loop starts, so the error banner can measure the tab.
        QTimer.singleShot(0, self.load_saved_keys)

    @staticmethod
    def _populate_device_combo(combo, devices, selected):
        """Fill a combo with 'System default' plus every device index."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("System default", None)
        for index, name in devices:
            combo.addItem(name, index)
        position = combo.findData(selected)
        combo.setCurrentIndex(position if position >= 0 else 0)
        combo.blockSignals(False)

    def _on_input_device_changed(self, position: int):
        device = self.input_select.itemData(position)
        self.settings["input_device"] = device
        set_input_device(device)
        self._store_app_settings()
        if self._mic_monitor.running:
            self._start_mic_test()

    def _on_output_device_changed(self, position: int):
        device = self.output_select.itemData(position)
        self.settings["output_device"] = device
        set_output_device(device)
        self._store_app_settings()
        if self._mic_monitor.running:
            self._start_mic_test()

    def _store_app_settings(self):
        def device_name(combo):
            return combo.currentText() if combo.currentData() is not None else ""

        store_app_settings({
            "hotkey": self.settings["hotkey"],
            "stop_hotkey": self.settings["stop_hotkey"],
            "theme": self.settings["theme"],
            "prompt": self.settings.get("prompt") or "",
            "input_device_name": device_name(self.input_select),
            "output_device_name": device_name(self.output_select),
            "mic_threshold": self.settings["mic_threshold"],
            "followup_window_s": self.settings["followup_window_s"],
        })

    def _store_slider_values(self):
        store_slider_values({
            **{key: self.settings[key] for key in self._preset_sliders},
            "surf_web": self._surf_web_wanted,
            "reasoning_effort": self._reasoning_wanted,
        })

    def _on_slider_value_typed(self, slider, scale: int, field: QLineEdit):
        try:
            value = round(float(field.text().replace(",", "")) * scale)
        except (ValueError, OverflowError):
            value = slider.value()
        slider.setValue(max(slider.minimum(), min(slider.maximum(), value)))
        # Re-emit so the field shows the formatted, clamped value even if unchanged.
        slider.valueChanged.emit(slider.value())

    @staticmethod
    def _slider_value_style(p: dict) -> str:
        return f"""
            QLineEdit {{
                background-color: transparent;
                border: 1px solid {p['chip_unsel_border']};
                border-radius: 4px;
                color: {p['mid_text']};
                padding: 0 4px;
                font-family: Inter;
                font-size: 12px;
            }}
            QLineEdit:hover {{ border-color: {p['dim_text']}; }}
            QLineEdit:focus {{ border-color: {ACCENT_GREEN}; }}
        """

    def _reset_sliders(self):
        for slider, value in self._slider_defaults.items():
            slider.setValue(value)

    def _on_context_window_slider_changed(self, v: int):
        self.context_window_value.setText(f"{v:,}")
        self.settings["context_window"] = v
        self.max_tokens_slider.setMaximum(max(256, v))

    def _on_max_tokens_slider_changed(self, v: int):
        self.max_tokens_value.setText(f"{v:,}")
        self.settings["max_tokens"] = v

    def _on_surf_web_toggled(self, on: bool):
        if not self.surf_web_btn.isEnabled():
            self._style_surf_web_btn(self.settings.get("theme", "dark"))
            return
        self._surf_web_wanted = on
        self.settings["surf_web"] = on
        self._store_slider_values()
        self._style_surf_web_btn(self.settings.get("theme", "dark"))

    def _on_reasoning_changed(self, _index: int):
        effort = self.reasoning_combo.currentData() or "off"
        if self.reasoning_combo.isEnabled():
            self._reasoning_wanted = effort
        self.settings["reasoning_effort"] = effort
        self._store_slider_values()

    def _style_surf_web_btn(self, theme: str):
        self.surf_web_btn.set_theme(theme)

    def _fill_reasoning_combo(self, efforts, mandatory: bool):
        combo = self.reasoning_combo
        combo.blockSignals(True)
        combo.clear()
        if not efforts:
            combo.addItem("Unavailable", "off")
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
            combo.setMaximumWidth(148)
            self.settings["reasoning_effort"] = "off"
            combo.blockSignals(False)
            return
        if not mandatory:
            combo.addItem("Off", "off")
        labels = dict(_REASONING_EFFORTS)
        for effort in efforts:
            combo.addItem(labels.get(effort, effort.capitalize()), effort)
        values = [combo.itemData(i) for i in range(combo.count())]
        wanted = self._reasoning_wanted
        if wanted in values:
            combo.setCurrentIndex(values.index(wanted))
        elif "medium" in values:
            combo.setCurrentIndex(values.index("medium"))
        else:
            combo.setCurrentIndex(0)
        combo.setEnabled(True)
        combo.setMaximumWidth(108)
        self.settings["reasoning_effort"] = combo.currentData() or "off"
        combo.blockSignals(False)

    def _apply_model_capabilities(self):
        """Match context max, surf, and reasoning controls to the selected vision model."""
        model = self.settings.get("model") or self.model_select.currentText()
        info = self._vision_models.get(model) or {}
        ctx = info.get("context_length") or _CONTEXT_MAX
        ctx = max(_CONTEXT_MIN, ctx)
        self.context_window_slider.setMaximum(ctx)
        if self.context_window_slider.value() > ctx:
            self.context_window_slider.setValue(ctx)

        can_search = bool(info.get("can_search"))
        self.surf_web_btn.blockSignals(True)
        self.surf_web_btn.setEnabled(can_search)
        self.surf_web_btn.setChecked(can_search and self._surf_web_wanted)
        self.surf_web_btn.blockSignals(False)
        self.settings["surf_web"] = bool(can_search and self._surf_web_wanted)
        self.surf_web_btn.setToolTip(
            "Lets Yogi look things up on the internet when it needs current facts."
            if can_search else "This model can't search the web."
        )
        self._style_surf_web_btn(self.settings.get("theme", "dark"))

        efforts, mandatory = reasoning_efforts(info)
        self._fill_reasoning_combo(efforts, mandatory)

    def _on_temperature_slider_changed(self, v: int):
        t = v / 100.0
        self.temp_value.setText(f"{t:.2f}")
        self.settings["temperature"] = t

    def _on_frequency_penalty_slider_changed(self, v: int):
        f = v / 100.0
        self.freq_pen_value.setText(f"{f:.2f}")
        self.settings["frequency_penalty"] = f

    def _on_presence_penalty_slider_changed(self, v: int):
        p = v / 100.0
        self.pres_pen_value.setText(f"{p:.2f}")
        self.settings["presence_penalty"] = p

    def _on_topk_slider_changed(self, v: int):
        self.topk_value.setText(str(v))
        self.settings["top_k"] = v

    def _on_topp_slider_changed(self, v: int):
        p = v / 100.0
        self.topp_value.setText(f"{p:.2f}")
        self.settings["top_p"] = p

    def _on_repetition_penalty_slider_changed(self, v: int):
        r = v / 100.0
        self.rep_pen_value.setText(f"{r:.2f}")
        self.settings["repetition_penalty"] = r

    def _on_min_p_slider_changed(self, v: int):
        p = v / 100.0
        self.minp_value.setText(f"{p:.2f}")
        self.settings["min_p"] = p

    def _on_top_a_slider_changed(self, v: int):
        a = v / 100.0
        self.topa_value.setText(f"{a:.2f}")
        self.settings["top_a"] = a

    # ── Vocal Model card ─────────────────────────────────────────────────────

    def _build_vocal_section(self, make_slider_row):
        section, card = self.make_section("Vocal Model", "mdi.microphone")
        self._vocal_combos, self._vocal_lines, self._vocal_toggles = [], [], []
        self._vocal_divider_lines = []
        self._vocal_key_rows = {}

        self._provider_buttons = QButtonGroup(self)
        self._provider_radios = {}
        for provider, label in vocal.PROVIDER_LABELS.items():
            radio = QRadioButton(label)
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            radio.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            radio.setStyleSheet(self._toggle_style(theme_palette("dark")))
            radio.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self._provider_buttons.addButton(radio)
            self._provider_radios[provider] = radio
            self._vocal_toggles.append(radio)
            # Left-aligned so the clickable area is the circle plus the label.
            card.addWidget(radio, 0, Qt.AlignmentFlag.AlignLeft)

        # One page per provider; only the selected one is shown, so the card
        # is as tall as that page rather than the tallest one.
        self._vocal_pages = {}
        for provider in vocal.PROVIDER_LABELS:
            page = QWidget()
            page.setStyleSheet("background-color: transparent; border: none;")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 8, 0, 0)
            layout.setSpacing(16)
            self._vocal_pages[provider] = page
            card.addWidget(page)

        self._build_grok_page(self._vocal_pages[vocal.GROK].layout(), make_slider_row)
        self._build_openrouter_page(self._vocal_pages[vocal.OPENROUTER].layout(), make_slider_row)
        self._build_fish_page(self._vocal_pages[vocal.FISH].layout(), make_slider_row)

        current = self.settings["tts_provider"]
        if current not in self._provider_radios:
            current = vocal.GROK
        for provider, radio in self._provider_radios.items():
            radio.toggled.connect(
                lambda on, p=provider: on and self._select_vocal_provider(p)
            )
        self._provider_radios[current].setChecked(True)
        self._select_vocal_provider(current)
        return section

    def _select_vocal_provider(self, provider: str):
        for name, page in self._vocal_pages.items():
            page.setVisible(name == provider)
        self._set_vocal("tts_provider", provider)

    def _build_grok_page(self, page, make_slider_row):
        self._add_vocal_key_row(page, "xai")
        picker = VoicePicker(
            "grok", "grok_voice", "xai", "xAI", vocal.lookup_grok_voice, _VOICE_IDS_SETTINGS_KEY
        )
        page.addWidget(self._vocal_row("Voice", self._build_voice_picker(
            picker, "Voice id, e.g. eve or a custom voice id"
        )))
        page.addWidget(self._vocal_row("Language", self._vocal_combo(
            "grok_language", [(code, f"{name} ({code})") for code, name in vocal.GROK_LANGUAGES]
        )))
        self._add_vocal_speed(page, make_slider_row, "grok_speed", 70, 150)

        page.addWidget(self._vocal_divider("Advanced"))
        page.addWidget(self._vocal_row("Streaming latency", self._vocal_combo(
            "grok_latency", vocal.GROK_LATENCY
        )))
        page.addWidget(self._vocal_row("Text normalization", self._vocal_toggle(
            "grok_text_normalization", "Speak numbers, symbols and abbreviations as words"
        )))
        page.addWidget(self._vocal_row("Timing metadata", self._vocal_toggle(
            "grok_timestamps", "Request per-character timestamps"
        )))

    def _build_openrouter_page(self, page, make_slider_row):
        self._add_vocal_key_row(page, "openrouter_tts")
        self._vocal_key_rows["openrouter_tts"].deleted.connect(self._clear_or_speech_models)
        self._or_models_check_id = 0

        self._or_model = self._vocal_combo("or_model", [])
        self._or_model.currentIndexChanged.connect(lambda _i: self._on_or_model_changed())
        page.addWidget(self._vocal_row("Model", self._or_model))
        self._or_voice = self._vocal_combo("or_voice", [])
        page.addWidget(self._vocal_row("Voice", self._or_voice))
        _row, speed = self._add_vocal_speed(page, make_slider_row, "or_speed", 50, 200)
        speed.setToolTip("Sent only when not 1.00; models without speed control reject it")
        page.addWidget(self._vocal_row("Provider routing", self._vocal_combo(
            "or_data_policy", vocal.OR_DATA_POLICIES
        )))

        page.addWidget(self._vocal_divider("Advanced"))
        style_row = self._vocal_row("Speaking style", self._vocal_combo(
            "or_style", [("", "None")] + [(s, s) for s in vocal.OR_STYLES]
        ))
        page.addWidget(style_row)
        degree_row, _field = self._add_vocal_speed(
            page, make_slider_row, "or_style_degree", 1, 200, title="Style intensity"
        )
        self._or_style_rows = (style_row, degree_row)
        self._or_style_support = {}  # model id -> bool, from its endpoints
        self._clear_or_speech_models()

    def _build_fish_page(self, page, make_slider_row):
        self._add_vocal_key_row(page, "fish_audio")
        page.addWidget(self._vocal_row("Model", self._vocal_combo(
            "fish_model", [(m, m) for m in vocal.FISH_MODELS]
        )))
        picker = VoicePicker(
            "fish", "fish_voice", "fish_audio", "Fish Audio", vocal.lookup_fish_voice,
            "fish_voice_ids",
        )
        page.addWidget(self._vocal_row("Voice", self._build_voice_picker(
            picker, "Voice id from your voices or the Fish Voice Library"
        )))
        self._add_vocal_speed(page, make_slider_row, "fish_speed", 50, 200)
        page.addWidget(self._vocal_row("Streaming", self._vocal_toggle(
            "fish_streaming", "Play audio while it downloads"
        )))
        page.addWidget(self._vocal_row("Voice direction", self._vocal_line(
            "fish_tags", "Put before each sentence, e.g. speak softly, sound amused"
        )))
        tags_row = QWidget()
        tags_row.setStyleSheet("background-color: transparent; border: none;")
        tags_layout = QHBoxLayout(tags_row)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(8)
        tags_layout.addWidget(self._vocal_toggle("fish_llm_tags", "Let yogi add cues."))
        self._fish_cue_prompt_btn = QPushButton()
        self._fish_cue_prompt_btn.setFixedSize(28, 28)
        self._fish_cue_prompt_btn.setIconSize(QSize(16, 16))
        self._fish_cue_prompt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fish_cue_prompt_btn.setToolTip("Edit the prompt that asks Yogi for cues")
        self._fish_cue_prompt_btn.clicked.connect(self._on_fish_cue_prompt_clicked)
        self._style_fish_cue_prompt_btn("dark")
        tags_layout.addWidget(self._fish_cue_prompt_btn)
        tags_layout.addStretch()
        page.addWidget(self._vocal_row("Direction tags", tags_row))

        page.addWidget(self._vocal_divider("Advanced"))
        self._add_vocal_speed(
            page, make_slider_row, "fish_temperature", 0, 100, title="Expressiveness"
        )[1].setToolTip("Temperature 0.00 – 1.00: higher is more varied, lower more consistent")
        self._add_vocal_speed(
            page, make_slider_row, "fish_top_p", 0, 100, title="Top-p"
        )[1].setToolTip("Nucleus sampling 0.00 – 1.00")

    def _style_prompt_import_btn(self, theme: str):
        tokens = _BTN_TOKENS[theme if theme in _BTN_TOKENS else "dark"]
        self.prompt_import_btn.setIcon(qta.icon("mdi.file-plus-outline", color=tokens["icon"]))
        self.prompt_import_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; border-radius: 4px; }"
            f" QPushButton:hover {{ background-color: {tokens['hover'].name()}; }}"
        )

    def _style_fish_cue_prompt_btn(self, theme: str):
        tokens = _BTN_TOKENS[theme if theme in _BTN_TOKENS else "dark"]
        self._fish_cue_prompt_btn.setIcon(qta.icon("mdi.pencil-outline", color=tokens["icon"]))
        self._fish_cue_prompt_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; border-radius: 4px; }"
            f" QPushButton:hover {{ background-color: {tokens['hover'].name()}; }}"
        )

    def _on_fish_cue_prompt_clicked(self):
        default = vocal.default_fish_tag_prompt(self.settings)
        dialog = PromptEditorDialog(
            self,
            self.settings["fish_cue_prompt"] or default,
            self.settings.get("theme", "dark"),
            "Added to the prompt when Yogi may write voice cues. Clear it to restore the default.",
        )
        if not dialog.exec():
            return
        text = dialog.text().strip()
        # Stored empty, the default keeps following the model's bracket style.
        self._set_vocal("fish_cue_prompt", "" if text == default else text)

    def _set_vocal(self, key: str, value):
        self.settings[key] = value
        store_vocal_settings({k: self.settings[k] for k in vocal.DEFAULTS})

    def _vocal_row(self, title: str, widget: QWidget) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background-color: transparent; border: none;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setStyleSheet("color: #707070; font-family: Inter; font-size: 12px; border: none;")
        label.setFixedWidth(120)
        self._slider_title_labels.append(label)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return row

    def _vocal_divider(self, title: str) -> QWidget:
        """Titled horizontal rule between groups of vocal settings."""
        row = QWidget()
        row.setStyleSheet("background-color: transparent; border: none;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setStyleSheet("color: #707070; font-family: Inter; font-size: 12px; border: none;")
        self._slider_title_labels.append(label)

        def add_line():
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet("background-color: #333333; border: none;")
            self._vocal_divider_lines.append(line)
            layout.addWidget(line, 1)

        add_line()
        layout.addWidget(label)
        add_line()
        return row

    def _vocal_combo(self, key: str, options, editable: bool = False, combo=None):
        """options: [(value, label)]. An editable combo stores whatever text is typed."""
        if combo is None:
            combo = NoWheelComboBox()
            combo.setEditable(editable)
        combo.setFixedHeight(32)
        combo.setStyleSheet(self._combo_style_from_palette(theme_palette("dark")))
        self._vocal_combos.append(combo)
        self._fill_vocal_combo(combo, key, options)
        if isinstance(combo, IdComboBox):
            combo.id_text_changed.connect(lambda text, k=key: self._set_vocal(k, text))
        elif combo.isEditable():
            combo.currentTextChanged.connect(lambda text, k=key: self._set_vocal(k, text.strip()))
        else:
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, k=key: self._set_vocal(k, c.currentData())
            )
        return combo

    def _fill_vocal_combo(self, combo, key: str, options):
        """Refill a combo, keeping the saved value; a stale saved value falls back to the first item."""
        combo.blockSignals(True)
        combo.clear()
        for value, label in options:
            combo.addItem(label, value)
        if combo.isEditable():
            combo.setEditText(str(self.settings[key]))
        elif combo.count():
            index = combo.findData(self.settings[key])
            combo.setCurrentIndex(max(index, 0))
            if index < 0:
                self._set_vocal(key, combo.currentData())
        combo.blockSignals(False)

    def _vocal_line(self, key: str, placeholder: str) -> QLineEdit:
        field = QLineEdit(self.settings[key])
        field.setFixedHeight(32)
        field.setPlaceholderText(placeholder)
        field.setStyleSheet(self._line_edit_style_from_palette(theme_palette("dark")))
        field.editingFinished.connect(lambda f=field, k=key: self._set_vocal(k, f.text().strip()))
        self._vocal_lines.append(field)
        return field

    def _vocal_toggle(self, key: str, text: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(self.settings[key]))
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.setStyleSheet(self._toggle_style(theme_palette("dark")))
        box.toggled.connect(lambda on, k=key: self._set_vocal(k, on))
        self._vocal_toggles.append(box)
        return box

    def _add_vocal_speed(
        self, page, make_slider_row, key: str, low: int, high: int, title: str = "Speech speed"
    ):
        """Slider in hundredths, low..high. Returns (row, value field)."""
        row, slider, field = make_slider_row(title, f"{self.settings[key]:.2f}")
        slider.setRange(low, high)
        slider.setValue(round(self.settings[key] * 100))
        slider.setStyleSheet(self._slider_stylesheet_from_palette(theme_palette("dark")))

        def changed(v: int):
            field.setText(f"{v / 100:.2f}")
            self._set_vocal(key, v / 100)

        slider.valueChanged.connect(changed)
        field.setToolTip(f"{low / 100:.2f} – {high / 100:.2f}")
        field.editingFinished.connect(lambda: self._on_slider_value_typed(slider, 100, field))
        self._param_sliders.append(slider)
        page.addWidget(row)
        return row, field

    def _add_vocal_key_row(self, page, provider_id: str):
        row = ApiKeyRow(key_store.PROVIDERS_BY_ID[provider_id])
        row.input.setStyleSheet(self._line_edit_style_from_palette(theme_palette("dark")))
        row.submitted.connect(lambda key, r=row: self._on_vocal_key_submitted(r, key))
        row.storage_failed.connect(self._show_error_banner)
        self._vocal_key_rows[provider_id] = row
        page.addWidget(row)

    @staticmethod
    def _toggle_style(p: dict) -> str:
        return f"""
            QCheckBox, QRadioButton {{
                color: {p['mid_text']};
                background-color: transparent;
                border: none;
                font-family: Inter;
                font-size: 13px;
                spacing: 10px;
            }}
            QCheckBox::indicator, QRadioButton::indicator {{
                width: 12px;
                height: 12px;
                border: 1px solid {p['chip_unsel_border']};
                background-color: {p['input_bg']};
            }}
            QCheckBox::indicator {{ border-radius: 3px; }}
            QRadioButton::indicator {{ border-radius: 7px; }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                background-color: {ACCENT_GREEN};
                border-color: {ACCENT_GREEN};
            }}
            QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
                border-color: {ACCENT_GREEN};
            }}
        """

    def _load_vocal_keys(self):
        for provider_id, row in self._vocal_key_rows.items():
            try:
                key = row.load_saved()
            except key_store.KeyStoreError as e:
                self._show_error_banner(str(e))
                continue
            if provider_id in self._VOCAL_KEY_CHECKS and key:
                self._check_vocal_key(provider_id, key, save=False)

    def _load_or_speech_models(self):
        """Fill the OpenRouter model list; called only once its key is verified."""
        self._or_models_check_id += 1
        check_id = self._or_models_check_id
        self._or_model.setPlaceholderText("Loading speech models…")

        def work():
            models, error = vocal.fetch_openrouter_speech_models()
            self._vocal_checked.emit("or_models", check_id, models, error or "")

        threading.Thread(target=work, daemon=True).start()

    def _clear_or_speech_models(self):
        self._or_models_check_id += 1
        self._or_speech_models = {}
        for combo in (self._or_model, self._or_voice):
            combo.blockSignals(True)
            combo.clear()
            combo.blockSignals(False)
            combo.setEnabled(False)
        self._or_model.setPlaceholderText("Connect an API key to load models")
        self._or_voice.setPlaceholderText("Pick a model first")
        self._set_or_style_enabled(False)

    def _on_vocal_key_submitted(self, row: ApiKeyRow, key: str):
        if not key:
            self._show_error_banner("API key is empty - paste a key and click Connect.")
            return
        if row.provider.id in self._VOCAL_KEY_CHECKS:
            self._check_vocal_key(row.provider.id, key, save=True)
            return
        # A provider without a key check is saved as-is; a bad key shows up on the first reply.
        try:
            row.save(key)
        except key_store.KeyStoreError as e:
            self._show_error_banner(str(e))

    # key_store provider id -> check(key) returning (result, None) or (None, error)
    _VOCAL_KEY_CHECKS = {
        "xai": vocal.fetch_grok_voices,
        "openrouter_tts": vocal.verify_openrouter_key,
        "fish_audio": vocal.fetch_fish_voices,
    }

    def _check_vocal_key(self, provider_id: str, key: str, save: bool):
        check_id = self._vocal_key_check_ids.get(provider_id, 0) + 1
        self._vocal_key_check_ids[provider_id] = check_id
        self._pending_vocal_keys[provider_id] = key if save else None
        self._vocal_key_rows[provider_id].set_busy(True)
        check = self._VOCAL_KEY_CHECKS[provider_id]

        def work():
            result, error = check(key)
            self._vocal_checked.emit(provider_id, check_id, result, error or "")

        threading.Thread(target=work, daemon=True).start()

    def _on_vocal_checked(self, kind: str, check_id: int, result, error: str):
        if kind == "or_models":
            if check_id != self._or_models_check_id:
                return  # key deleted or reconnected since
            if result is None:
                print("OpenRouter speech models:", error)
                self._or_model.setPlaceholderText("Couldn't load speech models")
                return
            self._or_speech_models = result
            self._fill_vocal_combo(self._or_model, "or_model", [(m, m) for m in result])
            self._or_model.setEnabled(True)
            self._fill_or_voices()
            self._refresh_or_style_support()
            return
        if kind == "or_style":
            self._on_or_style_checked(*result, error)
            return
        if kind == "voice":
            self._on_voice_looked_up(*result, error)
            return

        if check_id != self._vocal_key_check_ids.get(kind):
            return
        row = self._vocal_key_rows[kind]
        row.set_busy(False)
        key = self._pending_vocal_keys.pop(kind, None)
        if result is None:
            self._show_error_banner(error)
            return
        if key is not None:
            try:
                row.save(key)
            except key_store.KeyStoreError as e:
                self._show_error_banner(str(e))
                return
            self._show_success_banner("Connection successful")
        if kind == "openrouter_tts":
            self._load_or_speech_models()
        picker = next((p for p in self._voice_pickers.values() if p.key_id == kind), None)
        if picker is None:
            return
        if kind == "fish_audio":
            picker.account = dict(result)
            self._fill_voices(picker)
        unnamed = [vid for vid, name in picker.saved.items() if name == vid]
        if unnamed:
            self._lookup_voices(picker, unnamed, announce=False)

    # ── Saved-voice dropdowns (Grok, Fish Audio) ─────────────────────────────

    def _build_voice_picker(self, picker: VoicePicker, placeholder: str) -> IdComboBox:
        current = self.settings[picker.setting].strip()
        if current and current not in picker.saved:
            picker.saved[current] = current
            store_voice_ids(picker.saved, picker.store_key)
        picker.combo = self._vocal_combo(
            picker.setting, [], combo=IdComboBox("Add a new voice id")
        )
        picker.combo.lineEdit().setPlaceholderText(placeholder)
        picker.combo.add_requested.connect(lambda vid, p=picker: self._add_voice(p, vid))
        picker.delegate = DeletableItemDelegate(picker.combo, parts=("trash",))
        picker.delegate.delete_requested.connect(
            lambda row, p=picker: self._on_voice_delete_requested(p, row)
        )
        self._voice_pickers[picker.name] = picker
        self._fill_voices(picker)
        return picker.combo

    def _fill_voices(self, picker: VoicePicker):
        """"Add a new voice id" and the account's voices (locked), then added ids (deletable)."""
        combo = picker.combo
        voices = {**picker.account, **{
            vid: name for vid, name in picker.saved.items() if vid not in picker.account
        }}
        names = list(voices.values())
        options = [("", combo.add_label)] + [
            # A repeated name gets its id appended so each label maps to one voice.
            (vid, name if names.count(name) == 1 else f"{name} ({vid})")
            for vid, name in voices.items()
        ]
        picker.delegate.locked_rows = set(range(len(picker.account) + 1))
        self._fill_vocal_combo(combo, picker.setting, options)
        index = combo.findData(self.settings[picker.setting])
        if index > 0:
            combo.setEditText(combo.itemText(index))
        combo.sync_add_button()

    def _add_voice(self, picker: VoicePicker, voice_id: str):
        if voice_id and voice_id not in picker.saved and voice_id not in picker.account:
            picker.combo.set_adding(True)
            self._lookup_voices(picker, [voice_id], announce=True)

    def _lookup_voices(self, picker: VoicePicker, voice_ids: list, announce: bool):
        """Check ids with the provider off the UI thread. announce: report failures in the banner."""

        def work():
            try:
                key = key_store.get_key(picker.key_id)
            except key_store.KeyStoreError as e:
                key, error = None, str(e)
            else:
                error = f"Connect your {picker.key_label} API key first."
            for voice_id in voice_ids:
                name = None
                if key:
                    name, error = picker.lookup(key, voice_id)
                self._vocal_checked.emit(
                    "voice", 0, (picker.name, voice_id, name, announce), error or ""
                )

        threading.Thread(target=work, daemon=True).start()

    def _on_voice_looked_up(self, picker_name: str, voice_id: str, name, announce: bool, error: str):
        picker = self._voice_pickers[picker_name]
        if announce:
            picker.combo.set_adding(False)
        if name is None:
            if announce:
                self._show_error_banner(error)
            return
        if not announce and voice_id not in picker.saved:
            return  # deleted while the name was loading
        old = picker.saved.get(voice_id)
        picker.saved[voice_id] = name
        if not store_voice_ids(picker.saved, picker.store_key):
            if old is None:
                del picker.saved[voice_id]
            else:
                picker.saved[voice_id] = old
            self._show_error_banner("Couldn't save voice ids - Check app permissions.")
            return
        self._fill_voices(picker)

    def _on_voice_delete_requested(self, picker: VoicePicker, row: int):
        picker.combo.hidePopup()
        voice_id = picker.combo.itemData(row)
        ConfirmOverlay(
            self.window(),
            f"Are you sure you want to delete the voice \"{picker.combo.itemText(row)}\"?",
            "Delete",
            lambda: self._delete_voice(picker, voice_id),
            self.settings.get("theme", "dark"),
        )

    def _delete_voice(self, picker: VoicePicker, voice_id: str):
        if voice_id not in picker.saved:
            return
        before = dict(picker.saved)
        del picker.saved[voice_id]
        if not store_voice_ids(picker.saved, picker.store_key):
            picker.saved = before
            self._show_error_banner("Couldn't save voice ids - Check app permissions.")
            return
        if self.settings[picker.setting] == voice_id:
            remaining = [*picker.account, *picker.saved]
            self._set_vocal(picker.setting, remaining[0] if remaining else "")
        self._fill_voices(picker)

    def _on_or_model_changed(self):
        # The old model's voice id rarely exists on the new one.
        voices = self._or_speech_models.get(self.settings["or_model"], [])
        if self.settings["or_voice"] not in voices:
            self._set_vocal("or_voice", voices[0] if voices else "")
        self._fill_or_voices()
        self._refresh_or_style_support()

    def _refresh_or_style_support(self):
        """Grey out Speaking style and Style intensity until the model is known to support them."""
        model = self.settings["or_model"]
        if model in self._or_style_support:
            self._set_or_style_enabled(self._or_style_support[model])
            return
        self._set_or_style_enabled(False)
        if not model:
            return

        def work():
            supported, error = vocal.openrouter_style_supported(model)
            self._vocal_checked.emit("or_style", 0, (model, supported), error or "")

        threading.Thread(target=work, daemon=True).start()

    def _on_or_style_checked(self, model: str, supported, error: str):
        if supported is None:
            print("OpenRouter style support:", error)
            return
        self._or_style_support[model] = supported
        if model == self.settings["or_model"]:
            self._set_or_style_enabled(supported)

    def _set_or_style_enabled(self, enabled: bool):
        # A disabled row takes no clicks or typing; the opacity makes that visible.
        for row in self._or_style_rows:
            row.setEnabled(enabled)
            effect = row.graphicsEffect()
            if effect is None:
                effect = QGraphicsOpacityEffect(row)
                row.setGraphicsEffect(effect)
            effect.setOpacity(1.0 if enabled else 0.4)
            row.setToolTip("" if enabled else "Not supported by this model")

    def _fill_or_voices(self):
        """Voices differ per OpenRouter model. A model listing none gets its provider's default voice."""
        voices = self._or_speech_models.get(self.settings["or_model"], [])
        options = [(v, v) for v in voices] or [("", "Model default")]
        self._fill_vocal_combo(self._or_voice, "or_voice", options)
        self._or_voice.setEnabled(bool(self.settings["or_model"]))

    def _update_section_card_widths(self):
        inner = max(
            0,
            self._content.width() - 2 * self._content_h_margin
        )
        if inner <= 0:
            return
        # Cap card width so forms don't stretch edge-to-edge on wide windows.
        w = min(int(inner), 760)
        if w < 1:
            return
        for section in self._section_widgets:
            section.setFixedWidth(w)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_section_card_widths()

    def make_section(self, title, icon_name):
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(12)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon(icon_name, color="#aaaaaa").pixmap(18, 18))
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #A1A1A1; font-family: Inter; border: none;")
        title_label.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        header_layout.addWidget(icon_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        section_layout.addWidget(header)

        card = QWidget()
        card.setStyleSheet("""
            QWidget {
                background-color: #252525;
                border-radius: 8px;
                border: 1px solid #333333;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(16)
        section_layout.addWidget(card)

        section._icon_name = icon_name
        section._header_icon_label = icon_label
        section._header_title_label = title_label
        section._card_widget = card

        return section, card_layout

    def apply_theme(self, theme: str):
        if theme not in ("light", "dark"):
            theme = "dark"
        self.settings["theme"] = theme
        self._store_app_settings()
        p = theme_palette(theme)

        self.setStyleSheet(f"background-color: {p['window_bg']};")
        self._scroll.setStyleSheet(self._scroll_stylesheet_from_palette(p))

        for section in self._section_widgets:
            section._card_widget.setStyleSheet(
                f"""
                QWidget {{
                    background-color: {p['card_bg']};
                    border-radius: 8px;
                    border: 1px solid {p['card_border']};
                }}
                """
            )
            section._header_icon_label.setPixmap(
                qta.icon(section._icon_name, color=p["icon_color"]).pixmap(18, 18)
            )
            section._header_title_label.setStyleSheet(
                f"color: {p['section_title']}; font-family: Inter; border: none;"
            )

        self.hotkey_input.setStyleSheet(self._line_edit_style_from_palette(p))
        self.stop_hotkey_input.setStyleSheet(self._line_edit_style_from_palette(p))
        self.stop_record_btn.set_theme(theme)
        self.prompt_field.setStyleSheet(self._line_edit_style_from_palette(p))
        self.prompt_select.setStyleSheet(self._combo_style_from_palette(p))
        self._prompt_delegate.theme = theme
        for picker in self._voice_pickers.values():
            picker.delegate.theme = theme
            picker.combo.set_theme(theme)
        self.model_select.setStyleSheet(self._combo_style_from_palette(p))
        self.reasoning_combo.setStyleSheet(self._combo_style_from_palette(p))
        self._style_surf_web_btn(theme)
        self.input_select.setStyleSheet(self._combo_style_from_palette(p))
        self.output_select.setStyleSheet(self._combo_style_from_palette(p))
        for combo in self._vocal_combos:
            combo.setStyleSheet(self._combo_style_from_palette(p))
        for field in self._vocal_lines:
            field.setStyleSheet(self._line_edit_style_from_palette(p))
        for toggle in self._vocal_toggles:
            toggle.setStyleSheet(self._toggle_style(p))
        self._style_fish_cue_prompt_btn(theme)
        self._style_prompt_import_btn(theme)
        for row in self._vocal_key_rows.values():
            row.set_theme(
                theme,
                self._line_edit_style_from_palette(p),
                f"color: {p['dim_text']}; font-family: Inter; font-size: 12px; border: none;",
            )

        self.mic_threshold_slider.set_theme(theme)
        self.mic_test_btn.set_theme(theme)
        for lbl in (
            self.hotkey_hint_label,
            self.stop_hotkey_hint_label,
            self.input_hint_label,
            self.output_hint_label,
            self.mic_threshold_hint_label,
            self.mic_threshold_value_label,
            self.followup_hint_label,
            self.followup_value_label,
            self.model_hint_label,
            self.prompt_hint_label,
            self.reasoning_hint_label,
            self.theme_hint_label,
        ):
            lbl.setStyleSheet(
                f"color: {p['dim_text']}; font-family: Inter; font-size: 12px; border: none;"
            )

        for lbl in self._slider_title_labels:
            lbl.setStyleSheet(
                f"color: {p['dim_text']}; font-family: Inter; font-size: 12px; border: none;"
            )
        for line in self._vocal_divider_lines:
            line.setStyleSheet(f"background-color: {p['card_border']}; border: none;")
        for field in self._slider_value_labels:
            field.setStyleSheet(self._slider_value_style(p))

        ss = self._slider_stylesheet_from_palette(p)
        for s in self._param_sliders:
            s.setStyleSheet(ss)
        self.followup_slider.setStyleSheet(ss)

        self.record_btn.set_theme(theme)
        self.reset_sliders_btn.set_theme(theme)
        self.api_key_row.set_theme(
            theme,
            self._line_edit_style_from_palette(p),
            f"color: {p['dim_text']}; font-family: Inter; font-size: 12px; border: none;",
        )

        self._refresh_theme_chips(p)

    def _apply_theme_selection(self, theme: str):
        if theme not in ("light", "dark"):
            return
        if self.settings["theme"] == theme:
            return
        self.theme_changed.emit(theme)

    def _refresh_theme_chips(self, p: dict):
        t = self.settings["theme"]
        self._theme_light_btn.setStyleSheet(self._theme_chip_style(t == "light", p))
        self._theme_dark_btn.setStyleSheet(self._theme_chip_style(t == "dark", p))

    def _theme_chip_style(self, active: bool, p: dict) -> str:
        if active:
            return f"""
                QPushButton {{
                    background-color: {p['chip_sel_bg']};
                    border: 2px solid {ACCENT_GREEN};
                    border-radius: 8px;
                    color: {ACCENT_GREEN};
                    padding: 10px 18px;
                    font-family: Inter;
                    font-size: 13px;
                    font-weight: 600;
                }}
                QPushButton:focus {{ outline: none; }}
            """
        return f"""
            QPushButton {{
                background-color: {p['chip_bg']};
                border: 1px solid {p['chip_unsel_border']};
                border-radius: 8px;
                color: {p['chip_unsel_text']};
                padding: 10px 18px;
                font-family: Inter;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: {ACCENT_GREEN};
                color: {ACCENT_GREEN};
            }}
            QPushButton:focus {{ outline: none; }}
        """

    def _scroll_stylesheet_from_palette(self, p: dict) -> str:
        track = (
            "rgba(255, 255, 255, 0.05)"
            if self.settings["theme"] == "dark"
            else "rgba(0, 0, 0, 0.04)"
        )
        return scrollbar_stylesheet(track, p["scroll_handle"], p["scroll_handle_hover"])

    def _line_edit_style_from_palette(self, p: dict) -> str:
        return line_edit_stylesheet(p["input_bg"], p["input_border"], p["input_text"])

    def _combo_style_from_palette(self, p: dict) -> str:
        return combo_stylesheet(
            p["input_bg"], p["input_border"], p["input_text"], p["chip_sel_bg"]
        )

    def _slider_stylesheet_from_palette(self, p: dict) -> str:
        return slider_stylesheet(
            p["slider_groove"],
            p["slider_track_rest"],
            p["slider_handle"],
            p["slider_handle_hover"],
        )

    def _show_api_error(self, message: str):
        """Wipe the model dropdown and show the red error banner from the top."""
        self._clear_models()
        self._show_error_banner(message)

    def _show_success_banner(self, message: str):
        self._show_error_banner(message, success=True)

    def _show_error_banner(self, message: str, success: bool = False):
        self._error_timer.stop()
        if self._error_anim is not None:
            self._error_anim.stop()

        self._error_banner.setStyleSheet(
            f"background-color: {'#16a34a' if success else '#dc2626'}; color: #ffffff;"
            " border-radius: 8px; padding: 10px 18px; font-family: Inter;"
            " font-size: 13px; font-weight: 600; border: none;"
        )
        self._error_banner.setText(message)
        self._error_banner.adjustSize()
        max_w = max(200, self.width() - 80)
        if self._error_banner.width() > max_w:
            self._error_banner.setFixedWidth(max_w)
        x = (self.width() - self._error_banner.width()) // 2
        h = self._error_banner.height()
        self._error_banner.move(x, -h)
        self._error_banner.raise_()
        self._error_banner.show()

        pos_anim = QPropertyAnimation(self._error_banner, b"pos")
        pos_anim.setDuration(300)
        pos_anim.setStartValue(QPoint(x, -h))
        pos_anim.setEndValue(QPoint(x, 12))
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        fade_anim = QPropertyAnimation(self._error_opacity, b"opacity")
        fade_anim.setDuration(300)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)

        self._error_anim = QParallelAnimationGroup(self)
        self._error_anim.addAnimation(pos_anim)
        self._error_anim.addAnimation(fade_anim)
        self._error_anim.start()

        self._error_timer.start(4500)

    def _hide_error_banner(self):
        self._error_timer.stop()
        if not self._error_banner.isVisible():
            return
        fade = QPropertyAnimation(self._error_opacity, b"opacity")
        fade.setDuration(250)
        fade.setStartValue(self._error_opacity.opacity())
        fade.setEndValue(0.0)
        fade.finished.connect(self._error_banner.hide)
        self._error_anim = fade
        fade.start()

    def _on_prompt_field_clicked(self):
        dialog = PromptEditorDialog(self, "", self.settings.get("theme", "dark"))
        if dialog.exec() and dialog.text().strip():
            self.settings["prompt"] = dialog.text().strip()
            self._save_current_prompt()

    def _on_prompt_edit_requested(self, row: int):
        self.prompt_select.hidePopup()
        if not 0 <= row < len(self._saved_prompts):
            return
        preset = self._saved_prompts[row]
        dialog = PromptEditorDialog(self, preset["prompt"], self.settings.get("theme", "dark"))
        text = dialog.text().strip() if dialog.exec() else ""
        if not text or text == preset["prompt"]:
            return
        old = preset["prompt"]
        preset["prompt"] = text
        if not self._persist_saved_prompts():
            preset["prompt"] = old
            return
        selected = self.prompt_select.currentIndex() - 1
        if selected == row:
            self.settings["prompt"] = text
        self._populate_saved_prompts(selected)

    def _populate_saved_prompts(self, select_row: int = -1):
        """select_row is a saved-prompt index; -1 selects Default."""
        self.prompt_select.clear()
        # Default is combo row 0; an empty prompt makes yogi use its _SYSTEM_PROMPT.
        self.prompt_select.addItem("Default")
        for preset in self._saved_prompts:
            preview = " ".join(preset["prompt"].split())
            self.prompt_select.addItem(preview if len(preview) <= 60 else preview[:60] + "…")
        self.prompt_select.setCurrentIndex(select_row + 1)
        self._store_app_settings()

    def _persist_saved_prompts(self) -> bool:
        if store_saved_prompts(self._saved_prompts):
            return True
        self._show_error_banner("Couldn't save prompts - Check app permissions.")
        return False

    def _save_current_prompt(self):
        prompt = (self.settings.get("prompt") or "").strip()
        if not prompt:
            return
        preset = {
            "prompt": prompt,
            "params": {key: self.settings[key] for key in self._preset_sliders},
        }
        texts = [p["prompt"] for p in self._saved_prompts]
        if prompt in texts:
            row = texts.index(prompt)
            self._saved_prompts[row] = preset
        else:
            self._saved_prompts.append(preset)
            row = len(self._saved_prompts) - 1
        if self._persist_saved_prompts():
            self._populate_saved_prompts(row)

    def _on_import_prompt_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import prompt", "", "Prompt files (*.txt *.json)"
        )
        if path:
            self.import_prompt_file(path)

    def import_prompt_file(self, path) -> int:
        """Add the file's prompts to the dropdown. Returns how many were new."""
        presets, error = parse_prompt_file(path)
        if error:
            self._show_error_banner(error)
            return 0
        known = {p["prompt"] for p in self._saved_prompts}
        added = []
        for preset in presets:
            if preset["prompt"] not in known:
                preset["params"] = {
                    k: v for k, v in preset["params"].items() if k in self._preset_sliders
                }
                known.add(preset["prompt"])
                added.append(preset)
        if not added:
            self._show_error_banner("Those prompts are already in the list.")
            return 0
        selected = self.prompt_select.currentIndex() - 1
        self._saved_prompts.extend(added)
        if not self._persist_saved_prompts():
            del self._saved_prompts[-len(added):]
            return 0
        self._populate_saved_prompts(selected)
        n = len(added)
        self._show_error_banner(
            f"Imported {n} prompt{'s' if n != 1 else ''} - pick it from the prompt list.",
            success=True,
        )
        return n

    def _on_saved_prompt_selected(self, combo_row: int):
        row = combo_row - 1
        if row == -1:
            self.settings["prompt"] = ""
            self._store_app_settings()
        if not 0 <= row < len(self._saved_prompts):
            return
        preset = self._saved_prompts[row]
        self.settings["prompt"] = preset["prompt"]
        self._store_app_settings()
        for key, value in (preset.get("params") or {}).items():
            if key in self._preset_sliders and isinstance(value, (int, float)):
                slider, scale = self._preset_sliders[key]
                # The slider's valueChanged handler writes self.settings.
                slider.setValue(round(value * scale))

    def _on_prompt_delete_requested(self, row: int):
        self.prompt_select.hidePopup()
        ConfirmOverlay(
            self.window(),
            "Are you sure you want to delete this prompt?",
            "Delete",
            lambda: self._delete_saved_prompt(row),
            self.settings.get("theme", "dark"),
        )

    def _delete_saved_prompt(self, row: int):
        if not 0 <= row < len(self._saved_prompts):
            return
        selected = self.prompt_select.currentIndex() - 1
        removed = self._saved_prompts.pop(row)
        if not self._persist_saved_prompts():
            self._saved_prompts.insert(row, removed)
            return
        if selected == row:
            selected = -1
            self.settings["prompt"] = ""
        elif selected > row:
            selected -= 1
        self._populate_saved_prompts(selected)

    def load_saved_keys(self):
        """Show saved keys and, if OpenRouter has one, load its models in the background."""
        self._load_vocal_keys()
        try:
            key = self.api_key_row.load_saved()
        except key_store.KeyStoreError as e:
            self._show_api_error(str(e))
            return
        if key:
            self._check_openrouter(key, save=False)

    def _on_api_key_submitted(self, key: str):
        # Refresh from scratch on every submit: wipe stale models first.
        self._clear_models()

        if not key:
            print("API key is not valid")
            self._show_api_error("API key is empty - enter a key and click Connect.")
            return

        self._check_openrouter(key, save=True)

    def _on_api_key_deleted(self):
        self._openrouter_check_id += 1
        self._pending_key = None
        self._clear_models()

    def _check_openrouter(self, key: str, save: bool):
        self._openrouter_check_id += 1
        check_id = self._openrouter_check_id
        self._pending_key = key if save else None
        self.api_key_row.set_busy(True)

        def work():
            ids, error = _fetch_openrouter_models(key)
            self._openrouter_checked.emit(check_id, ids, error)

        threading.Thread(target=work, daemon=True).start()

    def _on_openrouter_checked(self, check_id: int, models, error: str):
        if check_id != self._openrouter_check_id:
            return
        key, self._pending_key = self._pending_key, None
        self.api_key_row.set_busy(False)

        if models is None:
            self._show_api_error(error)
            return

        if key is not None:
            try:
                self.api_key_row.save(key)
            except key_store.KeyStoreError as e:
                self._show_api_error(str(e))
                return

        self._vision_models = {}
        ids = []
        for item in models:
            if isinstance(item, str) and item.strip():
                self._vision_models[item] = {
                    "id": item, "context_length": None, "can_search": False, "reasoning": None,
                }
                ids.append(item)
            elif isinstance(item, dict) and item.get("id"):
                self._vision_models[item["id"]] = item
                ids.append(item["id"])
        self._load_models(ids)
        print("OpenRouter OK - Loaded ", len(ids), " vision models")

    def _load_models(self, ids: list):
        self.model_select.blockSignals(True)
        self.model_select.clear()
        self.model_select.addItems(ids)

        # _clear_models wipes settings["model"] before every reload, so prefer the stored pick.
        saved = load_selected_model() or self.settings.get("model", "")
        if saved in ids:
            self.model_select.setCurrentText(saved)
            self.settings["model"] = saved
        elif ids:
            self.model_select.setCurrentIndex(0)
            self.settings["model"] = self.model_select.currentText()

        self.model_select.blockSignals(False)
        self._hide_error_banner()
        self._apply_model_capabilities()

    def _on_model_picked(self):
        model = self.model_select.currentText()
        if not model:
            return
        store_selected_model(model)
        self._apply_model_capabilities()

        def work():
            try:
                key = key_store.get_key("openrouter")
            except key_store.KeyStoreError:
                return
            if key:
                self._model_status_checked.emit(model, _check_openrouter_model_up(key, model) or "")

        threading.Thread(target=work, daemon=True).start()

    def _on_model_status_checked(self, model: str, error: str):
        # A later pick supersedes this result.
        if error and model == self.model_select.currentText():
            self._show_error_banner(error)

    def _clear_models(self):
        self.model_select.blockSignals(True)
        self.model_select.clear()
        self.settings["model"] = ""
        self.model_select.blockSignals(False)
        self._vision_models = {}
        self._apply_model_capabilities()

    def _hotkey_widgets(self, target):
        """(input field, record button) for "hotkey" or "stop_hotkey"."""
        if target == "stop_hotkey":
            return self.stop_hotkey_input, self.stop_record_btn
        return self.hotkey_input, self.record_btn

    def toggle_recording_hotkey(self, target="hotkey"):
        if self.is_recording:
            self.stop_recording_hotkey()
        else:
            self.start_recording_hotkey(target)

    def start_recording_hotkey(self, target="hotkey"):
        self.is_recording = True
        self._recording_target = target
        field, button = self._hotkey_widgets(target)
        field.setText("Press keys...")
        button.setText("Recording...")
        button.setRecording(True)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        # Grab the keyboard so the recording can't silently get stuck if
        # focus moves to another widget mid-recording.
        self.grabKeyboard()

    def stop_recording_hotkey(self):
        self.is_recording = False
        self.releaseKeyboard()
        target = getattr(self, "_recording_target", "hotkey")
        field, button = self._hotkey_widgets(target)
        field.setText(self.settings[target])
        button.setText("Record")
        button.setRecording(False)

    def hideEvent(self, event):
        # If the user switches tabs mid-recording, cancel cleanly.
        if self.is_recording:
            self.stop_recording_hotkey()
        self.stop_mic_test()
        super().hideEvent(event)

    def _on_followup_slider_changed(self, value: int):
        self.settings["followup_window_s"] = value / 2
        self.followup_value_label.setText(f"{value / 2:g} s")
        if not self.followup_slider.isSliderDown():
            self._store_app_settings()

    def _on_app_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self.stop_mic_test()

    def _on_mic_threshold_moved(self, level: float):
        self.mic_threshold_value_label.setText(level_to_db_text(level))
        self._mic_monitor.set_threshold(level)

    def _on_mic_threshold_changed(self, level: float):
        self.settings["mic_threshold"] = level
        set_speech_threshold(level)
        self.mic_threshold_value_label.setText(level_to_db_text(level))
        self._store_app_settings()

    def _toggle_mic_test(self):
        if self._mic_monitor.running:
            self.stop_mic_test()
        else:
            self._start_mic_test()

    def _start_mic_test(self):
        self._mic_monitor.set_threshold(self.mic_threshold_slider.threshold())
        error = self._mic_monitor.start(
            self.settings["input_device"], self.settings["output_device"]
        )
        if error:
            print(f"audio: mic test failed: {error}", flush=True)
            self._show_error_banner(
                "Couldn't open the microphone - check it's connected and "
                "Windows lets apps use it."
            )
            return
        self.mic_test_btn.setText("Stop Test")
        self.mic_test_btn.setRecording(True)
        self.mic_threshold_slider.set_metering(True)
        self._mic_timer.start()

    def stop_mic_test(self):
        """Close the mic test (button, tab switch, app inactive, Yogi turned on)."""
        self._mic_timer.stop()
        self._mic_monitor.stop()
        self.mic_test_btn.setText("Test Microphone")
        self.mic_test_btn.setRecording(False)
        self.mic_threshold_slider.set_metering(False)

    def _on_mic_tick(self):
        if not self._mic_monitor.is_alive():
            self.stop_mic_test()
            self._show_error_banner("Microphone stopped - check it's still connected.")
            return
        self.mic_threshold_slider.push_level(self._mic_monitor.take_level())

    def keyPressEvent(self, event):
        if not self.is_recording:
            super().keyPressEvent(event)
            return

        target = getattr(self, "_recording_target", "hotkey")
        # Esc cancels recording the activation key, but is a valid stop key
        # (cancel that one by clicking the button again).
        if event.key() == Qt.Key.Key_Escape and target == "hotkey":
            self.stop_recording_hotkey()
            return

        modifier_keys = [Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta]
        if event.key() in modifier_keys:
            return

        keys = []
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            keys.append("Ctrl")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            keys.append("Alt")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            keys.append("Shift")

        key_name = Qt.Key(event.key()).name.replace("Key_", "")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if key_name in _SHIFT_NUMBER_ROW_KEY_TO_DIGIT:
                key_name = _SHIFT_NUMBER_ROW_KEY_TO_DIGIT[key_name]
            elif len(key_name) == 1 and key_name.isdigit():
                pass
            else:
                key_name = SHIFT_SYMBOL_MAP.get(key_name, key_name)
        keys.append(key_name)

        hotkey = "+".join(keys)
        other = "stop_hotkey" if target == "hotkey" else "hotkey"
        if hotkey.lower() == str(self.settings[other]).lower():
            self.stop_recording_hotkey()
            self._show_error_banner(
                "That key is already the "
                f"{'Stop' if other == 'stop_hotkey' else 'Activation'} Hotkey - pick another."
            )
            return
        self.settings[target] = hotkey
        self._store_app_settings()
        self.stop_recording_hotkey()
