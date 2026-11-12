"""Local speech-to-text via faster-whisper.

Recording ends on whichever comes first: the user pressing the activation
hotkey again, a pause in speech longer than SILENCE_HANG_S, or the hard cap
at MAX_RECORD_S.
"""

import sys
import threading
import time
import types
from collections import namedtuple

import numpy as np
import sounddevice as sd

from yogi.audio import voice_levels
from yogi.core import errors
from yogi.audio.devices import (
    get_input_device,
    get_speech_threshold,
    input_device_name,
    list_input_devices,
)

SAMPLE_RATE = 16000
MODEL_SIZE = "small"
MAX_RECORD_S = 180

BLOCK_MS = 50
SILENCE_HANG_S = 1.5      # stop this long after the user stops talking
NO_SPEECH_TIMEOUT_S = 8.0  # give up if nothing is ever said
# After a reply finishes playing, the user has this long to start a follow-up.
# Default for the "Question follow up time" setting.
FOLLOWUP_WINDOW_S = 2.0
MIN_UTTERANCE_S = 0.3

# Whisper is trained on normalised audio, so quiet mics get boosted rather
# than transcribed as silence.
TARGET_PEAK = 0.9
MAX_GAIN = 20.0

SttResult = namedtuple("SttResult", "text status")

_model = None
_model_lock = threading.Lock()
_loading = False
# Set whenever no load is running, so a question asked during startup waits for it.
_load_done = threading.Event()
_load_done.set()
# First run downloads ~500 MB, so this is generous.
MODEL_WAIT_S = 600

# Set while a recording has heard speech, so the hotkey can tell "I'm done
# talking" apart from "take a new screenshot".
_speech_active = threading.Event()


def speech_in_progress():
    return _speech_active.is_set()


def prewarm_stt():
    """Load the Whisper model in the background so the first question is fast."""
    threading.Thread(target=_ensure_model, daemon=True).start()


def _av_stub():
    """Stand-in for PyAV whose attributes raise an error that says why."""
    stub = types.ModuleType("av")

    def __getattr__(name):
        # Dunder probes (hasattr(m, "__file__"), inspect, freezers) must stay plain misses.
        if name.startswith("__"):
            raise AttributeError(name)
        raise AttributeError(
            f"av.{name}: av is intentionally not installed; Yogi passes numpy arrays"
        )

    stub.__getattr__ = __getattr__
    return stub


def _ensure_model():
    global _model, _loading
    with _model_lock:
        if _model is not None or _loading:
            return
        _loading = True
        _load_done.clear()
    try:
        # faster-whisper imports PyAV (GPL FFmpeg) only for decoding audio files.
        # Yogi passes numpy arrays, so a stub keeps FFmpeg out of the process.
        sys.modules.setdefault("av", _av_stub())
        from faster_whisper import WhisperModel

        t0 = time.perf_counter()
        print(f"stt: loading whisper {MODEL_SIZE}...", flush=True)
        model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"stt: model ready in {ms}ms", flush=True)
        with _model_lock:
            _model = model
    except Exception as e:
        errors.report(
            f"Speech recognition (Whisper {MODEL_SIZE}) failed to load. The first run needs "
            "internet to download it (about 500 MB).",
            detail=e,
        )
    finally:
        with _model_lock:
            _loading = False
            _load_done.set()


class _LevelTracker:
    """Turns incoming blocks into a speech/silence verdict.

    A block counts as speech when its RMS reaches the user's Microphone
    Threshold from Settings.
    """

    def __init__(self, threshold=None):
        self.lock = threading.Lock()
        self.frames = []
        self.peak = 0.0
        self.speech_started = False
        self.last_speech_t = None
        self._threshold = get_speech_threshold() if threshold is None else threshold

    def push(self, block: np.ndarray):
        rms = float(np.sqrt(np.mean(np.square(block))))
        now = time.perf_counter()

        with self.lock:
            self.frames.append(block)
            self.peak = max(self.peak, float(np.max(np.abs(block))))

            if rms >= self._threshold:
                _speech_active.set()
                self.speech_started = True
                self.last_speech_t = now

    def silence_elapsed(self):
        """Seconds since speech last stopped, or None while still talking."""
        with self.lock:
            if not self.speech_started or self.last_speech_t is None:
                return None
            return time.perf_counter() - self.last_speech_t

    def snapshot(self):
        with self.lock:
            return self.speech_started, self.peak, self._threshold

    def audio(self):
        with self.lock:
            if not self.frames:
                return None
            return np.concatenate(self.frames)


def _record(stop_event, cancel_event, no_speech_timeout=NO_SPEECH_TIMEOUT_S):
    _speech_active.clear()
    try:
        return _record_audio(stop_event, cancel_event, no_speech_timeout)
    finally:
        _speech_active.clear()


