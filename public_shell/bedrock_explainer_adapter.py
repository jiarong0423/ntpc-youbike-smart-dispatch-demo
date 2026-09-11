#!/usr/bin/env python3
"""Validate and optionally send one sanitized explanation request to Bedrock."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "bedrock_explainer.schema.json"
DEFAULT_REGION = "ap-southeast-2"
DEFAULT_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
MAX_OUTPUT_TOKENS = 256
CREDENTIAL_ENV = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
}
DIRECT_VENDOR_ENV = {
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def require_external_output(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = PROJECT_ROOT.resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError("output_directory_must_be_outside_project")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.expanduser().resolve(strict=True).read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        SCHEMA_PATH.read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ValueError("sanitized_payload_schema_invalid")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden = (
        "/" + "Users/",
        "latitude",
        "longitude",
        ".sqlite",
        "station_id",
        "station_name",
    )
    if any(item.lower() in encoded.lower() for item in forbidden):
        raise ValueError("sanitized_payload_contains_forbidden_text")
    return payload


def build_prompt(payload: dict[str, Any]) -> str:
    return (
        "你是公共自行車調度台的說明層。輸入是經敏感欄位遮蔽、區級聚合的"
        "既有決策摘要，不是要求你決定派工。不可要求或推測站名、位置、"
        "原始快照、資料庫、內部演算法、設備或個資。請用繁體中文輸出"
        "三行：狀態、原因、操作員顯示文字。\n\n"
        "Sanitized aggregate summary:\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def build_request(
    model_id: str,
    prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    if not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
        raise ValueError("max_tokens_out_of_range")
    return {
        "modelId": model_id,
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": 0,
        },
    }


def isolated_environment(
    profile: str,
    region: str,
    session_dir: Path,
) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
        raise ValueError("aws_profile_invalid")
    if any(os.environ.get(name) for name in CREDENTIAL_ENV):
        raise ValueError("ambient_aws_credentials_rejected")
    if any(os.environ.get(name) for name in DIRECT_VENDOR_ENV):
        raise ValueError("direct_vendor_credentials_rejected")
    session = require_external_output(session_dir)
    env = os.environ.copy()
    env.update(
        {
            "AWS_CONFIG_FILE": str(session / "config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(
                session / "credentials"
            ),
            "AWS_LOGIN_CACHE_DIRECTORY": str(
                session / "login" / "cache"
            ),
            "AWS_PROFILE": profile,
            "AWS_DEFAULT_PROFILE": profile,
            "AWS_REGION": region,
            "AWS_DEFAULT_REGION": region,
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_RETRY_MODE": "standard",
        }
    )
    return env


def redact_error(value: str) -> str:
    text = re.sub(
        r"arn:aws[^\s\"']*",
        "[ARN]",
        str(value),
    )
    text = re.sub(
        r"https?://[^\s]+",
        "[URL]",
        text,
    )
    text = re.sub(
        r"\b\d{12}\b",
        "[ACCOUNT]",
        text,
    )
    text = re.sub(
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "[ACCESS_KEY]",
        text,
    )
    return text[:1000]


def extract_text(response: dict[str, Any]) -> str:
    content = (
        response.get("output", {})
        .get("message", {})
        .get("content", [])
    )
    return "\n".join(
        item["text"]
        for item in content
        if (
            isinstance(item, dict)
            and isinstance(item.get("text"), str)
        )
    ).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument(
        "--payload",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--profile",
        required=True,
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=220,
    )
    parser.add_argument(
        "--allow-paid-inference",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = require_external_output(
        args.output_dir
    )
    payload = load_payload(args.payload)
    prompt = build_prompt(payload)
    request_payload = build_request(
        args.model_id,
        prompt,
        args.max_tokens,
    )
    request_path = output_dir / "bedrock_request.json"
    response_path = output_dir / "bedrock_response.json"
    summary_path = output_dir / "bedrock_summary.json"
    write_json(
        request_path,
        request_payload,
    )

    called = False
    return_code: int | None = None
    assistant_text = ""
    error_text = ""
    if args.allow_paid_inference:
        env = isolated_environment(
            args.profile,
            args.region,
            args.session_dir,
        )
        aws_bin = shutil.which(
            "aws",
            path=env.get("PATH"),
        )
        if not aws_bin:
            error_text = "aws_cli_not_available"
            return_code = 127
        else:
            called = True
            completed = subprocess.run(
                [
                    aws_bin,
                    "--profile",
                    args.profile,
                    "--region",
                    args.region,
                    "--no-cli-pager",
                    "bedrock-runtime",
                    "converse",
                    "--cli-input-json",
                    f"file://{request_path}",
                    "--output",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=60,
            )
            return_code = completed.returncode
            error_text = redact_error(
                completed.stderr
            )
            if completed.stdout.strip():
                try:
                    response = json.loads(
                        completed.stdout
                    )
                except json.JSONDecodeError:
                    response = {}
                assistant_text = extract_text(
                    response
                )
                write_json(
                    response_path,
                    response,
                )
    else:
        write_json(
            response_path,
            {
                "not_sent": True,
                "reason": "paid_inference_not_authorized",
            },
        )

    inference_succeeded = (
        called
        and return_code == 0
        and bool(assistant_text)
    )
    run_succeeded = (
        not args.allow_paid_inference
        or inference_succeeded
    )
    summary = {
        "schema_version": "youbike.bedrock_explainer_run.v2",
        "created_at": dt.datetime.now(
            dt.timezone.utc
        ).isoformat(),
        "mode": (
            "paid_single_converse"
            if args.allow_paid_inference
            else "prepare_only"
        ),
        "profile_configured": True,
        "region": args.region,
        "model_id": args.model_id,
        "bedrock_called": called,
        "provider_calls_attempted": (
            1 if called else 0
        ),
        "assistant_text": assistant_text,
        "stderr_redacted": error_text,
        "privacy_boundary": {
            "raw_snapshots_sent": False,
            "coordinates_sent": False,
            "station_names_sent": False,
            "identity_data_sent": False,
            "algorithm_sent": False,
            "cloud_resource_mutation": False,
        },
        "preparation_valid": True,
        "inference_succeeded": inference_succeeded,
    }
    write_json(
        summary_path,
        summary,
    )
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if run_succeeded else 2


if __name__ == "__main__":
    raise SystemExit(main())
