import html
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QPushButton, QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
import qtawesome as qta

from yogi.core import history_store
from yogi.ui.settings import (
    theme_palette, ConfirmOverlay, _BTN_TOKENS, _DELETE_RED, _TRASH_ICON_ON_RED,
)
from yogi.ui.theme_helpers import scrollbar_stylesheet

# Hard cap on chat bubble width regardless of window size.
_BUBBLE_MAX_WIDTH = 580


def _history_scroll_stylesheet(theme: str, p: dict, viewport_bg: str | None = None) -> str:
    """Shared QScrollArea + vertical scrollbar QSS for the History tab."""
    st = "rgba(0,0,0,0.04)" if theme == "light" else "rgba(255,255,255,0.04)"
    bg = viewport_bg if viewport_bg is not None else "transparent"
    return scrollbar_stylesheet(st, p["scroll_handle"], p["scroll_handle_hover"], bg)


def _history_surface_colors(theme: str, p: dict) -> dict:
    """Map global theme palette to History tab surfaces (sidebar / main / text)."""
    if theme == "light":
        return {
            "sidebar_bg": p["input_bg"],
            "divider": p["card_border"],
            "right_bg": p["card_bg"],
            "text_primary": p["mid_text"],
            "text_muted": p["dim_text"],
            "empty_text": p["dim_text"],
            "btn_hover": "rgba(100,100,100,0.10)",
        }
    return {
        "sidebar_bg": p["card_bg"],
        "divider": p["card_border"],
        "right_bg": p["window_bg"],
        "text_primary": p["mid_text"],
        "text_muted": p["dim_text"],
        "empty_text": p["dim_text"],
        "btn_hover": "rgba(136,136,136,0.12)",
    }


def _format_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{dt:%b} {dt.day}, {dt:%Y} · {dt.hour % 12 or 12}:{dt:%M %p}"


# ── Trash button (same look as the trash in saved-prompt and voice lists) ────
class TrashButton(QPushButton):
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setIconSize(QSize(16, 16))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Delete chat")
        self.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; border-radius: 4px; }"
            f" QPushButton:hover {{ background-color: {_DELETE_RED}; }}"
        )
        self._hovered = False
        self.set_theme(theme)

    def set_theme(self, theme: str):
        self._theme = theme if theme in _BTN_TOKENS else "dark"
        self._sync_icon()

    def _sync_icon(self):
        color = _TRASH_ICON_ON_RED if self._hovered else _BTN_TOKENS[self._theme]["icon"]
        self.setIcon(qta.icon("mdi.trash-can-outline", color=color))

    def enterEvent(self, event):
        self._hovered = True
        self._sync_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._sync_icon()
        super().leaveEvent(event)


