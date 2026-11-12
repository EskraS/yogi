"""User-facing errors: one line in the Yogi terminal (F2) and a red popup.

report() is safe from any thread. The UI registers the popup with
set_handler(); without one (tests, standalone runs) errors only print.
"""

import threading
import time

# The same message again within this window is printed but not popped up twice.
_REPEAT_WINDOW_S = 5.0

_lock = threading.Lock()
_handler = None
_last = {}


def set_handler(fn):
    """fn(message) is called from the reporting thread. None clears it."""
    global _handler
    with _lock:
        _handler = fn


def report(message, detail=None):
    """Print message (and detail, for the terminal only) and show it in the popup."""
    message = " ".join(str(message).split())
    print(f"ERROR: {message}", flush=True)
    if detail:
        detail = " ".join(str(detail).split())
        print(f"       {detail[:300]}{'...' if len(detail) > 300 else ''}", flush=True)
    now = time.monotonic()
    with _lock:
        handler = _handler
        if now - _last.get(message, -_REPEAT_WINDOW_S) < _REPEAT_WINDOW_S:
            return
        _last[message] = now
    if handler is not None:
        try:
            handler(message)
        except Exception as e:
            print(f"ERROR: couldn't show error popup: {e}", flush=True)


def http_reason(status, service):
    """Plain-language reason for an HTTP error status from an API."""
    if status in (401, 403):
        return f"{service} rejected the API key (HTTP {status}). Check it in Settings."
    if status == 402:
        return f"{service} account is out of credits (HTTP 402)."
    if status == 404:
        return f"{service} doesn't have the selected model or voice (HTTP 404). Pick another in Settings."
    if status == 408:
        return f"{service} timed out (HTTP 408). Try again."
    if status == 413:
        return f"The request was too large for {service} (HTTP 413). Select a smaller screen region."
    if status == 429:
        return f"{service} is rate limiting you (HTTP 429). Wait a moment and try again."
    if status == 400:
        return f"{service} rejected the request (HTTP 400). A setting may not be supported by this model."
    if status >= 500:
        return f"{service} is having problems (HTTP {status}). Try again or pick another model."
    return f"{service} returned an error (HTTP {status})."


def api_error_text(response):
    """The provider's own error message from a JSON error body, or ""."""
    try:
        data = response.json()
    except ValueError:
        return (response.text or "")[:300].strip()
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or "")[:300]
    if isinstance(err, str):
        return err[:300]
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"][:300]
    return ""
