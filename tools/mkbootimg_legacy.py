#!/usr/bin/env python3
import argparse
import hashlib
import pathlib
import struct


def read_file(path):
    return pathlib.Path(path).read_bytes() if path else b""


def pad_length(size, page_size):
    rem = size % page_size
    return 0 if rem == 0 else page_size - rem


def padded_write(out, blob, page_size):
    out.write(blob)
    out.write(b"\0" * pad_length(len(blob), page_size))


def fixed_bytes(value, length, field):
    data = value.encode("ascii")
    if len(data) > length:
        raise SystemExit(f"{field} is too long: {len(data)} > {length}")
    return data + b"\0" * (length - len(data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel", required=True)
    parser.add_argument("--ramdisk", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--second")
    parser.add_argument("--kernel-addr", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--ramdisk-addr", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--second-addr", type=lambda x: int(x, 0), default=0)
    parser.add_argument("--tags-addr", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--page-size", type=int, required=True)
    parser.add_argument("--cmdline", default="")
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    kernel = read_file(args.kernel)
    ramdisk = read_file(args.ramdisk)
    second = read_file(args.second)

    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, second):
        sha.update(blob)
        sha.update(struct.pack("<I", len(blob)))
    image_id = sha.digest() + b"\0" * (32 - hashlib.sha1().digest_size)

    header = b"".join(
        [
            b"ANDROID!",
            struct.pack(
                "<10I",
                len(kernel),
                args.kernel_addr,
                len(ramdisk),
                args.ramdisk_addr,
                len(second),
                args.second_addr,
                args.tags_addr,
                args.page_size,
                0,
                0,
            ),
            fixed_bytes(args.name, 16, "name"),
            fixed_bytes(args.cmdline, 512, "cmdline"),
            image_id,
        ]
    )

    with open(args.output, "wb") as out:
        padded_write(out, header, args.page_size)
        padded_write(out, kernel, args.page_size)
        padded_write(out, ramdisk, args.page_size)
        if second:
            padded_write(out, second, args.page_size)


if __name__ == "__main__":
    main()
