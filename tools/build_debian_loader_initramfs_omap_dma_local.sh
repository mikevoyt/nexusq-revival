#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular}"
DMA_KO="$OUT/drivers/dma/ti/omap-dma.ko"
NQ_LOADER_FORCE_DESCRIPTOR_RESIDUE="${NQ_LOADER_FORCE_DESCRIPTOR_RESIDUE:-0}"
NQ_LOADER_FORCE_LCH_SIG="${NQ_LOADER_FORCE_LCH_SIG:-}"
NQ_LOADER_FORCE_LCH="${NQ_LOADER_FORCE_LCH:-}"
NQ_LOADER_FORCE_RW_PRIORITY="${NQ_LOADER_FORCE_RW_PRIORITY:-0}"

[ -f "$DMA_KO" ] || {
	echo "missing $DMA_KO" >&2
	exit 1
}

case "$DMA_KO" in
	"$ROOT"/*) DMA_SRC="${DMA_KO#$ROOT/}" ;;
	*)
		echo "DMA module path must be under $ROOT: $DMA_KO" >&2
		exit 1
		;;
esac

EXTRA_LIST="$(mktemp "$ROOT/artifacts/debian-loader-omap-dma.list.XXXXXX")"
MARKER_FILE=""
FORCE_LCH_SIG_FILE=""
FORCE_LCH_FILE=""
FORCE_RW_PRIORITY_FILE=""
if [ "$NQ_LOADER_FORCE_DESCRIPTOR_RESIDUE" = "1" ]; then
	MARKER_FILE="$(mktemp "$ROOT/artifacts/nq-force-descriptor-residue.XXXXXX")"
	printf '1\n' > "$MARKER_FILE"
	case "$MARKER_FILE" in
		"$ROOT"/*) MARKER_SRC="${MARKER_FILE#$ROOT/}" ;;
		*)
			echo "marker path must be under $ROOT: $MARKER_FILE" >&2
			exit 1
		;;
	esac
fi
case "$NQ_LOADER_FORCE_LCH_SIG" in
	""|*[!0-9]*) ;;
	*)
		FORCE_LCH_SIG_FILE="$(mktemp "$ROOT/artifacts/nq-force-lch-sig.XXXXXX")"
		printf '%s\n' "$NQ_LOADER_FORCE_LCH_SIG" > "$FORCE_LCH_SIG_FILE"
		case "$FORCE_LCH_SIG_FILE" in
			"$ROOT"/*) FORCE_LCH_SIG_SRC="${FORCE_LCH_SIG_FILE#$ROOT/}" ;;
			*)
				echo "force lch sig path must be under $ROOT: $FORCE_LCH_SIG_FILE" >&2
				exit 1
				;;
		esac
		;;
esac
case "$NQ_LOADER_FORCE_LCH" in
	""|*[!0-9-]*) ;;
	*)
		FORCE_LCH_FILE="$(mktemp "$ROOT/artifacts/nq-force-lch.XXXXXX")"
		printf '%s\n' "$NQ_LOADER_FORCE_LCH" > "$FORCE_LCH_FILE"
		case "$FORCE_LCH_FILE" in
			"$ROOT"/*) FORCE_LCH_SRC="${FORCE_LCH_FILE#$ROOT/}" ;;
			*)
				echo "force lch path must be under $ROOT: $FORCE_LCH_FILE" >&2
				exit 1
				;;
		esac
		;;
esac
if [ "$NQ_LOADER_FORCE_RW_PRIORITY" = "1" ]; then
	FORCE_RW_PRIORITY_FILE="$(mktemp "$ROOT/artifacts/nq-force-rw-priority.XXXXXX")"
	printf '1\n' > "$FORCE_RW_PRIORITY_FILE"
	case "$FORCE_RW_PRIORITY_FILE" in
		"$ROOT"/*) FORCE_RW_PRIORITY_SRC="${FORCE_RW_PRIORITY_FILE#$ROOT/}" ;;
		*)
			echo "force rw priority path must be under $ROOT: $FORCE_RW_PRIORITY_FILE" >&2
			exit 1
			;;
	esac
fi
trap 'rm -f "$EXTRA_LIST" "$MARKER_FILE" "$FORCE_LCH_SIG_FILE" "$FORCE_LCH_FILE" "$FORCE_RW_PRIORITY_FILE"' EXIT HUP INT TERM

{
	printf '%s\n' 'dir /lib 755 0 0'
	printf '%s\n' 'dir /lib/modules 755 0 0'
	printf 'file /lib/modules/omap-dma.ko %s 644 0 0\n' "$DMA_SRC"
	if [ -n "$MARKER_FILE" ] || [ -n "$FORCE_LCH_SIG_FILE" ] ||
	   [ -n "$FORCE_LCH_FILE" ] || [ -n "$FORCE_RW_PRIORITY_FILE" ]; then
		printf '%s\n' 'dir /etc 755 0 0'
	fi
	if [ "$NQ_LOADER_FORCE_DESCRIPTOR_RESIDUE" = "1" ]; then
		printf 'file /etc/nq-force-descriptor-residue %s 644 0 0\n' "$MARKER_SRC"
	fi
	if [ -n "$FORCE_LCH_SIG_FILE" ]; then
		printf 'file /etc/nq-force-lch-sig %s 644 0 0\n' "$FORCE_LCH_SIG_SRC"
	fi
	if [ -n "$FORCE_LCH_FILE" ]; then
		printf 'file /etc/nq-force-lch %s 644 0 0\n' "$FORCE_LCH_SRC"
	fi
	if [ -n "$FORCE_RW_PRIORITY_FILE" ]; then
		printf 'file /etc/nq-force-rw-priority %s 644 0 0\n' "$FORCE_RW_PRIORITY_SRC"
	fi
} > "$EXTRA_LIST"

INITRAMFS_EXTRA_LIST="$EXTRA_LIST" "$ROOT/tools/build_debian_loader_initramfs_local.sh"
