import mss
import base64
import io
import requests
import keyboard
import time
import websocket
import sounddevice as sd
import threading
import json
from urllib.parse import urlencode
from PIL import Image

from yogi.audio import devices as audio_devices
from yogi.audio import vocal, voice_levels
from yogi.audio.stt import (
    FOLLOWUP_WINDOW_S,
    NO_SPEECH_TIMEOUT_S,
    listen_for_question,
    prewarm_stt,
    speech_in_progress,
)
from yogi.core import history_store, key_store, module_loader

test_settings = {
    "model": "google/gemini-3.6-flash",
    "max_tokens": 1024,
    "temperature": 0.7,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "top_k": 40,
    "top_p": 0.95,
    "repetition_penalty": 1.1,
    "min_p": 0.0,
    "top_a": 0.0,
}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_WARM_URL = "https://openrouter.ai/api/v1/auth/key"
AUDIO_SAMPLE_RATE = 24000

_settings_getter = None


def set_settings_getter(getter):
    """Register a callable that returns the live SettingsTab settings dict."""
    global _settings_getter
    _settings_getter = getter


def get_settings():
    """Merge vocal defaults, test_settings, live SettingsTab values and the saved OpenRouter key."""
    merged = {**vocal.DEFAULTS, **test_settings}
    if _settings_getter is not None:
        merged.update(_settings_getter() or {})
    try:
        merged["api_key"] = key_store.get_key("openrouter") or ""
    except key_store.KeyStoreError as e:
        print("OpenRouter key unavailable:", e)
        merged["api_key"] = ""
    return merged


_SYSTEM_PROMPT = (
    "You are Yogi, a personal AI assistant who looks at the user's screen and "
    "helps them. Talk casually and directly like a smart friend would. Keep it "
    "short and to the point. No bullet points, no markdown, no bold text, no "
    "numbered lists. Just plain conversational sentences. Don't over explain, "
    "don't be formal, don't say unnecessary filler like 'certainly' or 'of "
    "course'. Describe what you see on the screen and give advice naturally, "
    "like you're sitting next to the user looking at their monitor."
)

# Module blocks (Chess, …) append this when they return text for the shot.
_MODULE_PROMPT_ADDENDUM = (
    "\n\nA helper module already looked at this screenshot and produced the "
    "notes below. Use them only when they help answer the user. If you use "
    "them, say those facts out loud in your reply — text-to-speech will read "
    "whatever you write. The notes decide which facts to say; your "
    "personality, tone and reply length still come from the instructions "
    "above.\n\n"
)

# Wait this long for a scan that is still running. Follow-ups keep previous
# chess moves if a refresh finds no board or is not ready yet.
MODULE_WAIT_TIMEOUT_S = 1.5

# One scan per screenshot. Late results for an old id are ignored.
_screenshot_lock = threading.Lock()
_screenshot_id = 0
_module_context = ""
_module_ready = threading.Event()


def _llm_messages(encoded_image, question, settings=None, history=(), module_text=""):
    """history is the earlier (question, answer) turns of this session; the
    screenshot rides on the first user turn only."""
    prompt = ""
    if settings:
        prompt = (settings.get("prompt") or "").strip()
    if not prompt:
        prompt = _SYSTEM_PROMPT
    # Only Fish reads the cues; other voices would speak the brackets aloud.
    if settings and settings.get("tts_provider") == vocal.FISH and settings.get("fish_llm_tags"):
        prompt += vocal.fish_tag_prompt(settings)
    if module_text:
        prompt += _MODULE_PROMPT_ADDENDUM + module_text
    messages = [{"role": "system", "content": prompt}]
    for i, (q, answer) in enumerate([*history, (question, None)]):
        content = [{"type": "text", "text": q}]
        if i == 0:
            content.insert(0, {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"},
            })
        messages.append({"role": "user", "content": content})
        if answer is not None:
            messages.append({"role": "assistant", "content": answer})
    return messages


