"""Vocal model providers: Grok (xAI WebSocket), OpenRouter and Fish Audio (HTTP).

Shared by the settings card (option lists, model and voice discovery) and
yogi.speak_yogi (request building, audio decoding). Whatever format a provider
returns, it reaches the output device as 24 kHz int16 mono.
"""

import io
import queue
import re
import threading

import requests

PLAYBACK_RATE = 24000

GROK, OPENROUTER, FISH = "grok", "openrouter", "fish"
PROVIDER_LABELS = {
    GROK: "Grok TTS (xAI direct API)",
    OPENROUTER: "OpenRouter — TTS models",
    FISH: "Fish Audio",
}
# key_store provider id holding each vocal provider's API key.
KEY_PROVIDER = {GROK: "xai", OPENROUTER: "openrouter_tts", FISH: "fish_audio"}

DEFAULTS = {
    "tts_provider": GROK,
    "grok_voice": "wgarphwblupt",
    "grok_language": "en",
    "grok_speed": 1.0,
    "grok_codec": "pcm",
    "grok_sample_rate": 24000,
    "grok_bit_rate": 128000,
    "grok_latency": 1,
    "grok_text_normalization": False,
    "grok_timestamps": False,
    "or_model": "",
    "or_voice": "",
    "or_format": "pcm",
    "or_speed": 1.0,
    "or_data_policy": "default",
    "or_style": "",
    "or_style_degree": 1.0,
    "fish_model": "s2.1-pro",
    "fish_voice": "",
    "fish_format": "pcm",
    "fish_streaming": True,
    "fish_tags": "",
    "fish_speed": 1.0,
    "fish_temperature": 0.7,
    "fish_top_p": 0.7,
    "fish_llm_tags": False,
    # Empty uses default_fish_tag_prompt for the current model.
    "fish_cue_prompt": "",
}

GROK_LANGUAGES = [
    ("auto", "Auto-detect"), ("en", "English"), ("ar-EG", "Arabic (Egypt)"),
    ("ar-SA", "Arabic (Saudi Arabia)"), ("ar-AE", "Arabic (UAE)"), ("bn", "Bengali"),
    ("zh", "Chinese (Simplified)"), ("fr", "French"), ("de", "German"), ("hi", "Hindi"),
    ("id", "Indonesian"), ("it", "Italian"), ("ja", "Japanese"), ("ko", "Korean"),
    ("pt-BR", "Portuguese (Brazil)"), ("pt-PT", "Portuguese (Portugal)"), ("ru", "Russian"),
    ("es-MX", "Spanish (Mexico)"), ("es-ES", "Spanish (Spain)"), ("tr", "Turkish"),
    ("vi", "Vietnamese"),
]
GROK_CODECS = ["pcm", "mp3", "wav", "mulaw", "alaw"]
GROK_SAMPLE_RATES = [8000, 16000, 22050, 24000, 44100, 48000]
GROK_BIT_RATES = [32000, 64000, 96000, 128000, 192000]
GROK_LATENCY = [(0, "0 — best quality"), (1, "1 — faster first audio"), (2, "2 — fastest first audio")]
OR_FORMATS = ["pcm", "mp3"]
OR_DATA_POLICIES = [
    ("default", "Default routing"),
    ("zdr", "Zero data retention only"),
    ("deny", "Deny data collection"),
]
# Azure (MAI-Voice) express-as styles. Each voice supports a subset; Azure
# speaks neutrally when a voice lacks the chosen style.
OR_STYLES = [
    # MAI-Voice-2 voices
    "angry", "confused", "determined", "disgusted", "embarrassed", "excited", "fearful",
    "happy", "hopeful", "jealous", "joyful", "regretful", "relieved", "sad", "shouting",
    "softvoice", "surprised", "whispering",
    # MAI-Voice-2.1 voices
    "agent", "audiobook", "customer_call_center", "educational", "narrator", "neutral",
]
FISH_MODELS = ["s2.1-pro", "s2.1-pro-free", "s2-pro", "s1", "drama-3"]
FISH_FORMATS = ["pcm", "mp3", "wav", "opus"]

