#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SRC="$ROOT/kernel/linux-6.6.142"
OUT="$ROOT/build/linux-6.6-steelhead"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-steelhead.img}"
ZIMAGE_DTB="$ROOT/artifacts/linux66-steelhead-zImage-dtb"
DTB_TARGET="ti/omap/omap4-steelhead.dtb"
DTB_REL="arch/arm/boot/dts/$DTB_TARGET"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
CMDLINE="${CMDLINE:-console=ttyO2,115200n8 earlyprintk ignore_loglevel root=/dev/ram0 rdinit=/init init=/init}"
RAMDISK_ADDR="${RAMDISK_ADDR:-0x81000000}"

[ -d "$SRC" ] || {
	echo "missing $SRC; download and extract Linux 6.6 first" >&2
	exit 1
}

cp "$ROOT/linux66/omap4-steelhead.dts" \
	"$SRC/arch/arm/boot/dts/ti/omap/omap4-steelhead.dts"

mkdir -p "$OUT" "$ROOT/artifacts"

docker run --rm \
	-v "$ROOT:$ROOT" \
	-w "$SRC" \
	nexusq-linux66-build \
	bash -lc "ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- ./scripts/kconfig/merge_config.sh -O '$OUT' arch/arm/configs/multi_v7_defconfig '$ROOT/linux66/nexusq-linux66.fragment' && make O='$OUT' ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- -j'$JOBS' zImage '$DTB_TARGET'"

cat "$OUT/arch/arm/boot/zImage" "$OUT/$DTB_REL" > "$ZIMAGE_DTB"

python3 "$ROOT/tools/mkbootimg_legacy.py" \
	--kernel "$ZIMAGE_DTB" \
	--ramdisk "$ROOT/artifacts/nexusq-initramfs.cpio.gz" \
	--output "$IMAGE" \
	--kernel-addr 0x80008000 \
	--ramdisk-addr "$RAMDISK_ADDR" \
	--second-addr 0x80f00000 \
	--tags-addr 0x80000100 \
	--page-size 2048 \
	--cmdline "$CMDLINE"

ls -l "$OUT/arch/arm/boot/zImage" "$OUT/$DTB_REL" "$ZIMAGE_DTB" "$IMAGE"
