import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from yogi.ui import settings

_APP = QApplication.instance() or QApplication([])


def _write(name, content):
    d = tempfile.mkdtemp()
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


class TestParsePromptFile(unittest.TestCase):
    def test_txt_is_whole_prompt(self):
        presets, err = settings.parse_prompt_file(_write("p.txt", "\ufeff  Be a pirate.\r\nShort.  "))
        self.assertIsNone(err)
        self.assertEqual(presets, [{"prompt": "Be a pirate.\nShort.", "params": {}}])

    def test_json_shapes(self):
        cases = [
            ('"Just text"', ["Just text"]),
            ('{"prompt": "A", "params": {"temperature": 0.3, "bad": "x", "flag": true}}', ["A"]),
            ('{"system_prompt": "B"}', ["B"]),
            ('{"messages": [{"role": "system", "content": "C"}, {"role": "user", "content": "hi"}]}', ["C"]),
            ('[{"prompt": "D"}, "E", 5]', ["D", "E"]),
            ('{"prompts": [{"text": "F"}]}', ["F"]),
        ]
        for raw, expected in cases:
            presets, err = settings.parse_prompt_file(_write("p.json", raw))
            self.assertIsNone(err, raw)
            self.assertEqual([p["prompt"] for p in presets], expected, raw)
        presets, _ = settings.parse_prompt_file(_write("p.json", cases[1][0]))
        self.assertEqual(presets[0]["params"], {"temperature": 0.3})

    def test_errors(self):
        self.assertTrue(settings.parse_prompt_file(_write("p.md", "x"))[1])
        self.assertTrue(settings.parse_prompt_file(_write("p.txt", "   "))[1])
        self.assertTrue(settings.parse_prompt_file(_write("p.json", "{not json"))[1])
        self.assertTrue(settings.parse_prompt_file(_write("p.json", '{"nothing": 1}'))[1])
        self.assertTrue(settings.parse_prompt_file(os.path.join(tempfile.mkdtemp(), "x.txt"))[1])


class TestImportIntoDropdown(unittest.TestCase):
    def test_import_adds_to_dropdown_and_skips_duplicates(self):
        with mock.patch.object(settings, "load_saved_prompts", return_value=[]), \
                mock.patch.object(settings, "store_saved_prompts", return_value=True) as store, \
                mock.patch.object(settings, "store_app_settings"):
            tab = settings.SettingsTab()
            path = _write("p.json", json.dumps([{"prompt": "Imported one"}, "Imported two"]))
            self.assertEqual(tab.import_prompt_file(path), 2)
            items = [tab.prompt_select.itemText(i) for i in range(tab.prompt_select.count())]
            self.assertEqual(items, ["Default", "Imported one", "Imported two"])
            self.assertEqual(tab.prompt_select.currentIndex(), 0)
            store.assert_called()
            self.assertEqual(tab.import_prompt_file(path), 0)
            self.assertEqual(tab.prompt_select.count(), 3)


if __name__ == "__main__":
    unittest.main()