XAI_VOICES_URL = "https://api.x.ai/v1/tts/voices"
XAI_CUSTOM_VOICES_URL = "https://api.x.ai/v1/custom-voices"
INVALID_VOICE_ID = "Invalid voice Id"
OPENROUTER_AUTH_URL = "https://openrouter.ai/api/v1/auth/key"
OPENROUTER_SPEECH_URL = "https://openrouter.ai/api/v1/audio/speech"
OPENROUTER_SPEECH_MODELS_URL = "https://openrouter.ai/api/v1/models?output_modalities=speech"
FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_MODELS_URL = "https://api.fish.audio/model"


# ── Grok ─────────────────────────────────────────────────────────────────────

def grok_ws_params(s):
    """Query parameters for wss://api.x.ai/v1/tts. Also the prewarmed socket's identity."""
    params = {
        "voice": s["grok_voice"],
        "language": s["grok_language"],
        "codec": s["grok_codec"],
        "sample_rate": s["grok_sample_rate"],
        "speed": s["grok_speed"],
        "optimize_streaming_latency": s["grok_latency"],
        "text_normalization": "true" if s["grok_text_normalization"] else "false",
        "with_timestamps": "true" if s["grok_timestamps"] else "false",
    }
    if s["grok_codec"] == "mp3":
        params["bit_rate"] = s["grok_bit_rate"]
    return params


def fetch_grok_voices(key):
    """Verify an xAI key and list built-in voice ids. Returns (ids, None) or (None, error)."""
    try:
        r = requests.get(XAI_VOICES_URL, headers={"Authorization": f"Bearer {key}"}, timeout=15)
    except requests.RequestException:
        return None, "Network error - Check your internet connection."
    if r.status_code in (400, 401, 403):
        return None, "Invalid Key"
    if r.status_code != 200:
        return None, f"An unknown error has happened (HTTP {r.status_code})"
    try:
        voices = r.json().get("voices", [])
    except ValueError:
        return None, "An unknown error has happened (unreadable voice list)"
    return [v["voice_id"] for v in voices if isinstance(v, dict) and v.get("voice_id")], None


def lookup_grok_voice(key, voice_id):
    """Display name of a built-in or custom xAI voice. Returns (name, None) or (None, error)."""
    quoted = requests.utils.quote(voice_id, safe="")
    for url in (f"{XAI_VOICES_URL}/{quoted}", f"{XAI_CUSTOM_VOICES_URL}/{quoted}"):
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=15)
        except requests.RequestException:
            return None, "Network error - Check your internet connection."
        if r.status_code in (400, 404):
            continue
        if r.status_code in (401, 403):
            return None, "Invalid Key"
        if r.status_code != 200:
            return None, f"An unknown error has happened (HTTP {r.status_code})"
        try:
            name = r.json().get("name")
        except ValueError:
            name = None
        return (name if isinstance(name, str) and name.strip() else voice_id), None
    return None, INVALID_VOICE_ID


# ── OpenRouter ───────────────────────────────────────────────────────────────

def verify_openrouter_key(key):
    """Check a key against OpenRouter's authenticated key endpoint. Returns (True, None) or (None, error)."""
    try:
        r = requests.get(
            OPENROUTER_AUTH_URL, headers={"Authorization": f"Bearer {key}"}, timeout=15
        )
    except requests.RequestException:
        return None, "Network error - Check your internet connection."
    if r.status_code in (400, 401, 403):
        return None, "Invalid Key"
    if r.status_code != 200:
        return None, f"An unknown error has happened (HTTP {r.status_code})"
    return True, None


def openrouter_style_supported(model):
    """Whether an Azure endpoint serves model, so Speaking style applies. (bool, None) or (None, error)."""
    try:
        r = requests.get(f"https://openrouter.ai/api/v1/models/{model}/endpoints", timeout=15)
    except requests.RequestException:
        return None, "Network error - Check your internet connection."
    if r.status_code != 200:
        return None, f"OpenRouter error (HTTP {r.status_code})"
    try:
        endpoints = r.json().get("data", {}).get("endpoints") or []
    except (ValueError, AttributeError):
        return None, "OpenRouter returned an unreadable endpoint list"
    return any(
        isinstance(e, dict) and str(e.get("tag", "")).split("/")[0] == "azure" for e in endpoints
    ), None


