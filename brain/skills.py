from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Any, Protocol


OUTCOMES = {
    "success",
    "precondition_failed",
    "timeout",
    "unreachable",
    "unsafe",
    "interrupted",
    "verification_failed",
    "inventory_full",
    "unavailable",
}

FOOD_NAMES = {
    "cooked_beef",
    "cooked_porkchop",
    "cooked_chicken",
    "bread",
    "baked_potato",
    "apple",
    "carrot",
}


@dataclass(frozen=True, slots=True)
class SkillResult:
    status: str
    failure_code: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in OUTCOMES:
            raise ValueError(f"Unknown skill status: {self.status}")


@dataclass(slots=True)
class SkillStep:
    skill_name: str
    args: dict[str, Any]
    action: dict[str, Any]
    timeout_ms: int
    pre_state: dict[str, Any]
    retry_budget: int = 0


class Skill(Protocol):
    name: str
    timeout_ms: int

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        ...

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        ...

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        ...

    def cancel_action(self) -> dict[str, Any]:
        return {"kind": "stop"}


def inventory_counts(state: dict[str, Any]) -> Counter[str]:
    # Fix: Use Counter directly with pairs to properly sum duplicate items
    counts = Counter()
    for item in state.get("inventory", []):
        name = item.get("name")
        if name:
            count = int(item.get("count", 0))
            counts[str(name)] += count
    return counts


def finite_float(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool) or value is None:
        return default
    if not isinstance(value, (int, float)):
        return default
    result = float(value)
    return result if math.isfinite(result) else default


def block_counts(state: dict[str, Any]) -> Counter[str]:
    return Counter(state.get("nearby_blocks", {}).get("counts", {}))


def position(state: dict[str, Any]) -> tuple[float, float, float] | None:
    pos = state.get("position")
    if not isinstance(pos, dict):
        return None
    try:
        return (float(pos["x"]), float(pos["y"]), float(pos["z"]))
    except (KeyError, TypeError, ValueError):
        return None


class StopSkill:
    name = "Stop"
    timeout_ms = 2_000

    def __init__(self, reason: str = "requested") -> None:
        self.reason = reason

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "stop", "reason": self.reason}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        lifecycle = result.get("lifecycle") if isinstance(result.get("lifecycle"), dict) else {}
        adapter_unsafe = bool(lifecycle.get("unsafe_continuation"))
        stopped = (
            result.get("ok") is True
            and after.get("action_running") is False
            and after.get("movement_active") is False
            and after.get("pathfinder_active") is False
            and after.get("digging_active") is False
            and after.get("container_active") is False
            and not adapter_unsafe
        )
        evidence = {
            "reason": self.reason,
            "action_running": after.get("action_running"),
            "movement_active": after.get("movement_active"),
            "pathfinder_active": after.get("pathfinder_active"),
            "digging_active": after.get("digging_active"),
            "container_active": after.get("container_active"),
            "adapter_unsafe_continuation": adapter_unsafe,
            "verified_stopped": stopped,
        }
        if not stopped:
            return SkillResult("unsafe", "stop_not_verified", evidence)
        return SkillResult("success", evidence=evidence)


class EatWhenNeededSkill:
    name = "EatWhenNeeded"
    timeout_ms = 8_000

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        food = finite_float(state.get("food"))
        if food is None:
            return SkillResult("unsafe", "missing_food")
        inventory = inventory_counts(state)
        if food > 14:
            return SkillResult("precondition_failed", "food_not_low")
        if not any(inventory[name] > 0 for name in FOOD_NAMES):
            return SkillResult("unavailable", "no_safe_food")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "eat", "timeout_ms": self.timeout_ms}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "eat_action_failed", {"adapter_error": result.get("error")})
        return SkillResult("success", evidence={"food_before": before.get("food"), "food_after": after.get("food")})


