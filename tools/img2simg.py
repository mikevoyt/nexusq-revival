#!/usr/bin/env python3
import argparse
import os
import struct
from pathlib import Path


SPARSE_MAGIC = 0xED26FF3A
RAW = 0xCAC1
DONT_CARE = 0xCAC3
FILE_HDR_SZ = 28
CHUNK_HDR_SZ = 12
DEFAULT_BLOCK_SIZE = 4096
MAX_RAW_BLOCKS = 4096


def is_zero(block):
    return not block or block == b"\0" * len(block)


def scan_chunks(path, block_size):
    size = path.stat().st_size
    if size % block_size:
        raise SystemExit(f"{path} size is not a multiple of {block_size}")

    chunks = []
    with path.open("rb") as src:
        block_index = 0
        pending_type = None
        pending_start = 0
        pending_blocks = 0

        while True:
            block = src.read(block_size)
            if not block:
                break
            chunk_type = DONT_CARE if is_zero(block) else RAW
            if (
                pending_type == chunk_type
                and pending_blocks < MAX_RAW_BLOCKS
                and (chunk_type == DONT_CARE or pending_blocks < MAX_RAW_BLOCKS)
            ):
                pending_blocks += 1
            else:
                if pending_type is not None:
                    chunks.append((pending_type, pending_start, pending_blocks))
                pending_type = chunk_type
                pending_start = block_index
                pending_blocks = 1
            block_index += 1

        if pending_type is not None:
            chunks.append((pending_type, pending_start, pending_blocks))

    return chunks, size // block_size


def write_sparse(src_path, dest_path, block_size):
    chunks, total_blocks = scan_chunks(src_path, block_size)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with src_path.open("rb") as src, dest_path.open("wb") as dest:
        dest.write(
            struct.pack(
                "<IHHHHIIII",
                SPARSE_MAGIC,
                1,
                0,
                FILE_HDR_SZ,
                CHUNK_HDR_SZ,
                block_size,
                total_blocks,
                len(chunks),
                0,
            )
        )

        for chunk_type, start, blocks in chunks:
            if chunk_type == DONT_CARE:
                dest.write(struct.pack("<HHII", DONT_CARE, 0, blocks, CHUNK_HDR_SZ))
                continue

            byte_count = blocks * block_size
            dest.write(
                struct.pack(
                    "<HHII",
                    RAW,
                    0,
                    blocks,
                    CHUNK_HDR_SZ + byte_count,
                )
            )
            src.seek(start * block_size)
            remaining = byte_count
            while remaining:
                data = src.read(min(1024 * 1024, remaining))
                if not data:
                    raise RuntimeError("unexpected EOF while copying raw chunk")
                dest.write(data)
                remaining -= len(data)

    return chunks, total_blocks


def main():
    parser = argparse.ArgumentParser(description="Convert a raw image to Android sparse image format.")
    parser.add_argument("src", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    args = parser.parse_args()

    chunks, total_blocks = write_sparse(args.src, args.dest, args.block_size)
    raw_blocks = sum(blocks for typ, _, blocks in chunks if typ == RAW)
    dontcare_blocks = sum(blocks for typ, _, blocks in chunks if typ == DONT_CARE)
    print(
        f"{args.dest}: {len(chunks)} chunks, "
        f"{total_blocks} output blocks, "
        f"{raw_blocks} raw blocks, {dontcare_blocks} sparse blocks, "
        f"{os.path.getsize(args.dest)} bytes"
    )


if __name__ == "__main__":
    main()
