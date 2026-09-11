#!/usr/bin/env python3
"""Serve the public UI, proxy sealed results, and persist public task events."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any
from urllib import error, parse, request

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from task_ledger import TaskStore
from aws_task_client import IsolatedTaskSigner, NoSignedRedirect, validate_api_endpoint

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLACKBOX_URL = "http://127.0.0.1:8781/api/v1/dispatch/evaluate"
MAX_BODY_BYTES = 16 * 1024
MAX_LIVE_RESULT_AGE_SECONDS = 30 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
CONTRACT_DIR = PROJECT_ROOT / "contracts"
SEALED_RESULT_SCHEMA = json.loads(
    (CONTRACT_DIR / "sealed_result.schema.json").read_text(encoding="utf-8")
)
BLACKBOX_REQUEST_SCHEMA = json.loads(
    (CONTRACT_DIR / "blackbox_request.schema.json").read_text(encoding="utf-8")
)
BLACKBOX_RESPONSE_SCHEMA = json.loads(
    (CONTRACT_DIR / "blackbox_response.schema.json").read_text(encoding="utf-8")
)
TASK_EVENT_REQUEST_SCHEMA = json.loads(
    (CONTRACT_DIR / "task_event_request.schema.json").read_text(encoding="utf-8")
)
FORMAT_CHECKER = FormatChecker()
CONTRACT_REGISTRY = Registry().with_resource(
    SEALED_RESULT_SCHEMA["$id"], Resource.from_contents(SEALED_RESULT_SCHEMA)
)
SEALED_RESULT_VALIDATOR = Draft202012Validator(
    SEALED_RESULT_SCHEMA, format_checker=FORMAT_CHECKER
)
BLACKBOX_REQUEST_VALIDATOR = Draft202012Validator(
    BLACKBOX_REQUEST_SCHEMA, format_checker=FORMAT_CHECKER
)
BLACKBOX_RESPONSE_VALIDATOR = Draft202012Validator(
    BLACKBOX_RESPONSE_SCHEMA,
    registry=CONTRACT_REGISTRY,
    format_checker=FORMAT_CHECKER,
)
TASK_EVENT_REQUEST_VALIDATOR = Draft202012Validator(
    TASK_EVENT_REQUEST_SCHEMA,
    format_checker=FORMAT_CHECKER,
)
STATIC_PATHS = {
    "/public_shell/index.html",
    "/public_shell/app.js",
    "/public_shell/styles.css",
    "/public_shell/task.html",
    "/public_shell/task.js",
    "/public_shell/task.css",
    "/public_shell/media/historical-coverage.svg",
    "/public_shell/media/snapshot.svg",
    "/public_shell/media/weather-bike.svg",
    "/public_shell/media/weather-temperature.svg",
    "/public_shell/media/operational-scenarios.svg",
    "/fixtures/sealed.json",
}


def canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def validate_task_event_request(payload: Any) -> dict[str, Any]:
    errors = sorted(
        TASK_EVENT_REQUEST_VALIDATOR.iter_errors(payload),
        key=lambda item: list(item.path),
    )
    if errors or not isinstance(payload, dict):
        raise ValueError("task_event_request_json_schema_invalid")
    return payload


def validate_blackbox_url(value: str) -> str:
    parsed = parse.urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    if (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        return value
    raise ValueError("blackbox_url_requires_https_or_loopback_http")


def read_credential(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=True)
    project_root = PROJECT_ROOT.resolve(strict=True)
    if resolved == project_root or project_root in resolved.parents:
        raise ValueError("credential_file_must_be_outside_project")
    if os.name != "nt":
        mode = stat.S_IMODE(resolved.stat().st_mode)
        if mode & 0o077:
            raise PermissionError(
                "credential_file_permissions_must_be_0600"
            )
    token = resolved.read_text(encoding="utf-8").strip()
    if not token.startswith("ybx_v1_") or len(token) < 50:
        raise ValueError("credential_format_invalid")
    return token


def build_request() -> dict[str, Any]:
    body = {
        "schema_version": "youbike.blackbox_request.v1",
        "request_id": f"req-{secrets.token_hex(12)}",
        "requested_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds"),
        "nonce": secrets.token_urlsafe(32),
        "view": "district_dispatch_summary",
        "limit": 20,
    }
    errors = sorted(
        BLACKBOX_REQUEST_VALIDATOR.iter_errors(body),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ValueError("blackbox_request_json_schema_invalid")
    return body


def validate_recent_timestamp(
    value: Any,
    field_name: str,
    *,
    now: datetime | None = None,
) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}_missing")
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(f"{field_name}_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name}_timezone_missing")
    current = now or datetime.now(timezone.utc)
    age_seconds = (
        current.astimezone(timezone.utc)
        - parsed.astimezone(timezone.utc)
    ).total_seconds()
    if age_seconds < -MAX_FUTURE_SKEW_SECONDS:
        raise ValueError(f"{field_name}_future")
    if age_seconds > MAX_LIVE_RESULT_AGE_SECONDS:
        raise ValueError(f"{field_name}_stale")
    return parsed


def validate_future_timestamp(
    value: Any,
    field_name: str,
    *,
    now: datetime | None = None,
) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name}_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name}_timezone_missing")
    current = now or datetime.now(timezone.utc)
    if parsed.astimezone(timezone.utc) <= current.astimezone(timezone.utc):
        raise ValueError(f"{field_name}_expired")
    return parsed


def validate_sealed_result(result: Any) -> dict[str, Any]:
    schema_errors = sorted(
        SEALED_RESULT_VALIDATOR.iter_errors(result),
        key=lambda item: list(item.path),
    )
    if schema_errors:
        raise ValueError("sealed_result_json_schema_invalid")
    if not isinstance(result, dict):
        raise ValueError("blackbox_result_missing")
    required = {
        "schema_version",
        "package_id",
        "generated_at",
        "runtime_mode",
        "demo_scope",
        "proof_boundary",
        "summary",
        "districts",
        "selected_cases",
        "comparison_keys",
    }
    modes = {
        "LIVE_LOCAL_SANDBOX",
        "PORTABLE_SEALED_FALLBACK",
        "SEALED_DEMO_FIXTURE",
    }
    if (
        set(result) != required
        or result.get("schema_version")
        != "youbike.sealed_result.v1"
        or result.get("runtime_mode") not in modes
        or not isinstance(result.get("districts"), list)
        or not isinstance(result.get("selected_cases"), list)
    ):
        raise ValueError("sealed_result_schema_invalid")
    if result["runtime_mode"] == "LIVE_LOCAL_SANDBOX":
        validate_recent_timestamp(
            result["generated_at"],
            "live_result_generated_at",
        )
    for item in result["selected_cases"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("route_handoff"), dict)
            or not re.fullmatch(
                r"case-[a-z0-9-]{4,60}",
                str(item.get("case_id", "")),
            )
        ):
            raise ValueError("sealed_result_case_invalid")
    return result


def validate_blackbox_response(
    wrapped: Any,
    expected_request_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    schema_errors = sorted(
        BLACKBOX_RESPONSE_VALIDATOR.iter_errors(wrapped),
        key=lambda item: list(item.path),
    )
    if schema_errors:
        raise ValueError("blackbox_response_json_schema_invalid")
    if not isinstance(wrapped, dict):
        raise ValueError("blackbox_response_schema_invalid")
    if wrapped.get("request_id") != expected_request_id:
        raise ValueError("blackbox_response_request_id_mismatch")
    validate_recent_timestamp(
        wrapped["generated_at"], "blackbox_response_generated_at", now=now
    )
    validate_future_timestamp(
        wrapped["credential_expires_at"], "credential_expires_at", now=now
    )
    result = validate_sealed_result(wrapped["result"])
    source_snapshot_at = wrapped["source_snapshot_at"]
    if result["runtime_mode"] == "LIVE_LOCAL_SANDBOX":
        validate_recent_timestamp(source_snapshot_at, "source_snapshot_at", now=now)
    else:
        try:
            parsed_source = datetime.fromisoformat(
                source_snapshot_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("source_snapshot_at_invalid") from exc
        if parsed_source.tzinfo is None:
            raise ValueError("source_snapshot_at_timezone_missing")
    expected_hash = hashlib.sha256(canonical_json(result)).hexdigest()
    if wrapped["result_sha256"] != expected_hash:
        raise ValueError("blackbox_result_hash_mismatch")
    return result


def fetch_blackbox_result(
    url: str,
    credential_file: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    token = read_credential(credential_file)
    body = build_request()
    outbound = request.Request(
        validate_blackbox_url(url),
        data=canonical_json(body),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(
        outbound,
        timeout=timeout_seconds,
    ) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError(
                f"blackbox_http_status:{response.status}"
            )
        wrapped = json.loads(
            response.read(1024 * 1024).decode("utf-8")
        )
    return validate_blackbox_response(wrapped, body["request_id"])


def probe_blackbox_health(
    url: str,
    credential_file: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    read_credential(credential_file)
    parsed = parse.urlparse(validate_blackbox_url(url))
    if (
        parsed.path != "/api/v1/dispatch/evaluate"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("blackbox_evaluate_path_invalid")
    health_url = parse.urlunparse(
        parsed._replace(path="/api/health")
    )
    outbound = request.Request(
        health_url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with request.urlopen(
        outbound,
        timeout=timeout_seconds,
    ) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError(
                f"blackbox_health_status:{response.status}"
            )
        payload = json.loads(
            response.read(64 * 1024).decode("utf-8")
        )
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ok"
    ):
        raise ValueError("blackbox_health_payload_invalid")
    return {
        "status": "ok",
        "service": "public_blackbox_gateway",
        "blackbox": "ok",
    }


class CloudUnavailable(RuntimeError):
    pass


YOUBIKE_RESOURCE_REGION = "us-west-2"


class CloudTaskStore:
    """Exclusive HTTPS task authority; never creates a local database."""
    def __init__(self, api_url: str, public_base_url: str, session_dir: Path | None, region: str, profile: str) -> None:
        if region != YOUBIKE_RESOURCE_REGION:
            raise ValueError("cloud_resource_region_must_be_us_west_2")
        self.signer = IsolatedTaskSigner(session_dir, region, profile)
        self.api_url = validate_api_endpoint(api_url, region)
        self.public_base_url = validate_task_base(public_base_url, cloud=True)

    def call(self, suffix: str, payload: Any = None) -> tuple[int, dict[str, Any]]:
        try:
            outbound = self.signer.request(self.api_url + suffix,
                None if payload is None else canonical_json(payload))
        except RuntimeError:
            raise CloudUnavailable("isolated_aws_session_unavailable") from None
        try:
            response = request.build_opener(NoSignedRedirect()).open(outbound, timeout=5)
        except error.HTTPError as exc:
            if exc.code in {400, 403, 404, 409, 413}:
                return exc.code, {"ok": False, "error": "cloud_request_rejected"}
            raise CloudUnavailable("cloud_task_service_unavailable") from None
        except (OSError, error.URLError):
            raise CloudUnavailable("cloud_task_service_unavailable") from None
        with response:
            encoded = response.read(1024 * 1024 + 1)
            if len(encoded) > 1024 * 1024:
                raise CloudUnavailable("cloud_response_invalid")
            try:
                body = json.loads(encoded)
            except (ValueError, UnicodeDecodeError):
                raise CloudUnavailable("cloud_response_invalid") from None
            if not isinstance(body, dict):
                raise CloudUnavailable("cloud_response_invalid")
            return response.status, body

    @staticmethod
    def safe_task(task: Any) -> dict[str, Any]:
        schema = json.loads((CONTRACT_DIR / "task_response.schema.json").read_text(encoding="utf-8"))
        if not isinstance(task, dict):
            raise CloudUnavailable("cloud_task_contract_invalid")
        safe = {key: task[key] for key in schema["properties"] if key in task}
        if list(Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(safe)):
            raise CloudUnavailable("cloud_task_contract_invalid")
        return safe

    def list_tasks(self) -> list[dict[str, Any]]:
        code, body = self.call("/api/handoff/tasks")
        if code != 200 or not isinstance(body.get("tasks"), list):
            raise CloudUnavailable("cloud_task_service_unavailable")
        return [self.safe_task(task) for task in body["tasks"]]

    def detail(self, task_id: str) -> dict[str, Any] | None:
        code, body = self.call("/api/handoff/tasks/" + parse.quote(task_id, safe=""))
        if code == 404:
            return None
        if code != 200 or body.get("ok") is not True:
            raise CloudUnavailable("cloud_task_service_unavailable")
        body["task"] = self.safe_task(body.get("task"))
        return body

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        body = self.detail(task_id)
        return body["task"] if body else None

    def completion_link(self, task_id: str) -> str:
        code, body = self.call("/tasks/" + parse.quote(task_id, safe="") + "/grant", {})
        grant = body.get("grant")
        if code != 200 or not isinstance(grant, dict) or grant.get("task_id") != task_id:
            raise CloudUnavailable("cloud_signed_grant_required")
        allowed = {"task_id", "task_type", "issued_at", "expires_at", "device_salt", "device_hash", "signature"}
        if set(grant) != allowed:
            raise CloudUnavailable("cloud_grant_contract_invalid")
        return self.public_base_url + "/tasks/" + parse.quote(task_id, safe="") + "#" + parse.urlencode(grant)

    def seed_result(self, result: dict[str, Any]) -> int:
        count = 0
        for case in result["selected_cases"]:
            handoff = case["route_handoff"]
            if handoff.get("present") is not True:
                continue
            task = {key: case[key] for key in ("case_id", "display_name", "district_id", "action_label", "priority_band")}
            task.update({"task_id": "task-" + case["case_id"][5:], "route_label": handoff["label"], "eta_band": handoff["eta_band"]})
            code, body = self.call("/tasks", task)
            if code not in {200, 201, 409}:
                raise CloudUnavailable("cloud_task_seed_failed")
            count += 1
        return count

    def apply_event(self, task_id: str, payload: Any) -> tuple[int, dict[str, Any]]:
        code, body = self.call("/api/handoff/tasks/" + parse.quote(task_id, safe="") + "/events", payload)
        if code == 200 and body.get("ok") is True:
            return code, {"ok": True, "task": self.safe_task(body.get("task")),
                          "duplicate": body.get("duplicate") is True, "audit_only": body.get("audit_only") is True}
        return code, {"ok": False, "error": "cloud_request_rejected"}

    def reject(self, task_id: str, event_id: Any, reason: str, status: int = 400):
        code, body = self.call("/api/handoff/tasks/" + parse.quote(task_id, safe="") + "/events", {})
        return status, {"ok": False, "error": reason}


def validate_task_base(value: str, *, cloud: bool) -> str:
    parsed = parse.urlparse(value)
    if (parsed.scheme not in ({"https"} if cloud else {"http", "https"})
            or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or (not cloud and parsed.path not in {"", "/"})):
        raise ValueError("task_base_url_invalid")
    return value.rstrip("/")


class GatewayHandler(SimpleHTTPRequestHandler):
    server_version = "YouBikePublicGateway/2.0"

    def __init__(
        self,
        *args: Any,
        directory: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            *args,
            directory=directory or str(PROJECT_ROOT),
            **kwargs,
        )

    @property
    def task_store(self) -> TaskStore:
        return self.server.task_store  # type: ignore[attr-defined]

    def log_message(
        self,
        format: str,
        *args: Any,
    ) -> None:
        path = parse.urlparse(self.path).path
        status = args[1] if len(args) > 1 else "-"
        print(
            f"public_gateway method={self.command} "
            f"path={path} status={status}"
        )

    def send_json(
        self,
        status: int,
        payload: dict[str, Any],
    ) -> None:
        body = canonical_json(payload)
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def send_svg(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Type",
            "image/svg+xml; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def load_result(self) -> dict[str, Any]:
        fixture = self.server.offline_fixture  # type: ignore[attr-defined]
        if fixture:
            return validate_sealed_result(
                json.loads(
                    Path(fixture).read_text(encoding="utf-8")
                )
            )
        credential_value = os.environ.get(
            "YOUBIKE_BLACKBOX_CREDENTIAL_FILE",
            "",
        )
        if not credential_value:
            raise ValueError("blackbox_not_configured")
        return fetch_blackbox_result(
            os.environ.get(
                "YOUBIKE_BLACKBOX_URL",
                DEFAULT_BLACKBOX_URL,
            ),
            Path(credential_value),
            float(
                os.environ.get(
                    "YOUBIKE_BLACKBOX_TIMEOUT_SECONDS",
                    "5",
                )
            ),
        )

    def end_headers(self) -> None:
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def completion_link(self, task_id: str) -> str:
        if self.server.task_backend == "cloud":
            return self.task_store.completion_link(task_id)
        grant = self.task_store.issue_signature(task_id)
        return (self.server.public_base_url + "/tasks/" + parse.quote(task_id) + "#" + parse.urlencode(grant))

    def do_GET(self) -> None:
        try:
            return self.handle_GET()
        except CloudUnavailable:
            return self.send_json(503, {"ok": False, "error": "cloud_task_service_unavailable", "task_backend": "cloud", "fallback": False})

    def handle_GET(self) -> None:
        parsed_path = parse.urlparse(self.path)
        path = parsed_path.path
        parts = [
            part
            for part in path.split("/")
            if part
        ]
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Location", "/public_shell/index.html")
            self.end_headers()
            return None

        if path == "/api/integration/status" and not parsed_path.query:
            try:
                result = self.load_result()
            except (OSError, ValueError, RuntimeError, error.URLError):
                return self.send_json(503, {"health": "degraded", "source_mode": "unavailable", "new_decisions": False,
                                           "task_backend": self.server.task_backend})
            return self.send_json(200, {"health": "ok", "generated_at": result["generated_at"],
                "source_mode": result["runtime_mode"], "task_backend": self.server.task_backend,
                "districts": [{"district": row["district_id"], "priority_level": row["priority_band"],
                               "suggested_action": row["action_label"]} for row in result["districts"]]})

        if path == "/api/health" and not parsed_path.query:
            if self.server.offline_fixture:  # type: ignore[attr-defined]
                return self.send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "public_blackbox_gateway",
                        "mode": "offline_explicit",
                    },
                )
            credential_value = os.environ.get(
                "YOUBIKE_BLACKBOX_CREDENTIAL_FILE",
                "",
            )
            if not credential_value:
                return self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "status": "down",
                        "error": "blackbox_not_configured",
                    },
                )
            try:
                payload = probe_blackbox_health(
                    os.environ.get(
                        "YOUBIKE_BLACKBOX_URL",
                        DEFAULT_BLACKBOX_URL,
                    ),
                    Path(credential_value),
                    float(
                        os.environ.get(
                            "YOUBIKE_BLACKBOX_TIMEOUT_SECONDS",
                            "5",
                        )
                    ),
                )
            except (
                OSError,
                ValueError,
                RuntimeError,
                error.URLError,
                json.JSONDecodeError,
            ):
                return self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "status": "down",
                        "error": "blackbox_unavailable",
                    },
                )
            return self.send_json(
                HTTPStatus.OK,
                payload,
            )

        if (
            path == "/api/blackbox/result"
            and not parsed_path.query
        ):
            try:
                result = self.load_result()
                self.task_store.seed_result(result)
            except CloudUnavailable:
                raise
            except (
                OSError,
                ValueError,
                RuntimeError,
                error.URLError,
                json.JSONDecodeError,
            ):
                return self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "blackbox_unavailable"},
                )
            return self.send_json(
                HTTPStatus.OK,
                result,
            )

        if (
            path == "/api/handoff/health"
            and not parsed_path.query
        ):
            return self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "task_ledger",
                    "task_backend": self.server.task_backend,
                    "task_count": len(
                        self.task_store.list_tasks()
                    ),
                },
            )

        if (
            path == "/api/handoff/tasks"
            and not parsed_path.query
        ):
            return self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "tasks": self.task_store.list_tasks(),
                },
            )

        if (
            len(parts) == 4
            and parts[:3]
            == ["api", "handoff", "tasks"]
            and not parsed_path.query
        ):
            task = self.task_store.get_task(parts[3])
            if not task:
                return self.send_json(
                    HTTPStatus.NOT_FOUND,
                    {
                        "ok": False,
                        "error": "task_not_found",
                    },
                )
            return self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "task": task,
                    "task_backend": self.server.task_backend,
                    "completion_url": self.completion_link(parts[3]) if task["status"] == "OPEN" else None,
                },
            )

        if (
            len(parts) == 5
            and parts[:3]
            == ["api", "handoff", "tasks"]
            and parts[4] == "qr.svg"
            and not parsed_path.query
        ):
            task = self.task_store.get_task(parts[3])
            if not task:
                return self.send_json(
                    HTTPStatus.NOT_FOUND,
                    {
                        "ok": False,
                        "error": "task_not_found",
                    },
                )
            try:
                import qrcode
                import qrcode.image.svg
            except ImportError:
                return self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "ok": False,
                        "error": "qrcode_dependency_missing",
                    },
                )
            if task["status"] != "OPEN":
                return self.send_json(HTTPStatus.CONFLICT, {"ok": False, "error": "task_not_open"})
            target = self.completion_link(parts[3])
            image = qrcode.make(
                target,
                image_factory=qrcode.image.svg.SvgPathImage,
                box_size=8,
                border=3,
            )
            buffer = io.BytesIO()
            image.save(buffer)
            return self.send_svg(buffer.getvalue())

        if len(parts) == 2 and parts[0] == "tasks" and re.fullmatch(r"task-[a-z0-9][a-z0-9-]{3,64}", parts[1]) and not parsed_path.query:
            self.path = "/public_shell/task.html"
            return super().do_GET()

        if path == "/public_shell/task.html":
            query = parse.parse_qs(
                parsed_path.query,
                keep_blank_values=True,
            )
            task_ids = query.get("task_id", [])
            if (
                set(query) == {"task_id"}
                and len(task_ids) == 1
                and re.fullmatch(
                    r"task-[a-z0-9][a-z0-9-]{3,64}",
                    task_ids[0],
                )
            ):
                return super().do_GET()
            return self.send_error(
                HTTPStatus.NOT_FOUND
            )

        if path == "/public_shell/index.html":
            query = parse.parse_qs(
                parsed_path.query,
                keep_blank_values=True,
            )
            if (
                not parsed_path.query
                or query == {"mode": ["offline"]}
            ):
                return super().do_GET()
        if (
            not parsed_path.query
            and path in STATIC_PATHS
        ):
            return super().do_GET()
        return self.send_error(
            HTTPStatus.NOT_FOUND
        )

    def do_POST(self) -> None:
        try:
            return self.handle_POST()
        except CloudUnavailable:
            return self.send_json(503, {"ok": False, "error": "cloud_task_service_unavailable", "task_backend": "cloud", "fallback": False})

    def handle_POST(self) -> None:
        parsed_path = parse.urlparse(self.path)
        parts = [
            part
            for part in parsed_path.path.split("/")
            if part
        ]
        if (
            len(parts) != 5
            or parts[:3]
            != ["api", "handoff", "tasks"]
            or parts[4] != "events"
            or parsed_path.query
        ):
            return self.send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )
        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )
        except ValueError:
            status, body = self.task_store.reject(parts[3], None, "invalid_content_length")
            return self.send_json(status, body)
        if (
            length <= 0
            or length > MAX_BODY_BYTES
        ):
            status, body = self.task_store.reject(parts[3], None, "body_size_invalid", 413)
            return self.send_json(status, body)
        try:
            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            status, body = self.task_store.reject(parts[3], None, "invalid_json")
            return self.send_json(status, body)
        try:
            validate_task_event_request(payload)
        except ValueError:
            event_id = payload.get("event_id") if isinstance(payload, dict) else None
            status, body = self.task_store.reject(parts[3], event_id, "event_schema_invalid")
            return self.send_json(status, body)
        status, response = self.task_store.apply_event(
            parts[3],
            payload,
        )
        return self.send_json(
            status,
            response,
        )

    def do_HEAD(self) -> None:
        parsed_path = parse.urlparse(self.path)
        if parsed_path.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Location", "/public_shell/index.html")
            self.end_headers()
            return None
        if parsed_path.path == "/public_shell/index.html":
            query = parse.parse_qs(
                parsed_path.query,
                keep_blank_values=True,
            )
            if (
                not parsed_path.query
                or query == {"mode": ["offline"]}
            ):
                return super().do_HEAD()
        if (
            not parsed_path.query
            and parsed_path.path in STATIC_PATHS
        ):
            return super().do_HEAD()
        return self.send_error(
            HTTPStatus.NOT_FOUND
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8084,
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=PROJECT_ROOT,
    )
    parser.add_argument(
        "--task-db",
        type=Path,
    )
    parser.add_argument(
        "--public-task-base-url", "--public-base-url",
        dest="public_base_url",
        default=os.environ.get("PUBLIC_TASK_BASE_URL"),
    )
    parser.add_argument("--task-backend", choices=("local", "cloud"), default=os.environ.get("TASK_BACKEND", "local"))
    parser.add_argument("--task-cloud-url", default=os.environ.get("TASK_CLOUD_API_URL"))
    parser.add_argument("--aws-session-dir", type=Path)
    parser.add_argument("--aws-profile", default=os.environ.get("YOUBIKE_AWS_PROFILE"))
    parser.add_argument("--aws-region", default=os.environ.get("YOUBIKE_AWS_REGION", YOUBIKE_RESOURCE_REGION))
    parser.add_argument(
        "--offline-fixture",
        type=Path,
    )
    args = parser.parse_args()
    if args.task_backend == "cloud" and not args.task_cloud_url:
        args.task_cloud_url = args.public_base_url
    return args


def main() -> int:
    args = parse_args()
    directory = args.directory.resolve(
        strict=True
    )
    if not directory.is_dir():
        raise RuntimeError(
            "serve_directory_not_found"
        )
    if not args.public_base_url:
        raise ValueError("public_task_base_url_required")
    public_base = validate_task_base(args.public_base_url, cloud=args.task_backend == "cloud")
    if args.task_backend == "local" and not args.task_db:
        raise ValueError("local_task_database_required")
    if args.task_backend == "cloud" and (not args.task_cloud_url or not args.aws_profile):
        raise ValueError("cloud_task_url_and_explicit_profile_required")
    if args.task_backend == "cloud" and args.aws_region != YOUBIKE_RESOURCE_REGION:
        raise ValueError("cloud_resource_region_must_be_us_west_2")
    fixture = (
        args.offline_fixture.resolve(strict=True)
        if args.offline_fixture
        else None
    )
    if fixture:
        validate_sealed_result(
            json.loads(
                fixture.read_text(encoding="utf-8")
            )
        )
    if args.task_backend == "cloud":
        task_store = CloudTaskStore(
            args.task_cloud_url,
            public_base,
            args.aws_session_dir,
            args.aws_region,
            args.aws_profile,
        )
    else:
        task_store = TaskStore(args.task_db, PROJECT_ROOT)
        if fixture:
            task_store.seed_result(validate_sealed_result(json.loads(fixture.read_text(encoding="utf-8"))))
    handler = (
        lambda *handler_args, **handler_kwargs:
        GatewayHandler(
            *handler_args,
            directory=str(directory),
            **handler_kwargs,
        )
    )
    server = ThreadingHTTPServer(
        (args.bind, args.port),
        handler,
    )
    server.task_backend = args.task_backend
    server.task_store = task_store  # type: ignore[attr-defined]
    server.public_base_url = (  # type: ignore[attr-defined]
        args.public_base_url.rstrip("/")
    )
    server.offline_fixture = fixture  # type: ignore[attr-defined]
    mode = (
        "offline_explicit"
        if fixture
        else "live_blackbox"
    )
    print(
        f"public_gateway_ready "
        f"bind={args.bind} "
        f"port={args.port} "
        f"mode={mode}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
