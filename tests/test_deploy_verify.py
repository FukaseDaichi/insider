import contextlib
import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from deploy.verify.line_api_stub import ReplyRecorder
from deploy.verify.post_callback import build_body, post


@contextlib.contextmanager
def running_stub():
    server = HTTPServer(("127.0.0.1", 0), ReplyRecorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_text_event_carries_the_user_and_the_text():
    event = build_body("text", "U1", "お題")["events"][0]
    assert (event["type"], event["message"]["type"], event["message"]["text"]) == ("message", "text", "お題")
    assert event["source"] == {"type": "user", "userId": "U1"}
    assert event["replyToken"]


def test_a_postback_event_carries_the_data():
    event = build_body("postback", "U1", "1234")["events"][0]
    assert (event["type"], event["postback"]["data"]) == ("postback", "1234")


def test_a_sticker_event_has_sticker_ids():
    event = build_body("sticker", "U1", None)["events"][0]
    assert (event["type"], event["message"]["type"]) == ("message", "sticker")
    assert event["message"]["packageId"] and event["message"]["stickerId"]


def test_unknown_kinds_are_rejected():
    with pytest.raises(ValueError):
        build_body("image", "U1", None)


def test_the_stub_prints_the_reply_and_answers_200(capsys):
    payload = {"replyToken": "t", "messages": [{"type": "text", "text": "こんにちは"}]}
    with running_stub() as base:
        request = urllib.request.Request(
            base + "/v2/bot/message/reply",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer x"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert (response.status, response.read()) == (200, b"{}")
    out = capsys.readouterr().out
    assert "Bearer あり" in out
    assert "こんにちは" in out


def test_the_stub_refuses_other_paths():
    with running_stub() as base:
        request = urllib.request.Request(base + "/v2/bot/message/push", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
    assert error.value.code == 404


def test_post_sends_the_body_and_reports_the_status_and_time():
    with running_stub() as base:
        status, elapsed_ms = post(base + "/v2/bot/message/reply", "secret", b"{}")
    assert status == 200
    assert elapsed_ms >= 0
