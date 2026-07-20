from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


PROTOCOL_VERSION = 1
MAX_ABS_COORD = 30_000_000
MAX_DURATION_MS = 180_000
MAX_SEQUENCE_STEPS = 8
MAX_MESSAGE_BYTES = 1_000_000
SUPPORTED_ACTIONS = {
    "noop",
    "stop",
    "control",
    "look_delta",
    "goto",
    "goto_relative",
    "mine_nearest",
    "equip",
    "eat",
    "craft",
    "place_block",
    "smelt",
}
LIFECYCLE_EVENT_NAMES = {
    "abort_requested",
    "cleanup_started",
    "cleanup_completed",
    "execution_settled",
    "post_stop_probe_completed",
    "terminal_result",
}
LIFECYCLE_ORDER = [
    "abort_requested",
    "cleanup_started",
    "cleanup_completed",
    "execution_settled",
    "post_stop_probe_completed",
    "terminal_result",
]
REQUIRED_LIFECYCLE_EVENTS = {"execution_settled", "post_stop_probe_completed", "terminal_result"}
DANGERS = {"drowning", "fire", "fall", None}
COMMANDS = {"pause", "resume", "status"}
ADAPTER_ROLE = "mineflayer_adapter"


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    code: str | None = None
    message: str | None = None


