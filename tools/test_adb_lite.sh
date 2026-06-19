#!/bin/sh
# Smoke-test the Nexus Q ADB-compatible debug daemon from a host.

set -eu

ADB=${ADB:-adb}
SERIAL=${1:-${NQ_ADB_SERIAL:-192.168.86.38:5555}}
tmpdir=$(mktemp -d /tmp/nq-adb-lite.XXXXXX)

cleanup() {
    "$ADB" -s "$SERIAL" shell 'rm -rf /tmp/adb-lite-test /tmp/adb-lite-dir' >/dev/null 2>&1 || true
    rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM

"$ADB" disconnect "$SERIAL" >/dev/null 2>&1 || true
"$ADB" connect "$SERIAL"
"$ADB" -s "$SERIAL" shell 'echo shell=$SHELL; echo bash=$BASH_VERSION; id'

printf 'nexusq adb lite test\n' >"$tmpdir/push.txt"
"$ADB" -s "$SERIAL" push "$tmpdir/push.txt" /tmp/adb-lite-test
"$ADB" -s "$SERIAL" pull /tmp/adb-lite-test "$tmpdir/pulled.txt"
cmp "$tmpdir/push.txt" "$tmpdir/pulled.txt"

mkdir -p "$tmpdir/src/sub"
printf 'alpha\n' >"$tmpdir/src/a.txt"
printf 'beta\n' >"$tmpdir/src/sub/b.txt"
"$ADB" -s "$SERIAL" shell 'rm -rf /tmp/adb-lite-dir'
"$ADB" -s "$SERIAL" push "$tmpdir/src" /tmp/adb-lite-dir
mkdir -p "$tmpdir/out"
"$ADB" -s "$SERIAL" pull /tmp/adb-lite-dir "$tmpdir/out"
cmp "$tmpdir/src/a.txt" "$tmpdir/out/adb-lite-dir/a.txt"
cmp "$tmpdir/src/sub/b.txt" "$tmpdir/out/adb-lite-dir/sub/b.txt"

"$ADB" -s "$SERIAL" root
"$ADB" disconnect "$SERIAL" >/dev/null 2>&1 || true
"$ADB" connect "$SERIAL"
"$ADB" -s "$SERIAL" shell 'echo adb-lite-ok'
