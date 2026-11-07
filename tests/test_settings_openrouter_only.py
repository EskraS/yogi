"""Settings tab is OpenRouter-only: no provider picker, no other-provider sliders."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QRadioButton, QSlider

from yogi.audio import vocal
from yogi.ui.settings import PromptEditorDialog, RecordButton, SettingsTab, vision_model_info


_APP = None


def setUpModule():
    global _APP
    _APP = QApplication.instance() or QApplication([])


class TestSettingsOpenRouterOnly(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("yogi.ui.settings.key_store.keyring")
        self.keyring = patcher.start()
        self.keyring.get_password.return_value = None
        self.addCleanup(patcher.stop)
        # Keep tests off the real registry.
        for name, value in (
            ("load_saved_prompts", []),
            ("store_saved_prompts", True),
            ("load_slider_values", {}),
            ("store_slider_values", None),
        ):
            p = mock.patch(f"yogi.ui.settings.{name}", return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.tab = SettingsTab()

    def tearDown(self):
        self.tab.deleteLater()

    def test_api_key_label(self):
        self.assertEqual(self.tab.api_key_hint_label.text(), "Openrouter API Key")

    def test_api_key_not_in_settings_dict(self):
        self.assertNotIn("api_key", self.tab.settings)

    def test_saved_key_is_masked_and_never_shown(self):
        self.keyring.get_password.return_value = "sk-or-v1-secretsecret9876"
        with mock.patch("yogi.ui.settings._fetch_openrouter_models", return_value=(["m/a"], None)):
            self.tab.load_saved_keys()
        row = self.tab.api_key_row
        self.assertEqual(row.input.text(), "")
        self.assertTrue(row.input.isReadOnly())
        self.assertEqual(row.input.placeholderText(), "\u2022\u2022\u2022\u20229876")
        self.assertTrue(row.replace_btn.isVisibleTo(self.tab))
        self.assertTrue(row.delete_btn.isVisibleTo(self.tab))
        self.assertFalse(row.submit_btn.isVisibleTo(self.tab))

    def test_key_saved_only_after_successful_check(self):
        self.tab._check_openrouter = mock.Mock()
        self.tab._on_api_key_submitted("sk-or-v1-newkey00001111")
        self.keyring.set_password.assert_not_called()

        self.tab._pending_key = "sk-or-v1-newkey00001111"
        self.tab._on_openrouter_checked(self.tab._openrouter_check_id, None, "Invalid OpenRouter API key")
        self.keyring.set_password.assert_not_called()

        self.tab._pending_key = "sk-or-v1-newkey00001111"
        self.tab._on_openrouter_checked(self.tab._openrouter_check_id, ["m/a"], "")
        self.keyring.set_password.assert_called_once_with("Yogi", "openrouter", "sk-or-v1-newkey00001111")
        self.assertEqual(self.tab.api_key_row.input.placeholderText(), "\u2022\u2022\u2022\u20221111")

    def test_storage_failure_shows_banner_instead_of_raising(self):
        self.keyring.set_password.side_effect = RuntimeError("vault locked")
        self.tab._pending_key = "sk-or-v1-newkey00001111"
        with mock.patch.object(self.tab, "_show_api_error") as show:
            self.tab._on_openrouter_checked(self.tab._openrouter_check_id, ["m/a"], "")
        show.assert_called_once()
        self.assertNotIn("newkey", show.call_args[0][0])

    def test_no_provider_setting_or_widgets(self):
        self.assertNotIn("provider", self.tab.settings)
        self.assertFalse(hasattr(self.tab, "provider_select"))
        self.assertFalse(hasattr(self.tab, "_on_provider_changed"))
        self.assertFalse(hasattr(self.tab, "_verify_gemini"))
        self.assertFalse(hasattr(self.tab, "_verify_openai"))
        self.assertFalse(hasattr(self.tab, "_verify_anthropic"))
        self.assertFalse(hasattr(self.tab, "_gemini_unsupported_sliders"))
        self.assertFalse(hasattr(self.tab, "_update_gemini_param_enabled"))

    def test_no_provider_dropdown_labels_or_items(self):
        banned = {"OpenAI", "Anthropic", "Gemini", "Provider"}
        for combo in self.tab.findChildren(QComboBox):
            items = [combo.itemText(i) for i in range(combo.count())]
            for name in banned:
                self.assertNotIn(name, items)
        for label in self.tab.findChildren(QLabel):
            self.assertNotEqual(label.text(), "Provider")
            self.assertNotIn("Gemini", label.text())
            self.assertNotIn("Anthropic", label.text())
            self.assertNotIn("OpenAI", label.text())

    def test_context_window_slider_sits_above_max_tokens(self):
        titles = [lbl.text() for lbl in self.tab._slider_title_labels]
        self.assertLess(titles.index("Context Window"), titles.index("Max Tokens"))
        self.assertEqual(self.tab.settings["context_window"], 131072)
        self.assertEqual(self.tab.context_window_slider.minimum(), 2048)

    def test_surf_the_web_and_compact_reasoning_sit_under_reset(self):
        self.assertEqual(self.tab.surf_web_btn.text(), "Surf the web")
        self.assertTrue(self.tab.surf_web_btn.isCheckable())
        self.assertFalse(self.tab.surf_web_btn.isEnabled())
        self.assertFalse(self.tab.surf_web_btn.isChecked())
        self.assertEqual(self.tab.reasoning_hint_label.text(), "Reasoning effort")
        self.assertEqual(self.tab.reasoning_combo.currentText(), "Unavailable")
        self.assertFalse(self.tab.reasoning_combo.isEnabled())
        self.assertEqual(self.tab.reasoning_combo.currentData(), "off")
        self.assertIs(self.tab.reasoning_hint_label.parent(), self.tab.surf_web_btn.parent())

    def test_larger_model_keeps_context_smaller_model_clamps(self):
        self.tab.context_window_slider.setValue(32000)
        self.tab._vision_models = {
            "big/vl": vision_model_info({
                "id": "big/vl",
                "context_length": 1048576,
                "supported_parameters": ["tools"],
            })
        }
        self.tab._load_models(["big/vl"])
        self.assertEqual(self.tab.context_window_slider.maximum(), 1048576)
        self.assertEqual(self.tab.context_window_slider.value(), 32000)
        self.tab._vision_models = {
            "small/vl": vision_model_info({
                "id": "small/vl",
                "context_length": 8192,
                "supported_parameters": ["temperature"],
            })
        }
        self.tab._load_models(["small/vl"])
        self.assertEqual(self.tab.context_window_slider.maximum(), 8192)
        self.assertEqual(self.tab.context_window_slider.value(), 8192)

    def test_model_without_tools_greys_surf_the_web(self):
        self.tab._surf_web_wanted = True
        self.tab._vision_models = {
            "plain/vl": vision_model_info({
                "id": "plain/vl",
                "context_length": 8192,
                "supported_parameters": ["temperature", "max_tokens"],
            })
        }
        self.tab._load_models(["plain/vl"])
        self.assertFalse(self.tab.surf_web_btn.isEnabled())
        self.assertFalse(self.tab.surf_web_btn.isChecked())
        self.assertFalse(self.tab.settings["surf_web"])
        self.assertEqual(self.tab.reasoning_combo.currentText(), "Unavailable")
        self.assertEqual(self.tab.context_window_slider.maximum(), 8192)
        self.assertEqual(self.tab.context_window_slider.value(), 8192)

    def test_model_with_tools_enables_surf_the_web(self):
        self.tab._surf_web_wanted = True
        self.tab._vision_models = {
            "search/vl": vision_model_info({
                "id": "search/vl",
                "context_length": 32768,
                "supported_parameters": ["tools", "temperature"],
                "reasoning": {
                    "supported_efforts": ["high", "medium", "low"],
                    "mandatory": False,
                },
            })
        }
        self.tab._load_models(["search/vl"])
        self.assertTrue(self.tab.surf_web_btn.isEnabled())
        self.assertTrue(self.tab.surf_web_btn.isChecked())
        self.assertTrue(self.tab.settings["surf_web"])
        self.assertTrue(self.tab.reasoning_combo.isEnabled())
        self.assertLessEqual(self.tab.reasoning_combo.maximumWidth(), 120)
        self.assertNotEqual(self.tab.reasoning_combo.currentText(), "Unavailable")
        self.assertEqual(
            [self.tab.reasoning_combo.itemText(i) for i in range(self.tab.reasoning_combo.count())],
            ["Off", "Low", "Medium", "High"],
        )

    def test_mandatory_reasoning_has_no_off_and_runs_low_to_high(self):
        self.tab._vision_models = {
            "think/vl": vision_model_info({
                "id": "think/vl",
                "context_length": 8192,
                "supported_parameters": ["temperature"],
                "reasoning": {
                    "supported_efforts": ["high", "minimal", "low"],
                    "mandatory": True,
                },
            })
        }
        self.tab._load_models(["think/vl"])
        self.assertEqual(
            [self.tab.reasoning_combo.itemText(i) for i in range(self.tab.reasoning_combo.count())],
            ["Minimal", "Low", "High"],
        )

    def test_vision_model_info_reads_search_and_reasoning(self):
        info = vision_model_info({
            "id": "google/gemini-3-flash",
            "context_length": 1048576,
            "supported_parameters": ["tools", "reasoning"],
            "reasoning": {"supported_efforts": ["high", "low"], "mandatory": True},
        })
        self.assertTrue(info["can_search"])
        self.assertEqual(info["context_length"], 1048576)
        self.assertTrue(info["reasoning"]["mandatory"])
        self.assertFalse(vision_model_info({"id": "x", "supported_parameters": ["top_p"]})["can_search"])
        self.assertIsNone(vision_model_info({}))

    def test_all_param_sliders_enabled(self):
        self.assertTrue(self.tab._param_sliders)
        for slider in self.tab._param_sliders:
            self.assertIsInstance(slider, QSlider)
            self.assertTrue(slider.isEnabled())

    def test_prompt_field_opens_editor_and_saves(self):
        self.assertEqual(self.tab.prompt_hint_label.text(), "Prompt")
        self.assertEqual(self.tab.settings["prompt"], "")
        self.assertEqual(self.tab.prompt_field.placeholderText(), "Click to paste a prompt…")

        def fake_exec(dialog):
            dialog._editor.setPlainText("  Look at the screen and be brief.  ")
            return True

        with mock.patch.object(PromptEditorDialog, "exec", fake_exec):
            self.tab._on_prompt_field_clicked()

        self.assertEqual(
            self.tab.settings["prompt"], "Look at the screen and be brief."
        )
        self.assertEqual(self.tab.prompt_field.text(), "")
        self.assertEqual(self.tab.prompt_select.currentIndex(), 1)

    def test_surf_the_web_uses_the_painted_button(self):
        self.assertIsInstance(self.tab.surf_web_btn, RecordButton)
        self.assertEqual(self.tab.surf_web_btn.anim.duration(), 180)

    def test_vocal_provider_hitbox_stops_at_the_label(self):
        self.tab.resize(900, 1600)
        self.tab.show()
        _APP.processEvents()
        radio = self.tab._provider_radios[vocal.OPENROUTER]
        self.assertLess(radio.width(), 320)
        on_label = radio.mapTo(self.tab, QPoint(radio.width() - 4, radio.height() // 2))
        self.assertIsInstance(self.tab.childAt(on_label), QRadioButton)
        past_label = radio.mapTo(self.tab, QPoint(radio.width() + 48, radio.height() // 2))
        self.assertNotIsInstance(self.tab.childAt(past_label), QRadioButton)

class TestSavedPrompts(unittest.TestCase):
    def setUp(self):
        patchers = (
            mock.patch("yogi.ui.settings.key_store.keyring", **{"get_password.return_value": None}),
            mock.patch("yogi.ui.settings.load_saved_prompts", return_value=[]),
            mock.patch("yogi.ui.settings.load_slider_values", return_value={}),
            mock.patch("yogi.ui.settings.store_slider_values"),
            mock.patch("yogi.ui.settings.store_saved_prompts", return_value=True),
        )
        for patcher in patchers:
            self.store = patcher.start()
            self.addCleanup(patcher.stop)
        self.tab = SettingsTab()

    def tearDown(self):
        self.tab.deleteLater()

    def test_default_selected_when_nothing_saved(self):
        self.assertEqual(self.tab.prompt_select.count(), 1)
        self.assertEqual(self.tab.prompt_select.currentText(), "Default")
        self.assertEqual(self.tab._prompt_delegate.locked_rows, {0})

    def test_empty_prompt_is_not_saved(self):
        self.tab._save_current_prompt()
        self.store.assert_not_called()

    def test_save_select_and_delete(self):
        self.tab.settings["prompt"] = "Be terse."
        self.tab.temp_slider.setValue(20)
        self.tab._save_current_prompt()
        self.assertEqual(self.tab.prompt_select.count(), 2)
        saved = self.store.call_args[0][0][0]
        self.assertEqual(saved["prompt"], "Be terse.")
        self.assertEqual(saved["params"]["temperature"], 0.2)

        self.tab.settings["prompt"] = "other"
        self.tab.temp_slider.setValue(90)
        self.tab._on_saved_prompt_selected(1)
        self.assertEqual(self.tab.settings["prompt"], "Be terse.")
        self.assertEqual(self.tab.settings["temperature"], 0.2)

        self.tab._on_saved_prompt_selected(0)
        self.assertEqual(self.tab.settings["prompt"], "")

        self.tab._on_saved_prompt_selected(1)
        self.tab._delete_saved_prompt(0)
        self.assertEqual(self.tab.prompt_select.count(), 1)
        self.assertEqual(self.tab.prompt_select.currentIndex(), 0)
        self.assertEqual(self.tab.settings["prompt"], "")
        self.assertEqual(self.store.call_args[0][0], [])

    def test_delegate_survives_theme_change(self):
        self.tab.apply_theme("light")
        self.assertIs(self.tab.prompt_select.itemDelegate(), self.tab._prompt_delegate)
