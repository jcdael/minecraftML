from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from agent import SessionAgent


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BRAIN_DATA_DIR", ROOT / "data"))
agent = SessionAgent(DATA_DIR)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def handle(message: dict[str, Any]) -> None:
    kind = message.get("kind")
    payload = message.get("payload") or {}

    if kind == "adapter_disconnect":
        agent.on_adapter_disconnect()
        return

    if kind == "goal":
        active_id = agent.active_action_id()
        if active_id:
            agent.request_cancel_active("new_goal")
            emit({"type": "cancel", "action_id": active_id})
        response = agent.set_goal(str(payload.get("text", "")))
        emit({"type": "control_response", "message": response})
        return

    message_type = payload.get("type")
    if message_type == "observation":
        if agent.active_action_id():
            return
        next_step = agent.next_action(payload.get("state") or {})
        if next_step is None:
            return
        action_id, action = next_step
        emit({"type": "action", "action_id": action_id, "action": action})
        return

    if message_type == "result":
        agent.on_result(payload)
        return

    if message_type == "cancel_ack":
        agent.on_cancel_ack(payload)
        return

    if message_type == "event" and payload.get("event") == "death":
        agent.on_death(payload.get("action_id"))


for line in sys.stdin:
    try:
        raw = line.strip()
        if raw:
            handle(json.loads(raw))
    except Exception as error:
        emit({"type": "worker_error", "message": str(error)})
