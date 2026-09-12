#!/bin/sh

set -eu
umask 077

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
MEDIATOR_URL="http://127.0.0.1:8782/api/v1/dispatch/evaluate"
PUBLIC_PORT=8084
GATEWAY_PID=""

log() {
    printf '%s level=%s message=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2"
}

fail() {
    log ERROR "$1" >&2
    exit 1
}

cleanup() {
    if [ -n "$GATEWAY_PID" ] && kill -0 "$GATEWAY_PID" 2>/dev/null; then
        log INFO "stopping_live_gateway pid=$GATEWAY_PID"
        kill "$GATEWAY_PID" 2>/dev/null || true
        wait "$GATEWAY_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PYTHON_BIN=${PYTHON_BIN:-python3}
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "python_not_found executable=$PYTHON_BIN"

PYTHON_VERSION=$(
    "$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
) || fail "python_version_probe_failed"

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "python_3_11_or_newer_required detected=$PYTHON_VERSION"

"$PYTHON_BIN" -c 'import jsonschema, qrcode' \
    || fail "python_dependencies_missing run_python_m_pip_install_r_requirements_txt"

[ -n "${YOUBIKE_BLACKBOX_CREDENTIAL_FILE:-}" ] \
    || fail "credential_environment_variable_missing"

CREDENTIAL_PATH=$(
    "$PYTHON_BIN" -c '
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
credential = Path(sys.argv[2]).expanduser().resolve(strict=True)
if not credential.is_file():
    raise SystemExit("credential_not_regular_file")
if credential == root or root in credential.parents:
    raise SystemExit("credential_must_be_outside_repository")
if os.stat(credential).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
    raise SystemExit("credential_permissions_must_be_owner_only")
print(credential)
' "$PROJECT_ROOT" "$YOUBIKE_BLACKBOX_CREDENTIAL_FILE"
) || fail "credential_validation_failed"

export YOUBIKE_BLACKBOX_CREDENTIAL_FILE="$CREDENTIAL_PATH"
export YOUBIKE_BLACKBOX_URL="$MEDIATOR_URL"
export YOUBIKE_BLACKBOX_TIMEOUT_SECONDS="${YOUBIKE_BLACKBOX_TIMEOUT_SECONDS:-5}"
export PYTHONUNBUFFERED=1

RUNTIME_DIR_INPUT=${YOUBIKE_LIVE_RUNTIME_DIR:-${TMPDIR:-/tmp}/ntpc-youbike-live-mac}
RUNTIME_DIR=$(
    "$PYTHON_BIN" -c '
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
runtime = Path(sys.argv[2]).expanduser().resolve(strict=False)
if runtime == root or root in runtime.parents:
    raise SystemExit("runtime_directory_must_be_outside_repository")
runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
runtime.chmod(0o700)
print(runtime)
' "$PROJECT_ROOT" "$RUNTIME_DIR_INPUT"
) || fail "runtime_directory_validation_failed"

TASK_DB="$RUNTIME_DIR/task-ledger.sqlite3"
LOG_FILE="$RUNTIME_DIR/public-gateway.log"
PUBLIC_BIND=${YOUBIKE_PUBLIC_BIND:-127.0.0.1}
PUBLIC_BASE_URL=${PUBLIC_TASK_BASE_URL:-http://127.0.0.1:$PUBLIC_PORT}
TASK_BACKEND=${YOUBIKE_TASK_BACKEND:-local}

case "$PUBLIC_BIND" in
    127.0.0.1|0.0.0.0) ;;
    *) fail "public_bind_must_be_127_0_0_1_or_0_0_0_0" ;;
esac

