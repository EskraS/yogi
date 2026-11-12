import sys
import threading

if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("yogi.app")

# Orb configures WebEngine / OpenGL attrs before QApplication exists.
from yogi.ui.orb import OrbBridge, OrbWindow  # noqa: E402

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QStackedWidget
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QFont, QIcon, QColor, QMouseEvent

from yogi.paths import asset
from yogi.core import errors, history_store, module_loader, preflight
from yogi.audio import voice_levels
from yogi.core.assistant import (
    DEFAULT_HOTKEY,
    get_settings,
    listen_for_hotkey,
    start_prewarm,
    stop_prewarm,
    set_settings_getter,
    set_region_select_handler,
    set_orb_handler,
)
from yogi.ui.title_bar import TitleBar
from yogi.ui.home_tab import HomeTab, colorize_svg
from yogi.ui.settings import SettingsTab, theme_palette
from yogi.ui.blocks_tab import BlocksTab
from yogi.ui.history_tab import HistoryTab
from yogi.ui.region_overlay import RegionSelectBridge
from yogi.ui.debug_console import DebugConsole, F2Filter, install_stdio_capture
from yogi.ui.error_popup import ErrorPopup

RESIZE_MARGIN = 6


def make_icon():
    path = str(asset("logo", "yogi.svg"))
    return QIcon(colorize_svg(path, QColor("#748798"), 256))


