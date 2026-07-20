from __future__ import annotations

from collections import deque
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from goals import Goal, parse_goal
from memory import ExperienceStore
from protocol import validate_action, validate_message, validate_observation_state
from skills import (
    CraftItemSkill,
    EquipItemSkill,
    EscapeDangerSkill,
    ExploreSearchSkill,
    GatherVisibleBlockSkill,
    GotoSiteSkill,
    PlaceBlockSkill,
    RecoverStuckSkill,
    Skill,
    SkillResult,
    SkillStep,
    SmeltItemSkill,
    StopSkill,
    block_counts,
    inventory_counts,
    position,
)
from supervisor import SafetySupervisor


AGENT_POLICY_VERSION = "phase2-bootstrap-iron-v1"
SPIRAL_STEP_BLOCKS = 48
MAX_SPIRAL_DISTANCE = 64
MAX_ACTIONS_PER_RUN = 250
MAX_RUN_SECONDS = 900
BOOTSTRAP_STONE_MINE_RADIUS = 12
BOOTSTRAP_ORE_MINE_RADIUS = 16
BOOTSTRAP_WOOD_MINE_RADIUS = 24
BOOTSTRAP_WOOD_TIMEOUT_MS = 20_000
STOPPED_ACTION = {"kind": "noop"}
REACHABLE_SAMPLE_DY = {
    "oak_log": (-2, 3),
    "birch_log": (-2, 3),
    "stone": (-2, 3),
    "cobblestone": (-2, 3),
    "coal_ore": (-2, 3),
    "iron_ore": (-2, 3),
    "deepslate_iron_ore": (-2, 3),
}
REACHABLE_SAMPLE_HORIZONTAL = {
    "oak_log": BOOTSTRAP_WOOD_MINE_RADIUS,
    "birch_log": BOOTSTRAP_WOOD_MINE_RADIUS,
    "stone": BOOTSTRAP_STONE_MINE_RADIUS,
    "cobblestone": BOOTSTRAP_STONE_MINE_RADIUS,
    "coal_ore": BOOTSTRAP_ORE_MINE_RADIUS,
    "iron_ore": BOOTSTRAP_ORE_MINE_RADIUS,
    "deepslate_iron_ore": BOOTSTRAP_ORE_MINE_RADIUS,
}


