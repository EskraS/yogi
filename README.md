# Yogi

Voice + vision desktop API based assistant.

## License

[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) - see `LICENSE.txt`.

Third-party attribution: [`Third_party_notices.MD`](Third_party_notices.MD).

# What is Yogi?
Yogi is a visual assistant that uses OpenRouter's visual API models and various TTS API based services (Grok, OpenRouter, Fish Audio) to communicate with user and assist them in variety of tasks. Local Whisper handles speech-to-text. Community blocks can add extra screen context and power yogi to perform even better than just a from-scratch visual model.

## How it works

**Preparing** 
- Make sure both API fields (For visual model and vocal model) are filled
- Activation and Stop hotkeys are configured
- Audio input and output are configured
- Follow up question timer is set (How much time you have to ask a followup question after yogi replies)


1. **Step1** - Press the activate button and drag your mouse across the area you want to capture.
2. **Step2** - The orb will appear, which means that your microphone is being recorded. Ask your question.
3. **Step3** - Wait for the reply which will be read out by your selected TTS model. 
4. **Step4** - Ask a follow up question or just stay silent. Yogi will close by itself. You can also just press the stop button so it closes faster.

Important note: The speed on how fast you will get your reply as well as how good the visual recognition is solely depends on your selected model. I give you freedom of choice to use both super cheap as well as frontier models to find your desired sweet spot. 

## Additional Settings
Yogi supports custom prompts that let you tailor the responses you get. You can either paste them or import them as files with .json or .txt extension.

Yogi lets you tweak models parameters too. Sliders in Visual model settings will let you personalize every model even further.

Quick breakdown of each slider:

- **Context Window** - How much past conversation + image/prompt Yogi can keep in mind for this request. Bigger = more history, higher cost.
- **Max Tokens** - Hard cap on how long the reply can be. Raise it for long answers; lower it to keep replies short and cheap.
- **Temperature** - Randomness. Low = steady and focused. High = more creative / varied wording.
- **Frequency Penalty** - Discourages repeating the *same words* again and again. Higher = less echo-y phrasing.
- **Presence Penalty** - Pushes the model toward *new topics* instead of staying on what it already said. Higher = more topic drift.
- **Top K** - Each step, only the K most likely next tokens are allowed. Lower = safer / narrower. Higher = more variety.
- **Top P** - Nucleus sampling: keep the smallest set of tokens whose probabilities add up to P. Lower = tighter. Higher = freer.
- **Repetition Penalty** - Extra brake on looping the same phrases. `1.0` is off; higher values cut repetition harder.
- **Min P** - Drops tokens whose probability is below a floor relative to the top token. Higher = filters out weak options.
- **Top A** - Another rarity filter (dynamic absolute threshold). Usually leave at `0` unless you know you want it.

Some sliders stay disabled when the selected OpenRouter model does not advertise that parameter. In the same section: **Reasoning effort** (dropdown) controls how hard the model thinks before it answers, and **Surf the web** lets supporting models pull live web results.

(If this overwhelms you, just press "reset to defaults" button and it will go back to the original state.)

