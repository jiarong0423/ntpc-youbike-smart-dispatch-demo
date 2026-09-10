#!/usr/bin/env python3
"""Public-only SQLite task ledger. No station rows or private scoring inputs."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
import re
import sqlite3
from typing import Any

TASK_ID_RE = re.compile(r"^task-[a-z0-9][a-z0-9-]{3,64}$")
EVENT_ID_RE = re.compile(r"^evt-[A-Za-z0-9_-]{8,80}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
EVENT_TRANSITIONS = {
    ("pending", "claim"): "claimed",
    ("claimed", "arrive"): "arrived",
    ("arrived", "complete"): "completed",
    ("claimed", "exception"): "exception",
    ("arrived", "exception"): "exception",
}


class TaskStore:
    def __init__(self, path: Path, project_root: Path) -> None:
        self.path = path.expanduser().resolve()
        root = project_root.resolve()
        if self.path == root or root in self.path.parents:
            raise ValueError("task_database_must_be_outside_project")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_schema(self) -> None:
        with closing(self.connect()) as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS task (
                    task_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    district_id TEXT NOT NULL,
                    action_label TEXT NOT NULL,
                    priority_band TEXT NOT NULL,
                    route_label TEXT NOT NULL,
                    eta_band TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actor_alias TEXT,
                    source_package_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_event (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES task(task_id),
                    event_type TEXT NOT NULL,
                    actor_alias TEXT NOT NULL,
                    status_before TEXT NOT NULL,
                    status_after TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_event_task
                    ON task_event(task_id, created_at);
                """
            )
            conn.commit()

    @staticmethod
    def public_task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "case_id": row["case_id"],
            "display_name": row["display_name"],
            "district_id": row["district_id"],
            "action_label": row["action_label"],
            "priority_band": row["priority_band"],
            "route_label": row["route_label"],
            "eta_band": row["eta_band"],
            "status": row["status"],
            "actor_alias": row["actor_alias"],
            "updated_at": row["updated_at"],
        }

    def seed_result(self, result: dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for case in result["selected_cases"]:
            handoff = case["route_handoff"]
            if handoff.get("present") is not True:
                continue
            task_id = "task-" + str(case["case_id"])[5:]
            if not TASK_ID_RE.fullmatch(task_id):
                raise ValueError("generated_task_id_invalid")
            rows.append(
                (
                    task_id,
                    case["case_id"],
                    str(case["display_name"])[:80],
                    str(case["district_id"])[:48],
                    str(case["action_label"])[:32],
                    str(case["priority_band"])[:16],
                    str(handoff.get("label", "route"))[:80],
                    str(handoff.get("eta_band", "none"))[:24],
                    "pending",
                    result["package_id"],
                    now,
                    now,
                )
            )
        with closing(self.connect()) as conn:
            conn.executemany(
                """
                INSERT INTO task (
                    task_id, case_id, display_name, district_id, action_label,
                    priority_band, route_label, eta_band, status,
                    source_package_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    district_id=excluded.district_id,
                    action_label=excluded.action_label,
                    priority_band=excluded.priority_band,
                    route_label=excluded.route_label,
                    eta_band=excluded.eta_band,
                    source_package_id=excluded.source_package_id,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    def list_tasks(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM task ORDER BY created_at, task_id"
            ).fetchall()
        return [self.public_task(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        if not TASK_ID_RE.fullmatch(task_id):
            return None
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM task WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self.public_task(row) if row else None

    def apply_event(
        self, task_id: str, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not TASK_ID_RE.fullmatch(task_id) or not isinstance(payload, dict):
            return HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "invalid_request",
            }
        required = {"event_id", "event_type", "actor_alias"}
        if set(payload) != required:
            return HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "event_fields_invalid",
            }
        event_id = str(payload["event_id"])
        event_type = str(payload["event_type"])
        actor_alias = str(payload["actor_alias"])
        if (
            not EVENT_ID_RE.fullmatch(event_id)
            or event_type not in {"claim", "arrive", "complete", "exception"}
            or not ACTOR_RE.fullmatch(actor_alias)
        ):
            return HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "event_value_invalid",
            }

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT task_id FROM task_event WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            row = conn.execute(
                "SELECT * FROM task WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                conn.rollback()
                return HTTPStatus.NOT_FOUND, {
                    "ok": False,
                    "error": "task_not_found",
                }
            if existing:
                conn.rollback()
                if existing["task_id"] != task_id:
                    return HTTPStatus.CONFLICT, {
                        "ok": False,
                        "error": "event_id_conflict",
                    }
                return HTTPStatus.OK, {
                    "ok": True,
                    "duplicate": True,
                    "task": self.public_task(row),
                }

            status_before = str(row["status"])
            status_after = EVENT_TRANSITIONS.get(
                (status_before, event_type)
            )
            if not status_after:
                conn.rollback()
                return HTTPStatus.CONFLICT, {
                    "ok": False,
                    "error": "invalid_transition",
                    "status": status_before,
                    "event_type": event_type,
                }

            conn.execute(
                """
                UPDATE task
                SET status = ?, actor_alias = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status_after, actor_alias, now, task_id),
            )
            conn.execute(
                "INSERT INTO task_event VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    task_id,
                    event_type,
                    actor_alias,
                    status_before,
                    status_after,
                    now,
                ),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM task WHERE task_id = ?", (task_id,)
            ).fetchone()

        return HTTPStatus.OK, {
            "ok": True,
            "duplicate": False,
            "task": self.public_task(updated),
        }
