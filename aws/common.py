"""Strict public contracts and cryptographic helpers for AWS Lambdas."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
from typing import Any, Mapping


COMMIT_SCHEMA = "youbike.aws_dispatch_commit.v1"
RUNTIME_MODE = "LIVE"
TOP_LEVEL_KEYS = {
    "schema",
    "runtime_mode",
    "generation_id",
    "source_snapshot_at",
    "produced_at",
    "manifest_sha256",
    "payload_sha256",
    "districts",
    "tasks",
}
HASHED_TOP_LEVEL_KEYS = TOP_LEVEL_KEYS - {"payload_sha256"}
DISTRICT_KEYS = {
    "district_id",
    "district_name",
    "status_level",
    "suggested_action",
}
TASK_KEYS = {
    "task_id",
    "district_id",
    "station_id",
    "priority_level",
    "suggested_action",
    "created_at",
    "expires_at",
}
EVENT_KEYS = {"event_id", "event_type", "occurred_at"}
STATUS_LEVELS = {"CRITICAL", "WATCH", "STABLE"}
PRIORITY_LEVELS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
DISTRICT_ACTIONS = {"OBSERVE", "REBALANCE", "DISPATCH"}
TASK_ACTIONS = {"MOTORCYCLE_CHECK", "TRUCK_REBALANCE", "OBSERVE"}
EVENT_TARGET = {
    "CLAIM": ("OPEN", "CLAIMED"),
    "ARRIVE": ("CLAIMED", "ARRIVED"),
    "COMPLETE": ("ARRIVED", "COMPLETED"),
    "EXCEPTION": (None, "EXCEPTION"),
}
TERMINAL_TASK_STATES = {"COMPLETED", "EXCEPTION"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_CANONICAL_BYTES = 2_500_000
MAX_TASKS = 36
EXPECTED_DISTRICTS = 29


class ContractError(ValueError):
    """Raised when an untrusted payload violates the public contract."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expect_exact_keys(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label}_must_be_object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(f"{label}_keys_mismatch:missing={missing}:extra={extra}")
    return value


def _expect_string(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"{label}_invalid_string")
    return value


def _expect_identifier(value: Any, label: str) -> str:
    text = _expect_string(value, label, maximum=128)
    if not ID_RE.fullmatch(text):
        raise ContractError(f"{label}_invalid_identifier")
    return text


def parse_timestamp(value: Any, label: str) -> datetime:
    text = _expect_string(value, label, maximum=40)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"{label}_invalid_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{label}_timezone_required")
    return parsed.astimezone(timezone.utc)


def epoch_from_snapshot(source_snapshot_at: str) -> int:
    """Derive a monotonic millisecond epoch from the source timestamp."""
    parsed = parse_timestamp(source_snapshot_at, "source_snapshot_at")
    return int(parsed.timestamp() * 1000)


def compute_payload_sha256(payload: Mapping[str, Any]) -> str:
    if set(payload) != TOP_LEVEL_KEYS:
        raise ContractError("payload_keys_mismatch_before_hash")
    content = {key: payload[key] for key in HASHED_TOP_LEVEL_KEYS}
    return sha256_hex(canonical_json(content))


def validate_commit(payload: Any) -> dict[str, Any]:
    item = dict(_expect_exact_keys(payload, TOP_LEVEL_KEYS, "commit"))
    if item["schema"] != COMMIT_SCHEMA:
        raise ContractError("unsupported_schema")
    if item["runtime_mode"] != RUNTIME_MODE:
        raise ContractError("runtime_mode_must_be_live")
    _expect_identifier(item["generation_id"], "generation_id")
    snapshot = parse_timestamp(item["source_snapshot_at"], "source_snapshot_at")
    produced = parse_timestamp(item["produced_at"], "produced_at")
    if produced < snapshot:
        raise ContractError("produced_at_before_source_snapshot")
    if not isinstance(item["manifest_sha256"], str) or not SHA256_RE.fullmatch(item["manifest_sha256"]):
        raise ContractError("manifest_sha256_invalid")
    if not isinstance(item["payload_sha256"], str) or not SHA256_RE.fullmatch(item["payload_sha256"]):
        raise ContractError("payload_sha256_invalid")
    districts = item["districts"]
    tasks = item["tasks"]
    if not isinstance(districts, list) or len(districts) != EXPECTED_DISTRICTS:
        raise ContractError("district_count_must_be_29")
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise ContractError("task_count_must_be_between_0_and_36")

    district_ids: set[str] = set()
    district_names: set[str] = set()
    for index, district_value in enumerate(districts):
        district = _expect_exact_keys(district_value, DISTRICT_KEYS, f"district_{index}")
        district_id = _expect_identifier(district["district_id"], f"district_{index}.district_id")
        district_name = _expect_string(district["district_name"], f"district_{index}.district_name", maximum=32)
        if district_id in district_ids or district_name in district_names:
            raise ContractError("duplicate_district")
        district_ids.add(district_id)
        district_names.add(district_name)
        if district["status_level"] not in STATUS_LEVELS:
            raise ContractError(f"district_{index}.status_level_invalid")
        if district["suggested_action"] not in DISTRICT_ACTIONS:
            raise ContractError(f"district_{index}.suggested_action_invalid")

    task_ids: set[str] = set()
    for index, task_value in enumerate(tasks):
        task = _expect_exact_keys(task_value, TASK_KEYS, f"task_{index}")
        task_id = _expect_identifier(task["task_id"], f"task_{index}.task_id")
        _expect_identifier(task["station_id"], f"task_{index}.station_id")
        if task_id in task_ids:
            raise ContractError("duplicate_task")
        task_ids.add(task_id)
        if task["district_id"] not in district_ids:
            raise ContractError(f"task_{index}.unknown_district")
        if task["priority_level"] not in PRIORITY_LEVELS:
            raise ContractError(f"task_{index}.priority_level_invalid")
        if task["suggested_action"] not in TASK_ACTIONS:
            raise ContractError(f"task_{index}.suggested_action_invalid")
        created = parse_timestamp(task["created_at"], f"task_{index}.created_at")
        expires = parse_timestamp(task["expires_at"], f"task_{index}.expires_at")
        if created < snapshot or expires <= created:
            raise ContractError(f"task_{index}.time_window_invalid")

    encoded = canonical_json({key: item[key] for key in HASHED_TOP_LEVEL_KEYS})
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise ContractError("payload_too_large_for_atomic_transaction")
    expected_hash = sha256_hex(encoded)
    if not hmac.compare_digest(expected_hash, item["payload_sha256"]):
        raise ContractError("payload_sha256_mismatch")
    item["sequence_epoch"] = epoch_from_snapshot(item["source_snapshot_at"])
    return item


