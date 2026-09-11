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
from urllib import error, parse, request
from contextlib import closing
import sqlite3
import os
import shutil
from jsonschema import Draft202012Validator, FormatChecker
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public_shell"))

from aws_task_client import IsolatedTaskSigner, signed_request, NoSignedRedirect, validate_api_endpoint

from serve_public_blackbox_gateway import (
    canonical_json,
    validate_blackbox_response,
    validate_blackbox_url,
    validate_future_timestamp,
    validate_recent_timestamp,
    validate_sealed_result,
    validate_task_event_request,
    CloudTaskStore, CloudUnavailable, validate_task_base, parse_args,
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

    def test_signed_completion_contract_over_http(self) -> None:
        task = self.get_json("/api/handoff/tasks")["tasks"][0]
        path = "/api/handoff/tasks/" + task["task_id"]
        detail = self.get_json(path)
        grant_url = parse.urlparse(detail["completion_url"])
        self.assertTrue(grant_url.fragment)
        self.assertNotIn("signature", grant_url.query)
        grant = dict(parse.parse_qsl(grant_url.fragment))
        payload = {"task_id": task["task_id"], "task_type": task["task_type"],
                   "event_id": "evt-http-completion-01", "device_hash": grant["device_hash"],
                   "signature": grant["signature"], "occurred_at": datetime.now(timezone.utc).isoformat(),
                   "event_type": "complete"}
        event_schema = json.loads((ROOT / "contracts/task_event_request.schema.json").read_text())
        task_schema = json.loads((ROOT / "contracts/task_response.schema.json").read_text())
        Draft202012Validator(event_schema, format_checker=FormatChecker()).validate(payload)
        accept_payload = {**payload, "event_id": "evt-http-accept-0001", "event_type": "accept"}
        Draft202012Validator(event_schema, format_checker=FormatChecker()).validate(accept_payload)
        req = request.Request(self.base + path + "/events", data=canonical_json(accept_payload),
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=2) as response:
            accepted = json.loads(response.read())
        self.assertTrue(accepted["task"]["accepted"])
        self.assertFalse(accepted["task"]["arrived"])
        self.assertEqual("OPEN", accepted["task"]["status"])
        arrive_payload = {**payload, "event_id": "evt-http-arrival-0001", "event_type": "arrive"}
        Draft202012Validator(event_schema, format_checker=FormatChecker()).validate(arrive_payload)
        req = request.Request(self.base + path + "/events", data=canonical_json(arrive_payload),
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=2) as response:
            arrived = json.loads(response.read())
        self.assertTrue(arrived["task"]["arrived"])
        self.assertIsNotNone(arrived["task"]["arrived_at"])
        self.assertEqual("OPEN", arrived["task"]["status"])
        for duplicate in (False, True):
            req = request.Request(self.base + path + "/events", data=canonical_json(payload),
                                  headers={"Content-Type": "application/json"})
            with request.urlopen(req, timeout=2) as response:
                completed = json.loads(response.read())
            self.assertEqual(duplicate, completed["duplicate"])
            self.assertEqual("COMPLETED", completed["task"]["status"])
            Draft202012Validator(task_schema, format_checker=FormatChecker()).validate(completed["task"])
        self.assertIsNone(self.get_json(path)["completion_url"])
        with self.assertRaises(error.HTTPError) as blocked:
            request.urlopen(self.base + path + "/qr.svg", timeout=2)
        self.assertEqual(409, blocked.exception.code)

    def test_unsigned_and_malformed_events_only_append_errors(self) -> None:
        task = self.get_json("/api/handoff/tasks")["tasks"][0]
        path = "/api/handoff/tasks/" + task["task_id"]
        for body in (b'{"event_id":"evt-invalid-0001","event_type":"claim","actor_alias":"private-never-store"}', b'not-json'):
            with self.assertRaises(error.HTTPError):
                request.urlopen(request.Request(self.base + path + "/events", data=body,
                                headers={"Content-Type": "application/json"}), timeout=2)
        self.assertEqual("OPEN", self.get_json(path)["task"]["status"])
        with closing(sqlite3.connect(Path(self.temp.name) / "task.sqlite3")) as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM task_event").fetchone()[0])
            audits = conn.execute("SELECT * FROM task_attempt").fetchall()
            self.assertEqual(2, len(audits))
            self.assertNotIn("private-never-store", str(audits))

    def test_task_route_alias_and_lan_crypto_contract(self) -> None:
        task = self.get_json("/api/handoff/tasks")["tasks"][0]
        detail = self.get_json("/api/handoff/tasks/" + task["task_id"])
        self.assertIn("/tasks/" + task["task_id"] + "#", detail["completion_url"])
        with request.urlopen(self.base + "/tasks/" + task["task_id"]) as response:
            page = response.read().decode("utf-8")
        self.assertIn("完成任務", page)
        self.assertIn("接單", page)
        self.assertIn("確認抵達", page)
        self.assertIn("回報執行異常", page)
        self.assertIn('/public_shell/task.js', page)
        source = (ROOT / "public_shell/task.js").read_text(encoding="utf-8")
        self.assertNotIn("crypto.subtle", source)
        self.assertIn('grant.get("device_hash")', source)

    def test_safe_integration_status_has_only_display_fields(self) -> None:
        status = self.get_json("/api/integration/status")
        self.assertEqual("SEALED_DEMO_FIXTURE", status["source_mode"])
        self.assertEqual("local", status["task_backend"])
        self.assertEqual(29, len(status["districts"]))
        self.assertEqual({"district", "priority_level", "suggested_action"}, set(status["districts"][0]))

    def test_cloud_mode_boundary_and_signer_failure(self) -> None:
        self.assertEqual("https://example.test/stage", validate_task_base("https://example.test/stage/", cloud=True))
        with self.assertRaises(ValueError):
            validate_task_base("http://192.168.1.10", cloud=True)
        store = CloudTaskStore(
            "https://abc1234567.execute-api.us-west-2.amazonaws.com",
            "https://example.test",
            Path(self.temp.name),
            "us-west-2",
            "explicit-test-profile",
        )
        with patch.object(store.signer, "request", side_effect=RuntimeError("redacted")), patch('serve_public_blackbox_gateway.request.urlopen') as network:
            with self.assertRaises(CloudUnavailable):
                store.list_tasks()
            network.assert_not_called()
        self.assertFalse(hasattr(store, "path"))

    def test_blackbox_token_target_is_loopback_only(self) -> None:
        accepted = (
            "http://127.0.0.1:8900/api/v1/dispatch/evaluate",
            "http://localhost:8900/api/v1/dispatch/evaluate",
            "http://[::1]:8900/api/v1/dispatch/evaluate",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(value, validate_blackbox_url(value))

        rejected = (
            "https://example.test/api/v1/dispatch/evaluate",
            "http://192.168.1.10:8900/api/v1/dispatch/evaluate",
            "http://127.0.0.1:8900/wrong",
            "http://127.0.0.1:8900/api/v1/dispatch/evaluate?token=value",
            "http://user@127.0.0.1:8900/api/v1/dispatch/evaluate",
            "http://127.0.0.1/api/v1/dispatch/evaluate",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "blackbox_url_requires_loopback_endpoint",
                ):
                    validate_blackbox_url(value)

    def test_cloud_process_never_creates_sqlite_on_failure(self) -> None:
        cloud_port = free_port()
        forbidden_db = Path(self.temp.name) / "must-not-exist.sqlite3"
        child = subprocess.Popen([sys.executable, str(ROOT / "public_shell/serve_public_blackbox_gateway.py"),
            "--bind", "127.0.0.1", "--port", str(cloud_port), "--task-backend", "cloud",
            "--task-db", str(forbidden_db), "--public-task-base-url", "https://abc1234567.execute-api.us-west-2.amazonaws.com/stage",
            "--aws-session-dir", str(Path(self.temp.name) / "missing-session"),
            "--aws-profile", "explicit-test-profile", "--aws-region", "us-west-2",
            "--offline-fixture", str(ROOT / "fixtures/sealed.json")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                if child.poll() is not None:
                    self.fail("cloud gateway exited")
                try:
                    request.urlopen(f"http://127.0.0.1:{cloud_port}/api/health", timeout=.2).close()
                    break
                except error.URLError:
                    time.sleep(.05)
            for path in ("/api/handoff/tasks", "/api/blackbox/result"):
                with self.assertRaises(error.HTTPError) as unavailable:
                    request.urlopen(f"http://127.0.0.1:{cloud_port}" + path, timeout=2)
                self.assertEqual(503, unavailable.exception.code)
                body = json.loads(unavailable.exception.read())
                self.assertFalse(body["fallback"])
                self.assertEqual("cloud", body["task_backend"])
            self.assertFalse(forbidden_db.exists())
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_cloud_signer_rejects_unrelated_host_before_credentials(self) -> None:
        signer = IsolatedTaskSigner(Path(self.temp.name), "ap-southeast-2", "test-profile")
        invalid = ["https://example.test/tasks", "https://abc1234567.execute-api.ap-northeast-1.amazonaws.com/tasks",
                   "https://abc1234567.execute-api.ap-southeast-2.amazonaws.com.evil.test/tasks",
                   "https://abc1234567.execute-api.ap-southeast-2.amazonaws.com:444/tasks"]
        with patch.object(signer, "credentials") as credentials:
            for url in invalid:
                with self.assertRaises(ValueError):
                    signer.request(url, b"{}")
            credentials.assert_not_called()
        self.assertIsNone(NoSignedRedirect().redirect_request(None, None, 302, "Found", {}, "https://unrelated.test"))
        self.assertEqual("https://abc1234567.execute-api.ap-southeast-2.amazonaws.com/stage", validate_api_endpoint("https://abc1234567.execute-api.ap-southeast-2.amazonaws.com/stage", "ap-southeast-2"))

    def test_cloud_config_requires_explicit_profile_and_fixed_resource_region(self) -> None:
        argv = ["gateway", "--task-backend", "cloud", "--public-task-base-url", "https://example.test/stage"]
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {"AWS_REGION": "ap-northeast-1"}, clear=True):
            args = parse_args()
        self.assertEqual("https://example.test/stage", args.task_cloud_url)
        self.assertEqual("us-west-2", args.aws_region)
        self.assertIsNone(args.aws_profile)
        with patch.object(sys, "argv", argv + ["--task-cloud-url", "https://api.example.test", "--aws-profile", "explicit-test-profile", "--aws-region", "us-west-2"]), patch.dict(os.environ, {"AWS_REGION": "ap-northeast-1"}, clear=True):
            args = parse_args()
        self.assertEqual("https://api.example.test", args.task_cloud_url)
        self.assertEqual("us-west-2", args.aws_region)
        self.assertEqual("explicit-test-profile", args.aws_profile)
        with self.assertRaisesRegex(ValueError, "cloud_resource_region_must_be_us_west_2"):
            CloudTaskStore("https://abc1234567.execute-api.eu-west-1.amazonaws.com", "https://example.test", None, "eu-west-1", "explicit-test-profile")

    @unittest.skipUnless(shutil.which("node"), "Node.js required for browser script harness")
    def test_task_link_preserves_configured_cloud_and_lan_origin(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
async function run(target, backend) {
  const elements = new Map();
  function element(id) { if (!elements.has(id)) elements.set(id, {dataset:{},classList:{toggle(){}},addEventListener(){}}); return elements.get(id); }
  const task = {task_id:'task-test-demo',status:'OPEN',display_name:'Test',district_id:'ntpc-test',action_label:'observe',route_label:'route',eta_band:'none',updated_at:'now'};
  const context = {URL,URLSearchParams,window:{location:{search:'?task_id=task-test-demo',pathname:'/public_shell/task.html',hash:'',origin:'http://127.0.0.1:8084'}},document:{getElementById:element,querySelector:element},fetch:async()=>({ok:true,json:async()=>({ok:true,task,task_backend:backend,completion_url:target})})};
  vm.runInNewContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  if (element('task-link').href !== target) throw Error('configured origin lost');
}
(async()=>{await run('https://cloud.example.test/stage/tasks/task-test-demo#signature=test','cloud'); await run('http://192.168.1.10:8084/tasks/task-test-demo#signature=test','local');})().catch(()=>process.exit(1));
"""
        result = subprocess.run([shutil.which("node"), "-e", script, str(ROOT / "public_shell/task.js")], capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_sigv4_deterministic_temporary_session_headers(self) -> None:
        credentials = {"AccessKeyId": "TEST_ONLY_ID", "SecretAccessKey": "test-only-not-a-real-secret", "SessionToken": "test-only-session"}
        req = signed_request("https://abc1234567.execute-api.ap-southeast-2.amazonaws.com/stage/tasks", b'{}', credentials, "ap-southeast-2", now=datetime(2026,9,11,tzinfo=timezone.utc))
        self.assertEqual("20260911T000000Z", req.get_header("X-amz-date"))
        self.assertIn("20260911/ap-southeast-2/execute-api/aws4_request", req.get_header("Authorization"))
        self.assertEqual("test-only-session", req.get_header("X-amz-security-token"))
        self.assertNotIn(credentials["SecretAccessKey"], str(req.headers))
        signer = IsolatedTaskSigner(Path(self.temp.name), "ap-southeast-2", "test-profile")
        with patch('aws_task_client.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, "aws_cli_unavailable"):
                signer.credentials()

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
        with self.assertRaises(error.HTTPError) as missing:
            request.urlopen(self.base + "/missing", timeout=2)
        self.assertEqual("no-store", missing.exception.headers["Cache-Control"])
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


class TaskPhoneUiTests(unittest.TestCase):
    def test_gateway_accepts_arrive_and_rejects_implicit_complete(self) -> None:
        payload = {
            "task_id": "task-gateway-demo",
            "task_type": "observe",
            "event_id": "evt-gateway-arrive",
            "device_hash": "a" * 64,
            "signature": "grant." + "b" * 64,
            "occurred_at": "2026-09-11T00:00:00+00:00",
            "event_type": "arrive",
        }
        self.assertEqual(payload, validate_task_event_request(payload))
        del payload["event_type"]
        with self.assertRaisesRegex(ValueError, "task_event_request_json_schema_invalid"):
            validate_task_event_request(payload)

    def test_cloud_task_gateway_requires_arrival_projection(self) -> None:
        task = {
            "task_id": "task-cloud-demo",
            "case_id": "case-cloud-demo",
            "display_name": "Cloud demo",
            "district_id": "ntpc-test",
            "action_label": "observe",
            "priority_band": "low",
            "route_label": "route",
            "eta_band": "none",
            "status": "OPEN",
            "accepted": True,
            "accepted_at": "2026-09-11T00:00:00+00:00",
            "arrived": True,
            "arrived_at": "2026-09-11T00:01:00+00:00",
            "updated_at": "2026-09-11T00:01:00+00:00",
            "task_type": "observe",
        }
        self.assertEqual(task, CloudTaskStore.safe_task(task))
        del task["arrived_at"]
        with self.assertRaisesRegex(CloudUnavailable, "cloud_task_contract_invalid"):
            CloudTaskStore.safe_task(task)

    def test_cloud_cli_ignores_generic_region_and_requires_named_profile(self) -> None:
        argv = ["gateway", "--task-backend", "cloud", "--public-task-base-url", "https://example.test/stage"]
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {"AWS_REGION": "ap-northeast-1"}, clear=True):
            args = parse_args()
        self.assertEqual("us-west-2", args.aws_region)
        self.assertIsNone(args.aws_profile)
        with patch.object(sys, "argv", argv + ["--aws-profile", "explicit-test-profile", "--aws-region", "us-west-2"]), patch.dict(os.environ, {}, clear=True):
            args = parse_args()
        self.assertEqual("explicit-test-profile", args.aws_profile)
        self.assertEqual("us-west-2", args.aws_region)
        with self.assertRaisesRegex(ValueError, "cloud_resource_region_must_be_us_west_2"):
            CloudTaskStore("https://abc1234567.execute-api.eu-west-1.amazonaws.com", "https://example.test", None, "eu-west-1", "explicit-test-profile")

    def test_global_profile_export_is_explicit_and_does_not_inject_session_paths(self) -> None:
        expiration = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({
                "AccessKeyId": "TEST_ONLY_ID",
                "SecretAccessKey": "test-only-not-a-real-secret",
                "SessionToken": "test-only-session",
                "Expiration": expiration,
            }),
            stderr="",
        )
        signer = IsolatedTaskSigner(None, "us-west-2", "explicit-test-profile")
        with patch("aws_task_client.shutil.which", return_value="/mock/aws"), patch("aws_task_client.subprocess.run", return_value=completed) as run:
            credentials = signer.credentials()
        self.assertEqual("TEST_ONLY_ID", credentials["AccessKeyId"])
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertEqual(["/mock/aws", "configure", "export-credentials", "--profile", "explicit-test-profile", "--format", "process"], command)
        self.assertNotIn("AWS_CONFIG_FILE", environment)
        self.assertNotIn("AWS_SHARED_CREDENTIALS_FILE", environment)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for browser script harness")
    def test_phone_buttons_enforce_accept_arrive_complete(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {disabled:true, hidden:false, dataset:{}, classList:{toggle(){}}, addEventListener(type, callback){this.listener=callback;}});
  return elements.get(id);
}
const buttons = {
  '[data-event="accept"]': element('accept'),
  '[data-event="arrive"]': element('arrive'),
  '[data-event="complete"]': element('complete'),
  '[data-event="exception"]': element('exception')
};
let task = {task_id:'task-phone-demo',case_id:'case-phone-demo',display_name:'Phone demo',district_id:'ntpc-test',action_label:'observe',priority_band:'low',route_label:'route',eta_band:'none',status:'OPEN',accepted:false,accepted_at:null,arrived:false,arrived_at:null,updated_at:'2026-09-11T00:00:00+00:00',task_type:'observe'};
const sent = [];
let randomByte = 1;
const cryptoObject = {getRandomValues(array){array.fill(randomByte++); return array;}};
const context = {
  URL, URLSearchParams, setImmediate,
  crypto: cryptoObject,
  window: {
    crypto: cryptoObject,
    confirm(){return true;},
    location:{search:'',pathname:'/tasks/task-phone-demo',hash:'#task_type=observe&device_hash=' + 'a'.repeat(64) + '&signature=grant.' + 'b'.repeat(64) + '&expires_at=4102444800'}
  },
  document: {
    querySelector(selector){return buttons[selector];},
    getElementById(id){return element(id);}
  },
  fetch: async (url, options={}) => {
    if (!url.endsWith('/events')) return {ok:true,json:async()=>({ok:true,task,task_backend:'local'})};
    const event = JSON.parse(options.body);
    sent.push(event.event_type);
    if (event.event_type === 'accept') task = {...task,accepted:true,accepted_at:'2026-09-11T00:01:00+00:00'};
    if (event.event_type === 'arrive') task = {...task,arrived:true,arrived_at:'2026-09-11T00:02:00+00:00'};
    if (event.event_type === 'complete') task = {...task,status:'COMPLETED'};
    return {ok:true,json:async()=>({ok:true,task,duplicate:false,audit_only:false})};
  }
};
vm.runInNewContext(source, context);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  if (buttons['[data-event="accept"]'].disabled || !buttons['[data-event="arrive"]'].disabled || !buttons['[data-event="complete"]'].disabled) throw Error('initial button state invalid');
  await buttons['[data-event="accept"]'].listener();
  if (!buttons['[data-event="accept"]'].disabled || buttons['[data-event="arrive"]'].disabled || !buttons['[data-event="complete"]'].disabled) throw Error('accepted button state invalid');
  await buttons['[data-event="arrive"]'].listener();
  if (!buttons['[data-event="arrive"]'].disabled || buttons['[data-event="complete"]'].disabled) throw Error('arrived button state invalid');
  await buttons['[data-event="complete"]'].listener();
  if (!buttons['[data-event="complete"]'].disabled || task.status !== 'COMPLETED') throw Error('completed button state invalid');
  if (sent.join(',') !== 'accept,arrive,complete') throw Error('event order invalid');
})().catch(error=>{console.error(error.message);process.exit(1);});
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script, str(ROOT / "public_shell/task.js")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
