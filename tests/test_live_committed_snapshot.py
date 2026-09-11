from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "sealed.json"
TAIPEI = timezone(timedelta(hours=8))


def canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class BlackboxController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls = 0
        self._result: dict[str, object] = {}
        self._source_snapshot_at = ""
        self.set_generation("sealed-live-one", marker="generation-one")

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def set_generation(
        self,
        package_id: str,
        *,
        marker: str,
        source_age_seconds: float = 0,
    ) -> None:
        now = datetime.now(timezone.utc)
        result = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        result["package_id"] = package_id
        result["generated_at"] = now.astimezone(TAIPEI).isoformat(
            timespec="seconds"
        )
        result["runtime_mode"] = "LIVE_LOCAL_SANDBOX"
        result["demo_scope"]["data_class"] = "sealed_blackbox_result"
        result["demo_scope"]["public_claim"] = "private_algorithm_attached"
        result["summary"]["mode_banner"] = "本機黑箱 LIVE 測試"
        result["selected_cases"][0]["display_name"] = marker
        source_snapshot_at = (
            now - timedelta(seconds=source_age_seconds)
        ).isoformat(timespec="seconds")
        with self._lock:
            self._result = result
            self._source_snapshot_at = source_snapshot_at

    def response(self, request_id: str) -> dict[str, object]:
        with self._lock:
            self._calls += 1
            result = deepcopy(self._result)
            source_snapshot_at = self._source_snapshot_at
        now = datetime.now(timezone.utc)
        return {
            "schema_version": "youbike.blackbox_response.v1",
            "request_id": request_id,
            "generated_at": now.isoformat(timespec="seconds"),
            "source_snapshot_at": source_snapshot_at,
            "credential_expires_at": (
                now + timedelta(hours=1)
            ).isoformat(timespec="seconds"),
            "result_sha256": hashlib.sha256(
                canonical_json(result)
            ).hexdigest(),
            "result": result,
        }


