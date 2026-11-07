"""history_store save / load / delete against a temporary folder."""

import os
import tempfile
import unittest
from unittest import mock

from yogi.core import history_store


class TestHistoryStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(history_store, "HISTORY_DIR", self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(history_store.set_listener, None)

    def test_empty_folder_loads_no_chats(self):
        self.assertEqual(history_store.load_chats(), [])

    def test_missing_folder_loads_no_chats(self):
        with mock.patch.object(history_store, "HISTORY_DIR", os.path.join(self._tmp.name, "nope")):
            self.assertEqual(history_store.load_chats(), [])

    def test_save_load_round_trip_with_screenshot(self):
        heard = []
        history_store.set_listener(heard.append)
        turns = [("What is  this\nerror?", "A typo."), ("Where?", "Line 3.")]
        chat = history_store.save_chat("c1", "2026-10-30T00:30:00", turns, b"jpeg-bytes")

        self.assertEqual(heard, [chat])
        [loaded] = history_store.load_chats()
        self.assertEqual(loaded["title"], "What is this error?")
        self.assertEqual(
            [m["role"] for m in loaded["messages"]], ["user", "assistant", "user", "assistant"]
        )
        self.assertEqual(loaded["messages"][3]["content"], "Line 3.")
        with open(loaded["screenshot"], "rb") as f:
            self.assertEqual(f.read(), b"jpeg-bytes")

    def test_later_save_keeps_first_screenshot(self):
        history_store.save_chat("c1", "t", [("q", "a")], b"first")
        history_store.save_chat("c1", "t", [("q", "a"), ("q2", "a2")], b"second")
        with open(history_store.screenshot_path("c1"), "rb") as f:
            self.assertEqual(f.read(), b"first")
        self.assertEqual(len(history_store.load_chats()[0]["messages"]), 4)

    def test_newest_update_first(self):
        with mock.patch.object(history_store, "datetime") as dt:
            dt.now.return_value.isoformat.return_value = "2026-10-30T01:00:00"
            history_store.save_chat("old", "t", [("q", "a")])
            dt.now.return_value.isoformat.return_value = "2026-10-30T02:00:00"
            history_store.save_chat("new", "t", [("q", "a")])
        self.assertEqual([c["id"] for c in history_store.load_chats()], ["new", "old"])

    def test_unreadable_file_is_skipped(self):
        history_store.save_chat("good", "t", [("q", "a")])
        with open(os.path.join(self._tmp.name, "bad.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual([c["id"] for c in history_store.load_chats()], ["good"])

    def test_delete_removes_chat_and_screenshot(self):
        history_store.save_chat("c1", "t", [("q", "a")], b"jpeg")
        self.assertTrue(history_store.delete_chat("c1"))
        self.assertEqual(history_store.load_chats(), [])
        self.assertFalse(os.path.exists(history_store.screenshot_path("c1")))


if __name__ == "__main__":
    unittest.main()
