"""key_store: per-provider get/set/delete, masking, and failures that never leak the key."""

import unittest
from unittest import mock

from yogi.core import key_store

SECRET = "sk-or-v1-abcdefghijklmnop1234"


class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        del self.store[(service, user)]


class TestKeyStore(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeKeyring()
        patcher = mock.patch.object(key_store, "keyring", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_set_get_delete_round_trip(self):
        self.assertIsNone(key_store.get_key("openrouter"))
        key_store.set_key("openrouter", f"  {SECRET}  ")
        self.assertEqual(key_store.get_key("openrouter"), SECRET)
        self.assertIn(("Yogi", "openrouter"), self.fake.store)
        self.assertTrue(key_store.has_key("openrouter"))

        key_store.delete_key("openrouter")
        self.assertFalse(key_store.has_key("openrouter"))

    def test_delete_missing_key_is_noop(self):
        key_store.delete_key("openrouter")

    def test_empty_key_rejected(self):
        with self.assertRaises(key_store.KeyStoreError):
            key_store.set_key("openrouter", "   ")

    def test_unknown_provider_rejected(self):
        with self.assertRaises(key_store.KeyStoreError):
            key_store.get_key("nope")

    def test_backend_failure_message_hides_key(self):
        broken = mock.Mock()
        broken.set_password.side_effect = RuntimeError(f"vault rejected {SECRET}")
        with mock.patch.object(key_store, "keyring", broken):
            with self.assertRaises(key_store.KeyStoreError) as ctx:
                key_store.set_key("openrouter", SECRET)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_mask_shows_last_four_only(self):
        self.assertEqual(key_store.mask(SECRET), "\u2022\u2022\u2022\u20221234")
        self.assertEqual(key_store.mask("short"), "\u2022" * 4)


if __name__ == "__main__":
    unittest.main()
