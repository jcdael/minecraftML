from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sqlite3
import statistics
import time
from typing import Any

from protocol import PROTOCOL_VERSION


DEFAULT_SEEDS = [
    12001,
    12002,
    12003,
    12004,
    12005,
    12006,
    12007,
    12008,
    12009,
    12010,
]


def latest_run(db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, started_at, completed_at, goal, outcome, final_inventory_json, evidence_json
              FROM runs
             ORDER BY id DESC
             LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def failure_distribution(db_path: Path, run_started_at: str | None) -> dict[str, int]:
    if not db_path.exists() or not run_started_at:
        return {}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(failure_code, outcome) AS code, COUNT(*)
              FROM skill_attempts
             WHERE timestamp >= ?
             GROUP BY COALESCE(failure_code, outcome)
            """,
            (run_started_at,),
        ).fetchall()
        return {str(code): int(count) for code, count in rows}
    finally:
        conn.close()


def stuck_recoveries(db_path: Path, run_started_at: str | None) -> int:
    if not db_path.exists() or not run_started_at:
        return 0
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
              FROM skill_attempts
             WHERE timestamp >= ?
               AND skill_name = 'RecoverStuck'
            """,
            (run_started_at,),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def unsafe_continuations(db_path: Path, run_started_at: str | None) -> int:
    if not db_path.exists() or not run_started_at:
        return 0
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT skill_name, outcome, completion_evidence_json, result_json, timestamp
              FROM skill_attempts
             WHERE timestamp >= ?
             ORDER BY id
            """,
            (run_started_at,),
        ).fetchall()
        saw_verified_stop = False
        brain_unsafe = 0
        adapter_unsafe = 0
        for skill_name, _outcome, evidence_json, result_json, _timestamp in rows:
            evidence = json.loads(evidence_json or "{}")
            result = json.loads(result_json or "{}")
            lifecycle = result.get("lifecycle") if isinstance(result, dict) else None
            if isinstance(lifecycle, dict) and lifecycle.get("unsafe_continuation") is True:
                adapter_unsafe += 1
            if skill_name == "Stop" and evidence.get("verified_stopped") is True:
                saw_verified_stop = True
                continue
            if saw_verified_stop and skill_name != "Stop":
                brain_unsafe += 1
        return brain_unsafe + adapter_unsafe
    finally:
        conn.close()


def adapter_lifecycle_evidence(db_path: Path, run_started_at: str | None) -> list[dict[str, Any]]:
    if not db_path.exists() or not run_started_at:
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT action_id, skill_name, result_json
              FROM skill_attempts
             WHERE timestamp >= ?
             ORDER BY id
            """,
            (run_started_at,),
        ).fetchall()
        evidence = []
        for action_id, skill_name, result_json in rows:
            result = json.loads(result_json or "{}")
            lifecycle = result.get("lifecycle") if isinstance(result, dict) else None
            if isinstance(lifecycle, dict):
                evidence.append(
                    {
                        "action_id": action_id,
                        "skill_name": skill_name,
                        "terminal_result": lifecycle.get("terminal_result"),
                        "execution_settled": lifecycle.get("execution_settled"),
                        "final_activity_state": lifecycle.get("final_activity_state"),
                        "unsafe_continuation": bool(lifecycle.get("unsafe_continuation")),
                    }
                )
        return evidence
    finally:
        conn.close()


def pass_evidence(run: dict[str, Any], inventory: dict[str, int], evidence: dict[str, Any], unsafe_count: int) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if run["outcome"] != "success":
        missing.append("outcome_success")
    if inventory.get("oak_log", 0) < 16:
        missing.append("inventory_oak_log_16")
    if evidence.get("verified_goal_complete") is not True:
        missing.append("verified_goal_complete")
    if evidence.get("verified_stopped") is not True:
        missing.append("verified_stopped")
    if evidence.get("initial_inventory_empty") is not True:
        missing.append("initial_inventory_empty")
    if unsafe_count != 0:
        missing.append("no_unsafe_continuation")
    return not missing, missing