# ── Sidebar conversation item ─────────────────────────────────────────────────
class ConversationItem(QWidget):
    clicked = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, conv: dict, theme="dark", parent=None):
        super().__init__(parent)
        self.conv_id = conv["id"]
        self._theme = theme
        self._active = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("conv_item")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 8, 10)
        layout.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self._title_full = conv.get("title") or "Untitled chat"
        self.title_lbl = QLabel()
        self.title_lbl.setWordWrap(False)
        # Elided text only; the full title must not widen the row past the
        # sidebar (that pushed the trash button out of view).
        self.title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.time_lbl = QLabel(_format_time(conv.get("updated") or conv.get("created")))
        text_col.addWidget(self.title_lbl)
        text_col.addWidget(self.time_lbl)
        layout.addLayout(text_col, 1)

        self.trash_btn = TrashButton(theme)
        self.trash_btn.clicked.connect(lambda: self.delete_requested.emit(self.conv_id))
        layout.addWidget(self.trash_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_title_elide()
        self.apply_theme(theme)

    def _apply_title_elide(self):
        inner = max(40, self.width() - 12 - 8 - 6 - self.trash_btn.width())
        fm = self.title_lbl.fontMetrics()
        self.title_lbl.setText(
            fm.elidedText(self._title_full, Qt.TextElideMode.ElideRight, inner)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_title_elide()

    def set_active(self, active: bool):
        self._active = active
        self.apply_theme(self._theme)

    def apply_theme(self, theme: str):
        self._theme = theme
        if theme == "light":
            active_bg    = "#e8e8ee"
            active_title = "#18181b"
            active_time  = "#71717a"
            idle_title   = "#52525b"
            idle_time    = "#a1a1aa"
            hover_bg     = "#f0f0f4"
        else:
            active_bg    = "#2a2a2a"
            active_title = "#e0e0e0"
            active_time  = "#888888"
            idle_title   = "#909090"
            idle_time    = "#505050"
            hover_bg     = "#222222"

        if self._active:
            bg = active_bg; title_c = active_title; time_c = active_time; hover = active_bg
        else:
            bg = "transparent"; title_c = idle_title; time_c = idle_time; hover = hover_bg

        self.setStyleSheet(f"""
            QWidget#conv_item {{
                background-color: {bg};
                border-radius: 6px;
            }}
            QWidget#conv_item:hover {{
                background-color: {hover};
            }}
        """)
        self.title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: {'600' if self._active else '500'}; "
            f"color: {title_c}; background: transparent; border: none;"
        )
        self.time_lbl.setStyleSheet(
            f"font-size: 11px; color: {time_c}; background: transparent; border: none;"
        )
        self.trash_btn.set_theme(theme)
        self._apply_title_elide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.conv_id)