class SessionAgent:
    def __init__(self, data_dir: Path) -> None:
        self.paused = True
        self.goal: Goal | None = None
        self.memory = ExperienceStore(data_dir / "experiences.db")
        self.supervisor = SafetySupervisor()
        self.pending: SkillStep | None = None
        self.pending_action_id: str | None = None
        self.pending_started_at = 0.0
        self.completed_action_ids: set[str] = set()
        self.cancel_requested_for: set[str] = set()
        self.last_observation: dict[str, Any] | None = None
        self.completed = False
        self.run_id: int | None = None
        self.recent_positions: deque[tuple[float, float, float]] = deque(maxlen=8)
        self.stuck_recoveries = 0
        self.max_stuck_recoveries = 10
        self.initial_inventory_empty: bool | None = None
        self.exploration_index = 0
        self.spiral_direction_index = 0
        self.spiral_leg_length = 1
        self.spiral_legs_at_length = 0
        self.consecutive_gather_failures = 0
        self.actions_started = 0
        self.max_actions_per_run = MAX_ACTIONS_PER_RUN
        self.goal_started_at = 0.0
        self.max_run_seconds = MAX_RUN_SECONDS
        self.bootstrap_completed_steps: set[str] = set()
        self.bootstrap_forced_search_steps = 0
        self.bootstrap_prospect_steps = 0
        self.bootstrap_sites: dict[str, tuple[float, float, float]] = {}
        self.bootstrap_smelt_evidence: dict[str, Any] | None = None
        self.awaiting_death_respawn = False
        self.death_action_id: str | None = None
        self.death_recorded_at = 0.0

    def set_goal(self, text: str) -> str:
        self._interrupt_active_run("new_goal_started")
        goal = parse_goal(text)
        self.goal = goal
        self.pending = None
        self.pending_action_id = None
        self.completed = False
        self.stuck_recoveries = 0
        self.initial_inventory_empty = None
        self.exploration_index = 0
        self.spiral_direction_index = 0
        self.spiral_leg_length = 1
        self.spiral_legs_at_length = 0
        self.consecutive_gather_failures = 0
        self.actions_started = 0
        self.bootstrap_completed_steps.clear()
        self.bootstrap_forced_search_steps = 0
        self.bootstrap_prospect_steps = 0
        self.bootstrap_sites.clear()
        self.bootstrap_smelt_evidence = None
        self.awaiting_death_respawn = False
        self.death_action_id = None
        self.death_recorded_at = 0.0
        self.goal_started_at = time.monotonic()
        self.recent_positions.clear()
        if goal.kind in {"gather", "bootstrap"}:
            self.paused = False
            self.run_id = self.memory.start_run(
                goal=goal.describe(),
                target_item=str(goal.parameters["item"]),
                target_count=int(goal.parameters["count"]),
            )
            return f"Goal accepted: {goal.describe()}"
        self.paused = True
        reason = goal.unsupported_reason or "Use exactly: gather 16 oak_log or bootstrap 1 iron_ingot"
        return f"Unsupported Phase 1 goal: {reason}"

    def set_paused(self, value: bool) -> str:
        self.paused = value
        return "Agent paused" if value else "Agent resumed"

    def status(self) -> str:
        goal = self.goal.describe() if self.goal else "none"
        return f"Goal: {goal}; paused={self.paused}; completed={self.completed}; attempts={self.memory.count()}"

    def next_action(self, observation: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        state_validation = validate_observation_state(observation)
        if not state_validation.ok:
            self.memory.add_protocol_error(
                code=state_validation.code or "invalid_observation",
                message=state_validation.message or "invalid observation",
                payload={"state": observation},
            )
            return self._new_action(StopSkill("invalid_observation"), self._minimal_safe_state())

        self.last_observation = observation
        if self.goal and self.goal.kind in {"gather", "bootstrap"} and self.initial_inventory_empty is None:
            self.initial_inventory_empty = sum(inventory_counts(observation).values()) == 0
        self._track_position(observation)

        if self.awaiting_death_respawn:
            self._complete_death_after_respawn(observation)
            return None

        if self.pending is not None:
            raise RuntimeError("action already pending; cancel it instead of submitting a competing action")

        if self.paused or not self.goal or self.goal.kind not in {"gather", "bootstrap"}:
            return None
        if self.completed:
            return None
        goal_complete_action = self._goal_complete_action(observation)
        if goal_complete_action is not None:
            return goal_complete_action
        if self.actions_started >= self.max_actions_per_run:
            return self._new_action(StopSkill("run_action_budget_exhausted"), observation)
        if self.goal_started_at and time.monotonic() - self.goal_started_at >= self.max_run_seconds:
            return self._new_action(StopSkill("run_time_budget_exhausted"), observation)

        supervised = self.supervisor.evaluate(observation)
        if supervised.skill is not None:
            return self._new_action(supervised.skill, observation)

        if self.goal.kind == "bootstrap":
            return self._next_bootstrap_action(observation)

        item = str(self.goal.parameters["item"])
        target = int(self.goal.parameters["count"])
        inventory = inventory_counts(observation)

        visible = block_counts(observation)["oak_log"]
        if visible > 0:
            if self.consecutive_gather_failures >= 3:
                self.consecutive_gather_failures = 0
                return self._new_action(ExploreSearchSkill(self._next_spiral_strategy()), observation)
            return self._new_action(GatherVisibleBlockSkill("oak_log", item, target), observation)

        if self._is_stuck():
            if self.stuck_recoveries >= self.max_stuck_recoveries:
                self.stuck_recoveries = 0
            else:
                self.stuck_recoveries += 1
                return self._new_action(RecoverStuckSkill(), observation)

        strategy = self._next_exploration_strategy()
        return self._new_action(ExploreSearchSkill(strategy), observation)

    def _goal_complete_action(self, observation: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        if not self.goal:
            return None
        inventory = inventory_counts(observation)
        if self.goal.kind == "bootstrap" and inventory["iron_ingot"] >= 1:
            self.completed = True
            self.paused = True
            return self._new_action(StopSkill("verified_goal_complete"), observation)
        if self.goal.kind == "gather":
            item = str(self.goal.parameters["item"])
            target = int(self.goal.parameters["count"])
            if inventory[item] >= target:
                self.completed = True
                self.paused = True
                return self._new_action(StopSkill("verified_goal_complete"), observation)
        return None

    def on_result(self, result: dict[str, Any]) -> SkillResult | None:
        validation = validate_message(result, direction="adapter_to_brain")
        if not validation.ok:
            self.memory.add_protocol_error(
                code=validation.code or "invalid_result",
                message=validation.message or "invalid result",
                action_id=result.get("action_id") if isinstance(result, dict) else None,
                payload=result if isinstance(result, dict) else {"payload": result},
            )
            return None
        if not self.pending or not self.pending_action_id:
            action_id = str(result.get("action_id", ""))
            self.memory.add_protocol_error(
                code="duplicate_action_id" if action_id in self.completed_action_ids else "stale_action_id",
                message="result arrived with no matching pending action",
                action_id=action_id or None,
                payload=result,
            )
            return None
        result_action_id = result.get("action_id")
        if result_action_id != self.pending_action_id:
            self.memory.add_protocol_error(
                code="mismatched_action_id",
                message=f"expected {self.pending_action_id}, got {result_action_id}",
                action_id=str(result_action_id) if result_action_id else None,
                payload=result,
            )
            return None
        if result_action_id in self.completed_action_ids:
            self.memory.add_protocol_error(
                code="duplicate_action_id",
                message="duplicate result for completed action",
                action_id=str(result_action_id),
                payload=result,
            )
            return None
        pending = self.pending
        elapsed_ms = int((time.monotonic() - self.pending_started_at) * 1000)
        after = result.get("after_state") or self.last_observation or {}
        skill_result = (
            self._adapter_terminal_result(result)
            if result.get("code") in {"adapter_faulted"}
            else self._verify_result(pending, after, result)
        )
        reward = self._reward_for(pending, skill_result)

        evidence = dict(skill_result.evidence)
        if pending.skill_name == "RecoverStuck":
            self.recent_positions.clear()
        if pending.skill_name == "PlaceBlock" and skill_result.status == "success":
            detail = skill_result.evidence.get("adapter_detail")
            if isinstance(detail, dict):
                placed_item = str(detail.get("item") or "")
                placed_position = detail.get("position")
                if placed_item in {"crafting_table", "furnace"} and isinstance(placed_position, dict):
                    try:
                        self.bootstrap_sites[placed_item] = (
                            float(placed_position["x"]),
                            float(placed_position["y"]),
                            float(placed_position["z"]),
                        )
                    except (KeyError, TypeError, ValueError):
                        pass
        if pending.skill_name == "GotoSite" and skill_result.status != "success":
            site = str(pending.args.get("site") or "")
            self.bootstrap_sites.pop(site, None)
        if pending.skill_name == "SmeltItem" and skill_result.status == "success":
            self.bootstrap_smelt_evidence = {"action_id": self.pending_action_id, **evidence}
        if pending.skill_name == "GatherVisibleBlock":
            if skill_result.status == "success":
                self.consecutive_gather_failures = 0
            else:
                self.consecutive_gather_failures += 1
        if self.goal and self.goal.kind in {"gather", "bootstrap"}:
            item = str(self.goal.parameters["item"])
            target = int(self.goal.parameters["count"])
            count = inventory_counts(after)[item]
            if pending.skill_name == "Stop" and self.completed and count >= target and skill_result.status == "success":
                evidence.update({"verified_item": item, "verified_count": count, "target_count": target})
                evidence.update(
                    {
                        "verified_goal_complete": True,
                        "initial_inventory_empty": bool(self.initial_inventory_empty),
                    }
                )
                if self.goal.kind == "bootstrap":
                    evidence.update(self._bootstrap_final_evidence(after))
                if self.run_id is not None:
                    self.memory.complete_run(
                        run_id=self.run_id,
                        outcome="success",
                        final_inventory=dict(inventory_counts(after)),
                        evidence=evidence,
                    )
            elif pending.skill_name == "Stop" and self.completed and count >= target:
                self.paused = True
                if self.run_id is not None:
                    self.memory.complete_run(
                        run_id=self.run_id,
                        outcome="unsafe",
                        final_inventory=dict(inventory_counts(after)),
                        evidence={"failure_code": skill_result.failure_code or "stop_not_verified", **evidence},
                    )
            elif pending.skill_name == "Stop" and pending.args.get("reason") != "verified_goal_complete":
                terminal_reasons = {
                    "low_health",
                    "missing_health",
                    "missing_food",
                    "drowning",
                    "fire",
                    "fall",
                    "low_food_no_safe_food",
                    "inventory_full",
                    "invalid_observation",
                    "stuck_retry_budget_exhausted",
                    "run_action_budget_exhausted",
                    "run_time_budget_exhausted",
                }
                reason = str(pending.args.get("reason"))
                if reason in terminal_reasons or reason.startswith("invalid_action_"):
                    self.paused = True
                    if self.run_id is not None:
                        self.memory.complete_run(
                            run_id=self.run_id,
                            outcome="unsafe" if reason not in {"inventory_full"} else "inventory_full",
                            final_inventory=dict(inventory_counts(after)),
                            evidence={"failure_code": reason, **evidence},
                        )

        self.memory.add_skill_attempt(
            goal=self.goal.describe() if self.goal else None,
            subgoal=self._subgoal(),
            action_id=self.pending_action_id,
            skill_name=pending.skill_name,
            skill_args=pending.args,
            state_before=pending.pre_state,
            selected_action=pending.action,
            state_after=after,
            elapsed_ms=elapsed_ms,
            outcome=skill_result.status,
            failure_code=skill_result.failure_code,
            reward=reward,
            agent_policy_version=AGENT_POLICY_VERSION,
            result=result,
            completion_evidence=evidence if evidence else None,
        )

        if skill_result.status in {"timeout", "unreachable", "unsafe", "inventory_full", "unavailable"}:
            recoverable_skills = {"GatherVisibleBlock", "EscapeDanger", "ExploreSearch", "RecoverStuck", "GotoSite"}
            terminal = (
                skill_result.status in {"unsafe", "inventory_full"}
                or (skill_result.status == "unavailable" and pending.skill_name not in recoverable_skills)
                or (skill_result.status != "unavailable" and pending.skill_name not in recoverable_skills)
            )
            if terminal:
                self.paused = True
            if terminal and self.run_id is not None:
                self.memory.complete_run(
                    run_id=self.run_id,
                    outcome=skill_result.status,
                    final_inventory=dict(inventory_counts(after)),
                    evidence={"failure_code": skill_result.failure_code, **evidence},
                )

        self.completed_action_ids.add(self.pending_action_id)
        self.cancel_requested_for.discard(self.pending_action_id)
        self.pending = None
        self.pending_action_id = None
        return skill_result

    def _adapter_terminal_result(self, result: dict[str, Any]) -> SkillResult:
        lifecycle = result.get("lifecycle") if isinstance(result.get("lifecycle"), dict) else {}
        code = str(result.get("code") or "adapter_faulted")
        evidence = {
            "adapter_code": code,
            "adapter_error": result.get("error"),
            "adapter_fault_reason": lifecycle.get("fault_reason") or result.get("error"),
            "adapter_faulted": bool(lifecycle.get("faulted")),
            "adapter_action_id": result.get("action_id"),
            "adapter_lifecycle": lifecycle,
        }
        return SkillResult("unsafe", code, evidence)

    def on_cancel_ack(self, message: dict[str, Any]) -> None:
        validation = validate_message(message, direction="adapter_to_brain")
        if not validation.ok:
            self.memory.add_protocol_error(
                code=validation.code or "invalid_cancel_ack",
                message=validation.message or "invalid cancel acknowledgement",
                action_id=message.get("action_id") if isinstance(message, dict) else None,
                payload=message if isinstance(message, dict) else {"payload": message},
            )
            return
        action_id = str(message.get("action_id"))
        if action_id != self.pending_action_id:
            self.memory.add_protocol_error(
                code="mismatched_cancel_ack",
                message=f"cancel acknowledgement for non-active action {action_id}",
                action_id=action_id,
                payload=message,
            )
            return
        if message.get("ok") is True:
            after = message.get("after_state") or {}
            lifecycle = message.get("lifecycle") or {}
            inactive = (
                after.get("action_running") is False
                and after.get("movement_active") is False
                and after.get("pathfinder_active") is False
                and after.get("digging_active") is False
                and after.get("container_active") is False
                and lifecycle.get("unsafe_continuation") is False
            )
            if not inactive:
                self.memory.add_protocol_error(
                    code="cancel_not_quiescent",
                    message="successful cancel acknowledgement did not prove quiescence",
                    action_id=action_id,
                    payload=message,
                )
        self.cancel_requested_for.add(action_id)

    def on_death(self, action_id: str | None = None) -> None:
        self.paused = True
        if action_id and self.pending_action_id and action_id != self.pending_action_id:
            self.memory.add_protocol_error(
                code="mismatched_event_action_id",
                message="death event action id does not match active action",
                action_id=action_id,
            )
        self.awaiting_death_respawn = True
        self.death_action_id = action_id
        self.death_recorded_at = time.monotonic()
        self.completed = True
        self.pending = None
        self.pending_action_id = None

    def _complete_death_after_respawn(self, observation: dict[str, Any]) -> None:
        inactive = (
            observation.get("action_running") is False
            and observation.get("movement_active") is False
            and observation.get("pathfinder_active") is False
            and observation.get("digging_active") is False
            and observation.get("container_active") is False
        )
        if not inactive or float(observation.get("health", 0)) <= 0:
            return
        self.awaiting_death_respawn = False
        self.paused = True
        self.completed = True
        if self.run_id is not None:
            evidence = {
                "failure_code": "death",
                "death_interrupted": True,
                "respawn_observed": True,
                "pending_work_cleared": self.pending is None and self.pending_action_id is None,
                "adapter_action_id": self.death_action_id,
                "verified_stopped": True,
                "verified_stopped_state": {
                    "action_running": observation.get("action_running"),
                    "movement_active": observation.get("movement_active"),
                    "pathfinder_active": observation.get("pathfinder_active"),
                    "digging_active": observation.get("digging_active"),
                    "container_active": observation.get("container_active"),
                },
                "inventory": dict(inventory_counts(observation)),
                "position": observation.get("position"),
            }
            self.memory.complete_run(
                run_id=self.run_id,
                outcome="death",
                final_inventory=dict(inventory_counts(observation)),
                evidence=evidence,
            )

    def on_adapter_disconnect(self) -> SkillResult | None:
        if not self.pending or not self.pending_action_id:
            return None
        pending = self.pending
        action_id = self.pending_action_id
        elapsed_ms = int((time.monotonic() - self.pending_started_at) * 1000)
        after = self.last_observation or pending.pre_state or self._minimal_safe_state()
        evidence = {
            "failure_code": "adapter_disconnect_before_terminal",
            "adapter_action_id": action_id,
            "adapter_disconnect_before_terminal": True,
        }
        result = {
            "type": "result",
            "action_id": action_id,
            "ok": False,
            "code": "adapter_disconnect_before_terminal",
            "error": "adapter connection closed before terminal result",
            "after_state": after,
        }
        self.memory.add_skill_attempt(
            goal=self.goal.describe() if self.goal else None,
            subgoal=self._subgoal(),
            action_id=action_id,
            skill_name=pending.skill_name,
            skill_args=pending.args,
            state_before=pending.pre_state,
            selected_action=pending.action,
            state_after=after,
            elapsed_ms=elapsed_ms,
            outcome="unsafe",
            failure_code="adapter_disconnect_before_terminal",
            reward=-2.0,
            agent_policy_version=AGENT_POLICY_VERSION,
            result=result,
            completion_evidence=evidence,
        )
        if self.run_id is not None:
            self.memory.complete_run(
                run_id=self.run_id,
                outcome="unsafe",
                final_inventory=dict(inventory_counts(after)),
                evidence=evidence,
            )
        self.completed_action_ids.add(action_id)
        self.cancel_requested_for.discard(action_id)
        self.pending = None
        self.pending_action_id = None
        self.paused = True
        return SkillResult("unsafe", "adapter_disconnect_before_terminal", evidence)

    def active_action_id(self) -> str | None:
        return self.pending_action_id

    def request_cancel_active(self, reason: str) -> str | None:
        if not self.pending_action_id:
            self._interrupt_active_run(reason)
            return None
        self.paused = True
        self.cancel_requested_for.add(self.pending_action_id)
        return self.pending_action_id

    def _new_action(self, skill: Skill, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        precondition = skill.can_start(state)
        if precondition.status != "success":
            skill = StopSkill(precondition.failure_code or precondition.status)
        action = skill.build_action(state)
        validation = validate_action(action)
        if not validation.ok:
            skill = StopSkill(f"invalid_action_{validation.code}")
            action = skill.build_action(state)

        action_id = f"act-{uuid4().hex}"
        self.actions_started += 1
        self.pending = SkillStep(
            skill_name=skill.name,
            args=self._skill_args(skill),
            action=action,
            timeout_ms=skill.timeout_ms,
            pre_state=state,
        )
        self.pending_action_id = action_id
        self.pending_started_at = time.monotonic()
        return action_id, action

    def _minimal_safe_state(self) -> dict[str, Any]:
        return {
            "position": {"x": 0, "y": 0, "z": 0},
            "velocity": {"x": 0, "y": 0, "z": 0},
            "health": 0,
            "food": 0,
            "inventory": [],
            "nearby_blocks": {"counts": {}, "samples": []},
            "nearby_entities": [],
            "action_running": False,
            "movement_active": False,
            "pathfinder_active": False,
            "digging_active": False,
            "container_active": False,
            "danger": None,
        }

    def _interrupt_active_run(self, reason: str) -> None:
        if self.run_id is not None:
            self.memory.interrupt_open_runs(
                reason=reason,
                final_inventory=dict(inventory_counts(self.last_observation or {})),
            )

    def _verify_result(self, pending: SkillStep, after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if pending.skill_name == "GatherVisibleBlock":
            skill = GatherVisibleBlockSkill(
                str(pending.args["block"]),
                str(pending.args["target_item"]),
                int(pending.args["target_count"]),
                int(pending.args.get("max_distance", 64)),
            )
        elif pending.skill_name == "ExploreSearch":
            skill = ExploreSearchSkill(str(pending.args.get("strategy", "forward")))
        elif pending.skill_name == "RecoverStuck":
            skill = RecoverStuckSkill()
        elif pending.skill_name == "EscapeDanger":
            skill = EscapeDangerSkill(str(pending.args.get("danger", "drowning")))
        elif pending.skill_name == "CraftItem":
            skill = CraftItemSkill(
                str(pending.args["item"]),
                int(pending.args["target_count"]),
                bool(pending.args.get("use_crafting_table", False)),
            )
        elif pending.skill_name == "PlaceBlock":
            skill = PlaceBlockSkill(str(pending.args["item"]))
        elif pending.skill_name == "GotoSite":
            skill = GotoSiteSkill(
                str(pending.args["site"]),
                float(pending.args["x"]),
                float(pending.args["y"]),
                float(pending.args["z"]),
            )
        elif pending.skill_name == "EquipItem":
            skill = EquipItemSkill(str(pending.args["item"]))
        elif pending.skill_name == "SmeltItem":
            skill = SmeltItemSkill(
                str(pending.args.get("input", "raw_iron")),
                str(pending.args.get("fuel", "coal")),
                str(pending.args.get("output", "iron_ingot")),
                int(pending.args.get("target_count", 1)),
            )
        else:
            skill = StopSkill(str(pending.args.get("reason", "result")))
        return skill.verify(pending.pre_state, after, result)

    def _skill_args(self, skill: Skill) -> dict[str, Any]:
        if isinstance(skill, GatherVisibleBlockSkill):
            return {
                "block": skill.block,
                "target_item": skill.target_item,
                "target_count": skill.target_count,
                "max_distance": skill.max_distance,
            }
        if isinstance(skill, ExploreSearchSkill):
            return {"strategy": skill.strategy}
        if isinstance(skill, EscapeDangerSkill):
            return {"danger": skill.danger}
        if isinstance(skill, CraftItemSkill):
            return {"item": skill.item, "target_count": skill.target_count, "use_crafting_table": skill.use_crafting_table}
        if isinstance(skill, PlaceBlockSkill):
            return {"item": skill.item}
        if isinstance(skill, GotoSiteSkill):
            return {"site": skill.site, "x": skill.x, "y": skill.y, "z": skill.z}
        if isinstance(skill, EquipItemSkill):
            return {"item": skill.item}
        if isinstance(skill, SmeltItemSkill):
            return {"input": skill.input_item, "fuel": skill.fuel, "output": skill.output, "target_count": skill.target_count}
        if isinstance(skill, StopSkill):
            return {"reason": skill.reason}
        return {}

    def _subgoal(self) -> str | None:
        if not self.goal or self.goal.kind not in {"gather", "bootstrap"}:
            return None
        return f"obtain {self.goal.parameters['count']} {self.goal.parameters['item']}"

    def _next_bootstrap_action(self, observation: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        inventory = inventory_counts(observation)
        blocks = block_counts(observation)

        if inventory["iron_ingot"] >= 1:
            self.completed = True
            self.paused = True
            return self._new_action(StopSkill("verified_goal_complete"), observation)

        ready_to_smelt = inventory["coal"] >= 1 and inventory["raw_iron"] >= 1
        if ready_to_smelt:
            self.bootstrap_forced_search_steps = 0

        if self.bootstrap_forced_search_steps > 0:
            self.bootstrap_forced_search_steps -= 1
            return self._bootstrap_search_or_recover(observation)

        early_bootstrap = (
            inventory["wooden_pickaxe"] < 1
            and inventory["stone_pickaxe"] < 1
            and inventory["cobblestone"] < 1
            and inventory["furnace"] < 1
            and blocks["furnace"] < 1
        )

        if (
            early_bootstrap
            and
            inventory["oak_log"] < 3
            and inventory["oak_planks"] < 9
            and inventory["crafting_table"] < 1
            and blocks["crafting_table"] < 1
        ):
            if blocks["oak_log"] > 0:
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill(
                        "oak_log",
                        "oak_log",
                        3,
                        max_distance=BOOTSTRAP_WOOD_MINE_RADIUS,
                        timeout_ms=BOOTSTRAP_WOOD_TIMEOUT_MS,
                    ),
                    observation,
                )
            return self._bootstrap_search_or_recover(observation)

        if early_bootstrap and inventory["oak_planks"] < 9 and inventory["crafting_table"] < 1 and blocks["crafting_table"] < 1:
            return self._new_action(CraftItemSkill("oak_planks", 12), observation)

        if early_bootstrap and inventory["crafting_table"] < 1 and blocks["crafting_table"] < 1:
            return self._new_action(CraftItemSkill("crafting_table", 1), observation)

        if early_bootstrap and blocks["crafting_table"] < 1:
            return self._new_action(PlaceBlockSkill("crafting_table"), observation)

        held = observation.get("held_item") if isinstance(observation.get("held_item"), dict) else {}
        needs_stone_pickaxe = inventory["stone_pickaxe"] < 1 and not ready_to_smelt
        required_cobblestone = 3 if needs_stone_pickaxe else (
            8 if inventory["furnace"] < 1 and blocks["furnace"] < 1 and "furnace" not in self.bootstrap_sites else 0
        )
        needs_crafting_table = needs_stone_pickaxe or (
            inventory["furnace"] < 1
            and blocks["furnace"] < 1
            and "furnace" not in self.bootstrap_sites
        )

        if (
            held.get("name") != "wooden_pickaxe"
            and inventory["wooden_pickaxe"] >= 1
            and inventory["stone_pickaxe"] < 1
            and inventory["cobblestone"] < required_cobblestone
        ):
            return self._new_action(EquipItemSkill("wooden_pickaxe"), observation)

        if (
            required_cobblestone
            and inventory["cobblestone"] < required_cobblestone
            and held.get("name") not in {"wooden_pickaxe", "stone_pickaxe"}
        ):
            if inventory["stone_pickaxe"] >= 1:
                return self._new_action(EquipItemSkill("stone_pickaxe"), observation)
            if inventory["wooden_pickaxe"] >= 1:
                return self._new_action(EquipItemSkill("wooden_pickaxe"), observation)

        has_stone_tool = inventory["wooden_pickaxe"] >= 1 or inventory["stone_pickaxe"] >= 1
        if required_cobblestone and has_stone_tool and inventory["cobblestone"] < required_cobblestone:
            if blocks["stone"] > 0:
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill(
                        "stone",
                        "cobblestone",
                        required_cobblestone,
                        max_distance=BOOTSTRAP_STONE_MINE_RADIUS,
                    ),
                    observation,
                )
            if blocks["cobblestone"] > 0:
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill(
                        "cobblestone",
                        "cobblestone",
                        required_cobblestone,
                        max_distance=BOOTSTRAP_STONE_MINE_RADIUS,
                    ),
                    observation,
                )
            return self._bootstrap_search_or_recover(observation)

        if needs_crafting_table and blocks["crafting_table"] < 1:
            if inventory["crafting_table"] >= 1:
                return self._new_action(PlaceBlockSkill("crafting_table"), observation)
            table_site = self._goto_known_site("crafting_table")
            if table_site is not None:
                return self._new_action(table_site, observation)
            if inventory["oak_planks"] < 4:
                if inventory["oak_log"] < 1:
                    if blocks["oak_log"] > 0:
                        return self._bootstrap_gather_or_search(
                            GatherVisibleBlockSkill(
                                "oak_log",
                                "oak_log",
                                1,
                                max_distance=BOOTSTRAP_WOOD_MINE_RADIUS,
                                timeout_ms=BOOTSTRAP_WOOD_TIMEOUT_MS,
                            ),
                            observation,
                        )
                    return self._bootstrap_search_or_recover(observation)
                return self._new_action(CraftItemSkill("oak_planks", 4), observation)
            return self._new_action(CraftItemSkill("crafting_table", 1), observation)

        can_recover_stone_pickaxe = needs_stone_pickaxe and inventory["cobblestone"] >= 3
        required_sticks = 0 if inventory["stone_pickaxe"] >= 1 or ready_to_smelt else (
            2 if inventory["wooden_pickaxe"] >= 1 or can_recover_stone_pickaxe else 4
        )
        if inventory["stick"] < required_sticks:
            return self._new_action(CraftItemSkill("stick", required_sticks), observation)

        if can_recover_stone_pickaxe:
            return self._new_action(CraftItemSkill("stone_pickaxe", 1, use_crafting_table=True), observation)

        if inventory["wooden_pickaxe"] < 1 and inventory["stone_pickaxe"] < 1:
            return self._new_action(CraftItemSkill("wooden_pickaxe", 1, use_crafting_table=True), observation)

        if needs_stone_pickaxe:
            return self._new_action(CraftItemSkill("stone_pickaxe", 1, use_crafting_table=True), observation)

        if inventory["furnace"] < 1 and blocks["furnace"] < 1 and "furnace" not in self.bootstrap_sites:
            table_site = self._goto_known_site("crafting_table")
            if table_site is not None and blocks["crafting_table"] < 1:
                return self._new_action(table_site, observation)
            return self._new_action(CraftItemSkill("furnace", 1, use_crafting_table=True), observation)

        if blocks["furnace"] < 1 and "furnace" not in self.bootstrap_sites:
            furnace_site = self._goto_known_site("furnace")
            if furnace_site is not None and inventory["furnace"] < 1:
                return self._new_action(furnace_site, observation)
            return self._new_action(PlaceBlockSkill("furnace"), observation)

        if held.get("name") != "stone_pickaxe" and (inventory["coal"] < 1 or inventory["raw_iron"] < 1):
            return self._new_action(EquipItemSkill("stone_pickaxe"), observation)

        if inventory["coal"] < 1:
            if self._has_reachable_sample(observation, "coal_ore"):
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill("coal_ore", "coal", 1, max_distance=BOOTSTRAP_ORE_MINE_RADIUS),
                    observation,
                )
            return self._bootstrap_search_or_recover(observation)

        if inventory["raw_iron"] < 1:
            if self._has_reachable_sample(observation, "iron_ore"):
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill("iron_ore", "raw_iron", 1, max_distance=BOOTSTRAP_ORE_MINE_RADIUS),
                    observation,
                )
            if self._has_reachable_sample(observation, "deepslate_iron_ore"):
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill(
                        "deepslate_iron_ore",
                        "raw_iron",
                        1,
                        max_distance=BOOTSTRAP_ORE_MINE_RADIUS,
                    ),
                    observation,
                )
            if self._has_reachable_sample(observation, "stone") and self.bootstrap_prospect_steps < 24:
                self.bootstrap_prospect_steps += 1
                return self._bootstrap_gather_or_search(
                    GatherVisibleBlockSkill(
                        "stone",
                        "cobblestone",
                        inventory["cobblestone"] + 1,
                        max_distance=BOOTSTRAP_STONE_MINE_RADIUS,
                    ),
                    observation,
                )
            return self._bootstrap_search_or_recover(observation)

        if blocks["furnace"] < 1:
            furnace_site = self._goto_known_site("furnace")
            if furnace_site is not None:
                return self._new_action(furnace_site, observation)

        return self._new_action(SmeltItemSkill(), observation)

    def _goto_known_site(self, site: str) -> GotoSiteSkill | None:
        position = self.bootstrap_sites.get(site)
        if position is None:
            return None
        x, y, z = position
        return GotoSiteSkill(site, x, y, z)

    def _bootstrap_gather_or_search(
        self,
        skill: GatherVisibleBlockSkill,
        observation: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if self.consecutive_gather_failures >= 3:
            self.consecutive_gather_failures = 0
            self.bootstrap_forced_search_steps = 4
            return self._bootstrap_search_or_recover(observation)
        return self._new_action(skill, observation)

    def _bootstrap_search_or_recover(self, observation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if self._is_stuck() and self.stuck_recoveries < self.max_stuck_recoveries:
            self.stuck_recoveries += 1
            return self._new_action(RecoverStuckSkill(), observation)
        return self._new_action(ExploreSearchSkill(self._next_exploration_strategy()), observation)

    def _has_reachable_sample(self, observation: dict[str, Any], block_name: str) -> bool:
        nearby = observation.get("nearby_blocks") if isinstance(observation.get("nearby_blocks"), dict) else {}
        samples = nearby.get("samples") if isinstance(nearby.get("samples"), list) else []
        min_dy, max_dy = REACHABLE_SAMPLE_DY.get(block_name, (-2, 3))
        max_horizontal = REACHABLE_SAMPLE_HORIZONTAL.get(block_name, 16)
        for sample in samples:
            if not isinstance(sample, dict) or sample.get("name") != block_name:
                continue
            try:
                dy = int(sample.get("dy", 999))
                dx = float(sample.get("dx", 999))
                dz = float(sample.get("dz", 999))
            except (TypeError, ValueError):
                continue
            if min_dy <= dy <= max_dy and (dx * dx + dz * dz) ** 0.5 <= max_horizontal:
                return True
        return False

    def _bootstrap_final_evidence(self, state: dict[str, Any]) -> dict[str, Any]:
        inventory = dict(inventory_counts(state))
        held = state.get("held_item") if isinstance(state.get("held_item"), dict) else None
        return {
            "phase": "phase2_bootstrap_iron",
            "phase2_bootstrap_iron": True,
            "inventory": inventory,
            "equipped_tools": {
                "held_item": held,
                "wooden_pickaxe_present": inventory.get("wooden_pickaxe", 0) >= 1,
                "stone_pickaxe_present": inventory.get("stone_pickaxe", 0) >= 1,
            },
            "crafted_outputs": {
                "oak_planks": inventory.get("oak_planks", 0),
                "crafting_table_nearby": block_counts(state)["crafting_table"],
                "stick": inventory.get("stick", 0),
                "wooden_pickaxe": inventory.get("wooden_pickaxe", 0),
                "stone_pickaxe": inventory.get("stone_pickaxe", 0),
                "furnace_nearby": block_counts(state)["furnace"],
            },
            "furnace": {
                "input": "raw_iron",
                "fuel": "coal",
                "output": "iron_ingot",
                "iron_ingot": inventory.get("iron_ingot", 0),
            },
            "furnace_transition_evidence": self.bootstrap_smelt_evidence,
            "verified_stopped_state": {
                "action_running": state.get("action_running"),
                "movement_active": state.get("movement_active"),
                "pathfinder_active": state.get("pathfinder_active"),
                "digging_active": state.get("digging_active"),
                "container_active": state.get("container_active"),
            },
        }

    def _reward_for(self, pending: SkillStep, result: SkillResult) -> float:
        if result.status == "success":
            if pending.skill_name == "GatherVisibleBlock":
                return 5.0
            if pending.skill_name == "ExploreSearch":
                return 0.5
            return 1.0
        return -2.0

    def _next_exploration_strategy(self) -> str:
        if self.exploration_index % 5 == 4:
            strategy = self._next_spiral_strategy()
        else:
            strategy = "forward"
        self.exploration_index += 1
        return strategy

    def _next_spiral_strategy(self) -> str:
        directions = ((1, 0), (0, 1), (-1, 0), (0, -1))
        dx_dir, dz_dir = directions[self.spiral_direction_index % len(directions)]
        distance = min(MAX_SPIRAL_DISTANCE, SPIRAL_STEP_BLOCKS * self.spiral_leg_length)
        self.spiral_direction_index += 1
        self.spiral_legs_at_length += 1
        if self.spiral_legs_at_length >= 2:
            self.spiral_legs_at_length = 0
            self.spiral_leg_length += 1
        return f"goto_relative:{dx_dir * distance}:{dz_dir * distance}"

    def _track_position(self, state: dict[str, Any]) -> None:
        pos = position(state)
        if pos:
            self.recent_positions.append(pos)

    def _is_stuck(self) -> bool:
        if len(self.recent_positions) < self.recent_positions.maxlen:
            return False
        first = self.recent_positions[0]
        last = self.recent_positions[-1]
        distance = sum((a - b) ** 2 for a, b in zip(last, first)) ** 0.5
        return distance < 2.0
