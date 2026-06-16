#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-public-debian-legacydma}"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img}"
ZIMAGE_DTB="${ZIMAGE_DTB:-$ROOT/artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-public-debian-legacydma-zImage-dtb}"

OUT="$OUT" \
IMAGE="$IMAGE" \
ZIMAGE_DTB="$ZIMAGE_DTB" \
RAMDISK="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz" \
FRAGMENTS="$ROOT/linux66/nexusq-linux66.fragment $ROOT/linux66/nexusq-linux66-nosmp.fragment $ROOT/linux66/nexusq-linux66-audio.fragment $ROOT/linux66/nexusq-linux66-usbecm.fragment $ROOT/linux66/nexusq-linux66-wifi-public.fragment" \
CMDLINE="console=ttyO2,115200n8 ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.root=/dev/mmcblk0p13 nq.autoreboot=900 panic=30 oops=panic nq.audio_format=i2s nq.audio_inversion=nb-nf nq.steelhead_audio_dump=1 nq.tas571x_dump_regs=1 nq.tas571x_legacy_stream_reinit=1 nq.mcbsp_legacy_element=1 nq.mcbsp_legacy_threshold_frame=1 nq.mcbsp_legacy_tx_irq=1 nq.omap_dma_legacy_cyclic_sync=1 nq.omap_dma_legacy_cyclic_burst=1 nq.omap_dma_legacy_cyclic_pack=1 nq.omap_dma_dump_cyclic=1 nq.mcbsp_no_rx_err_irq=1" \
  "$ROOT/tools/build_linux66_omap2plus_local.sh"
