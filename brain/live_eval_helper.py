from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from protocol import LIFECYCLE_EVENT_NAMES, ProtocolError, _validate_lifecycle


LIFECYCLE_ORDER = [
    "abort_requested",
    "cleanup_started",
    "cleanup_completed",
    "execution_settled",
    "post_stop_probe_completed",
    "terminal_result",
]
REQUIRED_LIFECYCLE_EVENTS = {"execution_settled", "post_stop_probe_completed", "terminal_result"}


def _valid_timestamp(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _violate(summary: dict[str, Any], code: str, **extra: Any) -> None:
    summary["invalid_lifecycle_log"] += 1
    payload = {"code": code}
    payload.update(extra)
    summary["violations"].append(payload)


def inspect_adapter_log(path: Path | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path) if path else None,
        "entries": 0,
        "invalid_lifecycle_log": 0,
        "unresolved_execution": 0,
        "adapter_faults": 0,
        "post_stop_activity": 0,
        "duplicate_terminal_events": 0,
        "new_action_before_prior_settlement": 0,
        "violations": [],
    }
    if path is None or not path.exists():
        _violate(summary, "adapter_log_missing")
        return summary
    action_started: dict[str, int] = {}
    action_started_at: dict[str, float] = {}
    terminal_counts: dict[str, int] = {}
    settlement_counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            _violate(summary, "adapter_log_invalid_json")
            continue
        summary["entries"] += 1
        code = str(entry.get("code") or entry.get("reason") or "")
        event = str(entry.get("event") or "")
        raw_action_id = entry.get("action_id")
        action_id = raw_action_id if isinstance(raw_action_id, str) else ""
        lifecycle = entry.get("lifecycle") if isinstance(entry.get("lifecycle"), dict) else {}
        if event == "action_started":
            if not action_id:
                _violate(summary, "action_started_missing_id")
                continue
            if not _valid_timestamp(entry.get("at")):
                _violate(summary, "action_started_invalid_timestamp", action_id=action_id)
                continue
            if entry.get("seq") != 0:
                _violate(summary, "action_started_invalid_sequence", action_id=action_id)
            action_started[action_id] = action_started.get(action_id, 0) + 1
            action_started_at[action_id] = float(entry["at"])
        if event == "adapter_faulted" or code == "adapter_faulted" or lifecycle.get("faulted") is True:
            summary["adapter_faults"] += 1
            summary["violations"].append({"code": "adapter_fault", "action_id": action_id})
        if code == "new_action_before_prior_settlement":
            summary["new_action_before_prior_settlement"] += 1
            summary["violations"].append({"code": code, "action_id": action_id})
        if event == "terminal_message" and entry.get("message_type") == "result":
            if not action_id:
                _violate(summary, "terminal_missing_id")
                continue
            if action_id not in action_started:
                _violate(summary, "orphan_terminal_record", action_id=action_id)
            if not lifecycle:
                _violate(summary, "terminal_lifecycle_missing", action_id=action_id)
            else:
                try:
                    _validate_lifecycle(lifecycle, "adapter_log.lifecycle")
                except ProtocolError as error:
                    _violate(summary, "terminal_lifecycle_invalid", action_id=action_id, reason=error.code)
                nested_action_id = lifecycle.get("action_id")
                if nested_action_id != action_id:
                    _violate(
                        summary,
                        "mismatched_lifecycle_action_id",
                        action_id=action_id,
                        lifecycle_action_id=nested_action_id,
                    )
        if lifecycle:
            settled = lifecycle.get("execution_settled")
            terminal = lifecycle.get("terminal_result")
            if not isinstance(settled, dict):
                _violate(summary, "execution_settlement_missing", action_id=action_id)
            elif settled.get("settled") is not True:
                summary["unresolved_execution"] += 1
                summary["violations"].append({"code": "unresolved_execution", "action_id": action_id})
            elif event == "terminal_message" and entry.get("message_type") == "result":
                settlement_counts[action_id] = settlement_counts.get(action_id, 0) + 1
            if not isinstance(terminal, dict):
                _violate(summary, "terminal_result_missing", action_id=action_id)
            if event == "terminal_message" and entry.get("message_type") == "result":
                _validate_lifecycle_order(summary, action_id, action_started_at.get(action_id), lifecycle)
            if lifecycle.get("unsafe_continuation") is True:
                summary["post_stop_activity"] += 1
                summary["violations"].append({"code": "post_stop_activity", "action_id": action_id})
        if event == "terminal_message" and entry.get("message_type") == "result" and action_id:
            terminal_counts[action_id] = terminal_counts.get(action_id, 0) + 1
    for action_id, count in terminal_counts.items():
        if count > 1:
            summary["duplicate_terminal_events"] += count - 1
            summary["violations"].append({"code": "duplicate_terminal_events", "action_id": action_id, "count": count})
    if summary["entries"] == 0:
        _violate(summary, "adapter_log_empty")
    for action_id, count in action_started.items():
        if count != 1:
            _violate(summary, "action_started_duplicate", action_id=action_id, count=count)
        if terminal_counts.get(action_id, 0) != 1:
            _violate(summary, "action_terminal_count_invalid", action_id=action_id, count=terminal_counts.get(action_id, 0))
        if settlement_counts.get(action_id, 0) != 1:
            _violate(summary, "action_settlement_count_invalid", action_id=action_id, count=settlement_counts.get(action_id, 0))
    return summary


