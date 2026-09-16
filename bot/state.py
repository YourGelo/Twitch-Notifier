import json
from pathlib import Path


def load(path: Path):
    if not path.exists():
        return {"active": None, "pending_delete": []}
    # Invalid state stops the bot instead of silently creating duplicate posts.
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("pending_delete"), list):
        raise ValueError("Invalid state file")
    active = state.get("active")
    for message in state["pending_delete"] + ([active] if active is not None else []):
        if not isinstance(message, dict) or not all(
            key in message for key in ("stream_id", "message_id", "chat_id", "login")
        ):
            raise ValueError("Invalid saved message")
    return state


def save(path: Path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)
