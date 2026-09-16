import logging
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from bot.clients import ProviderError, Telegram, Twitch
from bot.state import load, save

logger = logging.getLogger(__name__)


def poll(twitch, telegram, path, login, chat_id):
    state = load(path)
    stream = twitch.get_stream(login)  # Failure is not an offline response.
    active = state["active"]
    if active and (
        stream is None
        or active["stream_id"] != stream["id"]
        or active["chat_id"] != chat_id
        or active["login"] != login
    ):
        state["pending_delete"].append(active)
        state["active"] = None
        save(path, state)
    for message in state["pending_delete"][:]:
        try:
            telegram.delete(message["chat_id"], message["message_id"])
        except (ProviderError, httpx.HTTPError):
            logger.warning("Deletion failed; will retry on the next poll")
        else:
            state["pending_delete"].remove(message)
            save(path, state)
    if stream is not None and state["active"] is None:
        text = f"{login} is live!\n{stream['title'][:500]}\nhttps://www.twitch.tv/{login}"
        message_id = telegram.send(chat_id, text)
        state["active"] = {
            "stream_id": stream["id"],
            "message_id": message_id,
            "chat_id": chat_id,
            "login": login,
        }
        save(path, state)


def main():
    load_dotenv()
    keys = (
        "TWITCH_CLIENT_ID",
        "TWITCH_CLIENT_SECRET",
        "TWITCH_LOGIN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    )
    if any(not os.getenv(key) or os.environ[key].startswith("replace-") for key in keys):
        raise SystemExit("Fill the required variables in .env using .env.example")
    interval = int(os.getenv("POLL_SECONDS", "60"))
    if interval < 10:
        raise SystemExit("POLL_SECONDS must be at least 10")
    path = Path(os.getenv("STATE_PATH", "data/state.json"))
    load(path)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with httpx.Client(timeout=15) as http:
        twitch = Twitch(http, os.environ["TWITCH_CLIENT_ID"], os.environ["TWITCH_CLIENT_SECRET"])
        telegram = Telegram(http, os.environ["TELEGRAM_BOT_TOKEN"])
        while True:
            try:
                poll(
                    twitch,
                    telegram,
                    path,
                    os.environ["TWITCH_LOGIN"],
                    os.environ["TELEGRAM_CHAT_ID"],
                )
            except (httpx.HTTPError, ProviderError, KeyError, TypeError) as exc:
                logger.warning("Poll failed (%s); state retained", type(exc).__name__)
            time.sleep(interval)


if __name__ == "__main__":
    main()
