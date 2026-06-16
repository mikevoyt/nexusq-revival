#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CC="${ARM_NONE_EABI_GCC:-/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/bin/arm-none-eabi-gcc}"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux30-rescue-audio-baseline-autofastboot.img}"
CMDLINE="${CMDLINE:-console=ttyFIQ0 androidboot.console=ttyFIQ0 mem=1G vmalloc=768M omap_wdt.timer_margin=30 no_console_suspend nq.autoreboot=600 panic=30 oops=panic}"

mkdir -p "$ROOT/artifacts"

"$CC" \
	-mcpu=cortex-a9 -marm -mfloat-abi=soft \
	-nostdlib -static -ffreestanding -fno-builtin -fno-stack-protector \
	-Wl,--build-id=none -Wl,-e,_start -Wl,-Ttext-segment=0x10000 \
	-o "$ROOT/artifacts/nq-tas5713-volume-ioctl-armel" \
	"$ROOT/tools/nq_tas5713_volume_ioctl_nolibc.c"

"$ROOT/tools/build_initramfs_local.sh"

python3 "$ROOT/tools/mkbootimg_legacy.py" \
	--kernel "$ROOT/artifacts/steelhead-zImage" \
	--ramdisk "$ROOT/artifacts/nexusq-initramfs.cpio.gz" \
	--output "$IMAGE" \
	--kernel-addr 0x80008000 \
	--ramdisk-addr 0x81000000 \
	--second-addr 0x80f00000 \
	--tags-addr 0x80000100 \
	--page-size 2048 \
	--cmdline "$CMDLINE"

ls -l \
	"$ROOT/artifacts/nq-tas5713-volume-ioctl-armel" \
	"$ROOT/artifacts/nexusq-initramfs.cpio.gz" \
	"$IMAGE"
