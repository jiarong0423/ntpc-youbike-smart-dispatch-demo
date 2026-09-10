from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public_shell"))

from task_ledger import TaskStore


class TaskWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "task.sqlite3"
        self.store = TaskStore(self.db_path, ROOT)
        self.fixture = json.loads(
            (ROOT / "fixtures" / "sealed.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(6, self.store.seed_result(self.fixture))
        self.task_id = "task-banqiao-venue-dispatch"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def event(self, sequence: int, event_type: str) -> dict[str, str]:
        return {
            "event_id": f"evt-test-sequence-{sequence:02d}",
            "event_type": event_type,
            "actor_alias": "operator-01",
        }

    def test_full_lifecycle_and_idempotency(self) -> None:
        status, claim = self.store.apply_event(
            self.task_id,
            self.event(1, "claim"),
        )
        self.assertEqual(200, status)
        self.assertEqual("claimed", claim["task"]["status"])

        status, duplicate = self.store.apply_event(
            self.task_id,
            self.event(1, "claim"),
        )
        self.assertEqual(200, status)
        self.assertTrue(duplicate["duplicate"])

        status, arrived = self.store.apply_event(
            self.task_id,
            self.event(2, "arrive"),
        )
        self.assertEqual(200, status)
        self.assertEqual("arrived", arrived["task"]["status"])

        status, completed = self.store.apply_event(
            self.task_id,
            self.event(3, "complete"),
        )
        self.assertEqual(200, status)
        self.assertEqual("completed", completed["task"]["status"])

        reopened = TaskStore(self.db_path, ROOT)
        self.assertEqual(
            "completed",
            reopened.get_task(self.task_id)["status"],
        )

    def test_invalid_transition_is_fail_closed(self) -> None:
        status, response = self.store.apply_event(
            self.task_id,
            self.event(4, "complete"),
        )
        self.assertEqual(409, status)
        self.assertEqual("invalid_transition", response["error"])
        self.assertEqual(
            "pending",
            self.store.get_task(self.task_id)["status"],
        )

    def test_database_inside_repository_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "task_database_must_be_outside_project",
        ):
            TaskStore(ROOT / "runtime.sqlite3", ROOT)


if __name__ == "__main__":
    unittest.main()
