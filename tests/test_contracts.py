from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from contract_samples import contract_only_sealed_result

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_contract_only_sealed_result_matches_schema(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "sealed_result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        contract_sample = contract_only_sealed_result()
        errors = list(
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).iter_errors(contract_sample)
        )
        self.assertEqual([], errors)

    def test_dispatch_contract_does_not_truncate_at_twenty_cases(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "sealed_result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        contract_sample = contract_only_sealed_result()
        template = contract_sample["selected_cases"][0]
        contract_sample["selected_cases"] = []
        for index in range(36):
            item = deepcopy(template)
            item["case_id"] = f"case-contract-{index:02d}"
            contract_sample["selected_cases"].append(item)
        contract_sample["summary"]["active_case_count"] = 36
        contract_sample["districts"][0]["case_count"] = 36
        errors = list(
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).iter_errors(contract_sample)
        )
        self.assertEqual([], errors)

    def test_blackbox_request_contract_has_no_limit_field(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "blackbox_request.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("limit", schema["required"])
        self.assertNotIn("limit", schema["properties"])

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
        task.update({
            "status": "EXPIRED",
            "accepted": False,
            "accepted_at": None,
            "arrived": False,
            "arrived_at": None,
        })
        self.assertEqual([], list(validator.iter_errors(task)))


if __name__ == "__main__":
    unittest.main()
