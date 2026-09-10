from __future__ import annotations

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
        self.assertEqual(3, len(tasks))
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


if __name__ == "__main__":
    unittest.main()
