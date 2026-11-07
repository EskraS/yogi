"""Project-root path helpers. Assets and modules/ stay at the repo root."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent


def asset(*parts: str) -> Path:
    """Path under the project root (logo/, fonts/, orb.html, …)."""
    return ROOT.joinpath(*parts)