def _record_audio(stop_event, cancel_event, no_speech_timeout):
    """Capture until the user stops, silence hangs, or nothing is ever said."""
    tracker = _LevelTracker()

    def callback(indata, _frames, _time_info, status):
        if status:
            print(f"stt: stream status: {status}", flush=True)
        block = indata[:, 0].copy()
        tracker.push(block)
        voice_levels.emit_levels(block, SAMPLE_RATE)

    blocksize = SAMPLE_RATE * BLOCK_MS // 1000
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            device=get_input_device(),
            callback=callback,
        ):
            t0 = time.perf_counter()
            next_meter = t0 + 1.0

            while True:
                if cancel_event.is_set():
                    return None, "cancelled"
                if stop_event.is_set():
                    break

                elapsed = time.perf_counter() - t0
                if elapsed > MAX_RECORD_S:
                    print("stt: hit max recording length", flush=True)
                    break

                silence = tracker.silence_elapsed()
                if silence is not None and silence >= SILENCE_HANG_S:
                    break

                started, peak, threshold = tracker.snapshot()
                if not started and elapsed > no_speech_timeout:
                    print(
                        f"stt: no speech in {no_speech_timeout:.0f}s "
                        f"(peak level {peak:.4f})",
                        flush=True,
                    )
                    if peak == 0.0:
                        _report_dead_mic()
                    return None, "no_speech"

                if time.perf_counter() >= next_meter:
                    next_meter += 1.0
                    state = "speaking" if started else "waiting"
                    print(
                        f"stt: {state} {elapsed:4.1f}s  peak={peak:.4f} thr={threshold:.4f}",
                        flush=True,
                    )

                time.sleep(BLOCK_MS / 1000)
    except Exception as e:
        print(f"stt: microphone error: {e}", flush=True)
        _print_device_help()
        return None, "error"

    audio = tracker.audio()
    started, peak, _threshold = tracker.snapshot()

    if audio is None or len(audio) < SAMPLE_RATE * MIN_UTTERANCE_S:
        return None, "no_speech"

    if not started:
        print(f"stt: only silence captured (peak level {peak:.4f})", flush=True)
        _print_device_help()
        if peak == 0.0:
            _report_dead_mic()
        return None, "no_speech"

    return audio, "ok"


def _report_dead_mic():
    errors.report(
        f"The microphone ({input_device_name()}) is sending no sound at all. It may be muted, "
        "blocked in Windows privacy settings, or the wrong input device."
    )


def _print_device_help():
    print(f"stt: current input device: {input_device_name()}", flush=True)
    print("stt: available input devices:", flush=True)
    for index, name in list_input_devices():
        print(f"       [{index}] {name}", flush=True)


def _normalize(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio)))
    if peak <= 0:
        return audio
    gain = min(TARGET_PEAK / peak, MAX_GAIN)
    if gain <= 1.0:
        return audio
    print(f"stt: boosting quiet audio x{gain:.1f}", flush=True)
    return audio * gain


def _transcribe(audio: np.ndarray) -> str:
    _ensure_model()
    if not _load_done.is_set():
        print("stt: waiting for the whisper model to finish loading...", flush=True)
        _load_done.wait(timeout=MODEL_WAIT_S)
    with _model_lock:
        model = _model
    if model is None:
        errors.report("Speech recognition isn't loaded, so your question couldn't be heard.")
        return ""

    t0 = time.perf_counter()
    try:
        segments, _info = model.transcribe(
            _normalize(audio),
            language="en",
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as e:
        errors.report("Speech recognition failed on that recording. Try again.", detail=e)
        return ""
    ms = int((time.perf_counter() - t0) * 1000)
    print(f"stt: transcribed in {ms}ms", flush=True)
    return text


def listen_for_question(
    stop_event, *, hotkey_label, cancel_event=None, no_speech_timeout=NO_SPEECH_TIMEOUT_S,
    cancel_label="esc",
) -> SttResult:
    """Record a question and transcribe it locally.

    Status is one of: ok, no_speech, cancelled, error.
    """
    if cancel_event is None:
        cancel_event = threading.Event()

    stop_event.clear()
    cancel_event.clear()

    print(
        f"stt: recording on {input_device_name()} — press {hotkey_label} when done, "
        f"or just pause for {SILENCE_HANG_S}s ({cancel_label} cancels)",
        flush=True,
    )

    audio, status = _record(stop_event, cancel_event, no_speech_timeout)
    if audio is None:
        if status == "cancelled":
            print("stt: cancelled", flush=True)
        return SttResult(None, status)

    print(f"stt: recorded {len(audio) / SAMPLE_RATE:.1f}s, transcribing...", flush=True)

    text = _transcribe(audio)
    if not text:
        print("stt: nothing recognised in that audio", flush=True)
        return SttResult(None, "no_speech")

    print(f'stt: you said: "{text}"', flush=True)
    return SttResult(text, "ok")
