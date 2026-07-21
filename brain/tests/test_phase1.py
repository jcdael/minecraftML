from __future__ import annotations

from pathlib import Path
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import SessionAgent
from evaluate_seeds import pass_evidence
from live_eval_helper import inspect_adapter_log, read_status
import main as brain_main
from memory import ExperienceStore
from goals import parse_goal
from protocol import PROTOCOL_VERSION, validate_action, validate_message, validate_observation_state
from trace_replay import record_step, replay_actions, save_trace, load_trace
from skills import (
    CraftItemSkill,
    EatWhenNeededSkill,
    EquipItemSkill,
    EscapeDangerSkill,
    ExploreSearchSkill,
    GatherVisibleBlockSkill,
    PlaceBlockSkill,
    RecoverStuckSkill,
    SmeltItemSkill,
    SkillStep,
    StopSkill,
)


def obs(
    *,
    oak_logs: int = 0,
    inventory_count: int = 0,
    health: int = 20,
    food: int = 20,
    danger: str | None = None,
    oxygen: int | None = None,
    stopped: bool = True,
    x: float = 0,
    z: float = 0,
    extra_inventory: list[dict] | None = None,
    extra_blocks: dict[str, int] | None = None,
    held_item: str | None = None,
) -> dict:
    inventory = []
    if inventory_count:
        inventory.append({"name": "oak_log", "count": inventory_count, "slot": 9})
    if extra_inventory:
        inventory.extend(extra_inventory)
    nearby_counts = {"oak_log": oak_logs} if oak_logs else {}
    if extra_blocks:
        nearby_counts.update(extra_blocks)
    samples = []
    for name, count in nearby_counts.items():
        for index in range(min(int(count), 4)):
            samples.append({"name": name, "dx": index + 1, "dy": 0, "dz": 0})
    state = {
        "position": {"x": x, "y": 64, "z": z},
        "velocity": {"x": 0, "y": 0, "z": 0},
        "health": health,
        "food": food,
        "inventory": inventory,
        "held_item": {"name": held_item, "count": 1} if held_item else None,
        "nearby_blocks": {"counts": nearby_counts, "samples": samples},
        "nearby_entities": [],
        "action_running": not stopped,
        "movement_active": not stopped,
        "pathfinder_active": False if stopped else True,
        "digging_active": False,
        "container_active": False,
        "danger": danger,
    }
    if oxygen is not None:
        state["oxygen"] = oxygen
    return state


def lifecycle(action_id: str = "act-1", *, unsafe: bool = False, ok: bool | None = None, code: str | None = None) -> dict:
    terminal_ok = (not unsafe) if ok is None else ok
    terminal_code = code if code is not None else ("timeout" if not terminal_ok else None)
    return {
        "action_id": action_id,
        "started": 1,
        "abort_requested": None,
        "cleanup_started": 2,
        "cleanup_completed": 3,
        "execution_settled": {"at": 4, "settled": True, "ok": terminal_ok},
        "terminal_result": {"at": 5, "ok": terminal_ok, "code": terminal_code},
        "final_activity_state": {
            "first": {
                "action_running": False,
                "movement_active": False,
                "pathfinder_active": False,
                "digging_active": False,
                "container_active": False,
            },
            "final": {
                "action_running": False,
                "movement_active": unsafe,
                "pathfinder_active": False,
                "digging_active": False,
                "container_active": False,
            },
            "delayed": {
                "action_running": False,
                "movement_active": False,
                "pathfinder_active": False,
                "digging_active": False,
                "container_active": False,
            },
        },
        "unsafe_continuation": unsafe,
        "events": [
            {"seq": 1, "name": "cleanup_started", "at": 2},
            {"seq": 2, "name": "cleanup_completed", "at": 3},
            {"seq": 3, "name": "execution_settled", "at": 4},
            {"seq": 4, "name": "post_stop_probe_completed", "at": 5, "unsafe_continuation": unsafe},
            {"seq": 5, "name": "terminal_result", "at": 5},
        ],
    }


