#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SRC="${SRC:-$ROOT/kernel/linux-6.6.142}"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead}"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-rd830-autoreboot.img}"
ZIMAGE_DTB="${ZIMAGE_DTB:-$ROOT/artifacts/linux66-omap2plus-steelhead-zImage-dtb}"
DTB_TARGET="ti/omap/omap4-steelhead.dtb"
DTB_REL="arch/arm/boot/dts/$DTB_TARGET"
if [ -n "${MAKE:-}" ]; then
	:
elif [ -x "$ROOT/tools/host/bin/make" ]; then
	MAKE="$ROOT/tools/host/bin/make"
elif command -v gmake >/dev/null 2>&1; then
	MAKE="$(command -v gmake)"
else
	MAKE=make
fi
CROSS_COMPILE="${CROSS_COMPILE:-/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/bin/arm-none-eabi-}"
HOST_ELF_H="${HOST_ELF_H:-/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/arm-none-eabi/include/elf.h}"
HOSTCFLAGS_LOCAL="-I$ROOT/tools/host/include ${HOSTCFLAGS:-}"
if [ -z "${PKG_CONFIG_PATH:-}" ] &&
	[ -d /opt/homebrew/opt/openssl@3/lib/pkgconfig ]; then
	export PKG_CONFIG_PATH=/opt/homebrew/opt/openssl@3/lib/pkgconfig
fi
FRAGMENTS="${FRAGMENTS:-$ROOT/linux66/nexusq-linux66.fragment}"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)}"
RAMDISK_ADDR="${RAMDISK_ADDR:-0x83000000}"
RAMDISK="${RAMDISK:-$ROOT/artifacts/nexusq-initramfs.cpio.gz}"
CMDLINE="${CMDLINE:-console=ttyO2,115200n8 earlyprintk ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.autoreboot=20}"

[ -x "$MAKE" ] || {
	echo "missing GNU make at $MAKE; build tools/host/bin/make first" >&2
	exit 1
}

[ -d "$SRC" ] || {
	echo "missing $SRC; download and extract Linux 6.6 first" >&2
	exit 1
}

KERNEL_PATCH="$ROOT/patches/linux-6.6.142-nexusq-steelhead.patch"
if [ -f "$KERNEL_PATCH" ] && [ ! -f "$SRC/sound/soc/ti/steelhead-tas5713.c" ]; then
	patch -d "$SRC" -p2 < "$KERNEL_PATCH"
fi

mkdir -p "$ROOT/tools/host/include"
[ -f "$HOST_ELF_H" ] || {
	echo "missing host elf.h source at $HOST_ELF_H" >&2
	exit 1
}
ln -sf "$HOST_ELF_H" "$ROOT/tools/host/include/elf.h"

cp "$ROOT/linux66/omap4-steelhead.dts" \
	"$SRC/arch/arm/boot/dts/ti/omap/omap4-steelhead.dts"

mkdir -p "$OUT" "$ROOT/artifacts"

"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
	HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
	omap2plus_defconfig

(
	cd "$SRC"
	PATH="$ROOT/tools/host/bin:$PATH" \
		KCONFIG_CONFIG="$OUT/.config" \
		ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
		HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
		./scripts/kconfig/merge_config.sh -m \
		"$OUT/.config" $FRAGMENTS
)

"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
	HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
	olddefconfig

"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
	HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
	-j"$JOBS" zImage "$DTB_TARGET"

if [ "${BUILD_MODULES:-0}" = "1" ]; then
	if [ -n "${BUILD_MODULES_TARGETS:-}" ]; then
		"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
			HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
			-j"$JOBS" $BUILD_MODULES_TARGETS
	elif [ -n "${BUILD_MODULES_M:-}" ]; then
		if [ ! -s "$OUT/Module.symvers" ] && [ -s "$OUT/vmlinux.symvers" ]; then
			cp "$OUT/vmlinux.symvers" "$OUT/Module.symvers"
		fi
		for module_dir in $BUILD_MODULES_M; do
			"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
				HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
				-j"$JOBS" M="$module_dir" modules
		done
	else
		"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
			HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
			-j"$JOBS" modules
	fi
fi

if [ -n "${POST_MODULES_SCRIPT:-}" ]; then
	ROOT="$ROOT" SRC="$SRC" OUT="$OUT" "$POST_MODULES_SCRIPT"
fi

cat "$OUT/arch/arm/boot/zImage" "$OUT/$DTB_REL" > "$ZIMAGE_DTB"

python3 "$ROOT/tools/mkbootimg_legacy.py" \
	--kernel "$ZIMAGE_DTB" \
	--ramdisk "$RAMDISK" \
	--output "$IMAGE" \
	--kernel-addr 0x80008000 \
	--ramdisk-addr "$RAMDISK_ADDR" \
	--second-addr 0x80f00000 \
	--tags-addr 0x80000100 \
	--page-size 2048 \
	--cmdline "$CMDLINE"

ls -l "$OUT/arch/arm/boot/zImage" "$OUT/$DTB_REL" "$ZIMAGE_DTB" "$IMAGE"
