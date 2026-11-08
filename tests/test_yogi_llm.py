"""Mocked unit tests for yogi LLM request building, streaming, and HTTP prewarm."""

import json
import threading
import time
import unittest
from unittest import mock

import yogi.core.assistant as yogi


def _sse_chunk(content):
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}".encode("utf-8")


class FakeResponse:
    def __init__(self, status_code=200, text="", lines=None):
        self.status_code = status_code
        self.text = text
        self._lines = lines or []

    def iter_lines(self):
        return iter(self._lines)


def _base_settings(**overrides):
    settings = {
        "api_key": "test-key",
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
    settings.update(overrides)
    return settings


class TestLlmRequest(unittest.TestCase):
    def test_openrouter_url_headers_and_extra_params(self):
        settings = _base_settings()
        url, headers, body = yogi._llm_request(settings, "imgb64", "what is this?")

        self.assertEqual(url, yogi.OPENROUTER_URL)
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(headers["Content-Type"], "application/json")
        for key in (
            "frequency_penalty",
            "presence_penalty",
            "repetition_penalty",
            "min_p",
            "top_a",
            "top_k",
        ):
            self.assertIn(key, body)
        self.assertTrue(body["stream"])
        self.assertEqual(body["model"], "google/gemini-3.6-flash")
        image_part = body["messages"][1]["content"][0]
        self.assertEqual(image_part["type"], "image_url")
        self.assertIn(
            "data:image/jpeg;base64,imgb64", image_part["image_url"]["url"]
        )
        self.assertEqual(body["messages"][0]["content"], yogi._SYSTEM_PROMPT)

    def test_custom_prompt_is_the_system_message(self):
        settings = _base_settings(prompt="  You are a terse assistant.  ")
        _, _, body = yogi._llm_request(settings, "imgb64", "what is this?")
        self.assertEqual(body["messages"][0]["content"], "You are a terse assistant.")

    def test_module_text_appended_to_system_prompt(self):
        _, _, body = yogi._llm_request(
            _base_settings(),
            "imgb64",
            "best move?",
            module_text="[Chess]\nWhite to move:\n  e4",
        )
        system = body["messages"][0]["content"]
        self.assertIn(yogi._MODULE_PROMPT_ADDENDUM.strip(), system)
        self.assertIn("[Chess]", system)
        self.assertIn("White to move:", system)

    def test_empty_module_text_leaves_system_prompt_alone(self):
        _, _, body = yogi._llm_request(
            _base_settings(), "imgb64", "what is this?", module_text=""
        )
        self.assertEqual(body["messages"][0]["content"], yogi._SYSTEM_PROMPT)

    def test_follow_up_keeps_history_and_image_on_first_turn(self):
        _, _, body = yogi._llm_request(
            _base_settings(), "imgb64", "and now?", history=[("what is this?", "A cat.")]
        )
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(body["messages"][1]["content"][0]["type"], "image_url")
        self.assertEqual(body["messages"][1]["content"][1]["text"], "what is this?")
        self.assertEqual(body["messages"][2]["content"], "A cat.")
        self.assertEqual(body["messages"][3]["content"], [{"type": "text", "text": "and now?"}])

    def test_surf_web_adds_openrouter_web_search_tool(self):
        _, _, body = yogi._llm_request(_base_settings(surf_web=True), "imgb64", "news?")
        self.assertEqual(body["tools"], [{"type": "openrouter:web_search"}])

    def test_surf_web_off_omits_tools(self):
        _, _, body = yogi._llm_request(_base_settings(surf_web=False), "imgb64", "news?")
        self.assertNotIn("tools", body)

    def test_reasoning_effort_is_sent_and_hidden_from_the_reply(self):
        _, _, body = yogi._llm_request(
            _base_settings(reasoning_effort="high"), "imgb64", "why?"
        )
        self.assertEqual(body["reasoning"], {"effort": "high", "exclude": True})

    def test_reasoning_off_omits_reasoning(self):
        _, _, body = yogi._llm_request(
            _base_settings(reasoning_effort="off"), "imgb64", "why?"
        )
        self.assertNotIn("reasoning", body)
        _, _, body = yogi._llm_request(_base_settings(), "imgb64", "why?")
        self.assertNotIn("reasoning", body)


class TestFollowUpLoop(unittest.TestCase):
    def test_listens_again_with_short_window_until_silence(self):
        listens = [("q1", "ok"), ("q2", "ok"), (None, "no_speech")]
        timeouts, histories = [], []

        def fake_listen(*_args, no_speech_timeout, **_kwargs):
            timeouts.append(no_speech_timeout)
            return listens.pop(0)

        module_texts = []

        def fake_ask(_img, question, _settings, history, module_text=""):
            histories.append(list(history))
            module_texts.append(module_text)
            yield f"answer to {question}"

        with mock.patch.object(yogi, "take_screenshot"), \
                mock.patch.object(yogi, "encode_screenshot", return_value="aW1n"), \
                mock.patch.object(yogi, "keyboard"), \
                mock.patch.object(yogi, "get_settings", return_value={}), \
                mock.patch.object(yogi, "listen_for_question", fake_listen), \
                mock.patch.object(yogi, "ask_yogi", fake_ask), \
                mock.patch.object(yogi, "speak_yogi", lambda chunks, _s: list(chunks)), \
                mock.patch.object(yogi.module_loader, "run_enabled_modules", return_value=""), \
                mock.patch.object(yogi.history_store, "save_chat") as save_chat:
            yogi.run_yogi()

        self.assertEqual(
            timeouts, [yogi.NO_SPEECH_TIMEOUT_S, yogi.FOLLOWUP_WINDOW_S, yogi.FOLLOWUP_WINDOW_S]
        )
        self.assertEqual(histories, [[], [("q1", "answer to q1")]])
        # Saved after each reply, under one chat id, with the screenshot bytes.
        self.assertEqual(save_chat.call_count, 2)
        ids = {c.args[0] for c in save_chat.call_args_list}
        self.assertEqual(len(ids), 1)
        self.assertEqual(save_chat.call_args.args[3], b"img")
        self.assertEqual(
            save_chat.call_args.args[2], [("q1", "answer to q1"), ("q2", "answer to q2")]
        )
        self.assertEqual(module_texts, ["", ""])
        # Chess text is not copied into saved history.
        for turn in save_chat.call_args.args[2]:
            self.assertEqual(len(turn), 2)

    def test_follow_up_gets_late_module_context(self):
        listens = [("q1", "ok"), ("q2", "ok"), (None, "no_speech")]
        module_texts = []
        started = threading.Event()
        release = threading.Event()

        def fake_listen(*_args, no_speech_timeout, **_kwargs):
            return listens.pop(0)

        def slow_modules(_image, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return "[Chess]\nWhite to move:\n  e4"

        def fake_ask(_img, question, _settings, history, module_text=""):
            module_texts.append(module_text)
            if question == "q1":
                release.set()
                started.wait(timeout=2)
                time.sleep(0.05)
            yield f"answer to {question}"

        with mock.patch.object(yogi, "MODULE_WAIT_TIMEOUT_S", 0.05), \
                mock.patch.object(yogi, "take_screenshot"), \
                mock.patch.object(yogi, "encode_screenshot", return_value="aW1n"), \
                mock.patch.object(yogi, "keyboard"), \
                mock.patch.object(yogi, "get_settings", return_value={}), \
                mock.patch.object(yogi, "listen_for_question", fake_listen), \
                mock.patch.object(yogi, "ask_yogi", fake_ask), \
                mock.patch.object(yogi, "speak_yogi", lambda chunks, _s: list(chunks)), \
                mock.patch.object(yogi.module_loader, "run_enabled_modules", slow_modules), \
                mock.patch.object(yogi.history_store, "save_chat"):
            yogi.run_yogi()

        self.assertEqual(module_texts[0], "")
        self.assertEqual(module_texts[1], "[Chess]\nWhite to move:\n  e4")

    def test_stale_scan_is_ignored_after_clear(self):
        with mock.patch.object(
            yogi.module_loader, "run_enabled_modules", return_value="LATE"
        ):
            shot_id = yogi._begin_screenshot_scan(object())
            yogi._clear_screenshot_scan()
            yogi._run_modules_for_shot(shot_id, object())
        self.assertEqual(yogi._module_text_for_turn(0), "")

    def _run_session(self, *, listens, modules, take_shots, encode="orig"):
        module_texts, encoded_sent = [], []

        def fake_listen(*_args, no_speech_timeout, **_kwargs):
            return listens.pop(0)

        def fake_ask(encoded, question, _settings, history, module_text=""):
            encoded_sent.append(encoded)
            module_texts.append(module_text)
            yield f"answer to {question}"

        with mock.patch.object(yogi, "MODULE_WAIT_TIMEOUT_S", 0.5), \
                mock.patch.object(yogi, "take_screenshot", side_effect=list(take_shots)) as shot, \
                mock.patch.object(yogi, "encode_screenshot", return_value=encode) as enc, \
                mock.patch.object(yogi, "keyboard"), \
                mock.patch.object(yogi, "get_settings", return_value={}), \
                mock.patch.object(yogi, "listen_for_question", fake_listen), \
                mock.patch.object(yogi, "ask_yogi", fake_ask), \
                mock.patch.object(yogi, "speak_yogi", lambda chunks, _s: list(chunks)), \
                mock.patch.object(yogi, "_followup_refresh_ids", return_value=("chess",)), \
                mock.patch.object(yogi.module_loader, "run_enabled_modules", modules), \
                mock.patch.object(yogi.history_store, "save_chat"):
            yogi.run_yogi()
        return module_texts, encoded_sent, shot, enc

    def test_follow_up_replaces_chess_context_when_board_found(self):
        img1, img2, img3 = object(), object(), object()
        calls = []

        def modules(image, module_ids=None):
            calls.append((image, module_ids))
            if module_ids == ("chess",):
                return "[Chess]\nNEW"
            return "[Chess]\nOLD"

        module_texts, encoded_sent, shot, enc = self._run_session(
            listens=[("q1", "ok"), ("q2", "ok"), (None, "no_speech")],
            modules=modules,
            take_shots=[img1, img2, img3],
        )
        self.assertEqual(module_texts, ["[Chess]\nOLD", "[Chess]\nNEW"])
        self.assertEqual(encoded_sent, ["orig", "orig"])
        self.assertEqual(enc.call_count, 1)
        self.assertIs(enc.call_args.args[0], img1)
        self.assertGreaterEqual(shot.call_count, 2)
        self.assertEqual(calls[0], (img1, None))
        self.assertEqual(calls[1], (img2, ("chess",)))

    def test_follow_up_keeps_chess_context_when_no_board(self):
        img1, img2, img3 = object(), object(), object()

        def modules(image, module_ids=None):
            if module_ids == ("chess",):
                return ""
            return "[Chess]\nOLD"

        module_texts, encoded_sent, shot, enc = self._run_session(
            listens=[("q1", "ok"), ("q2", "ok"), (None, "no_speech")],
            modules=modules,
            take_shots=[img1, img2, img3],
        )
        self.assertEqual(module_texts, ["[Chess]\nOLD", "[Chess]\nOLD"])
        self.assertEqual(encoded_sent, ["orig", "orig"])
        self.assertEqual(enc.call_count, 1)
        self.assertGreaterEqual(shot.call_count, 2)


class TestHotkeyFollowUpScreenshot(unittest.TestCase):
    def setUp(self):
        yogi._new_screenshot.clear()
        yogi._stop_recording.clear()

    def tearDown(self):
        yogi._yogi_in_session = False
        yogi._new_screenshot.clear()
        yogi._stop_recording.clear()
        yogi._awaiting_followup.clear()

    def test_hotkey_while_talking_in_followup_only_ends_question(self):
        yogi._yogi_in_session = True
        yogi._awaiting_followup.set()
        with mock.patch.object(yogi, "speech_in_progress", return_value=True):
            yogi._on_activation_hotkey()
        self.assertTrue(yogi._stop_recording.is_set())
        self.assertFalse(yogi._new_screenshot.is_set())

    def test_hotkey_in_followup_window_requests_screenshot(self):
        yogi._yogi_in_session = True
        yogi._awaiting_followup.set()
        with mock.patch.object(yogi, "speech_in_progress", return_value=False):
            yogi._on_activation_hotkey()
        self.assertTrue(yogi._new_screenshot.is_set())
        self.assertTrue(yogi._stop_recording.is_set())

    def test_hotkey_outside_followup_window_never_requests_screenshot(self):
        # First question, or while Yogi is answering.
        yogi._yogi_in_session = True
        with mock.patch.object(yogi, "speech_in_progress", return_value=False):
            yogi._on_activation_hotkey()
        self.assertFalse(yogi._new_screenshot.is_set())
        self.assertTrue(yogi._stop_recording.is_set())

    def test_hotkey_during_first_question_ends_session_without_screenshot(self):
        listens = []
        shots = []

        def fake_listen(*_args, no_speech_timeout, **_kwargs):
            listens.append(yogi._awaiting_followup.is_set())
            yogi._on_activation_hotkey()   # pressed before speaking
            return (None, "no_speech")

        with mock.patch.object(yogi, "take_screenshot", side_effect=lambda: shots.append(1)), \
                mock.patch.object(yogi, "encode_screenshot", return_value="aW1n"), \
                mock.patch.object(yogi, "keyboard"), \
                mock.patch.object(yogi, "get_settings", return_value={}), \
                mock.patch.object(yogi, "speech_in_progress", return_value=False), \
                mock.patch.object(yogi, "listen_for_question", fake_listen), \
                mock.patch.object(yogi.module_loader, "run_enabled_modules", return_value=""), \
                mock.patch.object(yogi.history_store, "save_chat"):
            yogi.run_yogi()
        self.assertEqual(listens, [False])
        self.assertEqual(len(shots), 1)

    def test_follow_up_screenshot_replaces_image_and_uses_followup_time(self):
        timeouts, encoded_sent = [], []
        encodes = iter(["shot1", "shot2"])

        def fake_listen(*_args, no_speech_timeout, **_kwargs):
            timeouts.append(no_speech_timeout)
            n = len(timeouts)
            if n == 1:
                return ("q1", "ok")
            if n == 2:
                # Hotkey pressed in the follow-up window before speaking.
                yogi._new_screenshot.set()
                return (None, "no_speech")
            if n == 3:
                return ("q2", "ok")
            return (None, "no_speech")

        def fake_ask(encoded, question, _settings, history, module_text=""):
            encoded_sent.append(encoded)
            yield f"answer to {question}"

        with mock.patch.object(yogi, "take_screenshot"), \
                mock.patch.object(yogi, "encode_screenshot", side_effect=lambda _i: next(encodes)), \
                mock.patch.object(yogi, "keyboard"), \
                mock.patch.object(yogi, "get_settings", return_value={"followup_window_s": 4.5}), \
                mock.patch.object(yogi, "listen_for_question", fake_listen), \
                mock.patch.object(yogi, "ask_yogi", fake_ask), \
                mock.patch.object(yogi, "speak_yogi", lambda chunks, _s: list(chunks)), \
                mock.patch.object(yogi, "_followup_refresh_ids", return_value=()), \
                mock.patch.object(yogi.module_loader, "run_enabled_modules", return_value=""), \
                mock.patch.object(yogi.base64, "b64decode", return_value=b""), \
                mock.patch.object(yogi.history_store, "save_chat"):
            yogi.run_yogi()

        self.assertEqual(encoded_sent, ["shot1", "shot2"])
        self.assertEqual(timeouts, [yogi.NO_SPEECH_TIMEOUT_S, 4.5, yogi.NO_SPEECH_TIMEOUT_S, 4.5])


class TestStopHotkey(unittest.TestCase):
    def tearDown(self):
        yogi._stop_speaking.clear()
        yogi._cancel_recording.clear()

    def test_stop_during_reply_cuts_stream_and_ends_session(self):
        listens = [("q1", "ok"), ("q2", "ok")]
        spoken = []
        keyboard = mock.Mock()

        def fake_listen(*_args, **_kwargs):
            return listens.pop(0)

        def fake_ask(*_args, **_kwargs):
            yield "first "
            yogi._cancel_recording_handler()   # stop pressed mid-answer
            yield "second"

        def fake_speak(chunks, _settings):
            spoken.extend(chunks)

        with mock.patch.object(yogi, "take_screenshot"), \
                mock.patch.object(yogi, "encode_screenshot", return_value="aW1n"), \
                mock.patch.object(yogi, "keyboard", keyboard), \
                mock.patch.object(yogi, "get_settings", return_value={"stop_hotkey": "Escape"}), \
                mock.patch.object(yogi, "listen_for_question", fake_listen), \
                mock.patch.object(yogi, "ask_yogi", fake_ask), \
                mock.patch.object(yogi, "speak_yogi", fake_speak), \
                mock.patch.object(yogi.module_loader, "run_enabled_modules", return_value=""), \
                mock.patch.object(yogi.history_store, "save_chat") as save_chat:
            yogi.run_yogi()

        self.assertEqual(spoken, ["first "])
        self.assertEqual(listens, [("q2", "ok")])   # no follow-up listen
        save_chat.assert_not_called()
        keyboard.add_hotkey.assert_called_once_with("esc", yogi._cancel_recording_handler)

    def test_stop_hotkey_normalizes_qt_names(self):
        self.assertEqual(yogi._normalize_hotkey("Escape", yogi.DEFAULT_STOP_HOTKEY), "esc")
        self.assertEqual(yogi._normalize_hotkey("", yogi.DEFAULT_STOP_HOTKEY), "esc")
        self.assertEqual(yogi._normalize_hotkey("Ctrl+Q", yogi.DEFAULT_STOP_HOTKEY), "ctrl+q")

    def test_speak_http_stops_early(self):
        from yogi.audio import vocal

        played = []
        stop = {"now": False}

        def build(text):
            return "u", {}, {}

        class Resp:
            status_code = 200

            def __init__(self, text):
                self.text = text

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def iter_content(self, _n):
                yield b"\x01\x00" * 4

        session = mock.Mock()
        session.post.side_effect = lambda *a, **k: Resp("x")

        def write(pcm):
            played.append(pcm)
            stop["now"] = True

        vocal.speak_http(iter(["a", "b", "c"]), build, ("pcm", vocal.PLAYBACK_RATE), write,
                         session, should_stop=lambda: stop["now"])
        self.assertEqual(len(played), 1)


class TestAskYogiStreaming(unittest.TestCase):
    def _run_ask(self, settings, response):
        session = mock.Mock()
        session.post.return_value = response
        with mock.patch.object(yogi._http_prewarm, "session", return_value=session):
            tokens = list(yogi.ask_yogi("imgb64", "hello?", settings) or [])
        return session, tokens

    def test_openrouter_streams_tokens(self):
        lines = [_sse_chunk("Hello"), _sse_chunk(" world"), b"data: [DONE]"]
        session, tokens = self._run_ask(
            _base_settings(), FakeResponse(lines=lines)
        )
        self.assertEqual(tokens, ["Hello", " world"])
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], yogi.OPENROUTER_URL)
        self.assertTrue(kwargs["stream"])
        self.assertIn("frequency_penalty", kwargs["json"])
        self.assertIn(
            "data:image/jpeg;base64,imgb64",
            kwargs["json"]["messages"][1]["content"][0]["image_url"]["url"],
        )

    def test_non_200_yields_nothing(self):
        session, tokens = self._run_ask(
            _base_settings(), FakeResponse(status_code=401, text="unauthorized")
        )
        self.assertEqual(tokens, [])
        session.post.assert_called_once()


