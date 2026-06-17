#!/usr/bin/env python3
"""Verify the Linux 6.6 TAS5713 Steelhead init table matches the old kernel."""

from __future__ import annotations

import ast
import os
import re
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OLD_INIT = os.path.join(
    ROOT,
    "downloads",
    "aosp-steelhead-3.0",
    "sound",
    "soc",
    "codecs",
    "tas5713_reg_init.h",
)
NEW_INIT = os.path.join(
    ROOT,
    "kernel",
    "linux-6.6.142",
    "sound",
    "soc",
    "codecs",
    "tas571x.c",
)

STRING_PATTERN = re.compile(r'"(?:\\.|[^"\\])*"')
OLD_ENTRY_PATTERN = re.compile(
    r"\{\s*\.size\s*=\s*(?P<size>\d+)\s*,\s*\.data\s*=\s*"
    r"(?P<data>(?:\"(?:\\.|[^\"\\])*\"\s*)+)\s*\}",
    re.S,
)
NEW_TABLE_PATTERN = re.compile(
    r"static const struct tas571x_raw_init steelhead_tas5713_init_sequence\[\]\s*=\s*"
    r"\{(?P<body>.*?)\n\};",
    re.S,
)
NEW_ENTRY_PATTERN = re.compile(r"TAS571X_RAW_INIT\((?P<data>.*?)\)", re.S)
HEX_PATTERN = re.compile(r"0x[0-9a-fA-F]+")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_c_string_bytes(text: str) -> bytes:
    data = bytearray()
    for match in STRING_PATTERN.finditer(text):
        data.extend(ast.literal_eval("b" + match.group(0)))
    return bytes(data)


def parse_old_table(path: str) -> list[bytes]:
    entries: list[bytes] = []
    for match in OLD_ENTRY_PATTERN.finditer(read_text(path)):
        expected_size = int(match.group("size"))
        data = parse_c_string_bytes(match.group("data"))
        if len(data) != expected_size:
            raise ValueError(
                f"{path}: old entry {len(entries)} size={expected_size} "
                f"but decoded {len(data)} bytes"
            )
        entries.append(data)
    return entries


def parse_new_table(path: str) -> list[bytes]:
    table = NEW_TABLE_PATTERN.search(read_text(path))
    if not table:
        raise ValueError(f"{path}: steelhead_tas5713_init_sequence not found")

    entries: list[bytes] = []
    for match in NEW_ENTRY_PATTERN.finditer(table.group("body")):
        values = [int(token, 16) for token in HEX_PATTERN.findall(match.group("data"))]
        entries.append(bytes(values))
    return entries


def describe(entry: bytes) -> str:
    if not entry:
        return "<empty>"
    return " ".join(f"{byte:02x}" for byte in entry)


def main() -> int:
    old_path = sys.argv[1] if len(sys.argv) > 1 else OLD_INIT
    new_path = sys.argv[2] if len(sys.argv) > 2 else NEW_INIT

    old = parse_old_table(old_path)
    new = parse_new_table(new_path)
    if old != new:
        print(
            f"tas5713 init mismatch: old={len(old)} entries new={len(new)} entries",
            file=sys.stderr,
        )
        for index, (old_entry, new_entry) in enumerate(zip(old, new)):
            if old_entry != new_entry:
                print(f"first mismatch at entry {index}", file=sys.stderr)
                print(f"  old: {describe(old_entry)}", file=sys.stderr)
                print(f"  new: {describe(new_entry)}", file=sys.stderr)
                break
        if len(old) != len(new):
            print("entry count differs", file=sys.stderr)
        return 1

    print(f"tas5713-init-parity-ok entries={len(old)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
