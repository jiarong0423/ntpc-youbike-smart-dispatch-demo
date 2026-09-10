from __future__ import annotations

from copy import deepcopy
import hashlib
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public_shell"))

from serve_public_blackbox_gateway import (
    canonical_json,
    validate_blackbox_response,
    validate_future_timestamp,
    validate_recent_timestamp,
    validate_sealed_result,
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class PublicGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(
                    ROOT
                    / "public_shell"
                    / "serve_public_blackbox_gateway.py"
                ),
                "--bind",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--directory",
                str(ROOT),
                "--task-db",
                str(Path(self.temp.name) / "task.sqlite3"),
                "--public-base-url",
                self.base,
                "--offline-fixture",
                str(
                    ROOT
                    / "fixtures"
                    / "sealed.json"
                ),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for _ in range(80):
            if self.process.poll() is not None:
                self.fail("gateway exited early")
            try:
                with request.urlopen(
                    self.base + "/api/health",
                    timeout=0.2,
                ) as response:
                    if response.status == 200:
                        break
            except (error.URLError, TimeoutError):
                time.sleep(0.05)
        else:
            self.fail("gateway did not become ready")

    def tearDown(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=5)
        self.temp.cleanup()

    def get_json(self, path: str) -> dict:
        with request.urlopen(
            self.base + path,
            timeout=2,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_offline_result_task_and_qr(self) -> None:
        result = self.get_json("/api/blackbox/result")
        self.assertEqual(
            "SEALED_DEMO_FIXTURE",
            result["runtime_mode"],
        )
        tasks = self.get_json("/api/handoff/tasks")["tasks"]
        self.assertEqual(6, len(tasks))
        task_id = tasks[0]["task_id"]
        with request.urlopen(
            self.base
            + "/api/handoff/tasks/"
            + task_id
            + "/qr.svg",
            timeout=2,
        ) as response:
            body = response.read()
        self.assertIn(b"<svg", body)
        self.assertNotIn(b"127.0.0.1:8781", body)

    def test_root_redirect_loads_relative_assets(self) -> None:
        with request.urlopen(
            self.base + "/",
            timeout=2,
        ) as response:
            html = response.read().decode("utf-8")
            self.assertEqual(
                "/public_shell/index.html",
                response.url.removeprefix(self.base),
            )
        self.assertIn("./styles.css", html)
        with request.urlopen(
            self.base + "/public_shell/styles.css",
            timeout=2,
        ) as response:
            self.assertEqual(200, response.status)
        with request.urlopen(
            self.base + "/public_shell/app.js",
            timeout=2,
        ) as response:
            self.assertEqual(200, response.status)

    def test_index_allows_only_explicit_offline_query(self) -> None:
        with request.urlopen(
            self.base + "/public_shell/index.html?mode=offline",
            timeout=2,
        ) as response:
            self.assertEqual(200, response.status)
        with self.assertRaises(error.HTTPError) as blocked:
            request.urlopen(
                self.base + "/public_shell/index.html?mode=live",
                timeout=2,
            )
        self.assertEqual(404, blocked.exception.code)

    def test_task_page_allows_only_valid_task_query(self) -> None:
        tasks = self.get_json("/api/handoff/tasks")["tasks"]
        task_id = tasks[0]["task_id"]
        with request.urlopen(
            self.base
            + "/public_shell/task.html?task_id="
            + task_id,
            timeout=2,
        ) as response:
            self.assertEqual(200, response.status)
        with self.assertRaises(error.HTTPError) as blocked:
            request.urlopen(
                self.base
                + "/public_shell/task.html?task_id="
                + task_id
                + "&extra=1",
                timeout=2,
            )
        self.assertEqual(404, blocked.exception.code)

    def test_static_allowlist_blocks_repository_files(self) -> None:
        with self.assertRaises(error.HTTPError) as blocked:
            request.urlopen(
                self.base + "/README.md",
                timeout=2,
            )
        self.assertEqual(404, blocked.exception.code)

    def test_time_gate_rejects_stale_future_and_missing(self) -> None:
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        stale = (now - timedelta(minutes=31)).isoformat()
        future = (now + timedelta(minutes=6)).isoformat()
        for field_name in (
            "live_result_generated_at",
            "blackbox_response_generated_at",
            "source_snapshot_at",
        ):
            with self.subTest(field=field_name, case="stale"):
                with self.assertRaisesRegex(
                    ValueError,
                    f"{field_name}_stale",
                ):
                    validate_recent_timestamp(
                        stale,
                        field_name,
                        now=now,
                    )
            with self.subTest(field=field_name, case="future"):
                with self.assertRaisesRegex(
                    ValueError,
                    f"{field_name}_future",
                ):
                    validate_recent_timestamp(
                        future,
                        field_name,
                        now=now,
                    )
            with self.subTest(field=field_name, case="missing"):
                with self.assertRaisesRegex(
                    ValueError,
                    f"{field_name}_missing",
                ):
                    validate_recent_timestamp(
                        None,
                        field_name,
                        now=now,
                    )

    def test_stale_live_result_is_rejected(self) -> None:
        live = deepcopy(
            json.loads(
                (ROOT / "fixtures" / "sealed.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        live["runtime_mode"] = "LIVE_LOCAL_SANDBOX"
        live["generated_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).astimezone(
            timezone(timedelta(hours=8))
        ).isoformat(timespec="seconds")
        live["demo_scope"]["data_class"] = (
            "sealed_blackbox_result"
        )
        live["demo_scope"]["public_claim"] = (
            "private_algorithm_attached"
        )
        live["proof_boundary"]["signature_policy"] = (
            "integrity_hash_only"
        )
        with self.assertRaisesRegex(
            ValueError,
            "live_result_generated_at_stale",
        ):
            validate_sealed_result(live)

    def valid_wrapped_response(self, now: datetime) -> dict:
        result = deepcopy(
            json.loads(
                (ROOT / "fixtures" / "sealed.json").read_text(encoding="utf-8")
            )
        )
        return {
            "schema_version": "youbike.blackbox_response.v1",
            "request_id": "req-123456789abc",
            "generated_at": now.isoformat(),
            "source_snapshot_at": now.isoformat(),
            "credential_expires_at": (now + timedelta(hours=2)).isoformat(),
            "result_sha256": hashlib.sha256(canonical_json(result)).hexdigest(),
            "result": result,
        }

    def test_blackbox_response_is_full_schema_fail_closed(self) -> None:
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        valid = self.valid_wrapped_response(now)
        self.assertEqual(
            valid["result"],
            validate_blackbox_response(valid, valid["request_id"], now=now),
        )
        missing = deepcopy(valid)
        del missing["credential_expires_at"]
        with self.assertRaisesRegex(
            ValueError, "blackbox_response_json_schema_invalid"
        ):
            validate_blackbox_response(missing, valid["request_id"], now=now)
        extra = deepcopy(valid)
        extra["private_score"] = 1
        with self.assertRaisesRegex(
            ValueError, "blackbox_response_json_schema_invalid"
        ):
            validate_blackbox_response(extra, valid["request_id"], now=now)

    def test_expired_credential_timestamp_is_rejected(self) -> None:
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(
            ValueError, "credential_expires_at_expired"
        ):
            validate_future_timestamp(
                (now - timedelta(seconds=1)).isoformat(),
                "credential_expires_at",
                now=now,
            )


if __name__ == "__main__":
    unittest.main()
