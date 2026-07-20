from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any

from agent import SessionAgent
from protocol import PROTOCOL_VERSION
from trace_replay import load_trace, record_step, replay_actions, save_trace


def obs(
    *,
    inventory: list[dict[str, Any]] | None = None,
    blocks: dict[str, int] | None = None,
    health: int = 20,
    food: int = 20,
    stopped: bool = True,
    held_item: str | None = None,
    x: float = 0,
) -> dict[str, Any]:
    counts = blocks or {}
    samples = [
        {"name": name, "dx": index + 1, "dy": 0, "dz": 0}
        for name, count in counts.items()
        for index in range(min(int(count), 4))
    ]
    return {
        "position": {"x": x, "y": 64, "z": 0},
        "velocity": {"x": 0, "y": 0, "z": 0},
        "health": health,
        "food": food,
        "inventory": inventory or [],
        "held_item": {"name": held_item, "count": 1} if held_item else None,
        "nearby_blocks": {"counts": counts, "samples": samples},
        "nearby_entities": [],
        "action_running": not stopped,
        "movement_active": not stopped,
        "pathfinder_active": not stopped,
        "digging_active": False,
        "container_active": False,
        "danger": None,
    }


def lifecycle(action_id: str = "trace-action", *, ok: bool = True, code: str | None = None) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "started": 1,
        "abort_requested": None,
        "cleanup_started": 2,
        "cleanup_completed": 3,
        "execution_settled": {"at": 4, "settled": True, "ok": ok},
        "terminal_result": {"at": 5, "ok": ok, "code": code},
        "final_activity_state": {
            "first": _inactive(),
            "final": _inactive(),
            "delayed": _inactive(),
        },
        "unsafe_continuation": False,
        "events": [
            {"seq": 1, "name": "cleanup_started", "at": 2},
            {"seq": 2, "name": "cleanup_completed", "at": 3},
            {"seq": 3, "name": "execution_settled", "at": 4},
            {"seq": 4, "name": "post_stop_probe_completed", "at": 5, "unsafe_continuation": False},
            {"seq": 5, "name": "terminal_result", "at": 5},
        ],
    }


def _inactive() -> dict[str, bool]:
    return {
        "action_running": False,
        "movement_active": False,
        "pathfinder_active": False,
        "digging_active": False,
        "container_active": False,
    }


def result(*, ok: bool, after: dict[str, Any], code: str | None = None, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "type": "result",
        "ok": ok,
        "elapsed_ms": 10,
        "after_state": after,
        "lifecycle": lifecycle(ok=ok, code=code),
    }
    if code:
        payload["code"] = code
        payload["error"] = code
    if detail is not None:
        payload["detail"] = detail
    return payload


