from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Iterable


VOLATILE_KEYS = {"action_id", "elapsed_ms", "timestamp", "timestamp_ms"}
TRACE_SCHEMA_VERSION = "minecraft_ml_trace.v2"


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS and item is not None
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, float):
        return round(value, 3)
    return value


def record_step(
    observation: dict[str, Any],
    action: dict[str, Any] | None,
    result: dict[str, Any] | None = None,
    *,
    expected_state_transition: dict[str, Any] | None = None,
    expected_terminal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "observation": normalize(observation),
        "selected_action": normalize(action),
        "adapter_result": normalize(result),
        "expected_state_transition": normalize(expected_state_transition),
        "expected_terminal": normalize(expected_terminal),
    }


def save_trace(path: Path, steps: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": TRACE_SCHEMA_VERSION, "frames": [normalize(step) for step in steps]},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def load_trace(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = data.get("frames")
    if frames is None:
        frames = data.get("steps")
    if not isinstance(frames, list):
        raise ValueError("trace must contain a frames array")
    return [_upgrade_frame(frame) for frame in frames]


def replay_actions(agent: Any, steps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    actual: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        frame = _upgrade_frame(step)
        observation = deepcopy(frame["observation"])
        lifecycle_event = frame.get("lifecycle")
        if isinstance(lifecycle_event, dict) and lifecycle_event.get("event") == "death":
            agent.on_death(lifecycle_event.get("action_id") or getattr(agent, "pending_action_id", None))

        expected_action = frame.get("selected_action")
        decision = agent.next_action(observation)
        action = decision[1] if decision is not None else None
        action_id = decision[0] if decision is not None else None
        normalized_action = normalize(action)
        actual.append({"expected": expected_action, "actual": normalized_action})
        if normalized_action != expected_action:
            raise AssertionError(
                f"trace frame {index} action mismatch: expected {expected_action}, got {normalized_action}"
            )

        post_action_event = frame.get("post_action_event")
        if isinstance(post_action_event, dict) and post_action_event.get("event") == "death":
            agent.on_death(post_action_event.get("action_id") or action_id)

        result_payload = frame.get("adapter_result")
        skill_result = None
        if result_payload is not None:
            if action_id is None:
                raise AssertionError(f"trace frame {index} supplied an adapter result but no action was selected")
            replay_result = _result_for_action(result_payload, action_id, observation)
            skill_result = agent.on_result(replay_result)

        _assert_transition(agent, frame.get("expected_state_transition"), skill_result, index)
        _assert_terminal(agent, frame.get("expected_terminal"), index)
    return actual


def _upgrade_frame(frame: dict[str, Any]) -> dict[str, Any]:
    upgraded = dict(frame)
    if "selected_action" not in upgraded and "action" in upgraded:
        upgraded["selected_action"] = upgraded.get("action")
    if "adapter_result" not in upgraded and "result" in upgraded:
        upgraded["adapter_result"] = upgraded.get("result")
    return upgraded


def _result_for_action(payload: dict[str, Any], action_id: str, before_state: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    result.setdefault("protocol_version", 1)
    result.setdefault("type", "result")
    result["action_id"] = action_id
    result.setdefault("elapsed_ms", 10)
    result.setdefault("before_state", before_state)
    result.setdefault("after_state", before_state)
    lifecycle = result.get("lifecycle")
    if isinstance(lifecycle, dict):
        lifecycle["action_id"] = action_id
        _stamp_action_id(lifecycle, action_id)
    return result


def _stamp_action_id(value: Any, action_id: str) -> None:
    if isinstance(value, dict):
        if "action_id" in value:
            value["action_id"] = action_id
        for child in value.values():
            _stamp_action_id(child, action_id)
    elif isinstance(value, list):
        for child in value:
            _stamp_action_id(child, action_id)


def _assert_transition(agent: Any, expected: dict[str, Any] | None, skill_result: Any, index: int) -> None:
    if not expected:
        return
    if "skill_result" in expected:
        expected_result = expected["skill_result"]
        if skill_result is None:
            raise AssertionError(f"trace frame {index} expected a skill result")
        if skill_result.status != expected_result.get("status"):
            raise AssertionError(
                f"trace frame {index} skill status mismatch: expected {expected_result.get('status')}, "
                f"got {skill_result.status}"
            )
        expected_code = expected_result.get("failure_code")
        if expected_code != skill_result.failure_code:
            raise AssertionError(
                f"trace frame {index} failure code mismatch: expected {expected_code}, "
                f"got {skill_result.failure_code}"
            )
    if "active_action_id" in expected:
        active_action_id = agent.active_action_id() if hasattr(agent, "active_action_id") else None
        if active_action_id != expected["active_action_id"]:
            raise AssertionError(
                f"trace frame {index} active action mismatch: expected {expected['active_action_id']}, "
                f"got {active_action_id}"
            )
    if "paused" in expected and bool(getattr(agent, "paused", False)) != bool(expected["paused"]):
        raise AssertionError(f"trace frame {index} paused mismatch")
    if "completed" in expected and bool(getattr(agent, "completed", False)) != bool(expected["completed"]):
        raise AssertionError(f"trace frame {index} completed mismatch")
    if "skill_attempt_count" in expected and hasattr(agent, "memory"):
        count = agent.memory.count()
        if count != int(expected["skill_attempt_count"]):
            raise AssertionError(
                f"trace frame {index} attempt count mismatch: expected {expected['skill_attempt_count']}, got {count}"
            )


def _assert_terminal(agent: Any, expected: dict[str, Any] | None, index: int) -> None:
    if not expected:
        return
    row = agent.memory.connection.execute(
        "SELECT outcome, evidence_json, final_inventory_json FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise AssertionError(f"trace frame {index} expected terminal run evidence but no run exists")
    outcome, evidence_json, inventory_json = row
    if outcome != expected.get("outcome"):
        raise AssertionError(f"trace frame {index} terminal outcome mismatch: expected {expected.get('outcome')}, got {outcome}")
    evidence = json.loads(evidence_json or "{}")
    inventory = json.loads(inventory_json or "{}")
    if "failure_code" in expected and evidence.get("failure_code") != expected["failure_code"]:
        raise AssertionError(
            f"trace frame {index} terminal failure mismatch: expected {expected['failure_code']}, "
            f"got {evidence.get('failure_code')}"
        )
    for item, count in (expected.get("inventory") or {}).items():
        if int(inventory.get(item, 0)) != int(count):
            raise AssertionError(
                f"trace frame {index} inventory mismatch for {item}: expected {count}, got {inventory.get(item, 0)}"
            )
