#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

"$ROOT/tools/build_debian_loader_initramfs_local.sh"

OUT="$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-debian" \
IMAGE="$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-debian.img" \
ZIMAGE_DTB="$ROOT/artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-debian-zImage-dtb" \
RAMDISK="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz" \
FRAGMENTS="$ROOT/linux66/nexusq-linux66.fragment $ROOT/linux66/nexusq-linux66-nosmp.fragment $ROOT/linux66/nexusq-linux66-audio.fragment $ROOT/linux66/nexusq-linux66-usbecm.fragment $ROOT/linux66/nexusq-linux66-wifi.fragment" \
CMDLINE="console=ttyO2,115200n8 earlyprintk ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.root=/dev/mmcblk0p13 panic=30 oops=panic" \
	"$ROOT/tools/build_linux66_omap2plus_local.sh"
