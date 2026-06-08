#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

GEN_INIT_CPIO="${GEN_INIT_CPIO:-/src/build-gcc46/usr/gen_init_cpio}"
DOCKER_IMAGE="${DOCKER_IMAGE:-nexusq-build:android-gcc46-amd64}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

tools/build_userspace.sh

docker run --rm --platform "$DOCKER_PLATFORM" \
	-v nexusq-kernel:/src \
	-v "$ROOT:$ROOT" \
	-w "$ROOT" \
	"$DOCKER_IMAGE" \
	bash -lc "\"$GEN_INIT_CPIO\" initramfs/initramfs.list > artifacts/nexusq-initramfs.cpio && gzip -9 -n -c artifacts/nexusq-initramfs.cpio > artifacts/nexusq-initramfs.cpio.gz"

python3 tools/mkbootimg_legacy.py \
	--kernel artifacts/steelhead-zImage \
	--ramdisk artifacts/nexusq-initramfs.cpio.gz \
	--output artifacts/nexusq-rescue-acm-ecm.img \
	--kernel-addr 0x80008000 \
	--ramdisk-addr 0x81000000 \
	--second-addr 0x80f00000 \
	--tags-addr 0x80000100 \
	--page-size 2048

ls -l artifacts/nexusq-initramfs.cpio.gz artifacts/nexusq-rescue-acm-ecm.img
