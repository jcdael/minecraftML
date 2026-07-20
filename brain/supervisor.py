from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from skills import FOOD_NAMES, EatWhenNeededSkill, EscapeDangerSkill, Skill, StopSkill, finite_float, inventory_counts


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    skill: Skill | None
    reason: str | None = None


class SafetySupervisor:
    def evaluate(self, state: dict[str, Any]) -> SupervisorDecision:
        health = finite_float(state.get("health"))
        food = finite_float(state.get("food"))
        oxygen = finite_float(state.get("oxygen"))
        inventory = inventory_counts(state)
        danger = state.get("danger")

        if health is None:
            return SupervisorDecision(StopSkill("missing_health"), "missing_health")
        if food is None:
            return SupervisorDecision(StopSkill("missing_food"), "missing_food")
        if health <= 6:
            return SupervisorDecision(StopSkill("low_health"), "low_health")
        if danger in {"drowning", "fire", "fall"}:
            return SupervisorDecision(EscapeDangerSkill(str(danger)), str(danger))
        if oxygen is not None and oxygen < 18:
            return SupervisorDecision(EscapeDangerSkill("drowning"), "drowning")
        if food <= 8 and any(inventory[name] > 0 for name in FOOD_NAMES):
            return SupervisorDecision(EatWhenNeededSkill(), "low_food")
        if food <= 0:
            if any(inventory[name] > 0 for name in FOOD_NAMES):
                return SupervisorDecision(EatWhenNeededSkill(), "low_food")
            return SupervisorDecision(StopSkill("low_food_no_safe_food"), "low_food_no_safe_food")
        return SupervisorDecision(None)
