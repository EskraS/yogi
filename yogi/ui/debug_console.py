"""In-app copy of Yogi's stdout/stderr. F2 shows it.

print() still reaches the real terminal. A ring buffer keeps the same text
for the debug window, including lines printed before the window is opened.
"""

import sys
import threading
import traceback

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from yogi.core import errors
from yogi.ui.settings import theme_palette

# Stuck print loops must not grow without bound.
MAX_LINES = 5000
MAX_BYTES = 512 * 1024

_MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Courier New")

_buffer = None
_installed = False


class LogBuffer(QObject):
    """Thread-safe text log. chunk_ready is emitted after the lock is released."""

    chunk_ready = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._text = ""
        self._seq = 0

    def append(self, text: str):
        if not text:
            return
        with self._lock:
            self._text += text
            self._trim()
            self._seq += 1
            seq = self._seq
        self.chunk_ready.emit(seq, text)

    def snapshot(self):
        """Return (seq, full text). seq is the last chunk included."""
        with self._lock:
            return self._seq, self._text

    def clear(self):
        with self._lock:
            self._text = ""
            self._seq += 1
            return self._seq

    def _trim(self):
        newlines = self._text.count("\n")
        while newlines > MAX_LINES:
            cut = self._text.find("\n")
            if cut == -1:
                break
            self._text = self._text[cut + 1:]
            newlines -= 1
        while self._text and len(self._text.encode("utf-8", "replace")) > MAX_BYTES:
            cut = self._text.find("\n")
            if cut == -1 or cut + 1 >= len(self._text):
                self._text = self._text[-4096:]
                break
            self._text = self._text[cut + 1:]


def get_log_buffer() -> LogBuffer:
    global _buffer
    if _buffer is None:
        _buffer = LogBuffer()
    return _buffer


class _StreamTee:
    """Write to the original stream and to the log buffer."""

    def __init__(self, real, buffer: LogBuffer):
        self._real = real
        self._buffer = buffer

    def write(self, text):
        if text is None:
            return 0
        if not isinstance(text, str):
            text = str(text)
        try:
            if self._real is not None:
                self._real.write(text)
        except Exception:
            pass
        try:
            self._buffer.append(text)
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            if self._real is not None:
                self._real.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return bool(self._real is not None and self._real.isatty())
        except Exception:
            return False

    def fileno(self):
        return self._real.fileno()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _excepthook(exc_type, exc, tb):
    sys.stderr.write("".join(traceback.format_exception(exc_type, exc, tb)))
    errors.report(f"Unexpected error: {exc_type.__name__}: {exc}. Details are in the terminal (F2).")


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    sys.stderr.write(
        "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    )
    errors.report(
        f"Unexpected error: {args.exc_type.__name__}: {args.exc_value}. "
        "Details are in the terminal (F2)."
    )


def install_stdio_capture():
    """Wrap stdout/stderr once. Call after QApplication exists."""
    global _installed
    if _installed:
        return get_log_buffer()
    _installed = True
    buffer = get_log_buffer()
    if not isinstance(sys.stdout, _StreamTee):
        sys.stdout = _StreamTee(sys.stdout, buffer)
    if not isinstance(sys.stderr, _StreamTee):
        sys.stderr = _StreamTee(sys.stderr, buffer)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return buffer


class DebugConsole(QDialog):
    """Read-only view of the log. Hide on close; the buffer keeps filling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Yogi terminal")
        self.resize(760, 480)
        self.setModal(False)
        self._accepting = False
        self._last_seq = 0
        self._theme = "dark"

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self._title = QLabel("Terminal")
        header.addWidget(self._title)
        header.addStretch()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._clear)
        header.addWidget(self._clear_btn)
        root.addLayout(header)

        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setUndoRedoEnabled(False)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._edit.setFont(_mono_font())
        root.addWidget(self._edit)

        get_log_buffer().chunk_ready.connect(
            self._on_chunk, Qt.ConnectionType.QueuedConnection
        )
        self.apply_theme(self._theme)

    def apply_theme(self, theme: str):
        self._theme = theme if theme in ("light", "dark") else "dark"
        p = theme_palette(self._theme)
        track = "rgba(0, 0, 0, 0.04)" if self._theme == "light" else "rgba(255, 255, 255, 0.05)"
        self.setStyleSheet(f"background-color: {p['window_bg']};")
        self._title.setStyleSheet(
            f"color: {p['mid_text']}; font-family: Inter; font-size: 13px; font-weight: 500;"
            "background: transparent; border: none;"
        )
        self._clear_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {p['chip_bg']};
                color: {p['mid_text']};
                border: 1px solid {p['chip_unsel_border']};
                border-radius: 4px;
                padding: 4px 12px;
                font-family: Inter;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {p['mid_text']};
            }}
            """
        )
        self._edit.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {p['input_bg']};
                color: {p['input_text']};
                border: 1px solid {p['input_border']};
                border-radius: 4px;
                font-family: "Cascadia Mono", Consolas, "Courier New";
                font-size: 12px;
            }}
            QScrollBar:vertical {{
                background: {track};
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {p['scroll_handle']};
                min-height: 24px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {p['scroll_handle_hover']};
            }}
            QScrollBar:horizontal {{
                background: {track};
                height: 8px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {p['scroll_handle']};
                min-width: 24px;
                border-radius: 3px;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                width: 0; height: 0;
            }}
            """
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._load_snapshot()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _load_snapshot(self):
        # Ignore queued chunks until the widget matches the buffer.
        self._accepting = False
        seq, text = get_log_buffer().snapshot()
        self._edit.setPlainText(text)
        self._last_seq = seq
        self._scroll_to_end()
        seq2, text2 = get_log_buffer().snapshot()
        if seq2 != seq:
            self._edit.setPlainText(text2)
            self._last_seq = seq2
            self._scroll_to_end()
        self._accepting = True

    def _on_chunk(self, seq: int, text: str):
        if not self._accepting or not self.isVisible():
            return
        if seq <= self._last_seq or not text:
            return
        self._last_seq = seq
        bar = self._edit.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        cursor = self._edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if at_end:
            bar.setValue(bar.maximum())

    def _scroll_to_end(self):
        bar = self._edit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear(self):
        self._last_seq = get_log_buffer().clear()
        self._edit.clear()


def _mono_font() -> QFont:
    font = QFont()
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFamilies(list(_MONO_FAMILIES))
    font.setPointSize(10)
    return font


class F2Filter(QObject):
    """Toggle the debug window on F2.

    Not a QShortcut: Settings grabs the keyboard while recording an
    activation hotkey, and a shortcut would swallow F2 before that grab.
    Returning False here lets the recorder store F2.
    """

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() != Qt.Key.Key_F2 or event.isAutoRepeat():
            return False
        mods = event.modifiers()
        extra = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if mods & extra:
            return False
        window = self._window
        if getattr(window.settings_tab, "is_recording", False):
            return False
        window.toggle_debug_console()
        return True
