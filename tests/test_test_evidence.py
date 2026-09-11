from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "TEST_EVIDENCE.md"

REQUIRED_LITERALS = (
    "OFFLINE_FIXTURE",
    "LIVE_LOCAL_SANDBOX",
    "2026-09-11T21:55:23+08:00",
    "2026-09-11T22:01:37+08:00",
)

REQUIRED_FACT_PATTERNS = (
    re.compile(
        r"(?:20\s*/\s*20.{0,24}(?:detail|details|\u8a73\u60c5)"
        r"|(?:detail|details|\u8a73\u60c5).{0,24}20\s*/\s*20)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:20\s*/\s*20.{0,24}QR|QR.{0,24}20\s*/\s*20)",
        re.IGNORECASE,
    ),
    re.compile(r"8\s*/\s*8"),
    re.compile(
        r"200\s*(?:rounds?|\u8f2a).{0,40}"
        r"1,?000\s*(?:cases?|\u6848\u4f8b)",
        re.IGNORECASE,
    ),
)

FORBIDDEN_PATTERNS = (
    re.compile("/" + "Users/"),
    re.compile(r"127\.0\.0\.1"),
    re.compile(r"192\.168\."),
    re.compile(r"AWS_SECRET_ACCESS_KEY", re.IGNORECASE),
    re.compile(r"AWS_SESSION_TOKEN", re.IGNORECASE),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        r"(?:X-Amz-Signature|signature|sig|token)\s*=",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:device[_ -]?serial|serial[_ -]?number|adb[_ -]?serial)",
        re.IGNORECASE,
    ),
    re.compile(
        r"device[_ -]?fingerprint\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\u7c3d\u7ae0\s*[:=]\s*\S+"),
    re.compile(r"\u88dd\u7f6e\u5e8f\u865f\s*[:=]\s*\S+"),
)


class TestEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(
            EVIDENCE_PATH.is_file(),
            "TEST_EVIDENCE.md must exist at the repository root",
        )
        self.text = EVIDENCE_PATH.read_text(encoding="utf-8")

    def test_required_modes_timestamps_and_facts(self) -> None:
        for literal in REQUIRED_LITERALS:
            with self.subTest(literal=literal):
                self.assertIn(literal, self.text)

        for pattern in REQUIRED_FACT_PATTERNS:
            with self.subTest(pattern=pattern.pattern):
                self.assertRegex(self.text, pattern)

    def test_external_platforms_are_explicitly_not_validated(self) -> None:
        section_match = re.search(
            r"^##\s*(?:Not validated|\u5c1a\u672a\u9a57\u6536)\s*$"
            r"(?P<body>.*?)(?=^##\s|\Z)",
            self.text,
            flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(
            section_match,
            "TEST_EVIDENCE.md must contain a not-validated section",
        )
        section = section_match.group("body")
        for platform in ("AWS", "4G", "5G", "Windows"):
            with self.subTest(platform=platform):
                self.assertRegex(
                    section,
                    re.compile(platform, re.IGNORECASE),
                )

    def test_evidence_contains_no_sensitive_runtime_values(self) -> None:
        findings = [
            pattern.pattern
            for pattern in FORBIDDEN_PATTERNS
            if pattern.search(self.text)
        ]
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
