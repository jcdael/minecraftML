from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


SCHEMA_VERSION = 5


class ExperienceStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self.recover_stale_running_runs()

    def _migrate(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            row = self.connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            version = int(row[0]) if row and str(row[0]).isdigit() else 0
            for target in range(version + 1, SCHEMA_VERSION + 1):
                getattr(self, f"_migrate_to_{target}")()
                self.connection.execute(
                    "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                    (str(target),),
                )

    def _migrate_to_1(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                goal TEXT,
                subgoal TEXT,
                action_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                skill_args_json TEXT NOT NULL,
                state_before_json TEXT NOT NULL,
                selected_action_json TEXT NOT NULL,
                state_after_json TEXT,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL,
                failure_code TEXT,
                reward REAL NOT NULL DEFAULT 0,
                agent_policy_version TEXT NOT NULL,
                result_json TEXT,
                completion_evidence_json TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                goal TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'running',
                target_item TEXT,
                target_count INTEGER,
                final_inventory_json TEXT,
                evidence_json TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                action_id TEXT,
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT
            )
            """
        )

    def _migrate_to_2(self) -> None:
        self._migrate_to_1()
        self._ensure_column("runs", "interrupted_reason", "TEXT")
        self._ensure_column("runs", "unsafe_continuation", "INTEGER NOT NULL DEFAULT 0")

    def _migrate_to_3(self) -> None:
        self._migrate_to_2()
        self._ensure_column("skill_attempts", "correlation_status", "TEXT NOT NULL DEFAULT 'matched'")

    def _migrate_to_4(self) -> None:
        self._migrate_to_3()

    def _migrate_to_5(self) -> None:
        self._migrate_to_4()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_updates (
                action_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                skill_name TEXT NOT NULL,
                skill_args_json TEXT NOT NULL,
                state_before_json TEXT NOT NULL,
                selected_action_json TEXT NOT NULL,
                reward REAL NOT NULL,
                agent_policy_version TEXT NOT NULL,
                exploration_bandit TEXT,
                exploration_parameters_json TEXT
            )
            """
        )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def start_run(self, *, goal: str, target_item: str, target_count: int) -> int:
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO runs (goal, target_item, target_count)
                VALUES (?, ?, ?)
                """,
                (goal, target_item, int(target_count)),
            )
        return int(cursor.lastrowid)

    def complete_run(
        self,
        *,
        run_id: int,
        outcome: str,
        final_inventory: dict[str, int],
        evidence: dict[str, Any],
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE runs
                   SET completed_at = CURRENT_TIMESTAMP,
                       outcome = ?,
                       final_inventory_json = ?,
                       evidence_json = ?
                 WHERE id = ?
                """,
                (
                    outcome,
                    json.dumps(final_inventory, separators=(",", ":"), sort_keys=True),
                    json.dumps(evidence, separators=(",", ":"), sort_keys=True),
                    int(run_id),
                ),
            )

    def interrupt_open_runs(self, *, reason: str, final_inventory: dict[str, int] | None = None) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE runs
                   SET completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                       outcome = CASE WHEN outcome = 'running' THEN 'interrupted' ELSE outcome END,
                       interrupted_reason = COALESCE(interrupted_reason, ?),
                       final_inventory_json = COALESCE(final_inventory_json, ?),
                       evidence_json = COALESCE(evidence_json, ?)
                 WHERE completed_at IS NULL OR outcome = 'running'
                """,
                (
                    reason,
                    json.dumps(final_inventory or {}, separators=(",", ":"), sort_keys=True),
                    json.dumps({"failure_code": reason}, separators=(",", ":"), sort_keys=True),
                ),
            )

    def recover_stale_running_runs(self) -> None:
        self.interrupt_open_runs(reason="startup_recovery", final_inventory={})

    def add_protocol_error(
        self,
        *,
        code: str,
        message: str,
        action_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO protocol_errors (action_id, code, message, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    action_id,
                    code,
                    message,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True) if payload else None,
                ),
            )

    def add_skill_attempt(
        self,
        *,
        goal: str | None,
        subgoal: str | None,
        action_id: str,
        skill_name: str,
        skill_args: dict[str, Any],
        state_before: dict[str, Any],
        selected_action: dict[str, Any],
        state_after: dict[str, Any] | None,
        elapsed_ms: int,
        outcome: str,
        failure_code: str | None,
        reward: float,
        agent_policy_version: str,
        result: dict[str, Any] | None,
        completion_evidence: dict[str, Any] | None = None,
        correlation_status: str = "matched",
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO skill_attempts
                    (goal, subgoal, action_id, skill_name, skill_args_json,
                     state_before_json, selected_action_json, state_after_json,
                     elapsed_ms, outcome, failure_code, reward, agent_policy_version,
                    result_json, completion_evidence_json, correlation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal,
                    subgoal,
                    action_id,
                    skill_name,
                    json.dumps(skill_args, separators=(",", ":"), sort_keys=True),
                    json.dumps(state_before, separators=(",", ":"), sort_keys=True),
                    json.dumps(selected_action, separators=(",", ":"), sort_keys=True),
                    json.dumps(state_after, separators=(",", ":"), sort_keys=True) if state_after else None,
                    int(elapsed_ms),
                    outcome,
                    failure_code,
                    float(reward),
                    agent_policy_version,
                    json.dumps(result, separators=(",", ":"), sort_keys=True) if result else None,
                    json.dumps(completion_evidence, separators=(",", ":"), sort_keys=True)
                    if completion_evidence
                    else None,
                    correlation_status,
                ),
            )

    def add_policy_update(
        self,
        *,
        action_id: str,
        skill_name: str,
        skill_args: dict[str, Any],
        state_before: dict[str, Any],
        selected_action: dict[str, Any],
        reward: float,
        agent_policy_version: str,
        exploration_bandit: str | None = None,
        exploration_parameters: dict[str, Any] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO policy_updates
                    (action_id, skill_name, skill_args_json, state_before_json,
                     selected_action_json, reward, agent_policy_version,
                     exploration_bandit, exploration_parameters_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    skill_name,
                    json.dumps(skill_args, separators=(",", ":"), sort_keys=True),
                    json.dumps(state_before, separators=(",", ":"), sort_keys=True),
                    json.dumps(selected_action, separators=(",", ":"), sort_keys=True),
                    float(reward),
                    agent_policy_version,
                    exploration_bandit,
                    json.dumps(exploration_parameters, separators=(",", ":"), sort_keys=True) if exploration_parameters else None,
                ),
            )

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM skill_attempts").fetchall()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self.connection.close()