def fetch_openrouter_speech_models():
    """{model id: [voice ids]} from the public models API. Returns (models, None) or (None, error).

    Voices differ per model; an empty list means the model takes any voice id.
    """
    try:
        r = requests.get(OPENROUTER_SPEECH_MODELS_URL, timeout=15)
    except requests.RequestException:
        return None, "Network error - Check your internet connection."
    if r.status_code != 200:
        return None, f"OpenRouter error (HTTP {r.status_code})"
    try:
        data = r.json().get("data", [])
    except ValueError:
        return None, "OpenRouter returned an unreadable model list"
    models = {}
    for m in data:
        if isinstance(m, dict) and m.get("id"):
            models[m["id"]] = [v for v in (m.get("supported_voices") or []) if isinstance(v, str)]
    return dict(sorted(models.items())), None


def openrouter_request(s, key, text):
    """(url, headers, body) for one OpenRouter speech request."""
    body = {"model": s["or_model"], "input": text, "response_format": s["or_format"]}
    if s["or_voice"]:
        body["voice"] = s["or_voice"]
    # Models without speed control reject any non-default value with a 400.
    if abs(s["or_speed"] - 1.0) > 1e-3:
        body["speed"] = s["or_speed"]
    provider = {}
    if s["or_data_policy"] == "zdr":
        provider["zdr"] = True
    elif s["or_data_policy"] == "deny":
        provider["data_collection"] = "deny"
    # OpenRouter forwards only the matched provider's options, so non-Azure models never see these.
    if s["or_style"]:
        provider["options"] = {"azure": {
            "style": s["or_style"], "styledegree": round(s["or_style_degree"], 2),
        }}
    if provider:
        body["provider"] = provider
    return OPENROUTER_SPEECH_URL, {"Authorization": f"Bearer {key}"}, body


def openrouter_audio_format(s):
    """(format, sample rate) of OpenRouter's response. Its pcm is 24 kHz mono."""
    return s["or_format"], PLAYBACK_RATE


# ── Fish Audio ───────────────────────────────────────────────────────────────

def _fish_get(key, url, params=None):
    """GET a Fish Audio JSON endpoint. Returns (data, None, status) or (None, error, status)."""
    try:
        r = requests.get(url, params=params, headers={"Authorization": f"Bearer {key}"}, timeout=15)
    except requests.RequestException:
        return None, "Network error - Check your internet connection.", None
    if r.status_code in (401, 403):
        return None, "Invalid Key", r.status_code
    if r.status_code != 200:
        return None, f"An unknown error has happened (HTTP {r.status_code})", r.status_code
    try:
        return r.json(), None, 200
    except ValueError:
        return None, "An unknown error has happened (unreadable reply)", 200


def fetch_fish_voices(key):
    """Verify a Fish Audio key and list the account's own voices.

    Returns ([(voice id, title)], None) or (None, error).
    """
    voices, page = [], 1
    while True:
        data, error, _status = _fish_get(
            key, FISH_MODELS_URL, {"self": "true", "page_size": 100, "page_number": page}
        )
        if data is None:
            return None, error
        items = data.get("items") or []
        voices += [
            (v["_id"], v.get("title") or v["_id"])
            for v in items if isinstance(v, dict) and v.get("_id")
        ]
        if not data.get("has_more") or not items:
            return voices, None
        page += 1


def lookup_fish_voice(key, voice_id):
    """Title of any Fish Audio voice (own or Voice Library). Returns (name, None) or (None, error)."""
    data, error, status = _fish_get(
        key, f"{FISH_MODELS_URL}/{requests.utils.quote(voice_id, safe='')}"
    )
    if status in (400, 404, 422):
        return None, INVALID_VOICE_ID
    if data is None:
        return None, error
    title = data.get("title") if isinstance(data, dict) else None
    return (title if isinstance(title, str) and title.strip() else voice_id), None


def fish_direction(s):
    """Voice direction as a cue Fish reads: [..] on S2 and Drama 3, (..) on the legacy S1."""
    d = s["fish_tags"].strip()
    if not d or d[0] in "[(":
        return d
    return f"({d})" if s["fish_model"] == "s1" else f"[{d}]"


def fish_tag_prompt(s):
    """System-prompt addition that lets the LLM write delivery cues into its reply."""
    custom = (s.get("fish_cue_prompt") or "").strip()
    return " " + (custom or default_fish_tag_prompt(s))


