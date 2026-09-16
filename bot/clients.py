import time

import httpx


class ProviderError(RuntimeError):
    pass


def payload(response):
    # Never include a Telegram request URL: it contains the bot token.
    if response.status_code >= 400:
        raise ProviderError(f"Provider returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise ProviderError("Invalid provider response") from None
    if not isinstance(data, dict):
        raise ProviderError("Invalid provider response")
    return data


class Twitch:
    def __init__(self, http: httpx.Client, client_id: str, client_secret: str):
        self.http = http
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = ""
        self.expires_at = 0.0

    def get_stream(self, login):
        for attempt in range(2):
            if time.monotonic() >= self.expires_at:
                data = payload(
                    self.http.post(
                        "https://id.twitch.tv/oauth2/token",
                        data={
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "grant_type": "client_credentials",
                        },
                    )
                )
                self.token = data["access_token"]
                self.expires_at = time.monotonic() + max(0, data["expires_in"] - 30)
            response = self.http.get(
                "https://api.twitch.tv/helix/streams",
                params={"user_login": login},
                headers={"Client-Id": self.client_id, "Authorization": f"Bearer {self.token}"},
            )
            if response.status_code == 401 and attempt == 0:
                self.expires_at = 0
                continue
            streams = payload(response).get("data")
            if not isinstance(streams, list):
                raise ProviderError("Invalid streams response")
            if not streams:
                return None
            if not isinstance(streams[0], dict) or not all(
                isinstance(streams[0].get(key), str) for key in ("id", "title")
            ):
                raise ProviderError("Invalid stream")
            return streams[0]


class Telegram:
    def __init__(self, http: httpx.Client, token: str):
        self.http = http
        self.base = f"https://api.telegram.org/bot{token}"

    def send(self, chat_id, text):
        data = payload(
            self.http.post(f"{self.base}/sendMessage", json={"chat_id": chat_id, "text": text})
        )
        if not data.get("ok"):
            raise ProviderError("Telegram send failed")
        return data["result"]["message_id"]

    def delete(self, chat_id, message_id):
        response = self.http.post(
            f"{self.base}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}
        )
        # An already deleted message is a successful terminal state.
        if response.status_code == 400:
            try:
                if response.json().get("description") == "Bad Request: message to delete not found":
                    return
            except (ValueError, AttributeError):
                pass
        if not payload(response).get("ok"):
            raise ProviderError("Telegram delete failed")