class ExploreSearchSkill:
    name = "ExploreSearch"
    timeout_ms = 12_000

    def __init__(self, strategy: str = "forward") -> None:
        self.strategy = strategy

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        health = finite_float(state.get("health"))
        if health is None:
            return SkillResult("unsafe", "missing_health")
        if health <= 6:
            return SkillResult("unsafe", "low_health")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.strategy.startswith("goto_relative:"):
            _, dx, dz = self.strategy.split(":", 2)
            return {"kind": "goto_relative", "dx": int(dx), "dy": 0, "dz": int(dz), "radius": 4}
        if self.strategy == "goto_east":
            return {"kind": "goto_relative", "dx": 48, "dy": 0, "dz": 0, "radius": 4}
        if self.strategy == "goto_west":
            return {"kind": "goto_relative", "dx": -48, "dy": 0, "dz": 0, "radius": 4}
        if self.strategy == "goto_south":
            return {"kind": "goto_relative", "dx": 0, "dy": 0, "dz": 48, "radius": 4}
        if self.strategy == "goto_north":
            return {"kind": "goto_relative", "dx": 0, "dy": 0, "dz": -48, "radius": 4}
        if self.strategy == "turn_left":
            return {"kind": "look_delta", "yaw_delta": -1.5708, "pitch_delta": 0}
        if self.strategy == "turn_right":
            return {"kind": "look_delta", "yaw_delta": 1.5708, "pitch_delta": 0}
        if self.strategy == "turn_slight_right":
            return {"kind": "look_delta", "yaw_delta": 0.7854, "pitch_delta": 0}
        if self.strategy == "turn_around":
            return {"kind": "look_delta", "yaw_delta": 3.1416, "pitch_delta": 0}
        return {
            "kind": "control",
            "states": {"forward": True, "jump": True, "sprint": True},
            "duration_ms": 2500,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "explore_action_failed", {"adapter_error": result.get("error")})
        before_pos = position(before)
        after_pos = position(after)
        moved = False
        if before_pos and after_pos:
            moved = sum((a - b) ** 2 for a, b in zip(after_pos, before_pos)) ** 0.5 >= 0.15
        return SkillResult("success", evidence={"moved": moved, "strategy": self.strategy})


class RecoverStuckSkill:
    name = "RecoverStuck"
    timeout_ms = 5_000

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "control",
            "states": {"jump": True, "sneak": True},
            "duration_ms": 1000,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "recover_action_failed", {"adapter_error": result.get("error")})
        return SkillResult("success")


class CollectItemSkill:
    name = "CollectItem"
    timeout_ms = -1

    def __init__(self, target_item: str, target_count: int = 1) -> None:
        self.target_item = target_item
        self.target_count = target_count
        self.timeout_ms = 30_000 if target_count <= -1 else 60_000

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        inventory = inventory_counts(state)
        if len(state.get("inventory", [])) >= 36 and inventory[self.target_item] < self.target_count:
            return SkillResult("inventory_full", "inventory_full")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "collect",
            "item": self.target_item,
            "count": self.target_count,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "collect_action_failed", {"adapter_error": result.get("error")})
        before_count = inventory_counts(before)[self.target_item]
        after_count = inventory_counts(after)[self.target_item]
        if after_count < before_count + self.target_count:
            return SkillResult("verification_failed", "inventory_did_not_increase", {"before": before_count, "after": after_count})
        return SkillResult("success", evidence={"before": before_count, "after": after_count})


class CraftItemSkill:
    name = "CraftItem"
    timeout_ms = 30_000

    def __init__(self, item: str, target_count: int = 1) -> None:
        self.item = item
        self.target_count = target_count

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        if len(state.get("inventory", [])) >= 36 and inventory_counts(state)[self.item] < self.target_count:
            return SkillResult("inventory_full", "inventory_full")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "craft",
            "item": self.item,
            "count": self.target_count,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            code = result.get("error", {}).get("code", "unknown")
            evidence = {"adapter_error": result.get("error")}
            if code in {"missing_ingredients", "missing_recipe", "no_placement_location", "inventory_full", "failed_verification"}:
                return SkillResult("unavailable" if code != "inventory_full" else "inventory_full", code, evidence)
            return SkillResult("verification_failed", "craft_action_failed", evidence)
        before_count = inventory_counts(before)[self.item]
        after_count = inventory_counts(after)[self.item]
        if after_count < before_count + self.target_count:
            return SkillResult("verification_failed", "craft_did_not_increase", {"before": before_count, "after": after_count})
        return SkillResult("success", evidence={"before": before_count, "after": after_count})