def default_fish_tag_prompt(s):
    open_, close = ("(", ")") if s["fish_model"] == "s1" else ("[", "]")
    return (
        "Your reply is read aloud by a voice that follows delivery cues written in "
        f"{open_}{close}. Put a short cue at the start of a sentence when it helps, "
        f"like {open_}warm{close}, {open_}reassuring{close} or {open_}soft tone{close}; "
        f"{open_}emphasis{close} right before a word to stress it; sounds like "
        f"{open_}chuckling{close} or {open_}sighing{close}; {open_}break{close} for a pause. "
        "Use them sparingly, at most one or two per sentence."
    )


# Fish rejects any reference_id outside this set. A voice title is not an id.
_FISH_VOICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_fish_title_ids = {}


def fish_voice_id(text):
    text = (text or "").strip()
    return text if _FISH_VOICE_ID.fullmatch(text) else ""


def resolve_fish_voice(s, key):
    """Turn a typed voice title into its model id. An id is left as-is.

    A title that does not resolve is cleared, so the request is not rejected
    and Fish speaks in its default voice.
    """
    voice = (s.get("fish_voice") or "").strip()
    if not voice or fish_voice_id(voice):
        s["fish_voice"] = voice
        return
    cached = _fish_title_ids.get(voice.casefold())
    if cached is not None:
        s["fish_voice"] = cached
        return
    data, error, _status = _fish_get(
        key, FISH_MODELS_URL, {"title": voice, "page_size": 20, "page_number": 1}
    )
    items = (data or {}).get("items") if isinstance(data, dict) else None
    wanted = voice.casefold()
    exact = [
        v for v in (items or [])
        if isinstance(v, dict)
        and str(v.get("title") or "").strip().casefold() == wanted
        and fish_voice_id(v.get("_id"))
    ]
    found = exact[0]["_id"] if len(exact) == 1 else ""
    if error and not items:
        print(f"tts: couldn't look up Fish voice {voice!r} ({error}). Using the default voice.", flush=True)
        s["fish_voice"] = ""
        return
    _fish_title_ids[wanted] = found
    if found:
        print(f"tts: Fish voice {voice!r} -> {found}", flush=True)
    elif exact:
        print(
            f"tts: {voice!r} matches {len(exact)} Fish voices. Paste one voice id. "
            "Using the default voice.",
            flush=True,
        )
    else:
        print(
            f"tts: {voice!r} is not a Fish voice id. Paste the id from the voice library. "
            "Using the default voice.",
            flush=True,
        )
    s["fish_voice"] = found


def fish_request(s, key, text):
    """(url, headers, body) for one Fish Audio /v1/tts request."""
    direction = fish_direction(s)
    body = {
        "text": f"{direction} {text}" if direction else text,
        "format": s["fish_format"],
        "temperature": round(s["fish_temperature"], 2),
        "top_p": round(s["fish_top_p"], 2),
    }
    voice = fish_voice_id(s.get("fish_voice"))
    if voice:
        body["reference_id"] = voice
    if abs(s["fish_speed"] - 1.0) > 1e-3:
        body["prosody"] = {"speed": round(s["fish_speed"], 2)}
    if s["fish_format"] in ("pcm", "wav"):
        body["sample_rate"] = PLAYBACK_RATE
    headers = {"Authorization": f"Bearer {key}", "model": s["fish_model"]}
    return FISH_TTS_URL, headers, body


def fish_audio_format(s):
    return s["fish_format"], PLAYBACK_RATE


# ── Text → requests ──────────────────────────────────────────────────────────

_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*\s+")


def iter_sentences(chunks, min_chars=80):
    """Regroup streamed text into speakable pieces for one-shot HTTP providers.

    The first piece is the first full sentence, so audio starts early; later
    pieces gather sentences up to min_chars to keep the request count down.
    """
    buf, first = "", True
    for chunk in chunks:
        buf += chunk
        ends = [m.end() for m in _BOUNDARY.finditer(buf)]
        if not ends:
            continue
        cut = ends[0] if first else ends[-1]
        if not first and cut < min_chars:
            continue
        head, buf = buf[:cut].strip(), buf[cut:]
        if head:
            yield head
            first = False
    if buf.strip():
        yield buf.strip()


