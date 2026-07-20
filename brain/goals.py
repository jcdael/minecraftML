from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal


GoalKind = Literal["gather", "bootstrap", "unsupported", "unknown"]


@dataclass(slots=True)
class Goal:
    kind: GoalKind
    raw_text: str
    parameters: dict[str, Any] = field(default_factory=dict)
    unsupported_reason: str | None = None

    def describe(self) -> str:
        if self.kind == "gather":
            return f"gather {self.parameters['count']} {self.parameters['item']}"
        if self.kind == "bootstrap":
            return f"bootstrap {self.parameters['count']} {self.parameters['item']}"
        if self.kind == "unsupported":
            return f"unsupported goal: {self.raw_text}"
        return "unknown goal"


def _normalize_item(value: str) -> str:
    value = value.lower().strip().replace("minecraft:", "")
    value = re.sub(r"[^a-z0-9_ ]", "", value).replace(" ", "_")
    aliases = {
        "wood": "oak_log",
        "logs": "oak_log",
        "log": "oak_log",
        "oak_logs": "oak_log",
    }
    return aliases.get(value, value)


def parse_goal(text: str) -> Goal:
    raw = text.strip()
    lowered = raw.lower().strip()

    if "ender dragon" in lowered or lowered in {"beat minecraft", "beat the game", "beat dragon"}:
        return Goal("unsupported", raw, unsupported_reason="beat_dragon is out of scope for Phase 1")
    if "house" in lowered or "base" in lowered or "build" in lowered:
        return Goal("unsupported", raw, unsupported_reason="building is out of scope for Phase 1")

    bootstrap_match = re.fullmatch(r"bootstrap\s+(?:(\d+)\s+)?iron_ingot", lowered)
    if bootstrap_match:
        count = int(bootstrap_match.group(1) or 1)
        if count != 1:
            return Goal("unsupported", raw, unsupported_reason="only bootstrap 1 iron_ingot is implemented in Phase 2")
        return Goal("bootstrap", raw, {"item": "iron_ingot", "count": 1})

    gather_match = re.fullmatch(
        r"(?:gather|collect|get|find|mine)\s+(?:(\d+)\s+)?(?:of\s+)?([a-z0-9_: ]+)",
        lowered,
    )
    if gather_match:
        count = int(gather_match.group(1) or 1)
        item = _normalize_item(gather_match.group(2))
        if item != "oak_log":
            return Goal("unsupported", raw, unsupported_reason="only oak_log gathering is implemented in Phase 1")
        return Goal("gather", raw, {"item": "oak_log", "count": max(1, min(count, 64))})

    return Goal("unknown", raw)
