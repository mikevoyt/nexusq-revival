#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUT_CPIO="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio"
OUT_GZ="$ROOT/artifacts/nexusq-debian-loader-initramfs.cpio.gz"

mkdir -p "$ROOT/artifacts"

python3 "$ROOT/tools/gen_init_cpio_newc.py" \
	"$ROOT/initramfs/debian-loader.list" \
	"$ROOT" > "$OUT_CPIO"

gzip -9 -n -c "$OUT_CPIO" > "$OUT_GZ"
ls -l "$OUT_CPIO" "$OUT_GZ"