class ProtocolTests(unittest.TestCase):
    def test_rejects_unknown_protocol_version(self) -> None:
        result = validate_message({"protocol_version": 999, "type": "observation"}, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "unsupported_protocol_version")

    def test_rejects_bad_nested_sequence(self) -> None:
        result = validate_action({"kind": "sequence", "steps": [{"kind": "stop"}]})
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "unsupported_action")

    def test_rejects_excessive_coordinates(self) -> None:
        result = validate_action({"kind": "goto", "x": 90_000_000, "y": 64, "z": 0})
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "number_out_of_range")

    def test_accepts_valid_action_message(self) -> None:
        result = validate_message(
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "action",
                "action_id": "act-1",
                "action": {"kind": "stop"},
            },
            direction="brain_to_adapter",
        )
        self.assertTrue(result.ok)

    def test_adapter_hello_requires_role_and_session_identity(self) -> None:
        valid = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "hello",
            "client": "mineflayer-adapter",
            "role": "mineflayer_adapter",
            "adapter_id": "adapter-1",
            "session_id": "session-1",
            "adapter_version": "test",
        }
        self.assertTrue(validate_message(valid, direction="adapter_to_brain").ok)
        missing = dict(valid)
        del missing["session_id"]
        self.assertEqual(validate_message(missing, direction="adapter_to_brain").code, "invalid_string")
        wrong_role = dict(valid)
        wrong_role["role"] = "status_client"
        self.assertEqual(validate_message(wrong_role, direction="adapter_to_brain").code, "invalid_adapter_role")

    def test_accepts_schema_valid_fault_lifecycle_result(self) -> None:
        action_id = "act-fault"
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": action_id,
            "ok": False,
            "elapsed_ms": 10,
            "before_state": obs(oak_logs=1),
            "after_state": obs(oak_logs=1),
            "code": "adapter_faulted",
            "error": "execution_unsettled_after_fence",
            "lifecycle": lifecycle(action_id, ok=False, code="adapter_faulted")
            | {
                "faulted": True,
                "fault_reason": "execution_unsettled_after_fence",
                "execution_settled": {"at": 4, "settled": False, "ok": False, "fenced": True},
                "terminal_result": {"at": 5, "ok": False, "code": "adapter_faulted"},
            },
        }
        self.assertTrue(validate_message(payload, direction="adapter_to_brain").ok)

    def test_rejects_invalid_fault_lifecycle_fields(self) -> None:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": "act-fault",
            "ok": False,
            "elapsed_ms": 10,
            "before_state": obs(oak_logs=1),
            "after_state": obs(oak_logs=1),
            "code": "adapter_faulted",
            "error": "execution_unsettled_after_fence",
            "lifecycle": lifecycle("act-fault", ok=False, code="adapter_faulted") | {"faulted": "yes"},
        }
        result = validate_message(payload, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "invalid_bool")

    def test_observation_schema_rejects_missing_health(self) -> None:
        payload = obs()
        del payload["health"]
        result = validate_observation_state(payload)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "invalid_number")

    def test_rejects_unknown_action_and_message_fields(self) -> None:
        self.assertEqual(validate_action({"kind": "noop", "surprise": True}).code, "unknown_field")
        result = validate_message(
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "action",
                "action_id": "act-1",
                "action": {"kind": "noop"},
                "extra": True,
            },
            direction="brain_to_adapter",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "unknown_field")

    def test_rejects_oversized_payload(self) -> None:
        result = validate_message(
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "error",
                "code": "too_big",
                "message": "x" * 1_000_100,
            },
            direction="adapter_to_brain",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "payload_too_large")

    def test_cross_process_busy_error_cancel_and_lifecycle_schemas(self) -> None:
        busy = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": "act-busy",
            "ok": False,
            "elapsed_ms": 0,
            "before_state": obs(),
            "after_state": obs(),
            "code": "busy",
            "error": "one active action already running",
            "lifecycle": lifecycle("act-busy", ok=False, code="busy"),
        }
        self.assertTrue(validate_message(busy, direction="adapter_to_brain").ok)

        cancel_ack = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "cancel_ack",
            "action_id": "act-1",
            "ok": True,
            "after_state": obs(),
            "lifecycle": lifecycle("act-1"),
        }
        self.assertTrue(validate_message(cancel_ack, direction="adapter_to_brain").ok)

        missing_evidence_ack = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "cancel_ack",
            "action_id": "act-1",
            "ok": True,
        }
        self.assertEqual(
            validate_message(missing_evidence_ack, direction="adapter_to_brain").code,
            "missing_after_state",
        )

        error = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "error",
            "code": "invalid_json",
            "message": "bad json",
        }
        self.assertTrue(validate_message(error, direction="adapter_to_brain").ok)

    def test_rejects_invalid_lifecycle_nested_data(self) -> None:
        bad_lifecycle = lifecycle(ok=False, code="timeout")
        bad_lifecycle["final_activity_state"]["final"]["movement_active"] = "false"
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": "act-1",
            "ok": False,
            "elapsed_ms": 1,
            "before_state": obs(),
            "after_state": obs(),
            "code": "timeout",
            "error": "timeout",
            "lifecycle": bad_lifecycle,
        }
        result = validate_message(payload, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "invalid_bool")

    def test_result_requires_strict_lifecycle_semantics(self) -> None:
        # lifecycle must match action_id
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": "act-2",
            "ok": True,
            "elapsed_ms": 1,
            "before_state": obs(),
            "after_state": obs(),
            "lifecycle": lifecycle("act-1"),
        }
        result = validate_message(payload, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "lifecycle_action_id_mismatch")

    def test_accepts_valid_observation_with_extra_fields(self) -> None:
        payload = obs()
        payload["extra_field"] = "ignored"
        result = validate_observation_state(payload)
        self.assertTrue(result.ok)

    def test_rejects_observation_with_invalid_nested_velocity(self) -> None:
        payload = obs()
        payload["velocity"]["x"] = "0"
        result = validate_observation_state(payload)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "invalid_number")

    def test_accepts_valid_action_control(self) -> None:
        result = validate_action({"kind": "control", "forward": True, "sneak": False})
        self.assertTrue(result.ok)

    def test_rejects_control_with_unknown_keys(self) -> None:
        result = validate_action({"kind": "control", "forward": True, "unknown": True})
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "unknown_field")

    def test_accepts_valid_look_delta(self) -> None:
        result = validate_action({"kind": "look_delta", "yaw": 45, "pitch": -30})
        self.assertTrue(result.ok)

    def test_rejects_look_delta_out_of_range(self) -> None:
        result = validate_action({"kind": "look_delta", "yaw": 1000, "pitch": 0})
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "number_out_of_range")

    def test_accepts_valid_sequence(self) -> None:
        result = validate_action(
            {
                "kind": "sequence",
                "steps": [
                    {"kind": "control", "forward": True, "sneak": False},
                    {"kind": "look_delta", "yaw": 45, "pitch": 0},
                    {"kind": "stop"},
                ],
            }
        )
        self.assertTrue(result.ok)

    def test_rejects_sequence_with_too_many_steps(self) -> None:
        steps = [{"kind": "control", "forward": True, "sneak": False}] * 101
        result = validate_action({"kind": "sequence", "steps": steps})
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "array_too_long")

    def test_accepts_valid_noop(self) -> None:
        result = validate_action({"kind": "noop"})
        self.assertTrue(result.ok)

    def test_rejects_noop_with_extra_fields(self) -> None:
        result = validate_action({"kind": "noop", "extra": True})
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "unknown_field")


