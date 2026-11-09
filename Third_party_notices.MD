# Third-Party Notices

Yogi uses the following third-party software and assets.
This file is for attribution and license awareness; it is not legal advice.
License texts are those of the upstream projects — consult each project for the
authoritative terms, especially before distribution.

Yogi itself is licensed under PolyForm Noncommercial 1.0.0 (`LICENSE.txt`).
Required Notice: Copyright (c) 2026 EskraS.

## Blocks (separate programs)

Installed blocks under `modules/` are separate programs, not part of Yogi’s
licensed work. Each block carries its own license and dependencies and should
ship its own notices. Yogi starts a block as its own process, passes a
screenshot path, and reads text from stdout. Block code is never imported into
the Yogi process.

Yogi’s PolyForm Noncommercial terms apply to Yogi. A block’s terms apply to
that block. Do not assume a block’s license (including GPL) extends to Yogi
core, or that Yogi’s license covers the block.

## Critical copyleft / dual-license components

### PySide6 + shiboken6 (Qt for Python) + Qt WebEngine
- Vendor: The Qt Company
- License: LGPL-3.0-only **or** GPL-2.0-only **or** GPL-3.0-only
- Notes: Yogi uses PySide6 / shiboken6 under **LGPL-3.0**. Modules in use:
  QtCore, QtGui, QtWidgets, QtSvg, QtWebEngine.
  LGPL obligations when distributing binaries: ship the LGPL-3.0 text, keep
  Qt/PySide6/shiboken6 as separate replaceable shared libraries (no static
  linking into Yogi), do not forbid reverse engineering for debugging those
  libraries, and point to the Qt/PySide6 source offer.
  WebEngine also includes Chromium third-party components with their own notices.
- https://doc.qt.io/qtforpython-6/licenses.html

### Not used: PyAV (`av`) + FFmpeg
PyPI PyAV wheels typically bundle a GPL build of FFmpeg, so Yogi does **not**
depend on or ship `av`.

- Text-to-speech requests raw 24 kHz int16 mono PCM from every provider
  (Grok, OpenRouter, Fish Audio). No decoder is required.
- `faster-whisper` is installed with `--no-deps`. Yogi stubs the `av` import
  before loading it, because Yogi passes numpy arrays and never asks
  faster-whisper to decode audio files.
- When freezing with PyInstaller, pass `--exclude-module av` and confirm no
  `av` package or FFmpeg DLLs appear in the bundle.

## Direct Python dependencies

Install:

```bash
pip install -r requirements.txt
pip install --no-deps "faster-whisper>=1.2,<2"
```

| Package | License (as declared upstream) |
|---------|--------------------------------|
| PySide6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (Yogi uses LGPL-3.0) |
| shiboken6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (Yogi uses LGPL-3.0) |
| QtAwesome | MIT (bundled icon fonts: see Fonts & icons) |
| requests | Apache-2.0 |
| numpy | BSD-3-Clause (plus permissive notices for bundled pieces) |
| sounddevice | MIT (uses PortAudio; PortAudio is MIT-style) |
| mss | MIT |
| Pillow | MIT-CMU / HPND-style (see upstream) |
| keyboard | MIT |
| websocket-client | Apache-2.0 |
| faster-whisper | MIT |
| ctranslate2 | MIT |
| huggingface-hub | Apache-2.0 |
| tokenizers | Apache-2.0 |
| onnxruntime | MIT |
| tqdm | MPL-2.0 AND MIT |
| keyring | MIT |

## Common transitive packages (also ship attribution when bundling)

| Package | License (as declared upstream) |
|---------|--------------------------------|
| certifi | MPL-2.0 |
| urllib3 | MIT |
| idna | BSD-3-Clause |
| charset-normalizer | MIT |
| cffi | MIT-0 |
| pycparser | BSD-3-Clause |
| PyYAML | MIT |
| filelock | MIT |
| fsspec | BSD-3-Clause |
| packaging | Apache-2.0 OR BSD-2-Clause |
| typing-extensions | PSF-2.0 |
| hf-xet | Apache-2.0 |
| jaraco.classes / jaraco.context / jaraco.functools | MIT |
| more-itertools | MIT |

File-level copyleft notes: **certifi** and parts of **tqdm** use MPL-2.0.
That requires keeping those files under MPL terms and providing source for
modifications to those files; it does **not** force Yogi itself onto the GPL.

Re-scan the frozen bundle before each release — transitive sets change with
versions.

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

## Models & online services (not in requirements.txt)

- Whisper / faster-whisper model weights: follow the license of the specific
  model files you download and redistribute (if any).
- OpenRouter, xAI/Grok TTS, Fish Audio, and similar APIs: governed by each
  provider’s Terms of Service, not an open-source license.

## Distribution checklist

- [x] Yogi `LICENSE.txt` is PolyForm Noncommercial 1.0.0 with Required Notice.
- [x] Core avoids PyQt6, PyAV/FFmpeg, and in-process GPL plugins (blocks are subprocess-only; TTS is PCM-only; STT stubs `av`).
- [ ] Ship LGPL-3.0 text and keep Qt/PySide6/shiboken6 libraries replaceable in bundles.
- [ ] Confirm `av` is absent from the bundle (`--exclude-module av`; no FFmpeg DLLs).
- [ ] Ship Inter `OFL.txt` and do not remove Font Awesome attribution.
- [ ] Include this notices file (or equivalent) with binary releases.
- [ ] Do not ship community blocks inside the Yogi core package; they keep their own licenses.
- [ ] Re-check transitive package licenses after dependency bumps.