def _llm_request(settings, encoded_image, question, history=(), module_text=""):
    """Return (url, headers, body) for the OpenRouter chat completion call."""
    api_key = settings["api_key"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = _llm_messages(
        encoded_image, question, settings, history, module_text=module_text
    )

    body = {
        "model": settings["model"],
        "max_tokens": settings["max_tokens"],
        "temperature": settings["temperature"],
        "frequency_penalty": settings["frequency_penalty"],
        "presence_penalty": settings["presence_penalty"],
        "top_k": settings["top_k"],
        "top_p": settings["top_p"],
        "repetition_penalty": settings["repetition_penalty"],
        "min_p": settings["min_p"],
        "top_a": settings["top_a"],
        "stream": True,
        "messages": messages,
    }
    if settings.get("surf_web"):
        body["tools"] = [{"type": "openrouter:web_search"}]
    effort = (settings.get("reasoning_effort") or "off").strip().lower()
    if effort and effort != "off":
        body["reasoning"] = {"effort": effort, "exclude": True}
    return OPENROUTER_URL, headers, body


def _warm_request(settings):
    """Return (url, headers) for the OpenRouter TLS warm GET."""
    return OPENROUTER_WARM_URL, {
        "Authorization": f"Bearer {settings['api_key']}"
    }


def _iter_stream_deltas(response, t_ms):
    """Yield text deltas from an SSE chat completion stream."""
    first_token_printed = False
    stream_done_printed = False
    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data = line[len("data: "):]
        if data == "[DONE]":
            stream_done_printed = True
            print(f"\nT+{t_ms()}ms stream_done", flush=True)
            break
        chunk = json.loads(data)
        if "error" in chunk:
            print("\nLLM STREAM ERROR:", chunk["error"])
            break
        choices = chunk.get("choices")
        if not choices:
            continue
        delta = choices[0].get("delta", {}).get("content", "")
        if delta:
            if not first_token_printed:
                first_token_printed = True
                print(f"\nT+{t_ms()}ms first_token", flush=True)
            print(delta, end="", flush=True)
            yield delta

    if not stream_done_printed:
        print(f"\nT+{t_ms()}ms stream_done", flush=True)
    print()

# ── Prewarm managers ──────────────────────────────────────────────────────────
#
# Toggling Yogi on opens everything that has a setup cost, so no reply pays for
# it. Measured on this machine: HTTPS connect to OpenRouter ~520ms, TTS
# WebSocket handshake ~640ms, audio device open ~40ms.
def _tts_ws_alive(ws) -> bool:
    try:
        return ws is not None and getattr(ws, "connected", False)
    except Exception:
        return False


def _tts_close_quietly(ws):
    if ws is None:
        return
    try:
        ws.close()
    except Exception:
        pass


def _vocal_key(provider):
    try:
        return key_store.get_key(vocal.KEY_PROVIDER[provider])
    except key_store.KeyStoreError as e:
        print("tts: API key unavailable:", e, flush=True)
        return None


def _grok_ws_target(settings):
    """(params, key) for the Grok socket the current settings want, or None."""
    if settings.get("tts_provider") != vocal.GROK:
        return None
    key = _vocal_key(vocal.GROK)
    return (vocal.grok_ws_params(settings), key) if key else None


def _tts_connect(params, key):
    t0 = time.perf_counter()

    def t_ms():
        return int((time.perf_counter() - t0) * 1000)

    url = "wss://api.x.ai/v1/tts?" + urlencode(params)
    try:
        ws = websocket.create_connection(url, header=[f"Authorization: Bearer {key}"])
        # The socket's voice/format are fixed at handshake; acquire() compares these.
        ws.yogi_params = params
        print(f"tts: ws_handshake_done in {t_ms()}ms", flush=True)
        return ws
    except Exception as e:
        print(f"tts: ws_handshake_failed after {t_ms()}ms: {e}", flush=True)
        return None


class _TtsPrewarm:
    """Holds one ready-to-use TTS socket while Yogi is toggled on."""

    PING_INTERVAL_S = 20

    def __init__(self):
        self._lock = threading.Lock()
        self._ws = None
        self._in_use = False
        self._stop = None
        self._wake = threading.Event()

    def start(self, settings_getter):
        """settings_getter is re-read each tick, so voice/format changes rewarm."""
        with self._lock:
            if self._stop is not None and not self._stop.is_set():
                self._wake.set()
                return
            stop = threading.Event()
            self._stop = stop
            self._in_use = False
            stale_ws, self._ws = self._ws, None

        _tts_close_quietly(stale_ws)
        self._wake.clear()
        threading.Thread(
            target=self._keepalive_loop, args=(settings_getter, stop), daemon=True
        ).start()
        print("tts: prewarm started", flush=True)

    def stop(self):
        with self._lock:
            stop, self._stop = self._stop, None
            ws, self._ws = self._ws, None
            self._in_use = False

        if stop is not None:
            stop.set()
        self._wake.set()
        _tts_close_quietly(ws)
        if stop is not None:
            print("tts: prewarm stopped", flush=True)

    def acquire(self, params):
        """Hand the warm socket to a reply if it was opened with these params, else None."""
        with self._lock:
            ws, self._ws = self._ws, None
            if _tts_ws_alive(ws) and getattr(ws, "yogi_params", None) == params:
                self._in_use = True
                return ws

        _tts_close_quietly(ws)
        # Settings changed since the warm socket opened; reconnect for the next reply.
        self._wake.set()
        return None

    def release_and_rewarm(self):
        with self._lock:
            self._in_use = False
        self._wake.set()

    def _keepalive_loop(self, settings_getter, stop):
        while not stop.is_set():
            with self._lock:
                in_use = self._in_use
                ws = self._ws

            if in_use:
                # Never touch the socket while a reply is speaking through it.
                self._sleep(self.PING_INTERVAL_S)
                continue

            target = _grok_ws_target(settings_getter())
            if ws is not None and (target is None or ws.yogi_params != target[0]):
                self._drop(ws)
                ws = None
            if target is None:
                self._sleep(self.PING_INTERVAL_S)
                continue

            if _tts_ws_alive(ws):
                if not self._ping(ws):
                    continue
            else:
                self._discard(ws)
                self._replace_ws(_tts_connect(*target), stop)

            self._sleep(self.PING_INTERVAL_S)

        self._shutdown(stop)

    def _sleep(self, timeout):
        self._wake.wait(timeout=timeout)
        self._wake.clear()

    def _ping(self, ws):
        """Ping the idle socket; returns False when it turned out to be dead."""
        with self._lock:
            if self._in_use or self._ws is not ws:
                return True
        try:
            ws.ping()
            return True
        except Exception:
            self._discard(ws)
            return False

    def _drop(self, ws):
        """Close a live socket the settings no longer want."""
        with self._lock:
            if self._ws is ws:
                self._ws = None
        _tts_close_quietly(ws)

    def _discard(self, ws):
        """Drop a socket that is no longer usable so the loop reconnects."""
        if ws is None:
            return
        print("tts: ws_died, reconnecting", flush=True)
        with self._lock:
            if self._ws is ws:
                self._ws = None
        _tts_close_quietly(ws)

    def _replace_ws(self, new_ws, stop):
        if new_ws is None:
            return
        keep = False
        with self._lock:
            if not stop.is_set() and self._stop is stop and not self._in_use:
                self._ws = new_ws
                keep = True
        if not keep:
            _tts_close_quietly(new_ws)

    def _shutdown(self, stop):
        with self._lock:
            if self._stop is not stop:
                return
            ws, self._ws = self._ws, None
            self._in_use = False
        _tts_close_quietly(ws)


class _HttpPrewarm:
    """Keeps a pooled TLS connection to the active LLM host ready."""

    # Idle connections get dropped by the edge, so re-touch well under that.
    WARM_INTERVAL_S = 60

    def __init__(self):
        self._lock = threading.Lock()
        self._session = None
        self._stop = None
        self._wake = threading.Event()

    def session(self):
        """The shared session; created on demand so standalone runs work too."""
        with self._lock:
            if self._session is None:
                self._session = self._build_session()
            return self._session

    @staticmethod
    def _build_session():
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4, pool_maxsize=8
        )
        session.mount("https://", adapter)
        return session

    def start(self, settings_getter):
        """Start the warm loop. settings_getter is called each tick for live settings."""
        with self._lock:
            if self._stop is not None and not self._stop.is_set():
                self._wake.set()
                return
            stop = threading.Event()
            self._stop = stop
            if self._session is None:
                self._session = self._build_session()

        self._wake.clear()
        threading.Thread(
            target=self._warm_loop, args=(settings_getter, stop), daemon=True
        ).start()

    def stop(self):
        with self._lock:
            stop, self._stop = self._stop, None
            session, self._session = self._session, None

        if stop is not None:
            stop.set()
        self._wake.set()
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def _warm_loop(self, settings_getter, stop):
        first = True
        while not stop.is_set():
            with self._lock:
                session = self._session
                current = self._stop is stop
            if not current or session is None:
                break

            settings = settings_getter() if callable(settings_getter) else settings_getter
            self._warm_once(session, settings, announce=first)
            first = False

            self._wake.wait(timeout=self.WARM_INTERVAL_S)
            self._wake.clear()

    @staticmethod
    def _warm_once(session, settings, announce):
        t0 = time.perf_counter()
        url, headers = _warm_request(settings)
        try:
            session.get(url, headers=headers, timeout=15)
            if announce:
                ms = int((time.perf_counter() - t0) * 1000)
                print(f"http: connection_warm in {ms}ms", flush=True)
        except Exception as e:
            if announce:
                print(f"http: warm_failed: {e}", flush=True)


