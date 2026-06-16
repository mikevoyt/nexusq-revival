#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SRC="${SRC:-$ROOT/kernel/linux-6.6.142}"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-public-debian-modular}"
MODULE_TARGETS="${MODULE_TARGETS:-sound/soc/codecs/snd-soc-tas571x.ko sound/soc/ti/snd-soc-ti-sdma.ko sound/soc/ti/snd-soc-omap-mcbsp.ko sound/soc/ti/snd-soc-steelhead-tas5713.ko}"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)}"

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

[ -x "$MAKE" ] || {
	echo "missing GNU make at $MAKE; build tools/host/bin/make first" >&2
	exit 1
}

[ -f "$OUT/.config" ] || {
	echo "missing modular kernel config: $OUT/.config" >&2
	echo "run tools/build_audio_modular_image_local.sh first" >&2
	exit 1
}

mkdir -p "$ROOT/tools/host/include"
[ -f "$HOST_ELF_H" ] || {
	echo "missing host elf.h source at $HOST_ELF_H" >&2
	exit 1
}
ln -sf "$HOST_ELF_H" "$ROOT/tools/host/include/elf.h"

if [ ! -s "$OUT/Module.symvers" ] && [ -s "$OUT/vmlinux.symvers" ]; then
	cp "$OUT/vmlinux.symvers" "$OUT/Module.symvers"
fi

"$MAKE" -C "$SRC" O="$OUT" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" \
	HOSTCFLAGS="$HOSTCFLAGS_LOCAL" \
	-j"$JOBS" $MODULE_TARGETS

for target in $MODULE_TARGETS; do
	printf '%s\n' "$OUT/$target"
done
