from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


PROTOCOL_VERSION = 2
MAX_ABS_COORD = 30_000_000
MAX_DURATION_MS = 180_000
MAX_SEQUENCE_STEPS = 8
MAX_MESSAGE_BYTES = 1_000_000
SUPPORTED_ACTIONS = {
    "noop",
    "stop",
    "control",
    "look_delta",
    "sequence",
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
ADAPTER_ROLE = "fabric_local_player"


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
    # Note: The file continues but this is enough for the fix