def _number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError("invalid_number", f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolError("invalid_number", f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise ProtocolError("number_out_of_range", f"{field} is below {minimum}")
    if maximum is not None and result > maximum:
        raise ProtocolError("number_out_of_range", f"{field} is above {maximum}")
    return result


def _string(value: Any, field: str, *, max_length: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ProtocolError("invalid_string", f"{field} must be a non-empty string")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError("invalid_bool", f"{field} must be a boolean")
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("invalid_object", f"{field} must be an object")
    return value


def _array(value: Any, field: str, *, max_length: int = 256) -> list[Any]:
    if not isinstance(value, list):
        raise ProtocolError("invalid_array", f"{field} must be an array")
    if len(value) > max_length:
        raise ProtocolError("array_too_large", f"{field} is too large")
    return value


def _check_allowed_keys(value: dict[str, Any], allowed: set[str], field: str = "message") -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ProtocolError("unknown_field", f"{field} has unknown fields: {sorted(unknown)}")


ACTIVITY_FIELDS = ("action_running", "movement_active", "pathfinder_active", "digging_active", "container_active")


def _validate_activity_state(value: Any, field: str) -> None:
    state = _object(value, field)
    for key in ACTIVITY_FIELDS:
        _bool(state.get(key), f"{field}.{key}")


def _activity_any(state: dict[str, Any]) -> bool:
    return any(bool(state.get(key)) for key in ACTIVITY_FIELDS)


def _validate_lifecycle(
    value: Any,
    field: str = "lifecycle",
    *,
    expected_action_id: str | None = None,
    result_ok: bool | None = None,
    result_code: str | None = None,
    require_complete: bool = False,
) -> None:
    lifecycle = _object(value, field)
    _check_allowed_keys(
        lifecycle,
        {
            "action_id",
            "started",
            "abort_requested",
            "cleanup_started",
            "cleanup_completed",
            "execution_settled",
            "terminal_result",
            "final_activity_state",
            "unsafe_continuation",
            "faulted",
            "fault_reason",
            "events",
        },
        field,
    )
    action_id = _string(lifecycle.get("action_id"), f"{field}.action_id", max_length=64)
    if expected_action_id is not None and action_id != expected_action_id:
        raise ProtocolError("mismatched_lifecycle_action_id", f"{field}.action_id must match action_id")
    started_at = _number(lifecycle.get("started"), f"{field}.started", minimum=0)
    for key in ("abort_requested", "cleanup_started", "cleanup_completed"):
        if lifecycle.get(key) is not None:
            _number(lifecycle.get(key), f"{field}.{key}", minimum=0)
    settled = lifecycle.get("execution_settled")
    settled_at: float | None = None
    if settled is not None:
        settled_obj = _object(settled, f"{field}.execution_settled")
        settled_at = _number(settled_obj.get("at"), f"{field}.execution_settled.at", minimum=0)
        _bool(settled_obj.get("settled"), f"{field}.execution_settled.settled")
        _bool(settled_obj.get("ok"), f"{field}.execution_settled.ok")
    terminal = lifecycle.get("terminal_result")
    terminal_at: float | None = None
    if terminal is not None:
        terminal_obj = _object(terminal, f"{field}.terminal_result")
        terminal_at = _number(terminal_obj.get("at"), f"{field}.terminal_result.at", minimum=0)
        terminal_ok = _bool(terminal_obj.get("ok"), f"{field}.terminal_result.ok")
        if terminal_obj.get("code") is not None:
            _string(terminal_obj.get("code"), f"{field}.terminal_result.code", max_length=64)
        if result_ok is not None and terminal_ok is not result_ok:
            raise ProtocolError("mismatched_lifecycle_terminal", f"{field}.terminal_result.ok must match result.ok")
        if result_code is not None and terminal_obj.get("code") != result_code:
            raise ProtocolError("mismatched_lifecycle_terminal", f"{field}.terminal_result.code must match result.code")
        if result_code is None and result_ok is True and terminal_obj.get("code") is not None:
            raise ProtocolError("mismatched_lifecycle_terminal", f"{field}.terminal_result.code must be null for successful result")
    final = lifecycle.get("final_activity_state")
    final_states: list[dict[str, Any]] = []
    if final is not None:
        final_obj = _object(final, f"{field}.final_activity_state")
        _validate_activity_state(final_obj.get("first"), f"{field}.final_activity_state.first")
        _validate_activity_state(final_obj.get("final"), f"{field}.final_activity_state.final")
        final_states.extend([final_obj["first"], final_obj["final"]])
        if final_obj.get("delayed") is not None:
            _validate_activity_state(final_obj.get("delayed"), f"{field}.final_activity_state.delayed")
            final_states.append(final_obj["delayed"])
        elif require_complete:
            raise ProtocolError("missing_lifecycle_final_state", f"{field}.final_activity_state.delayed is required")
    elif require_complete:
        raise ProtocolError("missing_lifecycle_final_state", f"{field}.final_activity_state is required")
    unsafe_continuation = _bool(lifecycle.get("unsafe_continuation"), f"{field}.unsafe_continuation")
    if final_states and unsafe_continuation != any(_activity_any(state) for state in final_states):
        raise ProtocolError("mismatched_unsafe_continuation", f"{field}.unsafe_continuation must match final activity state")
    if lifecycle.get("faulted") is not None:
        _bool(lifecycle.get("faulted"), f"{field}.faulted")
    if lifecycle.get("fault_reason") is not None:
        _string(lifecycle.get("fault_reason"), f"{field}.fault_reason", max_length=128)
    events = _array(lifecycle.get("events", []), f"{field}.events", max_length=128)
    seen: set[str] = set()
    previous_order = -1
    previous_at = started_at
    by_name: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(events):
        event_obj = _object(event, f"{field}.events[{index}]")
        name = _string(event_obj.get("name"), f"{field}.events[{index}].name", max_length=64)
        if name not in LIFECYCLE_EVENT_NAMES:
            raise ProtocolError("unknown_lifecycle_event", f"{field}.events[{index}].name is not supported")
        seq = event_obj.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq != index + 1:
            raise ProtocolError("invalid_lifecycle_sequence", f"{field}.events[{index}].seq must be contiguous from 1")
        event_at = _number(event_obj.get("at"), f"{field}.events[{index}].at", minimum=0)
        if name in seen:
            raise ProtocolError("duplicate_lifecycle_event", f"{field}.events[{index}].name is duplicated")
        seen.add(name)
        order = LIFECYCLE_ORDER.index(name)
        if order < previous_order:
            raise ProtocolError("misordered_lifecycle_event", f"{field}.events[{index}].name is out of order")
        previous_order = order
        if terminal_at is not None and (event_at < started_at or event_at > terminal_at):
            raise ProtocolError("lifecycle_event_outside_bounds", f"{field}.events[{index}].at is outside action bounds")
        if event_at < previous_at:
            raise ProtocolError("lifecycle_event_timestamp_reversed", f"{field}.events[{index}].at is before previous lifecycle event")
        previous_at = event_at
        by_name[name] = event_obj
    if require_complete:
        missing = REQUIRED_LIFECYCLE_EVENTS - seen
        if missing:
            raise ProtocolError("missing_lifecycle_event", f"{field}.events missing required events: {sorted(missing)}")
        if settled is None:
            raise ProtocolError("execution_settlement_missing", f"{field}.execution_settled is required")
        if terminal is None:
            raise ProtocolError("terminal_result_missing", f"{field}.terminal_result is required")
    if "cleanup_completed" in seen and "cleanup_started" not in seen:
        raise ProtocolError("misordered_lifecycle_event", f"{field}.cleanup_completed requires cleanup_started")
    if "cleanup_started" in seen and "cleanup_completed" not in seen:
        raise ProtocolError("misordered_lifecycle_event", f"{field}.cleanup_started requires cleanup_completed")
    if lifecycle.get("abort_requested") is not None and "abort_requested" not in seen:
        raise ProtocolError("missing_lifecycle_event", f"{field}.abort_requested requires an abort_requested event")
    for key in ("abort_requested", "cleanup_started", "cleanup_completed"):
        if key in by_name and lifecycle.get(key) != by_name[key].get("at"):
            raise ProtocolError("mismatched_lifecycle_timestamp", f"{field}.{key} must match its event timestamp")
    if settled_at is not None:
        if started_at > settled_at:
            raise ProtocolError("out_of_order_execution_settled", f"{field}.execution_settled is before lifecycle start")
        if "execution_settled" in by_name and by_name["execution_settled"].get("at") != settled_at:
            raise ProtocolError("mismatched_lifecycle_timestamp", f"{field}.execution_settled.at must match its event")
    if terminal_at is not None:
        if started_at > terminal_at or (settled_at is not None and settled_at > terminal_at):
            raise ProtocolError("out_of_order_terminal_result", f"{field}.terminal_result is out of order")
        if "terminal_result" in by_name and by_name["terminal_result"].get("at") != terminal_at:
            raise ProtocolError("mismatched_lifecycle_timestamp", f"{field}.terminal_result.at must match its event")
    if "post_stop_probe_completed" in by_name:
        probe_at = _number(by_name["post_stop_probe_completed"].get("at"), f"{field}.post_stop_probe_completed.at", minimum=0)
        if settled_at is not None and probe_at < settled_at:
            raise ProtocolError("out_of_order_post_stop_probe", f"{field}.post_stop_probe_completed is before settlement")
        if terminal_at is not None and terminal_at < probe_at:
            raise ProtocolError("terminal_before_post_stop_probe", f"{field}.terminal_result is before post-stop probe")
        if by_name["post_stop_probe_completed"].get("unsafe_continuation") is not None:
            probe_unsafe = _bool(
                by_name["post_stop_probe_completed"].get("unsafe_continuation"),
                f"{field}.post_stop_probe_completed.unsafe_continuation",
            )
            if probe_unsafe is not unsafe_continuation:
                raise ProtocolError("mismatched_unsafe_continuation", f"{field}.post_stop_probe_completed unsafe flag must match lifecycle")


def validate_action(action: Any, *, nested: bool = False) -> ValidationResult:
    try:
        _validate_action_or_raise(action, nested=nested)
        return ValidationResult(True)
    except ProtocolError as error:
        return ValidationResult(False, error.code, str(error))


def _validate_action_or_raise(action: Any, *, nested: bool = False) -> None:
    if not isinstance(action, dict):
        raise ProtocolError("invalid_action", "action must be an object")
    kind = action.get("kind")
    if kind not in SUPPORTED_ACTIONS:
        raise ProtocolError("unsupported_action", f"unsupported action kind: {kind}")

    if kind == "noop":
        _check_allowed_keys(action, {"kind"}, "action")
        return

    if kind == "stop":
        _check_allowed_keys(action, {"kind", "reason"}, "action")
        if action.get("reason") is not None:
            _string(action.get("reason"), "reason", max_length=128)
        return

    if kind == "control":
        _check_allowed_keys(action, {"kind", "states", "duration_ms", "timeout_ms"}, "action")
        states = action.get("states")
        if not isinstance(states, dict):
            raise ProtocolError("invalid_states", "control.states must be an object")
        allowed = {"forward", "back", "left", "right", "jump", "sprint", "sneak"}
        unknown = set(states) - allowed
        if unknown:
            raise ProtocolError("unknown_control_state", f"unknown control states: {sorted(unknown)}")
        if not states or not all(isinstance(value, bool) for value in states.values()):
            raise ProtocolError("invalid_states", "control states must be booleans")
        _number(action.get("duration_ms", 250), "duration_ms", minimum=1, maximum=MAX_DURATION_MS)
        return

    if kind == "look_delta":
        _check_allowed_keys(action, {"kind", "yaw_delta", "pitch_delta", "timeout_ms"}, "action")
        _number(action.get("yaw_delta", 0), "yaw_delta", minimum=-6.2832, maximum=6.2832)
        _number(action.get("pitch_delta", 0), "pitch_delta", minimum=-3.1416, maximum=3.1416)
        return

    if kind == "goto":
        _check_allowed_keys(action, {"kind", "x", "y", "z", "radius", "timeout_ms"}, "action")
        for field in ("x", "y", "z"):
            _number(action.get(field), field, minimum=-MAX_ABS_COORD, maximum=MAX_ABS_COORD)
        _number(action.get("radius", 1), "radius", minimum=0.5, maximum=16)
        return

    if kind == "goto_relative":
        _check_allowed_keys(action, {"kind", "dx", "dy", "dz", "radius", "timeout_ms"}, "action")
        for field in ("dx", "dy", "dz"):
            _number(action.get(field, 0), field, minimum=-64, maximum=64)
        _number(action.get("radius", 1), "radius", minimum=0.5, maximum=16)
        return

    if kind == "mine_nearest":
        _check_allowed_keys(action, {"kind", "block", "max_distance", "timeout_ms"}, "action")
        _string(action.get("block"), "block")
        _number(action.get("max_distance", 24), "max_distance", minimum=1, maximum=64)
        _number(action.get("timeout_ms", 20_000), "timeout_ms", minimum=1, maximum=MAX_DURATION_MS)
        return

    if kind == "equip":
        _check_allowed_keys(action, {"kind", "item", "destination", "timeout_ms"}, "action")
        _string(action.get("item"), "item")
        destination = action.get("destination", "hand")
        if destination not in {"hand", "off-hand", "head", "torso", "legs", "feet"}:
            raise ProtocolError("invalid_destination", "unsupported equipment destination")
        return

    if kind == "eat":
        _check_allowed_keys(action, {"kind", "item", "timeout_ms"}, "action")
        if action.get("item") is not None:
            _string(action.get("item"), "item")
        _number(action.get("timeout_ms", 8_000), "timeout_ms", minimum=1, maximum=MAX_DURATION_MS)
        return

    if kind == "craft":
        _check_allowed_keys(action, {"kind", "item", "count", "use_crafting_table", "timeout_ms"}, "action")
        item = _string(action.get("item"), "item")
        if item not in {"oak_planks", "crafting_table", "stick", "wooden_pickaxe", "stone_pickaxe", "furnace"}:
            raise ProtocolError("unsupported_recipe", "craft action is limited to the bootstrap recipe set")
        _number(action.get("count", 1), "count", minimum=1, maximum=64)
        if action.get("use_crafting_table") is not None:
            _bool(action.get("use_crafting_table"), "use_crafting_table")
        _number(action.get("timeout_ms", 10_000), "timeout_ms", minimum=1, maximum=MAX_DURATION_MS)
        return

    if kind == "place_block":
        _check_allowed_keys(action, {"kind", "item", "timeout_ms"}, "action")
        item = _string(action.get("item"), "item")
        if item not in {"crafting_table", "furnace"}:
            raise ProtocolError("unsupported_place_block", "place_block is limited to crafting_table and furnace")
        _number(action.get("timeout_ms", 8_000), "timeout_ms", minimum=1, maximum=MAX_DURATION_MS)
        return

    if kind == "smelt":
        _check_allowed_keys(action, {"kind", "input", "fuel", "output", "count", "timeout_ms"}, "action")
        if _string(action.get("input"), "input") != "raw_iron":
            raise ProtocolError("unsupported_smelt_input", "smelt supports only raw_iron")
        if _string(action.get("fuel"), "fuel") != "coal":
            raise ProtocolError("unsupported_smelt_fuel", "smelt supports only coal fuel")
        if _string(action.get("output"), "output") != "iron_ingot":
            raise ProtocolError("unsupported_smelt_output", "smelt supports only iron_ingot output")
        _number(action.get("count", 1), "count", minimum=1, maximum=8)
        _number(action.get("timeout_ms", 60_000), "timeout_ms", minimum=1, maximum=MAX_DURATION_MS)
        return

    if kind == "sequence" or (nested and isinstance(action.get("steps"), list)):
        raise ProtocolError("unsupported_action", "nested sequences are not supported")


def validate_message(message: Any, *, direction: str) -> ValidationResult:
    try:
        _validate_message_or_raise(message, direction=direction)
        return ValidationResult(True)
    except ProtocolError as error:
        return ValidationResult(False, error.code, str(error))


def _validate_message_or_raise(message: Any, *, direction: str) -> None:
    if not isinstance(message, dict):
        raise ProtocolError("invalid_message", "message must be an object")
    try:
        size = len(json.dumps(message, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        raise ProtocolError("invalid_message", "message must be JSON serializable")
    if size > MAX_MESSAGE_BYTES:
        raise ProtocolError("payload_too_large", "message payload is too large")
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol_version", "unsupported protocol version")
    message_type = message.get("type")

    if direction == "brain_to_adapter":
        if message_type == "action":
            _check_allowed_keys(message, {"protocol_version", "type", "action_id", "action"})
            _string(message.get("action_id"), "action_id", max_length=64)
            _validate_action_or_raise(message.get("action"), nested=False)
            return
        if message_type == "cancel":
            _check_allowed_keys(message, {"protocol_version", "type", "action_id"})
            _string(message.get("action_id"), "action_id", max_length=64)
            return
        raise ProtocolError("unsupported_message_type", f"unsupported message type: {message_type}")

    if direction == "adapter_to_brain":
        if message_type == "hello":
            _check_allowed_keys(message, {"protocol_version", "type", "client", "adapter_version", "role", "adapter_id", "session_id"})
            _string(message.get("client"), "client", max_length=128)
            if message.get("role") != ADAPTER_ROLE:
                raise ProtocolError("invalid_adapter_role", "hello.role must identify the mineflayer adapter")
            _string(message.get("adapter_id"), "adapter_id", max_length=128)
            _string(message.get("session_id"), "session_id", max_length=128)
            if message.get("adapter_version") is not None:
                _string(message.get("adapter_version"), "adapter_version", max_length=128)
            return
        if message_type == "observation":
            _check_allowed_keys(message, {"protocol_version", "type", "request_id", "timestamp_ms", "state"})
            _string(message.get("request_id"), "request_id", max_length=64)
            _number(message.get("timestamp_ms"), "timestamp_ms", minimum=0)
            _validate_observation_state_or_raise(message.get("state"))
            return
        if message_type == "goal":
            _check_allowed_keys(message, {"protocol_version", "type", "text", "requested_by"})
            _string(message.get("text"), "text", max_length=240)
            if message.get("requested_by") is not None:
                _string(message.get("requested_by"), "requested_by", max_length=64)
            return
        if message_type == "command":
            _check_allowed_keys(message, {"protocol_version", "type", "command", "requested_by"})
            if message.get("command") not in COMMANDS:
                raise ProtocolError("unsupported_command", "unsupported command")
            if message.get("requested_by") is not None:
                _string(message.get("requested_by"), "requested_by", max_length=64)
            return
        if message_type == "event":
            _check_allowed_keys(message, {"protocol_version", "type", "event", "timestamp_ms", "action_id"})
            if message.get("event") != "death":
                raise ProtocolError("unsupported_event", "unsupported event")
            if message.get("timestamp_ms") is not None:
                _number(message.get("timestamp_ms"), "timestamp_ms", minimum=0)
            _string(message.get("action_id"), "action_id", max_length=64)
            return
        if message_type == "result":
            _check_allowed_keys(
                message,
                {
                    "protocol_version",
                    "type",
                    "action_id",
                    "ok",
                    "elapsed_ms",
                    "before_state",
                    "after_state",
                    "code",
                    "error",
                    "detail",
                    "lifecycle",
                },
            )
            _string(message.get("action_id"), "action_id", max_length=64)
            if not isinstance(message.get("ok"), bool):
                raise ProtocolError("invalid_result", "result.ok must be a boolean")
            _number(message.get("elapsed_ms"), "elapsed_ms", minimum=0, maximum=MAX_DURATION_MS * 2)
            _validate_observation_state_or_raise(message.get("before_state"))
            _validate_observation_state_or_raise(message.get("after_state"))
            if message.get("code") is not None:
                _string(message.get("code"), "code", max_length=64)
            if message.get("error") is not None:
                _string(message.get("error"), "error", max_length=512)
            if message.get("lifecycle") is None:
                raise ProtocolError("missing_lifecycle", "result must include lifecycle")
            _validate_lifecycle(
                message.get("lifecycle"),
                expected_action_id=message.get("action_id"),
                result_ok=message.get("ok"),
                result_code=message.get("code"),
                require_complete=True,
            )
            return
        if message_type == "cancel_ack":
            _check_allowed_keys(
                message,
                {"protocol_version", "type", "action_id", "ok", "code", "after_state", "lifecycle"},
            )
            _string(message.get("action_id"), "action_id", max_length=64)
            if not isinstance(message.get("ok"), bool):
                raise ProtocolError("invalid_cancel_ack", "cancel_ack.ok must be a boolean")
            if message.get("code") is not None:
                _string(message.get("code"), "code", max_length=64)
            if message.get("ok") is True and message.get("after_state") is None:
                raise ProtocolError("missing_after_state", "successful cancel_ack must include after_state")
            if message.get("ok") is True and message.get("lifecycle") is None:
                raise ProtocolError("missing_lifecycle", "successful cancel_ack must include lifecycle")
            if message.get("after_state") is not None:
                _validate_observation_state_or_raise(message.get("after_state"))
            if message.get("lifecycle") is not None:
                _validate_lifecycle(
                    message.get("lifecycle"),
                    expected_action_id=message.get("action_id"),
                    require_complete=message.get("ok") is True,
                )
            return
        if message_type == "error":
            _check_allowed_keys(message, {"protocol_version", "type", "code", "message", "action_id"})
            _string(message.get("code"), "code", max_length=64)
            if message.get("message") is not None:
                _string(message.get("message"), "message", max_length=512)
            if message.get("action_id") is not None:
                _string(message.get("action_id"), "action_id", max_length=64)
            return
        raise ProtocolError("unsupported_message_type", f"unsupported message type: {message_type}")

    raise ProtocolError("invalid_direction", "unknown protocol direction")


def validate_observation_state(state: Any) -> ValidationResult:
    try:
        _validate_observation_state_or_raise(state)
        return ValidationResult(True)
    except ProtocolError as error:
        return ValidationResult(False, error.code, str(error))


def _validate_position(value: Any, field: str) -> None:
    position = _object(value, field)
    for axis in ("x", "y", "z"):
        _number(position.get(axis), f"{field}.{axis}", minimum=-MAX_ABS_COORD, maximum=MAX_ABS_COORD)


def _validate_inventory(items: Any) -> None:
    inventory = _array(items, "inventory", max_length=46)
    for index, item in enumerate(inventory):
        item_obj = _object(item, f"inventory[{index}]")
        _string(item_obj.get("name"), f"inventory[{index}].name", max_length=128)
        _number(item_obj.get("count"), f"inventory[{index}].count", minimum=0, maximum=64)
        _number(item_obj.get("slot"), f"inventory[{index}].slot", minimum=0, maximum=255)


def _validate_observation_state_or_raise(state: Any) -> None:
    state_obj = _object(state, "state")
    _validate_position(state_obj.get("position"), "position")
    if state_obj.get("velocity") is not None:
        _validate_position(state_obj.get("velocity"), "velocity")
    _number(state_obj.get("health"), "health", minimum=0, maximum=20)
    _number(state_obj.get("food"), "food", minimum=0, maximum=20)
    _validate_inventory(state_obj.get("inventory", []))
    nearby = _object(state_obj.get("nearby_blocks"), "nearby_blocks")
    counts = _object(nearby.get("counts", {}), "nearby_blocks.counts")
    if len(counts) > 512:
        raise ProtocolError("object_too_large", "nearby block counts too large")
    for name, count in counts.items():
        _string(name, "nearby block name", max_length=128)
        _number(count, f"nearby_blocks.counts.{name}", minimum=0, maximum=100000)
    _bool(state_obj.get("action_running"), "action_running")
    if state_obj.get("movement_active") is not None:
        _bool(state_obj.get("movement_active"), "movement_active")
    if state_obj.get("pathfinder_active") is not None:
        _bool(state_obj.get("pathfinder_active"), "pathfinder_active")
    if state_obj.get("digging_active") is not None:
        _bool(state_obj.get("digging_active"), "digging_active")
    if state_obj.get("container_active") is not None:
        _bool(state_obj.get("container_active"), "container_active")
    danger = state_obj.get("danger")
    if danger not in DANGERS:
        raise ProtocolError("invalid_danger", "unsupported danger value")
