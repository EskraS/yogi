"""Checks run before Yogi turns on: every key it will use works and every model is reachable.

check_ready() makes blocking HTTP calls. Run it off the UI thread.
"""

import requests

from yogi.audio import vocal
from yogi.core import key_store

NETWORK_ERROR = "Network error - Check your internet connection."
_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"


def _key(provider_id, label):
    """(key, None) or (None, message)."""
    try:
        key = key_store.get_key(provider_id)
    except key_store.KeyStoreError as e:
        return None, str(e)
    if not key:
        return None, f"Add your {label} in Settings."
    return key, None


def _get(url, key=None, params=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return requests.get(url, headers=headers, params=params, timeout=15)


def _openrouter_model_error(key, model, label, need_image=False):
    """None when an OpenRouter provider is serving model, else the message to show."""
    if not model:
        return f"Pick a {label} in Settings."
    try:
        r = _get(_ENDPOINTS_URL.format(model=model), key)
    except requests.RequestException:
        return NETWORK_ERROR
    if r.status_code in (400, 404):
        return f"{label.capitalize()} {model} isn't available on OpenRouter. Pick another in Settings."
    if r.status_code != 200:
        return f"OpenRouter error checking {model} (HTTP {r.status_code})"
    try:
        data = r.json().get("data") or {}
    except ValueError:
        return f"OpenRouter returned an unreadable reply for {model}"
    if need_image:
        inputs = (data.get("architecture") or {}).get("input_modalities") or []
        if "image" not in inputs:
            return f"{model} can't read images. Pick a vision model in Settings."
    for e in data.get("endpoints") or []:
        if isinstance(e, dict) and e.get("status", 0) == 0 and e.get("uptime_last_5m") != 0:
            return None
    return f"{model}: the provider is down. Try another model."


def _check_visual(settings):
    key, error = _key("openrouter", "OpenRouter API key (Visual Model)")
    if error:
        return error
    ok, error = vocal.verify_openrouter_key(key)
    if not ok:
        return "OpenRouter API key (Visual Model) doesn't work." if error == "Invalid Key" else error
    return _openrouter_model_error(key, settings.get("model"), "visual model", need_image=True)


def _check_vocal(settings):
    provider = settings.get("tts_provider")
    if provider not in vocal.KEY_PROVIDER:
        provider = vocal.GROK
    name = {vocal.GROK: "xAI", vocal.OPENROUTER: "OpenRouter", vocal.FISH: "Fish Audio"}[provider]
    label = f"{name} API key (Vocal Model)"
    key, error = _key(vocal.KEY_PROVIDER[provider], label)
    if error:
        return error

    if provider == vocal.GROK:
        _voices, error = vocal.fetch_grok_voices(key)
    elif provider == vocal.OPENROUTER:
        _ok, error = vocal.verify_openrouter_key(key)
    else:
        try:
            r = _get(vocal.FISH_MODELS_URL, key, {"self": "true", "page_size": 1, "page_number": 1})
        except requests.RequestException:
            return NETWORK_ERROR
        if r.status_code in (401, 403):
            error = "Invalid Key"
        elif r.status_code != 200:
            error = f"Fish Audio error (HTTP {r.status_code})"
    if error:
        return f"{label} doesn't work." if error == "Invalid Key" else error

    if provider == vocal.OPENROUTER:
        return _openrouter_model_error(key, settings.get("or_model"), "speech model")
    if provider == vocal.FISH and settings.get("fish_model") not in vocal.FISH_MODELS:
        return "Pick a Fish Audio model in Settings."
    return None


def check_ready(settings):
    """None when Yogi can start, else the first problem as a message for the user."""
    return _check_visual(settings) or _check_vocal(settings)
