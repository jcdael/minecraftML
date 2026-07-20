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
    return Counter(
        {
            str(item.get("name")): int(item.get("count", 0))
            for item in state.get("inventory", [])
            if item.get("name")
        }
    )


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
        return {"kind": "control", "states": {"back": True, "sneak": True}, "duration_ms": 750}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "recover_action_failed", {"adapter_error": result.get("error")})
        return SkillResult("success", evidence={"position_before": before.get("position"), "position_after": after.get("position")})


class EscapeDangerSkill:
    name = "EscapeDanger"
    timeout_ms = 6_000

    def __init__(self, danger: str) -> None:
        self.danger = danger

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        if self.danger not in {"drowning", "fire", "fall"}:
            return SkillResult("precondition_failed", "unsupported_danger")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.danger == "drowning":
            return {"kind": "control", "states": {"forward": True, "jump": True, "sprint": True}, "duration_ms": 3500}
        return {"kind": "control", "states": {"back": True, "sneak": True}, "duration_ms": 900}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        if not result.get("ok"):
            return SkillResult("verification_failed", "escape_action_failed", {"adapter_error": result.get("error")})
        escaped = after.get("danger") != self.danger
        return SkillResult("success" if escaped else "verification_failed", None if escaped else "danger_still_present", {
            "danger_before": self.danger,
            "danger_after": after.get("danger"),
        })


class GatherVisibleBlockSkill:
    name = "GatherVisibleBlock"
    timeout_ms = 8_000

    def __init__(
        self,
        block: str,
        target_item: str,
        target_count: int,
        max_distance: int = 64,
        timeout_ms: int | None = None,
    ) -> None:
        self.block = block
        self.target_item = target_item
        self.target_count = target_count
        self.max_distance = max_distance
        if timeout_ms is not None:
            self.timeout_ms = timeout_ms

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        inventory = inventory_counts(state)
        if len(state.get("inventory", [])) >= 36 and inventory[self.target_item] < self.target_count:
            return SkillResult("inventory_full", "inventory_full")
        if block_counts(state)[self.block] <= 0:
            return SkillResult("precondition_failed", "missing_visible_block")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "mine_nearest", "block": self.block, "max_distance": self.max_distance, "timeout_ms": self.timeout_ms}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        before_count = inventory_counts(before)[self.target_item]
        after_count = inventory_counts(after)[self.target_item]
        if after_count > before_count:
            return SkillResult(
                "success",
                evidence={
                    "before_count": before_count,
                    "after_count": after_count,
                    "target_count": self.target_count,
                    "adapter_ok": bool(result.get("ok")),
                    "adapter_code": result.get("code"),
                    "adapter_error": result.get("error"),
                },
            )
        if not result.get("ok"):
            code = str(result.get("code") or result.get("error_code") or "")
            if code == "adapter_faulted":
                return SkillResult("unsafe", "adapter_faulted", {"adapter_error": result.get("error")})
            if "interrupted" in code:
                return SkillResult("interrupted", "interrupted", {"before": before_count, "after": after_count})
            if "unreachable" in code:
                return SkillResult("unreachable", "unreachable", {"before": before_count, "after": after_count})
            if "timeout" in code:
                return SkillResult("timeout", "timeout", {"before": before_count, "after": after_count})
            if "unavailable" in code:
                return SkillResult("unavailable", "unavailable", {"before": before_count, "after": after_count})
            return SkillResult("verification_failed", "adapter_action_failed", {"adapter_error": result.get("error")})
        return SkillResult(
            "verification_failed",
            "inventory_did_not_increase",
            {"before_count": before_count, "after_count": after_count},
        )


