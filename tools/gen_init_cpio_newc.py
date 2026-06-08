#!/usr/bin/env python3
import os
import stat
import sys
from pathlib import Path


S_IFREG = 0o100000
S_IFDIR = 0o040000
S_IFLNK = 0o120000
S_IFCHR = 0o020000


def align4(out):
    pad = (-out.tell()) % 4
    if pad:
        out.write(b"\0" * pad)


def write_entry(out, ino, name, mode, uid, gid, data=b"", rdevmajor=0, rdevminor=0):
    namesize = len(name.encode("utf-8")) + 1
    fields = [
        ino,
        mode,
        uid,
        gid,
        1,
        0,
        len(data),
        0,
        0,
        rdevmajor,
        rdevminor,
        namesize,
        0,
    ]
    header = "070701" + "".join(f"{value:08x}" for value in fields)
    out.write(header.encode("ascii"))
    out.write(name.encode("utf-8") + b"\0")
    align4(out)
    out.write(data)
    align4(out)


def parse_mode(value, file_type):
    return file_type | int(value, 8)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: gen_init_cpio_newc.py INITRAMFS_LIST ROOT")

    initramfs_list = Path(sys.argv[1])
    root = Path(sys.argv[2])
    ino = 1

    for raw_line in initramfs_list.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        entry_type = parts[0]

        if entry_type == "dir":
            _, name, mode, uid, gid = parts
            write_entry(
                sys.stdout.buffer,
                ino,
                name.lstrip("/"),
                parse_mode(mode, S_IFDIR),
                int(uid),
                int(gid),
            )
        elif entry_type == "file":
            _, name, src, mode, uid, gid = parts
            data = (root / src).read_bytes()
            write_entry(
                sys.stdout.buffer,
                ino,
                name.lstrip("/"),
                parse_mode(mode, S_IFREG),
                int(uid),
                int(gid),
                data,
            )
        elif entry_type == "slink":
            _, name, target, mode, uid, gid = parts
            write_entry(
                sys.stdout.buffer,
                ino,
                name.lstrip("/"),
                parse_mode(mode, S_IFLNK),
                int(uid),
                int(gid),
                target.encode("utf-8"),
            )
        elif entry_type == "nod":
            _, name, mode, uid, gid, dev_type, major, minor = parts
            if dev_type != "c":
                raise SystemExit(f"unsupported device node type: {dev_type}")
            write_entry(
                sys.stdout.buffer,
                ino,
                name.lstrip("/"),
                parse_mode(mode, S_IFCHR),
                int(uid),
                int(gid),
                rdevmajor=int(major),
                rdevminor=int(minor),
            )
        else:
            raise SystemExit(f"unsupported initramfs.list entry: {entry_type}")

        ino += 1

    write_entry(sys.stdout.buffer, ino, "TRAILER!!!", 0, 0, 0)


if __name__ == "__main__":
    main()