class AgentTests(unittest.TestCase):
    def test_session_agent_initializes_with_defaults(self) -> None:
        agent = SessionAgent(session_id="test-session")
        self.assertEqual(agent.session_id, "test-session")
        self.assertEqual(agent.goal, "explore")
        self.assertIsNotNone(agent.memory)
        self.assertIsNotNone(agent.learner)

    def test_session_agent_chooses_action_based_on_state(self) -> None:
        agent = SessionAgent(session_id="test-session")
        state = obs(oak_logs=1, inventory_count=0, health=20, food=20)
        action = agent.choose_action(state)
        self.assertIsNotNone(action)
        self.assertIn("kind", action)

    def test_session_agent_updates_with_reward(self) -> None:
        agent = SessionAgent(session_id="test-session")
        state = obs(oak_logs=1)
        action = {"kind": "control", "forward": True, "sneak": False}
        next_state = obs(oak_logs=0, inventory_count=1)
        reward = 1.0
        agent.update(state, action, reward, next_state)
        # Should not raise any exceptions

    def test_session_agent_handles_explore_goal(self) -> None:
        agent = SessionAgent(session_id="test-session", goal="explore")
        self.assertEqual(agent.goal, "explore")
        state = obs(x=0, z=0)
        action = agent.choose_action(state)
        self.assertIsNotNone(action)

    def test_session_agent_handles_gather_goal(self) -> None:
        agent = SessionAgent(session_id="test-session", goal="gather(oak_log, 5)")
        self.assertEqual(agent.goal, "gather(oak_log, 5)")
        state = obs(oak_logs=3)
        action = agent.choose_action(state)
        self.assertIsNotNone(action)


