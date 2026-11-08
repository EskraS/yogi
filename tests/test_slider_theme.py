"""Slider handle (the circular knob) must be gray in light mode, white in dark."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from yogi.ui.settings import SettingsTab, theme_palette
from yogi.ui.theme_helpers import slider_stylesheet


_APP = None


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class TestSliderHandleTheme(unittest.TestCase):
    def test_light_palette_uses_gray_handle(self):
        p = theme_palette("light")
        self.assertEqual(p["slider_handle"], "#9ca3af")
        self.assertEqual(p["slider_handle_hover"], "#71717a")

    def test_dark_palette_keeps_white_handle(self):
        p = theme_palette("dark")
        self.assertEqual(p["slider_handle"], "#ffffff")
        self.assertEqual(p["slider_handle_hover"], "#b3b3b3")

    def test_applied_stylesheet_follows_theme(self):
        tab = SettingsTab()
        try:
            tab.apply_theme("light")
            light_ss = tab._param_sliders[0].styleSheet()
            self.assertIn("background: #9ca3af", light_ss)
            self.assertNotIn("background: #ffffff", light_ss)

            tab.apply_theme("dark")
            dark_ss = tab._param_sliders[0].styleSheet()
            self.assertIn("background: #ffffff", dark_ss)
        finally:
            tab.deleteLater()

    def test_stylesheet_helper_substitutes_handle_color(self):
        ss = slider_stylesheet("#e4e4e7", "#e5e5e5", "#9ca3af", "#71717a")
        self.assertIn("background: #9ca3af", ss)
        self.assertIn("background: #71717a", ss)
        self.assertNotIn("background: #ffffff", ss)
