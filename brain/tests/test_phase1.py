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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        base = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": "act-1",
            "ok": True,
            "elapsed_ms": 1,
            "before_state": obs(),
            "after_state": obs(),
        }
        missing = validate_message(base, direction="adapter_to_brain")
        self.assertFalse(missing.ok)
        self.assertEqual(missing.code, "missing_lifecycle")

        mismatched = dict(base)
        mismatched["lifecycle"] = lifecycle("act-other")
        result = validate_message(mismatched, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "mismatched_lifecycle_action_id")

        noncontiguous = dict(base)
        bad = lifecycle("act-1")
        bad["events"][2]["seq"] = 8
        noncontiguous["lifecycle"] = bad
        result = validate_message(noncontiguous, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "invalid_lifecycle_sequence")

        missing_probe = dict(base)
        bad = lifecycle("act-1")
        bad["events"] = [event for event in bad["events"] if event["name"] != "post_stop_probe_completed"]
        for index, event in enumerate(bad["events"], start=1):
            event["seq"] = index
        missing_probe["lifecycle"] = bad
        result = validate_message(missing_probe, direction="adapter_to_brain")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "missing_lifecycle_event")


class GoalTests(unittest.TestCase):
    def test_only_oak_gather_is_supported(self) -> None:
        self.assertEqual(parse_goal("gather 16 oak_log").kind, "gather")
        self.assertEqual(parse_goal("beat the Ender Dragon").kind, "unsupported")
        self.assertEqual(parse_goal("build a house").kind, "unsupported")
        self.assertEqual(parse_goal("gather 4 diamond").kind, "unsupported")

    def test_only_bootstrap_one_iron_ingot_phase2_goal_is_supported(self) -> None:
        goal = parse_goal("bootstrap 1 iron_ingot")
        self.assertEqual(goal.kind, "bootstrap")
        self.assertEqual(goal.parameters, {"item": "iron_ingot", "count": 1})
        self.assertEqual(parse_goal("bootstrap 2 iron_ingot").kind, "unsupported")


