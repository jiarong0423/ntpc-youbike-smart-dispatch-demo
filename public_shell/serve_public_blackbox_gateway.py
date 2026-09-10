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

from task_ledger import TaskStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLACKBOX_URL = "http://127.0.0.1:8781/api/v1/dispatch/evaluate"
MAX_BODY_BYTES = 16 * 1024
SEALED_RESULT_SCHEMA = json.loads((PROJECT_ROOT / "contracts" / "sealed_result.schema.json").read_text(encoding="utf-8"))
SEALED_RESULT_VALIDATOR = Draft202012Validator(SEALED_RESULT_SCHEMA, format_checker=FormatChecker())
STATIC_PATHS = {
    "/public_shell/index.html",
    "/public_shell/app.js",
    "/public_shell/styles.css",
    "/public_shell/task.html",
    "/public_shell/task.js",
    "/public_shell/task.css",
    "/public_shell/media/snapshot.svg",
    "/public_shell/media/weather-bike.svg",
    "/public_shell/media/weather-temperature.svg",
    "/fixtures/sealed.json",
}


def canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


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
    return {
        "schema_version": "youbike.blackbox_request.v1",
        "request_id": f"req-{secrets.token_hex(12)}",
        "requested_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds"),
        "nonce": secrets.token_urlsafe(32),
        "view": "district_dispatch_summary",
        "limit": 20,
    }


def validate_sealed_result(result: Any) -> dict[str, Any]:
    schema_errors = sorted(SEALED_RESULT_VALIDATOR.iter_errors(result), key=lambda item: list(item.path))
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
        "edge_status",
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
    if (
        not isinstance(wrapped, dict)
        or wrapped.get("schema_version")
        != "youbike.blackbox_response.v1"
        or wrapped.get("request_id") != body["request_id"]
    ):
        raise ValueError("blackbox_response_schema_invalid")
    result = validate_sealed_result(wrapped.get("result"))
    expected_hash = hashlib.sha256(
        canonical_json(result)
    ).hexdigest()
    if wrapped.get("result_sha256") != expected_hash:
        raise ValueError("blackbox_result_hash_mismatch")
    return result


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

    def do_GET(self) -> None:
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
                    "service": "public_task_ledger",
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
            target = (
                f"{self.server.public_base_url}"  # type: ignore[attr-defined]
                "/public_shell/task.html"
                f"?task_id={parse.quote(parts[3])}"
            )
            image = qrcode.make(
                target,
                image_factory=qrcode.image.svg.SvgPathImage,
                box_size=8,
                border=3,
            )
            buffer = io.BytesIO()
            image.save(buffer)
            return self.send_svg(buffer.getvalue())

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

        if (
            not parsed_path.query
            and path in STATIC_PATHS
        ):
            return super().do_GET()
        return self.send_error(
            HTTPStatus.NOT_FOUND
        )

    def do_POST(self) -> None:
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
            return self.send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "invalid_content_length",
                },
            )
        if (
            length <= 0
            or length > MAX_BODY_BYTES
        ):
            return self.send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {
                    "ok": False,
                    "error": "body_size_invalid",
                },
            )
        try:
            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return self.send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "invalid_json",
                },
            )
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
        required=True,
    )
    parser.add_argument(
        "--public-base-url",
        required=True,
    )
    parser.add_argument(
        "--offline-fixture",
        type=Path,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = args.directory.resolve(
        strict=True
    )
    if not directory.is_dir():
        raise RuntimeError(
            "serve_directory_not_found"
        )
    parsed_base = parse.urlparse(
        args.public_base_url
    )
    if (
        parsed_base.scheme != "http"
        or not parsed_base.hostname
        or parsed_base.path not in {"", "/"}
    ):
        raise ValueError(
            "public_base_url_must_be_http_origin"
        )
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
    task_store = TaskStore(
        args.task_db,
        PROJECT_ROOT,
    )
    if fixture:
        task_store.seed_result(
            validate_sealed_result(
                json.loads(
                    fixture.read_text(
                        encoding="utf-8"
                    )
                )
            )
        )
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