class _AudioPrewarm:
    """Opens the output device up front; replies only pay the ~0.4ms start."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stream = None
        self._in_use = False

    def start(self):
        threading.Thread(target=self._open, daemon=True).start()

    def _open(self):
        with self._lock:
            if self._stream is not None or self._in_use:
                return
        stream = self._new_stream(announce=True)
        keep = False
        with self._lock:
            if stream is not None and self._stream is None and not self._in_use:
                self._stream = stream
                keep = True
        if stream is not None and not keep:
            _audio_close_quietly(stream)

    def reopen(self):
        """Swap to a freshly opened stream, e.g. after the device changed."""
        self.stop()
        self.start()

    @staticmethod
    def _new_stream(announce=False):
        t0 = time.perf_counter()
        try:
            stream = sd.RawOutputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=audio_devices.get_output_device(),
            )
            if announce:
                ms = int((time.perf_counter() - t0) * 1000)
                print(f"audio: device_open in {ms}ms", flush=True)
            return stream
        except Exception as e:
            print(f"audio: device_open_failed: {e}", flush=True)
            return None

    def acquire(self):
        """Return (stream, is_shared). Falls back to a throwaway stream."""
        with self._lock:
            stream = self._stream
            if stream is not None and not self._in_use:
                self._in_use = True
                return stream, True

        return self._new_stream(), False

    def release(self, stream, is_shared):
        if stream is None:
            return
        if not is_shared:
            _audio_close_quietly(stream)
            return
        # Keep the device open for the next reply; stop() resets it cleanly.
        # abort() drops queued audio so the stop hotkey cuts off instantly.
        try:
            if _stop_speaking.is_set():
                stream.abort()
            else:
                stream.stop()
        except Exception:
            _audio_close_quietly(stream)
            with self._lock:
                if self._stream is stream:
                    self._stream = None
        with self._lock:
            self._in_use = False

    def stop(self):
        with self._lock:
            stream, self._stream = self._stream, None
            self._in_use = False
        _audio_close_quietly(stream)


def _audio_close_quietly(stream):
    if stream is None:
        return
    try:
        stream.stop()
    except Exception:
        pass
    try:
        stream.close()
    except Exception:
        pass


# mss holds per-thread GDI resources, so each thread keeps its own capturer
# instead of building one per screenshot.
_capturer = threading.local()


def _get_capturer():
    sct = getattr(_capturer, "sct", None)
    if sct is None:
        sct = mss.mss()
        _capturer.sct = sct
    return sct


_tts_prewarm = _TtsPrewarm()
_http_prewarm = _HttpPrewarm()
_audio_prewarm = _AudioPrewarm()

audio_devices.on_output_device_changed(lambda _device: _audio_prewarm.reopen())


def start_prewarm():
    """Open the TTS socket, HTTPS connection, audio device, and STT model up front."""
    # Both warm loops re-read live settings each tick so key and voice changes apply.
    _tts_prewarm.start(get_settings)
    _http_prewarm.start(get_settings)
    _audio_prewarm.start()
    prewarm_stt()


def stop_prewarm():
    """Release everything opened by start_prewarm."""
    _tts_prewarm.stop()
    _http_prewarm.stop()
    _audio_prewarm.stop()


def tts_acquire_ws(params):
    """Acquire the warm socket for a reply; returns ws or None."""
    return _tts_prewarm.acquire(params)


def tts_release_and_rewarm():
    """Release the socket slot and reconnect a fresh one for the next reply."""
    _tts_prewarm.release_and_rewarm()


SCREENSHOT_JPEG_QUALITY = 80
MIN_REGION_SIZE = 32
REGION_PADDING_PX = 12
REGION_PADDING_RATIO = 0.08

_region_select_handler = None


def set_region_select_handler(handler):
    global _region_select_handler
    _region_select_handler = handler


_orb_handler = None


def set_orb_handler(handler):
    """Register the orb window. It must expose show() and hide()."""
    global _orb_handler
    _orb_handler = handler


def _emit_tts_levels(pcm):
    """Feed one TTS chunk to the orb. pcm is little-endian int16 mono."""
    import numpy as np

    if len(pcm) < 2:
        return
    even = len(pcm) - (len(pcm) % 2)
    samples = np.frombuffer(pcm[:even], dtype="<i2").astype(np.float32) * (1.0 / 32768.0)
    voice_levels.emit_levels(samples, AUDIO_SAMPLE_RATE)


def grab_primary_monitor():
    sct = _get_capturer()
    monitor = sct.monitors[1]
    shot = sct.grab(monitor)
    image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return image, monitor


def crop_screenshot(image, box):
    """Crop with padding; box is (left, top, right, bottom) in image pixels."""
    width, height = image.size
    box_left, box_top, box_right, box_bottom = box
    pad_x = max(REGION_PADDING_PX, int((box_right - box_left) * REGION_PADDING_RATIO))
    pad_y = max(REGION_PADDING_PX, int((box_bottom - box_top) * REGION_PADDING_RATIO))
    left = max(0, box_left - pad_x)
    top = max(0, box_top - pad_y)
    right = min(width, box_right + pad_x)
    bottom = min(height, box_bottom + pad_y)
    if right - left < MIN_REGION_SIZE or bottom - top < MIN_REGION_SIZE:
        return image
    return image.crop((left, top, right, bottom))


def take_screenshot():
    image, _monitor = grab_primary_monitor()
    return image


def encode_screenshot(image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=SCREENSHOT_JPEG_QUALITY, subsampling=0)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def ask_yogi(encoded_image, question, settings, history=(), module_text=""):
    t0 = time.perf_counter()
    def t_ms():
        return int((time.perf_counter() - t0) * 1000)

    if not settings.get("api_key"):
        print("No OpenRouter API key saved. Add one in Settings.", flush=True)
        return

    url, headers, body = _llm_request(
        settings, encoded_image, question, history, module_text=module_text
    )

    print(f"T+{t_ms()}ms requesting llm...", flush=True)
    response = _http_prewarm.session().post(
        url,
        headers=headers, json=body, stream=True, timeout=(10, 180),
    )
    print(f"T+{t_ms()}ms http_response_ready", flush=True)
    if response.status_code != 200:
        print("LLM ERROR:", response.status_code, response.text)
        return

    yield from _iter_stream_deltas(response, t_ms)


def speak_yogi(text_chunks, settings):
    provider = settings.get("tts_provider")
    if provider not in vocal.KEY_PROVIDER:
        provider = vocal.GROK
    key = _vocal_key(provider)
    if not key:
        print(f"tts: no {vocal.PROVIDER_LABELS[provider]} API key - add it in Settings > Vocal Model",
              flush=True)
        return
    if provider == vocal.GROK:
        _speak_grok(text_chunks, settings, key)
    else:
        _speak_http(text_chunks, settings, provider, key)


def _speak_http(text_chunks, settings, provider, key):
    """OpenRouter and Fish Audio take whole text per request, so speak sentence by sentence."""
    t0 = time.perf_counter()
    if provider == vocal.OPENROUTER:
        if not settings["or_model"]:
            print("tts: pick an OpenRouter speech model in Settings > Vocal Model", flush=True)
            return
        build = lambda text: vocal.openrouter_request(settings, key, text)
        audio_format = vocal.openrouter_audio_format(settings)
        stream_response = True
    else:
        vocal.resolve_fish_voice(settings, key)
        build = lambda text: vocal.fish_request(settings, key, text)
        audio_format = vocal.fish_audio_format(settings)
        stream_response = settings["fish_streaming"]

    stream, stream_is_shared = _audio_prewarm.acquire()
    if stream is None:
        print("tts: no audio device available", flush=True)
        return
    stream.start()
    first_audio = []

    def write(pcm):
        if _stop_speaking.is_set():
            return
        if not first_audio:
            first_audio.append(True)
            print(f"tts: T+{int((time.perf_counter() - t0) * 1000)}ms first_audio", flush=True)
        stream.write(pcm)
        _emit_tts_levels(pcm)

    try:
        vocal.speak_http(vocal.iter_sentences(text_chunks), build, audio_format, write,
                         _http_prewarm.session(), stream=stream_response,
                         should_stop=_stop_speaking.is_set)
    finally:
        _audio_prewarm.release(stream, stream_is_shared)


def _speak_grok(text_chunks, settings, key):
    t0 = time.perf_counter()
    def t_ms():
        return int((time.perf_counter() - t0) * 1000)

    # Prefer the prewarmed (already-handshaked) socket when available.
    params = vocal.grok_ws_params(settings)
    acquired_from_manager = False
    ws = tts_acquire_ws(params)
    if ws is not None:
        acquired_from_manager = True
        print(f"tts: T+{t_ms()}ms using prewarmed ws", flush=True)
    else:
        print(f"tts: T+{t_ms()}ms cold connecting ws...", flush=True)
        ws = _tts_connect(params, key)
        if ws is None:
            return
    print(f"tts: T+{t_ms()}ms tts_ws_ready", flush=True)

    audio_done = threading.Event()
    stream, stream_is_shared = _audio_prewarm.acquire()
    if stream is None:
        print("tts: no audio device available", flush=True)
        _tts_close_quietly(ws)
        if acquired_from_manager:
            tts_release_and_rewarm()
        return
    stream.start()
    print(
        f"tts: T+{t_ms()}ms audio_ready"
        f"{' (prewarmed)' if stream_is_shared else ' (cold)'}",
        flush=True,
    )

    def write(pcm):
        if _stop_speaking.is_set():
            return
        stream.write(pcm)
        _emit_tts_levels(pcm)

    sink = vocal.PcmSink(write, settings["grok_codec"], settings["grok_sample_rate"])
    first_audio_delta_printed = False
    def receive_audio():
        try:
            while True:
                msg = ws.recv()
                if not msg:
                    continue
                data = json.loads(msg)
                msg_type = data.get("type")
                if msg_type == "audio.delta":
                    audio_b64 = data.get("delta")
                    if audio_b64:
                        nonlocal first_audio_delta_printed
                        if not first_audio_delta_printed:
                            first_audio_delta_printed = True
                            print(f"tts: T+{t_ms()}ms first_audio_delta", flush=True)
                        sink.feed(base64.b64decode(audio_b64))
                elif msg_type == "audio.done":
                    print(f"tts: T+{t_ms()}ms tts_audio_done", flush=True)
                    break
                elif msg_type == "error":
                    print("TTS ERROR:", data.get("message", data))
                    break
        except Exception as e:
            print("TTS receive exception:", e)
        finally:
            audio_done.set()
    threading.Thread(target=receive_audio, daemon=True).start()

    for chunk in text_chunks:
        ws.send(json.dumps({"type": "text.delta", "delta": chunk}))

    if not _stop_speaking.is_set():
        ws.send(json.dumps({"type": "text.done"}))
    deadline = time.perf_counter() + 180
    completed = False
    while not _stop_speaking.is_set() and time.perf_counter() < deadline:
        if audio_done.wait(timeout=0.05):
            completed = True
            break
    if completed:
        print(f"tts: T+{t_ms()}ms tts_wait_completed", flush=True)
    elif _stop_speaking.is_set():
        print(f"tts: T+{t_ms()}ms tts_stopped", flush=True)
        # Closing the socket ends receive_audio's blocking recv().
        _tts_close_quietly(ws)
        audio_done.wait(timeout=2)
    else:
        print(f"tts: T+{t_ms()}ms tts_wait_timeout", flush=True)
    sink.close(timeout=2 if _stop_speaking.is_set() else 180)
    _audio_prewarm.release(stream, stream_is_shared)
    _tts_close_quietly(ws)
    if acquired_from_manager:
        tts_release_and_rewarm()

DEFAULT_HOTKEY = "`"

_yogi_session_lock = threading.Lock()
_yogi_in_session = False
_stop_recording = threading.Event()
_cancel_recording = threading.Event()
# Stop hotkey: cut the reply, TTS and any recording, then end the session.
_stop_speaking = threading.Event()
DEFAULT_STOP_HOTKEY = "esc"
_activation_hotkey = DEFAULT_HOTKEY

# How long the orb stays up after the reply (or a failed listen) before hiding.
ORB_HIDE_DELAY_S = 0.8
# Set only while waiting for a follow-up after the reply finished playing.
# The hotkey takes a follow-up screenshot only in that window, and only
# before the user starts talking; anywhere else it just ends the recording.
_awaiting_followup = threading.Event()
_new_screenshot = threading.Event()

# Qt reports punctuation keys by name; the keyboard library wants the literal.
_QT_KEY_ALIASES = {
    "quoteleft": "`",
    "asciitilde": "`",
    "grave": "`",
    "escape": "esc",
}


def _normalize_hotkey(hotkey, default=DEFAULT_HOTKEY):
    hotkey = (hotkey or default).lower().replace(" ", "")
    parts = [_QT_KEY_ALIASES.get(p, p) for p in hotkey.split("+") if p]
    return "+".join(parts) or default


def _on_activation_hotkey():
    with _yogi_session_lock:
        if _yogi_in_session:
            if _awaiting_followup.is_set() and not speech_in_progress():
                _new_screenshot.set()
            _stop_recording.set()
            return
    threading.Thread(target=run_yogi, daemon=True).start()


def _cancel_recording_handler():
    if not _stop_speaking.is_set():
        print("Stop hotkey pressed - cutting Yogi off", flush=True)
    _stop_speaking.set()
    _cancel_recording.set()


def _until_stopped(chunks):
    """Stop reading the LLM stream as soon as the stop hotkey is pressed."""
    for chunk in chunks or ():
        if _stop_speaking.is_set():
            return
        yield chunk


def _register_stop_hotkey():
    """Register the configured stop key for this session. Returns the key used."""
    key = _normalize_hotkey(get_settings().get("stop_hotkey"), DEFAULT_STOP_HOTKEY)
    try:
        keyboard.add_hotkey(key, _cancel_recording_handler)
    except ValueError as e:
        print(f"Invalid stop hotkey {key!r} ({e}); using {DEFAULT_STOP_HOTKEY}", flush=True)
        key = DEFAULT_STOP_HOTKEY
        keyboard.add_hotkey(key, _cancel_recording_handler)
    return key


def _collect(chunks, out):
    """Pass chunks through while keeping a copy for the conversation history."""
    for chunk in chunks or ():
        out.append(chunk)
        yield chunk


def _begin_screenshot_scan(image, keep_previous_on_empty=False, module_ids=None):
    """Start run_enabled_modules in the background. Returns this shot's id."""
    global _screenshot_id, _module_context
    with _screenshot_lock:
        _screenshot_id += 1
        shot_id = _screenshot_id
        if not keep_previous_on_empty:
            _module_context = ""
        _module_ready.clear()
    threading.Thread(
        target=_run_modules_for_shot,
        args=(shot_id, image, keep_previous_on_empty, module_ids),
        daemon=True,
        name="yogi-modules",
    ).start()
    return shot_id