async def submit_goal(brain_url: str, goal: str) -> None:
    import websockets

    async with websockets.connect(brain_url, max_size=8 * 1024 * 1024) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "goal",
                    "text": goal,
                    "requested_by": "seed-evaluation-runner",
                },
                separators=(",", ":"),
            )
        )


async def run_one(args: argparse.Namespace, seed: int) -> dict[str, Any]:
    print(f"Seed {seed}: start a fresh disposable survival world with level-seed={seed}.")
    print("Press Enter when the local server, brain, and adapter are running for this seed.")
    input()
    started = time.monotonic()
    first_run = latest_run(args.db)
    await submit_goal(args.brain_url, args.goal)
    deadline = time.monotonic() + args.timeout_seconds

    while time.monotonic() < deadline:
        run = latest_run(args.db)
        if run and run.get("completed_at") and run.get("id") != (first_run or {}).get("id"):
            elapsed = time.monotonic() - started
            failures = failure_distribution(args.db, run.get("started_at"))
            evidence = json.loads(run["evidence_json"] or "{}")
            inventory = json.loads(run["final_inventory_json"] or "{}")
            unsafe_count = unsafe_continuations(args.db, run.get("started_at"))
            lifecycle = adapter_lifecycle_evidence(args.db, run.get("started_at"))
            passed, missing = pass_evidence(run, inventory, evidence, unsafe_count)
            return {
                "seed": seed,
                "outcome": run["outcome"],
                "passed": passed,
                "missing_required_evidence": missing,
                "completion_time_seconds": round(elapsed, 2),
                "deaths": 1 if run["outcome"] == "death" else 0,
                "stuck_recoveries": stuck_recoveries(args.db, run.get("started_at")),
                "unsafe_continuations": unsafe_count,
                "adapter_lifecycle": lifecycle,
                "failure_code_distribution": failures,
                "evidence": evidence,
                "final_inventory": inventory,
            }
        await asyncio.sleep(2)

    return {
        "seed": seed,
        "outcome": "timeout",
        "passed": False,
        "completion_time_seconds": args.timeout_seconds,
        "deaths": 0,
        "stuck_recoveries": 0,
        "unsafe_continuations": 0,
        "adapter_lifecycle": [],
        "missing_required_evidence": ["completed_run_record"],
        "failure_code_distribution": {"timeout": 1},
        "evidence": {},
        "final_inventory": {},
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Opt-in ten-seed gather-oak evaluation runner.")
    parser.add_argument("--i-understand-disposable-world", action="store_true", required=True)
    parser.add_argument("--brain-url", default="ws://127.0.0.1:8765")
    parser.add_argument("--goal", default="gather 16 oak_log")
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "experiences.db")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "evaluation-results.json")
    parser.add_argument("--seeds", nargs="*", type=int, default=DEFAULT_SEEDS)
    args = parser.parse_args()

    results = []
    for seed in args.seeds:
        results.append(await run_one(args, seed))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")

    passed = sum(1 for result in results if result["passed"])
    hung = sum(1 for result in results if result["outcome"] == "timeout")
    deaths = sum(int(result["deaths"]) for result in results)
    stuck = sum(int(result["stuck_recoveries"]) for result in results)
    unsafe = sum(int(result["unsafe_continuations"]) for result in results)
    completion_times = [float(result["completion_time_seconds"]) for result in results if result["passed"]]
    failures = Counter()
    for result in results:
        failures.update(result["failure_code_distribution"])
    summary = {
        "passed": passed,
        "total": len(results),
        "completion_rate": round(passed / max(1, len(results)), 3),
        "median_completion_time_seconds": statistics.median(completion_times) if completion_times else None,
        "deaths": deaths,
        "stuck_recoveries": stuck,
        "hung_runs": hung,
        "unsafe_continuations": unsafe,
        "failure_code_distribution": dict(failures),
        "acceptance_gate_passed": passed >= 8 and hung == 0 and deaths == 0 and unsafe == 0,
    }
    print(json.dumps({"summary": summary, "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
