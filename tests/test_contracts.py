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


if __name__ == "__main__":
    unittest.main()
