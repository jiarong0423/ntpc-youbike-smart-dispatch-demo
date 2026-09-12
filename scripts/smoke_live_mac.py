#!/usr/bin/env python3
"""Fail-closed smoke checks for the Mac LIVE service chain."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any
from urllib import error, parse, request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEDIATOR_EVALUATE_URL = "http://127.0.0.1:8782/api/v1/dispatch/evaluate"
MEDIATOR_HEALTH_URL = "http://127.0.0.1:8782/api/health"
# LIVE is the sanitized mediator output; LIVE_LOCAL_SANDBOX is the older local-only label.
EXPECTED_RUNTIME_MODES = frozenset({"LIVE", "LIVE_LOCAL_SANDBOX"})
MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_SOURCE_AGE_SECONDS = 30 * 60
MAX_FUTURE_SKEW_SECONDS = 120

DENIED_KEYS = {
    "access_key",
    "address",
    "algorithm_parameters",
    "api_key",
    "coordinates",
    "credential",
    "device_fingerprint",
    "display_rank",
    "feature_matrix",
    "file_path",
    "formula",
    "latitude",
    "longitude",
    "private_score",
    "rank_value",
    "raw_data",
    "raw_rows",
    "secret",
    "source_url",
    "station_id",
    "station_name",
    "threshold",
    "thresholds",
    "token",
    "weight",
    "weights",
}


class LiveSmokeError(RuntimeError):
    """Raised when a required LIVE invariant is not satisfied."""


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-base-url",
        default="http://127.0.0.1:8084",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=0.5,
    )
    parser.add_argument(
        "--max-source-age-seconds",
        type=float,
        default=DEFAULT_SOURCE_AGE_SECONDS,
    )
    parser.add_argument(
        "--mediator-only",
        action="store_true",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("timeout-seconds must be positive")
    if args.wait_seconds < 0:
        parser.error("wait-seconds must not be negative")
    if args.interval_seconds <= 0:
        parser.error("interval-seconds must be positive")
    if args.max_source_age_seconds <= 0:
        parser.error("max-source-age-seconds must be positive")
    return args


def validate_credential_path() -> Path:
    raw_path = os.environ.get("YOUBIKE_BLACKBOX_CREDENTIAL_FILE")
    if not raw_path:
        raise LiveSmokeError("credential_environment_variable_missing")
    try:
        credential = Path(raw_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise LiveSmokeError("credential_file_unavailable") from exc
    if not credential.is_file():
        raise LiveSmokeError("credential_not_regular_file")
    if credential == PROJECT_ROOT or PROJECT_ROOT in credential.parents:
        raise LiveSmokeError("credential_inside_repository")
    try:
        mode = credential.stat().st_mode
    except OSError as exc:
        raise LiveSmokeError("credential_stat_failed") from exc
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise LiveSmokeError("credential_permissions_not_owner_only")
    return credential


def validate_loopback_base_url(value: str) -> str:
    parsed = parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise LiveSmokeError("public_base_url_invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port != 8084
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise LiveSmokeError("public_base_url_must_be_loopback_8084")
    return value.rstrip("/")


def get_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    outbound = request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with request.build_opener(NoRedirect()).open(
            outbound,
            timeout=timeout_seconds,
        ) as response:
            if response.status != 200:
                raise LiveSmokeError(f"unexpected_http_status:{response.status}")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise LiveSmokeError(f"unexpected_content_type:{content_type}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except error.HTTPError as exc:
        raise LiveSmokeError(f"http_error:{exc.code}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise LiveSmokeError(f"request_failed:{type(exc).__name__}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LiveSmokeError("response_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveSmokeError("response_json_invalid") from exc
    if not isinstance(payload, dict):
        raise LiveSmokeError("response_root_must_be_object")
    return payload


def parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise LiveSmokeError(f"{field_name}_missing")
    try:
        parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveSmokeError(f"{field_name}_invalid") from exc
    if parsed_value.tzinfo is None:
        raise LiveSmokeError(f"{field_name}_timezone_missing")
    return parsed_value.astimezone(timezone.utc)


def validate_fresh_timestamp(
    value: Any,
    field_name: str,
    max_age_seconds: float,
) -> datetime:
    parsed_value = parse_timestamp(value, field_name)
    age_seconds = (datetime.now(timezone.utc) - parsed_value).total_seconds()
    if age_seconds < -MAX_FUTURE_SKEW_SECONDS:
        raise LiveSmokeError(f"{field_name}_future")
    if age_seconds > max_age_seconds:
        raise LiveSmokeError(f"{field_name}_stale")
    return parsed_value


def find_values(payload: Any, target_key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == target_key:
                values.append(value)
            values.extend(find_values(value, target_key))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(find_values(value, target_key))
    return values


def find_denied_keys(payload: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            if key.casefold() in DENIED_KEYS:
                findings.append(child_path)
            findings.extend(find_denied_keys(value, child_path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            findings.extend(find_denied_keys(value, f"{path}[{index}]"))
    return findings


def check_mediator(timeout_seconds: float) -> None:
    if MEDIATOR_EVALUATE_URL != "http://127.0.0.1:8782/api/v1/dispatch/evaluate":
        raise LiveSmokeError("mediator_endpoint_invariant_failed")
    payload = get_json(MEDIATOR_HEALTH_URL, timeout_seconds)
    if payload.get("status") != "ok" or payload.get("core") != "ok":
        raise LiveSmokeError("mediator_health_invalid")
    logging.info("check=mediator_health status=pass")


def check_public_chain(
    public_base_url: str,
    timeout_seconds: float,
    max_source_age_seconds: float,
) -> None:
    health = get_json(f"{public_base_url}/api/health", timeout_seconds)
    if (
        health.get("status") != "ok"
        or health.get("service") != "public_blackbox_gateway"
        or health.get("blackbox") != "ok"
        or "mode" in health
    ):
        raise LiveSmokeError("public_health_invalid")
    validate_fresh_timestamp(
        health.get("committed_result_generated_at"),
        "committed_result_generated_at",
        max_source_age_seconds,
    )
    logging.info("check=public_health status=pass")

    result = get_json(f"{public_base_url}/api/blackbox/result", timeout_seconds)
    if result.get("runtime_mode") not in EXPECTED_RUNTIME_MODES:
        raise LiveSmokeError("runtime_mode_not_live")
    generated_at = validate_fresh_timestamp(
        result.get("generated_at"),
        "result_generated_at",
        max_source_age_seconds,
    )
    source_values = find_values(result, "source_snapshot_at")
    if not source_values:
        source_values = find_values(result, "as_of_label")
    if len(source_values) != 1:
        raise LiveSmokeError("source_timestamp_not_unique")
    source_at = validate_fresh_timestamp(
        source_values[0],
        "source_snapshot_at",
        max_source_age_seconds,
    )
    denied = find_denied_keys(result)
    if denied:
        raise LiveSmokeError("sensitive_keys_present:" + ",".join(sorted(denied)))
    logging.info(
        "check=live_result status=pass generated_at=%s source_snapshot_at=%s",
        generated_at.isoformat(),
        source_at.isoformat(),
    )

    task_payload = get_json(f"{public_base_url}/api/handoff/tasks", timeout_seconds)
    tasks = task_payload.get("tasks")
    if task_payload.get("ok") is not True or not isinstance(tasks, list) or not tasks:
        raise LiveSmokeError("task_list_unavailable_or_empty")
    for index, task in enumerate(tasks):
        if (
            not isinstance(task, dict)
            or not isinstance(task.get("task_id"), str)
            or not task["task_id"]
            or task.get("status") not in {"OPEN", "ACCEPTED", "ARRIVED", "COMPLETED", "EXPIRED"}
        ):
            raise LiveSmokeError(f"task_list_item_invalid:{index}")
    logging.info("check=task_list status=pass count=%d", len(tasks))


def run_once(args: argparse.Namespace) -> None:
    validate_credential_path()
    configured_url = os.environ.get("YOUBIKE_BLACKBOX_URL")
    if configured_url and configured_url != MEDIATOR_EVALUATE_URL:
        raise LiveSmokeError("configured_mediator_url_mismatch")
    check_mediator(args.timeout_seconds)
    if args.mediator_only:
        return
    public_base_url = validate_loopback_base_url(args.public_base_url)
    check_public_chain(
        public_base_url,
        args.timeout_seconds,
        args.max_source_age_seconds,
    )


def main() -> int:
    args = parse_args()
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ level=%(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    deadline = time.monotonic() + args.wait_seconds
    last_error: LiveSmokeError | None = None
    while True:
        try:
            run_once(args)
            logging.info("live_smoke status=pass")
            return 0
        except LiveSmokeError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            logging.error("live_smoke status=fail reason=%s", last_error)
            return 1
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
