#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT_CPIO="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio"
OUT_GZ="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz"

mkdir -p "$ROOT/artifacts"

INITRAMFS_LIST="$ROOT/initramfs/debian-loader.list"
TMP_LIST=""
if [ -n "${INITRAMFS_EXTRA_LIST:-}" ]; then
	TMP_LIST="$(mktemp "$ROOT/artifacts/debian-loader.list.XXXXXX")"
	trap 'rm -f "$TMP_LIST"' EXIT HUP INT TERM
	sed -n 'p' "$ROOT/initramfs/debian-loader.list" > "$TMP_LIST"
	printf '\n' >> "$TMP_LIST"
	sed -n 'p' "$INITRAMFS_EXTRA_LIST" >> "$TMP_LIST"
	INITRAMFS_LIST="$TMP_LIST"
fi

python3 "$ROOT/tools/gen_init_cpio_newc.py" \
	"$INITRAMFS_LIST" \
	"$ROOT" > "$OUT_CPIO"

gzip -9 -n -c "$OUT_CPIO" > "$OUT_GZ"
ls -l "$OUT_CPIO" "$OUT_GZ"