class TestHttpPrewarm(unittest.TestCase):
    def test_warm_request_openrouter(self):
        url, headers = yogi._warm_request(_base_settings())
        self.assertEqual(url, yogi.OPENROUTER_WARM_URL)
        self.assertEqual(headers["Authorization"], "Bearer test-key")

    def test_warm_once_hits_openrouter_host(self):
        session = mock.Mock()
        yogi._HttpPrewarm._warm_once(
            session,
            _base_settings(api_key="or-key"),
            announce=False,
        )
        args, kwargs = session.get.call_args
        self.assertIn("openrouter.ai", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer or-key")


class TestGetSettingsMerge(unittest.TestCase):
    def tearDown(self):
        yogi.set_settings_getter(None)

    def test_live_settings_override_and_voice_keys_survive(self):
        yogi.set_settings_getter(
            lambda: {
                "model": "qwen/qwen3-vl-8b-instruct",
                "temperature": 0.2,
            }
        )
        with mock.patch.object(yogi.key_store, "get_key", return_value="stored-openrouter-key"):
            merged = yogi.get_settings()
        self.assertNotIn("provider", merged)
        self.assertEqual(merged["api_key"], "stored-openrouter-key")
        self.assertEqual(merged["model"], "qwen/qwen3-vl-8b-instruct")
        self.assertEqual(merged["temperature"], 0.2)
        self.assertEqual(merged["voice_api_key"], yogi.test_settings["voice_api_key"])
        self.assertEqual(merged["voice_id"], yogi.test_settings["voice_id"])

    def test_no_getter_returns_test_settings_copy(self):
        yogi.set_settings_getter(None)
        with mock.patch.object(yogi.key_store, "get_key", return_value=None):
            merged = yogi.get_settings()
        self.assertEqual(merged["api_key"], "")
        self.assertNotIn("api_key", yogi.test_settings)
        self.assertIsNot(merged, yogi.test_settings)

    def test_storage_failure_yields_empty_key(self):
        yogi.set_settings_getter(None)
        with mock.patch.object(
            yogi.key_store, "get_key", side_effect=yogi.key_store.KeyStoreError("boom")
        ):
            merged = yogi.get_settings()
        self.assertEqual(merged["api_key"], "")


if __name__ == "__main__":
    unittest.main()