# ── Screenshot the chat was about ─────────────────────────────────────────────
class ScreenshotMessage(QWidget):
    """The session's screenshot on the user side; click opens it full size."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._pixmap = QPixmap(path)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 56, 8)
        layout.addStretch()
        self.image = QLabel()
        self.image.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image.setToolTip("Open screenshot")
        self.image.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.image)
        self.set_max_width(_BUBBLE_MAX_WIDTH)

    def set_max_width(self, width: int):
        if self._pixmap.isNull():
            return
        w = min(width, self._pixmap.width())
        self.image.setPixmap(
            self._pixmap.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))


# ── Chat message bubble ───────────────────────────────────────────────────────
class ChatMessage(QWidget):
    def __init__(self, message: dict, theme="dark", parent=None):
        super().__init__(parent)
        self.message = message
        self._theme = theme
        self._build()
        self.apply_theme(theme)

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        self.avatar = QLabel()
        self.avatar.setFixedSize(32, 32)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.bubble = QFrame()
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)

        # Questions and LLM replies are both untrusted text; escape them so the
        # RichText label shows them literally.
        content = html.escape(self.message["content"]).replace("\n", "<br>")
        self.content_label = QLabel(content)
        self.content_label.setWordWrap(True)
        self.content_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.content_label.setTextFormat(Qt.TextFormat.RichText)
        self.content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content_label.setMaximumWidth(_BUBBLE_MAX_WIDTH)
        bubble_layout.addWidget(self.content_label)

        if self.message["role"] == "user":
            layout.addStretch()
            layout.addWidget(self.bubble)
            layout.addWidget(self.avatar)
        else:
            layout.addWidget(self.avatar)
            layout.addWidget(self.bubble)
            layout.addStretch()

    def apply_theme(self, theme: str):
        self._theme = theme
        if theme == "light":
            if self.message["role"] == "user":
                bubble_bg = "#e4e4e7"; text_c = "#3f3f46"; avatar_c = "#71717a"
            else:
                bubble_bg = "#22c55e"; text_c = "#ffffff"; avatar_c = "#22c55e"
        else:
            if self.message["role"] == "user":
                bubble_bg = "#2a2a2a"; text_c = "#e4e4e7"; avatar_c = "#71717a"
            else:
                bubble_bg = "#22c55e"; text_c = "#ffffff"; avatar_c = "#22c55e"

        self.bubble.setStyleSheet(f"""
            QFrame {{
                background-color: {bubble_bg};
                border-radius: 12px;
                border: none;
            }}
        """)
        self.content_label.setStyleSheet(f"""
            QLabel {{
                color: {text_c};
                font-size: 13px;
                line-height: 1.5;
                border: none;
                background: transparent;
            }}
        """)
        icon_name = "mdi.account" if self.message["role"] == "user" else "mdi.robot"
        self.avatar.setPixmap(qta.icon(icon_name, color=avatar_c).pixmap(20, 20))


# ── Main HistoryTab ────────────────────────────────────────────────────────────
class HistoryTab(QWidget):
    # Emitted from the hotkey thread by history_store; delivered on the UI thread.
    chat_saved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "dark"
        self._conversations: list[dict] = []
        self._active_id: str | None = None
        self._current_conversation: dict | None = None
        self._conv_items: dict[str, ConversationItem] = {}
        self._build()
        self.chat_saved.connect(self._on_chat_saved)
        self._load_conversations()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_sidebar()
        self._build_chat_area()

        root.addWidget(self.sidebar)
        root.addWidget(self.chat_area)
        root.setStretch(0, 0)
        root.setStretch(1, 1)

        self.apply_theme(self._theme)

    def _build_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("history_sidebar")
        # Sidebar width adapts within a 240–320px range (see resizeEvent).
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(58)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 10, 0)
        header_layout.setSpacing(8)

        self.header_title = QLabel("Chat History")
        header_layout.addWidget(self.header_title)
        header_layout.addStretch()

        self.clear_all_btn = QPushButton("Clear all")
        self.clear_all_btn.setFixedHeight(24)
        self.clear_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_all_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_all_btn.setToolTip("Delete every chat")
        self.clear_all_btn.clicked.connect(self._request_clear_all)
        header_layout.addWidget(self.clear_all_btn)

        sidebar_layout.addWidget(header)

        search_wrap = QWidget()
        search_inner = QVBoxLayout(search_wrap)
        search_inner.setContentsMargins(10, 2, 10, 10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search conversations...")
        self.search_input.setFixedHeight(32)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_conversations)
        search_inner.addWidget(self.search_input)

        sidebar_layout.addWidget(search_wrap)

        self.conv_scroll = QScrollArea()
        self.conv_scroll.setWidgetResizable(True)
        self.conv_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.conv_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.conv_container = QWidget()
        self.conv_layout = QVBoxLayout(self.conv_container)
        self.conv_layout.setContentsMargins(8, 4, 8, 4)
        self.conv_layout.setSpacing(2)
        self.conv_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.conv_scroll.setWidget(self.conv_container)
        sidebar_layout.addWidget(self.conv_scroll, 1)

    def _build_chat_area(self):
        self.chat_area = QFrame()
        self.chat_area.setObjectName("history_chat_area")
        self.chat_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        chat_layout = QVBoxLayout(self.chat_area)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        chat_header = QWidget()
        chat_header.setFixedHeight(58)
        chat_header_layout = QHBoxLayout(chat_header)
        chat_header_layout.setContentsMargins(24, 0, 24, 0)

        self.chat_title = QLabel("Select a conversation")
        # Long first questions are clipped instead of widening the window.
        self.chat_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        chat_header_layout.addWidget(self.chat_title, 1)

        self.close_chat_btn = QPushButton()
        self.close_chat_btn.setIcon(qta.icon("mdi.close", color="#888888"))
        self.close_chat_btn.setFixedSize(28, 28)
        self.close_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_chat_btn.clicked.connect(self._close_conversation)
        self.close_chat_btn.hide()
        chat_header_layout.addWidget(self.close_chat_btn)

        chat_layout.addWidget(chat_header)

        self.chat_sep = QFrame()
        self.chat_sep.setFixedHeight(1)
        chat_layout.addWidget(self.chat_sep)

        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(24, 24, 24, 24)
        self.messages_layout.setSpacing(16)
        self.messages_layout.addStretch()

        self.messages_scroll.setWidget(self.messages_container)
        chat_layout.addWidget(self.messages_scroll, 1)

        self.empty_label = QLabel("Select a conversation from the sidebar\nto view the chat")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(self.empty_label, 1)

        self.messages_scroll.hide()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_conversations(self):
        self._conversations = history_store.load_chats()
        self._populate_list(self._conversations)

    def _on_chat_saved(self, chat: dict):
        """A Yogi session saved a new reply; show it at the top of the list."""
        self._conversations = [c for c in self._conversations if c["id"] != chat["id"]]
        self._conversations.insert(0, chat)
        self._populate_list(self._current_filtered_conversations())
        if self._active_id == chat["id"]:
            self._load_conversation(chat)

    def _current_filtered_conversations(self) -> list[dict]:
        q = self.search_input.text().lower().strip()
        if not q:
            return list(self._conversations)
        return [c for c in self._conversations if q in (c.get("title") or "").lower()]

    def _populate_list(self, conversations: list[dict]):
        while self.conv_layout.count():
            item = self.conv_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._conv_items.clear()

        for conv in conversations:
            ci = ConversationItem(conv, theme=self._theme)
            ci.clicked.connect(self._load_conversation_by_id)
            ci.delete_requested.connect(self._request_delete)
            if conv["id"] == self._active_id:
                ci.set_active(True)
            self._conv_items[conv["id"]] = ci
            self.conv_layout.addWidget(ci)
        self.clear_all_btn.setEnabled(bool(self._conversations))

    def _filter_conversations(self, _: str):
        self._populate_list(self._current_filtered_conversations())

    def _load_conversation_by_id(self, conv_id: str):
        conv = next((c for c in self._conversations if c["id"] == conv_id), None)
        if conv:
            self._load_conversation(conv)

    def _clear_messages(self):
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _load_conversation(self, conversation: dict):
        self._current_conversation = conversation
        self._active_id = conversation["id"]

        for cid, ci in self._conv_items.items():
            ci.set_active(cid == conversation["id"])

        self.chat_title.setText(conversation.get("title") or "Untitled chat")

        self._clear_messages()
        if conversation.get("screenshot"):
            self.messages_layout.insertWidget(
                self.messages_layout.count() - 1, ScreenshotMessage(conversation["screenshot"])
            )
        for msg in conversation.get("messages", []):
            bubble = ChatMessage(msg, theme=self._theme)
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)

        self.empty_label.hide()
        self.messages_scroll.show()
        self.close_chat_btn.show()

        QTimer.singleShot(50, lambda: self.messages_scroll.verticalScrollBar().setValue(
            self.messages_scroll.verticalScrollBar().maximum()
        ))
        QTimer.singleShot(0, self._update_bubble_widths)

    def _close_conversation(self):
        self._current_conversation = None
        self._active_id = None
        for ci in self._conv_items.values():
            ci.set_active(False)
        self.chat_title.setText("Select a conversation")
        self.messages_scroll.hide()
        self.close_chat_btn.hide()
        self.empty_label.show()
        self._clear_messages()

    def _request_delete(self, conv_id: str):
        ConfirmOverlay(
            self.window(),
            "Are you sure you want to delete this chat?",
            "Delete",
            lambda: self._delete_conversation(conv_id),
            self._theme,
        )

    def _delete_conversation(self, conv_id: str):
        if not history_store.delete_chat(conv_id):
            return
        self._conversations = [c for c in self._conversations if c["id"] != conv_id]
        if self._active_id == conv_id:
            self._close_conversation()
        self._populate_list(self._current_filtered_conversations())

    def _request_clear_all(self):
        if not self._conversations:
            return
        ConfirmOverlay(
            self.window(),
            "Are you sure you want to delete all chats?",
            "Delete",
            self._clear_all_conversations,
            self._theme,
        )

    def _clear_all_conversations(self):
        for conv in list(self._conversations):
            if history_store.delete_chat(conv["id"]):
                self._conversations.remove(conv)
        if self._active_id not in {c["id"] for c in self._conversations}:
            self._close_conversation()
        self._populate_list(self._current_filtered_conversations())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Adapt the sidebar within its 240–320px range (~25% of tab width).
        sidebar_w = min(320, max(240, int(self.width() * 0.25)))
        if self.sidebar.width() != sidebar_w:
            self.sidebar.setFixedWidth(sidebar_w)
        self._update_bubble_widths()

    def _update_bubble_widths(self):
        """Cap bubble width to the smaller of 580px or the available chat width."""
        available = self.chat_area.width() - 160  # margins, avatar, stretch
        width = max(220, min(_BUBBLE_MAX_WIDTH, available))
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, ChatMessage):
                w.content_label.setMaximumWidth(width)
            elif isinstance(w, ScreenshotMessage):
                w.set_max_width(width)

    # ── Theming ───────────────────────────────────────────────────────────────

    def apply_theme(self, theme: str):
        self._theme = theme if theme in ("light", "dark") else "dark"
        p = theme_palette(self._theme)
        hc = _history_surface_colors(self._theme, p)

        sidebar_bg = hc["sidebar_bg"]
        divider = hc["divider"]
        right_bg = hc["right_bg"]
        text_primary = hc["text_primary"]
        text_muted = hc["text_muted"]
        empty_text = hc["empty_text"]
        btn_hover = hc["btn_hover"]
        input_bg = p["input_bg"]
        input_border = p["input_border"]
        input_text = p["input_text"]

        scroll_sidebar = _history_scroll_stylesheet(self._theme, p, None)
        scroll_messages = _history_scroll_stylesheet(self._theme, p, right_bg)

        icon_btn_style = f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background-color: {btn_hover}; }}
        """

        # Sidebar
        self.sidebar.setStyleSheet(f"""
            QFrame#history_sidebar {{
                background-color: {sidebar_bg};
                border: none;
                border-right: 1px solid {divider};
            }}
        """)
        self.header_title.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {text_primary}; border: none;"
        )
        self.clear_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {text_muted};
                border: 1px solid {divider}; border-radius: 4px;
                padding: 0 6px; font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {_DELETE_RED}; color: {_TRASH_ICON_ON_RED};
                border-color: {_DELETE_RED};
            }}
            QPushButton:disabled {{ color: {divider}; }}
        """)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {input_bg};
                color: {input_text};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: #22c55e; }}
        """)
        self.conv_container.setStyleSheet("background: transparent;")
        self.conv_scroll.setStyleSheet(scroll_sidebar)

        # Chat area
        self.chat_area.setStyleSheet(f"""
            QFrame#history_chat_area {{
                background-color: {right_bg};
                border: none;
            }}
        """)
        self.chat_title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {text_primary}; border: none;"
        )
        self.close_chat_btn.setIcon(qta.icon("mdi.close", color=text_muted))
        self.close_chat_btn.setStyleSheet(icon_btn_style)
        self.chat_sep.setStyleSheet(f"background-color: {divider}; border: none;")
        self.empty_label.setStyleSheet(
            f"font-size: 13px; color: {empty_text}; background: transparent;"
        )
        self.messages_container.setStyleSheet(f"background-color: {right_bg};")
        self.messages_scroll.setStyleSheet(scroll_messages)

        for ci in self._conv_items.values():
            ci.apply_theme(theme)
        for i in range(self.messages_layout.count()):
            w = self.messages_layout.itemAt(i)
            if w and isinstance(w.widget(), ChatMessage):
                w.widget().apply_theme(theme)
