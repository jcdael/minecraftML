from __future__ import annotations

import json
import math
from pathlib import Path
import random
from typing import Iterable


class PersistentUCBBandit:
    """Small, transparent online learner for choosing exploration strategies.

    This is intentionally simple. It proves the complete observe -> act -> reward ->
    update -> persist loop before a neural policy is added.
    """

    def __init__(self, arms: Iterable[str], path: Path, exploration: float = 1.4) -> None:
        self.arms = list(arms)
        self.path = path
        self.exploration = exploration
        self.counts = {arm: 0 for arm in self.arms}
        self.values = {arm: 0.0 for arm in self.arms}
        self.load()

    def select(self) -> str:
        untried = [arm for arm in self.arms if self.counts.get(arm, 0) == 0]
        if untried:
            return random.choice(untried)

        total = max(1, sum(self.counts.values()))
        return max(
            self.arms,
            key=lambda arm: self.values[arm]
            + self.exploration * math.sqrt(math.log(total) / self.counts[arm]),
        )

    def update(self, arm: str, reward: float) -> None:
        if arm not in self.counts:
            return
        self.counts[arm] += 1
        count = self.counts[arm]
        old_value = self.values[arm]
        self.values[arm] = old_value + (reward - old_value) / count
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"counts": self.counts, "values": self.values}, indent=2),
            encoding="utf-8",
        )

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for arm in self.arms:
                self.counts[arm] = int(payload.get("counts", {}).get(arm, 0))
                self.values[arm] = float(payload.get("values", {}).get(arm, 0.0))
        except (OSError, ValueError, TypeError):
            # A corrupt learner file should never prevent the agent from starting.
            return