def _validate_lifecycle_order(
    summary: dict[str, Any],
    action_id: str,
    outer_started_at: float | None,
    lifecycle: dict[str, Any],
) -> None:
    started = lifecycle.get("started")
    settled = lifecycle.get("execution_settled") if isinstance(lifecycle.get("execution_settled"), dict) else {}
    terminal = lifecycle.get("terminal_result") if isinstance(lifecycle.get("terminal_result"), dict) else {}
    settled_at = settled.get("at")
    terminal_at = terminal.get("at")
    events = lifecycle.get("events", [])
    if outer_started_at is None:
        _violate(summary, "terminal_without_started_timestamp", action_id=action_id)
    if not _valid_timestamp(started):
        _violate(summary, "lifecycle_started_invalid_timestamp", action_id=action_id)
    if not _valid_timestamp(settled_at):
        _violate(summary, "execution_settlement_invalid_timestamp", action_id=action_id)
    if not _valid_timestamp(terminal_at):
        _violate(summary, "terminal_result_invalid_timestamp", action_id=action_id)
    if not isinstance(events, list):
        _violate(summary, "lifecycle_events_invalid", action_id=action_id)
        events = []
    if not all(_valid_timestamp(value) for value in (started, settled_at, terminal_at)):
        return
    started_f = float(started)
    settled_f = float(settled_at)
    terminal_f = float(terminal_at)
    if outer_started_at is not None and outer_started_at > started_f:
        _violate(summary, "out_of_order_action_started", action_id=action_id)
    if started_f > settled_f:
        _violate(summary, "out_of_order_execution_settled", action_id=action_id)
    if settled_f > terminal_f:
        _violate(summary, "out_of_order_terminal_result", action_id=action_id)
    seen: set[str] = set()
    previous_order = -1
    previous_seq = 0
    previous_at = started_f
    by_name: dict[str, dict[str, Any]] = {}
    for raw_event in events:
        if not isinstance(raw_event, dict):
            _violate(summary, "lifecycle_event_invalid", action_id=action_id)
            continue
        name = raw_event.get("name")
        seq = raw_event.get("seq")
        at = raw_event.get("at")
        if name not in LIFECYCLE_EVENT_NAMES:
            _violate(summary, "unknown_lifecycle_event", action_id=action_id, event=name)
            continue
        if name in seen:
            _violate(summary, "duplicate_lifecycle_event", action_id=action_id, event=name)
        seen.add(str(name))
        order = LIFECYCLE_ORDER.index(str(name))
        if order < previous_order:
            _violate(summary, "misordered_lifecycle_event", action_id=action_id, event=name)
        previous_order = max(previous_order, order)
        if isinstance(seq, bool) or not isinstance(seq, int) or seq != previous_seq + 1:
            _violate(summary, "invalid_lifecycle_sequence", action_id=action_id, event=name)
        else:
            previous_seq = seq
        if not _valid_timestamp(at):
            _violate(summary, "lifecycle_event_invalid_timestamp", action_id=action_id, event=name)
            continue
        at_f = float(at)
        if at_f < started_f or at_f > terminal_f:
            _violate(summary, "lifecycle_event_outside_bounds", action_id=action_id, event=name)
        if at_f < previous_at:
            _violate(summary, "lifecycle_event_timestamp_reversed", action_id=action_id, event=name)
        previous_at = max(previous_at, at_f)
        by_name[str(name)] = raw_event
    for name in sorted(REQUIRED_LIFECYCLE_EVENTS - seen):
        _violate(summary, f"{name}_missing", action_id=action_id)
    if "cleanup_completed" in seen and "cleanup_started" not in seen:
        _violate(summary, "cleanup_completed_without_started", action_id=action_id)
    if "cleanup_started" in seen and "cleanup_completed" not in seen:
        _violate(summary, "cleanup_started_without_completed", action_id=action_id)
    if (
        "execution_settled" in by_name
        and _valid_timestamp(by_name["execution_settled"].get("at"))
        and float(by_name["execution_settled"].get("at")) != settled_f
    ):
        _violate(summary, "execution_settlement_event_mismatch", action_id=action_id)
    if (
        "terminal_result" in by_name
        and _valid_timestamp(by_name["terminal_result"].get("at"))
        and float(by_name["terminal_result"].get("at")) != terminal_f
    ):
        _violate(summary, "terminal_result_event_mismatch", action_id=action_id)
    if "post_stop_probe_completed" in by_name:
        probe_at = by_name["post_stop_probe_completed"].get("at")
        if _valid_timestamp(probe_at) and float(probe_at) < settled_f:
            _violate(summary, "out_of_order_post_stop_probe", action_id=action_id)
    if "terminal_result" in by_name and "post_stop_probe_completed" in by_name:
        terminal_event_at = by_name["terminal_result"].get("at")
        probe_at = by_name["post_stop_probe_completed"].get("at")
        if (
            _valid_timestamp(terminal_event_at)
            and _valid_timestamp(probe_at)
            and float(terminal_event_at) < float(probe_at)
        ):
            _violate(summary, "terminal_before_post_stop_probe", action_id=action_id)