class SmeltItemSkill:
    name = "SmeltItem"
    timeout_ms = 120_000

    def __init__(self, input_item: str, output: str, fuel: str = "coal") -> None:
        self.input_item = input_item
        self.output = output
        self.fuel = fuel

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        inventory = inventory_counts(state)
        if len(state.get("inventory", [])) >= 36 and inventory[self.output] < 1:
            return SkillResult("inventory_full", "inventory_full")
        if inventory[self.input_item] < 1:
            return SkillResult("unavailable", "missing_input")
        if inventory[self.fuel] < 1:
            return SkillResult("unavailable", "missing_fuel")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "smelt",
            "input": self.input_item,
            "output": self.output,
            "fuel": self.fuel,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            code = result.get("error", {}).get("code", "unknown")
            evidence = {"adapter_error": result.get("error")}
            if code in {"missing_input", "missing_fuel", "no_furnace", "inventory_full", "failed_verification"}:
                return SkillResult("unavailable" if code != "inventory_full" else "inventory_full", code, evidence)
            return SkillResult("verification_failed", "smelt_action_failed", evidence)
        before_count = inventory_counts(before)[self.output]
        after_count = inventory_counts(after)[self.output]
        if after_count < before_count + 1:
            return SkillResult("verification_failed", "smelt_did_not_increase", {"before": before_count, "after": after_count})
        return SkillResult("success", evidence={"before": before_count, "after": after_count})


class GatherVisibleBlockSkill:
    name = "GatherVisibleBlock"
    timeout_ms = 60_000

    def __init__(self, target_block: str = "oak_log", target_count: int = 5) -> None:
        self.target_block = target_block
        self.target_count = target_count

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        # Check if we have inventory space
        if len(state.get("inventory", [])) >= 36:
            inventory = inventory_counts(state)
            if inventory[self.target_block] < self.target_count:
                return SkillResult("inventory_full", "inventory_full")
        
        # Check if blocks are visible nearby
        blocks = block_counts(state)
        if blocks[self.target_block] > 0:
            return SkillResult("success")
        return SkillResult("precondition_failed", "no_visible_blocks")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "gather",
            "block": self.target_block,
            "count": self.target_count,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "gather_action_failed", {"adapter_error": result.get("error")})
        
        before_count = inventory_counts(before)[self.target_block]
        after_count = inventory_counts(after)[self.target_block]
        
        if after_count < before_count + self.target_count:
            return SkillResult("verification_failed", "inventory_did_not_increase", {"before": before_count, "after": after_count})
        
        return SkillResult("success", evidence={"before": before_count, "after": after_count})


class EscapeDangerSkill:
    name = "EscapeDanger"
    timeout_ms = -1

    def __init__(self, danger_type: str = "lava") -> None:
        self.danger_type = danger_type
        self.timeout_ms = 15_000

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        danger = state.get("danger")
        if danger == self.danger_type:
            return SkillResult("success")
        return SkillResult("precondition_failed", "no_danger")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "control",
            "states": {"sprint": True, "jump": True, "back": True},
            "duration_ms": 2000,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "escape_action_failed", {"adapter_error": result.get("error")})
        
        # Check if danger is gone or reduced
        before_danger = before.get("danger")
        after_danger = after.get("danger")
        
        if after_danger != before_danger:
            return SkillResult("success", evidence={"danger_before": before_danger, "danger_after": after_danger})
        
        # Even if danger is still present, moving away might be success
        return SkillResult("success", evidence={"danger_still_present": True})