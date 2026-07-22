from __future__ import annotations

import json
import logging
import math
import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from goals import Goal, parse_goal
from learner import PersistentUCBBandit
from memory import ExperienceStore
from skills import (
    CollectItemSkill,
    CraftItemSkill,
    EatWhenNeededSkill,
    ExploreSearchSkill,
    RecoverStuckSkill,
    Skill,
    SkillResult,
    SkillStep,
    SmeltItemSkill,
    StopSkill,
    inventory_counts,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionAgent:
    """Agent that runs a session of skills toward a goal."""

    goal: Goal
    state: dict[str, Any] = field(default_factory=dict)
    steps: list[SkillStep] = field(default_factory=list)
    current_step: SkillStep | None = None
    step_start_time: float | None = None
    step_retries_left: int = 0
    learner: PersistentUCBBandit = field(default_factory=lambda: PersistentUCBBandit(data_dir=Path("data/bandit")))
    session_start_time: float = field(default_factory=time.time)
    last_reward_time: float = field(default_factory=time.time)
    reward_accumulator: float = 0.0
    total_reward: float = 0.0
    last_action: dict[str, Any] | None = None
    last_action_result: dict[str, Any] | None = None
    memory: ExperienceStore = field(default_factory=lambda: ExperienceStore(Path("data/experience.db")))
    is_paused: bool = False
    active_action_id: str | None = None
    last_observation_state: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        logger.info("SessionAgent created for goal: %s", self.goal.describe())
        self.learner.load()

    # New methods required by main.py
    def on_adapter_disconnect(self) -> None:
        """Called when adapter disconnects."""
        logger.info("Adapter disconnected, resetting agent state")
        self.active_action_id = None
        self.current_step = None
        self.step_start_time = None
        self.is_paused = True  # Pause when disconnected

    def request_cancel_active(self, reason: str) -> str | None:
        """Cancel active action and return its action_id."""
        logger.info(f"Requesting cancel of active action: {reason}")
        action_id = self.active_action_id
        self.active_action_id = None
        self.current_step = None
        self.step_start_time = None
        return action_id

    def set_goal(self, text: str) -> str:
        """Parse and set new goal."""
        try:
            new_goal = parse_goal(text)
            self.goal = new_goal
            logger.info(f"Goal set to: {self.goal.describe()}")
            return f"Goal set: {self.goal.describe()}"
        except Exception as e:
            logger.error(f"Failed to parse goal '{text}': {e}")
            return f"Error parsing goal: {e}"

    def set_paused(self, paused: bool) -> str:
        """Pause or resume the agent."""
        self.is_paused = paused
        status = "paused" if paused else "resumed"
        logger.info(f"Agent {status}")
        return f"Agent {status}"

    def status(self) -> str:
        """Return status string."""
        return (
            f"Goal: {self.goal.describe()}, "
            f"Paused: {self.is_paused}, "
            f"Active action: {self.active_action_id}, "
            f"Steps completed: {len(self.steps)}, "
            f"Total reward: {self.total_reward:.2f}"
        )

    def active_action_id(self) -> str | None:
        """Return current action ID or None."""
        return self.active_action_id

    def next_action(self, state: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Get next action based on state, return (action_id, action)."""
        if self.is_paused:
            logger.debug("Agent is paused, not returning action")
            return None
        
        if self.active_action_id is not None:
            logger.debug("Action already active, not returning new action")
            return None
        
        self.state = state.copy()
        self.last_observation_state = state.copy()
        
        # Update reward based on current state
        self.update_reward()
        
        # Choose a new skill
        skill = self.choose_skill()
        if skill is None:
            logger.warning("No skill chosen")
            return None
        
        # Check if skill can start
        can_start = skill.can_start(self.state)
        if can_start.status != "success":
            logger.warning("Skill %s cannot start: %s", skill.name, can_start.failure_code or can_start.status)
            
            # If it's a stop skill that can't start, still execute it
            if isinstance(skill, StopSkill):
                action = skill.build_action(self.state)
            else:
                # Try a recovery skill instead
                recovery = RecoverStuckSkill()
                recovery_can_start = recovery.can_start(self.state)
                if recovery_can_start.status == "success":
                    skill = recovery
                else:
                    # Fall back to stop
                    skill = StopSkill("cannot_start_any_skill")
                action = skill.build_action(self.state)
        else:
            action = skill.build_action(self.state)
        
        # Generate action ID
        action_id = str(uuid.uuid4())
        self.active_action_id = action_id
        
        # Record as current step
        self.current_step = SkillStep(
            skill_name=skill.name,
            args={},
            action=action,
            timeout_ms=skill.timeout_ms,
            pre_state=self.state.copy(),
            retry_budget=3,
        )
        self.current_step.skill_instance = skill  # type: ignore
        self.step_start_time = time.time()
        self.step_retries_left = 3
        
        logger.info(f"Generated action {action_id}: {action.get('kind', 'unknown')}")
        return action_id, action

    def on_result(self, message: dict[str, Any]) -> SkillResult | None:
        """Process result message."""
        action_id = message.get("action_id")
        if action_id != self.active_action_id:
            logger.warning(f"Result for unknown action ID: {action_id}")
            return None
        
        ok = message.get("ok", False)
        code = message.get("code", "unknown")
        
        # Create skill result
        skill_result = SkillResult(
            status="success" if ok else "failure",
            failure_code=None if ok else code,
            elapsed_ms=message.get("elapsed_ms", 0),
            result=message
        )
        
        # Record the step
        if self.current_step and self.step_start_time:
            self.record_step(
                skill=self.current_step.skill_instance,
                action=self.current_step.action,
                result=message,
                skill_result=skill_result
            )
        
        # Clear active action
        self.active_action_id = None
        self.current_step = None
        self.step_start_time = None
        
        # Update bandit with reward
        if self.current_step and isinstance(self.current_step.skill_instance, ExploreSearchSkill):
            strategy = self.current_step.skill_instance.strategy
            reward = self.reward_accumulator
            self.learner.record_attempt(strategy, reward)
            self.reward_accumulator = 0.0
        
        logger.info(f"Processed result for action {action_id}: ok={ok}, code={code}")
        return skill_result

    def on_cancel_ack(self, message: dict[str, Any]) -> None:
        """Process cancel acknowledgment."""
        action_id = message.get("action_id")
        ok = message.get("ok", False)
        logger.info(f"Cancel acknowledgment for action {action_id}: ok={ok}")
        
        if action_id == self.active_action_id:
            self.active_action_id = None
            self.current_step = None
            self.step_start_time = None

    def on_death(self, action_id: str | None) -> None:
        """Handle player death."""
        logger.info(f"Player death recorded, action_id={action_id}")
        self.is_paused = True
        self.active_action_id = None
        self.current_step = None
        self.step_start_time = None

    # Original methods
    def choose_skill(self) -> Skill | None:
        """Choose the next skill to execute based on current state and goal."""
        if self.goal.kind == "gather":
            return self._choose_gather_skill()
        if self.goal.kind == "bootstrap":
            return self._choose_bootstrap_skill()
        if self.goal.kind == "explore":
            return self._choose_explore_skill()
        if self.goal.kind == "unsupported":
            return StopSkill("unsupported_goal")
        return StopSkill("unknown_goal")

    def _choose_gather_skill(self) -> Skill | None:
        """Choose skill for gathering goals."""
        item = self.goal.parameters["item"]
        target_count = self.goal.parameters["count"]
        inventory = inventory_counts(self.state)
        current_count = inventory.get(item, 0)

        if current_count >= target_count:
            logger.info("Goal satisfied: have %d/%d %s", current_count, target_count, item)
            return StopSkill("goal_satisfied")

        # Check if we need to eat
        eat_skill = EatWhenNeededSkill()
        if eat_skill.can_start(self.state).status == "success":
            return eat_skill

        # Check if we're stuck
        if random.random() < 0.1:
            return RecoverStuckSkill()

        # Try to collect the item
        return CollectItemSkill(item, target_count - current_count)

    def _choose_bootstrap_skill(self) -> Skill | None:
        """Choose skill for bootstrap goals."""
        item = self.goal.parameters["item"]
        target_count = self.goal.parameters["count"]
        inventory = inventory_counts(self.state)
        current_count = inventory.get(item, 0)

        if current_count >= target_count:
            logger.info("Goal satisfied: have %d/%d %s", current_count, target_count, item)
            return StopSkill("goal_satisfied")

        # Check if we need to eat
        eat_skill = EatWhenNeededSkill()
        if eat_skill.can_start(self.state).status == "success":
            return eat_skill

        # Bootstrap logic for iron_ingot
        if item == "iron_ingot":
            # Check if we have iron_ore
            iron_ore_count = inventory.get("iron_ore", 0)
            if iron_ore_count > 0:
                # Smelt iron ore
                return SmeltItemSkill("iron_ore", "iron_ingot", "coal")
            
            # Check if we have coal for smelting
            coal_count = inventory.get("coal", 0)
            if coal_count == 0:
                # Need to collect coal first
                return CollectItemSkill("coal", 1)
            
            # Need to collect iron ore
            return CollectItemSkill("iron_ore", 1)

        return StopSkill("unsupported_bootstrap_item")

    def _choose_explore_skill(self) -> Skill | None:
        """Choose skill for exploration goals."""
        radius = self.goal.parameters.get("radius", 100)
        
        # Check if we need to eat
        eat_skill = EatWhenNeededSkill()
        if eat_skill.can_start(self.state).status == "success":
            return eat_skill

        # Check if we're stuck
        if random.random() < 0.1:
            return RecoverStuckSkill()

        # Choose exploration strategy using bandit
        strategies = [
            "forward",
            "turn_left",
            "turn_right",
            "turn_slight_right",
            "turn_around",
            "goto_east",
            "goto_west",
            "goto_south",
            "goto_north",
        ]
        
        # Add relative movement strategies based on radius
        if radius > -1:
            for dx in [-32, -16, 16, 32]:
                for dz in [-32, -16, 16, 32]:
                    if dx != 0 or dz != 0:
                        strategies.append(f"goto_relative:{dx}:{dz}")
        
        # Use bandit to choose strategy
        chosen_idx = self.learner.select_arm(strategies)
        chosen_strategy = strategies[chosen_idx]
        return ExploreSearchSkill(chosen_strategy)

    def update_reward(self) -> None:
        """Calculate and accumulate reward based on progress toward goal."""
        now = time.time()
        time_delta = now - self.last_reward_time
        if time_delta < 1.0:
            return  # Only update once per second
        
        reward = 0.0
        
        if self.goal.kind == "gather":
            item = self.goal.parameters["item"]
            target_count = self.goal.parameters["count"]
            inventory = inventory_counts(self.state)
            current_count = inventory.get(item, 0)
            progress = min(1.0, current_count / target_count) if target_count > 0 else 0.0
            reward = progress * 10.0  # Max 10 reward for completion
            
        elif self.goal.kind == "bootstrap":
            item = self.goal.parameters["item"]
            target_count = self.goal.parameters["count"]
            inventory = inventory_counts(self.state)
            current_count = inventory.get(item, 0)
            progress = min(1.0, current_count / target_count) if target_count > 0 else 0.0
            reward = progress * 15.0  # Bootstrap is harder, more reward
            
        elif self.goal.kind == "explore":
            # Reward for movement and discovering new areas
            pos = self.state.get("position")
            if isinstance(pos, dict):
                x = pos.get("x", 0.0)
                z = pos.get("z", 0.0)
                distance = math.sqrt(x*x + z*z)
                radius = self.goal.parameters.get("radius", 100)
                exploration_progress = min(1.0, distance / radius) if radius > 0 else 0.0
                reward = exploration_progress * 8.0
                
                # Bonus reward for moving
                if self.state.get("movement_active"):
                    reward += 0.1
        
        # Penalty for low health
        health = self.state.get("health")
        if isinstance(health, (int, float)) and health < 10:
            reward -= (10 - health) * 0.5
        
        # Penalty for being stuck (no movement for a while)
        if not self.state.get("movement_active") and random.random() < 0.05:
            reward -= 0.2
        
        self.reward_accumulator += reward
        self.total_reward += reward
        self.last_reward_time = now

    def record_step(
        self,
        skill: Skill,
        action: dict[str, Any],
        result: dict[str, Any],
        skill_result: SkillResult,
    ) -> None:
        """Record a completed skill step."""
        step = SkillStep(
            skill_name=skill.name,
            args={},
            action=action,
            timeout_ms=skill.timeout_ms,
            pre_state=self.state.copy(),
            retry_budget=self.step_retries_left,
        )
        step.skill_instance = skill  # type: ignore
        self.steps.append(step)
        
        logger.info(
            "Step %d: %s -> %s (status=%s)",
            len(self.steps),
            skill.name,
            skill_result.status,
            skill_result.failure_code or "success",
        )
        
        # Reset current step tracking
        self.current_step = None
        self.step_start_time = None
        self.step_retries_left = 0

    def should_retry_step(self, skill_result: SkillResult) -> bool:
        """Determine if we should retry the current step."""
        if self.step_retries_left <= 0:
            return False
        
        retryable_statuses = {
            "precondition_failed",
            "timeout",
            "unreachable",
            "unsafe",
            "interrupted",
            "verification_failed",
        }
        
        if skill_result.status in retryable_statuses:
            self.step_retries_left -= 1
            logger.info("Retrying step, %d retries left", self.step_retries_left)
            return True
        
        return False

    def get_action(self) -> dict[str, Any]:
        """Get the next action to execute, or None if session is complete."""
        # Update reward based on current state
        self.update_reward()
        
        # If we have a current step that's still running, continue with it
        if self.current_step is not None and self.step_start_time is not None:
            elapsed = time.time() - self.step_start_time
            if elapsed * 1000 < self.current_step.timeout_ms:
                # Step is still within timeout, return its action
                return self.current_step.action
        
        # Choose a new skill
        skill = self.choose_skill()
        if skill is None:
            return {"kind": "stop", "reason": "no_skill_chosen"}
        
        # Check if skill can start
        can_start = skill.can_start(self.state)
        if can_start.status != "success":
            logger.warning("Skill %s cannot start: %s", skill.name, can_start.failure_code or can_start.status)
            
            # If it's a stop skill that can't start, still execute it
            if isinstance(skill, StopSkill):
                action = skill.build_action(self.state)
                self.current_step = SkillStep(
                    skill_name=skill.name,
                    args={},
                    action=action,
                    timeout_ms=skill.timeout_ms,
                    pre_state=self.state.copy(),
                    retry_budget=0,
                )
                self.current_step.skill_instance = skill  # type: ignore
                self.step_start_time = time.time()
                self.step_retries_left = 3  # Give stop skills some retries
                return action
            
            # Try a recovery skill instead
            recovery = RecoverStuckSkill()
            recovery_can_start = recovery.can_start(self.state)
            if recovery_can_start.status == "success":
                skill = recovery
            else:
                # Fall back to stop
                skill = StopSkill("cannot_start_any_skill")
        
        # Build and return the action
        action = skill.build_action(self.state)
        
        # Record as current step
        self.current_step = SkillStep(
            skill_name=skill.name,
            args={},
            action=action,
            timeout_ms=skill.timeout_ms,
            pre_state=self.state.copy(),
            retry_budget=3,
        )
        self.current_step.skill_instance = skill  # type: ignore
        self.step_start_time = time.time()
        self.step_retries_left = 3
        
        return action