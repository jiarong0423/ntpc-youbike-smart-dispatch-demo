from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_sealed_fixture_matches_schema(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "sealed_result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        fixture = json.loads(
            (ROOT / "fixtures" / "sealed.json").read_text(
                encoding="utf-8"
            )
        )
        errors = list(
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).iter_errors(fixture)
        )
        self.assertEqual([], errors)

    def test_bedrock_fixture_matches_schema(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "bedrock_explainer.schema.json").read_text(
                encoding="utf-8"
            )
        )
        fixture = json.loads(
            (ROOT / "fixtures" / "bedrock_summary_v1.json").read_text(
                encoding="utf-8"
            )
        )
        errors = list(
            Draft202012Validator(schema).iter_errors(fixture)
        )
        self.assertEqual([], errors)

    def test_all_json_files_parse(self) -> None:
        for path in sorted(ROOT.rglob("*.json")):
            with self.subTest(path=path.relative_to(ROOT)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_task_event_requires_explicit_arrive_type(self) -> None:
        schema = json.loads((ROOT / "contracts" / "task_event_request.schema.json").read_text(encoding="utf-8"))
        payload = {
            "task_id": "task-contract-test",
            "task_type": "observe",
            "event_id": "evt-contract-arrive",
            "device_hash": "a" * 64,
            "signature": "grant." + "b" * 64,
            "occurred_at": "2026-09-11T00:00:00+00:00",
            "event_type": "arrive",
        }
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual([], list(validator.iter_errors(payload)))
        payload.pop("event_type")
        self.assertTrue(list(validator.iter_errors(payload)))

    def test_task_response_binds_arrival_flag_to_timestamp(self) -> None:
        schema = json.loads((ROOT / "contracts" / "task_response.schema.json").read_text(encoding="utf-8"))
        task = {
            "task_id": "task-contract-test",
            "case_id": "case-contract-test",
            "display_name": "Contract test",
            "district_id": "ntpc-test",
            "action_label": "observe",
            "priority_band": "low",
            "route_label": "route",
            "eta_band": "none",
            "status": "OPEN",
            "accepted": True,
            "accepted_at": "2026-09-11T00:00:00+00:00",
            "arrived": True,
            "arrived_at": "2026-09-11T00:01:00+00:00",
            "updated_at": "2026-09-11T00:01:00+00:00",
            "task_type": "observe",
        }
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual([], list(validator.iter_errors(task)))
        task["arrived_at"] = None
        self.assertTrue(list(validator.iter_errors(task)))


if __name__ == "__main__":
    unittest.main()