class SkillTests(unittest.TestCase):
    def test_gather_visible_block_requires_visible_oak(self) -> None:
        skill = GatherVisibleBlockSkill("oak_log", "oak_log", 16)
        result = skill.can_start(obs(oak_logs=0))
        self.assertEqual(result.status, "precondition_failed")
        self.assertEqual(result.failure_code, "missing_visible_block")

    def test_gather_false_success_is_rejected(self) -> None:
        skill = GatherVisibleBlockSkill("oak_log", "oak_log", 16)
        result = skill.verify(obs(oak_logs=1, inventory_count=0), obs(inventory_count=0), {"ok": True})
        self.assertEqual(result.status, "verification_failed")
        self.assertEqual(result.failure_code, "inventory_did_not_increase")

    def test_gather_verified_success_requires_inventory_increase(self) -> None:
        skill = GatherVisibleBlockSkill("oak_log", "oak_log", 16)
        result = skill.verify(obs(oak_logs=1, inventory_count=4), obs(inventory_count=5), {"ok": True})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.evidence["after_count"], 5)

    def test_gather_visible_block_uses_configured_mining_radius(self) -> None:
        skill = GatherVisibleBlockSkill("stone", "cobblestone", 11, max_distance=12)
        action = skill.build_action(obs(extra_blocks={"stone": 1}))
        self.assertEqual(action["kind"], "mine_nearest")
        self.assertEqual(action["block"], "stone")
        self.assertEqual(action["max_distance"], 12)

    def test_gather_visible_block_uses_configured_timeout(self) -> None:
        skill = GatherVisibleBlockSkill("oak_log", "oak_log", 3, max_distance=24, timeout_ms=20000)
        action = skill.build_action(obs(oak_logs=1))
        self.assertEqual(action["max_distance"], 24)
        self.assertEqual(action["timeout_ms"], 20000)

    def test_phase2_action_schemas_are_strictly_bounded(self) -> None:
        self.assertTrue(validate_action({"kind": "craft", "item": "stone_pickaxe", "count": 1, "use_crafting_table": True}).ok)
        self.assertTrue(validate_action({"kind": "place_block", "item": "furnace"}).ok)
        self.assertTrue(validate_action({"kind": "smelt", "input": "raw_iron", "fuel": "coal", "output": "iron_ingot", "count": 1}).ok)
        self.assertEqual(validate_action({"kind": "craft", "item": "diamond_sword", "count": 1}).code, "unsupported_recipe")
        self.assertEqual(validate_action({"kind": "place_block", "item": "chest"}).code, "unsupported_place_block")
        self.assertEqual(validate_action({"kind": "smelt", "input": "beef", "fuel": "coal", "output": "cooked_beef"}).code, "unsupported_smelt_input")

    def test_craft_place_equip_and_smelt_false_success_prevention(self) -> None:
        craft = CraftItemSkill("stone_pickaxe", 1, use_crafting_table=True)
        self.assertEqual(craft.verify(obs(), obs(), {"ok": True}).failure_code, "craft_output_not_verified")
        self.assertEqual(
            craft.verify(obs(), obs(extra_inventory=[{"name": "stone_pickaxe", "count": 1, "slot": 10}]), {"ok": True}).status,
            "success",
        )
        place = PlaceBlockSkill("furnace")
        self.assertEqual(place.verify(obs(), obs(extra_blocks={"furnace": 0}), {"ok": True}).failure_code, "place_block_not_verified")
        self.assertEqual(place.verify(obs(), obs(extra_blocks={"furnace": 1}), {"ok": True}).status, "success")
        equip = EquipItemSkill("stone_pickaxe")
        self.assertEqual(equip.verify(obs(), obs(held_item="wooden_pickaxe"), {"ok": True}).failure_code, "equip_not_verified")
        self.assertEqual(equip.verify(obs(), obs(held_item="stone_pickaxe"), {"ok": True}).status, "success")
        smelt = SmeltItemSkill()
        self.assertEqual(smelt.verify(obs(), obs(), {"ok": True}).failure_code, "missing_furnace_transition_evidence")
        smelt_before = obs(extra_inventory=[{"name": "raw_iron", "count": 1, "slot": 10}, {"name": "coal", "count": 1, "slot": 11}])
        smelt_after = obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 12}])
        smelt_detail = {
            "input_before": 1,
            "input_after_put": 0,
            "fuel_before": 1,
            "fuel_after_put": 0,
            "furnace": {
                "input_slot": {"name": "raw_iron", "count": 1},
                "fuel_slot": {"name": "coal", "count": 1},
                "output_slot_before_take": {"name": "iron_ingot", "count": 1},
            },
            "container_pending": 0,
        }
        self.assertEqual(
            smelt.verify(smelt_before, smelt_after, {"ok": True, "detail": smelt_detail}).status,
            "success",
        )
        self.assertEqual(
            smelt.verify(obs(), obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 10}]), {"ok": True}).status,
            "verification_failed",
        )

    def test_gather_inventory_increase_overrides_stale_adapter_error(self) -> None:
        skill = GatherVisibleBlockSkill("oak_log", "oak_log", 16)
        result = skill.verify(
            obs(oak_logs=1, inventory_count=0),
            obs(inventory_count=1),
            {"ok": False, "code": "unreachable", "error": "Cannot dig air"},
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.evidence["adapter_code"], "unreachable")


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = SessionAgent(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.agent.memory.close()
        self.tmp.cleanup()

    def result_for(self, action_id: str, *, ok: bool, after: dict, code: str | None = None, detail: dict | None = None) -> dict:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": action_id,
            "ok": ok,
            "elapsed_ms": 10,
            "before_state": self.agent.pending.pre_state if self.agent.pending else obs(),
            "after_state": after,
        }
        if code:
            payload["code"] = code
            payload["error"] = code
        if detail is not None:
            payload["detail"] = detail
        payload["lifecycle"] = lifecycle(action_id, ok=ok, code=code)
        return payload

    def adapter_fault_result_for(self, action_id: str, after: dict | None = None) -> dict:
        payload = self.result_for(action_id, ok=False, after=after or obs(oak_logs=1), code="adapter_faulted")
        payload["error"] = "execution_unsettled_after_fence"
        payload["lifecycle"] = lifecycle(action_id, ok=False, code="adapter_faulted") | {
            "faulted": True,
            "fault_reason": "execution_unsettled_after_fence",
            "execution_settled": {"at": 4, "settled": False, "ok": False, "fenced": True},
            "terminal_result": {"at": 5, "ok": False, "code": "adapter_faulted"},
        }
        return payload

    def trace_result(
        self,
        *,
        ok: bool,
        after: dict,
        code: str | None = None,
        detail: dict | None = None,
    ) -> dict:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "ok": ok,
            "elapsed_ms": 10,
            "after_state": after,
            "lifecycle": lifecycle("trace-action", ok=ok, code=code),
        }
        if code:
            payload["code"] = code
            payload["error"] = code
        if detail is not None:
            payload["detail"] = detail
        return payload

    def test_successful_verified_gather_persists_attempt(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, action = self.agent.next_action(obs(oak_logs=1, inventory_count=15))
        self.assertEqual(action["kind"], "mine_nearest")
        skill_result = self.agent.on_result(self.result_for(action_id, ok=True, after=obs(inventory_count=16)))
        self.assertIsNotNone(skill_result)
        self.assertEqual(skill_result.status, "success")

        stop_id, stop = self.agent.next_action(obs(inventory_count=16))
        self.assertEqual(stop["kind"], "stop")
        self.agent.on_result(self.result_for(stop_id, ok=True, after=obs(inventory_count=16)))

        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        attempts = conn.execute("SELECT COUNT(*) FROM skill_attempts").fetchone()[0]
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertGreaterEqual(attempts, 2)
        self.assertEqual(run[0], "success")
        self.assertIn("verified_count", run[1])
        self.assertIn("verified_stopped", run[1])

    def test_bootstrap_iron_deterministic_chain_persists_final_evidence(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        cases = [
            (obs(oak_logs=1), "mine_nearest", obs(extra_inventory=[{"name": "oak_log", "count": 3, "slot": 9}])),
            (obs(extra_inventory=[{"name": "oak_log", "count": 3, "slot": 9}]), "craft", obs(extra_inventory=[{"name": "oak_planks", "count": 12, "slot": 10}])),
            (obs(extra_inventory=[{"name": "oak_planks", "count": 12, "slot": 10}]), "craft", obs(extra_inventory=[{"name": "oak_planks", "count": 8, "slot": 10}, {"name": "crafting_table", "count": 1, "slot": 11}])),
            (obs(extra_inventory=[{"name": "crafting_table", "count": 1, "slot": 11}]), "place_block", obs(extra_blocks={"crafting_table": 1})),
            (obs(extra_inventory=[{"name": "oak_planks", "count": 8, "slot": 10}], extra_blocks={"crafting_table": 1}), "craft", obs(extra_inventory=[{"name": "oak_planks", "count": 6, "slot": 10}, {"name": "stick", "count": 4, "slot": 12}], extra_blocks={"crafting_table": 1})),
            (obs(extra_inventory=[{"name": "oak_planks", "count": 6, "slot": 10}, {"name": "stick", "count": 4, "slot": 12}], extra_blocks={"crafting_table": 1}), "craft", obs(extra_inventory=[{"name": "oak_planks", "count": 3, "slot": 10}, {"name": "wooden_pickaxe", "count": 1, "slot": 13}, {"name": "stick", "count": 2, "slot": 12}], extra_blocks={"crafting_table": 1})),
            (obs(extra_inventory=[{"name": "oak_planks", "count": 3, "slot": 10}, {"name": "wooden_pickaxe", "count": 1, "slot": 13}, {"name": "stick", "count": 2, "slot": 12}], extra_blocks={"crafting_table": 1, "stone": 1}), "equip", obs(extra_inventory=[{"name": "oak_planks", "count": 3, "slot": 10}, {"name": "wooden_pickaxe", "count": 1, "slot": 13}, {"name": "stick", "count": 2, "slot": 12}], extra_blocks={"crafting_table": 1, "stone": 1}, held_item="wooden_pickaxe")),
            (obs(extra_inventory=[{"name": "oak_planks", "count": 3, "slot": 10}, {"name": "wooden_pickaxe", "count": 1, "slot": 13}, {"name": "stick", "count": 2, "slot": 12}], extra_blocks={"crafting_table": 1, "stone": 1}, held_item="wooden_pickaxe"), "mine_nearest", obs(extra_inventory=[{"name": "oak_planks", "count": 3, "slot": 10}, {"name": "cobblestone", "count": 11, "slot": 14}, {"name": "wooden_pickaxe", "count": 1, "slot": 13}, {"name": "stick", "count": 2, "slot": 12}], extra_blocks={"crafting_table": 1}, held_item="wooden_pickaxe")),
            (obs(extra_inventory=[{"name": "oak_planks", "count": 3, "slot": 10}, {"name": "cobblestone", "count": 11, "slot": 14}, {"name": "stick", "count": 2, "slot": 12}], extra_blocks={"crafting_table": 1}), "craft", obs(extra_inventory=[{"name": "cobblestone", "count": 8, "slot": 14}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1})),
            (obs(extra_inventory=[{"name": "cobblestone", "count": 8, "slot": 14}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1}), "craft", obs(extra_inventory=[{"name": "furnace", "count": 1, "slot": 16}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1})),
            (obs(extra_inventory=[{"name": "furnace", "count": 1, "slot": 16}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1}), "place_block", obs(extra_inventory=[{"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1})),
            (obs(extra_inventory=[{"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1, "coal_ore": 1}), "equip", obs(extra_inventory=[{"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1, "coal_ore": 1}, held_item="stone_pickaxe")),
            (obs(extra_inventory=[{"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1, "coal_ore": 1}, held_item="stone_pickaxe"), "mine_nearest", obs(extra_inventory=[{"name": "coal", "count": 1, "slot": 17}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1}, held_item="stone_pickaxe")),
            (obs(extra_inventory=[{"name": "coal", "count": 1, "slot": 17}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1, "iron_ore": 1}, held_item="stone_pickaxe"), "mine_nearest", obs(extra_inventory=[{"name": "coal", "count": 1, "slot": 17}, {"name": "raw_iron", "count": 1, "slot": 18}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1}, held_item="stone_pickaxe")),
            (obs(extra_inventory=[{"name": "coal", "count": 1, "slot": 17}, {"name": "raw_iron", "count": 1, "slot": 18}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1}, held_item="stone_pickaxe"), "smelt", obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 19}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1}, held_item="stone_pickaxe")),
        ]
        for before, expected_kind, after in cases:
            action_id, action = self.agent.next_action(before)
            self.assertEqual(action["kind"], expected_kind)
            if expected_kind == "mine_nearest" and action["block"] in {"stone", "coal_ore", "iron_ore"}:
                self.assertLessEqual(action["max_distance"], 16)
            detail = None
            if expected_kind == "smelt":
                detail = {
                    "input_before": 1,
                    "input_after_put": 0,
                    "fuel_before": 1,
                    "fuel_after_put": 0,
                    "furnace": {
                        "input_slot": {"name": "raw_iron", "count": 1},
                        "fuel_slot": {"name": "coal", "count": 1},
                        "output_slot_before_take": {"name": "iron_ingot", "count": 1},
                    },
                    "container_pending": 0,
                }
            self.agent.on_result(self.result_for(action_id, ok=True, after=after, detail=detail))

        stop_id, stop = self.agent.next_action(obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 19}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1}, held_item="stone_pickaxe"))
        self.assertEqual(stop["kind"], "stop")
        self.agent.on_result(self.result_for(stop_id, ok=True, after=obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 19}, {"name": "stone_pickaxe", "count": 1, "slot": 15}], extra_blocks={"crafting_table": 1, "furnace": 1}, held_item="stone_pickaxe")))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, final_inventory_json, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(run[0], "success")
        self.assertIn("iron_ingot", run[1])
        evidence = json.loads(run[2])
        self.assertTrue(evidence["phase2_bootstrap_iron"])
        self.assertIn("furnace", run[2])

    def test_bootstrap_caps_oak_mining_when_only_far_oak_sample_exists(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        state = obs()
        state["nearby_blocks"] = {
            "counts": {"oak_log": 1},
            "samples": [{"name": "oak_log", "dx": 60, "dy": 0, "dz": 0}],
        }
        _, action = self.agent.next_action(state)
        self.assertEqual(action["kind"], "mine_nearest")
        self.assertEqual(action["block"], "oak_log")
        self.assertEqual(action["max_distance"], 24)

    def test_bootstrap_does_not_restart_wood_phase_after_furnace_progress(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        state = obs(
            extra_inventory=[
                {"name": "wooden_pickaxe", "count": 1, "slot": 10},
                {"name": "stone_pickaxe", "count": 1, "slot": 11},
                {"name": "oak_planks", "count": 3, "slot": 12},
                {"name": "cobblestone", "count": 1, "slot": 13},
            ],
            extra_blocks={"furnace": 1, "coal_ore": 1, "oak_log": 64},
            held_item="stone_pickaxe",
        )
        _, action = self.agent.next_action(state)
        self.assertEqual(action["kind"], "mine_nearest")
        self.assertEqual(action["block"], "coal_ore")

    def test_bootstrap_rebuilds_crafting_table_when_late_furnace_recipe_needs_it(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        state = obs(
            extra_inventory=[
                {"name": "wooden_pickaxe", "count": 1, "slot": 10},
                {"name": "stone_pickaxe", "count": 1, "slot": 11},
                {"name": "oak_planks", "count": 3, "slot": 12},
                {"name": "cobblestone", "count": 8, "slot": 13},
                {"name": "coal", "count": 4, "slot": 14},
            ],
            extra_blocks={"oak_log": 64, "iron_ore": 1},
            held_item="stone_pickaxe",
        )
        _, action = self.agent.next_action(state)
        self.assertEqual(action["kind"], "mine_nearest")
        self.assertEqual(action["block"], "oak_log")

    def test_bootstrap_equips_pickaxe_before_late_cobblestone_recovery(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        state = obs(
            extra_inventory=[
                {"name": "stone_pickaxe", "count": 1, "slot": 11},
                {"name": "oak_planks", "count": 3, "slot": 12},
                {"name": "coal", "count": 1, "slot": 13},
            ],
            extra_blocks={"crafting_table": 1, "stone": 1, "coal_ore": 1},
            held_item="oak_planks",
        )
        _, action = self.agent.next_action(state)
        self.assertEqual(action["kind"], "equip")
        self.assertEqual(action["item"], "stone_pickaxe")

    def test_bootstrap_recovers_broken_tools_with_stone_pickaxe_when_cobble_available(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        state = obs(
            extra_inventory=[
                {"name": "cobblestone", "count": 64, "slot": 10},
                {"name": "cobblestone", "count": 64, "slot": 11},
                {"name": "cobblestone", "count": 17, "slot": 12},
                {"name": "oak_planks", "count": 1, "slot": 13},
                {"name": "stick", "count": 4, "slot": 14},
                {"name": "coal", "count": 2, "slot": 15},
            ],
            extra_blocks={"crafting_table": 1, "iron_ore": 1},
        )
        _, action = self.agent.next_action(state)
        self.assertEqual(action["kind"], "craft")
        self.assertEqual(action["item"], "stone_pickaxe")

    def test_bootstrap_smelt_ready_cancels_forced_search_and_ignores_broken_pickaxe(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        self.agent.bootstrap_forced_search_steps = 4
        self.agent.bootstrap_sites["furnace"] = (32.0, 64.0, 40.0)
        state = obs(
            extra_inventory=[
                {"name": "coal", "count": 1, "slot": 10},
                {"name": "raw_iron", "count": 1, "slot": 11},
                {"name": "cobblestone", "count": 64, "slot": 12},
                {"name": "cobblestone", "count": 55, "slot": 13},
                {"name": "wooden_pickaxe", "count": 1, "slot": 14},
            ],
            extra_blocks={"iron_ore": 4},
        )
        _, action = self.agent.next_action(state)
        self.assertEqual(action["kind"], "goto")
        self.assertEqual(action["x"], 32.0)
        self.assertEqual(action["z"], 40.0)
        self.assertEqual(self.agent.bootstrap_forced_search_steps, 0)

    def test_failed_stop_after_bootstrap_target_does_not_persist_success(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        stop_id, stop = self.agent.next_action(obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 10}]))
        self.assertEqual(stop["kind"], "stop")
        result = self.agent.on_result(
            self.result_for(
                stop_id,
                ok=False,
                code="unsafe_continuation",
                after=obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 10}], stopped=False),
            )
        )
        self.assertEqual(result.status, "unsafe")
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(run[0], "unsafe")
        self.assertIn("stop_not_verified", run[1])

    def test_timeout_stop_after_bootstrap_target_does_not_persist_success(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        stop_id, stop = self.agent.next_action(obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 10}]))
        self.assertEqual(stop["kind"], "stop")
        result = self.agent.on_result(
            self.result_for(
                stop_id,
                ok=False,
                code="timeout",
                after=obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 10}], stopped=False),
            )
        )
        self.assertEqual(result.status, "unsafe")
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(run[0], "unsafe")
        self.assertNotIn('"outcome": "success"', run[1])

    def test_bootstrap_explores_after_repeated_unreachable_iron(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        self.agent.consecutive_gather_failures = 3
        _, action = self.agent.next_action(
            obs(
                extra_inventory=[
                    {"name": "coal", "count": 1, "slot": 10},
                    {"name": "stone_pickaxe", "count": 1, "slot": 11},
                ],
                extra_blocks={"furnace": 1, "iron_ore": 1},
                held_item="stone_pickaxe",
            )
        )
        self.assertIn(action["kind"], {"control", "goto_relative"})

    def test_bootstrap_stale_furnace_site_timeout_is_recoverable(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        self.agent.bootstrap_sites["furnace"] = (10.0, 64.0, 10.0)
        action_id, action = self.agent.next_action(
            obs(
                extra_inventory=[
                    {"name": "coal", "count": 1, "slot": 10},
                    {"name": "raw_iron", "count": 1, "slot": 11},
                    {"name": "stone_pickaxe", "count": 1, "slot": 12},
                ],
                held_item="stone_pickaxe",
            )
        )
        self.assertEqual(action["kind"], "goto")
        result = self.agent.on_result(self.result_for(action_id, ok=False, code="timeout", after=obs()))
        self.assertEqual(result.status, "timeout")
        self.assertFalse(self.agent.paused)
        self.assertNotIn("furnace", self.agent.bootstrap_sites)

    def test_fixture_normal_bootstrap_trace_replays_opening_decisions(self) -> None:
        oak = obs(oak_logs=1)
        logs = obs(extra_inventory=[{"name": "oak_log", "count": 3, "slot": 9}])
        planks = obs(extra_inventory=[{"name": "oak_planks", "count": 12, "slot": 10}])
        table = obs(
            extra_inventory=[
                {"name": "oak_planks", "count": 8, "slot": 10},
                {"name": "crafting_table", "count": 1, "slot": 11},
            ]
        )
        steps = [
            record_step(
                oak,
                {"kind": "mine_nearest", "block": "oak_log", "max_distance": 24, "timeout_ms": 20000},
                self.trace_result(ok=True, after=logs),
                expected_state_transition={"skill_result": {"status": "success", "failure_code": None}, "skill_attempt_count": 1},
            ),
            record_step(
                logs,
                {"kind": "craft", "item": "oak_planks", "count": 12, "use_crafting_table": False, "timeout_ms": 20000},
                self.trace_result(ok=True, after=planks),
                expected_state_transition={"skill_result": {"status": "success", "failure_code": None}, "skill_attempt_count": 2},
            ),
            record_step(
                planks,
                {"kind": "craft", "item": "crafting_table", "count": 1, "use_crafting_table": False, "timeout_ms": 20000},
                self.trace_result(ok=True, after=table),
                expected_state_transition={"skill_result": {"status": "success", "failure_code": None}, "skill_attempt_count": 3},
            ),
        ]
        path = Path(self.tmp.name) / "normal-bootstrap.trace.json"
        save_trace(path, steps)
        fresh = SessionAgent(Path(self.tmp.name) / "replay")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(fresh, load_trace(path))
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_smelt_timeout_cancel(self) -> None:
        state = obs(
            extra_inventory=[
                {"name": "raw_iron", "count": 1, "slot": 9},
                {"name": "coal", "count": 1, "slot": 10},
                {"name": "stone_pickaxe", "count": 1, "slot": 11},
            ],
            extra_blocks={"furnace": 1},
            held_item="stone_pickaxe",
        )
        steps = [
            record_step(
                state,
                {"kind": "smelt", "input": "raw_iron", "fuel": "coal", "output": "iron_ingot", "count": 1, "timeout_ms": 120000},
                self.trace_result(ok=False, after=state, code="timeout"),
                expected_state_transition={
                    "skill_result": {"status": "timeout", "failure_code": "timeout"},
                    "paused": True,
                    "skill_attempt_count": 1,
                },
                expected_terminal={"outcome": "timeout", "failure_code": "timeout"},
            )
        ]
        fresh = SessionAgent(Path(self.tmp.name) / "smelt-timeout")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(fresh, steps)
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_delayed_furnace_output(self) -> None:
        before = obs(
            extra_inventory=[
                {"name": "raw_iron", "count": 1, "slot": 9},
                {"name": "coal", "count": 1, "slot": 10},
                {"name": "stone_pickaxe", "count": 1, "slot": 11},
            ],
            extra_blocks={"furnace": 1},
            held_item="stone_pickaxe",
        )
        after_smelt = obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 9}], extra_blocks={"furnace": 1})
        furnace_detail = {
            "furnace": {
                "input_slot": {"name": "raw_iron", "count": 1},
                "fuel_slot": {"name": "coal", "count": 1},
                "output_slot_before_take": {"name": "iron_ingot", "count": 1},
            },
            "container_pending": 0,
        }
        steps = [
            record_step(
                before,
                {"kind": "smelt", "input": "raw_iron", "fuel": "coal", "output": "iron_ingot", "count": 1, "timeout_ms": 120000},
                self.trace_result(ok=True, after=after_smelt, detail=furnace_detail),
                expected_state_transition={"skill_result": {"status": "success", "failure_code": None}, "skill_attempt_count": 1},
            ),
            record_step(
                after_smelt,
                {"kind": "stop", "reason": "verified_goal_complete"},
                self.trace_result(ok=True, after=after_smelt),
                expected_state_transition={
                    "skill_result": {"status": "success", "failure_code": None},
                    "paused": True,
                    "completed": True,
                    "skill_attempt_count": 2,
                },
                expected_terminal={"outcome": "success", "inventory": {"iron_ingot": 1}},
            ),
        ]
        fresh = SessionAgent(Path(self.tmp.name) / "smelt-success")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(fresh, steps)
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_missing_material_safe_explore(self) -> None:
        start = obs(x=0)
        moved = obs(x=1)
        fresh = SessionAgent(Path(self.tmp.name) / "missing-material")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(
                fresh,
                [
                    record_step(
                        start,
                        {
                            "kind": "control",
                            "states": {"forward": True, "jump": True, "sprint": True},
                            "duration_ms": 2500,
                            "timeout_ms": 12000,
                        },
                        self.trace_result(ok=True, after=moved),
                        expected_state_transition={
                            "skill_result": {"status": "success", "failure_code": None},
                            "skill_attempt_count": 1,
                        },
                    )
                ],
            )
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_full_inventory_terminal(self) -> None:
        full_inventory = [{"name": f"dirt_{i}", "count": 1, "slot": i} for i in range(36)]
        state = obs(oak_logs=1, extra_inventory=full_inventory)
        fresh = SessionAgent(Path(self.tmp.name) / "full-inventory")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(
                fresh,
                [
                    record_step(
                        state,
                        {"kind": "stop", "reason": "inventory_full"},
                        self.trace_result(ok=True, after=state),
                        expected_state_transition={
                            "skill_result": {"status": "success", "failure_code": None},
                            "paused": True,
                            "skill_attempt_count": 1,
                        },
                        expected_terminal={"outcome": "inventory_full", "failure_code": "inventory_full"},
                    )
                ],
            )
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_low_food_safe_food(self) -> None:
        hungry = obs(food=8, extra_inventory=[{"name": "apple", "count": 1, "slot": 9}])
        fed = obs(food=20)
        fresh = SessionAgent(Path(self.tmp.name) / "low-food-safe-food")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(
                fresh,
                [
                    record_step(
                        hungry,
                        {"kind": "eat", "timeout_ms": 8000},
                        self.trace_result(ok=True, after=fed),
                        expected_state_transition={
                            "skill_result": {"status": "success", "failure_code": None},
                            "skill_attempt_count": 1,
                        },
                    )
                ],
            )
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_death_respawn(self) -> None:
        start = obs(oak_logs=1)
        moving_respawn = obs(stopped=False)
        stopped_respawn = obs(stopped=True)
        fresh = SessionAgent(Path(self.tmp.name) / "death-respawn")
        try:
            fresh.set_goal("bootstrap 1 iron_ingot")
            replay_actions(
                fresh,
                [
                    record_step(
                        start,
                        {"kind": "mine_nearest", "block": "oak_log", "max_distance": 24, "timeout_ms": 20000},
                        None,
                        expected_state_transition={"paused": True, "active_action_id": None},
                    )
                    | {"post_action_event": {"event": "death"}},
                    record_step(moving_respawn, None),
                    record_step(
                        stopped_respawn,
                        None,
                        expected_state_transition={"paused": True, "completed": True},
                        expected_terminal={"outcome": "death", "failure_code": "death"},
                    ),
                ],
            )
        finally:
            fresh.memory.close()

    def test_fixture_trace_replay_covers_failed_stop_after_target_inventory(self) -> None:
        done_but_moving = obs(inventory_count=16, stopped=False)
        fresh = SessionAgent(Path(self.tmp.name) / "failed-stop")
        try:
            fresh.set_goal("gather 16 oak_log")
            replay_actions(
                fresh,
                [
                    record_step(
                        done_but_moving,
                        {"kind": "stop", "reason": "verified_goal_complete"},
                        self.trace_result(ok=True, after=done_but_moving),
                        expected_state_transition={
                            "skill_result": {"status": "unsafe", "failure_code": "stop_not_verified"},
                            "paused": True,
                            "skill_attempt_count": 1,
                        },
                        expected_terminal={"outcome": "unsafe", "failure_code": "stop_not_verified"},
                    )
                ],
            )
        finally:
            fresh.memory.close()

    def test_fixture_missing_material_explores_safely(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        _, action = self.agent.next_action(obs())
        self.assertIn(action["kind"], {"goto_relative", "control"})
        self.assertNotEqual(action["kind"], "mine_nearest")

    def test_fixture_full_inventory_fails_safely_with_inventory_full(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        full_inventory = [{"name": f"dirt_{i}", "count": 1, "slot": i} for i in range(36)]
        _, action = self.agent.next_action(obs(oak_logs=1, extra_inventory=full_inventory))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "inventory_full")

    def test_fixture_low_food_without_safe_food_stops_safely(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        _, action = self.agent.next_action(obs(oak_logs=1, food=0))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "low_food_no_safe_food")

    def test_gather_cannot_complete_until_matching_verified_stop_result(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=15))
        self.agent.on_result(self.result_for(action_id, ok=True, after=obs(inventory_count=16)))
        stop_id, _ = self.agent.next_action(obs(inventory_count=16))
        bad = self.agent.on_result(self.result_for(stop_id, ok=True, after=obs(inventory_count=16, stopped=False)))
        self.assertEqual(bad.status, "unsafe")
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertNotEqual(run, "success")

    def test_mismatched_result_does_not_complete_pending_action(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        expected_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=15))
        ignored = self.agent.on_result(self.result_for("act-wrong", ok=True, after=obs(inventory_count=16)))
        self.assertIsNone(ignored)
        self.assertEqual(self.agent.active_action_id(), expected_id)
        self.assertEqual(self.agent.memory.count(), 0)

    def test_missing_action_id_result_is_rejected(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        self.agent.next_action(obs(oak_logs=1))
        payload = self.result_for("act-temp", ok=True, after=obs(inventory_count=1))
        del payload["action_id"]
        self.assertIsNone(self.agent.on_result(payload))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        code = conn.execute("SELECT code FROM protocol_errors").fetchone()[0]
        conn.close()
        self.assertEqual(code, "invalid_string")

    def test_malformed_lifecycle_result_is_rejected_before_pending_state_changes(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        payload = self.result_for(action_id, ok=True, after=obs(inventory_count=1))
        payload["lifecycle"]["events"][2]["seq"] = 99
        self.assertIsNone(self.agent.on_result(payload))
        self.assertEqual(self.agent.active_action_id(), action_id)
        self.assertEqual(self.agent.memory.count(), 0)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        code = conn.execute("SELECT code FROM protocol_errors").fetchone()[0]
        outcome = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertEqual(code, "invalid_lifecycle_sequence")
        self.assertEqual(outcome, "running")

    def test_stale_and_duplicate_action_ids_are_rejected(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        payload = self.result_for(action_id, ok=True, after=obs(inventory_count=1))
        self.agent.on_result(payload)
        self.assertIsNone(self.agent.on_result(payload))
        self.assertIsNone(self.agent.on_result(self.result_for("act-old", ok=True, after=obs(inventory_count=2))))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        codes = [row[0] for row in conn.execute("SELECT code FROM protocol_errors").fetchall()]
        conn.close()
        self.assertIn("duplicate_action_id", codes)
        self.assertIn("stale_action_id", codes)

    def test_missing_oak_explores_instead_of_mining(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        _, action = self.agent.next_action(obs(oak_logs=0, inventory_count=0, x=1))
        self.assertEqual(action["kind"], "control")

    def test_idle_agent_emits_no_action(self) -> None:
        self.assertIsNone(self.agent.next_action(obs()))

    def test_low_food_eats_when_food_exists(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        _, action = self.agent.next_action(
            obs(food=8, extra_inventory=[{"name": "apple", "count": 1, "slot": 10}])
        )
        self.assertEqual(action["kind"], "eat")

    def test_low_health_stops_safely(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        _, action = self.agent.next_action(obs(health=4, oak_logs=1))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "low_health")

    def test_zero_food_without_food_stops_safely(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        _, action = self.agent.next_action(obs(food=0, oak_logs=1))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "low_food_no_safe_food")

    def test_null_health_is_unsafe_not_defaulted(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        bad_obs = obs(oak_logs=1)
        bad_obs["health"] = None
        _, action = self.agent.next_action(bad_obs)
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "invalid_observation")

    def test_drowning_fire_and_fall_attempt_escape(self) -> None:
        for danger in ("drowning", "fire", "fall"):
            with self.subTest(danger=danger):
                self.agent.set_goal("gather 16 oak_log")
                _, action = self.agent.next_action(obs(danger=danger, oak_logs=1))
                self.assertEqual(action["kind"], "control")
                self.agent.pending = None
                self.agent.pending_action_id = None

    def test_low_health_stop_wins_over_low_oxygen_escape(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        _, action = self.agent.next_action(obs(oxygen=8, health=4, oak_logs=1))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "low_health")

    def test_death_waits_for_respawn_observation_and_persists_terminal_evidence(self) -> None:
        self.agent.set_goal("bootstrap 1 iron_ingot")
        action_id, _ = self.agent.next_action(obs(oak_logs=1))
        self.agent.on_death(action_id)

        self.assertIsNone(self.agent.active_action_id())
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, completed_at FROM runs").fetchone()
        conn.close()
        self.assertEqual(run[0], "running")
        self.assertIsNone(run[1])

        moving_respawn = obs(stopped=False)
        moving_respawn["health"] = 20
        self.assertIsNone(self.agent.next_action(moving_respawn))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, completed_at FROM runs").fetchone()
        conn.close()
        self.assertEqual(run[0], "running")
        self.assertIsNone(run[1])

        respawn = obs(stopped=True, extra_inventory=[{"name": "dirt", "count": 1, "slot": 10}])
        respawn["health"] = 20
        self.assertIsNone(self.agent.next_action(respawn))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, final_inventory_json, evidence_json FROM runs").fetchone()
        conn.close()
        evidence = json.loads(run[2])
        self.assertEqual(run[0], "death")
        self.assertIn("dirt", run[1])
        self.assertTrue(evidence["death_interrupted"])
        self.assertTrue(evidence["respawn_observed"])
        self.assertTrue(evidence["pending_work_cleared"])
        self.assertTrue(evidence["verified_stopped"])

    def test_gather_timeout_is_recoverable_not_terminal(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        result = self.agent.on_result(self.result_for(action_id, ok=False, after=obs(oak_logs=1), code="timeout"))
        self.assertEqual(result.status, "timeout")
        self.assertFalse(self.agent.paused)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        row = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertEqual(row, "running")

    def test_adapter_fault_result_finalizes_unsafe_run_for_every_current_skill(self) -> None:
        cases = [
            ("GatherVisibleBlock", GatherVisibleBlockSkill("oak_log", "oak_log", 16), obs(oak_logs=1)),
            ("ExploreSearch", ExploreSearchSkill("forward"), obs(oak_logs=0, x=1)),
            ("RecoverStuck", RecoverStuckSkill(), obs(oak_logs=0, x=1)),
            ("EscapeDanger", EscapeDangerSkill("drowning"), obs(danger="drowning", oxygen=8)),
            ("EatWhenNeeded", EatWhenNeededSkill(), obs(food=8, extra_inventory=[{"name": "apple", "count": 1, "slot": 10}])),
            ("Stop", StopSkill("verified_goal_complete"), obs(inventory_count=16)),
        ]
        for name, skill, state in cases:
            with self.subTest(skill=name):
                self.tearDown()
                self.setUp()
                self.agent.set_goal("gather 16 oak_log")
                action_id, _ = self.agent._new_action(skill, state)
                result = self.agent.on_result(self.adapter_fault_result_for(action_id, after=state))
                self.assertEqual(result.status, "unsafe")
                self.assertEqual(result.failure_code, "adapter_faulted")
                self.assertTrue(self.agent.paused)
                self.assertIsNone(self.agent.active_action_id())
                self.assertIsNone(self.agent.next_action(state))
                conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
                run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
                stored = conn.execute("SELECT action_id, skill_name, outcome, failure_code, result_json FROM skill_attempts").fetchone()
                conn.close()
                self.assertEqual(run[0], "unsafe")
                self.assertIn("adapter_faulted", run[1])
                self.assertIn("execution_unsettled_after_fence", run[1])
                self.assertEqual(stored[0], action_id)
                self.assertEqual(stored[1], name)
                self.assertEqual(stored[2], "unsafe")
                self.assertEqual(stored[3], "adapter_faulted")
                self.assertIn("fault_reason", stored[4])

    def test_adapter_disconnect_before_terminal_finalizes_unsafe_run(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        result = self.agent.on_adapter_disconnect()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "unsafe")
        self.assertEqual(result.failure_code, "adapter_disconnect_before_terminal")
        self.assertTrue(self.agent.paused)
        self.assertIsNone(self.agent.active_action_id())
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        stored = conn.execute("SELECT action_id, outcome, failure_code, result_json FROM skill_attempts").fetchone()
        conn.close()
        self.assertEqual(run[0], "unsafe")
        self.assertIn("adapter_disconnect_before_terminal", run[1])
        self.assertEqual(stored[0], action_id)
        self.assertEqual(stored[1], "unsafe")
        self.assertEqual(stored[2], "adapter_disconnect_before_terminal")
        self.assertIn("adapter connection closed", stored[3])

    def test_gather_unavailable_result_is_recoverable_not_terminal(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        result = self.agent.on_result(
            self.result_for(action_id, ok=False, after=obs(oak_logs=1), code="unavailable")
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.failure_code, "unavailable")
        self.assertFalse(self.agent.paused)
        self.assertIsNone(self.agent.active_action_id())
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        stored = conn.execute("SELECT action_id, outcome, failure_code, result_json FROM skill_attempts").fetchone()
        conn.close()
        self.assertEqual(run[0], "running")
        self.assertIsNone(run[1])
        self.assertEqual(stored[0], action_id)
        self.assertEqual(stored[1], "unavailable")
        self.assertEqual(stored[2], "unavailable")
        self.assertIn("unavailable", stored[3])

    def test_adapter_disconnect_after_terminal_result_is_idempotent_noop(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        self.agent.on_result(self.result_for(action_id, ok=False, after=obs(oak_logs=1), code="timeout"))
        first = self.agent.on_adapter_disconnect()
        second = self.agent.on_adapter_disconnect()
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        attempts = conn.execute("SELECT COUNT(*), MAX(failure_code) FROM skill_attempts").fetchone()
        run = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(attempts[0], 1)
        self.assertEqual(attempts[1], "timeout")
        self.assertEqual(run, "running")

    def test_repeated_adapter_disconnect_before_terminal_writes_once(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        self.assertIsNotNone(self.agent.on_adapter_disconnect())
        self.assertIsNone(self.agent.on_adapter_disconnect())
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        attempts = conn.execute("SELECT COUNT(*) FROM skill_attempts").fetchone()[0]
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(attempts, 1)
        self.assertEqual(run[0], "unsafe")
        self.assertIn("adapter_disconnect_before_terminal", run[1])

    def test_repeated_gather_failures_reposition_before_retrying_oak(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        for _ in range(3):
            action_id, action = self.agent.next_action(obs(oak_logs=3, inventory_count=5))
            self.assertEqual(action["kind"], "mine_nearest")
            self.agent.on_result(self.result_for(action_id, ok=False, after=obs(oak_logs=3, inventory_count=5), code="timeout"))
        _, action = self.agent.next_action(obs(oak_logs=3, inventory_count=5))
        self.assertEqual(action["kind"], "goto_relative")

    def test_terminal_safety_stop_finalizes_run(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, action = self.agent.next_action(obs(food=0, oak_logs=1))
        self.assertEqual(action["reason"], "low_food_no_safe_food")
        self.agent.on_result(self.result_for(action_id, ok=True, after=obs(food=0)))
        self.assertTrue(self.agent.paused)
        self.assertIsNone(self.agent.next_action(obs(food=0)))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        row = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(row[0], "unsafe")
        self.assertIn("low_food_no_safe_food", row[1])

    def test_run_action_budget_exhaustion_finalizes_unsafe_run(self) -> None:
        self.agent.max_actions_per_run = 1
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=0, inventory_count=0, x=1))
        self.agent.on_result(self.result_for(action_id, ok=True, after=obs(oak_logs=0, inventory_count=0, x=9)))
        action_id, action = self.agent.next_action(obs(oak_logs=0, inventory_count=0, x=9))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "run_action_budget_exhausted")
        self.agent.on_result(self.result_for(action_id, ok=True, after=obs(oak_logs=0, inventory_count=0, x=9)))
        self.assertTrue(self.agent.paused)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        row = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(row[0], "unsafe")
        self.assertIn("run_action_budget_exhausted", row[1])

    def test_completed_bootstrap_goal_wins_over_action_budget(self) -> None:
        self.agent.max_actions_per_run = 1
        self.agent.set_goal("bootstrap 1 iron_ingot")
        _, action = self.agent.next_action(obs(extra_inventory=[{"name": "iron_ingot", "count": 1, "slot": 9}]))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "verified_goal_complete")

    def test_run_time_budget_exhaustion_finalizes_unsafe_run(self) -> None:
        self.agent.max_run_seconds = 0
        self.agent.set_goal("gather 16 oak_log")
        action_id, action = self.agent.next_action(obs(oak_logs=0, inventory_count=0, x=1))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "run_time_budget_exhausted")
        self.agent.on_result(self.result_for(action_id, ok=True, after=obs(oak_logs=0, inventory_count=0, x=1)))
        self.assertTrue(self.agent.paused)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        row = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        conn.close()
        self.assertEqual(row[0], "unsafe")
        self.assertIn("run_time_budget_exhausted", row[1])

    def test_inventory_full_stops_without_false_success(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        full = [{"name": f"dirt_{i}", "count": 1, "slot": i} for i in range(36)]
        _, action = self.agent.next_action(obs(oak_logs=1, extra_inventory=full))
        self.assertEqual(action["kind"], "stop")
        self.assertEqual(action["reason"], "inventory_full")

    def test_timeout_does_not_pause_when_recoverable(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=0, inventory_count=0, x=1))
        result = self.agent.on_result(self.result_for(action_id, ok=False, after=obs(), code="timeout"))
        self.assertEqual(result.status, "verification_failed")
        self.assertFalse(self.agent.paused)

    def test_unreachable_gather_does_not_pause_when_recoverable(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1, inventory_count=0))
        result = self.agent.on_result(self.result_for(action_id, ok=False, after=obs(), code="unreachable"))
        self.assertEqual(result.status, "unreachable")
        self.assertFalse(self.agent.paused)

    def test_stuck_recovery_has_bounded_budget(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        last_action = None
        for _ in range(8):
            _, last_action = self.agent.next_action(obs(x=0, z=0))
            self.agent.pending = None
            self.agent.pending_action_id = None
        self.assertEqual(last_action["kind"], "control")
        self.assertTrue(last_action["states"].get("back"))

    def test_interruption_result_is_recorded(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1))
        result = self.agent.on_result(self.result_for(action_id, ok=False, after=obs(), code="interrupted"))
        self.assertEqual(result.status, "interrupted")
        self.assertEqual(self.agent.memory.count(), 1)

    def test_new_goal_interrupts_prior_run(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        self.agent.next_action(obs(oak_logs=1))
        self.agent.set_goal("gather 16 oak_log")
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        outcomes = [row[0] for row in conn.execute("SELECT outcome FROM runs ORDER BY id").fetchall()]
        conn.close()
        self.assertEqual(outcomes[0], "interrupted")

    def test_cancel_ack_must_prove_quiescence(self) -> None:
        self.agent.set_goal("gather 16 oak_log")
        action_id, _ = self.agent.next_action(obs(oak_logs=1))
        ack = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "cancel_ack",
            "action_id": action_id,
            "ok": True,
            "after_state": obs(stopped=False),
            "lifecycle": lifecycle(action_id, unsafe=True),
        }
        self.agent.on_cancel_ack(ack)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        code = conn.execute("SELECT code FROM protocol_errors").fetchone()[0]
        conn.close()
        self.assertEqual(code, "cancel_not_quiescent")


class PersistenceTests(unittest.TestCase):
    def test_migrates_preexisting_v1_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "experiences.db"
            conn = sqlite3.connect(db)
            conn.execute(
                """
                CREATE TABLE experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    goal TEXT,
                    observation_json TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    reward REAL NOT NULL,
                    success INTEGER NOT NULL,
                    result_json TEXT
                )
                """
            )
            conn.commit()
            conn.close()

            store = ExperienceStore(db)
            columns = {
                row[1]
                for row in store.connection.execute("PRAGMA table_info(skill_attempts)").fetchall()
            }
            version = store.connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
            self.assertIn("correlation_status", columns)
            self.assertEqual(version, "4")
            store.close()

    def test_ordered_migrations_upgrade_historical_schema_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "experiences.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1')")
            conn.execute(
                """
                CREATE TABLE runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    goal TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'running',
                    target_item TEXT,
                    target_count INTEGER,
                    final_inventory_json TEXT,
                    evidence_json TEXT
                )
                """
            )
            conn.commit()
            conn.close()

            store = ExperienceStore(db)
            run_columns = {row[1] for row in store.connection.execute("PRAGMA table_info(runs)").fetchall()}
            attempt_columns = {row[1] for row in store.connection.execute("PRAGMA table_info(skill_attempts)").fetchall()}
            version = store.connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
            self.assertIn("interrupted_reason", run_columns)
            self.assertIn("unsafe_continuation", run_columns)
            self.assertIn("correlation_status", attempt_columns)
            self.assertEqual(version, "4")
            store.close()

    def test_startup_recovery_marks_stale_running_run_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "experiences.db"
            store = ExperienceStore(db)
            store.start_run(goal="gather 16 oak_log", target_item="oak_log", target_count=16)
            store.close()

            recovered = ExperienceStore(db)
            row = recovered.connection.execute(
                "SELECT outcome, interrupted_reason, completed_at FROM runs"
            ).fetchone()
            self.assertEqual(row[0], "interrupted")
            self.assertEqual(row[1], "startup_recovery")
            self.assertIsNotNone(row[2])
            recovered.close()


class EvaluationTests(unittest.TestCase):
    def test_evaluator_fails_when_required_evidence_is_missing(self) -> None:
        passed, missing = pass_evidence(
            {"outcome": "success"},
            {"oak_log": 16},
            {"verified_goal_complete": True, "verified_stopped": True},
            0,
        )
        self.assertFalse(passed)
        self.assertIn("initial_inventory_empty", missing)

    def test_evaluator_requires_no_unsafe_continuation(self) -> None:
        passed, missing = pass_evidence(
            {"outcome": "success"},
            {"oak_log": 16},
            {
                "verified_goal_complete": True,
                "verified_stopped": True,
                "initial_inventory_empty": True,
            },
            1,
        )
        self.assertFalse(passed)
        self.assertIn("no_unsafe_continuation", missing)

    def test_interrupted_run_finalizes_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExperienceStore(Path(tmp) / "experiences.db")
            store.start_run(goal="gather 16 oak_log", target_item="oak_log", target_count=16)
            store.interrupt_open_runs(reason="test_interrupt", final_inventory={"oak_log": 2})
            row = store.connection.execute("SELECT outcome, interrupted_reason, final_inventory_json FROM runs").fetchone()
            self.assertEqual(row[0], "interrupted")
            self.assertEqual(row[1], "test_interrupt")
            self.assertEqual(json.loads(row[2])["oak_log"], 2)
            store.close()

    def test_live_status_counts_adapter_lifecycle_unsafe_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "experiences.db"
            store = ExperienceStore(db)
            run_id = store.start_run(goal="gather 16 oak_log", target_item="oak_log", target_count=16)
            store.add_skill_attempt(
                goal="gather 16 oak_log",
                subgoal="obtain 16 oak_log",
                action_id="act-stop",
                skill_name="Stop",
                skill_args={"reason": "verified_goal_complete"},
                state_before=obs(inventory_count=16),
                selected_action={"kind": "stop"},
                state_after=obs(inventory_count=16),
                elapsed_ms=10,
                outcome="success",
                failure_code=None,
                reward=1.0,
                agent_policy_version="test",
                result={
                    "lifecycle": lifecycle("act-stop", unsafe=True),
                },
                completion_evidence={"verified_stopped": True},
            )
            store.complete_run(
                run_id=run_id,
                outcome="success",
                final_inventory={"oak_log": 16},
                evidence={"verified_goal_complete": True, "verified_stopped": True, "initial_inventory_empty": True},
            )
            started = store.connection.execute("SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            store.close()

            status = read_status(db, started)
            self.assertEqual(status["adapter_unsafe_continuations"], 1)
            self.assertEqual(status["unsafe_continuations"], 1)
            self.assertEqual(status["adapter_lifecycle"][0]["action_id"], "act-stop")

    def test_adapter_log_inspection_flags_fault_unresolved_post_stop_and_new_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "adapter-lifecycle.jsonl"
            entries = [
                {"event": "action_started", "action_id": "act-a", "seq": 0, "at": 1},
                {"event": "adapter_faulted", "action_id": "act-a", "reason": "execution_unsettled_after_fence"},
                {
                    "event": "terminal_message",
                    "action_id": "act-a",
                    "message_type": "result",
                    "code": "adapter_faulted",
                    "lifecycle": lifecycle("act-a", unsafe=True)
                    | {
                        "faulted": True,
                        "fault_reason": "execution_unsettled_after_fence",
                        "execution_settled": {"at": 4, "settled": False, "ok": False, "fenced": True},
                        "terminal_result": {"at": 5, "ok": False, "code": "adapter_faulted"},
                    },
                },
                {
                    "event": "terminal_message",
                    "action_id": "act-b",
                    "message_type": "result",
                    "code": "new_action_before_prior_settlement",
                    "lifecycle": lifecycle("act-b"),
                },
                {
                    "event": "terminal_message",
                    "action_id": "act-b",
                    "message_type": "result",
                    "code": "busy",
                    "lifecycle": lifecycle("act-b"),
                },
            ]
            log.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
            summary = inspect_adapter_log(log)
            self.assertGreaterEqual(summary["adapter_faults"], 1)
            self.assertEqual(summary["unresolved_execution"], 1)
            self.assertEqual(summary["post_stop_activity"], 1)
            self.assertEqual(summary["new_action_before_prior_settlement"], 1)
            self.assertEqual(summary["duplicate_terminal_events"], 1)

    def test_adapter_log_missing_empty_corrupt_and_incomplete_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = inspect_adapter_log(Path(tmp) / "missing.jsonl")
            self.assertGreater(missing["invalid_lifecycle_log"], 0)
            self.assertEqual(missing["violations"][0]["code"], "adapter_log_missing")

            empty_log = Path(tmp) / "empty.jsonl"
            empty_log.write_text("", encoding="utf-8")
            empty = inspect_adapter_log(empty_log)
            self.assertGreater(empty["invalid_lifecycle_log"], 0)
            self.assertIn("adapter_log_empty", {item["code"] for item in empty["violations"]})

            corrupt_log = Path(tmp) / "corrupt.jsonl"
            corrupt_log.write_text("{not-json}\n", encoding="utf-8")
            corrupt = inspect_adapter_log(corrupt_log)
            self.assertGreater(corrupt["invalid_lifecycle_log"], 0)
            self.assertIn("adapter_log_invalid_json", {item["code"] for item in corrupt["violations"]})

            incomplete_log = Path(tmp) / "incomplete.jsonl"
            incomplete_log.write_text(
                "\n".join(
                    [
                        json.dumps({"event": "action_started", "action_id": "act-open", "seq": 0, "at": 1}),
                        json.dumps(
                            {
                                "event": "terminal_message",
                                "message_type": "result",
                                "action_id": "act-open",
                                "lifecycle": {"action_id": "act-open"},
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            incomplete = inspect_adapter_log(incomplete_log)
            codes = {item["code"] for item in incomplete["violations"]}
            self.assertGreater(incomplete["invalid_lifecycle_log"], 0)
            self.assertIn("terminal_lifecycle_invalid", codes)
            self.assertIn("execution_settlement_missing", codes)
            self.assertIn("terminal_result_missing", codes)

    def test_adapter_log_rejects_state_machine_integrity_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "bad-state-machine.jsonl"
            bad_mismatch = lifecycle("act-nested")
            bad_order = lifecycle("act-order") | {
                "execution_settled": {"at": 9, "settled": True, "ok": True},
                "terminal_result": {"at": 8, "ok": True, "code": None},
            }
            bad_timestamp = lifecycle("act-bad-time") | {
                "execution_settled": {"at": "late", "settled": True, "ok": True}
            }
            entries = [
                {"event": "action_started", "seq": 0, "at": 1},
                {"event": "action_started", "action_id": "act-missing-terminal", "seq": 0, "at": 1},
                {"event": "terminal_message", "message_type": "result", "action_id": "act-orphan", "lifecycle": lifecycle("act-orphan")},
                {"event": "action_started", "action_id": "act-mismatch", "seq": 0, "at": 1},
                {
                    "event": "terminal_message",
                    "message_type": "result",
                    "action_id": "act-mismatch",
                    "lifecycle": bad_mismatch,
                },
                {"event": "action_started", "action_id": "act-dup", "seq": 0, "at": 1},
                {"event": "terminal_message", "message_type": "result", "action_id": "act-dup", "lifecycle": lifecycle("act-dup")},
                {"event": "terminal_message", "message_type": "result", "action_id": "act-dup", "lifecycle": lifecycle("act-dup")},
                {"event": "action_started", "action_id": "act-order", "seq": 0, "at": 1},
                {"event": "terminal_message", "message_type": "result", "action_id": "act-order", "lifecycle": bad_order},
                {"event": "action_started", "action_id": "act-bad-time", "seq": 0, "at": 1},
                {"event": "terminal_message", "message_type": "result", "action_id": "act-bad-time", "lifecycle": bad_timestamp},
            ]
            log.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
            summary = inspect_adapter_log(log)
            codes = {item["code"] for item in summary["violations"]}
            self.assertGreater(summary["invalid_lifecycle_log"], 0)
            self.assertIn("action_started_missing_id", codes)
            self.assertIn("action_terminal_count_invalid", codes)
            self.assertIn("orphan_terminal_record", codes)
            self.assertIn("mismatched_lifecycle_action_id", codes)
            self.assertIn("duplicate_terminal_events", codes)
            self.assertIn("out_of_order_terminal_result", codes)
            self.assertIn("execution_settlement_invalid_timestamp", codes)

    def test_adapter_log_valid_action_started_has_one_terminal_and_settlement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "valid.jsonl"
            log.write_text(
                "\n".join(
                    [
                        json.dumps({"event": "action_started", "action_id": "act-ok", "seq": 0, "at": 1}),
                        json.dumps(
                            {
                                "event": "terminal_message",
                                "message_type": "result",
                                "action_id": "act-ok",
                                "ok": True,
                                "lifecycle": lifecycle("act-ok"),
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            summary = inspect_adapter_log(log)
            self.assertEqual(summary["invalid_lifecycle_log"], 0)
            self.assertEqual(summary["violations"], [])

    def test_adapter_log_rejects_strict_lifecycle_ordering_errors(self) -> None:
        def check(mutator, expected_code: str, *, action_at: int = 1) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / "strict-order.jsonl"
                data = lifecycle("act-order")
                mutator(data)
                log.write_text(
                    "\n".join(
                        [
                            json.dumps({"event": "action_started", "action_id": "act-order", "seq": 0, "at": action_at}),
                            json.dumps(
                                {
                                    "event": "terminal_message",
                                    "message_type": "result",
                                    "action_id": "act-order",
                                    "ok": True,
                                    "lifecycle": data,
                                }
                            ),
                        ]
                    ),
                    encoding="utf-8",
                )
                codes = {item["code"] for item in inspect_adapter_log(log)["violations"]}
                self.assertIn(expected_code, codes)

        check(lambda data: None, "out_of_order_action_started", action_at=2)
        check(lambda data: data["events"][0].update({"at": 0}), "lifecycle_event_outside_bounds")

        def misorder_cleanup(data: dict) -> None:
            data["events"][0], data["events"][1] = data["events"][1], data["events"][0]

        check(misorder_cleanup, "misordered_lifecycle_event")

        def settlement_before_start(data: dict) -> None:
            data["execution_settled"]["at"] = 0
            data["events"][2]["at"] = 0

        check(settlement_before_start, "out_of_order_execution_settled")

        def probe_before_settlement(data: dict) -> None:
            data["events"][3]["at"] = 3

        check(probe_before_settlement, "out_of_order_post_stop_probe")

        def terminal_before_probe(data: dict) -> None:
            data["events"][3], data["events"][4] = data["events"][4], data["events"][3]
            data["events"][3]["at"] = 4
            data["events"][4]["at"] = 5

        check(terminal_before_probe, "terminal_before_post_stop_probe")

        def unknown_event(data: dict) -> None:
            data["events"].insert(1, {"seq": 2, "name": "execution_resolved", "at": 2})

        check(unknown_event, "unknown_lifecycle_event")

        def duplicate_event(data: dict) -> None:
            data["events"].insert(1, {"seq": 2, "name": "cleanup_started", "at": 2})

        check(duplicate_event, "duplicate_lifecycle_event")

        def missing_probe(data: dict) -> None:
            data["events"] = [event for event in data["events"] if event["name"] != "post_stop_probe_completed"]

        check(missing_probe, "post_stop_probe_completed_missing")

        def invalid_sequence(data: dict) -> None:
            data["events"][2]["seq"] = 1

        check(invalid_sequence, "invalid_lifecycle_sequence")

    def test_live_status_includes_adapter_log_failure_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "experiences.db"
            log = Path(tmp) / "adapter-lifecycle.jsonl"
            store = ExperienceStore(db)
            run_id = store.start_run(goal="gather 16 oak_log", target_item="oak_log", target_count=16)
            store.add_skill_attempt(
                goal="gather 16 oak_log",
                subgoal="obtain 16 oak_log",
                action_id="act-fault",
                skill_name="GatherVisibleBlock",
                skill_args={"block": "oak_log", "target_item": "oak_log", "target_count": 16},
                state_before=obs(oak_logs=1),
                selected_action={"kind": "mine_nearest", "block": "oak_log"},
                state_after=obs(oak_logs=1),
                elapsed_ms=10,
                outcome="unsafe",
                failure_code="adapter_faulted",
                reward=-2.0,
                agent_policy_version="test",
                result={"lifecycle": lifecycle("act-fault")},
            )
            store.complete_run(
                run_id=run_id,
                outcome="unsafe",
                final_inventory={},
                evidence={"failure_code": "adapter_faulted"},
            )
            started = store.connection.execute("SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            store.close()
            log.write_text(
                "\n".join(
                    [
                        json.dumps({"event": "action_started", "action_id": "act-fault", "seq": 0, "at": 1}),
                        json.dumps(
                            {
                                "event": "terminal_message",
                                "message_type": "result",
                                "action_id": "act-fault",
                                "code": "adapter_faulted",
                                "lifecycle": lifecycle("act-fault") | {"faulted": True},
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            status = read_status(db, started, log)
            self.assertEqual(status["adapter_faults"], 1)
            self.assertEqual(status["adapter_invalid_lifecycle_log"], 0)
            self.assertEqual(status["adapter_log_summary"]["entries"], 2)


class FakeProtocolEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_agent = brain_main.agent
        self.original_sessions = brain_main.adapter_sessions
        brain_main.agent = SessionAgent(Path(self.tmp.name))
        brain_main.adapter_sessions = brain_main.AdapterSessionRegistry()

    def tearDown(self) -> None:
        brain_main.agent.memory.close()
        brain_main.agent = self.original_agent
        brain_main.adapter_sessions = self.original_sessions
        self.tmp.cleanup()

    def run_ready(self, awaitable):
        stack = [awaitable.__await__()]
        value = None
        while stack:
            try:
                yielded = stack[-1].send(value)
            except StopIteration as done:
                stack.pop()
                value = done.value
                continue
            if hasattr(yielded, "__await__"):
                stack.append(yielded.__await__())
                value = None
                continue
            if yielded is None:
                value = None
                continue
            raise AssertionError(f"fake protocol test awaited non-ready object: {yielded!r}")
        return value

    class FakeWebSocket:
        def __init__(self, messages: list[dict] | None = None, exception: Exception | None = None) -> None:
            self.messages = [json.dumps(message) for message in (messages or [])]
            self.exception = exception
            self.raised = False
            self.closed = False
            self.close_code = None
            self.close_reason = None

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            if self.messages:
                return self.messages.pop(0)
            if self.exception is not None and not self.raised:
                self.raised = True
                raise self.exception
            raise StopAsyncIteration

        async def close(self, code: int = 1000, reason: str = "") -> None:
            self.closed = True
            self.close_code = code
            self.close_reason = reason

    def hello(self, *, adapter_id: str = "adapter-1", session_id: str = "session-1") -> dict:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "type": "hello",
            "client": "mineflayer-adapter",
            "role": "mineflayer_adapter",
            "adapter_id": adapter_id,
            "session_id": session_id,
            "adapter_version": "test-adapter",
        }

    def result_for(self, action_id: str, *, ok: bool, after: dict, code: str | None = None) -> dict:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "result",
            "action_id": action_id,
            "ok": ok,
            "elapsed_ms": 1,
            "before_state": obs(oak_logs=1, inventory_count=0),
            "after_state": after,
            "lifecycle": lifecycle(action_id, ok=ok, code=code),
        }
        if code:
            payload["code"] = code
            payload["error"] = code
        return payload

    def test_handle_message_persists_invalid_observation_protocol_error(self) -> None:
        async def run_case() -> None:
            await brain_main.handle_message(
                object(),
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "observation",
                    "request_id": "obs-bad",
                    "timestamp_ms": 1,
                    "state": {"health": None},
                },
            )

        self.run_ready(run_case())
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        code = conn.execute("SELECT code FROM protocol_errors").fetchone()[0]
        conn.close()
        self.assertEqual(code, "invalid_object")

    def test_handle_message_result_for_wrong_action_does_not_mutate_pending(self) -> None:
        async def run_case() -> str:
            agent = brain_main.agent
            agent.set_goal("gather 16 oak_log")
            action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=15))
            await brain_main.handle_message(
                object(),
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "result",
                    "action_id": "act-wrong",
                    "ok": True,
                    "elapsed_ms": 1,
                    "before_state": obs(oak_logs=1, inventory_count=15),
                    "after_state": obs(inventory_count=16),
                    "lifecycle": lifecycle("act-wrong"),
                },
            )
            return action_id

        expected_id = self.run_ready(run_case())
        self.assertEqual(brain_main.agent.active_action_id(), expected_id)
        self.assertEqual(brain_main.agent.memory.count(), 0)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        code = conn.execute("SELECT code FROM protocol_errors").fetchone()[0]
        conn.close()
        self.assertEqual(code, "stale_adapter_session")

    def test_temporary_goal_client_close_while_adapter_action_pending_does_not_finalize(self) -> None:
        agent = brain_main.agent
        agent.set_goal("gather 16 oak_log")
        action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
        self.run_ready(
            brain_main.handler(
                self.FakeWebSocket([
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "type": "command",
                        "command": "status",
                        "requested_by": "test-status-client",
                    }
                ])
            )
        )
        self.assertEqual(agent.active_action_id(), action_id)
        self.assertFalse(agent.paused)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        attempts = conn.execute("SELECT COUNT(*) FROM skill_attempts").fetchone()[0]
        outcome = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertEqual(attempts, 0)
        self.assertEqual(outcome, "running")

    def test_second_adapter_session_cannot_submit_result_for_active_run(self) -> None:
        async def run_case() -> tuple[bool, int | None, str | None]:
            agent = brain_main.agent
            agent.set_goal("gather 16 oak_log")
            action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
            first = self.FakeWebSocket()
            second = self.FakeWebSocket()
            await brain_main.handle_message(first, self.hello(adapter_id="adapter-1", session_id="session-1"))
            await brain_main.handle_message(second, self.hello(adapter_id="adapter-1", session_id="session-2"))
            await brain_main.handle_message(second, self.result_for(action_id, ok=True, after=obs(inventory_count=1)))
            return second.closed, second.close_code, agent.active_action_id()

        closed, close_code, active_action_id = self.run_ready(run_case())
        self.assertTrue(closed)
        self.assertEqual(close_code, 4001)
        self.assertIsNotNone(active_action_id)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        codes = [row[0] for row in conn.execute("SELECT code FROM protocol_errors").fetchall()]
        attempts = conn.execute("SELECT COUNT(*) FROM skill_attempts").fetchone()[0]
        conn.close()
        self.assertIn("adapter_session_conflict", codes)
        self.assertIn("stale_adapter_session", codes)
        self.assertEqual(attempts, 0)

    def test_reconnect_registers_new_session_and_old_session_results_are_stale(self) -> None:
        async def run_case() -> tuple[str | None, str | None]:
            agent = brain_main.agent
            agent.set_goal("gather 16 oak_log")
            action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
            old_ws = self.FakeWebSocket()
            new_ws = self.FakeWebSocket()
            await brain_main.handle_message(old_ws, self.hello(adapter_id="adapter-1", session_id="old-session"))
            brain_main.adapter_sessions.disconnect(old_ws)
            await brain_main.handle_message(new_ws, self.hello(adapter_id="adapter-1", session_id="new-session"))
            await brain_main.handle_message(old_ws, self.result_for(action_id, ok=True, after=obs(inventory_count=1)))
            return brain_main.adapter_sessions.session_id, agent.active_action_id()

        session_id, active_action_id = self.run_ready(run_case())
        self.assertEqual(session_id, "new-session")
        self.assertIsNone(active_action_id)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        codes = [row[0] for row in conn.execute("SELECT code FROM protocol_errors").fetchall()]
        attempts = conn.execute("SELECT COUNT(*), MAX(failure_code) FROM skill_attempts").fetchone()
        run = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertIn("stale_adapter_session", codes)
        self.assertEqual(attempts, (1, "adapter_disconnect_before_terminal"))
        self.assertEqual(run, "unsafe")

    def test_real_adapter_normal_close_before_result_finalizes_pending_action(self) -> None:
        agent = brain_main.agent
        agent.set_goal("gather 16 oak_log")
        action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
        self.run_ready(brain_main.handler(self.FakeWebSocket([self.hello()])))
        self.assertIsNone(agent.active_action_id())
        self.assertTrue(agent.paused)
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        stored = conn.execute("SELECT action_id, failure_code FROM skill_attempts").fetchone()
        conn.close()
        self.assertEqual(run[0], "unsafe")
        self.assertIn("adapter_disconnect_before_terminal", run[1])
        self.assertEqual(stored, (action_id, "adapter_disconnect_before_terminal"))

    def test_real_adapter_normal_close_after_result_does_not_overwrite_terminal_result(self) -> None:
        agent = brain_main.agent
        agent.set_goal("gather 16 oak_log")
        action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
        self.run_ready(
            brain_main.handler(
                self.FakeWebSocket([
                    self.hello(),
                    self.result_for(action_id, ok=False, after=obs(oak_logs=1), code="timeout"),
                ])
            )
        )
        self.assertIsNone(agent.active_action_id())
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        attempts = conn.execute("SELECT COUNT(*), MAX(failure_code) FROM skill_attempts").fetchone()
        run = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertEqual(attempts, (1, "timeout"))
        self.assertEqual(run, "running")

    def test_real_adapter_exception_close_before_result_finalizes_pending_action(self) -> None:
        agent = brain_main.agent
        agent.set_goal("gather 16 oak_log")
        action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
        websocket = self.FakeWebSocket([self.hello()], exception=brain_main.websockets.ConnectionClosedOK(None, None))
        self.run_ready(brain_main.handler(websocket))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        stored = conn.execute("SELECT action_id, failure_code FROM skill_attempts").fetchone()
        conn.close()
        self.assertEqual(run[0], "unsafe")
        self.assertIn("adapter_disconnect_before_terminal", run[1])
        self.assertEqual(stored, (action_id, "adapter_disconnect_before_terminal"))

    def test_real_adapter_repeated_close_is_idempotent(self) -> None:
        agent = brain_main.agent
        agent.set_goal("gather 16 oak_log")
        agent.next_action(obs(oak_logs=1, inventory_count=0))
        websocket = self.FakeWebSocket([self.hello()])
        self.run_ready(brain_main.handler(websocket))
        brain_main.adapter_sessions.disconnect(websocket)
        self.run_ready(brain_main.handler(self.FakeWebSocket()))
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        attempts = conn.execute("SELECT COUNT(*) FROM skill_attempts").fetchone()[0]
        run = conn.execute("SELECT outcome FROM runs").fetchone()[0]
        conn.close()
        self.assertEqual(attempts, 1)
        self.assertEqual(run, "unsafe")

    def test_unavailable_gather_delivery_persists_recoverable_attempt(self) -> None:
        agent = brain_main.agent
        agent.set_goal("gather 16 oak_log")
        action_id, _ = agent.next_action(obs(oak_logs=1, inventory_count=0))
        self.run_ready(
            brain_main.handler(
                self.FakeWebSocket([
                    self.hello(),
                    self.result_for(action_id, ok=False, after=obs(), code="unavailable"),
                ])
            )
        )
        conn = sqlite3.connect(Path(self.tmp.name) / "experiences.db")
        run = conn.execute("SELECT outcome, evidence_json FROM runs").fetchone()
        stored = conn.execute("SELECT action_id, outcome, failure_code, result_json FROM skill_attempts").fetchone()
        conn.close()
        self.assertEqual(run[0], "running")
        self.assertIsNone(run[1])
        self.assertEqual(stored[0], action_id)
        self.assertEqual(stored[1], "unavailable")
        self.assertEqual(stored[2], "unavailable")
        self.assertIn("lifecycle", stored[3])


if __name__ == "__main__":
    unittest.main()
