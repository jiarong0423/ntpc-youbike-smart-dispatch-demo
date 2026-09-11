from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public_shell"))

import bedrock_explainer_adapter as adapter


class BedrockBoundaryTests(unittest.TestCase):
    def test_fixture_is_sanitized(self) -> None:
        payload = adapter.load_payload(
            ROOT / "fixtures" / "bedrock_summary_v1.json"
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).lower()
        for denied in (
            "station_id",
            "station_name",
            "latitude",
            "longitude",
            "/users/",
            ".sqlite",
        ):
            self.assertNotIn(denied, encoded)
        self.assertTrue(
            payload["policy_boundary"]["do_not_decide_dispatch"]
        )

    def test_explicit_named_profile_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "aws_profile_invalid",
                ):
                    adapter.isolated_environment(
                        "",
                        "ap-southeast-2",
                        Path(temp),
                    )

    def test_prepare_only_does_not_call_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            session = Path(temp) / "session"
            argv = [
                "--payload",
                str(
                    ROOT
                    / "fixtures"
                    / "bedrock_summary_v1.json"
                ),
                "--output-dir",
                str(output),
                "--session-dir",
                str(session),
                "--profile",
                "explicit-test-profile",
            ]
            with mock.patch(
                "sys.argv",
                ["bedrock_explainer_adapter.py", *argv],
            ):
                self.assertEqual(0, adapter.main())
            summary = json.loads(
                (output / "bedrock_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(summary["bedrock_called"])
            self.assertTrue(summary["preparation_valid"])
            self.assertFalse(summary["inference_succeeded"])
            self.assertTrue(summary["profile_configured"])
            self.assertNotIn("profile", summary)


if __name__ == "__main__":
    unittest.main()
