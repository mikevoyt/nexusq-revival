#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

"$ROOT/tools/build_debian_loader_initramfs_local.sh"

OUT="$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-public-debian-modular" \
IMAGE="$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-modular.img" \
ZIMAGE_DTB="$ROOT/artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-public-debian-modular-zImage-dtb" \
RAMDISK="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz" \
FRAGMENTS="$ROOT/linux66/nexusq-linux66.fragment $ROOT/linux66/nexusq-linux66-nosmp.fragment $ROOT/linux66/nexusq-linux66-audio.fragment $ROOT/linux66/nexusq-linux66-audio-modular.fragment $ROOT/linux66/nexusq-linux66-usbecm.fragment $ROOT/linux66/nexusq-linux66-wifi-public.fragment" \
CMDLINE="console=ttyO2,115200n8 ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.root=/dev/mmcblk0p13 nq.autoreboot=900 panic=30 oops=panic nq.audio_format=i2s nq.audio_inversion=nb-nf nq.steelhead_audio_dump=1 nq.tas571x_dump_regs=1 nq.tas571x_legacy_stream_reinit=1 nq.mcbsp_legacy_element=1 nq.mcbsp_legacy_threshold_frame=1 nq.mcbsp_legacy_tx_irq=1 nq.omap_dma_legacy_cyclic_sync=1 nq.omap_dma_legacy_cyclic_burst=1 nq.omap_dma_legacy_cyclic_pack=1 nq.omap_dma_dump_cyclic=1 nq.mcbsp_no_rx_err_irq=1" \
BUILD_MODULES=1 \
BUILD_MODULES_TARGETS="${BUILD_MODULES_TARGETS:-sound/soc/codecs/snd-soc-tas571x.ko sound/soc/ti/snd-soc-ti-sdma.ko sound/soc/ti/snd-soc-omap-mcbsp.ko sound/soc/ti/snd-soc-steelhead-tas5713.ko drivers/net/wireless/broadcom/brcm80211/brcmutil/brcmutil.ko drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko drivers/net/wireless/broadcom/brcm80211/brcmfmac/wcc/brcmfmac-wcc.ko}" \
	"$ROOT/tools/build_linux66_omap2plus_local.sh"
