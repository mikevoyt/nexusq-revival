#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
LOCAL_CC="$ROOT/build/toolchains/armv5l-linux-musleabi-cross/bin/armv5l-linux-musleabi-gcc"
CC="${CC:-}"
ZIG="${ZIG:-}"
ZIG_TARGET="${ZIG_TARGET:-arm-linux-musleabihf}"
ZIG_CFLAGS="${ZIG_CFLAGS:--include sys/ioctl.h}"
FORCE_DOCKER="${FORCE_DOCKER:-0}"
DOCKER_IMAGE="${DOCKER_IMAGE:-ubuntu:20.04}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

build_with_cc() {
	"$CC" -static -Os -Wall "$@"
}

build_with_docker() {
	docker run --rm --platform "$DOCKER_PLATFORM" \
		-v nexusq-musl:/musl \
		-v "$ROOT:$ROOT" \
		-w "$ROOT" \
		"$DOCKER_IMAGE" \
		/musl/armv5l-linux-musleabi-cross/bin/armv5l-linux-musleabi-gcc \
		-static -Os -Wall "$@"
}

build_with_zig() {
	"$ZIG" cc -target "$ZIG_TARGET" -static -Os -Wall $ZIG_CFLAGS "$@"
}

build() {
	if [ "$FORCE_DOCKER" != 1 ] && [ -z "$CC" ] && [ -x "$LOCAL_CC" ] &&
		"$LOCAL_CC" --version >/dev/null 2>&1; then
		CC="$LOCAL_CC"
	fi
	if [ "$FORCE_DOCKER" != 1 ] && [ -z "$CC" ] && [ -z "$ZIG" ] &&
		command -v zig >/dev/null 2>&1; then
		ZIG="$(command -v zig)"
	fi

	if [ "$FORCE_DOCKER" != 1 ] && [ -n "$CC" ]; then
		CC="${CC:-$LOCAL_CC}"
		build_with_cc "$@"
	elif [ "$FORCE_DOCKER" != 1 ] && [ -n "$ZIG" ]; then
		build_with_zig "$@"
	else
		build_with_docker "$@"
	fi
}

build -Ithird_party/tinyalsa/include \
	-o artifacts/bin/tinyplay \
	third_party/tinyalsa/tinyplay.c third_party/tinyalsa/pcm.c

build -Ithird_party/tinyalsa/include \
	-o artifacts/bin/nqstreamd \
	tools/nqstreamd.c third_party/tinyalsa/pcm.c

build -Ithird_party/tinyalsa/include \
	-o artifacts/bin/tinymix \
	third_party/tinyalsa/tinymix.c third_party/tinyalsa/mixer.c

build \
	-o artifacts/bin/reboot-bootloader \
	tools/reboot_bootloader.c

build \
	-o artifacts/bin/nq-knob-volume \
	tools/nq_knob_volume.c

build \
	-o artifacts/bin/nq-adbd-lite \
	tools/nq_adbd_lite.c

build \
	-o artifacts/bin/nq-avr-i2c \
	tools/nq_avr_i2c.c

build \
	-o artifacts/bin/nq-led-visualizer \
	tools/nq_led_visualizer.c

build \
	-o artifacts/bin/nq-pcm-level-tap \
	tools/nq_pcm_level_tap.c

build \
	-o artifacts/bin/nq-pcm-sync-pulse \
	tools/nq_pcm_sync_pulse.c

build \
	-o artifacts/bin/nq-nfc-poll \
	tools/nq_nfc_poll.c

ls -l artifacts/bin/tinyplay artifacts/bin/nqstreamd artifacts/bin/tinymix \
	artifacts/bin/reboot-bootloader artifacts/bin/nq-knob-volume \
	artifacts/bin/nq-adbd-lite artifacts/bin/nq-avr-i2c \
	artifacts/bin/nq-led-visualizer artifacts/bin/nq-pcm-level-tap \
	artifacts/bin/nq-pcm-sync-pulse artifacts/bin/nq-nfc-poll
