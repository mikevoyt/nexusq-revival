#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular}"
TARGET="${TARGET:-root@192.168.86.38}"
SSH_KEY="${SSH_KEY:-$ROOT/.secrets/nexusq-ssh-test/id_ed25519}"
POLL_MS="${NQ_AVR_POLL_MS:-50}"
FORCE_POLL="${NQ_AVR_FORCE_POLL:-1}"
DEBUG_EVENTS="${NQ_AVR_DEBUG_EVENTS:-0}"
LEGACY_INIT="${NQ_AVR_LEGACY_INIT:-1}"
RESET_PULSE_MS="${NQ_AVR_RESET_PULSE_MS:-0}"
I2C_ADAPTER="${NQ_INPUT_I2C_ADAPTER:-i2c-1}"
I2C_ADDR="${NQ_INPUT_I2C_ADDR:-0x20}"
START_KNOB="${NQ_START_KNOB_VOLUME:-1}"

KO="$OUT/drivers/input/misc/steelhead_avr.ko"
HELPER="$ROOT/artifacts/bin/nq-knob-volume"

[ -s "$KO" ] || {
	echo "missing $KO; build drivers/input/misc/steelhead_avr.ko first" >&2
	exit 1
}
[ -x "$HELPER" ] || {
	echo "missing $HELPER; run tools/build_userspace.sh first" >&2
	exit 1
}

SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
if [ -n "$SSH_KEY" ]; then
	SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

# shellcheck disable=SC2086
scp $SSH_OPTS "$KO" "$HELPER" "$TARGET:/tmp/"

# shellcheck disable=SC2086
ssh $SSH_OPTS "$TARGET" \
	"POLL_MS='$POLL_MS' FORCE_POLL='$FORCE_POLL' DEBUG_EVENTS='$DEBUG_EVENTS' LEGACY_INIT='$LEGACY_INIT' RESET_PULSE_MS='$RESET_PULSE_MS' I2C_ADAPTER='$I2C_ADAPTER' I2C_ADDR='$I2C_ADDR' START_KNOB='$START_KNOB' /bin/sh -s" <<'EOF'
set -eu

krel="$(uname -r)"
moddir="/lib/modules/$krel/kernel/drivers/input/misc"
mkdir -p "$moddir" /usr/sbin

stop_knob_volume() {
	live_pids=""

	pkill -x nq-knob-volume 2>/dev/null || true
	for pid in $(pgrep -x nq-knob-volume 2>/dev/null || true); do
		state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
		[ "$state" = "Z" ] && continue
		live_pids="$live_pids $pid"
	done
	[ -z "$live_pids" ] || kill $live_pids 2>/dev/null || true
	sleep 1
	live_pids=""
	for pid in $(pgrep -x nq-knob-volume 2>/dev/null || true); do
		state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
		[ "$state" = "Z" ] && continue
		live_pids="$live_pids $pid"
	done
	[ -z "$live_pids" ] || kill -KILL $live_pids 2>/dev/null || true
}

stop_knob_volume
cp /tmp/steelhead_avr.ko "$moddir/steelhead_avr.ko"
rm -f /usr/sbin/nq-knob-volume
cp /tmp/nq-knob-volume /usr/sbin/nq-knob-volume
chmod 755 /usr/sbin/nq-knob-volume

avr_args="poll_ms=$POLL_MS force_poll=$FORCE_POLL debug_events=$DEBUG_EVENTS legacy_init=$LEGACY_INIT reset_pulse_ms=$RESET_PULSE_MS"
depmod -a "$krel" 2>/dev/null || true
rmmod steelhead_avr 2>/dev/null || true
insmod "$moddir/steelhead_avr.ko" $avr_args 2>/dev/null || \
	modprobe steelhead_avr $avr_args 2>/dev/null || true

if ! grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null &&
   [ -n "$I2C_ADAPTER" ]; then
	adapter="/sys/bus/i2c/devices/$I2C_ADAPTER"
	if [ -w "$adapter/new_device" ]; then
		echo "binding steelhead-avr on $I2C_ADAPTER at $I2C_ADDR"
		echo "steelhead-avr $I2C_ADDR" >"$adapter/new_device" 2>/dev/null || true
	else
		echo "cannot bind on $I2C_ADAPTER; available adapters:"
		ls -d /sys/bus/i2c/devices/i2c-* 2>/dev/null || true
	fi
fi

if [ "$START_KNOB" = "1" ] && grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null; then
	stop_knob_volume
	NQ_KNOB_MIXER_CARD="${NQ_KNOB_MIXER_CARD:-0}" \
	NQ_KNOB_CONTROL="${NQ_KNOB_CONTROL:-Master Volume}" \
	NQ_KNOB_MUTE_CONTROL="${NQ_KNOB_MUTE_CONTROL:-Speaker Switch}" \
	NQ_KNOB_MIN="${NQ_KNOB_MIN:-120}" \
	NQ_KNOB_MAX="${NQ_KNOB_MAX:-231}" \
	NQ_KNOB_STEP="${NQ_KNOB_STEP:-2}" \
	NQ_KNOB_MUTE_ENABLE="${NQ_KNOB_MUTE_ENABLE:-1}" \
		/usr/sbin/nq-knob-volume >/tmp/nq-knob-volume.log 2>&1 &
	echo "$!" >/tmp/nq-knob-volume.pid
	sleep 1
	echo "--- knob volume ---"
	cat /tmp/nq-knob-volume.log 2>/dev/null || true
fi

echo "--- input devices ---"
cat /proc/bus/input/devices 2>/dev/null || true
echo "--- knob processes ---"
for pid in $(pgrep -x nq-knob-volume 2>/dev/null || true); do
	state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
	echo "$pid state=${state:-?}"
done
echo "--- steelhead dmesg ---"
dmesg | grep -Ei 'steelhead|avr|i2c' | tail -80 || true
EOF