def _run_modules_for_shot(
    shot_id, image, keep_previous_on_empty=False, module_ids=None
):
    global _module_context
    try:
        if module_ids is None:
            text = module_loader.run_enabled_modules(image) or ""
        else:
            text = module_loader.run_enabled_modules(image, module_ids=module_ids) or ""
    except Exception as exc:
        print(f"modules: {exc}", flush=True)
        text = ""
    with _screenshot_lock:
        if shot_id != _screenshot_id:
            print(f"modules: ignoring stale scan for screenshot {shot_id}", flush=True)
            return
        if text or not keep_previous_on_empty:
            _module_context = text
        _module_ready.set()


def _chess_block_enabled():
    for info in module_loader.scan_modules():
        if info.get("id") == "chess":
            return bool(info.get("enabled", True)) and not info.get("error")
    return False


def _begin_followup_chess_scan():
    """Full-screen chess refresh. The grab is never sent to the LLM."""
    if not _module_ready.is_set() or not _chess_block_enabled():
        return
    try:
        image = take_screenshot()
    except Exception as exc:
        print(f"modules: follow-up capture failed: {exc}", flush=True)
        return
    _begin_screenshot_scan(
        image, keep_previous_on_empty=True, module_ids=("chess",)
    )


def _module_text_for_turn(wait_s):
    """Context for this LLM call. Does not write into conversation history."""
    _module_ready.wait(timeout=wait_s)
    with _screenshot_lock:
        return _module_context