def traces() -> dict[str, tuple[str, list[dict[str, Any]]]]:
    oak = obs(blocks={"oak_log": 1})
    logs = obs(inventory=[{"name": "oak_log", "count": 3, "slot": 9}])
    planks = obs(inventory=[{"name": "oak_planks", "count": 12, "slot": 10}])
    table = obs(inventory=[{"name": "oak_planks", "count": 8, "slot": 10}, {"name": "crafting_table", "count": 1, "slot": 11}])
    smelt_ready = obs(
        inventory=[
            {"name": "raw_iron", "count": 1, "slot": 9},
            {"name": "coal", "count": 1, "slot": 10},
            {"name": "stone_pickaxe", "count": 1, "slot": 11},
        ],
        blocks={"furnace": 1},
        held_item="stone_pickaxe",
    )
    ingot = obs(inventory=[{"name": "iron_ingot", "count": 1, "slot": 9}], blocks={"furnace": 1})
    furnace_detail = {
        "furnace": {
            "input_slot": {"name": "raw_iron", "count": 1},
            "fuel_slot": {"name": "coal", "count": 1},
            "output_slot_before_take": {"name": "iron_ingot", "count": 1},
        },
        "container_pending": 0,
    }
    full = obs(blocks={"oak_log": 1}, inventory=[{"name": f"dirt_{slot}", "count": 1, "slot": slot} for slot in range(36)])
    hungry = obs(food=8, inventory=[{"name": "apple", "count": 1, "slot": 9}])
    fed = obs(food=20)
    moving_respawn = obs(stopped=False)
    stopped_respawn = obs()
    done_moving = obs(inventory=[{"name": "oak_log", "count": 16, "slot": 9}], stopped=False)
    return {
        "normal_bootstrap": (
            "bootstrap 1 iron_ingot",
            [
                record_step(oak, {"kind": "mine_nearest", "block": "oak_log", "max_distance": 24, "timeout_ms": 20000}, result(ok=True, after=logs)),
                record_step(logs, {"kind": "craft", "item": "oak_planks", "count": 12, "use_crafting_table": False, "timeout_ms": 20000}, result(ok=True, after=planks)),
                record_step(planks, {"kind": "craft", "item": "crafting_table", "count": 1, "use_crafting_table": False, "timeout_ms": 20000}, result(ok=True, after=table)),
            ],
        ),
        "smelt_timeout_cancel": (
            "bootstrap 1 iron_ingot",
            [record_step(smelt_ready, {"kind": "smelt", "input": "raw_iron", "fuel": "coal", "output": "iron_ingot", "count": 1, "timeout_ms": 120000}, result(ok=False, after=smelt_ready, code="timeout"), expected_terminal={"outcome": "timeout", "failure_code": "timeout"})],
        ),
        "delayed_furnace_output": (
            "bootstrap 1 iron_ingot",
            [
                record_step(smelt_ready, {"kind": "smelt", "input": "raw_iron", "fuel": "coal", "output": "iron_ingot", "count": 1, "timeout_ms": 120000}, result(ok=True, after=ingot, detail=furnace_detail)),
                record_step(ingot, {"kind": "stop", "reason": "verified_goal_complete"}, result(ok=True, after=ingot), expected_terminal={"outcome": "success", "inventory": {"iron_ingot": 1}}),
            ],
        ),
        "missing_material": (
            "bootstrap 1 iron_ingot",
            [
                record_step(
                    obs(x=0),
                    {
                        "kind": "control",
                        "states": {"forward": True, "jump": True, "sprint": True},
                        "duration_ms": 2500,
                        "timeout_ms": 12000,
                    },
                    result(ok=True, after=obs(x=1)),
                )
            ],
        ),
        "full_inventory": ("bootstrap 1 iron_ingot", [record_step(full, {"kind": "stop", "reason": "inventory_full"}, result(ok=True, after=full), expected_terminal={"outcome": "inventory_full", "failure_code": "inventory_full"})]),
        "low_food": ("bootstrap 1 iron_ingot", [record_step(hungry, {"kind": "eat", "timeout_ms": 8000}, result(ok=True, after=fed))]),
        "death_respawn": (
            "bootstrap 1 iron_ingot",
            [
                record_step(oak, {"kind": "mine_nearest", "block": "oak_log", "max_distance": 24, "timeout_ms": 20000}) | {"post_action_event": {"event": "death"}},
                record_step(moving_respawn, None),
                record_step(stopped_respawn, None, expected_terminal={"outcome": "death", "failure_code": "death"}),
            ],
        ),
        "failed_stop_after_target_inventory": (
            "gather 16 oak_log",
            [record_step(done_moving, {"kind": "stop", "reason": "verified_goal_complete"}, result(ok=True, after=done_moving), expected_terminal={"outcome": "unsafe", "failure_code": "stop_not_verified"})],
        ),
    }


def default_trace_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "bootstrap" / "traces"


def write_traces(trace_dir: Path) -> list[Path]:
    written = []
    for name, (_, frames) in traces().items():
        path = trace_dir / f"{name}.trace.json"
        save_trace(path, frames)
        written.append(path)
    return written


def replay_trace_files(trace_dir: Path) -> list[Path]:
    paths = sorted(trace_dir.glob("*.trace.json"))
    expected = set(traces())
    if {path.stem.removesuffix(".trace") for path in paths} != expected:
        missing = sorted(expected - {path.stem.removesuffix(".trace") for path in paths})
        raise RuntimeError(f"missing trace fixtures: {missing}")
    for path in paths:
        name = path.stem.removesuffix(".trace")
        goal, _ = traces()[name]
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = SessionAgent(Path(temp_dir))
            try:
                agent.set_goal(goal)
                replay_actions(agent, load_trace(path))
            finally:
                agent.memory.close()
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Write and replay deterministic bootstrap trace fixtures.")
    parser.add_argument("--trace-dir", type=Path, default=default_trace_dir())
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if not args.write and not args.replay:
        args.replay = True
    written = write_traces(args.trace_dir) if args.write else []
    replayed = replay_trace_files(args.trace_dir) if args.replay else []
    print(json.dumps({"ok": True, "written": [str(path) for path in written], "replayed": [str(path) for path in replayed]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
