"""Persistent API key storage in Windows Credential Manager.

The only module that touches keyring. Keys are stored under SERVICE_NAME with
the provider id as the username. Nothing here prints, logs, or puts key text
into an exception message.
"""

from dataclasses import dataclass

import keyring

SERVICE_NAME = "Yogi"
MASK_CHAR = "\u2022"
MASK_VISIBLE_CHARS = 4

_STORAGE_ERROR = "Couldn't access Windows Credential Manager. Your API key was not changed."


@dataclass(frozen=True)
class Provider:
    id: str
    label: str


PROVIDERS = (
    Provider("openrouter", "Openrouter API Key"),
    # Separate from the vision key, for OpenRouter speech in the Vocal Model card.
    Provider("openrouter_tts", "Openrouter API Key"),
    Provider("xai", "xAI API Key"),
    Provider("fish_audio", "Fish Audio API Key"),
)
PROVIDERS_BY_ID = {p.id: p for p in PROVIDERS}

_PROVIDER_IDS = frozenset(p.id for p in PROVIDERS)


class KeyStoreError(Exception):
    """Storage failure. The message is safe to show in the UI."""


def _check_provider(provider_id):
    if provider_id not in _PROVIDER_IDS:
        raise KeyStoreError(f"Unknown API provider: {provider_id}")


def get_key(provider_id):
    """Return the saved key, or None when nothing is saved."""
    _check_provider(provider_id)
    try:
        return keyring.get_password(SERVICE_NAME, provider_id) or None
    except Exception:
        raise KeyStoreError(_STORAGE_ERROR) from None


def has_key(provider_id):
    return get_key(provider_id) is not None


def set_key(provider_id, key):
    _check_provider(provider_id)
    key = (key or "").strip()
    if not key:
        raise KeyStoreError("API key is empty.")
    try:
        keyring.set_password(SERVICE_NAME, provider_id, key)
    except Exception:
        raise KeyStoreError(_STORAGE_ERROR) from None


def delete_key(provider_id):
    """Remove the saved key. Deleting a key that isn't there is not an error."""
    _check_provider(provider_id)
    try:
        if keyring.get_password(SERVICE_NAME, provider_id) is None:
            return
        keyring.delete_password(SERVICE_NAME, provider_id)
    except Exception:
        raise KeyStoreError(_STORAGE_ERROR) from None


def mask(key):
    """"••••1234" style preview. Short keys are fully masked."""
    key = key or ""
    if len(key) <= MASK_VISIBLE_CHARS * 2:
        return MASK_CHAR * 4
    return MASK_CHAR * 4 + key[-MASK_VISIBLE_CHARS:]
