#!/usr/bin/env python3
"""Compare TAS5713 debug register dumps.

The old 3.0 driver exposes a debugfs dump. The 6.6 port can read the same
registers with i2ctransfer. This helper normalizes both formats to
register-address -> hex-word list so the audio bring-up notes can cite a
repeatable diff.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REG_LINE = re.compile(r"\[([0-9a-fA-F]{2})\]\s*:\s*([0-9a-fA-FxX ]+)$")
HEX_WORD = re.compile(r"(?:0x)?([0-9a-fA-F]+)")


def parse_dump(path: Path) -> dict[int, tuple[str, ...]]:
    regs: dict[int, tuple[str, ...]] = {}
    for line in path.read_text(errors="replace").splitlines():
        match = REG_LINE.search(line.strip())
        if not match:
            continue
        reg = int(match.group(1), 16)
        words = tuple(word.lower().zfill(2) for word in HEX_WORD.findall(match.group(2)))
        if words:
            regs[reg] = words
    return regs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path, help="Known-good TAS dump")
    parser.add_argument("actual", type=Path, help="New TAS dump")
    args = parser.parse_args()

    expected = parse_dump(args.expected)
    actual = parse_dump(args.actual)
    all_regs = sorted(set(expected) | set(actual))

    mismatches: list[str] = []
    missing_expected: list[int] = []
    missing_actual: list[int] = []

    for reg in all_regs:
        if reg not in expected:
            missing_expected.append(reg)
            continue
        if reg not in actual:
            missing_actual.append(reg)
            continue
        if expected[reg] != actual[reg]:
            mismatches.append(
                f"0x{reg:02x}: expected {' '.join(expected[reg])} "
                f"actual {' '.join(actual[reg])}"
            )

    print(f"expected_regs={len(expected)} actual_regs={len(actual)}")
    if missing_expected:
        print("missing_from_expected=" + ",".join(f"0x{reg:02x}" for reg in missing_expected))
    if missing_actual:
        print("missing_from_actual=" + ",".join(f"0x{reg:02x}" for reg in missing_actual))
    if mismatches:
        print(f"mismatches={len(mismatches)}")
        for line in mismatches:
            print(line)
        return 1

    print("tas5713-dumps-match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
