from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QSizePolicy, QFileDialog, QMessageBox,
    QGraphicsOpacityEffect, QApplication,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, pyqtProperty
from PyQt6.QtGui import QColor, QFontMetrics
import qtawesome as qta

from yogi.core.module_loader import (
    install_module, scan_modules, set_module_enabled, uninstall_module,
)
from yogi.ui.history_tab import TrashButton
from yogi.ui.settings import ConfirmOverlay
from yogi.ui.theme_helpers import scrollbar_stylesheet, mix_hex

# Cache qtawesome pixmaps: (icon_name, color, size) -> QPixmap.
# Theme application re-renders many icons; cache avoids redundant SVG work.
_icon_cache: dict[tuple, object] = {}


def _cached_icon(name: str, color: str, size: int):
    key = (name, color, size)
    if key not in _icon_cache:
        _icon_cache[key] = qta.icon(name, color=color).pixmap(size, size)
    return _icon_cache[key]

# Blocks visual tokens (easy to tweak)
BLOCK_CARD_WIDTH = 360
BLOCK_CARD_HEIGHT = 210
BLOCK_CARD_RADIUS = 8
BLOCK_GRID_SPACING = 16
BLOCKS_PER_ROW = 3
BLOCK_CONTENT_PADDING_X = 16
BLOCK_CONTENT_PADDING_Y = 16
# Extra inset for icon chip from the card edge.
ICON_BOX_EDGE_EXTRA_LEFT = 0
ICON_BOX_EDGE_EXTRA_TOP = 0
ICON_TO_TITLE_SPACING = 12
TITLE_TO_BODY_SPACING = 0
TITLE_FONT_SIZE_PX = 14
BODY_FONT_SIZE_PX = 12

TOGGLE_WIDTH = 44
TOGGLE_HEIGHT = 24
TOGGLE_KNOB_SIZE = 16
TOGGLE_PADDING = 4
TOGGLE_ON_COLOR = "#22c55e"
TOGGLE_OFF_COLOR = "#3a3a3a"
TOGGLE_OFF_KNOB_COLOR = "#bdbdbd"