async def submit_goal(url: str, goal: str) -> None:
    import websockets

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "protocol_version": 1,
                    "type": "goal",
                    "text": goal,
                    "requested_by": "ten-seed-evaluator",
                },
                separators=(",", ":"),
            )
        )


def read_status(db: Path, started_after: str, adapter_log: Path | None = None) -> dict[str, Any]:
    if not db.exists():
        return {}
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        run_row = conn.execute(
            """
            SELECT id, started_at, completed_at, goal, outcome, final_inventory_json, evidence_json
              FROM runs
             WHERE started_at >= ?
             ORDER BY id DESC
             LIMIT 1
            """,
            (started_after,),
        ).fetchone()
        if not run_row:
            return {}
        run = dict(run_row)
        attempts = conn.execute(
            "SELECT COUNT(*) FROM skill_attempts WHERE timestamp >= ?",
            (run["started_at"],),
        ).fetchone()[0]
        failures = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                """
                SELECT COALESCE(failure_code, outcome), COUNT(*)
                  FROM skill_attempts
                 WHERE timestamp >= ?
                 GROUP BY COALESCE(failure_code, outcome)
                """,
                (run["started_at"],),
            ).fetchall()
        }
        stuck = conn.execute(
            """
            SELECT COUNT(*)
              FROM skill_attempts
             WHERE timestamp >= ? AND skill_name = 'RecoverStuck'
            """,
            (run["started_at"],),
        ).fetchone()[0]
        critical_skill_failures = {
            f"{row[0]}:{row[1]}": int(row[2])
            for row in conn.execute(
                """
                SELECT skill_name, COALESCE(failure_code, outcome), COUNT(*)
                  FROM skill_attempts
                 WHERE timestamp >= ?
                   AND skill_name IN ('CraftItem', 'PlaceBlock', 'SmeltItem')
                   AND outcome != 'success'
                 GROUP BY skill_name, COALESCE(failure_code, outcome)
                """,
                (run["started_at"],),
            ).fetchall()
        }
        navigation_retries = conn.execute(
            """
            SELECT COUNT(*)
              FROM skill_attempts
             WHERE timestamp >= ?
               AND skill_name IN ('ExploreSearch', 'GotoSite', 'RecoverStuck')
               AND outcome != 'success'
            """,
            (run["started_at"],),
        ).fetchone()[0]
        exploration_retries = conn.execute(
            """
            SELECT COUNT(*)
              FROM skill_attempts
             WHERE timestamp >= ?
               AND skill_name = 'ExploreSearch'
               AND outcome != 'success'
            """,
            (run["started_at"],),
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT action_id, skill_name, completion_evidence_json, result_json
              FROM skill_attempts
             WHERE timestamp >= ?
             ORDER BY id
            """,
            (run["started_at"],),
        ).fetchall()
        saw_stop = False
        brain_unsafe = 0
        adapter_unsafe = 0
        lifecycle = []
        for action_id, skill_name, evidence_json, result_json in rows:
            evidence = json.loads(evidence_json or "{}")
            result = json.loads(result_json or "{}")
            adapter_lifecycle = result.get("lifecycle") if isinstance(result, dict) else None
            if isinstance(adapter_lifecycle, dict):
                unsafe_flag = bool(adapter_lifecycle.get("unsafe_continuation"))
                if unsafe_flag:
                    adapter_unsafe += 1
                lifecycle.append(
                    {
                        "action_id": action_id,
                        "skill_name": skill_name,
                        "terminal_result": adapter_lifecycle.get("terminal_result"),
                        "execution_settled": adapter_lifecycle.get("execution_settled"),
                        "final_activity_state": adapter_lifecycle.get("final_activity_state"),
                        "unsafe_continuation": unsafe_flag,
                    }
                )
            if skill_name == "Stop" and evidence.get("verified_stopped") is True:
                saw_stop = True
                continue
            if saw_stop and skill_name != "Stop":
                brain_unsafe += 1
        run["attempts"] = int(attempts)
        run["failure_code_distribution"] = failures
        run["stuck_recoveries"] = int(stuck)
        run["critical_skill_failures"] = critical_skill_failures
        run["navigation_retries"] = int(navigation_retries)
        run["exploration_retries"] = int(exploration_retries)
        run["brain_unsafe_continuations"] = int(brain_unsafe)
        run["adapter_unsafe_continuations"] = int(adapter_unsafe)
        run["unsafe_continuations"] = int(brain_unsafe + adapter_unsafe)
        run["adapter_lifecycle"] = lifecycle
        adapter_log_summary = inspect_adapter_log(adapter_log)
        run["adapter_log_summary"] = adapter_log_summary
        run["adapter_invalid_lifecycle_log"] = int(adapter_log_summary["invalid_lifecycle_log"])
        run["adapter_faults"] = int(adapter_log_summary["adapter_faults"])
        run["adapter_unresolved_execution"] = int(adapter_log_summary["unresolved_execution"])
        run["adapter_post_stop_activity"] = int(adapter_log_summary["post_stop_activity"])
        run["adapter_duplicate_terminal_events"] = int(adapter_log_summary["duplicate_terminal_events"])
        run["adapter_new_action_before_prior_settlement"] = int(adapter_log_summary["new_action_before_prior_settlement"])
        return run
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--url", default="ws://127.0.0.1:8765")
    submit.add_argument("--goal", default="gather 16 oak_log")
    status = sub.add_parser("status")
    status.add_argument("--db", type=Path, required=True)
    status.add_argument("--started-after", required=True)
    status.add_argument("--adapter-log", type=Path)
    args = parser.parse_args()

    if args.command == "submit":
        asyncio.run(submit_goal(args.url, args.goal))
    elif args.command == "status":
        print(json.dumps(read_status(args.db, args.started_after, args.adapter_log), separators=(",", ":")))


if __name__ == "__main__":
    main()