class CraftItemSkill:
    name = "CraftItem"
    timeout_ms = 20_000

    def __init__(self, item: str, target_count: int, use_crafting_table: bool = False) -> None:
        self.item = item
        self.target_count = target_count
        self.use_crafting_table = use_crafting_table

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        if len(state.get("inventory", [])) >= 36 and inventory_counts(state)[self.item] < self.target_count:
            return SkillResult("inventory_full", "inventory_full")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        current = inventory_counts(state)[self.item]
        return {
            "kind": "craft",
            "item": self.item,
            "count": max(1, self.target_count - current),
            "use_crafting_table": self.use_crafting_table,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        before_count = inventory_counts(before)[self.item]
        after_count = inventory_counts(after)[self.item]
        evidence = {
            "item": self.item,
            "before_count": before_count,
            "after_count": after_count,
            "target_count": self.target_count,
            "used_crafting_table": self.use_crafting_table,
            "adapter_detail": result.get("detail"),
            "adapter_code": result.get("code"),
            "adapter_error": result.get("error"),
        }
        if after_count >= self.target_count and after_count > before_count:
            return SkillResult("success", evidence=evidence)
        code = str(result.get("code") or "")
        if code in {"missing_ingredients", "missing_recipe", "no_placement_location", "inventory_full", "failed_verification"}:
            return SkillResult("unavailable" if code != "inventory_full" else "inventory_full", code, evidence)
        if not result.get("ok"):
            return SkillResult("verification_failed", code or "craft_action_failed", evidence)
        return SkillResult("verification_failed", "craft_output_not_verified", evidence)


class PlaceBlockSkill:
    name = "PlaceBlock"
    timeout_ms = 20_000

    def __init__(self, item: str) -> None:
        self.item = item

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        if inventory_counts(state)[self.item] <= 0:
            return SkillResult("unavailable", "missing_ingredients")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "place_block", "item": self.item, "timeout_ms": self.timeout_ms}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        before_count = block_counts(before)[self.item]
        after_count = block_counts(after)[self.item]
        evidence = {
            "item": self.item,
            "nearby_before": before_count,
            "nearby_after": after_count,
            "adapter_detail": result.get("detail"),
            "adapter_code": result.get("code"),
            "adapter_error": result.get("error"),
        }
        if result.get("ok") and after_count > before_count:
            return SkillResult("success", evidence=evidence)
        code = str(result.get("code") or "")
        if code in {"missing_ingredients", "no_placement_location", "failed_verification"}:
            return SkillResult("unavailable", code, evidence)
        return SkillResult("verification_failed", code or "place_block_not_verified", evidence)


class GotoSiteSkill:
    name = "GotoSite"
    timeout_ms = 60_000

    def __init__(self, site: str, x: float, y: float, z: float) -> None:
        self.site = site
        self.x = x
        self.y = y
        self.z = z

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "goto", "x": self.x, "y": self.y, "z": self.z, "radius": 3, "timeout_ms": self.timeout_ms}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        evidence = {
            "site": self.site,
            "target": {"x": self.x, "y": self.y, "z": self.z},
            "nearby_after": block_counts(after)[self.site],
            "adapter_error": result.get("error"),
            "adapter_code": result.get("code"),
        }
        if result.get("ok") and block_counts(after)[self.site] > 0:
            return SkillResult("success", evidence=evidence)
        code = str(result.get("code") or "")
        if code in {"timeout", "unreachable"}:
            return SkillResult("timeout" if code == "timeout" else "unreachable", code, evidence)
        if not result.get("ok"):
            return SkillResult("verification_failed", code or "goto_site_failed", evidence)
        return SkillResult("verification_failed", "site_not_found_after_goto", evidence)


class EquipItemSkill:
    name = "EquipItem"
    timeout_ms = 4_000

    def __init__(self, item: str) -> None:
        self.item = item

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        if inventory_counts(state)[self.item] <= 0:
            return SkillResult("unavailable", "missing_required_tool")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "equip", "item": self.item, "destination": "hand", "timeout_ms": self.timeout_ms}

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        held = after.get("held_item") if isinstance(after.get("held_item"), dict) else {}
        evidence = {"item": self.item, "held_item": held, "adapter_error": result.get("error")}
        if result.get("ok") and held.get("name") == self.item:
            return SkillResult("success", evidence=evidence)
        code = str(result.get("code") or "")
        if code == "unavailable":
            return SkillResult("unavailable", "missing_required_tool", evidence)
        return SkillResult("verification_failed", code or "equip_not_verified", evidence)


