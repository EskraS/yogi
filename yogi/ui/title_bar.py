from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
import qtawesome as qta

# Theme tokens for the title bar, keyed by theme name.
_THEMES = {
    "light": {
        "bar_bg": "#ffffff",
        "icon": "#71717a",
        "chrome_hover": "#ececec",
        "tab_active_bg": "#ececec",
        "tab_active_fg": "#3f3f46",
        "tab_idle_fg": "#a1a1aa",
        "tab_hover_fg": "#52525b",
    },
    "dark": {
        "bar_bg": "#252525",
        "icon": "#707070",
        "chrome_hover": "#2a2a2a",
        "tab_active_bg": "#2a2a2a",
        "tab_active_fg": "#aaaaaa",
        "tab_idle_fg": "#555555",
        "tab_hover_fg": "#888888",
    },
}


class TitleBar(QWidget):
    tab_changed = pyqtSignal(str)
    settings_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("background-color: #252525;")
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(4)

        self.active_tab = "home"
        self.tab_buttons = {}
        self._theme = "dark"
        self._maximized = False

        tabs = [("home", "Home"), ("history", "History"), ("blocks", "Yogi Blocks")]
        for tab_id, label in tabs:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, tid=tab_id: self.switch_tab(tid))
            self.tab_buttons[tab_id] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # (attribute, icon when normal, icon when maximized)
        right_buttons = [
            ("minimize_btn", "mdi.minus", None),
            ("maximize_btn", "mdi.window-maximize", "mdi.window-restore"),
            ("settings_btn", "mdi.cog", None),
            ("close_btn", "mdi.close", None),
        ]
        for attr, icon_name, alt_icon in right_buttons:
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color="#707070"))
            btn.setFixedSize(28, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            setattr(self, attr, btn)
            layout.addWidget(btn)

        self.minimize_btn.clicked.connect(self.window().showMinimized)
        self.maximize_btn.clicked.connect(self.maximize_clicked)
        self.settings_btn.clicked.connect(self.settings_clicked)
        self.close_btn.clicked.connect(self.window().close)

        self._chrome_icons = {
            self.minimize_btn: "mdi.minus",
            self.maximize_btn: "mdi.window-maximize",
            self.settings_btn: "mdi.cog",
            self.close_btn: "mdi.close",
        }

        self.update_tab_styles()

    def set_maximized(self, maximized: bool):
        """Swap the maximize/restore icon to match window state."""
        self._maximized = maximized
        icon_name = "mdi.window-restore" if maximized else "mdi.window-maximize"
        self._chrome_icons[self.maximize_btn] = icon_name
        t = _THEMES[self._theme]
        self.maximize_btn.setIcon(qta.icon(icon_name, color=t["icon"]))

    def apply_theme(self, theme: str):
        self._theme = theme if theme in _THEMES else "dark"
        t = _THEMES[self._theme]
        self.setStyleSheet(f"background-color: {t['bar_bg']};")
        chrome_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {t['chrome_hover']};
            }}
        """
        for btn, icon_name in self._chrome_icons.items():
            btn.setIcon(qta.icon(icon_name, color=t["icon"]))
            btn.setStyleSheet(chrome_style)
        self.update_tab_styles()

    def switch_tab(self, tab_id):
        if tab_id == self.active_tab:
            return
        self.active_tab = tab_id
        self.update_tab_styles()
        self.tab_changed.emit(tab_id)

    def clear_active_tab(self):
        """Deselect all tabs, e.g. while the settings page is shown."""
        self.active_tab = None
        self.update_tab_styles()

    def update_tab_styles(self):
        t = _THEMES[getattr(self, "_theme", "dark")]
        active_style = f"""
            QPushButton {{
                background-color: {t['tab_active_bg']};
                color: {t['tab_active_fg']};
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-family: Inter;
                font-size: 13px;
                font-weight: 500;
            }}
        """
        idle_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {t['tab_idle_fg']};
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-family: Inter;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                color: {t['tab_hover_fg']};
            }}
        """
        for tab_id, btn in self.tab_buttons.items():
            btn.setStyleSheet(active_style if tab_id == self.active_tab else idle_style)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            # Dragging a maximized window first restores it so it can move.
            if self.window().isMaximized():
                self.maximize_clicked.emit()
                win = self.window()
                cursor_x = event.globalPosition().toPoint().x()
                ratio = cursor_x / max(1, self.width())
                win.move(
                    int(cursor_x - win.width() * ratio),
                    event.globalPosition().toPoint().y() - self.height() // 2,
                )
                self._drag_pos = (
                    event.globalPosition().toPoint() - win.frameGeometry().topLeft()
                )
                return
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_clicked.emit()
