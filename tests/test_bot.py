from unittest.mock import Mock

import httpx
import pytest

from bot.clients import ProviderError, Telegram, Twitch
from bot.main import poll
from bot.state import load


def test_live_restart_offline(tmp_path):
    path = tmp_path / "state.json"
    twitch, telegram = Mock(), Mock()
    twitch.get_stream.return_value = {"id": "stream-1", "title": "Hello"}
    telegram.send.return_value = 42
    poll(twitch, telegram, path, "example", "chat")
    poll(twitch, telegram, path, "example", "chat")
    telegram.send.assert_called_once()
    assert load(path)["active"]["message_id"] == 42
    twitch.get_stream.return_value = None
    poll(twitch, telegram, path, "example", "chat")
    telegram.delete.assert_called_once_with("chat", 42)
    assert load(path) == {"active": None, "pending_delete": []}


def test_network_error_does_not_end_stream(tmp_path):
    path = tmp_path / "state.json"
    twitch, telegram = Mock(), Mock()
    twitch.get_stream.return_value = {"id": "1", "title": "Hi"}
    telegram.send.return_value = 1
    poll(twitch, telegram, path, "example", "chat")
    before = path.read_bytes()
    twitch.get_stream.side_effect = ProviderError("timeout")
    with pytest.raises(ProviderError):
        poll(twitch, telegram, path, "example", "chat")
    assert path.read_bytes() == before
    telegram.delete.assert_not_called()


def test_delete_retry_keeps_original_chat(tmp_path):
    path = tmp_path / "state.json"
    twitch, telegram = Mock(), Mock()
    twitch.get_stream.return_value = {"id": "1", "title": "Hi"}
    telegram.send.return_value = 1
    poll(twitch, telegram, path, "example", "old-chat")
    twitch.get_stream.return_value = None
    telegram.delete.side_effect = ProviderError("unavailable")
    poll(twitch, telegram, path, "example", "new-chat")
    assert len(load(path)["pending_delete"]) == 1
    telegram.delete.side_effect = None
    poll(twitch, telegram, path, "example", "new-chat")
    telegram.delete.assert_called_with("old-chat", 1)
    assert load(path)["pending_delete"] == []


def test_new_stream_replaces_old(tmp_path):
    twitch, telegram = Mock(), Mock()
    twitch.get_stream.side_effect = [{"id": "1", "title": "One"}, {"id": "2", "title": "Two"}]
    telegram.send.side_effect = [10, 20]
    path = tmp_path / "state.json"
    for _ in range(2):
        poll(twitch, telegram, path, "example", "chat")
    telegram.delete.assert_called_once_with("chat", 10)
    assert load(path)["active"]["message_id"] == 20


def test_corrupt_state_stops(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("broken")
    with pytest.raises(ValueError):
        load(path)


def test_twitch_token_refresh():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == "/oauth2/token":
            assert "client_secret" not in str(request.url)
            return httpx.Response(200, json={"access_token": "test", "expires_in": 3600})
        if len(requests) == 2:
            return httpx.Response(401)
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        assert Twitch(http, "test", "test").get_stream("example") is None
    assert len(requests) == 4


def test_malformed_twitch_not_offline():
    def handle(request):
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "test", "expires_in": 3600})
        return httpx.Response(200, json={"unexpected": []})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ProviderError):
            Twitch(http, "test", "test").get_stream("example")


def test_telegram_missing_message_is_deleted():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400, json={"description": "Bad Request: message to delete not found"}
            )
        )
    ) as http:
        Telegram(http, "test").delete("chat", 1)


def test_telegram_error_does_not_expose_token():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as http:
        with pytest.raises(ProviderError) as error:
            Telegram(http, "do-not-log").send("chat", "text")
        assert "do-not-log" not in str(error.value)
