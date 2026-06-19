#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
LOCAL_CC="$ROOT/build/toolchains/armv5l-linux-musleabi-cross/bin/armv5l-linux-musleabi-gcc"
CC="${CC:-}"
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

build() {
	if [ "$FORCE_DOCKER" != 1 ] && [ -z "$CC" ] && [ -x "$LOCAL_CC" ] &&
		"$LOCAL_CC" --version >/dev/null 2>&1; then
		CC="$LOCAL_CC"
	fi

	if [ "$FORCE_DOCKER" != 1 ] && [ -n "$CC" ]; then
		CC="${CC:-$LOCAL_CC}"
		build_with_cc "$@"
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

ls -l artifacts/bin/tinyplay artifacts/bin/nqstreamd artifacts/bin/tinymix \
	artifacts/bin/reboot-bootloader artifacts/bin/nq-knob-volume \
	artifacts/bin/nq-adbd-lite artifacts/bin/nq-avr-i2c \
	artifacts/bin/nq-led-visualizer
