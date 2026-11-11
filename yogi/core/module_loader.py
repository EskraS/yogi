import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from yogi.paths import ROOT

# modules/ lives at the project root, not next to this package file.
DEFAULT_MODULES_ROOT = ROOT / "modules"

# Id is the zip file stem, lowercased. First char a letter, then up to 31 more.
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Caps are a zip-bomb brake. Declared size is checked first, then bytes actually written.
MAX_INSTALL_BYTES = 500 * 1024 * 1024
MAX_INSTALL_FILES = 500
_TOO_LARGE = f"Zip is too large to install (max {MAX_INSTALL_BYTES // (1024 * 1024)} MB unzipped)."

# Mac "Compress" adds these next to the real folder. They are not the module.
_NOISE_TOP_NAMES = {"__MACOSX", ".DS_Store"}


def validate_manifest(data):
    """Return None if valid, or an error message string if not."""
    if not isinstance(data, dict):
        return "manifest.json must be a JSON object"

    if "name" not in data:
        return 'manifest.json is missing "name"'
    if "description" not in data:
        return 'manifest.json is missing "description"'

    name = data["name"]
    description = data["description"]

    if not isinstance(name, str):
        return '"name" must be a string'
    if not isinstance(description, str):
        return '"description" must be a string'

    if not (1 <= len(name) <= 40):
        return '"name" must be 1 to 40 characters'
    if len(description) > 200:
        return '"description" must be at most 200 characters'
    if "enabled" in data and not isinstance(data["enabled"], bool):
        return '"enabled" must be true or false'

    return None


def _modules_root(root):
    return Path(root) if root is not None else DEFAULT_MODULES_ROOT