## Yogi blocks
Yogi blocks are like plugins that can be used to enhance yogi's abilities. As a proof of concept I've created one that helps yogi read chess board with a sharp accuracy - check out [Yogi-chess](https://github.com/EskraS/yogi-chess). They run as separate processes and are never imported into Yogi, so a block can use its own dependencies and license without affecting Yogi core. On each screenshot, Yogi passes the image path to enabled blocks and reads their notes from stdout. Install a zip from the Blocks tab, or drop a folder under `modules/`.

See **Writing a block** below for the contract.

## Requirements

- Python 3.10+
- Windows (hotkeys use the `keyboard` package; this is the supported desktop target)
- An [OpenRouter](https://openrouter.ai/) API key for vision models
- A TTS API key for the voice you pick (Grok / OpenRouter / Fish Audio)

## Install

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
# source venv/bin/activate

pip install -r requirements.txt
pip install --no-deps "faster-whisper>=1.2,<2"
```

`faster-whisper` is installed without its dependencies so PyAV (GPL FFmpeg) is not pulled in. Yogi passes it numpy audio and stubs the `av` import. `pip check` may warn that `av` is missing - that is expected.

## Run

```bash
python main.py
# or
python -m yogi
```

## Where your data is stored

Close Yogi before you delete any of this. A running copy can write the same values back.

Nothing below uses a hard-coded username. `%LOCALAPPDATA%` and `%USERPROFILE%` are your own profile. In File Explorer, paste the path into the address bar and it expands.

| What | Where | Clear it |
|------|--------|----------|
| Model choice, sliders, prompts, voice options, hotkeys, theme, mic threshold, follow-up time, audio devices | Windows Registry: `HKEY_CURRENT_USER\Software\Yogi\Yogi` | Delete that key. There is no settings folder. |
| API keys | Windows Credential Manager, not a file | Remove every generic credential named `Yogi` or ending in `@Yogi`. |
| Chat history (transcript JSON and screenshot JPEG) | `%LOCALAPPDATA%\Yogi\history` | Delete that folder. If `LOCALAPPDATA` is unset, the fallback is `~/Yogi/history`. |
| Local Whisper download (`small`) | `%LOCALAPPDATA%\Yogi\whisper-small` | Delete that folder. The next listen downloads it again (~500 MB). Older builds may also leave `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-small`; that folder is unused by current Yogi and safe to delete. |
| Installed blocks, including the enabled flag in each `manifest.json` and each block's Python packages in `.yogi-env/` | `modules/` next to `main.py`, or `<folder that contains Yogi.exe>\_internal\modules` in a frozen build | Delete one block folder to remove that block. A settings reset does not require this. |

API key names in Credential Manager (service `Yogi`, one entry per provider):

- `Yogi` (whichever key was saved most recently under the plain service name)
- `openrouter@Yogi`
- `openrouter_tts@Yogi`
- `xai@Yogi`
- `fish_audio@Yogi`

Open Credential Manager from Control Panel, or run `control /name Microsoft.CredentialManager`. The entries are generic Windows credentials. The comment on them is `Stored using python-keyring`. Do not delete unrelated credentials.

Speech-model cache overrides, if you set them: `HF_HUB_CACHE`, then `HUGGINGFACE_HUB_CACHE`, then `HF_HOME\hub`. When `XDG_CACHE_HOME` is set and `HF_HOME` is not, the hub folder is `%XDG_CACHE_HOME%\huggingface\hub` instead of `%USERPROFILE%\.cache\huggingface\hub`. Other folders in that cache belong to other programs.

Windows is the supported desktop. The same settings object on another system would be `~/Library/Preferences/com.Yogi.Yogi.plist` (macOS) or `~/.config/Yogi/Yogi.conf` (Linux). API keys would be in that system's keyring under the service name `Yogi`.

## Layout

| Path | Contents |
|------|----------|
| `main.py` | Thin launcher |
| `yogi/app.py` | Main window / app shell |
| `yogi/core/` | Assistant loop, history, keys, block runner |
| `yogi/audio/` | STT, TTS, devices, levels, mic threshold |
| `yogi/ui/` | Tabs, settings, orb, overlays, theme |
| `yogi/paths.py` | Project-root asset helpers |
| `orb.html`, `overlay.html`, `logo/`, `fonts/`, `sounds/` | Runtime assets (stay at repo root) |
| `modules/` | Custom community plugins location |

## Developer

Press **F2** while the Yogi window is focused to open the developer console ("Yogi terminal"). Press F2 again or Esc to hide it. **Clear** empties it.

It shows everything Yogi prints, including lines from before you opened it (the last 5000 lines): recording levels, transcripts, request timings, block logs and full tracebacks. Problems appear as lines starting with `ERROR:`.

F2 does nothing while Settings is recording a new hotkey, so F2 itself can be picked as a hotkey.

When you run from source (`python main.py`), the same output also goes to the terminal you launched it from.

## Writing a block

Blocks are separate programs. Yogi never imports them. Each enabled block runs as its own process.

`manifest.json` in the block folder:

```json
{
  "name": "Example",
  "description": "Short description (max 200 chars)",
  "entry": "example.py",
  "followup_refresh": false,
  "enabled": true
}
```

- `name`: required, 1 to 40 characters.
- `description`: required string, at most 200 characters (may be empty).
- `entry`: optional. Basename only (no folders) of a `.py` or `.exe` in that folder. Missing `entry` → listed in the UI but not run.
- `followup_refresh`: optional. When `true`, Yogi recaptures the full screen between questions and re-runs only those blocks. Empty output keeps the previous notes.
- `enabled`: optional, `true` or `false` (default `true`). Sets whether the block starts on after install. The toggle in the Blocks tab writes this field back into `manifest.json`.

Contract when Yogi runs the block:

1. Command: `python entry.py <temp.png>` (or `entry.exe <temp.png>`). The image is always a temporary PNG path as `argv[1]`.
   - Python: the installer ships a private Python 3.13 (`_internal\python`), so users don't need their own. If it's missing, Yogi falls back to `python` on PATH, and shows "Python must be installed" on startup when there is none.
   - Dependencies: put them in `requirements.txt` next to `manifest.json`. The first time the block is enabled (or on startup), Yogi creates `.yogi-env/` in the block folder and `pip install`s them. This needs internet once and can take a minute; the block is skipped until it finishes. Changing `requirements.txt` triggers a reinstall.
2. Working directory is the block folder.
3. Write the result text to **stdout** (UTF-8). Empty stdout means “nothing to add”. Non-empty results from several blocks are joined as `[Block Name]\n…` before they reach the model.
4. Write logs to **stderr** (Yogi prefixes them with the block id).
5. Exit `0` on success. Non-zero or timeout (`8s`) drops that block’s text for the scan.

Install:

- Blocks tab zip, or drop a folder under `modules/<id>/`.
- Block id = folder name / zip file stem: start with a letter, then letters, digits, underscores, or hyphens (1–32 chars, lowercase). Example: `yogi-chess.zip` → `modules/yogi-chess/`.
- A zip must include `manifest.json` and at least one `.py` (at the zip root or inside one top-level folder).
- `manifest.json` is the only config file a block needs.

Building the installer needs the private Python in `python_runtime/` (unzip the `tools` folder of the NuGet [`python`](https://www.nuget.org/packages/python) package there) before `pyinstaller --noconfirm Yogi.spec`.
