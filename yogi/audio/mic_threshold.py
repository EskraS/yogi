"""Microphone Threshold control: a draggable threshold over a live input meter.

Levels are block RMS values (0..1), the same measure stt.py compares against
the threshold. The bar is drawn on a dB scale so normal speech sits mid-bar
instead of crammed against the left edge.
"""

import collections
import math
import threading

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from yogi.audio.devices import MAX_SPEECH_THRESHOLD, MIN_SPEECH_THRESHOLD
from yogi.ui.theme_helpers import ACCENT_GREEN

MIN_DB = 20 * math.log10(MIN_SPEECH_THRESHOLD)   # -60 dB
MAX_DB = 20 * math.log10(MAX_SPEECH_THRESHOLD)   # 0 dB

_SAMPLE_RATE = 16000   # same rate stt.py records at, so the RMS matches
_BLOCK = _SAMPLE_RATE // 20
_ECHO_MAX_BLOCKS = 4   # at most ~200 ms of playback delay

_METER_FALL_PER_TICK = 0.012   # how fast the white marker drifts back when quiet


def level_to_pos(level: float) -> float:
    """RMS level to bar position 0..1."""
    if level <= MIN_SPEECH_THRESHOLD:
        return 0.0
    db = 20 * math.log10(min(level, MAX_SPEECH_THRESHOLD))
    return (db - MIN_DB) / (MAX_DB - MIN_DB)


def pos_to_level(pos: float) -> float:
    pos = min(1.0, max(0.0, pos))
    return 10 ** ((MIN_DB + pos * (MAX_DB - MIN_DB)) / 20)


def level_to_db_text(level: float) -> str:
    return f"{20 * math.log10(max(level, MIN_SPEECH_THRESHOLD)):.0f} dB"


