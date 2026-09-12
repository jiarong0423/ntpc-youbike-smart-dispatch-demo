#!/usr/bin/env python3
"""Refresh the integrity hashes of an already reviewed public package allowlist.

The allowlist is a review decision, not an inventory of whatever happens to sit in
the working tree. A file that nobody approved must not become a published file just
because someone ran this script: new paths are reported and the run fails until they
are admitted explicitly with --approve.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "PUBLIC_EXPORT_MANIFEST.json"
# Mirrors .gitignore: anything Git refuses to track must never be describable as an
# approved public file either.
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".aws", "runtime", "security-audit-output"}
EXCLUDED_NAMES = {".DS_Store", MANIFEST_PATH.name}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite3", ".sqlite3-shm", ".sqlite3-wal"}
EXCLUDED_PREFIXES = (".env",)
REMOVED_PATHS = {
    "controller",
    "fixtures/sealed.json",
    "public_shell/app.js",
    "public_shell/index.html",
    "public_shell/media",
    "public_shell/styles.css",
}


def repository_files() -> list[str]:
    offenders: list[str] = []
    result: list[str] = []
    for candidate in ROOT.rglob("*"):
        if (
            not candidate.is_file()
            or any(part in EXCLUDED_PARTS for part in candidate.parts)
            or candidate.name in EXCLUDED_NAMES
            or candidate.suffix.lower() in EXCLUDED_SUFFIXES
            or candidate.name.startswith(EXCLUDED_PREFIXES)
            or candidate.is_symlink()
        ):
            continue
        relative = candidate.relative_to(ROOT).as_posix()
        if any(
            relative == removed or relative.startswith(removed + "/")
            for removed in REMOVED_PATHS
        ):
            offenders.append(relative)
            continue
        result.append(relative)
    if offenders:
        raise RuntimeError(
            "removed_dashboard_or_fixture_path_present:"
            + ",".join(sorted(offenders))
        )
    return sorted(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approve",
        action="append",
        default=[],
        metavar="PATH",
        help="Admit one reviewed path that is not yet in the allowlist. Repeatable.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift and exit without writing the manifest.",
    )
    args = parser.parse_args()

    existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    approved = set(existing["allowed_files"]) | set(args.approve)
    present = repository_files()

    unreviewed = sorted(set(present) - approved)
    if unreviewed:
        print("unreviewed_files_present:")
        for item in unreviewed:
            print(f"  {item}")
        print("Review each one, then re-run with --approve <path> for the ones that ship.")
        return 1

    missing = sorted(approved - set(present))
    if missing:
        print("approved_files_missing:")
        for item in missing:
            print(f"  {item}")
        print("Remove them from allowed_files if the removal was intended.")
        return 1

    relative = sorted(present)
    if args.check:
        print(f"manifest_check_ok files={len(relative)}")
        return 0

    payload = {
        "schema_version": existing["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": existing["repository"],
        "public_claim": existing["public_claim"],
        "allowed_files": relative,
        "sha256": {
            item: hashlib.sha256((ROOT / item).read_bytes()).hexdigest()
            for item in relative
        },
        "denied_classes": existing["denied_classes"],
    }
    temporary = MANIFEST_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(MANIFEST_PATH)
    print(f"manifest_updated files={len(relative)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