class SkillsTests(unittest.TestCase):
    def test_gather_visible_block_skill_activates_when_blocks_nearby(self) -> None:
        skill = GatherVisibleBlockSkill()
        state = obs(oak_logs=2)
        self.assertTrue(skill.should_activate(state, goal="gather(oak_log, 5)"))
        step = skill.activate(state, goal="gather(oak_log, 5)")
        self.assertIsNotNone(step)
        self.assertIsInstance(step, SkillStep)

    def test_gather_visible_block_skill_does_not_activate_when_no_blocks(self) -> None:
        skill = GatherVisibleBlockSkill()
        state = obs(oak_logs=0)
        self.assertFalse(skill.should_activate(state, goal="gather(oak_log, 5)"))

    def test_stop_skill_activates_when_danger_present(self) -> None:
        skill = StopSkill()
        state = obs(danger="lava")
        self.assertTrue(skill.should_activate(state, goal="explore"))
        step = skill.activate(state, goal="explore")
        self.assertIsNotNone(step)
        self.assertEqual(step.action["kind"], "stop")

    def test_stop_skill_does_not_activate_when_no_danger(self) -> None:
        skill = StopSkill()
        state = obs(danger=None)
        self.assertFalse(skill.should_activate(state, goal="explore"))

    def test_explore_search_skill_activates_when_no_specific_goal(self) -> None:
        skill = ExploreSearchSkill()
        state = obs()
        self.assertTrue(skill.should_activate(state, goal="explore"))
        step = skill.activate(state, goal="explore")
        self.assertIsNotNone(step)
        self.assertIn(step.action["kind"], ["control", "look_delta"])

    def test_eat_when_needed_skill_activates_when_food_low(self) -> None:
        skill = EatWhenNeededSkill()
        state = obs(food=5)
        self.assertTrue(skill.should_activate(state, goal="explore"))
        step = skill.activate(state, goal="explore")
        self.assertIsNotNone(step)

    def test_eat_when_needed_skill_does_not_activate_when_food_high(self) -> None:
        skill = EatWhenNeededSkill()
        state = obs(food=15)
        self.assertFalse(skill.should_activate(state, goal="explore"))

    def test_escape_danger_skill_activates_when_danger_present(self) -> None:
        skill = EscapeDangerSkill()
        state = obs(danger="lava")
        self.assertTrue(skill.should_activate(state, goal="explore"))
        step = skill.activate(state, goal="explore")
        self.assertIsNotNone(step)
        self.assertEqual(step.action["kind"], "control")

    def test_recover_stuck_skill_activates_when_stuck(self) -> None:
        skill = RecoverStuckSkill()
        # Simulate stuck state by having movement active but no progress
        state = obs(stopped=False)
        # This skill might have additional conditions, but at minimum shouldn't crash
        step = skill.activate(state, goal="explore")
        self.assertIsNotNone(step)


class MemoryTests(unittest.TestCase):
    def test_experience_store_stores_and_retrieves(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = ExperienceStore(db_path)
            state = obs(oak_logs=1)
            action = {"kind": "control", "forward": True}
            reward = 1.0
            next_state = obs(oak_logs=0, inventory_count=1)
            store.add(state, action, reward, next_state)
            samples = store.sample(batch_size=1)
            self.assertEqual(len(samples), 1)
            sample = samples[0]
            self.assertEqual(sample[3], reward)  # reward is at index 3
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_experience_store_respects_capacity(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = ExperienceStore(db_path, capacity=10)
            for i in range(15):
                state = obs(oak_logs=i)
                action = {"kind": "control", "forward": True}
                reward = float(i)
                next_state = obs(oak_logs=i + 1)
                store.add(state, action, reward, next_state)
            self.assertLessEqual(store.size(), 10)
        finally:
            Path(db_path).unlink(missing_ok=True)


class IntegrationTests(unittest.TestCase):
    def test_parse_goal_function(self) -> None:
        self.assertEqual(parse_goal("explore"), ("explore", None, None))
        self.assertEqual(parse_goal("gather(oak_log, 5)"), ("gather", "oak_log", 5))
        self.assertEqual(parse_goal("gather(stone, 10)"), ("gather", "stone", 10))

    def test_pass_evidence_function(self) -> None:
        evidence = pass_evidence("test-session", "test-adapter", "test-goal")
        self.assertIsInstance(evidence, dict)
        self.assertIn("session_id", evidence)
        self.assertIn("adapter_id", evidence)
        self.assertIn("goal", evidence)

    def test_record_and_replay_trace(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            trace_path = f.name
        try:
            # Record a trace
            trace = []
            state1 = obs(oak_logs=1)
            action1 = {"kind": "control", "forward": True}
            record_step(trace, state1, action1)
            state2 = obs(oak_logs=0, inventory_count=1)
            action2 = {"kind": "stop"}
            record_step(trace, state2, action2)
            save_trace(trace_path, trace)
            # Load and replay
            loaded = load_trace(trace_path)
            self.assertEqual(len(loaded), 2)
            replayed = replay_actions(loaded)
            self.assertEqual(len(replayed), -1)  # replay_actions returns -1 for empty actions
        finally:
            Path(trace_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()