def validate_event(payload: Any) -> dict[str, Any]:
    item = dict(_expect_exact_keys(payload, EVENT_KEYS, "task_event"))
    _expect_identifier(item["event_id"], "event_id")
    if item["event_type"] not in EVENT_TARGET:
        raise ContractError("event_type_invalid")
    parse_timestamp(item["occurred_at"], "occurred_at")
    return item


def transaction_token(*parts: str) -> str:
    return sha256_hex("\n".join(parts).encode("utf-8"))[:36]


def response(status_code: int, body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def decode_json_body(event: Mapping[str, Any]) -> Any:
    body = event.get("body")
    if not isinstance(body, str):
        raise ContractError("request_body_must_be_json_string")
    if event.get("isBase64Encoded") is True:
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ContractError("invalid_base64_body") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json") from exc


def get_header(event: Mapping[str, Any], name: str) -> str | None:
    headers = event.get("headers") or {}
    if not isinstance(headers, dict):
        return None
    target = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == target and isinstance(value, str):
            return value
    return None


def encode_capability(claims: Mapping[str, Any], secret: str) -> str:
    expected = {"v", "task_id", "generation_id", "exp", "nonce"}
    clean = _expect_exact_keys(dict(claims), expected, "capability")
    if clean["v"] != 1 or not isinstance(clean["exp"], int):
        raise ContractError("capability_claims_invalid")
    _expect_identifier(clean["task_id"], "capability.task_id")
    _expect_identifier(clean["generation_id"], "capability.generation_id")
    _expect_identifier(clean["nonce"], "capability.nonce")
    payload = base64.urlsafe_b64encode(canonical_json(clean)).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def decode_capability(token: str, secret: str, *, now_epoch: int) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 2048:
        raise ContractError("capability_invalid")
    encoded, signature = token.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ContractError("capability_signature_invalid")
    try:
        padding = "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("capability_payload_invalid") from exc
    claims = dict(_expect_exact_keys(claims, {"v", "task_id", "generation_id", "exp", "nonce"}, "capability"))
    if claims["v"] != 1 or not isinstance(claims["exp"], int):
        raise ContractError("capability_claims_invalid")
    _expect_identifier(claims["task_id"], "capability.task_id")
    _expect_identifier(claims["generation_id"], "capability.generation_id")
    _expect_identifier(claims["nonce"], "capability.nonce")
    if claims["exp"] < now_epoch:
        raise ContractError("capability_expired")
    return claims


def load_secret(secret_arn: str, client: Any, field: str) -> str:
    if not secret_arn:
        raise ContractError("secret_arn_not_configured")
    result = client.get_secret_value(SecretId=secret_arn)
    value = result.get("SecretString")
    if not isinstance(value, str) or not value:
        raise ContractError("secret_value_missing")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        if field == "qr_hmac_secret":
            return value
        raise ContractError("secret_json_required")
    selected = decoded.get(field) if isinstance(decoded, dict) else None
    return _expect_string(selected, f"secret.{field}", maximum=4096)


def require_region() -> str:
    region = os.environ.get("AWS_REGION", "")
    if region not in {"us-west-2", "us-east-1"}:
        raise ContractError("unsupported_aws_region")
    return region