class MicLevelMonitor:
    """Opens the mic, keeps the loudest block RMS since the last read, and
    optionally plays the mic back through an output device."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stream = None
        self._playback = None
        self._level = 0.0
        # Playback only passes blocks Yogi would count as speech.
        self._threshold = MIN_SPEECH_THRESHOLD
        # Bounded so playback lag can't grow; old blocks are dropped first.
        self._echo = collections.deque(maxlen=_ECHO_MAX_BLOCKS)

    def set_threshold(self, level: float):
        with self._lock:
            self._threshold = level

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self, device, output_device=None, playback=True):
        """Returns None on success, or an error message. Playback failing
        is not an error: the meter still runs."""
        self.stop()
        try:
            stream = sd.InputStream(
                samplerate=_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=_BLOCK,
                device=device,
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            return str(exc)
        self._stream = stream
        if playback:
            try:
                out = sd.OutputStream(
                    samplerate=_SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=_BLOCK,
                    device=output_device,
                    latency="low",
                    callback=self._play,
                )
                out.start()
                self._playback = out
            except Exception as exc:
                print(f"audio: mic test playback unavailable: {exc}", flush=True)
        return None

    def _callback(self, indata, _frames, _time_info, _status):
        block = indata[:, 0]
        rms = float(np.sqrt(np.mean(np.square(block))))
        with self._lock:
            self._level = max(self._level, rms)
            if rms >= self._threshold:
                self._echo.append(block.copy())

    def _play(self, outdata, frames, _time_info, _status):
        out = outdata[:, 0]
        filled = 0
        with self._lock:
            while filled < frames and self._echo:
                block = self._echo[0]
                take = min(frames - filled, len(block))
                out[filled:filled + take] = block[:take]
                if take == len(block):
                    self._echo.popleft()
                else:
                    self._echo[0] = block[take:]
                filled += take
        out[filled:] = 0

    def take_level(self) -> float:
        with self._lock:
            level, self._level = self._level, 0.0
        return level

    def is_alive(self) -> bool:
        """False once PortAudio stops the stream on its own (e.g. mic unplugged)."""
        try:
            return self._stream is not None and self._stream.active
        except Exception:
            return False

    def stop(self):
        streams = (self._stream, self._playback)
        self._stream = self._playback = None
        for stream in streams:
            if stream is None:
                continue
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                print(f"audio: mic test close failed: {exc}", flush=True)
        with self._lock:
            self._level = 0.0
            self._echo.clear()


class MicThresholdSlider(QWidget):
    """Grey bar with a draggable green-ringed threshold knob and a white live-level marker."""

    # Emitted with the new threshold (RMS) when the user finishes moving it.
    threshold_changed = pyqtSignal(float)
    # Emitted continuously while dragging, for the value label.
    threshold_moved = pyqtSignal(float)

    _KNOB = 14
    _TRACK_H = 6
    _MARKER_W = 4
    _MARKER_H = 12

    def __init__(self, threshold: float, parent=None):
        super().__init__(parent)
        self._pos = level_to_pos(threshold)
        self._meter = 0.0
        self._metering = False
        self._dragging = False
        self._theme = "dark"
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(
            "Drag to set how loud you must be for Yogi to hear you. "
            "Sounds below this line are ignored."
        )

    def threshold(self) -> float:
        return pos_to_level(self._pos)

    def set_theme(self, theme: str):
        self._theme = theme if theme in ("light", "dark") else "dark"
        self.update()

    def set_metering(self, on: bool):
        self._metering = on
        if not on:
            self._meter = 0.0
        self.update()

    def push_level(self, level: float):
        """Show the latest mic level; falls back slowly so short words stay visible."""
        self._meter = max(level_to_pos(level), self._meter - _METER_FALL_PER_TICK)
        self.update()

    def _track_rect(self) -> QRectF:
        pad = self._KNOB / 2 + 1
        y = (self.height() - self._TRACK_H) / 2
        return QRectF(pad, y, self.width() - 2 * pad, self._TRACK_H)

    def _x_for(self, pos: float) -> float:
        track = self._track_rect()
        return track.left() + pos * track.width()

    def _set_pos_from_x(self, x: float):
        track = self._track_rect()
        if track.width() <= 0:
            return
        self._pos = min(1.0, max(0.0, (x - track.left()) / track.width()))
        self.threshold_moved.emit(self.threshold())
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_pos_from_x(e.position().x())
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._set_pos_from_x(e.position().x())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.threshold_changed.emit(self.threshold())
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        step = 1 / (MAX_DB - MIN_DB)   # one dB per arrow press
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._pos = max(0.0, self._pos - step)
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._pos = min(1.0, self._pos + step)
        else:
            super().keyPressEvent(e)
            return
        self.threshold_moved.emit(self.threshold())
        self.threshold_changed.emit(self.threshold())
        self.update()

    def paintEvent(self, _e):
        light = self._theme == "light"
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self._track_rect()
        radius = self._TRACK_H / 2

        # Grey bar; the part below the threshold is darker ("ignored" zone).
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d4d4d8" if light else "#3a3a3a"))
        p.drawRoundedRect(track, radius, radius)
        knob_x = self._x_for(self._pos)
        ignored = QRectF(track.left(), track.top(), knob_x - track.left(), track.height())
        p.setBrush(QColor("#a1a1aa" if light else "#2a2a2a"))
        p.drawRoundedRect(ignored, radius, radius)

        # Live level: translucent white fill plus a small solid white marker.
        if self._metering and self._meter > 0:
            meter_x = self._x_for(self._meter)
            fill = QRectF(track.left(), track.top(), meter_x - track.left(), track.height())
            p.setBrush(QColor(255, 255, 255, 110 if light else 70))
            p.drawRoundedRect(fill, radius, radius)
            marker = QRectF(
                meter_x - self._MARKER_W / 2,
                (self.height() - self._MARKER_H) / 2,
                self._MARKER_W,
                self._MARKER_H,
            )
            p.setPen(QPen(QColor("#3f3f46" if light else "#1e1e1e"), 1.5 if light else 1))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(marker, 2, 2)

        # Threshold knob: hollow green ring so it never looks like the white meter.
        knob = QRectF(
            knob_x - self._KNOB / 2,
            (self.height() - self._KNOB) / 2,
            self._KNOB,
            self._KNOB,
        )
        p.setPen(QPen(QColor(ACCENT_GREEN), 3 if self._dragging or self.hasFocus() else 2.5))
        p.setBrush(QColor("#ffffff" if light else "#252525"))
        p.drawEllipse(knob.adjusted(1.25, 1.25, -1.25, -1.25))