class YogiApp(QMainWindow):
    # "" when Yogi may start, else the message to show on the home tab.
    _preflight_done = Signal(str)
    # Emitted from any thread by errors.report(); shown on the GUI thread.
    _error_reported = Signal(str)

    def __init__(self):
        super().__init__()
        self.error_popup = ErrorPopup(self)
        self._error_reported.connect(self.error_popup.show_message)
        errors.set_handler(self._error_reported.emit)
        self.setWindowTitle("Yogi")
        self.resize(1280, 720)
        self.setMinimumSize(960, 600)
        self.setStyleSheet("background-color: #1e1e1e;")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowIcon(make_icon())
        self.setMouseTracking(True)
        self._resizing = False
        self._resize_dir = 0  # bitmask of Qt.Edge values
        self._resize_start_global = QPoint()
        self._resize_start_geometry = QRect()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.title_bar = TitleBar(parent=self)
        main_layout.addWidget(self.title_bar)

        self._separator = QWidget()
        self._separator.setFixedHeight(1)
        self._separator.setStyleSheet("background-color: #252525;")
        main_layout.addWidget(self._separator)

        self.stack = QStackedWidget()
        self.home_tab = HomeTab(parent=self)
        self.settings_tab = SettingsTab(parent=self)
        self.stack.addWidget(self.home_tab)
        self.stack.addWidget(self.settings_tab)
        main_layout.addWidget(self.stack)

        self.blocks_tab = BlocksTab(parent=self)
        self.history_tab = HistoryTab(parent=self)
        self.stack.addWidget(self.blocks_tab)
        self.stack.addWidget(self.history_tab)

        self.title_bar.tab_changed.connect(self.on_tab_changed)
        self.title_bar.settings_clicked.connect(self.on_settings_clicked)
        self.title_bar.maximize_clicked.connect(self.toggle_maximize)

        self.settings_tab.theme_changed.connect(self.apply_theme)
        self._debug = DebugConsole(self)
        self._f2_filter = F2Filter(self)
        QApplication.instance().installEventFilter(self._f2_filter)
        self.apply_theme(self.settings_tab.settings["theme"])

        # Live SettingsTab dict for LLM; test_settings still supplies voice_* via merge.
        set_settings_getter(lambda: self.settings_tab.settings)

        self._yogi_thread = None
        self._yogi_stop_event = None
        self._region_bridge = RegionSelectBridge()
        set_region_select_handler(
            self._region_bridge.request_screenshot, cancel=self._region_bridge.cancel
        )

        self.orb_window = OrbWindow()
        self.orb_bridge = OrbBridge(self.orb_window)
        set_orb_handler(self.orb_bridge)
        voice_levels.set_level_listener(self.orb_bridge.levels)
        history_store.set_listener(self.history_tab.chat_saved.emit)
        # After the window is shown, so a "Python missing" popup is visible.
        QTimer.singleShot(1000, module_loader.prepare_blocks)

        self.home_tab.yogi_toggled.connect(self.on_yogi_toggled)
        self.home_tab.start_requested.connect(self.on_start_requested)
        self._preflight_done.connect(self.on_preflight_done)


        # Mouse-move events must reach the window for resize hover cursors;
        # enable tracking on all children (they cover the central widget).
        for child in self.findChildren(QWidget):
            child.setMouseTracking(True)

    def on_start_requested(self):
        settings = get_settings()

        def run():
            try:
                error = preflight.check_ready(settings)
            except Exception as e:
                error = f"Couldn't check API keys: {type(e).__name__}"
            if error:
                errors.report(f"Yogi not started: {error}")
            self._preflight_done.emit(error or "")

        threading.Thread(target=run, daemon=True).start()

    def on_preflight_done(self, error: str):
        if error:
            self.home_tab.start_failed()
        else:
            self.home_tab.set_running(True)

    def on_yogi_toggled(self, running: bool):
        if running:
            self.settings_tab.stop_mic_test()
            if self._yogi_thread and self._yogi_thread.is_alive():
                return
            self._yogi_stop_event = threading.Event()
            hotkey = self.settings_tab.settings.get("hotkey", DEFAULT_HOTKEY)
            self._yogi_thread = threading.Thread(
                target=listen_for_hotkey,
                args=(self._yogi_stop_event, hotkey),
                daemon=True
            )
            self._yogi_thread.start()
            # Open TTS socket, HTTPS connection and audio device up front.
            start_prewarm()
        else:
            if self._yogi_stop_event:
                self._yogi_stop_event.set()
                self._yogi_thread = None
            stop_prewarm()

    def toggle_debug_console(self):
        if self._debug.isVisible():
            self._debug.hide()
        else:
            self._debug.show()
            self._debug.raise_()
            self._debug.activateWindow()

    def apply_theme(self, theme: str):
        if theme not in ("light", "dark"):
            theme = "dark"
        p = theme_palette(theme)
        self.setStyleSheet(f"background-color: {p['window_bg']};")
        self._separator.setStyleSheet(
            f"background-color: {'#e4e4e7' if theme == 'light' else '#252525'};"
        )
        self.title_bar.apply_theme(theme)
        self.home_tab.apply_theme(theme)
        self.settings_tab.apply_theme(theme)
        self.blocks_tab.apply_theme(theme)
        self.history_tab.apply_theme(theme)
        self._debug.apply_theme(theme)

    def on_settings_clicked(self):
        self.title_bar.clear_active_tab()
        self.stack.setCurrentWidget(self.settings_tab)

    def on_tab_changed(self, tab_id):
        if tab_id == "home":
            self.stack.setCurrentWidget(self.home_tab)
        elif tab_id == "history":
            self.stack.setCurrentWidget(self.history_tab)
        elif tab_id == "blocks":
            self.stack.setCurrentWidget(self.blocks_tab)

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.title_bar.set_maximized(self.isMaximized())

    # ── Frameless edge resizing ──────────────────────────────────────────────

    def _edges_at(self, pos: QPoint) -> int:
        """Bitmask of Qt.Edge values under the given local position."""
        if self.isMaximized():
            return 0
        edges = 0
        if pos.x() < RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge.value
        elif pos.x() >= self.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge.value
        if pos.y() < RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge.value
        elif pos.y() >= self.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge.value
        return edges

    @staticmethod
    def _cursor_for_edges(edges: int):
        left = bool(edges & Qt.Edge.LeftEdge.value)
        right = bool(edges & Qt.Edge.RightEdge.value)
        top = bool(edges & Qt.Edge.TopEdge.value)
        bottom = bool(edges & Qt.Edge.BottomEdge.value)
        if (top and left) or (bottom and right):
            return Qt.CursorShape.SizeFDiagCursor
        if (top and right) or (bottom and left):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._resizing = True
                self._resize_dir = edges
                self._resize_start_global = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_global
            geo = QRect(self._resize_start_geometry)
            min_w, min_h = self.minimumWidth(), self.minimumHeight()
            d = self._resize_dir
            # Clamp each dragged edge to exactly the minimum-size position.
            # Never let Qt clamp via setGeometry: stale drag offsets cause
            # the window to snap/reset when the limit is hit.
            if d & Qt.Edge.LeftEdge.value:
                geo.setLeft(min(geo.left() + delta.x(), geo.right() - min_w + 1))
            if d & Qt.Edge.RightEdge.value:
                geo.setRight(max(geo.right() + delta.x(), geo.left() + min_w - 1))
            if d & Qt.Edge.TopEdge.value:
                geo.setTop(min(geo.top() + delta.y(), geo.bottom() - min_h + 1))
            if d & Qt.Edge.BottomEdge.value:
                geo.setBottom(max(geo.bottom() + delta.y(), geo.top() + min_h - 1))
            self.setGeometry(geo)
            event.accept()
            return
        # Hover: update cursor shape near edges.
        if not self.isMaximized():
            cursor = self._cursor_for_edges(self._edges_at(event.position().toPoint()))
            self.setCursor(cursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._resizing and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            self._resize_dir = 0
            event.accept()
            return
        super().mouseReleaseEvent(event)


def main():
    app = QApplication(sys.argv)
    # After QApplication so the log buffer can emit. Startup prints land here.
    install_stdio_capture()
    app.setWindowIcon(make_icon())

    for parts in (("fonts", "Inter"), ("fonts", "inter")):
        inter_path = asset(*parts, "Inter-VariableFont_opsz,wght.ttf")
        if inter_path.is_file():
            QFontDatabase.addApplicationFont(str(inter_path))
            break

    font = QFont("Inter", 10)
    app.setFont(font)
    app.setStyleSheet("* { font-family: Inter; }")

    window = YogiApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
