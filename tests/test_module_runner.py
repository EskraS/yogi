"""Block runner: separate process, stdout text, non-zero exit ignored."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from yogi.core import module_loader


def _write_block(root: Path, module_id: str, script: str, *, followup=False):
    folder = root / module_id
    folder.mkdir()
    (folder / "manifest.json").write_text(
        "{\n"
        f'  "name": "{module_id.title()}",\n'
        '  "description": "test block",\n'
        '  "entry": "entry.py"'
        + (',\n  "followup_refresh": true' if followup else "")
        + "\n}\n",
        encoding="utf-8",
    )
    (folder / "entry.py").write_text(script, encoding="utf-8")
    return folder


class TestModuleRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.image = Image.new("RGB", (8, 8), color=(0, 0, 0))

    def tearDown(self):
        self._tmp.cleanup()

    def test_stdout_text_is_returned(self):
        _write_block(
            self.root,
            "hello",
            "import sys\n"
            "print('hi')\n",
        )
        text = module_loader.run_enabled_modules(self.image, root=self.root)
        self.assertEqual(text, "[Hello]\nhi")

    def test_nonzero_exit_returns_empty(self):
        _write_block(
            self.root,
            "boom",
            "import sys\n"
            "print('should ignore')\n"
            "sys.exit(1)\n",
        )
        text = module_loader.run_enabled_modules(self.image, root=self.root)
        self.assertEqual(text, "")

    def test_followup_refresh_ids(self):
        _write_block(self.root, "plain", "print('x')\n")
        _write_block(self.root, "refresh", "print('y')\n", followup=True)
        self.assertEqual(
            module_loader.followup_refresh_ids(root=self.root),
            ("refresh",),
        )


if __name__ == "__main__":
    unittest.main()
