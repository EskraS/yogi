"""Yogi application package."""

import os

# QtAwesome loads Qt through QtPy, which picks PyQt6 over PySide6 when both
# are installed. Mixing bindings in one process crashes.
os.environ.setdefault("QT_API", "pyside6")
