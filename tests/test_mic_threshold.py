"""Microphone Threshold: dB mapping, stt verdict and settings validation."""

import unittest
from unittest import mock

import numpy as np

from yogi.audio import devices as audio_devices
from yogi.audio import stt
from yogi.audio.mic_threshold import level_to_pos, pos_to_level


class TestMapping(unittest.TestCase):
    def test_round_trip_and_ends(self):
        for level in (0.001, 0.012, 0.1, 1.0):
            self.assertAlmostEqual(pos_to_level(level_to_pos(level)), level, places=6)
        self.assertEqual(level_to_pos(0.0), 0.0)
        self.assertEqual(level_to_pos(5.0), 1.0)
        self.assertLess(level_to_pos(0.012), level_to_pos(0.1))


class TestSttUsesThreshold(unittest.TestCase):
    def _push(self, threshold, rms):
        tracker = stt._LevelTracker(threshold=threshold)
        tracker.push(np.full(800, rms, dtype=np.float32))
        return tracker.snapshot()[0]

    def test_only_sound_above_threshold_counts(self):
        self.assertTrue(self._push(0.05, 0.06))
        self.assertFalse(self._push(0.05, 0.04))

    def test_tracker_reads_global_threshold(self):
        old = audio_devices.get_speech_threshold()
        try:
            audio_devices.set_speech_threshold(0.2)
            self.assertFalse(stt._LevelTracker().snapshot()[0])
            tracker = stt._LevelTracker()
            tracker.push(np.full(800, 0.1, dtype=np.float32))
            self.assertFalse(tracker.snapshot()[0])
            self.assertEqual(tracker.snapshot()[2], 0.2)
        finally:
            audio_devices.set_speech_threshold(old)

    def test_set_threshold_clamps(self):
        old = audio_devices.get_speech_threshold()
        try:
            audio_devices.set_speech_threshold(0)
            self.assertEqual(audio_devices.get_speech_threshold(), audio_devices.MIN_SPEECH_THRESHOLD)
        finally:
            audio_devices.set_speech_threshold(old)


class TestSavedThreshold(unittest.TestCase):
    def _load(self, raw):
        from yogi.ui import settings

        with mock.patch.object(settings, "QSettings") as qs:
            qs.return_value.value.return_value = raw
            return settings.load_app_settings()

    def test_valid_threshold_loads(self):
        self.assertEqual(self._load('{"mic_threshold": 0.05}')["mic_threshold"], 0.05)

    def test_bad_threshold_ignored(self):
        for raw in ('{"mic_threshold": 2}', '{"mic_threshold": "x"}', '{"mic_threshold": true}'):
            self.assertNotIn("mic_threshold", self._load(raw))

    def test_followup_time_loads_and_rejects_out_of_range(self):
        self.assertEqual(self._load('{"followup_window_s": 4.5}')["followup_window_s"], 4.5)
        for raw in ('{"followup_window_s": 0}', '{"followup_window_s": 99}', '{"followup_window_s": "3"}'):
            self.assertNotIn("followup_window_s", self._load(raw))


class TestStopHotkeySetting(unittest.TestCase):
    def test_record_escape_as_stop_key_and_reject_duplicates(self):
        from PySide6.QtCore import QSettings, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from yogi.ui import settings

        qs = QSettings("Yogi", "Yogi")
        backup = qs.value("app_settings", None)
        try:
            with mock.patch.object(settings, "store_app_settings"):
                tab = settings.SettingsTab()
                tab.settings["hotkey"] = "`"
                tab.settings["stop_hotkey"] = "Q"

                def press(key):
                    tab.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

                tab.start_recording_hotkey("stop_hotkey")
                press(Qt.Key.Key_Escape)
                self.assertEqual(tab.settings["stop_hotkey"], "Escape")
                self.assertEqual(tab.stop_hotkey_input.text(), "Escape")
                self.assertFalse(tab.is_recording)

                tab.settings["hotkey"] = "F5"
                with mock.patch.object(tab, "_show_error_banner") as banner:
                    tab.start_recording_hotkey("stop_hotkey")
                    press(Qt.Key.Key_F5)
                banner.assert_called_once()
                self.assertEqual(tab.settings["stop_hotkey"], "Escape")
        finally:
            if backup is None:
                qs.remove("app_settings")
            else:
                qs.setValue("app_settings", backup)
        del app


class TestPlayback(unittest.TestCase):
    def test_play_drains_echo_in_order_and_pads_silence(self):
        from yogi.audio.mic_threshold import MicLevelMonitor

        m = MicLevelMonitor()
        m._callback(np.full((3, 1), 0.5, dtype=np.float32), 3, None, None)
        m._callback(np.full((3, 1), 0.25, dtype=np.float32), 3, None, None)
        out = np.ones((4, 1), dtype=np.float32)
        m._play(out, 4, None, None)
        np.testing.assert_allclose(out[:, 0], [0.5, 0.5, 0.5, 0.25])
        out = np.ones((4, 1), dtype=np.float32)
        m._play(out, 4, None, None)
        np.testing.assert_allclose(out[:, 0], [0.25, 0.25, 0, 0])

    def test_below_threshold_is_not_played(self):
        from yogi.audio.mic_threshold import MicLevelMonitor

        m = MicLevelMonitor()
        m.set_threshold(0.3)
        m._callback(np.full((3, 1), 0.2, dtype=np.float32), 3, None, None)
        m._callback(np.full((3, 1), 0.5, dtype=np.float32), 3, None, None)
        out = np.ones((6, 1), dtype=np.float32)
        m._play(out, 6, None, None)
        np.testing.assert_allclose(out[:, 0], [0.5, 0.5, 0.5, 0, 0, 0])
        # The meter still shows the loudest level, gated or not.
        self.assertAlmostEqual(m.take_level(), 0.5)


if __name__ == "__main__":
    unittest.main()
