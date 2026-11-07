# Third-Party Notices

Yogi uses the following third-party software and assets.
This file is for attribution and license awareness; it is not legal advice.
License texts are those of the upstream projects — consult each project for the
authoritative terms, especially before commercial distribution.

## Critical copyleft / dual-license components

### PyQt6 / PyQt6-WebEngine
- Vendor: Riverbank Computing
- License: GPL-3.0 **or** Riverbank commercial license
- Notes: Free PyPI wheels are GPL-3.0. Proprietary distribution generally
  requires a commercial PyQt (and WebEngine) license from Riverbank.
  Qt libraries themselves are typically LGPL/GPL depending on module;
  WebEngine also includes Chromium third-party components.

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

- [ ] Decide Yogi’s own `LICENSE` (GPL-compatible if using free PyQt without a commercial license).
- [ ] If shipping closed-source: obtain commercial PyQt (+ WebEngine) as needed.
- [ ] Re-check `chess` and FFmpeg/PyAV for closed-source compatibility.
- [ ] Ship Inter `OFL.txt` and do not remove Font Awesome attribution.
- [ ] Include this notices file (or equivalent) with binary releases.