def speak_http(pieces, build_request, audio_format, write, session, stream=True, lookahead=2,
               should_stop=lambda: False):
    """One request per text piece, played in order.

    Up to `lookahead` pieces download while an earlier one plays, so there is
    no handshake gap between sentences. Returns once everything has played,
    or soon after should_stop() turns true.
    """
    fmt, rate = audio_format
    slots = threading.Semaphore(lookahead)
    order = queue.Queue()

    def fetch(text, out):
        try:
            url, headers, body = build_request(text)
            with session.post(url, headers=headers, json=body, stream=stream,
                              timeout=(10, 120)) as r:
                if r.status_code != 200:
                    print(f"tts: HTTP {r.status_code}: {r.text[:300]}", flush=True)
                    return
                if stream:
                    for data in r.iter_content(4096):
                        if should_stop():
                            break
                        out.put(data)
                else:
                    out.put(r.content)
        except requests.RequestException as e:
            print(f"tts: request failed: {e}", flush=True)
        finally:
            out.put(None)

    def produce():
        try:
            for text in pieces:
                slots.acquire()
                out = queue.Queue()
                order.put(out)
                threading.Thread(target=fetch, args=(text, out), daemon=True).start()
        finally:
            order.put(None)

    threading.Thread(target=produce, daemon=True).start()
    while not should_stop() and (out := order.get()) is not None:
        sink = PcmSink(write, fmt, rate)
        while not should_stop() and (data := out.get()) is not None:
            sink.feed(data)
        sink.close()
        slots.release()
    if should_stop():
        # Unblock the producer so its thread can finish.
        for _ in range(lookahead):
            slots.release()


# ── Audio decoding ───────────────────────────────────────────────────────────

# PyAV demuxer per provider format; opus arrives in a container, so it is probed.
_AV_FORMATS = {"pcm": "s16le", "mp3": "mp3", "wav": "wav", "mulaw": "mulaw",
               "alaw": "alaw", "opus": None}
_RAW_FORMATS = {"pcm", "mulaw", "alaw"}


class _QueueReader(io.RawIOBase):
    """Blocking file object over a queue of byte chunks; None ends the stream."""

    def __init__(self, chunks):
        self._chunks = chunks
        self._buf = b""
        self._eof = False

    def readable(self):
        return True

    def readinto(self, b):
        while not self._buf and not self._eof:
            chunk = self._chunks.get()
            if chunk is None:
                self._eof = True
            else:
                self._buf = chunk
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n


class PcmSink:
    """Takes provider audio bytes in any supported format and calls write()
    with 24 kHz int16 mono PCM. 24 kHz pcm passes straight through."""

    def __init__(self, write, fmt="pcm", rate=PLAYBACK_RATE):
        self._write = write
        self._direct = fmt == "pcm" and rate == PLAYBACK_RATE
        self._carry = b""
        if not self._direct:
            self._chunks = queue.Queue()
            self._thread = threading.Thread(target=self._decode, args=(fmt, rate), daemon=True)
            self._thread.start()

    def feed(self, data):
        if not data:
            return
        if not self._direct:
            self._chunks.put(data)
            return
        # HTTP chunks can split a sample; hold the odd byte for the next chunk.
        data = self._carry + data
        cut = len(data) - len(data) % 2
        self._carry = data[cut:]
        if cut:
            self._write(data[:cut])

    def close(self, timeout=180):
        if not self._direct:
            self._chunks.put(None)
            self._thread.join(timeout)

    def _decode(self, fmt, rate):
        import av

        options = {"probesize": "32768", "analyzeduration": "0"}
        if fmt in _RAW_FORMATS:
            options.update(sample_rate=str(rate), ch_layout="mono")
        reader = _QueueReader(self._chunks)
        try:
            with av.open(reader, mode="r", format=_AV_FORMATS.get(fmt), options=options) as container:
                resampler = av.AudioResampler(format="s16", layout="mono", rate=PLAYBACK_RATE)
                for frame in container.decode(audio=0):
                    for out in resampler.resample(frame):
                        self._write(out.to_ndarray().tobytes())
                for out in resampler.resample(None):
                    self._write(out.to_ndarray().tobytes())
        except Exception as e:
            print(f"tts: could not decode {fmt} audio: {e}", flush=True)
        finally:
            # Drain so a failed decode never leaves the feeder blocked on a full stream.
            while reader.read(65536):
                pass
