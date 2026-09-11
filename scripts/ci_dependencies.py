"""Install the reviewed public dependencies in an ephemeral GitHub runner."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REVIEWED = ("jsonschema==4.25.1", "qrcode==8.2")


def reviewed_requirements(path: Path) -> tuple[str, ...]:
    actual = tuple(path.read_text(encoding="utf-8").splitlines())
    if actual != REVIEWED:
        raise ValueError("dependency_contract_changed_review_required")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        packages = reviewed_requirements(ROOT / "requirements.txt")
        if not args.execute:
            logging.info("dependency_contract=PASS mode=check_only count=%d", len(packages))
            return 0
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
            raise ValueError("execution_requires_ephemeral_windows_github_runner")
        command = [
            sys.executable, "-m", "pip", "--isolated", "install",
            "--disable-pip-version-check", "--only-binary=:all:",
            "--index-url", "https://pypi.org/simple", *packages,
        ]
        completed = subprocess.run(command, check=False, timeout=300)
        logging.info("dependency_install_exit=%d", completed.returncode)
        return completed.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logging.error("dependency_gate_failed type=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
