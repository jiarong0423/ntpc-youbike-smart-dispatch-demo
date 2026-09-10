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
        self.fixture = json.loads((ROOT / "fixtures" / "sealed.json").read_text())
        self.assertEqual(6, self.store.seed_result(self.fixture))
        self.task_id = "task-banqiao-venue-dispatch"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def event(self, sequence: int = 1, task_id: str | None = None) -> dict[str, str]:
        target = task_id or self.task_id
        grant = self.store.issue_signature(target)
        return {"task_id": target, "task_type": grant["task_type"],
                "event_id": f"evt-test-sequence-{sequence:02d}",
                "device_hash": hashlib.sha256((grant["device_salt"] + ":ephemeral-random").encode()).hexdigest(),
                "signature": grant["signature"], "occurred_at": datetime.now(timezone.utc).isoformat()}

    def counts(self):
        with closing(self.store.connect()) as conn:
            self.assertEqual("ok", conn.execute("PRAGMA integrity_check").fetchone()[0])
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("task_event", "task_attempt"))

    def test_complete_idempotency_and_restart(self) -> None:
        event = self.event()
        code, first = self.store.apply_event(self.task_id, event)
        self.assertEqual(200, code)
        self.assertEqual("COMPLETED", first["task"]["status"])
        self.assertFalse(first["duplicate"])
        code, second = self.store.apply_event(self.task_id, event)
        self.assertEqual(200, code)
        self.assertTrue(second["duplicate"])
        self.assertEqual((1, 0), self.counts())
        self.store.seed_result(self.fixture)
        self.assertEqual("COMPLETED", TaskStore(self.db_path, ROOT).get_task(self.task_id)["status"])

    def test_reused_id_with_changed_request_is_conflict(self) -> None:
        event = self.event()
        self.store.apply_event(self.task_id, event)
        for changed in ({**event, "device_hash": "f" * 64},
                        {**event, "occurred_at": datetime.now(timezone.utc).isoformat()}):
            code, result = self.store.apply_event(self.task_id, changed)
            self.assertEqual(409, code)
            self.assertEqual("event_id_conflict", result["error"])
        self.assertEqual((1, 2), self.counts())

    def test_cross_task_reused_event_id_is_conflict(self) -> None:
        first = self.event()
        other_id = next(t["task_id"] for t in self.store.list_tasks() if t["task_id"] != self.task_id)
        other = self.event(task_id=other_id)
        self.store.apply_event(self.task_id, first)
        self.assertEqual(409, self.store.apply_event(other_id, other)[0])
        self.assertEqual("OPEN", self.store.get_task(other_id)["status"])

    def test_concurrent_distinct_events_complete_once(self) -> None:
        events = [self.event(i) for i in range(12)]
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda event: self.store.apply_event(self.task_id, event), events))
        self.assertEqual(1, sum(code == 200 for code, _ in results))
        self.assertEqual(11, sum(code == 409 for code, _ in results))
        self.assertEqual((1, 11), self.counts())

    def test_concurrent_identical_event_is_idempotent(self) -> None:
        event = self.event()
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda _: self.store.apply_event(self.task_id, event), range(12)))
        self.assertTrue(all(code == 200 for code, _ in results))
        self.assertEqual(1, sum(not body["duplicate"] for _, body in results))
        self.assertEqual((1, 0), self.counts())

    def test_invalid_inputs_only_append_safe_audit(self) -> None:
        event = self.event()
        invalid = [None, {**event, "private": "never-store-me"},
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

    def test_event_insert_failure_rolls_back_completion(self) -> None:
        event = self.event()
        with closing(self.store.connect()) as conn:
            conn.execute("CREATE TRIGGER reject_test_event BEFORE INSERT ON task_event BEGIN SELECT RAISE(ABORT, 'test_failure'); END")
            conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.apply_event(self.task_id, event)
        self.assertEqual("OPEN", self.store.get_task(self.task_id)["status"])
        self.assertEqual((0, 0), self.counts())

    def test_drifted_v2_database_is_not_silently_repaired(self) -> None:
        with closing(self.store.connect()) as conn:
            conn.execute("DROP TABLE task_attempt")
            conn.commit()
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "explicit_migration"):
            TaskStore(self.db_path, ROOT)
        self.assertEqual(before, self.db_path.read_bytes())

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
