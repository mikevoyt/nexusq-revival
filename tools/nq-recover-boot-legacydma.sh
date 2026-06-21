#!/bin/sh
# Recover a Nexus Q into fastboot and boot the legacy-DMA audio test image.

set -u

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img}"
DEFAULT_FASTBOOT="$ROOT/build/platform-tools-test/platform-tools_r35.0.2/platform-tools/fastboot"
DEFAULT_ADB="$ROOT/build/platform-tools-test/platform-tools_r35.0.2/platform-tools/adb"
FASTBOOT="${FASTBOOT:-}"
ADB="${ADB:-}"
PYTHON="${PYTHON:-python3}"
NQ_ADB_SERIAL="${NQ_ADB_SERIAL:-169.254.42.2:5555}"
NQ_SSH_USER="${NQ_SSH_USER:-root}"
NQ_SSH_HOSTS="${NQ_SSH_HOSTS:-169.254.42.2 172.16.42.2 ${NQ_HOST:-192.168.86.38}}"
NQ_SERIAL_DEVICE="${NQ_SERIAL_DEVICE:-}"
NQ_RECOVER_TIMEOUT="${NQ_RECOVER_TIMEOUT:-0}"
NQ_RECOVER_INTERVAL="${NQ_RECOVER_INTERVAL:-2}"
NQ_WAIT_AFTER_BOOT="${NQ_WAIT_AFTER_BOOT:-1}"
NQ_RUN_AUDIO_SMOKE="${NQ_RUN_AUDIO_SMOKE:-0}"
NQ_AUDIO_SMOKE_SECONDS="${NQ_AUDIO_SMOKE_SECONDS:-6}"

usage() {
    cat <<EOF
Usage: nq-recover-boot-legacydma.sh

Wait for a Nexus Q over fastboot, ADB, SSH, or USB serial. If Linux is alive,
ask it to reboot to fastboot. Once fastboot is visible, boot this image without
flashing:

  $IMAGE

Environment:
  IMAGE                  boot image, defaults to the legacy-DMA audio artifact
  FASTBOOT               fastboot binary
  ADB                    adb binary
  NQ_ADB_SERIAL          ADB TCP target, defaults to 169.254.42.2:5555
  NQ_SSH_HOSTS           space-separated SSH hosts to try
  NQ_SERIAL_DEVICE       serial device; auto-detects /dev/cu.usbmodem* if empty
  NQ_RECOVER_TIMEOUT     seconds to wait; 0 means forever
  NQ_RECOVER_INTERVAL    seconds between attempts, defaults to 2
  NQ_WAIT_AFTER_BOOT     wait for ADB after fastboot boot, defaults to 1
  NQ_RUN_AUDIO_SMOKE     run a short ALSA tone after boot, defaults to 0
EOF
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    "")
        ;;
    *)
        echo "unexpected argument: $1" >&2
        usage >&2
        exit 2
        ;;
esac

if [ -z "$FASTBOOT" ]; then
    if [ -x "$DEFAULT_FASTBOOT" ]; then
        FASTBOOT="$DEFAULT_FASTBOOT"
    elif command -v fastboot >/dev/null 2>&1; then
        FASTBOOT="$(command -v fastboot)"
    else
        echo "nq-recover: fastboot not found; set FASTBOOT=/path/to/fastboot" >&2
        exit 127
    fi
fi

if [ -z "$ADB" ]; then
    if [ -x "$DEFAULT_ADB" ]; then
        ADB="$DEFAULT_ADB"
    elif command -v adb >/dev/null 2>&1; then
        ADB="$(command -v adb)"
    fi
fi

if [ ! -s "$IMAGE" ]; then
    echo "nq-recover: missing boot image: $IMAGE" >&2
    exit 1
fi

case "$NQ_RECOVER_TIMEOUT" in
    ""|*[!0-9]*) NQ_RECOVER_TIMEOUT=0 ;;
esac
case "$NQ_RECOVER_INTERVAL" in
    ""|*[!0-9]*) NQ_RECOVER_INTERVAL=2 ;;
esac

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fastboot_serial() {
    "$FASTBOOT" devices 2>/dev/null |
        awk 'NF >= 2 && $2 == "fastboot" { print $1; exit }'
}

adb_run() {
    [ -n "$ADB" ] || return 127
    "$PYTHON" - "$ADB" "$@" <<'PY'
import subprocess
import sys

cmd = sys.argv[1:]
try:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=6,
    )
except subprocess.TimeoutExpired as exc:
    if exc.stdout:
        sys.stdout.write(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace"))
    raise SystemExit(124)

sys.stdout.write(proc.stdout)
raise SystemExit(proc.returncode)
PY
}

