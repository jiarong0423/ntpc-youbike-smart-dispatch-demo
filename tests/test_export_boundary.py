from __future__ import annotations

from pathlib import Path, PurePath, PureWindowsPath
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
REMOVED_DASHBOARD_PATHS = {
    "controller",
    "public_shell/index.html",
    "public_shell/app.js",
    "public_shell/styles.css",
    "public_shell/media",
    "fixtures/sealed.json",
}


def manifest_relative_path(path: PurePath, root: PurePath) -> str:
    return path.relative_to(root).as_posix()


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
            manifest_relative_path(path, ROOT)
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
            manifest_relative_path(path, ROOT)
            for path in ROOT.rglob("*")
            if (
                path.is_file()
                and ".git" not in path.parts
                and ".venv" not in path.parts
                and "__pycache__" not in path.parts
                and path.name not in ignored_names
                and path.suffix.lower() != ".pyc"
            )
        }
        self.assertEqual(actual, set(self.manifest()["allowed_files"]))

    def test_manifest_paths_are_posix_on_windows(self) -> None:
        root = PureWindowsPath("D:/a/demo/demo")
        for relative in (
            "README.md",
            "public_shell/task.js",
            ".github/workflows/public-gate.yml",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(
                    relative,
                    manifest_relative_path(root / relative, root),
                )

    def test_no_private_runtime_files(self) -> None:
        offenders = [
            manifest_relative_path(path, ROOT)
            for path in self.public_files()
            if (
                path.is_file()
                and ".git" not in path.parts
                and path.suffix.lower()
                in FORBIDDEN_FILE_SUFFIXES
            )
        ]
        self.assertEqual([], offenders)

    def test_public_page_topology_and_data_lineage_are_explicit(self) -> None:
        index = (ROOT / "PAGE_AND_WORKSPACE_INDEX.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "/docs/hackathon/2026Q3/"
            "youbike_district_traffic_light_frontend_demo_20260816.html",
            index,
        )
        self.assertIn("三個既有分頁", index)
        self.assertIn("tasks/{task_id}", index)
        self.assertIn("不得提供替代控制台", index)
        self.assertIn("真實 LIVE", index)
        self.assertIn(
            "2026 年 1 至 9 月的輕量特徵快照與天氣特徵",
            readme,
        )
        self.assertIn(
            "單一影子觀察窗持續接收近期站點與天氣流入",
            readme,
        )

    def test_removed_dashboard_and_fixture_paths_stay_absent(self) -> None:
        offenders = [
            relative
            for relative in sorted(REMOVED_DASHBOARD_PATHS)
            if (ROOT / relative).exists()
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
