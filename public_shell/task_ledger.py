#!/usr/bin/env python3
"""Public-only SQLite task ledger. No station rows or private scoring inputs."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
import re
import base64
import hashlib
import hmac
import json
import secrets
import time
import sqlite3
from typing import Any

TASK_ID_RE = re.compile(r"^task-[a-z0-9][a-z0-9-]{3,64}$")
EVENT_ID_RE = re.compile(r"^evt-[A-Za-z0-9_-]{8,80}$")
TASK_TYPES = {"add_bikes", "pull_bikes", "observe", "rebalance_window"}
QR_TTL_SECONDS = 300
EVENT_MAX_AGE_SECONDS = 300
FUTURE_SKEW_SECONDS = 30
SCHEMA_VERSION = 2


def canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class TaskStore:
    def __init__(self, path: Path, project_root: Path, *, signing_key: bytes | None = None) -> None:
        self.path = path.expanduser().resolve()
        root = project_root.resolve()
        if self.path == root or root in self.path.parents:
            raise ValueError("task_database_must_be_outside_project")
        self.signing_key = signing_key if signing_key is not None else secrets.token_bytes(32)
        if len(self.signing_key) < 32:
            raise ValueError("signing_key_too_short")
        existing_database = self.path.exists()
        if existing_database:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as conn:
                if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise ValueError("task_database_schema_requires_explicit_migration")
                required_columns = {
                    "task": {"task_id", "case_id", "display_name", "district_id", "action_label", "priority_band", "route_label", "eta_band", "status", "source_package_id", "created_at", "updated_at"},
                    "task_event": {"event_id", "task_id", "event_type", "request_hash", "status_before", "status_after", "created_at"},
                    "task_attempt": {"attempt_id", "task_id", "event_id", "error_code", "created_at"},
                }
                for table, columns in required_columns.items():
                    actual = {row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")}
                    if actual != columns:
                        raise ValueError("task_database_schema_requires_explicit_migration")
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("task_database_integrity_failed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not existing_database:
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
                    source_package_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_event (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES task(task_id),
                    event_type TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status_before TEXT NOT NULL,
                    status_after TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_attempt (
                    attempt_id INTEGER PRIMARY KEY,
                    task_id TEXT,
                    event_id TEXT,
                    error_code TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                PRAGMA user_version = 2;
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
            "task_type": row["action_label"],
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
                    "OPEN",
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
                WHERE task.status = 'OPEN'
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

    def issue_signature(self, task_id: str, *, now: int | None = None) -> dict[str, Any]:
        task = self.get_task(task_id)
        if not task or task["status"] != "OPEN":
            raise ValueError("task_not_open")
        issued = int(time.time()) if now is None else now
        claims = {"task_id": task_id, "task_type": task["task_type"],
                  "issued_at": issued, "expires_at": issued + QR_TTL_SECONDS,
                  "device_salt": secrets.token_hex(16)}
        encoded = base64.urlsafe_b64encode(canonical(claims)).decode().rstrip("=")
        digest = hmac.new(self.signing_key, encoded.encode(), hashlib.sha256).hexdigest()
        return {**claims, "signature": encoded + "." + digest}

    def _verify_signature(self, token: str, task_id: str, task_type: str, now: float) -> bool:
        try:
            encoded, digest = token.split(".")
            expected = hmac.new(self.signing_key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, digest):
                return False
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            return (claims["task_id"] == task_id and claims["task_type"] == task_type
                    and claims["issued_at"] <= now + FUTURE_SKEW_SECONDS
                    and now < claims["expires_at"]
                    and claims["expires_at"] - claims["issued_at"] == QR_TTL_SECONDS)
        except (ValueError, KeyError, TypeError):
            return False

    def reject(self, task_id: str, event_id: Any, error: str, status: int = 400,
               *, conn: sqlite3.Connection | None = None) -> tuple[int, dict[str, Any]]:
        values = (task_id if TASK_ID_RE.fullmatch(task_id) else None,
                  event_id if isinstance(event_id, str) and EVENT_ID_RE.fullmatch(event_id) else None,
                  error, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if conn is None:
            with closing(self.connect()) as audit:
                audit.execute("INSERT INTO task_attempt(task_id,event_id,error_code,created_at) VALUES (?,?,?,?)", values)
                audit.commit()
        else:
            conn.execute("INSERT INTO task_attempt(task_id,event_id,error_code,created_at) VALUES (?,?,?,?)", values)
            conn.commit()
        return status, {"ok": False, "error": error}

    def apply_event(self, task_id: str, payload: Any) -> tuple[int, dict[str, Any]]:
        event_id = payload.get("event_id") if isinstance(payload, dict) else None
        required = {"task_id", "task_type", "event_id", "device_hash", "signature", "occurred_at"}
        if not TASK_ID_RE.fullmatch(task_id) or not isinstance(payload, dict) or set(payload) != required:
            return self.reject(task_id, event_id, "event_fields_invalid")
        if (not all(isinstance(v, str) for v in payload.values())
                or not EVENT_ID_RE.fullmatch(event_id)
                or payload["task_id"] != task_id
                or payload["task_type"] not in TASK_TYPES
                or not re.fullmatch(r"[a-f0-9]{64}", payload["device_hash"])
                or len(payload["signature"]) > 1024):
            return self.reject(task_id, event_id, "event_value_invalid")
        now = time.time()
        try:
            occurred = datetime.fromisoformat(payload["occurred_at"].replace("Z", "+00:00"))
            if occurred.tzinfo is None:
                raise ValueError("timezone_missing")
            age = now - occurred.timestamp()
            if not -FUTURE_SKEW_SECONDS <= age <= EVENT_MAX_AGE_SECONDS:
                raise ValueError("time_out_of_range")
        except (ValueError, OverflowError):
            return self.reject(task_id, event_id, "event_time_invalid")
        if not self._verify_signature(payload["signature"], task_id, payload["task_type"], now):
            return self.reject(task_id, event_id, "signature_invalid_or_expired", 403)
        request_hash = hashlib.sha256(canonical(payload)).hexdigest()
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._verify_signature(payload["signature"], task_id, payload["task_type"], time.time()):
                return self.reject(task_id, event_id, "signature_invalid_or_expired", 403, conn=conn)
            row = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                return self.reject(task_id, event_id, "task_not_found", 404, conn=conn)
            if row["action_label"] != payload["task_type"]:
                return self.reject(task_id, event_id, "task_type_mismatch", 409, conn=conn)
            existing = conn.execute("SELECT * FROM task_event WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if existing["task_id"] != task_id or existing["request_hash"] != request_hash:
                    return self.reject(task_id, event_id, "event_id_conflict", 409, conn=conn)
                conn.rollback()
                return 200, {"ok": True, "duplicate": True, "task": self.public_task(row)}
            if row["status"] != "OPEN":
                return self.reject(task_id, event_id, "invalid_transition", 409, conn=conn)
            changed = conn.execute("UPDATE task SET status='COMPLETED', updated_at=? WHERE task_id=? AND status='OPEN'", (timestamp, task_id))
            if changed.rowcount != 1:
                return self.reject(task_id, event_id, "invalid_transition", 409, conn=conn)
            conn.execute("INSERT INTO task_event VALUES (?,?,?,?,?,?,?)",
                         (event_id, task_id, "complete", request_hash, "OPEN", "COMPLETED", timestamp))
            updated = conn.execute("SELECT * FROM task WHERE task_id=?", (task_id,)).fetchone()
            conn.commit()
        return 200, {"ok": True, "duplicate": False, "task": self.public_task(updated)}
