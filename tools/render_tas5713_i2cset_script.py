#!/usr/bin/env python3
"""Render the TAS5713 raw init table as a remote i2ctransfer playback script."""

from __future__ import annotations

import re
import shlex
import sys


def parse_raw_commands(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    commands: list[list[str]] = []
    for match in re.finditer(r"\bRAW\((.*?)\)", text, re.S):
        values = re.findall(r"0x[0-9a-fA-F]+", match.group(1))
        if len(values) < 2:
            continue
        commands.append([v.lower() for v in values])

    if not commands:
        raise SystemExit(f"no RAW commands found in {path}")
    return commands


def q(value: str) -> str:
    return shlex.quote(value)


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: render_tas5713_i2cset_script.py INIT_C REMOTE_WAV "
            "APLAY_EXTRA_ARGS LIVE_I2C_DELAY"
        )

    init_c, remote_wav, aplay_extra_args, live_i2c_delay = sys.argv[1:]
    commands = parse_raw_commands(init_c)

    print("set -eu")
    print(f"remote_wav={q(remote_wav)}")
    print(f"aplay_extra_args={q(aplay_extra_args)}")
    print(f"live_i2c_delay={q(live_i2c_delay)}")
    print("bus=3")
    print("chip=0x1b")
    print('echo "starting aplay: $remote_wav"')
    print('aplay -D hw:0,0 -q $aplay_extra_args "$remote_wav" &')
    print("pid=$!")
    print('echo "aplay_pid=$pid"')
    print('sleep "$live_i2c_delay"')
    print('echo "live_i2c_begin=$(date +%s.%N)"')
    print('mvol="$(i2cget -f -y "$bus" "$chip" 0x07 2>/dev/null || echo 0xff)"')
    print('ch1="$(i2cget -f -y "$bus" "$chip" 0x08 2>/dev/null || echo 0x30)"')
    print('ch2="$(i2cget -f -y "$bus" "$chip" 0x09 2>/dev/null || echo 0x30)"')
    print('mute="$(i2cget -f -y "$bus" "$chip" 0x06 2>/dev/null || echo 0x00)"')
    print('echo "preserve mvol=$mvol ch1=$ch1 ch2=$ch2 mute=$mute"')

    for values in commands:
        print(f'i2ctransfer -f -y "$bus" w{len(values)}@"$chip" {" ".join(values)}')

    print('i2ctransfer -f -y "$bus" w2@"$chip" 0x05 0x00')
    print('i2ctransfer -f -y "$bus" w2@"$chip" 0x07 "$mvol"')
    print('i2ctransfer -f -y "$bus" w2@"$chip" 0x08 "$ch1"')
    print('i2ctransfer -f -y "$bus" w2@"$chip" 0x09 "$ch2"')
    print('i2ctransfer -f -y "$bus" w2@"$chip" 0x06 "$mute"')
    print('i2ctransfer -f -y "$bus" w2@"$chip" 0x02 0x00')
    print('echo "live_i2c_done=$(date +%s.%N)"')
    print("wait $pid")
    print('echo "aplay_done=$?"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
