from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public_shell"))
from task_ledger import TaskStore


class TaskWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "task.sqlite3"
        self.store = TaskStore(self.db_path, ROOT)
        self.fixture = json.loads((ROOT / "fixtures" / "sealed.json").read_text(encoding="utf-8"))
        self.assertEqual(6, self.store.seed_result(self.fixture))
        self.task_id = "task-banqiao-venue-dispatch"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def event(self, sequence: int = 1, task_id: str | None = None, event_type: str = "complete") -> dict[str, str]:
        target = task_id or self.task_id
        grant = self.store.issue_signature(target)
        return {"task_id": target, "task_type": grant["task_type"],
                "event_id": f"evt-test-sequence-{sequence:02d}",
                "device_hash": grant["device_hash"],
                "signature": grant["signature"], "occurred_at": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type}

    def counts(self):
        with closing(self.store.connect()) as conn:
            self.assertEqual("ok", conn.execute("PRAGMA integrity_check").fetchone()[0])
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("task_event", "task_attempt"))

    def accept(self, task_id: str | None = None, sequence: int = 90) -> dict[str, str]:
        target = task_id or self.task_id
        event = self.event(sequence, target, "accept")
        code, result = self.store.apply_event(target, event)
        self.assertEqual(200, code)
        self.assertTrue(result["task"]["accepted"])
        self.assertEqual("OPEN", result["task"]["status"])
        return event

    def arrive(self, task_id: str | None = None, sequence: int = 91) -> dict[str, str]:
        target = task_id or self.task_id
        event = self.event(sequence, target, "arrive")
        code, result = self.store.apply_event(target, event)
        self.assertEqual(200, code)
        self.assertTrue(result["task"]["arrived"])
        self.assertEqual("OPEN", result["task"]["status"])
        return event

    def test_complete_idempotency_and_restart(self) -> None:
        self.accept()
        self.arrive()
        event = self.event()
        code, first = self.store.apply_event(self.task_id, event)
        self.assertEqual(200, code)
        self.assertEqual("COMPLETED", first["task"]["status"])
        self.assertFalse(first["duplicate"])
        code, second = self.store.apply_event(self.task_id, event)
        self.assertEqual(200, code)
        self.assertTrue(second["duplicate"])
        self.assertEqual((3, 0), self.counts())
        self.store.seed_result(self.fixture)
        self.assertEqual("COMPLETED", TaskStore(self.db_path, ROOT).get_task(self.task_id)["status"])

    def test_reused_id_with_changed_request_is_conflict(self) -> None:
        self.accept()
        self.arrive()
        event = self.event()
        self.store.apply_event(self.task_id, event)
        for changed in ({**event, "event_type": "exception"},
                        {**event, "occurred_at": datetime.now(timezone.utc).isoformat()}):
            code, result = self.store.apply_event(self.task_id, changed)
            self.assertEqual(409, code)
            self.assertEqual("event_id_conflict", result["error"])
        self.assertEqual((3, 2), self.counts())

    def test_cross_task_reused_event_id_is_conflict(self) -> None:
        first = self.event()
        other_id = next(t["task_id"] for t in self.store.list_tasks() if t["task_id"] != self.task_id)
        other = self.event(task_id=other_id)
        self.accept(self.task_id, 80)
        self.accept(other_id, 81)
        self.arrive(self.task_id, 82)
        self.arrive(other_id, 83)
        self.store.apply_event(self.task_id, first)
        self.assertEqual(409, self.store.apply_event(other_id, other)[0])
        self.assertEqual("OPEN", self.store.get_task(other_id)["status"])

    def test_concurrent_distinct_events_complete_once(self) -> None:
        self.accept()
        self.arrive()
        events = [self.event(i) for i in range(12)]
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda event: self.store.apply_event(self.task_id, event), events))
        self.assertEqual(1, sum(code == 200 for code, _ in results))
        self.assertEqual(11, sum(code == 409 for code, _ in results))
        self.assertEqual((3, 11), self.counts())

    def test_concurrent_identical_event_is_idempotent(self) -> None:
        self.accept()
        self.arrive()
        event = self.event()
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda _: self.store.apply_event(self.task_id, event), range(12)))
        self.assertTrue(all(code == 200 for code, _ in results))
        self.assertEqual(1, sum(not body["duplicate"] for _, body in results))
        self.assertEqual((3, 0), self.counts())

    def test_invalid_inputs_only_append_safe_audit(self) -> None:
        event = self.event()
        invalid = [None, {key: value for key, value in event.items() if key != "event_type"},
                   {**event, "private": "never-store-me"},
                   {**event, "device_hash": "raw-device-never-store-me"},
                   {**event, "signature": "broken-secret-never-store-me"},
                   {**event, "task_type": "observe" if event["task_type"] != "observe" else "add_bikes"},
                   {**event, "occurred_at": "2026-09-10T00:00:00"},
                   {**event, "occurred_at": (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()},
                   {**event, "occurred_at": (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()}]
        for payload in invalid:
            self.assertGreaterEqual(self.store.apply_event(self.task_id, payload)[0], 400)
        self.assertEqual("OPEN", self.store.get_task(self.task_id)["status"])
        self.assertEqual((0, len(invalid)), self.counts())
        with closing(self.store.connect()) as conn:
            self.assertNotIn("never-store-me", str([tuple(row) for row in conn.execute("SELECT * FROM task_attempt").fetchall()]))
            self.assertEqual(4, len(conn.execute("PRAGMA table_info(task_attempt)").fetchall()) - 1)

    def test_expired_and_other_process_signature_fail_closed(self) -> None:
        event = self.event()
        with patch("task_ledger.time.time", return_value=time.time() + 301):
            event["occurred_at"] = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
            self.assertEqual(403, self.store.apply_event(self.task_id, event)[0])
        event = self.event()
        self.assertEqual(403, TaskStore(self.db_path, ROOT).apply_event(self.task_id, event)[0])
        self.assertEqual("OPEN", self.store.get_task(self.task_id)["status"])

    def test_unknown_task_and_wrong_type_are_audited(self) -> None:
        event = self.event()
        with closing(self.store.connect()) as conn:
            conn.execute("DELETE FROM task WHERE task_id=?", (self.task_id,))
            conn.commit()
        self.assertEqual(404, self.store.apply_event(self.task_id, event)[0])
        self.store.seed_result(self.fixture)
        with closing(self.store.connect()) as conn:
            conn.execute("UPDATE task SET action_label='observe' WHERE task_id=?", (self.task_id,))
            conn.commit()
        self.assertEqual(409, self.store.apply_event(self.task_id, event)[0])

    def test_operator_report_is_audit_only_and_idempotent(self) -> None:
        self.accept()
        event = self.event(event_type="exception")
        for duplicate in (False, True):
            code, body = self.store.apply_event(self.task_id, event)
            self.assertEqual(200, code)
            self.assertTrue(body["audit_only"])
            self.assertEqual(duplicate, body["duplicate"])
            self.assertEqual("OPEN", body["task"]["status"])
        self.arrive(sequence=2)
        self.assertEqual((3, 0), self.counts())
        self.assertEqual(200, self.store.apply_event(self.task_id, self.event(3))[0])

    def test_device_pseudonym_is_bound_to_signed_grant(self) -> None:
        event = self.event()
        self.assertEqual(403, self.store.apply_event(self.task_id, {**event, "device_hash": "f" * 64})[0])
        self.assertEqual("OPEN", self.store.get_task(self.task_id)["status"])

    def test_event_insert_failure_rolls_back_completion(self) -> None:
        self.accept()
        self.arrive()
        event = self.event()
        with closing(self.store.connect()) as conn:
            conn.execute("CREATE TRIGGER reject_test_event BEFORE INSERT ON task_event BEGIN SELECT RAISE(ABORT, 'test_failure'); END")
            conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.apply_event(self.task_id, event)
        self.assertEqual("OPEN", self.store.get_task(self.task_id)["status"])
        self.assertEqual((2, 0), self.counts())

    def test_completion_requires_acceptance_arrival_and_accept_is_idempotent(self) -> None:
        code, body = self.store.apply_event(self.task_id, self.event(70))
        self.assertEqual(409, code)
        self.assertEqual("task_not_accepted", body["error"])
        accepted_event = self.accept(sequence=71)
        code, duplicate = self.store.apply_event(self.task_id, accepted_event)
        self.assertEqual(200, code)
        self.assertTrue(duplicate["duplicate"])
        code, body = self.store.apply_event(self.task_id, self.event(72))
        self.assertEqual(409, code)
        self.assertEqual("task_not_arrived", body["error"])
        arrived_event = self.arrive(sequence=73)
        code, duplicate = self.store.apply_event(self.task_id, arrived_event)
        self.assertEqual(200, code)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(200, self.store.apply_event(self.task_id, self.event(74))[0])
        self.assertEqual((3, 2), self.counts())

    def test_arrival_requires_acceptance_and_is_concurrency_safe(self) -> None:
        code, body = self.store.apply_event(self.task_id, self.event(61, event_type="arrive"))
        self.assertEqual(409, code)
        self.assertEqual("task_not_accepted", body["error"])
        self.accept(sequence=62)
        events = [self.event(sequence, event_type="arrive") for sequence in range(63, 75)]
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda event: self.store.apply_event(self.task_id, event), events))
        self.assertEqual(1, sum(code == 200 for code, _ in results))
        self.assertEqual(11, sum(code == 409 for code, _ in results))
        task = self.store.get_task(self.task_id)
        self.assertTrue(task["arrived"])
        self.assertIsNotNone(task["arrived_at"])
        self.assertEqual("OPEN", task["status"])

    def test_exception_does_not_change_arrival_state(self) -> None:
        self.accept(sequence=50)
        before = self.store.get_task(self.task_id)
        code, body = self.store.apply_event(self.task_id, self.event(51, event_type="exception"))
        self.assertEqual(200, code)
        self.assertTrue(body["audit_only"])
        self.assertEqual(before["arrived_at"], body["task"]["arrived_at"])
        self.assertFalse(body["task"]["arrived"])

    def test_drifted_v4_database_is_not_silently_repaired(self) -> None:
        with closing(self.store.connect()) as conn:
            conn.execute("DROP TABLE task_attempt")
            conn.commit()
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "explicit_migration"):
            TaskStore(self.db_path, ROOT)
        self.assertEqual(before, self.db_path.read_bytes())

    def test_v3_database_requires_explicit_migration_with_backup(self) -> None:
        old = Path(self.temp.name) / "v3.sqlite3"
        backup = Path(self.temp.name) / "backup" / "v3.sqlite3"
        with closing(sqlite3.connect(old)) as conn:
            conn.executescript(
                """
                CREATE TABLE task (
                    task_id TEXT PRIMARY KEY, case_id TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL, district_id TEXT NOT NULL,
                    action_label TEXT NOT NULL, priority_band TEXT NOT NULL,
                    route_label TEXT NOT NULL, eta_band TEXT NOT NULL,
                    status TEXT NOT NULL, accepted_at TEXT, source_package_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE task_event (
                    event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES task(task_id),
                    event_type TEXT NOT NULL, request_hash TEXT NOT NULL,
                    status_before TEXT NOT NULL, status_after TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE task_attempt (
                    attempt_id INTEGER PRIMARY KEY, task_id TEXT, event_id TEXT,
                    error_code TEXT NOT NULL, created_at TEXT NOT NULL
                );
                INSERT INTO task VALUES (
                    'task-legacy-v3', 'case-legacy-v3', 'Legacy', 'ntpc-test',
                    'observe', 'low', 'route', 'none', 'COMPLETED',
                    '2026-09-11T00:00:00+00:00', 'pkg',
                    '2026-09-11T00:00:00+00:00', '2026-09-11T00:01:00+00:00'
                );
                PRAGMA user_version = 3;
                """
            )
            conn.commit()
        before = old.read_bytes()
        with self.assertRaisesRegex(ValueError, "explicit_migration"):
            TaskStore(old, ROOT)
        self.assertEqual(before, old.read_bytes())
        self.assertEqual(backup.resolve(), TaskStore.migrate_v3_to_v4(old, ROOT, backup))
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(3, conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertNotIn("arrived_at", {row[1] for row in conn.execute("PRAGMA table_info(task)")})
        migrated = TaskStore(old, ROOT)
        task = migrated.get_task("task-legacy-v3")
        self.assertEqual("COMPLETED", task["status"])
        self.assertFalse(task["arrived"])
        self.assertIsNone(task["arrived_at"])

    def test_legacy_database_is_unchanged(self) -> None:
        old = Path(self.temp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(old)) as conn:
            conn.execute("CREATE TABLE task(task_id TEXT, status TEXT)")
            conn.execute("INSERT INTO task VALUES ('task-legacy','claimed')")
            conn.commit()
        before = old.read_bytes()
        with self.assertRaisesRegex(ValueError, "explicit_migration"):
            TaskStore(old, ROOT)
        self.assertEqual(before, old.read_bytes())

    def test_database_inside_repository_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "task_database_must_be_outside_project"):
            TaskStore(ROOT / "runtime.sqlite3", ROOT)


if __name__ == "__main__":
    unittest.main()
