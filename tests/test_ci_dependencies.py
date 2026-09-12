from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_dependencies", ROOT / "scripts/ci_dependencies.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class DependencyGateTests(unittest.TestCase):
    def test_reviewed_versions(self):
        self.assertEqual(gate.REVIEWED, gate.reviewed_requirements(ROOT / "requirements.txt"))

    def test_rejects_options_urls_and_version_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            for value in ("--extra-index-url https://example.invalid", "jsonschema>=4", "qrcode @ https://example.invalid/a.whl"):
                path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    gate.reviewed_requirements(path)

    def test_check_only_cannot_invoke_pip(self):
        with patch("sys.argv", ["ci_dependencies.py"]), patch.object(gate.subprocess, "run") as run:
            self.assertEqual(0, gate.main())
            run.assert_not_called()

    def test_execution_rejected_outside_runner(self):
        with patch("sys.argv", ["ci_dependencies.py", "--execute"]), patch.dict(os.environ, {}, clear=True), patch.object(gate.subprocess, "run") as run:
            self.assertEqual(1, gate.main())
            run.assert_not_called()