adb_reboot_bootloader() {
    [ -n "$ADB" ] || return 1
    NQ_ADB_WAIT_TIMEOUT=8 NQ_ADB_CMD_TIMEOUT=5 ADB="$ADB" \
        "$ROOT/tools/nq-adb-connect.sh" "$NQ_ADB_SERIAL" >/dev/null 2>&1 || return 1
    log "ADB is alive at $NQ_ADB_SERIAL; asking for bootloader"
    adb_run -s "$NQ_ADB_SERIAL" reboot bootloader >/dev/null 2>&1 && return 0
    adb_run -s "$NQ_ADB_SERIAL" shell '/sbin/nq-reboot-fastboot || reboot bootloader || reboot -f' >/dev/null 2>&1
}

ssh_reboot_bootloader() {
    for host in $NQ_SSH_HOSTS; do
        [ -n "$host" ] || continue
        ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
            -o ConnectTimeout=3 "$NQ_SSH_USER@$host" \
            '/sbin/nq-reboot-fastboot || reboot bootloader || reboot -f' >/dev/null 2>&1 || continue
        log "SSH is alive at $host; asked for bootloader"
        return 0
    done
    return 1
}

serial_device() {
    if [ -n "$NQ_SERIAL_DEVICE" ]; then
        [ -e "$NQ_SERIAL_DEVICE" ] && printf '%s\n' "$NQ_SERIAL_DEVICE"
        return
    fi
    for dev in /dev/cu.usbmodem*; do
        [ -e "$dev" ] || continue
        printf '%s\n' "$dev"
        return
    done
}

serial_reboot_bootloader() {
    dev="$(serial_device)"
    [ -n "$dev" ] || return 1
    "$PYTHON" "$ROOT/tools/nq_serial_exec.py" --device "$dev" --timeout 6 \
        '/sbin/nq-reboot-fastboot || reboot bootloader || reboot -f' >/dev/null 2>&1 || return 1
    log "serial is alive at $dev; asked for bootloader"
    return 0
}

wait_for_fastboot_after_reboot() {
    deadline=$(( $(date +%s) + 45 ))
    while [ "$(date +%s)" -le "$deadline" ]; do
        serial="$(fastboot_serial)"
        if [ -n "$serial" ]; then
            printf '%s\n' "$serial"
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_adb_after_boot() {
    [ "$NQ_WAIT_AFTER_BOOT" = "1" ] || return 0
    [ -n "$ADB" ] || return 0
    log "waiting for ADB after temporary boot"
    NQ_ADB_WAIT_TIMEOUT=120 NQ_ADB_CMD_TIMEOUT=5 ADB="$ADB" \
        "$ROOT/tools/nq-adb-connect.sh" "$NQ_ADB_SERIAL"
}

run_audio_smoke() {
    [ "$NQ_RUN_AUDIO_SMOKE" = "1" ] || return 0
    [ -n "$ADB" ] || return 1
    log "running short ALSA smoke test"
    adb_run -s "$NQ_ADB_SERIAL" shell "
        set -x
        pkill -x nq-knob-volume 2>/dev/null || true
        amixer -q -c 0 cset name='Speaker Switch' on || true
        amixer -q -c 0 cset name='Speaker Volume' 210,210 || true
        amixer -q -c 0 cset name='Master Volume' 190 || true
        timeout '$NQ_AUDIO_SMOKE_SECONDS' speaker-test -D hw:0,0 -r 48000 -c 2 -F S16_LE -t sine -f 880 -l 1
        echo smoke_rc=\$?
        cat /proc/asound/card0/pcm0p/sub0/status 2>/dev/null || true
    "
}

boot_image() {
    serial="$1"
    log "fastboot is alive on $serial; booting $(basename "$IMAGE")"
    if ! "$FASTBOOT" boot "$IMAGE"; then
        log "fastboot boot failed"
        return 1
    fi
    if ! wait_for_adb_after_boot; then
        log "temporary boot was sent, but ADB did not become ready"
        return 1
    fi
    run_audio_smoke
}

start="$(date +%s)"
last_status=0
log "watching for Nexus Q; timeout=${NQ_RECOVER_TIMEOUT}s image=$IMAGE"

while :; do
    serial="$(fastboot_serial)"
    if [ -n "$serial" ]; then
        boot_image "$serial"
        exit $?
    fi

    if adb_reboot_bootloader || ssh_reboot_bootloader || serial_reboot_bootloader; then
        serial="$(wait_for_fastboot_after_reboot || true)"
        if [ -n "$serial" ]; then
            boot_image "$serial"
            exit $?
        fi
        log "bootloader request sent, but fastboot did not appear yet"
    fi

    now="$(date +%s)"
    if [ "$NQ_RECOVER_TIMEOUT" -gt 0 ] && [ $((now - start)) -ge "$NQ_RECOVER_TIMEOUT" ]; then
        log "timed out waiting for a recoverable Nexus Q"
        exit 124
    fi
    if [ $((now - last_status)) -ge 30 ]; then
        last_status="$now"
        log "still waiting for fastboot, ADB, SSH, or serial"
    fi
    sleep "$NQ_RECOVER_INTERVAL"
done
