from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".cmd",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yml",
}
FORBIDDEN_FILE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".wal",
    ".shm",
    ".env",
}
FORBIDDEN_TEXT = {
    "/" + "Users/",
    "AWS_" + "SECRET_ACCESS_KEY=",
    "AWS_" + "SESSION_TOKEN=",
    "BEGIN " + "PRIVATE KEY",
    "raw_" + "station_snapshot",
}
PRIVATE_ALGORITHM_PATTERNS = (
    re.compile(r"\b(?:weight|threshold|coefficient)\s*=", re.IGNORECASE),
    re.compile(r"\b(?:score|rank)_station\s*\(", re.IGNORECASE),
)


class ExportBoundaryTests(unittest.TestCase):
    @staticmethod
    def public_files() -> list[Path]:
        manifest = json.loads(
            (ROOT / "PUBLIC_EXPORT_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        return [ROOT / value for value in manifest["allowed_files"]]

    def test_manifest_files_exist(self) -> None:
        missing = [
            str(path.relative_to(ROOT))
            for path in self.public_files()
            if not path.is_file()
        ]
        self.assertEqual([], missing)

    def test_manifest_hashes_match(self) -> None:
        manifest = json.loads(
            (ROOT / "PUBLIC_EXPORT_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        mismatches = [
            relative
            for relative, expected in manifest["sha256"].items()
            if hashlib.sha256(
                (ROOT / relative).read_bytes()
            ).hexdigest() != expected
        ]
        self.assertEqual([], mismatches)

    def test_no_private_runtime_files(self) -> None:
        offenders = [
            str(path.relative_to(ROOT))
            for path in self.public_files()
            if (
                path.is_file()
                and ".git" not in path.parts
                and path.suffix.lower()
                in FORBIDDEN_FILE_SUFFIXES
            )
        ]
        self.assertEqual([], offenders)

    def test_no_local_paths_secrets_or_algorithm_formulas(self) -> None:
        findings = []
        for path in self.public_files():
            if (
                not path.is_file()
                or ".git" in path.parts
                or path.suffix.lower() not in TEXT_SUFFIXES
            ):
                continue
            text = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
            for value in FORBIDDEN_TEXT:
                if value in text:
                    findings.append(
                        f"{path.relative_to(ROOT)}:{value}"
                    )
            for pattern in PRIVATE_ALGORITHM_PATTERNS:
                if pattern.search(text):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{pattern.pattern}"
                    )
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
