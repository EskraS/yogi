import threading
import traceback

from PIL import Image
from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QObject, QUrl, QTimer, Signal, QEventLoop
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap, QImage, QMouseEvent, QKeyEvent
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QApplication

from yogi.paths import asset

# A drag smaller than this in either direction counts as a plain click,
# which falls back to sending the whole screen.
MIN_DRAG_PX = 12
# Qt-drawn dim, only used until overlay.html has loaded.
DIM_ALPHA = 110
# overlay.html fade in/out. The window hides only after the fade, so the web
# view's last frame is empty and the next open never flashes the old box.
FADE_MS = 320
FADE_SLACK_MS = 80

_OVERLAY_HTML = str(asset("overlay.html"))


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    """Convert without letting Qt alias PIL's buffer.

    PIL.ImageQt wraps the source buffer instead of copying it, and the pixmap
    keeps pointing at that memory after Python frees it, which segfaults on the
    first paint. Copying the QImage detaches it from `data`.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    data = image.tobytes("raw", "RGB")
    qimage = QImage(
        data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
    ).copy()
    return QPixmap.fromImage(qimage)


class RegionSelectOverlay(QWidget):
    """Fullscreen frozen-screen overlay for click-drag region selection.

    Qt paints the frozen screenshot and handles the mouse; overlay.html sits on
    top in a click-through web view and draws the dim, the silk and the
    selection box. Built once and reused so the page is loaded before use.
    """

    def __init__(self, screen=None):
        super().__init__()
        self._screenshot: Image.Image | None = None
        self._pixmap = QPixmap()
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._result: Image.Image | None = None
        self._loop: QEventLoop | None = None
        self._closing = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_now)

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        screen = screen or QApplication.primaryScreen()
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())

        self._web_ready = False
        self._view = QWebEngineView(self)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._view.setStyleSheet("background: transparent; border: none;")
        self._view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self._view.loadFinished.connect(self._on_web_loaded)
        self._view.hide()
        self._view.load(QUrl.fromLocalFile(_OVERLAY_HTML))

    def _on_web_loaded(self, ok: bool):
        self._web_ready = bool(ok)
        self._view.setVisible(self._web_ready)
        if not ok:
            print("Region overlay: overlay.html failed to load; using plain dim.")

    def resizeEvent(self, event):
        self._view.setGeometry(self.rect())
        super().resizeEvent(event)

    def _push_selection(self):
        if not self._web_ready:
            return
        rect = self._normalized_rect() if self._dragging else QRect()
        self._view.page().runJavaScript(
            f"window.setSelection && window.setSelection("
            f"{rect.x()}, {rect.y()}, {rect.width()}, {rect.height()})"
        )

    # ── Selection loop ───────────────────────────────────────────────────────

    def exec_select(self, screenshot: Image.Image) -> Image.Image | None:
        self._screenshot = screenshot
        self._pixmap = pil_to_pixmap(screenshot)
        self._result = None
        self._dragging = False
        self._push_selection()
        if self._web_ready:
            self._view.page().runJavaScript(
                "window.clearAccent && window.clearAccent();"
                f"window.setShown && window.setShown(true, {FADE_MS})"
            )
        self._loop = QEventLoop()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()
        self._loop.exec()
        return self._result

    def _finish(self, image: Image.Image | None):
        self._result = image
        self._dragging = False
        self._closing = True
        self.releaseKeyboard()
        if self._web_ready:
            self._view.page().runJavaScript(
                f"window.setShown && window.setShown(false, {FADE_MS})"
            )
            self._hide_timer.start(FADE_MS + FADE_SLACK_MS)
        else:
            self.hide_now()
        if self._loop is not None and self._loop.isRunning():
            self._loop.quit()

    def is_selecting(self) -> bool:
        return self._loop is not None and self._loop.isRunning() and not self._closing

    def cancel(self):
        self._finish(None)

    def hide_now(self):
        """End a pending fade-out at once; called before a new screen grab."""
        self._hide_timer.stop()
        self._closing = False
        self.hide()

    def _normalized_rect(self) -> QRect:
        return QRect(self._origin, self._current).normalized()

    def _image_box(self, rect: QRect) -> tuple[int, int, int, int]:
        """Map a widget rect (logical px) to screenshot pixels (physical px)."""
        scale_x = self._pixmap.width() / max(1, self.width())
        scale_y = self._pixmap.height() / max(1, self.height())
        return (
            round(rect.left() * scale_x),
            round(rect.top() * scale_y),
            round((rect.right() + 1) * scale_x),
            round((rect.bottom() + 1) * scale_y),
        )

    # ── Painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        full = self.rect()
        painter.drawPixmap(full, self._pixmap)
        if self._web_ready:
            return
        painter.fillRect(full, QColor(0, 0, 0, DIM_ALPHA))

        rect = self._normalized_rect()
        if not self._dragging or rect.width() < 1 or rect.height() < 1:
            return

        # Restore the selection to full brightness, then outline it.
        left, top, right, bottom = self._image_box(rect)
        painter.drawPixmap(
            QRectF(rect),
            self._pixmap,
            QRectF(left, top, right - left, bottom - top),
        )

        pen = QPen(QColor(255, 255, 255))
        pen.setWidth(1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

    # ── Input ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if self._closing:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()
            self._push_selection()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._current = event.position().toPoint()
            self.update()
            self._push_selection()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not (self._dragging and event.button() == Qt.MouseButton.LeftButton):
            super().mouseReleaseEvent(event)
            return

        self._dragging = False
        rect = self._normalized_rect()
        event.accept()
        try:
            if rect.width() < MIN_DRAG_PX or rect.height() < MIN_DRAG_PX:
                self._finish(self._screenshot)
                return
            from yogi.core.assistant import crop_screenshot

            self._finish(crop_screenshot(self._screenshot, self._image_box(rect)))
        except Exception:
            traceback.print_exc()
            self._finish(self._screenshot)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape and not self._closing:
            self._finish(None)
            event.accept()
            return
        super().keyPressEvent(event)


class RegionSelectBridge(QObject):
    """Lets the hotkey thread run the overlay on the Qt GUI thread and wait for it."""

    _show_overlay = Signal()
    _cancel_overlay = Signal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._event: threading.Event | None = None
        self._result: Image.Image | None = None
        self._overlay: RegionSelectOverlay | None = None
        self._show_overlay.connect(self._run_overlay)
        self._cancel_overlay.connect(self._cancel_selection)
        if QApplication.instance() is not None:
            # Built now so overlay.html is loaded before the first screenshot.
            self._overlay = RegionSelectOverlay()

    def request_screenshot(self) -> Image.Image | None:
        app = QApplication.instance()
        if app is None:
            from yogi.core.assistant import take_screenshot

            return take_screenshot()

        if threading.current_thread() is threading.main_thread():
            return self._select_region()

        with self._lock:
            self._event = threading.Event()
            self._result = None
            event = self._event

        self._show_overlay.emit()
        event.wait(timeout=120)

        with self._lock:
            result = self._result
            self._event = None
            return result

    def cancel(self):
        """Close an open selection as if Esc was pressed in it. Safe from any thread.

        The overlay only sees Esc when it has keyboard focus, and Windows often
        keeps focus with the app the user was in, so the stop hotkey calls this.
        """
        self._cancel_overlay.emit()

    def _cancel_selection(self):
        overlay = self._overlay
        if overlay is not None and overlay.is_selecting():
            overlay.cancel()

    def _select_region(self) -> Image.Image | None:
        from yogi.core.assistant import grab_primary_monitor

        if self._overlay is not None:
            # A still-fading overlay would end up in the grab.
            self._overlay.hide_now()
        screenshot, _monitor = grab_primary_monitor()
        if self._overlay is None:
            self._overlay = RegionSelectOverlay()
        return self._overlay.exec_select(screenshot)

    def _run_overlay(self):
        image = None
        try:
            image = self._select_region()
        except Exception:
            traceback.print_exc()
        finally:
            with self._lock:
                self._result = image
                if self._event is not None:
                    self._event.set()
