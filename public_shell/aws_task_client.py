"""AWS IAM task API signing with an explicitly selected CLI profile."""
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse, request
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess

def validate_api_endpoint(url, region):
    parsed = parse.urlsplit(url)
    expected = r"[a-z0-9]{10}\.execute-api\." + re.escape(region) + r"\.amazonaws\.com"
    if (not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*", region)
            or parsed.scheme != "https" or not re.fullmatch(expected, parsed.hostname or "")
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or parsed.query or ".." in parse.unquote(parsed.path).split("/")):
        raise ValueError("cloud_api_must_match_execute_api_region")
    return url.rstrip("/")


class NoSignedRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def signed_request(url, body, credentials, region, *, now=None, method=None):
    validate_api_endpoint(url, region)
    current = now or datetime.now(timezone.utc)
    stamp = current.strftime("%Y%m%dT%H%M%SZ")
    date = current.strftime("%Y%m%d")
    parsed = parse.urlsplit(url)
    method = method or ("GET" if body is None else "POST")
    encoded = b"" if body is None else body
    headers = {"host": parsed.netloc, "x-amz-date": stamp,
               "x-amz-security-token": credentials["SessionToken"]}
    names = ";".join(sorted(headers))
    canonical_headers = "".join(f"{key}:{headers[key].strip()}\n" for key in sorted(headers))
    query = "&".join(f"{parse.quote(k, safe='-_.~')}={parse.quote(v, safe='-_.~')}"
                     for k, v in sorted(parse.parse_qsl(parsed.query, keep_blank_values=True)))
    path = parse.quote(parse.unquote(parsed.path or "/"), safe="/-_.~")
    canonical = "\n".join((method, path, query, canonical_headers, names, hashlib.sha256(encoded).hexdigest()))
    scope = f"{date}/{region}/execute-api/aws4_request"
    message = "\n".join(("AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()))
    key = ("AWS4" + credentials["SecretAccessKey"]).encode()
    for part in (date, region, "execute-api", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={credentials['AccessKeyId']}/{scope}, SignedHeaders={names}, Signature={signature}"
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return request.Request(url, data=body, headers=headers, method=method)


class IsolatedTaskSigner:
    def __init__(self, session_dir: Path | None, region: str, profile: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
            raise ValueError("aws_profile_invalid")
        self.session = session_dir.expanduser().resolve() if session_dir else None
        self.region = region
        self.profile = profile

    def credentials(self):
        if self.session is not None and not self.session.is_dir():
            raise RuntimeError("isolated_aws_session_unavailable")
        env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
        env.update({"AWS_EC2_METADATA_DISABLED": "true", "AWS_CLI_AUTO_PROMPT": "off"})
        if self.session is not None:
            env.update({"AWS_CONFIG_FILE": str(self.session / "config"),
                        "AWS_SHARED_CREDENTIALS_FILE": str(self.session / "credentials"),
                        "AWS_LOGIN_CACHE_DIRECTORY": str(self.session / "login" / "cache")})
        executable = shutil.which("aws", path=env.get("PATH"))
        if not executable:
            raise RuntimeError("aws_cli_unavailable")
        try:
            result = subprocess.run([executable, "configure", "export-credentials", "--profile", self.profile,
                                     "--format", "process"], capture_output=True, text=True, encoding="utf-8",
                                    timeout=15, env=env, check=False)
            if result.returncode:
                raise RuntimeError("isolated_aws_session_unavailable")
            credentials = json.loads(result.stdout)
            if not all(isinstance(credentials.get(key), str) and credentials[key]
                       for key in ("AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration")):
                raise ValueError("temporary_credentials_required")
            expires = datetime.fromisoformat(credentials["Expiration"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                raise ValueError("temporary_credentials_expired")
            return credentials
        except (OSError, subprocess.SubprocessError, ValueError):
            raise RuntimeError("isolated_aws_session_unavailable") from None

    def request(self, url, body):
        validate_api_endpoint(url, self.region)
        return signed_request(url, body, self.credentials(), self.region)
