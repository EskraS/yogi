"""Saved Yogi conversations: one JSON file and one screenshot JPEG per chat.

A chat is one hotkey session: the screenshot plus every question and reply
asked about it. Files live in HISTORY_DIR, named by chat id.
"""

import json
import os
import threading
import uuid
from datetime import datetime

HISTORY_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Yogi", "history"
)

_lock = threading.Lock()
_listener = None


def set_listener(fn):
    """Register the single consumer called with each chat after it is saved. None clears it."""
    global _listener
    with _lock:
        _listener = fn


def new_chat_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def screenshot_path(chat_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{chat_id}.jpg")


def _chat_path(chat_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{chat_id}.json")


def save_chat(chat_id: str, created: str, turns, screenshot_jpeg: bytes | None = None):
    """Write the chat; turns are (question, answer) pairs. Returns the chat dict, or None on failure."""
    now = datetime.now().isoformat(timespec="seconds")
    messages = []
    for question, answer in turns:
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": answer})
    chat = {
        "id": chat_id,
        "title": " ".join(turns[0][0].split()) if turns else "",
        "created": created,
        "updated": now,
        "messages": messages,
    }
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        shot = screenshot_path(chat_id)
        if screenshot_jpeg and not os.path.exists(shot):
            with open(shot, "wb") as f:
                f.write(screenshot_jpeg)
        tmp = _chat_path(chat_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(chat, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _chat_path(chat_id))
    except OSError as e:
        print(f"history: couldn't save chat {chat_id}: {e}", flush=True)
        return None
    chat = _with_screenshot(chat)
    with _lock:
        listener = _listener
    if listener is not None:
        listener(chat)
    return chat


def _with_screenshot(chat: dict) -> dict:
    shot = screenshot_path(chat["id"])
    return {**chat, "screenshot": shot if os.path.isfile(shot) else None}


def load_chats() -> list:
    """Every readable saved chat, most recently updated first."""
    try:
        names = os.listdir(HISTORY_DIR)
    except OSError:
        return []
    chats = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(HISTORY_DIR, name), encoding="utf-8") as f:
                chat = json.load(f)
        except (OSError, ValueError):
            print(f"history: skipping unreadable {name}", flush=True)
            continue
        if not (
            isinstance(chat, dict)
            and chat.get("id") == name[:-len(".json")]
            and isinstance(chat.get("messages"), list)
        ):
            continue
        chats.append(_with_screenshot(chat))
    chats.sort(key=lambda c: str(c.get("updated") or c.get("created") or ""), reverse=True)
    return chats


def delete_chat(chat_id: str) -> bool:
    """Remove the chat and its screenshot. Returns False if a file couldn't be removed."""
    ok = True
    for path in (_chat_path(chat_id), screenshot_path(chat_id)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"history: couldn't delete {path}: {e}", flush=True)
            ok = False
    return ok