class FakeBlackboxHandler(BaseHTTPRequestHandler):
    server_version = "TestBlackbox/1.0"

    def do_GET(self) -> None:
        if self.path != "/api/health":
            self.send_error(404)
            return
        self.send_json(200, {"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/api/v1/dispatch/evaluate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        controller = self.server.controller  # type: ignore[attr-defined]
        self.send_json(200, controller.response(payload["request_id"]))

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = canonical_json(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


GATEWAY_WRAPPER = r"""
import os
import sqlite3
import sys
import threading as real_threading
import types

sys.path.insert(0, os.environ["TEST_PUBLIC_SHELL"])
import serve_public_blackbox_gateway as app


class FastEvent:
    def __init__(self):
        self._event = real_threading.Event()

    def is_set(self):
        return self._event.is_set()

    def set(self):
        return self._event.set()

    def wait(self, timeout=None):
        if timeout == 30:
            timeout = float(os.environ["TEST_SYNC_INTERVAL"])
        return self._event.wait(timeout)


app.threading = types.SimpleNamespace(
    Event=FastEvent,
    Lock=real_threading.Lock,
    Thread=real_threading.Thread,
)
app.MAX_COMMITTED_RESULT_AGE_SECONDS = float(
    os.environ["TEST_MAX_COMMITTED_AGE"]
)
original_seed = app.TaskStore.seed_result
fail_package = os.environ.get("TEST_FAIL_PACKAGE", "")
remaining_lock_failures = int(os.environ.get("TEST_LOCK_FAILURES", "0"))


def controlled_seed(self, result):
    global remaining_lock_failures
    if remaining_lock_failures:
        remaining_lock_failures -= 1
        raise sqlite3.OperationalError("database is locked")
    if fail_package and result["package_id"] == fail_package:
        raise ValueError("test_seed_failure")
    return original_seed(self, result)


app.TaskStore.seed_result = controlled_seed
raise SystemExit(app.main())
"""


class LiveGatewayHarness:
    def __init__(
        self,
        controller: BlackboxController,
        *,
        sync_interval: float = 30,
        lock_failures: int = 0,
        max_committed_age: float = 90,
        fail_package: str = "",
    ) -> None:
        self.controller = controller
        self.sync_interval = sync_interval
        self.lock_failures = lock_failures
        self.max_committed_age = max_committed_age
        self.fail_package = fail_package
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.gateway_port = free_port()
        self.gateway_base = f"http://127.0.0.1:{self.gateway_port}"
        self.blackbox = ThreadingHTTPServer(
            ("127.0.0.1", 0), FakeBlackboxHandler
        )
        self.blackbox.controller = controller  # type: ignore[attr-defined]
        self.blackbox_thread = threading.Thread(
            target=self.blackbox.serve_forever,
            daemon=True,
        )
        self.process: subprocess.Popen[str] | None = None
        self.db_path = self.temp_path / "tasks.sqlite3"

    def __enter__(self) -> "LiveGatewayHarness":
        self.blackbox_thread.start()
        credential = self.temp_path / "blackbox.token"
        credential.write_text("ybx_v1_" + "a" * 64, encoding="utf-8")
        credential.chmod(0o600)
        env = os.environ.copy()
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "TEST_PUBLIC_SHELL": str(ROOT / "public_shell"),
                "TEST_SYNC_INTERVAL": str(self.sync_interval),
                "TEST_MAX_COMMITTED_AGE": str(self.max_committed_age),
                "TEST_FAIL_PACKAGE": self.fail_package,
                "TEST_LOCK_FAILURES": str(self.lock_failures),
                "YOUBIKE_BLACKBOX_CREDENTIAL_FILE": str(credential),
                "YOUBIKE_BLACKBOX_URL": (
                    "http://127.0.0.1:"
                    f"{self.blackbox.server_port}"
                    "/api/v1/dispatch/evaluate"
                ),
            }
        )
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                GATEWAY_WRAPPER,
                "--bind",
                "127.0.0.1",
                "--port",
                str(self.gateway_port),
                "--directory",
                str(ROOT),
                "--task-db",
                str(self.db_path),
                "--public-base-url",
                self.gateway_base,
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.wait_until(lambda: self.db_path.exists())
        return self

    def __exit__(self, *_args: object) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        if self.process is not None and self.process.stderr is not None:
            self.process.stderr.close()
        self.blackbox.shutdown()
        self.blackbox.server_close()
        self.blackbox_thread.join(timeout=2)
        self.temp.cleanup()

    def wait_until(self, predicate, *, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                self.fail_with_process_status()
            if predicate():
                return
            time.sleep(0.025)
        raise AssertionError("condition_not_reached_before_timeout")

    def fail_with_process_status(self) -> None:
        code = self.process.returncode if self.process is not None else None
        stderr = ""
        if self.process is not None and self.process.stderr is not None:
            stderr = self.process.stderr.read()
        raise AssertionError(f"gateway_exited_early:{code}:{stderr}")

    def get_result(self) -> tuple[int, dict[str, object]]:
        try:
            with request.urlopen(
                self.gateway_base + "/api/blackbox/result",
                timeout=2,
            ) as response:
                return response.status, json.loads(response.read())
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read())
        except error.URLError:
            return 0, {}

    def wait_for_package(self, package_id: str) -> dict[str, object]:
        result: dict[str, object] = {}

        def committed() -> bool:
            nonlocal result
            status, result = self.get_result()
            return status == 200 and result.get("package_id") == package_id

        self.wait_until(committed)
        return result

    def database_snapshot(self) -> tuple[object, ...]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return tuple(
                tuple(conn.execute(f"SELECT * FROM {table} ORDER BY 1"))
                for table in ("task", "task_event", "task_attempt")
            )

    def task_count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM task").fetchone()[0])


class LiveCommittedSnapshotTests(unittest.TestCase):
    """LIVE publication contract tests.

    The test-only wrapper accelerates the 30-second poll and can inject a
    deterministic seed failure. It does not bypass response validation and it
    runs the real gateway, TaskStore, SQLite schema, and HTTP GET route.
    """

    def test_transient_database_lock_retries_without_publishing_failed_seed(self) -> None:
        controller = BlackboxController()
        with LiveGatewayHarness(controller, sync_interval=0.1, lock_failures=2) as live:
            result = live.wait_for_package("sealed-live-one")
            self.assertEqual("sealed-live-one", result["package_id"])
            self.assertGreaterEqual(controller.calls, 3)
            self.assertGreater(live.task_count(), 0)

    def test_sealed_result_is_published_only_after_seed_succeeds(self) -> None:
        controller = BlackboxController()
        controller.set_generation(
            "sealed-seed-fail",
            marker="must-not-publish",
        )
        with LiveGatewayHarness(
            controller,
            sync_interval=0.1,
            fail_package="sealed-seed-fail",
        ) as live:
            live.wait_until(lambda: controller.calls >= 2)
            status, _body = live.get_result()
            self.assertEqual(503, status)
            self.assertEqual(0, live.task_count())

            controller.set_generation(
                "sealed-live-after-seed",
                marker="publish-after-seed",
            )
            result = live.wait_for_package("sealed-live-after-seed")
            self.assertEqual("publish-after-seed", result["selected_cases"][0]["display_name"])
            self.assertGreater(live.task_count(), 0)

    def test_repeated_get_does_not_refetch_or_write_task_database(self) -> None:
        controller = BlackboxController()
        with LiveGatewayHarness(controller) as live:
            live.wait_for_package("sealed-live-one")
            calls_before = controller.calls
            with closing(sqlite3.connect(live.db_path)) as observer:
                version_before = observer.execute("PRAGMA data_version").fetchone()[0]
                rows_before = live.database_snapshot()
                for _ in range(8):
                    status, body = live.get_result()
                    self.assertEqual(200, status)
                    self.assertEqual("sealed-live-one", body["package_id"])
                version_after = observer.execute("PRAGMA data_version").fetchone()[0]
            self.assertEqual(calls_before, controller.calls)
            self.assertEqual(version_before, version_after)
            self.assertEqual(rows_before, live.database_snapshot())

    def test_seed_failure_keeps_previous_committed_generation(self) -> None:
        controller = BlackboxController()
        with LiveGatewayHarness(
            controller,
            sync_interval=0.1,
            max_committed_age=5,
            fail_package="sealed-seed-fail",
        ) as live:
            first = live.wait_for_package("sealed-live-one")
            rows_before = live.database_snapshot()
            calls_before = controller.calls
            controller.set_generation(
                "sealed-seed-fail",
                marker="must-not-replace",
            )
            live.wait_until(lambda: controller.calls >= calls_before + 2)
            status, after = live.get_result()
            self.assertEqual(200, status)
            self.assertEqual(first, after)
            self.assertEqual(rows_before, live.database_snapshot())

    def test_source_snapshot_older_than_30_minutes_is_unavailable(self) -> None:
        controller = BlackboxController()
        controller.set_generation(
            "sealed-live-stale-source",
            marker="stale-source",
            source_age_seconds=31 * 60,
        )
        with LiveGatewayHarness(controller, max_committed_age=90) as live:
            live.wait_until(lambda: controller.calls >= 1)
            live.wait_until(lambda: live.get_result()[0] != 0)
            status, body = live.get_result()
            self.assertEqual(
                503,
                status,
                f"stale source was published: {body.get('package_id')}",
            )

    def test_invalid_stale_source_cannot_refresh_committed_heartbeat(self) -> None:
        controller = BlackboxController()
        with LiveGatewayHarness(
            controller,
            sync_interval=0.1,
            max_committed_age=0.4,
        ) as live:
            live.wait_for_package("sealed-live-one")
            calls_before = controller.calls
            controller.set_generation(
                "sealed-live-one",
                marker="stale-source-must-not-renew-heartbeat",
                source_age_seconds=31 * 60,
            )
            time.sleep(0.8)
            self.assertGreater(controller.calls, calls_before)
            status, body = live.get_result()
            self.assertEqual(
                503,
                status,
                f"stale source renewed heartbeat: {body.get('package_id')}",
            )


if __name__ == "__main__":
    unittest.main()
