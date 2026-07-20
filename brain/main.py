from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

import websockets

from agent import SessionAgent
from protocol import PROTOCOL_VERSION, validate_message

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BRAIN_DATA_DIR", ROOT / "data"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("BRAIN_PORT", "8765"))

agent = SessionAgent(DATA_DIR)
print(f"Minecraft AI brain initialized with data dir {DATA_DIR}", flush=True)


ADAPTER_RUNTIME_MESSAGES = {"observation", "result", "cancel_ack", "event"}


class AdapterSessionRegistry:
    def __init__(self) -> None:
        self.websocket: Any | None = None
        self.adapter_id: str | None = None
        self.session_id: str | None = None

    def register(self, websocket: Any, message: dict[str, Any]) -> bool:
        if self.websocket is not None and self.websocket is not websocket:
            return False
        self.websocket = websocket
        self.adapter_id = str(message["adapter_id"])
        self.session_id = str(message["session_id"])
        return True

    def is_active(self, websocket: Any) -> bool:
        return self.websocket is websocket

    def disconnect(self, websocket: Any) -> bool:
        if not self.is_active(websocket):
            return False
        self.websocket = None
        self.adapter_id = None
        self.session_id = None
        agent.on_adapter_disconnect()
        return True

    def active_websocket(self) -> Any | None:
        return self.websocket


adapter_sessions = AdapterSessionRegistry()


async def send_json(websocket: Any, payload: dict[str, Any]) -> None:
    payload.setdefault("protocol_version", PROTOCOL_VERSION)
    validation = validate_message(payload, direction="brain_to_adapter")
    if not validation.ok:
        await websocket.send(
            json.dumps(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "error",
                    "code": validation.code,
                    "message": validation.message,
                },
                separators=(",", ":"),
            )
        )
        return
    await websocket.send(json.dumps(payload, separators=(",", ":")))


async def send_action(websocket: Any, action_id: str, action: dict[str, Any]) -> None:
    await send_json(websocket, {"type": "action", "action_id": action_id, "action": action})


async def send_cancel(websocket: Any, action_id: str) -> None:
    await send_json(websocket, {"type": "cancel", "action_id": action_id})


async def handle_message(websocket: Any, message: dict[str, Any]) -> None:
    validation = validate_message(message, direction="adapter_to_brain")
    if not validation.ok:
        print(f"Rejected protocol message: {validation.code}: {validation.message}", file=sys.stderr)
        agent.memory.add_protocol_error(
            code=validation.code or "invalid_message",
            message=validation.message or "invalid message",
            action_id=message.get("action_id") if isinstance(message, dict) else None,
            payload=message if isinstance(message, dict) else {"payload": message},
        )
        return

    message_type = message.get("type")

    if message_type == "hello":
        if adapter_sessions.register(websocket, message):
            print(f"Adapter connected: {message}")
        else:
            agent.memory.add_protocol_error(
                code="adapter_session_conflict",
                message="hello received from second adapter while another adapter session is active",
                payload=message,
            )
            await websocket.close(code=4001, reason="active adapter session already registered")
        return

    if message_type in ADAPTER_RUNTIME_MESSAGES and not adapter_sessions.is_active(websocket):
        agent.memory.add_protocol_error(
            code="stale_adapter_session",
            message=f"{message_type} received from non-active adapter session",
            action_id=message.get("action_id") if isinstance(message, dict) else None,
            payload=message,
        )
        print(f"Rejected non-active adapter message: {message_type}", file=sys.stderr)
        return

    if message_type == "goal":
        active_id = agent.request_cancel_active("new_goal_started")
        if active_id and adapter_sessions.active_websocket() is not None:
            await send_cancel(adapter_sessions.active_websocket(), active_id)
        response = agent.set_goal(str(message.get("text", "")))
        print(response)
        return

    if message_type == "command":
        command = message.get("command")
        if command == "pause":
            response = agent.set_paused(True)
            active_id = agent.request_cancel_active("pause")
            if active_id and adapter_sessions.active_websocket() is not None:
                await send_cancel(adapter_sessions.active_websocket(), active_id)
        elif command == "resume":
            response = agent.set_paused(False)
        elif command == "status":
            response = agent.status()
        else:
            response = f"Unknown command: {command}"
        print(response)
        return

    if message_type == "observation":
        if agent.active_action_id():
            return
        state = message.get("state") or {}
        try:
            next_step = agent.next_action(state)
            if next_step is None:
                return
            action_id, action = next_step
            await send_action(websocket, action_id, action)
        except RuntimeError as error:
            print(f"Skipped observation while busy: {error}", file=sys.stderr)
        return

    if message_type == "result":
        skill_result = agent.on_result(message)
        status = skill_result.status if skill_result else "ignored"
        print(f"Action result: {status}; action_id={message.get('action_id')}")
        return

    if message_type == "cancel_ack":
        agent.on_cancel_ack(message)
        print(f"Cancel ack: action_id={message.get('action_id')} ok={message.get('ok')}")
        return

    if message_type == "event" and message.get("event") == "death":
        agent.on_death(message.get("action_id"))
        print("Death event recorded; agent paused")


async def handler(websocket: Any) -> None:
    try:
        async for raw in websocket:
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("Message must be a JSON object")
                await handle_message(websocket, message)
            except (json.JSONDecodeError, ValueError) as error:
                print(f"Ignored invalid JSON: {error}", file=sys.stderr)
    except websockets.ConnectionClosed:
        pass
    finally:
        if adapter_sessions.disconnect(websocket):
            print("Adapter disconnected")


async def main() -> None:
    print(f"Minecraft AI brain listening on ws://{HOST}:{PORT}", flush=True)
    async with websockets.serve(handler, HOST, PORT, max_size=8 * 1024 * 1024):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBrain stopped")
