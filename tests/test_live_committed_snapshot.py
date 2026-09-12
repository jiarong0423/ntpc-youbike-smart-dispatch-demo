from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import socket
import tempfile
import unittest
from urllib import error


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "public_shell"))

from serve_public_blackbox_gateway import (
    DEFAULT_BLACKBOX_URL,
    canonical_json,
    fetch_blackbox_result,
    validate_blackbox_response,
)
from contract_samples import contract_only_sealed_result


def unused_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LiveBoundaryTests(unittest.TestCase):
    """CI boundary tests; real LIVE 8782 evidence belongs to the main run."""

    def test_default_blackbox_endpoint_is_sanitized_mediator_8782(self) -> None:
        self.assertEqual(
            "http://127.0.0.1:8782/api/v1/dispatch/evaluate",
            DEFAULT_BLACKBOX_URL,
        )

    def test_unreachable_loopback_mediator_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            credential = Path(temporary) / "mediator.token"
            credential.write_text(
                "ybx_v1_" + "a" * 64,
                encoding="utf-8",
            )
            credential.chmod(0o600)
            endpoint = (
                "http://127.0.0.1:"
                f"{unused_loopback_port()}"
                "/api/v1/dispatch/evaluate"
            )
            with self.assertRaises(error.URLError):
                fetch_blackbox_result(endpoint, credential, 0.2)

    def test_contract_validator_rejects_stale_source(self) -> None:
        now = datetime.now(timezone.utc)
        result = contract_only_sealed_result(now=now)
        wrapped = {
            "schema_version": "youbike.blackbox_response.v1",
            "request_id": "req-contract-stale",
            "generated_at": now.isoformat(),
            "source_snapshot_at": (
                now - timedelta(minutes=31)
            ).isoformat(),
            "credential_expires_at": (
                now + timedelta(hours=1)
            ).isoformat(),
            "result_sha256": hashlib.sha256(
                canonical_json(result)
            ).hexdigest(),
            "result": result,
        }
        with self.assertRaisesRegex(ValueError, "source_snapshot_at_stale"):
            validate_blackbox_response(
                wrapped,
                wrapped["request_id"],
                now=now,
            )

    def test_contract_validator_rejects_hash_mismatch(self) -> None:
        now = datetime.now(timezone.utc)
        result = contract_only_sealed_result(now=now)
        wrapped = {
            "schema_version": "youbike.blackbox_response.v1",
            "request_id": "req-contract-hash",
            "generated_at": now.isoformat(),
            "source_snapshot_at": now.isoformat(),
            "credential_expires_at": (
                now + timedelta(hours=1)
            ).isoformat(),
            "result_sha256": "0" * 64,
            "result": result,
        }
        with self.assertRaisesRegex(ValueError, "blackbox_result_hash_mismatch"):
            validate_blackbox_response(
                wrapped,
                wrapped["request_id"],
                now=now,
            )


if __name__ == "__main__":
    unittest.main()