# A QR encoding 127.0.0.1 is unreachable from a phone. When the operator opens the
# gateway to the LAN, the task base URL must name exactly one LAN address; an
# ambiguous or absent address refuses to start rather than publishing a dead QR.
if [ "$PUBLIC_BIND" = "0.0.0.0" ] && [ -z "${PUBLIC_TASK_BASE_URL:-}" ]; then
    LAN_ADDRESSES=$(
        for interface in $(ifconfig -l 2>/dev/null); do
            case "$interface" in
                (lo*|utun*|awdl*|llw*|bridge*|gif*|stf*|anpi*|ap1) continue ;;
            esac
            address=$(ipconfig getifaddr "$interface" 2>/dev/null) || continue
            [ -n "$address" ] && printf '%s\n' "$address"
        done | sort -u
    )
    LAN_COUNT=$(printf '%s' "$LAN_ADDRESSES" | grep -c . || true)
    [ "$LAN_COUNT" -eq 1 ] \
        || fail "lan_address_must_be_unique found=$LAN_COUNT addresses=$(printf '%s' "$LAN_ADDRESSES" | tr '\n' ',') remedy=set_PUBLIC_TASK_BASE_URL_to_http_//<chosen-address>:$PUBLIC_PORT"
    PUBLIC_BASE_URL="http://$LAN_ADDRESSES:$PUBLIC_PORT"
    log INFO "lan_task_base_url url=$PUBLIC_BASE_URL"
fi

case "$TASK_BACKEND" in
    local) ;;
    cloud)
        [ -n "${TASK_CLOUD_API_URL:-}" ] \
            || fail "cloud_task_api_url_missing"
        [ -n "${YOUBIKE_AWS_PROFILE:-}" ] \
            || fail "cloud_aws_profile_missing"
        [ -n "${YOUBIKE_AWS_REGION:-}" ] \
            || fail "cloud_aws_region_missing"
        ;;
    *) fail "task_backend_must_be_local_or_cloud" ;;
esac

if "$PYTHON_BIN" -c '
import socket
import sys

with socket.socket() as sock:
    sock.settimeout(0.25)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
' "$PUBLIC_PORT"; then
    fail "public_port_already_in_use port=$PUBLIC_PORT"
fi

log INFO "preflight_live_mediator"
"$PYTHON_BIN" "$PROJECT_ROOT/scripts/smoke_live_mac.py" \
    --mediator-only \
    --wait-seconds 5

set -- \
    "$PYTHON_BIN" -u "$PROJECT_ROOT/public_shell/serve_public_blackbox_gateway.py" \
    --bind "$PUBLIC_BIND" \
    --port "$PUBLIC_PORT" \
    --directory "$PROJECT_ROOT" \
    --public-task-base-url "$PUBLIC_BASE_URL" \
    --task-backend "$TASK_BACKEND"

if [ "$TASK_BACKEND" = "local" ]; then
    set -- "$@" --task-db "$TASK_DB"
else
    set -- "$@" \
        --task-cloud-url "$TASK_CLOUD_API_URL" \
        --aws-profile "$YOUBIKE_AWS_PROFILE" \
        --aws-region "$YOUBIKE_AWS_REGION"
fi

log INFO "starting_live_gateway bind=$PUBLIC_BIND port=$PUBLIC_PORT task_backend=$TASK_BACKEND"
"$@" >>"$LOG_FILE" 2>&1 &
GATEWAY_PID=$!

if ! "$PYTHON_BIN" "$PROJECT_ROOT/scripts/smoke_live_mac.py" \
    --public-base-url "http://127.0.0.1:$PUBLIC_PORT" \
    --wait-seconds 25; then
    log ERROR "live_smoke_failed log=$LOG_FILE"
    tail -n 40 "$LOG_FILE" >&2 || true
    exit 1
fi

if ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
    wait "$GATEWAY_PID" || true
    fail "live_gateway_exited_after_smoke log=$LOG_FILE"
fi

log INFO "live_gateway_ready worker_base=$PUBLIC_BASE_URL/tasks/ pid=$GATEWAY_PID log=$LOG_FILE"
wait "$GATEWAY_PID"
