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
FORBIDDEN_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z])" + "B" + "LE" + r"(?![A-Za-z])",
        re.IGNORECASE,
    ),
)
PRIVATE_ALGORITHM_PATTERNS = (
    re.compile(r"\b(?:weight|threshold|coefficient)\s*=", re.IGNORECASE),
    re.compile(r"\b(?:score|rank)_station\s*\(", re.IGNORECASE),
)


class ExportBoundaryTests(unittest.TestCase):
    @staticmethod
    def manifest() -> dict:
        return json.loads(
            (ROOT / "PUBLIC_EXPORT_MANIFEST.json").read_text(encoding="utf-8")
        )

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
        manifest = self.manifest()
        self.assertEqual(
            set(manifest["allowed_files"]),
            set(manifest["sha256"]),
        )
        mismatches = [
            relative
            for relative, expected in manifest["sha256"].items()
            if hashlib.sha256(
                (ROOT / relative).read_bytes()
            ).hexdigest() != expected
        ]
        self.assertEqual([], mismatches)

    def test_manifest_covers_repository_package(self) -> None:
        ignored_names = {".DS_Store", "PUBLIC_EXPORT_MANIFEST.json"}
        actual = {
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*")
            if (
                path.is_file()
                and ".git" not in path.parts
                and "__pycache__" not in path.parts
                and path.name not in ignored_names
                and path.suffix.lower() != ".pyc"
            )
        }
        self.assertEqual(actual, set(self.manifest()["allowed_files"]))

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

    def test_windows_offline_fixture_exists(self) -> None:
        launcher = (
            ROOT / "public_shell" / "start_windows.cmd"
        ).read_text(encoding="utf-8")
        self.assertIn(
            r"--offline-fixture fixtures\sealed.json",
            launcher,
        )
        self.assertTrue((ROOT / "fixtures" / "sealed.json").is_file())

    def test_public_data_lineage_is_explicit(self) -> None:
        index = (
            ROOT / "public_shell" / "index.html"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        historical = (
            ROOT / "public_shell" / "media" / "historical-coverage.svg"
        ).read_text(encoding="utf-8")
        self.assertIn("2026-01 至 2026-09-11", index)
        self.assertIn("2026-09-08 19:16 至 2026-09-11 01:38", index)
        self.assertIn("本次重點區", index)
        self.assertIn("313 批", index)
        self.assertIn("1,606 站點維度", index)
        self.assertIn('id="lineage-mode"', index)
        self.assertIn('id="lineage-freshness"', index)
        self.assertIn("固定 29 區安全轉換資料", readme)
        self.assertIn("區間化", historical)
        self.assertIn("時間錯位", historical)
        self.assertIn("不能還原單站或精確比例", historical)
        self.assertNotRegex(historical, r">\d+\.\d+%</text>")

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
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    findings.append(
                        f"{path.relative_to(ROOT)}:forbidden_token"
                    )
            for pattern in PRIVATE_ALGORITHM_PATTERNS:
                if pattern.search(text):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{pattern.pattern}"
                    )
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
