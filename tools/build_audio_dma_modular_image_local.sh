#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CMDLINE_EXTRA="${CMDLINE_EXTRA:-}"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular}"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img}"
ZIMAGE_DTB="${ZIMAGE_DTB:-$ROOT/artifacts/linux66-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular-zImage-dtb}"
RAMDISK="${RAMDISK:-$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz}"

OUT="$OUT" \
IMAGE="$IMAGE" \
ZIMAGE_DTB="$ZIMAGE_DTB" \
RAMDISK="$RAMDISK" \
NQ_LOADER_FORCE_LCH_SIG="${NQ_LOADER_FORCE_LCH_SIG:-17}" \
NQ_LOADER_FORCE_LCH="${NQ_LOADER_FORCE_LCH:-0}" \
NQ_LOADER_FORCE_DESCRIPTOR_RESIDUE="${NQ_LOADER_FORCE_DESCRIPTOR_RESIDUE:-1}" \
FRAGMENTS="$ROOT/linux66/nexusq-linux66.fragment $ROOT/linux66/nexusq-linux66-nosmp.fragment $ROOT/linux66/nexusq-linux66-devsafe.fragment $ROOT/linux66/nexusq-linux66-audio.fragment $ROOT/linux66/nexusq-linux66-audio-modular.fragment $ROOT/linux66/nexusq-linux66-dma-modular.fragment $ROOT/linux66/nexusq-linux66-usbecm.fragment $ROOT/linux66/nexusq-linux66-wifi-public.fragment" \
CMDLINE="console=ttyO2,115200n8 ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.root=/dev/mmcblk0p13 nq.autoreboot=900 panic=30 oops=panic $CMDLINE_EXTRA" \
BUILD_MODULES=1 \
BUILD_MODULES_TARGETS="${BUILD_MODULES_TARGETS:-drivers/dma/ti/omap-dma.ko sound/soc/codecs/snd-soc-tas571x.ko sound/soc/ti/snd-soc-ti-sdma.ko sound/soc/ti/snd-soc-omap-mcbsp.ko sound/soc/ti/snd-soc-steelhead-tas5713.ko drivers/net/wireless/broadcom/brcm80211/brcmutil/brcmutil.ko drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko drivers/net/wireless/broadcom/brcm80211/brcmfmac/wcc/brcmfmac-wcc.ko}" \
POST_MODULES_SCRIPT="$ROOT/tools/build_debian_loader_initramfs_omap_dma_local.sh" \
	"$ROOT/tools/build_linux66_omap2plus_local.sh"