class SmeltItemSkill:
    name = "SmeltItem"
    timeout_ms = 120_000

    def __init__(self, input_item: str = "raw_iron", fuel: str = "coal", output: str = "iron_ingot", target_count: int = 1) -> None:
        self.input_item = input_item
        self.fuel = fuel
        self.output = output
        self.target_count = target_count

    def can_start(self, state: dict[str, Any]) -> SkillResult:
        inventory = inventory_counts(state)
        if inventory[self.input_item] <= 0:
            return SkillResult("unavailable", "missing_ingredients")
        if inventory[self.fuel] <= 0:
            return SkillResult("unavailable", "missing_fuel")
        if block_counts(state)["furnace"] <= 0:
            return SkillResult("unavailable", "missing_furnace")
        return SkillResult("success")

    def build_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "smelt",
            "input": self.input_item,
            "fuel": self.fuel,
            "output": self.output,
            "count": self.target_count,
            "timeout_ms": self.timeout_ms,
        }

    def verify(self, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> SkillResult:
        before_count = inventory_counts(before)[self.output]
        after_count = inventory_counts(after)[self.output]
        before_input = inventory_counts(before)[self.input_item]
        before_fuel = inventory_counts(before)[self.fuel]
        detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
        furnace = detail.get("furnace") if isinstance(detail.get("furnace"), dict) else {}
        input_evidence = furnace.get("input_slot") if isinstance(furnace.get("input_slot"), dict) else None
        fuel_evidence = furnace.get("fuel_slot") if isinstance(furnace.get("fuel_slot"), dict) else None
        output_evidence = furnace.get("output_slot_before_take") if isinstance(furnace.get("output_slot_before_take"), dict) else None
        pending_container = int(detail.get("container_pending") or 0) if isinstance(detail.get("container_pending") or 0, int) else 1
        evidence = {
            "input": self.input_item,
            "fuel": self.fuel,
            "output": self.output,
            "input_before": before_input,
            "fuel_before": before_fuel,
            "output_before": before_count,
            "output_after": after_count,
            "target_count": self.target_count,
            "adapter_detail": detail,
            "furnace_transition": {
                "input_slot": input_evidence,
                "fuel_slot": fuel_evidence,
                "output_slot_before_take": output_evidence,
                "container_pending": pending_container,
            },
            "container_active_after": after.get("container_active"),
            "adapter_code": result.get("code"),
            "adapter_error": result.get("error"),
        }
        valid_furnace_evidence = (
            before_input >= self.target_count
            and before_fuel >= 1
            and isinstance(input_evidence, dict)
            and input_evidence.get("name") == self.input_item
            and isinstance(fuel_evidence, dict)
            and fuel_evidence.get("name") == self.fuel
            and isinstance(output_evidence, dict)
            and output_evidence.get("name") == self.output
            and int(output_evidence.get("count") or 0) >= self.target_count
            and pending_container == 0
            and after.get("container_active") is False
        )
        if result.get("ok") is True and after_count >= self.target_count and after_count > before_count and valid_furnace_evidence:
            return SkillResult("success", evidence=evidence)
        code = str(result.get("code") or "")
        if code in {"missing_ingredients", "missing_fuel", "missing_furnace", "missing_recipe", "timeout"}:
            return SkillResult("timeout" if code == "timeout" else "unavailable", code, evidence)
        if not result.get("ok"):
            return SkillResult("verification_failed", code or "smelt_action_failed", evidence)
        if pending_container != 0 or after.get("container_active") is not False:
            return SkillResult("verification_failed", "container_still_active", evidence)
        if not valid_furnace_evidence:
            return SkillResult("verification_failed", "missing_furnace_transition_evidence", evidence)
        return SkillResult("verification_failed", "smelt_output_not_verified", evidence)
