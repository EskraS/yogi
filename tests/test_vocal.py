"""Self-check for vocal. Run: python -m tests.test_vocal"""

import io
import math

import av
import numpy as np

from yogi.audio import vocal


def _tone(rate, seconds=0.5):
    t = np.arange(int(rate * seconds)) / rate
    return (np.sin(2 * math.pi * 440 * t) * 8000).astype(np.int16)


def _encode(container_fmt, codec, rate, samples):
    buf = io.BytesIO()
    with av.open(buf, mode="w", format=container_fmt) as out:
        stream = out.add_stream(codec, rate=rate, layout="mono")
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.rate = rate
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def _decoded_seconds(data, fmt, rate):
    got = []
    sink = vocal.PcmSink(got.append, fmt, rate)
    for i in range(0, len(data), 1000):
        sink.feed(data[i:i + 1000])
    sink.close()
    return sum(len(b) for b in got) / 2 / vocal.PLAYBACK_RATE


def test_sentences():
    chunks = ["Hello the", "re. This is short. ", "And this one keeps going for a while. ",
              "More words here to pass the limit. End"]
    pieces = list(vocal.iter_sentences(chunks, min_chars=40))
    assert pieces[0] == "Hello there.", pieces
    assert "".join(pieces).replace(" ", "") == "".join(chunks).replace(" ", ""), pieces
    assert pieces[-1].endswith("End"), pieces
    assert list(vocal.iter_sentences(["no boundary at all"])) == ["no boundary at all"]


def test_direct_pcm_keeps_sample_alignment():
    got = []
    sink = vocal.PcmSink(got.append)
    for piece in (b"\x01", b"\x02\x03", b"\x04\x05\x06"):
        sink.feed(piece)
    sink.close()
    assert b"".join(got) == b"\x01\x02\x03\x04\x05\x06"
    assert all(len(b) % 2 == 0 for b in got)


def test_decoded_formats_play_at_24k():
    cases = {
        "mp3": (_encode("mp3", "libmp3lame", 44100, _tone(44100)), 44100),
        "wav": (_encode("wav", "pcm_s16le", 24000, _tone(24000)), 24000),
        "pcm@16k": (_tone(16000).tobytes(), 16000),
        "mulaw": (_encode("mulaw", "pcm_mulaw", 8000, _tone(8000)), 8000),
        "opus": (_encode("ogg", "libopus", 48000, _tone(48000)), 48000),
    }
    for name, (data, rate) in cases.items():
        fmt = name.split("@")[0]
        seconds = _decoded_seconds(data, fmt, rate)
        assert 0.4 < seconds < 0.65, (name, seconds)


def test_speak_http_plays_pieces_in_order():
    import time

    class Response:
        def __init__(self, body, delay):
            self.status_code, self._body, self._delay = 200, body, delay
            self.content = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_content(self, size):
            time.sleep(self._delay)
            yield from (self._body[i:i + size] for i in range(0, len(self._body), size))

    class Session:
        def post(self, url, headers, json, stream, timeout):
            # Later pieces answer faster, so out-of-order playback would show up.
            n = int(json["text"])
            return Response(bytes([n, 0]) * 5000, delay=0.05 * (4 - n))

    got = []
    vocal.speak_http(["1", "2", "3"], lambda t: ("u", {}, {"text": t}),
                     ("pcm", vocal.PLAYBACK_RATE), got.append, Session())
    order = [b[0] for b in got if b]
    assert order == sorted(order) and set(order) == {1, 2, 3}, order


def test_request_builders():
    s = dict(vocal.DEFAULTS, or_model="m", or_voice="v", or_data_policy="zdr", fish_tags="[calm]")
    _, _, body = vocal.openrouter_request(s, "k", "hi")
    assert body == {"model": "m", "input": "hi", "response_format": "pcm", "voice": "v",
                    "provider": {"zdr": True}}, body
    _, _, body = vocal.openrouter_request(dict(s, or_style="sad", or_style_degree=1.5), "k", "hi")
    assert body["provider"] == {"zdr": True, "options": {"azure": {"style": "sad", "styledegree": 1.5}}}
    _, headers, body = vocal.fish_request(s, "k", "hi")
    assert headers["model"] == "s2.1-pro" and body["text"] == "[calm] hi"
    assert body["temperature"] == 0.7 and body["top_p"] == 0.7 and "prosody" not in body
    _, _, body = vocal.fish_request(dict(s, fish_tags="speak softly", fish_speed=1.5), "k", "hi")
    assert body["text"] == "[speak softly] hi" and body["prosody"] == {"speed": 1.5}
    _, _, body = vocal.fish_request(dict(s, fish_tags="calm", fish_model="s1"), "k", "hi")
    assert body["text"] == "(calm) hi"
    assert body["sample_rate"] == 24000 and "reference_id" not in body
    _, _, body = vocal.fish_request(dict(s, fish_voice="Dexter morgan"), "k", "hi")
    assert "reference_id" not in body
    _, _, body = vocal.fish_request(dict(s, fish_voice="9a9cf47702da476aa4629e2506d4a857"), "k", "hi")
    assert body["reference_id"] == "9a9cf47702da476aa4629e2506d4a857"


def test_resolve_fish_voice_title():
    calls = []

    def fake_get(key, url, params=None):
        calls.append(params)
        return {"items": [{"_id": "abc123voice", "title": "Dexter Morgan"}]}, None, 200

    named = {"fish_voice": "Dexter morgan"}
    vocal._fish_title_ids.clear()
    original = vocal._fish_get
    vocal._fish_get = fake_get
    try:
        vocal.resolve_fish_voice(named, "k")
        vocal.resolve_fish_voice(named, "k")
    finally:
        vocal._fish_get = original
        vocal._fish_title_ids.clear()
    assert named["fish_voice"] == "abc123voice", named
    assert calls == [{"title": "Dexter morgan", "page_size": 20, "page_number": 1}]
    params = vocal.grok_ws_params(dict(vocal.DEFAULTS, grok_codec="mp3"))
    assert params["bit_rate"] == 128000 and params["text_normalization"] == "false"
    assert "bit_rate" not in vocal.grok_ws_params(vocal.DEFAULTS)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
