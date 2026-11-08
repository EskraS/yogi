# Third-Party Notices

Yogi uses the following third-party software and assets.
This file is for attribution and license awareness; it is not legal advice.
License texts are those of the upstream projects - consult each project for the
authoritative terms, especially before commercial distribution.

## Critical copyleft / dual-license components

### PySide6 (Qt for Python) + Qt WebEngine
- Vendor: The Qt Company
- License: LGPL-3.0 **or** GPL-2.0/GPL-3.0 **or** Qt commercial license
- Notes: Yogi uses PySide6 under LGPL-3.0. The Qt modules used (QtCore, QtGui,
  QtWidgets, QtSvg, QtWebEngine) are available under LGPL-3.0.
  LGPL obligations when distributing: ship the LGPL-3.0 text, keep Qt/PySide6
  as separate replaceable shared libraries (no static linking), do not forbid
  reverse engineering for debugging those changes, and point to the Qt/PySide6
  source. WebEngine also includes Chromium third-party components with their
  own notices.
- https://doc.qt.io/qtforpython-6/licenses.html

### python-chess (`chess`)
- License: GPL-3.0-or-later
- https://github.com/niklasf/python-chess

### PyAV (`av`) + FFmpeg
- PyAV: BSD-style (see upstream LICENSE)
- Bundled/linked FFmpeg: often LGPL and/or GPL depending on the build/wheel
- Verify the exact FFmpeg configuration in your distributed runtime.

## Permissive / attribution-friendly Python packages

| Package | Typical license |
|---------|-----------------|
| QtAwesome | MIT (bundled icon fonts have additional terms; see below) |
| requests | Apache-2.0 |
| numpy | BSD |
| sounddevice | MIT |
| mss | MIT |
| Pillow | HPND / permissive (see upstream) |
| keyboard | MIT |
| websocket-client | Apache-2.0 |
| faster-whisper | MIT |
| keyring | MIT / PSF-style |
| onnxruntime | MIT |

Also keep licenses for transitive deps installed with the above
(e.g. ctranslate2, tokenizers, huggingface_hub) when shipping a bundle.

## Fonts & icons

### Inter
- License: SIL Open Font License 1.1
- Keep `fonts/Inter/OFL.txt` with redistributed font files.
- https://github.com/rsms/inter

### Font Awesome (via QtAwesome)
- Fonts: SIL OFL 1.1
- Icons (SVG/JS packaging upstream): CC BY 4.0
- Code: MIT
- Keep attribution; do not strip embedded license comments from font/code files.

## Models & online services (not in requirements.txt, but used at runtime)

- Whisper / faster-whisper model weights: follow the license of the specific
  model files you download and redistribute (if any).
- OpenRouter, xAI/Grok TTS, Fish Audio, and similar APIs: governed by each
  provider’s Terms of Service, not an open-source license.

## Distribution checklist

- [ ] Decide Yogi’s own `LICENSE`.
- [ ] Ship the LGPL-3.0 text and keep Qt/PySide6 libraries replaceable in bundles.
- [ ] Re-check `chess` (GPL-3.0) and FFmpeg/PyAV for closed-source compatibility.
- [ ] Ship Inter `OFL.txt` and do not remove Font Awesome attribution.
- [ ] Include this notices file (or equivalent) with binary releases.

## Chess piece classifier and board finder
- Source: chessimg2pos by Marcodicio (https://github.com/mdicio/chessimg2pos),
  via ChessSnip (https://github.com/DaoraDio/ChessSnip)
- License: MIT, Copyright (c) 2025 Marcodicio
- Used for: the ONNX piece model and the board-detection code in the chess block
- The full MIT license text must be included with this notice.