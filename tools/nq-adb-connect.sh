#!/bin/sh
# Wait for the Nexus Q ADB-compatible debug bridge and verify shell access.

set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEFAULT_ADB="$ROOT/build/platform-tools-test/platform-tools_r35.0.2/platform-tools/adb"
ADB=${ADB:-}
SERIAL=${NQ_ADB_SERIAL:-169.254.42.2:5555}
TIMEOUT=${NQ_ADB_WAIT_TIMEOUT:-90}
INTERVAL=${NQ_ADB_WAIT_INTERVAL:-1}
ADB_CMD_TIMEOUT=${NQ_ADB_CMD_TIMEOUT:-8}
PYTHON=${PYTHON:-python3}

usage() {
    cat <<'USAGE'
Usage: nq-adb-connect.sh [SERIAL]

Wait for the Nexus Q ADB-compatible TCP bridge and verify root shell access.

Environment:
  ADB                  adb binary to use
  NQ_ADB_SERIAL        default target, defaults to 169.254.42.2:5555
  NQ_ADB_WAIT_TIMEOUT  seconds to wait, defaults to 90
  NQ_ADB_WAIT_INTERVAL seconds between attempts, defaults to 1
  NQ_ADB_CMD_TIMEOUT   seconds before restarting stuck adb commands, defaults to 8
USAGE
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    "")
        ;;
    *)
        SERIAL=$1
        ;;
esac

if [ -z "$ADB" ]; then
    if [ -x "$DEFAULT_ADB" ]; then
        ADB=$DEFAULT_ADB
    elif command -v adb >/dev/null 2>&1; then
        ADB=$(command -v adb)
    else
        echo "nq-adb-connect: adb not found; set ADB=/path/to/adb" >&2
        exit 127
    fi
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "nq-adb-connect: python3 not found; set PYTHON=/path/to/python3" >&2
    exit 127
fi

case "$TIMEOUT" in
    ""|*[!0-9]*) TIMEOUT=90 ;;
esac
case "$INTERVAL" in
    ""|*[!0-9]*) INTERVAL=1 ;;
esac
case "$ADB_CMD_TIMEOUT" in
    ""|*[!0-9]*) ADB_CMD_TIMEOUT=8 ;;
esac

adb_run() {
    NQ_ADB_CMD_TIMEOUT=$ADB_CMD_TIMEOUT "$PYTHON" - "$ADB" "$@" <<'PY'
import os
import subprocess
import sys

timeout = int(os.environ.get("NQ_ADB_CMD_TIMEOUT", "8"))
cmd = sys.argv[1:]
try:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
except subprocess.TimeoutExpired as exc:
    if exc.stdout:
        sys.stdout.write(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace"))
    print("nq-adb-connect: timed out: " + " ".join(cmd), file=sys.stderr)
    raise SystemExit(124)

sys.stdout.write(proc.stdout)
raise SystemExit(proc.returncode)
PY
}

deadline=$(( $(date +%s) + TIMEOUT ))
attempt=0

adb_run start-server >/dev/null 2>&1 || true
adb_run disconnect "$SERIAL" >/dev/null 2>&1 || true

while :; do
    attempt=$((attempt + 1))
    now=$(date +%s)
    if [ "$now" -gt "$deadline" ]; then
        echo "nq-adb-connect: timed out waiting for $SERIAL" >&2
        "$ADB" devices >&2 || true
        exit 1
    fi

    connect_out=$(adb_run connect "$SERIAL" 2>&1 || true)
    case "$connect_out" in
        *"timed out"*)
            adb_run kill-server >/dev/null 2>&1 || true
            adb_run start-server >/dev/null 2>&1 || true
            sleep "$INTERVAL"
            continue
            ;;
    esac
    state=$(adb_run -s "$SERIAL" get-state 2>/dev/null || true)
    if [ "$state" = "device" ]; then
        shell_out=$(adb_run -s "$SERIAL" shell 'printf "nq-adb-ready "; id; uname -r' 2>&1 || true)
        case "$shell_out" in
            nq-adb-ready*)
                printf '%s\n' "$connect_out"
                printf '%s\n' "$shell_out"
                exit 0
                ;;
        esac
    fi

    case "$connect_out $state" in
        *offline*|*unauthorized*|*unknown*)
            adb_run disconnect "$SERIAL" >/dev/null 2>&1 || true
            ;;
    esac

    if [ $((attempt % 15)) -eq 0 ]; then
        adb_run kill-server >/dev/null 2>&1 || true
        adb_run start-server >/dev/null 2>&1 || true
    fi
    sleep "$INTERVAL"
done
