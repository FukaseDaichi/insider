import json

import httpx2
import pytest

from insider_bot.line.client import LineReplyClient

MESSAGES = [{"type": "text", "text": "こんにちは"}]


def recording(status=200):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(status, json={})

    return requests, httpx2.MockTransport(handler)


async def test_reply_posts_the_token_and_the_messages_with_the_bearer_token():
    requests, transport = recording()
    client = LineReplyClient("channel-token", transport=transport)
    await client.reply("reply-token", MESSAGES)
    await client.aclose()
    (request,) = requests
    assert (request.method, str(request.url)) == ("POST", "https://api.line.me/v2/bot/message/reply")
    assert request.headers["Authorization"] == "Bearer channel-token"
    assert json.loads(request.content) == {"replyToken": "reply-token", "messages": MESSAGES}


async def test_the_api_base_url_can_point_at_a_stub():
    requests, transport = recording()
    client = LineReplyClient("channel-token", "http://127.0.0.1:18080", transport=transport)
    await client.reply("reply-token", MESSAGES)
    await client.aclose()
    assert str(requests[0].url) == "http://127.0.0.1:18080/v2/bot/message/reply"


async def test_http_errors_are_raised_for_the_caller_to_log():
    _, transport = recording(status=400)
    client = LineReplyClient("channel-token", transport=transport)
    with pytest.raises(httpx2.HTTPStatusError):
        await client.reply("reply-token", MESSAGES)
    await client.aclose()


@pytest.mark.parametrize("count", [0, 6])
async def test_no_messages_or_more_than_five_are_refused_before_sending(count):
    requests, transport = recording()
    client = LineReplyClient("channel-token", transport=transport)
    with pytest.raises(ValueError):
        await client.reply("reply-token", MESSAGES * count)
    await client.aclose()
    assert requests == []
