#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT="$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-public-debian"
ROOTFS_DIR="$ROOT/build/debian-trixie-armhf/rootfs"
ROOTFS_SIZE_MB="${ROOTFS_SIZE_MB:-768}"
MKE2FS="${MKE2FS:-/opt/homebrew/opt/e2fsprogs/sbin/mke2fs}"
RELEASE_VERSION="${RELEASE_VERSION:-v0.4.0}"

# On Apple Silicon, older /usr/local GNU binutils can be x86_64-only. Keep the
# system ar ahead of those while still preferring Homebrew OpenSSL 3 for
# `openssl passwd -6` in the rootfs builder.
if [ -d /opt/homebrew/opt/openssl@3/bin ]; then
	PATH="/opt/homebrew/opt/openssl@3/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
else
	PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
fi
export PATH

BOOT_IMAGE="$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img"
ZIMAGE_DTB="$ROOT/artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-public-debian-zImage-dtb"
ROOTFS_EXT4="$ROOT/artifacts/nexusq-debian-trixie-armhf-rootfs.ext4"
ROOTFS_SPARSE="$ROOT/artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img"
SHA256SUMS="$ROOT/artifacts/SHA256SUMS-$RELEASE_VERSION.txt"
NQ_AUDIO_CMDLINE="nq.audio_format=i2s nq.audio_inversion=nb-nf nq.mcbsp_no_rx_err_irq=1 nq.steelhead_audio_dump=1 nq.tas571x_dump_regs=1 nq.tas571x_legacy_stream_reinit=1 nq.mcbsp_legacy_element=1 nq.mcbsp_legacy_threshold_frame=1 nq.mcbsp_legacy_tx_irq=1 nq.omap_dma_legacy_cyclic_sync=1 nq.omap_dma_legacy_cyclic_burst=1"

"$ROOT/tools/build_userspace.sh"
python3 "$ROOT/tools/build_debian_rootfs.py" --no-ext4
"$ROOT/tools/build_debian_loader_initramfs_local.sh"

OUT="$OUT" \
IMAGE="$BOOT_IMAGE" \
ZIMAGE_DTB="$ZIMAGE_DTB" \
RAMDISK="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz" \
FRAGMENTS="$ROOT/linux66/nexusq-linux66.fragment $ROOT/linux66/nexusq-linux66-nosmp.fragment $ROOT/linux66/nexusq-linux66-audio.fragment $ROOT/linux66/nexusq-linux66-input-modular.fragment $ROOT/linux66/nexusq-linux66-usbecm.fragment $ROOT/linux66/nexusq-linux66-nfc.fragment $ROOT/linux66/nexusq-linux66-wifi-public.fragment" \
CMDLINE="console=ttyO2,115200n8 earlyprintk ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.root=/dev/mmcblk0p13 panic=30 oops=panic $NQ_AUDIO_CMDLINE" \
BUILD_MODULES=1 \
BUILD_MODULES_TARGETS="drivers/input/misc/steelhead_avr.ko net/nfc/nfc.ko net/nfc/hci/hci.ko drivers/nfc/pn544/pn544.ko drivers/nfc/pn544/pn544_i2c.ko drivers/net/wireless/broadcom/brcm80211/brcmutil/brcmutil.ko drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko drivers/net/wireless/broadcom/brcm80211/brcmfmac/wcc/brcmfmac-wcc.ko" \
	"$ROOT/tools/build_linux66_omap2plus_local.sh"

python3 "$ROOT/tools/install_linux66_modules.py" \
	--build-dir "$OUT" \
	--rootfs "$ROOTFS_DIR"

[ -x "$MKE2FS" ] || {
	echo "missing mke2fs at $MKE2FS" >&2
	exit 1
}

rm -f "$ROOTFS_EXT4" "$ROOTFS_SPARSE"
"$MKE2FS" -t ext4 -d "$ROOTFS_DIR" -L nq-debian "$ROOTFS_EXT4" "${ROOTFS_SIZE_MB}M"
python3 "$ROOT/tools/img2simg.py" "$ROOTFS_EXT4" "$ROOTFS_SPARSE"

(
	cd "$ROOT"
	shasum -a 256 \
		"artifacts/$(basename "$BOOT_IMAGE")" \
		"artifacts/$(basename "$ROOTFS_SPARSE")"
) > "$SHA256SUMS"

ls -l "$BOOT_IMAGE" "$ROOTFS_EXT4" "$ROOTFS_SPARSE"
cat "$SHA256SUMS"