def scan_modules(root=None):
    """List each folder under modules/ and read its manifest.json.

    Returns a list of {id, name, description, error, enabled}.
    Broken modules stay in the list with error set; they are not skipped.
    Folders whose name starts with "." are skipped. Install uses one as a
    staging dir (".<id>.installing") and it is not a block.
    """
    root_path = _modules_root(root)
    if not root_path.is_dir():
        return []

    results = []
    for folder in sorted(root_path.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue

        entry = {
            "id": folder.name,
            "name": "",
            "description": "",
            "error": None,
            "enabled": True,
            "followup_refresh": False,
        }
        path = folder / "manifest.json"

        if not path.is_file():
            entry["error"] = "manifest.json is missing"
            results.append(entry)
            continue

        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            entry["error"] = "manifest.json is not valid JSON"
            results.append(entry)
            continue
        except OSError as exc:
            entry["error"] = f"could not read manifest.json: {exc}"
            results.append(entry)
            continue

        if isinstance(data, dict):
            if isinstance(data.get("name"), str):
                entry["name"] = data["name"]
            if isinstance(data.get("description"), str):
                entry["description"] = data["description"]
            entry["followup_refresh"] = data.get("followup_refresh") is True
            entry["enabled"] = data.get("enabled") is not False

        entry["error"] = validate_manifest(data)
        results.append(entry)

    return results


def _shown_entry(name):
    """Short single-line form of a zip entry name for an error dialog."""
    clean = name.replace("\r", "").replace("\n", "\\n")
    if len(clean) > 80:
        return clean[:77] + "..."
    return clean


def _safe_zip_path(name):
    """Return a normalized relative zip path, or None if it is unsafe.

    Rejects absolute paths and any ".." segment. A "." segment is dropped,
    so "./manifest.json" is the same as "manifest.json".
    A trailing slash is kept so directory entries stay directories.
    """
    if not name or "\x00" in name:
        return None
    # POSIX absolute, Windows drive, UNC. Also reject a leading slash
    # before we touch os.path, so the check does not depend on the OS.
    if name.startswith("/") or name.startswith("\\"):
        return None
    if name.startswith("//") or name.startswith("\\\\"):
        return None
    if re.match(r"^[A-Za-z]:", name):
        return None

    norm = name.replace("\\", "/")
    if os.path.isabs(name) or os.path.isabs(norm):
        return None

    is_dir = norm.endswith("/")
    parts = norm.split("/")
    if is_dir:
        parts = parts[:-1]

    kept = []
    for part in parts:
        if part == "":
            return None
        if part == ".":
            continue
        if part == "..":
            return None
        # "C:" as a segment becomes an absolute path when joined on Windows.
        if ":" in part:
            return None
        kept.append(part)

    if not kept:
        return None
    rel = "/".join(kept)
    if is_dir:
        rel += "/"
    return rel


def _is_symlink(info):
    # Zip stores the Unix mode in the high 16 bits of external_attr.
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _is_noise(rel):
    top = rel.split("/", 1)[0]
    return top in _NOISE_TOP_NAMES


def _list_zip_entries(zf):
    """Return (entries, error). Each entry is (ZipInfo, safe relative path)."""
    entries = []
    seen = set()
    for info in zf.infolist():
        shown = _shown_entry(info.filename)
        rel = _safe_zip_path(info.filename)
        if rel is None:
            return None, f'Zip entry "{shown}" is not a safe path.'
        if _is_symlink(info):
            return None, f'Zip entry "{shown}" is a symlink and cannot be installed.'
        if info.flag_bits & 0x1:
            return None, "Encrypted zip files are not supported."
        if rel in seen:
            return None, f'Zip entry "{shown}" is duplicated.'
        seen.add(rel)
        entries.append((info, rel))
    return entries, None


def _content_prefix(file_rels):
    """Where manifest.json and the .py file live.

    Returns (prefix, error). prefix is "" or "folder/".
    Top level wins when manifest.json is there. Otherwise exactly one
    top-level folder, with manifest.json directly inside it.
    """
    top_files = [rel for rel in file_rels if "/" not in rel]
    top_dirs = []
    for rel in file_rels:
        if "/" not in rel:
            continue
        top = rel.split("/", 1)[0]
        if top not in top_dirs:
            top_dirs.append(top)

    if "manifest.json" in top_files:
        prefix = ""
    elif len(top_dirs) == 1 and not top_files:
        prefix = top_dirs[0] + "/"
    else:
        has_manifest = any(rel == "manifest.json" or rel.endswith("/manifest.json") for rel in file_rels)
        if not has_manifest:
            return None, "Zip is missing manifest.json"
        return None, (
            "Zip must contain manifest.json and a .py file at the top level, "
            "or inside a single folder"
        )

    if (prefix + "manifest.json") not in file_rels:
        return None, "Zip is missing manifest.json"

    has_py = any(
        rel.startswith(prefix) and rel.lower().endswith(".py")
        for rel in file_rels
    )
    if not has_py:
        return None, "Zip is missing a .py file"
    return prefix, None


def _read_manifest(zf, info):
    """Read manifest.json from the zip. Does not extract anything."""
    if info.is_dir():
        return None, "Zip is missing manifest.json"
    # Stop after 64 KiB so a lying size cannot pull a huge file into memory.
    limit = 64 * 1024
    try:
        with zf.open(info, "r") as src:
            raw = src.read(limit + 1)
    except RuntimeError:
        return None, "Encrypted zip files are not supported."
    except zipfile.BadZipFile:
        return None, "This file is not a valid zip archive."
    if len(raw) > limit:
        return None, "manifest.json is too large."
    try:
        # utf-8-sig drops a BOM if the editor saved one.
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "manifest.json is not valid JSON"
    return data, None


def _module_dir(module_id, root=None):
    """Return (folder, error). Folder is a real child of modules/, never a traversal."""
    if not isinstance(module_id, str) or not module_id:
        return None, "Block id is not a safe folder name."
    if module_id.startswith(".") or module_id in {".", ".."}:
        return None, "Block id is not a safe folder name."
    if any(ch in module_id for ch in ("/", "\\", ":", "\x00")):
        return None, "Block id is not a safe folder name."
    root_path = _modules_root(root)
    dest = root_path / module_id
    if dest.name != module_id:
        return None, "Block id is not a safe folder name."
    if not _under_root(dest, root_path):
        return None, "Block id is not a safe folder name."
    return dest, None


def uninstall_module(module_id, root=None):
    """Delete modules/<id>/ and everything in it. Returns None or an error string."""
    dest, error = _module_dir(module_id, root)
    if error:
        return error
    if not dest.exists():
        return f'No block named "{module_id}" is installed.'
    if dest.is_symlink() or not dest.is_dir():
        return f'"{module_id}" is not a block folder.'
    try:
        shutil.rmtree(dest)
    except OSError as exc:
        return f"Could not delete block: {exc}"
    return None


def set_module_enabled(module_id, enabled, root=None):
    """Set "enabled" in the block's manifest.json. Returns None or an error string."""
    dest, error = _module_dir(module_id, root)
    if error:
        return error
    if dest.is_symlink() or not dest.is_dir():
        return f'No block named "{module_id}" is installed.'
    path = dest / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "Could not update block: manifest.json is missing or not valid JSON"
    if not isinstance(data, dict):
        return "Could not update block: manifest.json must be a JSON object"
    data["enabled"] = bool(enabled)
    try:
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        return f"Could not update block: {exc}"
    return None


def _under_root(path, root):
    """True when path resolves to a child of root, and is not root itself."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    return resolved != resolved_root and resolved.is_relative_to(resolved_root)


def _discard_staging(staging, root):
    """Delete only our own staging dir. Never a module folder, never modules/ itself."""
    if not staging.exists():
        return None
    name = staging.name
    if not (name.startswith(".") and name.endswith(".installing") and _under_root(staging, root)):
        return "Could not clean up a previous install attempt."
    shutil.rmtree(staging)
    return None


def _extract_zip(zf, entries, prefix, staging):
    """Copy zip bytes into staging. Never calls ZipFile.extract.

    Returned paths are checked again after resolve(), so a tricky name
    cannot leave the staging folder. Python files are copied as bytes.
    Nothing in the zip is imported or run.
    """
    root = staging.resolve()
    remaining = MAX_INSTALL_BYTES
    for info, rel in entries:
        if info.is_dir() or _is_noise(rel):
            continue
        if prefix and not rel.startswith(prefix):
            continue
        inner = rel[len(prefix):]
        if not inner or inner.endswith("/"):
            continue
        target = (root / inner).resolve()
        if not _under_root(target, root):
            return f'Zip entry "{_shown_entry(info.filename)}" is not a safe path.'
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as out:
            while True:
                chunk = src.read(64 * 1024)
                if not chunk:
                    break
                remaining -= len(chunk)
                if remaining < 0:
                    return _TOO_LARGE
                out.write(chunk)
    return None


def install_module(zip_path, root=None):
    """Install one block zip into modules/<id>/.

    Returns None on success, or an error message string. Writes nothing
    until every check has passed. Never overwrites an existing folder.
    """
    root_path = _modules_root(root)
    zip_path = Path(zip_path)

    # 1. Extension is not proof. is_zipfile reads the zip magic bytes.
    if not zipfile.is_zipfile(zip_path):
        return "This file is not a valid zip archive."

    try:
        with zipfile.ZipFile(zip_path) as zf:
            # 2. Reject unsafe names before any file is written.
            entries, error = _list_zip_entries(zf)
            if error:
                return error

            file_entries = [(info, rel) for info, rel in entries if not info.is_dir()]
            if len(file_entries) > MAX_INSTALL_FILES:
                return "Zip contains too many files."
            file_rels = [rel for info, rel in file_entries if not _is_noise(rel)]
            declared = sum(info.file_size for info, rel in entries if not info.is_dir())
            if declared > MAX_INSTALL_BYTES:
                return _TOO_LARGE

            # 3. manifest.json and a .py, at the top or inside one folder.
            prefix, error = _content_prefix(file_rels)
            if error:
                return error

            # 4. Validate the manifest from the zip. Still nothing extracted.
            manifest_rel = prefix + "manifest.json"
            manifest_info = next(info for info, rel in entries if rel == manifest_rel)
            data, error = _read_manifest(zf, manifest_info)
            if error:
                return error
            error = validate_manifest(data)
            if error:
                return error

            # 5. Id comes from the zip file name, not from manifest "name".
            module_id = zip_path.stem.lower()
            if MODULE_ID_RE.fullmatch(module_id) is None:
                return (
                    f'Zip file name "{zip_path.stem}" is not a valid block id. '
                    "Use 1 to 32 characters: start with a letter, then letters, digits, underscores, or hyphens."
                )

            dest = root_path / module_id
            if dest.exists():
                return f'A block named "{module_id}" is already installed.'
            if not _under_root(dest, root_path):
                return "Block id is not a safe folder name."

            root_path.mkdir(parents=True, exist_ok=True)
            staging = root_path / f".{module_id}.installing"
            error = _discard_staging(staging, root_path)
            if error:
                return error
            staging.mkdir()
            try:
                error = _extract_zip(zf, entries, prefix, staging)
                if error:
                    _discard_staging(staging, root_path)
                    return error
                if dest.exists():
                    _discard_staging(staging, root_path)
                    return f'A block named "{module_id}" is already installed.'
                staging.rename(dest)
            except OSError as exc:
                _discard_staging(staging, root_path)
                return f"Could not install block: {exc}"
    except (zipfile.BadZipFile, ValueError):
        return "This file is not a valid zip archive."
    except OSError as exc:
        return f"Could not read zip file: {exc}"

    return None


# Per-block cap so a stuck helper cannot block the LLM forever.
MODULE_RUN_TIMEOUT_S = 8


def _read_entry_name(folder):
    """Basename of the entry file from manifest.json, or None."""
    path = folder / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get("entry")
    if not isinstance(entry, str) or not entry:
        return None
    # Only a file in this folder. No path segments.
    name = Path(entry).name
    if name != entry or name in {".", ".."} or "\\" in entry or "/" in entry:
        return None
    return name


def _block_command(entry_path):
    """Command list for one block entry. .py needs a Python interpreter."""
    if entry_path.suffix.lower() == ".exe":
        return [str(entry_path)]
    return [sys.executable, str(entry_path)]


def _run_block_process(folder, entry_name, image, module_id):
    """Run the block as its own process. Never import plugin code into Yogi.

    shortcut: one process per scan costs ~1-2s cold start, upgrade to a
    long-lived worker if latency hurts.
    """
    entry_path = (folder / entry_name).resolve()
    if not entry_path.is_file() or not _under_root(entry_path, folder):
        print(f"module {module_id}: entry file missing", flush=True)
        return ""

    png_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            png_path = tmp.name
        image.save(png_path, format="PNG")

        cmd = _block_command(entry_path) + [png_path]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        kwargs = {
            "cwd": str(folder.resolve()),
            "capture_output": True,
            "timeout": MODULE_RUN_TIMEOUT_S,
            "env": env,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        completed = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        print(
            f"module {module_id}: timed out after {MODULE_RUN_TIMEOUT_S}s",
            flush=True,
        )
        return ""
    except Exception as exc:
        print(f"module {module_id}: {exc}", flush=True)
        return ""
    finally:
        if png_path is not None:
            try:
                os.unlink(png_path)
            except OSError:
                pass

    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    for line in stderr.splitlines():
        if line.strip():
            print(f"module {module_id}: {line}", flush=True)

    if completed.returncode != 0:
        print(
            f"module {module_id}: exited with code {completed.returncode}",
            flush=True,
        )
        return ""

    text = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    return text


def followup_refresh_ids(root=None):
    """Ids of enabled blocks that opt into follow-up screenshot refreshes."""
    ids = []
    for info in scan_modules(root):
        if info.get("error") or not info.get("enabled", True):
            continue
        if info.get("followup_refresh"):
            ids.append(info["id"])
    return tuple(ids)


def run_enabled_modules(image, root=None, module_ids=None):
    """Run every enabled block as a subprocess. Returns joined text, or \"\".

    Each block receives a temporary PNG path as argv[1] and writes result text
    to stdout. Logs go to stderr. Display-only modules (no entry) are skipped.
    Errors and timeouts print to the terminal and add nothing. module_ids, if
    given, limits the run to those folder ids (e.g. follow-up refresh).
    """
    allowed = None if module_ids is None else set(module_ids)
    parts = []
    for info in scan_modules(root):
        if allowed is not None and info["id"] not in allowed:
            continue
        if info.get("error") or not info.get("enabled", True):
            continue
        folder = _modules_root(root) / info["id"]
        entry_name = _read_entry_name(folder)
        if not entry_name:
            continue
        label = info.get("name") or info["id"]
        text = _run_block_process(folder, entry_name, image, info["id"])
        if text:
            parts.append(f"[{label}]\n{text}")
    return "\n\n".join(parts)
