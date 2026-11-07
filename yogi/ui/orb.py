"""Always-on-top orb window. Preloaded hidden, shown for one question at a time.

Import this module before constructing QApplication. QtWebEngine must be
imported first, and the Chromium flag has to be set before that import so a
file:// page can load the three.js module from the CDN.
"""

import ctypes
import os
import sys

# No video encoding here; skipping the hardware encoder probe silences mf_video_encoder_util errors.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--allow-file-access-from-files --disable-accelerated-video-encode",
)

from PyQt6.QtCore import Qt, QUrl, QObject, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

# Required before QApplication exists, or the web view cannot composite alpha.
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

# Bottom-center placement, matching the previous standalone window.
SCREEN_FRACTION = 0.08
BOTTOM_OFFSET_FRACTION = 0.04

# How far voice pushes the orb's deformations. 1.0 is the page default,
# 0 freezes the shape, 2-3 makes swells, dents and wind clearly visible.
VOICE_INTENSITY = 2.5

from yogi.paths import asset

_ORB_HTML = str(asset("orb.html"))



def _js_number(value):
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return "0"
    return f"{number:.5f}"


class OrbWindow(QMainWindow):
    """Frameless, click-through, never takes focus. Hosts orb.html."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.setStyleSheet("QMainWindow { background: transparent; border: none; }")
        self.setContentsMargins(0, 0, 0, 0)

        self._loaded = False
        self._pending_boot = False

        self._view = QWebEngineView()
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._view.setStyleSheet("background: transparent; border: none;")
        self._view.page().setBackgroundColor(Qt.GlobalColor.transparent)

        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )

        self._view.loadFinished.connect(self._on_load)
        self._view.load(QUrl.fromLocalFile(_ORB_HTML))
        self.setCentralWidget(self._view)
        self._place()

    def _place(self):
        screen = QApplication.primaryScreen().geometry()
        size = int(screen.width() * SCREEN_FRACTION)
        bottom_offset = int(screen.height() * BOTTOM_OFFSET_FRACTION)
        self.setGeometry(
            (screen.width() - size) // 2,
            (screen.height() - size) - bottom_offset,
            size,
            size,
        )

    def _run_js(self, source):
        self._view.page().runJavaScript(source)

    def _boot(self):
        self._run_js("window.bootOrb && window.bootOrb()")

    def _on_load(self, ok):
        self._loaded = bool(ok)
        if ok:
            self._run_js(
                "window.setVoiceIntensity && window.setVoiceIntensity("
                f"{_js_number(VOICE_INTENSITY)})"
            )
        if ok and self._pending_boot:
            self._pending_boot = False
            self._boot()

    def _clear_native_border(self):
        """Windows 11 draws a 1px frame around frameless windows. Turn it off."""
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        DWMWA_BORDER_COLOR = 34
        DWMWA_COLOR_NONE = 0xFFFFFFFE
        corner = ctypes.c_int(DWMWCP_DONOTROUND)
        border = ctypes.c_uint(DWMWA_COLOR_NONE)
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), ctypes.sizeof(border))

    def show_orb(self):
        self._place()
        self.show()
        self._clear_native_border()
        if self._loaded:
            self._boot()
        else:
            self._pending_boot = True

    def hide_orb(self):
        self._pending_boot = False
        self._run_js("window.resetVoice && window.resetVoice()")
        self.hide()

    def set_levels(self, low, mid, high):
        self._run_js(
            "window.setVoiceLevels && window.setVoiceLevels("
            f"{_js_number(low)}, {_js_number(mid)}, {_js_number(high)})"
        )


class OrbBridge(QObject):
    """Thread-safe show, hide, and level updates for the hotkey thread."""

    _show = pyqtSignal()
    _hide = pyqtSignal()
    _levels = pyqtSignal(float, float, float)

    def __init__(self, window: OrbWindow):
        super().__init__()
        self._window = window
        self._show.connect(window.show_orb)
        self._hide.connect(window.hide_orb)
        self._levels.connect(window.set_levels)

    def show(self):
        self._show.emit()

    def hide(self):
        self._hide.emit()

    def levels(self, low, mid, high):
        self._levels.emit(float(low), float(mid), float(high))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OrbWindow()
    window.show_orb()
    sys.exit(app.exec())
