"""Shared QSS helpers for the Yogi desktop app.

Centralises stylesheet builders that were previously copy-pasted across
``settings.py``, ``blocks_tab.py`` and ``history_tab.py``.
"""

# Used as the active/selected accent throughout the app.
ACCENT_GREEN = "#22c55e"

# Light-theme slider groove colour (also used as the "resting" track colour
# in the light theme). Exposed so the dark theme can choose a different one.
SLIDER_TRACK_REST_LIGHT = "#e5e5e5"


def scrollbar_stylesheet(track: str, handle: str, handle_hover: str,
                         background: str = "transparent") -> str:
    """Return QSS for a QScrollArea with slim, rounded scrollbars.

    Args:
        track: Colour of the scrollbar groove (usually a translucent overlay).
        handle: Resting colour of the scrollbar handle.
        handle_hover: Hover colour of the scrollbar handle.
        background: Background colour of the scroll area itself.
    """
    return f"""
        QScrollArea {{
            border: none;
            background: {background};
        }}
        QScrollBar:vertical {{
            border: none;
            background: transparent;
            width: 8px;
            margin: 8px 4px 8px 0;
        }}
        QScrollBar::groove:vertical {{
            background: {track};
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {handle};
            min-height: 30px;
            margin: 1px;
            border: none;
            border-radius: 3px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {handle_hover};
        }}
        QScrollBar:horizontal {{
            border: none;
            background: transparent;
            height: 8px;
            margin: 0 8px 4px 8px;
        }}
        QScrollBar::groove:horizontal {{
            background: {track};
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {handle};
            min-width: 30px;
            margin: 1px;
            border: none;
            border-radius: 3px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {handle_hover};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            height: 0;
            width: 0;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical,
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {{
            background: transparent;
            border-radius: 999px;
        }}
    """


def line_edit_stylesheet(input_bg: str, input_border: str, input_text: str) -> str:
    """Return QSS for a standard single-line text field."""
    return f"""
        QLineEdit {{
            background-color: {input_bg};
            border: 1px solid {input_border};
            border-radius: 4px;
            color: {input_text};
            padding: 6px 10px;
            font-family: Inter;
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border-color: {ACCENT_GREEN};
        }}
    """


def combo_stylesheet(input_bg: str, input_border: str, input_text: str,
                     selection_bg: str) -> str:
    """Return QSS for a read-only combo box and its popup."""
    return f"""
        QComboBox {{
            background-color: {input_bg};
            border: 1px solid {input_border};
            border-radius: 4px;
            color: {input_text};
            padding: 6px 10px;
            font-family: Inter;
            font-size: 13px;
        }}
        QComboBox:focus {{
            border-color: {ACCENT_GREEN};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 28px;
        }}
        QComboBox::down-arrow {{
            image: none;
        }}
        QAbstractItemView {{
            background-color: {input_bg};
            border: 1px solid {input_border};
            selection-background-color: {selection_bg};
            color: {input_text};
        }}
    """


def slider_stylesheet(
    groove: str,
    track_rest: str,
    handle: str = "#ffffff",
    handle_hover: str = "#b3b3b3",
) -> str:
    """Return QSS for a horizontal slider.

    ``groove`` colours the empty groove; ``track_rest`` colours the portion
    after the handle (the remaining track). ``handle`` / ``handle_hover``
    colour the circular knob so light theme can use gray instead of white.
    """
    return f"""
        QSlider::groove:horizontal {{
            height: 6px;
            background: {groove};
            border-radius: 3px;
        }}
        QSlider::sub-page:horizontal {{
            background: {ACCENT_GREEN};
            border-radius: 3px;
        }}
        QSlider::sub-page:horizontal:disabled {{
            background: #808080;
            border-radius: 3px;
        }}
        QSlider::add-page:horizontal {{
            background: {track_rest};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            background: {handle};
        }}
        QSlider::handle:horizontal:hover {{
            background: {handle_hover};
        }}
        QSlider::handle:horizontal:disabled {{
            background: #808080;
        }}
        QSlider::handle:horizontal:disabled:hover {{
            background: #808080;
        }}
    """


def mix_hex(c1: str, c2: str, t: float) -> str:
    """Linearly interpolate between two hex colours; t in [0, 1]."""
    from PySide6.QtGui import QColor

    a = QColor(c1)
    b = QColor(c2)
    r = round(a.red() + (b.red() - a.red()) * t)
    g = round(a.green() + (b.green() - a.green()) * t)
    bl = round(a.blue() + (b.blue() - a.blue()) * t)
    return QColor(r, g, bl).name()
