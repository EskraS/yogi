"""Which microphone and speaker Yogi uses.

Device identity is the PortAudio index, or None for the system default.
Listeners let the audio prewarm reopen its stream when the user switches
output device from the settings tab.
"""

import threading

import sounddevice as sd

# PortAudio exposes every endpoint once per host API, so the raw device list is
# several times longer than what Windows shows. DirectSound is listed first
# because its device set matches the Windows Sound panel one-for-one, it
# reports full (untruncated) names, and it resamples to whatever rate we ask
# for -- WASAPI shared mode only runs at the endpoint's native rate.
_HOST_API_PREFERENCE = (
    "Windows DirectSound",
    "MME",
    "Core Audio",
    "ALSA",
    "ASIO",
)

# Routing aliases rather than real endpoints; "System default" covers them.
_PSEUDO_DEVICE_PREFIXES = (
    "primary sound",
    "microsoft sound mapper",
    "default",
    "sysdefault",
    "pulse",
)

# Speech threshold: block RMS (0..1) the mic must reach to count as speech.
DEFAULT_SPEECH_THRESHOLD = 0.012
MIN_SPEECH_THRESHOLD = 0.001
MAX_SPEECH_THRESHOLD = 1.0

_lock = threading.Lock()
_input_device = None
_output_device = None
_output_listeners = []
_speech_threshold = DEFAULT_SPEECH_THRESHOLD


def _is_pseudo(name):
    lowered = name.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _PSEUDO_DEVICE_PREFIXES)


def _list(channel_key):
    """Real endpoints for one direction, mirroring the Windows Sound panel."""
    try:
        devices = list(enumerate(sd.query_devices()))
        hostapis = sd.query_hostapis()
    except Exception as e:
        print(f"audio: could not list devices: {e}", flush=True)
        return []

    candidates = [
        (index, device)
        for index, device in devices
        if device[channel_key] > 0 and not _is_pseudo(device["name"])
    ]

    for api_name in _HOST_API_PREFERENCE:
        matches = [
            (index, device["name"])
            for index, device in candidates
            if hostapis[device["hostapi"]]["name"] == api_name
        ]
        if matches:
            return matches

    # Unknown platform: show every endpoint once, first host API wins.
    seen = set()
    fallback = []
    for index, device in candidates:
        name = device["name"]
        if name in seen:
            continue
        seen.add(name)
        fallback.append((index, name))
    return fallback


def list_input_devices():
    return _list("max_input_channels")


def list_output_devices():
    return _list("max_output_channels")


def get_input_device():
    with _lock:
        return _input_device


def get_output_device():
    with _lock:
        return _output_device


def set_input_device(device):
    global _input_device
    with _lock:
        _input_device = device
    print(f"audio: input device -> {input_device_name()}", flush=True)


def set_output_device(device, notify=True):
    """notify=False restores a saved choice at startup without reopening streams."""
    global _output_device
    with _lock:
        _output_device = device
        listeners = list(_output_listeners) if notify else []
    print(f"audio: output device -> {output_device_name()}", flush=True)
    for listener in listeners:
        try:
            listener(device)
        except Exception as e:
            print(f"audio: output listener failed: {e}", flush=True)


def get_speech_threshold():
    with _lock:
        return _speech_threshold


def set_speech_threshold(value):
    global _speech_threshold
    value = min(MAX_SPEECH_THRESHOLD, max(MIN_SPEECH_THRESHOLD, float(value)))
    with _lock:
        _speech_threshold = value


def on_output_device_changed(listener):
    """Register a callback fired whenever the output device is switched."""
    with _lock:
        _output_listeners.append(listener)


def _name(device, kind):
    try:
        return sd.query_devices(device, kind)["name"]
    except Exception:
        return "unavailable device"


def input_device_name():
    device = get_input_device()
    return f"{_name(device, 'input')}{'' if device is not None else ' (system default)'}"


def output_device_name():
    device = get_output_device()
    return f"{_name(device, 'output')}{'' if device is not None else ' (system default)'}"