def _clear_screenshot_scan():
    """Drop active context and ignore any scan still running."""
    global _screenshot_id, _module_context
    with _screenshot_lock:
        _screenshot_id += 1
        _module_context = ""
        _module_ready.set()


def _capture_screenshot():
    """Region select (or full screen). Returns (image, encoded jpeg b64) or None."""
    t0 = time.perf_counter()
    if _region_select_handler is not None:
        image = _region_select_handler()
        if image is None:
            print("Screenshot cancelled")
            return None
    else:
        image = take_screenshot()
    encoded = encode_screenshot(image)
    ms = int((time.perf_counter() - t0) * 1000)
    kb = len(encoded) * 3 // 4 // 1024
    print(f"Screenshot taken: {ms}ms, {kb}KB")
    return image, encoded


def run_yogi():
    global _yogi_in_session

    with _yogi_session_lock:
        if _yogi_in_session:
            _stop_recording.set()
            return
        _yogi_in_session = True

    orb = _orb_handler
    shown = False
    try:
        _new_screenshot.clear()
        shot = _capture_screenshot()
        if shot is None:
            return
        image, encoded = shot

        # First scan uses the activation screenshot. Follow-ups recapture the
        # full screen for chess only; the LLM keeps this image until the user
        # takes a follow-up screenshot with the hotkey.
        _begin_screenshot_scan(image)
        fresh_shot = True

        if orb is not None:
            orb.show()
            shown = True

        _stop_speaking.clear()
        stop_key = _register_stop_hotkey()
        try:
            history = []
            chat_id = history_store.new_chat_id()
            created = time.strftime("%Y-%m-%dT%H:%M:%S")
            shot_jpeg = base64.b64decode(encoded)
            no_speech_timeout = NO_SPEECH_TIMEOUT_S
            awaiting_followup = False
            while True:
                if _new_screenshot.is_set():
                    _new_screenshot.clear()
                    awaiting_followup = False
                    print("Follow-up screenshot requested", flush=True)
                    if shown:
                        orb.hide()
                        time.sleep(0.15)
                    shot = _capture_screenshot()
                    if shown:
                        orb.show()
                    if shot is not None:
                        image, encoded = shot
                        shot_jpeg = base64.b64decode(encoded)
                        _begin_screenshot_scan(image)
                        fresh_shot = True
                    no_speech_timeout = NO_SPEECH_TIMEOUT_S
                if _stop_speaking.is_set():
                    print("Yogi stopped.", flush=True)
                    break
                _stop_recording.clear()
                _cancel_recording.clear()
                if not fresh_shot:
                    _begin_followup_chess_scan()
                if awaiting_followup:
                    print(
                        f"Awaiting followup question ({no_speech_timeout:g}s, "
                        f"press {_activation_hotkey} for a follow-up screenshot)...",
                        flush=True,
                    )
                    _awaiting_followup.set()
                listen_t0 = time.perf_counter()
                try:
                    question, status = listen_for_question(
                        _stop_recording,
                        hotkey_label=_activation_hotkey,
                        cancel_label=stop_key,
                        cancel_event=_cancel_recording,
                        no_speech_timeout=no_speech_timeout,
                    )
                finally:
                    _awaiting_followup.clear()
                if status != "ok":
                    if awaiting_followup and status != "cancelled" and _new_screenshot.is_set():
                        continue
                    if awaiting_followup and status == "no_speech":
                        waited = time.perf_counter() - listen_t0
                        print(
                            f"No followup question detected (waited {waited:.1f}s)",
                            flush=True,
                        )
                    print("Session ended.")
                    break
                awaiting_followup = False
                wait_s = 0 if _module_ready.is_set() else MODULE_WAIT_TIMEOUT_S
                fresh_shot = False
                module_text = _module_text_for_turn(wait_s)
                if wait_s and not module_text and not _module_ready.is_set():
                    print(
                        f"modules: not ready in {MODULE_WAIT_TIMEOUT_S}s; "
                        "sending without them",
                        flush=True,
                    )
                settings = get_settings()
                reply = []
                speak_yogi(
                    _collect(
                        _until_stopped(ask_yogi(
                            encoded, question, settings, history, module_text=module_text
                        )),
                        reply,
                    ),
                    settings,
                )
                if _stop_speaking.is_set():
                    print("Yogi stopped.", flush=True)
                    break
                if not reply:
                    break
                print("Tts finished", flush=True)
                history.append((question, "".join(reply)))
                history_store.save_chat(chat_id, created, history, shot_jpeg)
                no_speech_timeout = float(settings.get("followup_window_s", FOLLOWUP_WINDOW_S))
                awaiting_followup = True
                # A hotkey press during the reply must not count as a screenshot request.
                _new_screenshot.clear()
        finally:
            try:
                keyboard.remove_hotkey(_cancel_recording_handler)
            except KeyError:
                pass
    finally:
        _clear_screenshot_scan()
        if shown:
            time.sleep(ORB_HIDE_DELAY_S)
            orb.hide()
        with _yogi_session_lock:
            _yogi_in_session = False


