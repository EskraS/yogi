# Third-Party Notices

Yogi uses the following third-party software and assets.
This file is for attribution and license awareness; it is not legal advice.
License texts are those of the upstream projects - consult each project for the
authoritative terms, especially before commercial distribution.

Yogi itself is licensed under PolyForm Noncommercial 1.0.0 (`LICENSE.txt`).

## Blocks (separate programs)

Installed blocks under `modules/` are separate programs. Each block carries its
own license and dependencies. Yogi starts a block as its own process, passes a
screenshot path, and reads text from stdout. Block code is never imported into
the Yogi process. GPL (or other) block licenses do not apply to Yogi core.

Chess (python-chess, Stockfish, ONNX board recognition, chessimg2pos/ChessSnip)
belongs in the chess block repo, not in Yogi notices.

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

- [x] Yogi `LICENSE.txt` is PolyForm Noncommercial 1.0.0 with Required Notice.
- [ ] Ship the LGPL-3.0 text and keep Qt/PySide6 libraries replaceable in bundles.
- [ ] Re-check FFmpeg/PyAV for your distribution story.
- [ ] Ship Inter `OFL.txt` and do not remove Font Awesome attribution.
- [ ] Include this notices file (or equivalent) with binary releases.
- [ ] Do not ship community blocks inside the Yogi core package; they keep their own licenses.
