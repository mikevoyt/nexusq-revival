#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular}" \
MODULE_TARGETS="${MODULE_TARGETS:-drivers/dma/ti/omap-dma.ko sound/soc/codecs/snd-soc-tas571x.ko sound/soc/ti/snd-soc-ti-sdma.ko sound/soc/ti/snd-soc-omap-mcbsp.ko sound/soc/ti/snd-soc-steelhead-tas5713.ko}" \
	"$ROOT/tools/build_audio_modules_local.sh"