def listen_for_hotkey(stop_event, hotkey=DEFAULT_HOTKEY):
    global _activation_hotkey
    _activation_hotkey = _normalize_hotkey(hotkey)
    # Single-key hotkeys are suppressed so activating Yogi doesn't also type
    # the character into whatever window has focus.
    suppress = "+" not in _activation_hotkey
    try:
        keyboard.add_hotkey(
            _activation_hotkey, _on_activation_hotkey, suppress=suppress
        )
    except ValueError as e:
        print(f"Invalid hotkey {_activation_hotkey!r} ({e}); using {DEFAULT_HOTKEY}")
        _activation_hotkey = DEFAULT_HOTKEY
        keyboard.add_hotkey(_activation_hotkey, _on_activation_hotkey, suppress=True)

    print(
        f"Yogi is running. Press {_activation_hotkey} to activate, "
        f"then again when you finish speaking."
    )
    while not stop_event.is_set():
        time.sleep(0.2)
    keyboard.remove_hotkey(_on_activation_hotkey)
    _clear_screenshot_scan()
    print("Yogi has stopped listening.")


if __name__ == "__main__":
    keyboard.add_hotkey(DEFAULT_HOTKEY, _on_activation_hotkey, suppress=True)
    print(f"Yogi is running. Press {DEFAULT_HOTKEY} to activate.")
    keyboard.wait()