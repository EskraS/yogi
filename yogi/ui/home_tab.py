from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, pyqtSignal, QByteArray, QRectF, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter

from yogi.paths import asset

_SVG_TEMPLATE_COLOR = "#748798"

# Cache of SVG file contents keyed by absolute path, so the logo file is
# read from disk once instead of on every render (including animation frames).
_svg_text_cache: dict[str, str] = {}


def _load_svg(path: str) -> str:
    if path not in _svg_text_cache:
        with open(path, encoding="utf-8") as f:
            _svg_text_cache[path] = f.read()
    return _svg_text_cache[path]


def colorize_svg(path, color: QColor, size: int) -> QPixmap:
    svg = _load_svg(path).replace(_SVG_TEMPLATE_COLOR, color.name())
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if renderer.isValid():
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
    return pixmap


# Animation endpoints: (icon colour, status text colour)
_IDLE_ICON = (90, 90, 90)
_ACTIVE_ICON = (34, 197, 94)
_IDLE_TEXT = (85, 85, 85)
_ACTIVE_TEXT = (34, 197, 94)
_ANIM_STEPS = 18


class HomeTab(QWidget):
    yogi_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = False
        self._theme = "dark"
        self._icon_rgb = _IDLE_ICON
        self._text_rgb = _IDLE_TEXT
        self._anim_from = (_IDLE_ICON, _IDLE_TEXT)
        self._anim_step = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._step_animation)
        self.svg_path = str(asset("logo", "yogi.svg"))

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        layout.setContentsMargins(0, 0, 0, 0)

        # Logo button
        self.logo_btn = QPushButton()
        self.logo_btn.setFixedSize(180, 180)
        self.logo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logo_btn.clicked.connect(self.toggle_yogi)
        self._set_icon(QColor(*self._icon_rgb))
        self.logo_btn.setStyleSheet(self._idle_logo_stylesheet())
        layout.addWidget(self.logo_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status label
        self.status_label = QLabel("Yogi is idle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(self._idle_status_stylesheet())
        layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Glow effect
        self.glow = QGraphicsDropShadowEffect()
        self.glow.setBlurRadius(0)
        self.glow.setColor(QColor(34, 197, 94, 160))
        self.glow.setOffset(0, 0)
        self.logo_btn.setGraphicsEffect(self.glow)

        self.glow_anim = QPropertyAnimation(self.glow, b"blurRadius")
        self.glow_anim.setDuration(400)
        self.glow_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def apply_theme(self, theme: str):
        self._theme = theme if theme in ("light", "dark") else "dark"
        bg = "#f4f4f5" if self._theme == "light" else "#1e1e1e"
        self.setStyleSheet(f"background-color: {bg};")
        if not self.is_running:
            self._set_icon(QColor(90, 90, 90))
            self.logo_btn.setStyleSheet(self._idle_logo_stylesheet())
            self.status_label.setStyleSheet(self._idle_status_stylesheet())
            self.status_label.setText("Yogi is idle")

    def _idle_logo_stylesheet(self):
        if getattr(self, "_theme", "dark") == "light":
            return """
                QPushButton {
                    background-color: #ffffff;
                    border: 3px solid #d4d4d8;
                    border-radius: 90px;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton:hover { border-color: #a1a1aa; }
                QPushButton:focus { outline: none; }
            """
        return """
            QPushButton {
                background-color: #2a2a2a;
                border: 3px solid #4a4a4a;
                border-radius: 90px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover { border-color: #5a5a5a; }
            QPushButton:focus { outline: none; }
        """

    def _idle_status_stylesheet(self):
        if getattr(self, "_theme", "dark") == "light":
            return """
                color: #71717a;
                font-family: Inter;
                font-size: 15px;
                border: none;
                background: transparent;
            """
        return """
            color: #555555;
            font-family: Inter;
            font-size: 15px;
            border: none;
            background: transparent;
        """

    def _set_icon(self, color: QColor):
        colored = colorize_svg(self.svg_path, color, 64)
        self.logo_btn.setIcon(QIcon(colored))
        self.logo_btn.setIconSize(colored.size())

    def toggle_yogi(self):
        self.is_running = not self.is_running

        # Animate from wherever the colours currently are (even mid-animation)
        # so rapid toggling never causes a visual jump.
        self._anim_from = (self._icon_rgb, self._text_rgb)
        self._anim_step = 0
        self._anim_timer.start(16)

        self.glow_anim.stop()
        if self.is_running:
            self.glow_anim.setStartValue(self.glow.blurRadius())
            self.glow_anim.setEndValue(90)
            self.logo_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 3px solid #22c55e;
                    border-radius: 90px;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton:focus { outline: none; }
            """)
        else:
            self.glow_anim.setStartValue(self.glow.blurRadius())
            self.glow_anim.setEndValue(0)
            self.logo_btn.setStyleSheet(self._idle_logo_stylesheet())

        self.glow_anim.start()
        self.yogi_toggled.emit(self.is_running)

    def _step_animation(self):
        self._anim_step += 1
        t = min(self._anim_step / _ANIM_STEPS, 1.0)

        target_icon = _ACTIVE_ICON if self.is_running else _IDLE_ICON
        target_text = _ACTIVE_TEXT if self.is_running else _IDLE_TEXT
        start_icon, start_text = self._anim_from

        self._icon_rgb = tuple(
            round(start_icon[i] + (target_icon[i] - start_icon[i]) * t) for i in range(3)
        )
        self._text_rgb = tuple(
            round(start_text[i] + (target_text[i] - start_text[i]) * t) for i in range(3)
        )

        self._set_icon(QColor(*self._icon_rgb))
        self.status_label.setStyleSheet(f"""
            color: rgb({self._text_rgb[0]}, {self._text_rgb[1]}, {self._text_rgb[2]});
            font-family: Inter;
            font-size: 15px;
            border: none;
            background: transparent;
        """)

        if t >= 1.0:
            self._anim_timer.stop()
            self.status_label.setText("Yogi is running" if self.is_running else "Yogi is idle")