# ──────────────────────────────────────────────
# Toggle Switch Widget
# ──────────────────────────────────────────────
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, enabled=True, parent=None):
        super().__init__(parent)
        self.setFixedSize(TOGGLE_WIDTH, TOGGLE_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enabled = enabled
        self._theme = "dark"

    def set_theme(self, theme: str):
        self._theme = theme if theme in ("light", "dark") else "dark"
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        off_color = "#d4d4d8" if self._theme == "light" else TOGGLE_OFF_COLOR
        off_knob = "#9ca3af" if self._theme == "light" else TOGGLE_OFF_KNOB_COLOR
        track_color = QColor(TOGGLE_ON_COLOR) if self._enabled else QColor(off_color)
        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, TOGGLE_WIDTH, TOGGLE_HEIGHT, TOGGLE_HEIGHT // 2, TOGGLE_HEIGHT // 2)

        knob_x = (TOGGLE_WIDTH - TOGGLE_PADDING - TOGGLE_KNOB_SIZE) if self._enabled else TOGGLE_PADDING
        knob_color = QColor("white") if self._enabled else QColor(off_knob)
        p.setBrush(QBrush(knob_color))
        p.drawEllipse(knob_x, TOGGLE_PADDING, TOGGLE_KNOB_SIZE, TOGGLE_KNOB_SIZE)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._enabled = not self._enabled
            self.update()
            self.toggled.emit(self._enabled)

    def set_enabled_state(self, val: bool):
        self._enabled = val
        self.update()


# ──────────────────────────────────────────────
# Block Card
# ──────────────────────────────────────────────
class BlockCard(QWidget):
    remove_requested = pyqtSignal(str)
    toggle_requested = pyqtSignal(str, bool)

    def __init__(self, block: dict, theme="dark", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("block_card")
        self.block = block
        self._theme = theme
        self._card_bg = "#262626"
        self._base_border = "#4a4a4a"
        self._hover_border = "#575757"
        self._hover_t = 0.0
        # scan_modules always sets these keys. Name can be empty when the manifest is bad.
        self._name_full = block.get("name") or block.get("id") or ""
        self._description_full = block.get("description") or ""
        self._error = block.get("error")
        self.setFixedSize(BLOCK_CARD_WIDTH, BLOCK_CARD_HEIGHT)
        self._hover_anim = QPropertyAnimation(self, b"hover_t")
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._build()
        self.apply_theme(theme)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            BLOCK_CONTENT_PADDING_X,
            BLOCK_CONTENT_PADDING_Y,
            BLOCK_CONTENT_PADDING_X,
            BLOCK_CONTENT_PADDING_Y,
        )
        layout.setSpacing(6)

        # Same trash control as History / Settings. Top-right of the card.
        self.trash_btn = TrashButton(self._theme, self)
        self.trash_btn.setToolTip("Delete block")
        self.trash_btn.move(self.width() - 30, 8)
        self.trash_btn.clicked.connect(
            lambda: self.remove_requested.emit(self.block["id"])
        )

        self.icon_container = QLabel()
        self.icon_container.setFixedSize(42, 42)
        self.icon_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_name = "mdi.puzzle-outline"
        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(
            ICON_BOX_EDGE_EXTRA_LEFT,
            ICON_BOX_EDGE_EXTRA_TOP,
            0,
            0,
        )
        icon_row.setSpacing(0)
        icon_row.addWidget(
            self.icon_container,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        icon_row.addStretch()
        layout.addLayout(icon_row)
        layout.addSpacing(ICON_TO_TITLE_SPACING)

        self.title_label = QLabel(self._name_full)
        self.title_label.setStyleSheet(f"font-size: {TITLE_FONT_SIZE_PX}px; font-weight: 500;")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setWordWrap(False)
        self.title_label.setToolTip(self._name_full)
        layout.addWidget(self.title_label)
        layout.addSpacing(TITLE_TO_BODY_SPACING)

        self.description_label = QLabel(self._description_full)
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.description_label.setToolTip(self._description_full)
        layout.addWidget(self.description_label)

        # Same string validate_manifest / scan_modules returned. Hidden when the module is valid.
        self.error_label = QLabel(self._error or "")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(bool(self._error))
        if self._error:
            self.error_label.setToolTip(self._error)
        layout.addWidget(self.error_label)

        layout.addStretch()

        toggle_row = QHBoxLayout()
        toggle_row.addStretch()
        self.toggle = ToggleSwitch(enabled=self.block.get("enabled", True))
        self.toggle.toggled.connect(
            lambda val: self.toggle_requested.emit(self.block["id"], val)
        )
        toggle_row.addWidget(self.toggle)
        layout.addLayout(toggle_row)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0 if self.block.get("enabled", True) else 0.72)
        self.setGraphicsEffect(self._opacity)
        self._update_elided_title()

    def _update_elided_title(self):
        title_width = max(12, self.title_label.width())
        title_fm = QFontMetrics(self.title_label.font())
        self.title_label.setText(
            title_fm.elidedText(
                self._name_full,
                Qt.TextElideMode.ElideRight,
                title_width,
            )
        )

    def _apply_card_shell_style(self):
        border = mix_hex(self._base_border, self._hover_border, self._hover_t)
        self.setStyleSheet(f"""
            QWidget#block_card {{
                background-color: {self._card_bg};
                border: 1px solid {border};
                border-radius: {BLOCK_CARD_RADIUS}px;
            }}
            QWidget#block_card QLabel {{
                border: none;
                background: transparent;
            }}
        """)

    def _get_hover_t(self):
        return self._hover_t

    def _set_hover_t(self, value: float):
        self._hover_t = max(0.0, min(1.0, float(value)))
        self._apply_card_shell_style()

    hover_t = pyqtProperty(float, fget=_get_hover_t, fset=_set_hover_t)

    def apply_theme(self, theme: str):
        self._theme = theme
        if theme == "light":
            self._card_bg = "#f4f4f5"
            self._base_border = "#dedee4"
            self._hover_border = "#ececf2"
            title_enabled, title_disabled = "#3f3f46", "#71717a"
            body_enabled, body_disabled = "#71717a", "#8f8f96"
            error_color = "#b91c1c"
            icon_enabled, icon_disabled = "#71717a", "#9b9ba1"
            icon_chip_bg_enabled = "#fafafa"
        else:
            self._card_bg = "#262626"
            self._base_border = "#4a4a4a"
            self._hover_border = "#5d5d5d"
            title_enabled, title_disabled = "#a1a1a1", "#7c7c7c"
            body_enabled, body_disabled = "#6f6f6f", "#575757"
            error_color = "#f87171"
            icon_enabled, icon_disabled = "#7e7e7e", "#595959"
            icon_chip_bg_enabled = "#303030"

        enabled = self.block.get("enabled", True)

        self._apply_card_shell_style()
        self.trash_btn.set_theme(theme)
        self.toggle.set_theme(theme)
        icon_color = icon_enabled if enabled else icon_disabled
        self.icon_container.setPixmap(_cached_icon(self._icon_name, icon_color, 24))
        self.icon_container.setStyleSheet(
            f"""
            QLabel {{
                border-radius: 6px;
                background-color: {icon_chip_bg_enabled if enabled else "transparent"};
                border: none;
            }}
            """
        )
        self.title_label.setStyleSheet(
            f"font-size: {TITLE_FONT_SIZE_PX}px; font-weight: 500; color: {title_enabled if enabled else title_disabled};"
        )
        self.description_label.setStyleSheet(
            f"font-size: {BODY_FONT_SIZE_PX}px; color: {body_enabled if enabled else body_disabled};"
        )
        self.error_label.setStyleSheet(
            f"font-size: {BODY_FONT_SIZE_PX}px; color: {error_color};"
        )
        self._update_elided_title()

    def set_enabled(self, enabled: bool):
        """Update the card in place when its toggle changes (no grid rebuild)."""
        self.block["enabled"] = enabled
        self._opacity.setOpacity(1.0 if enabled else 0.72)
        self.apply_theme(self._theme)

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.trash_btn.move(self.width() - 30, 8)
        self._update_elided_title()


# ──────────────────────────────────────────────
# Main BlocksTab
# ──────────────────────────────────────────────
class BlocksTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "dark"
        self._blocks: list[dict] = []
        self._cards: dict[str, BlockCard] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        header = QHBoxLayout()
        self.title_label = QLabel("Blocks")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 500;")
        header.addWidget(self.title_label)
        header.addStretch()

        self.add_btn = QPushButton("  Add Block")
        self.add_btn.setIcon(qta.icon("mdi.plus", color="#aaaaaa"))
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._on_add_block)
        header.addWidget(self.add_btn)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.grid_container = QWidget()
        self.grid_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.grid = QGridLayout(self.grid_container)
        self.grid.setSpacing(BLOCK_GRID_SPACING)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_container)
        root.addWidget(self.scroll)

        self.empty_label = QLabel("No blocks yet\nAdd a .zip file with manifest.json and a Python file")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #666666; font-size: 13px;")
        root.addWidget(self.empty_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._reload_modules()
        self.apply_theme(self._theme)

    def _on_add_block(self):
        # Filter hides other types in the picker. The suffix is still not trusted:
        # install_module rejects anything zipfile.is_zipfile does not accept.
        path, _chosen_filter = QFileDialog.getOpenFileName(
            self,
            "Add block",
            "",
            "Zip files (*.zip)",
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            error = install_module(path)
        except Exception as exc:
            error = f"Could not add block: {exc}"
        finally:
            QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "Could not add block", error)
            return
        self._reload_modules()

    def _on_remove(self, block_id: str):
        block = next((b for b in self._blocks if b["id"] == block_id), None)
        name = (block.get("name") if block else None) or block_id
        ConfirmOverlay(
            self.window(),
            f'Are you sure you want to delete the block "{name}"?',
            "Delete",
            lambda: self._delete_module(block_id),
            self._theme,
        )

    def _delete_module(self, block_id: str):
        try:
            error = uninstall_module(block_id)
        except Exception as exc:
            error = f"Could not delete block: {exc}"
        if error:
            QMessageBox.warning(self, "Could not delete block", error)
            return
        self._reload_modules()

    def _on_toggle(self, block_id: str, val: bool):
        try:
            error = set_module_enabled(block_id, val)
        except Exception as exc:
            error = f"Could not update block: {exc}"
        card = self._cards.get(block_id)
        if error:
            if card is not None:
                card.toggle.set_enabled_state(not val)
                card.set_enabled(not val)
            QMessageBox.warning(self, "Could not update block", error)
            return
        for b in self._blocks:
            if b["id"] == block_id:
                b["enabled"] = val
        if card is not None:
            card.set_enabled(val)

    def _reload_modules(self):
        try:
            self._blocks = scan_modules()
        except Exception as exc:
            self._blocks = []
            QMessageBox.warning(self, "Could not read blocks", str(exc))
        self._refresh_grid()

    def _refresh_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        # Three fixed columns. Stretch on the next column eats leftover
        # width, so cards stay on the left and fill left to right.
        for col in range(BLOCKS_PER_ROW):
            self.grid.setColumnMinimumWidth(col, BLOCK_CARD_WIDTH)
            self.grid.setColumnStretch(col, 0)
        self.grid.setColumnStretch(BLOCKS_PER_ROW, 1)

        has = bool(self._blocks)
        self.empty_label.setVisible(not has)
        self.grid_container.setVisible(has)

        for i, block in enumerate(self._blocks):
            row, col = divmod(i, BLOCKS_PER_ROW)
            card = BlockCard(block, theme=self._theme)
            card.remove_requested.connect(self._on_remove)
            card.toggle_requested.connect(self._on_toggle)
            self._cards[block["id"]] = card
            self.grid.addWidget(card, row, col)

    def apply_theme(self, theme: str):
        self._theme = theme
        fg = "#3f3f46" if theme == "light" else "#aaaaaa"
        btn_bg = "#ececec" if theme == "light" else "#2a2a2a"
        btn_hover = "#e0e0e0" if theme == "light" else "#3a3a3a"
        empty_fg = "#71717a" if theme == "light" else "#666666"
        scroll_handle = "#cbd5e1" if theme == "light" else "#9ca3af"
        scroll_handle_hover = "#94a3b8" if theme == "light" else "#b4bcc8"
        scroll_track = "rgba(0, 0, 0, 0.04)" if theme == "light" else "rgba(255, 255, 255, 0.05)"
        self.title_label.setStyleSheet(f"font-size: 16px; font-weight: 500; color: {fg};")
        self.empty_label.setStyleSheet(f"color: {empty_fg}; font-size: 13px;")
        self.add_btn.setIcon(qta.icon("mdi.plus", color=fg))
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {fg};
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {btn_hover}; }}
        """)
        self.scroll.setStyleSheet(
            scrollbar_stylesheet(scroll_track, scroll_handle, scroll_handle_hover)
        )
        for i in range(self.grid.count()):
            w = self.grid.itemAt(i).widget()
            if isinstance(w, BlockCard):
                w.apply_theme(theme)
