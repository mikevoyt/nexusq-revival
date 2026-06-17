#!/usr/bin/env python3
"""Run a shell script on the Nexus Q serial console.

The Linux 3.0 rescue image exposes a root shell on the USB CDC serial port but
does not always expose USB networking on macOS. This helper uploads a small
script through the serial shell and prints the captured console output.
"""

from __future__ import annotations

import argparse
import os
import re
import select
import sys
import termios
import time


DEFAULT_DEVICE = "/dev/cu.usbmodemAW1S122505241"
PROMPT_RE = re.compile(rb"(?:^|\r|\n)/ # ")


def configure_serial(fd: int, baud: int) -> None:
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = attrs[2] | termios.CLOCAL | termios.CREAD
    attrs[3] = 0
    attrs[4] = baud
    attrs[5] = baud
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def read_available(fd: int, timeout: float) -> bytes:
    out = bytearray()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        remaining = max(0.0, end - time.monotonic())
        ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if chunk:
            out.extend(chunk)
    return bytes(out)


def read_until_prompt(fd: int, timeout: float) -> bytes:
    out = bytearray()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        remaining = max(0.0, end - time.monotonic())
        ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not chunk:
            continue
        out.extend(chunk)
        if PROMPT_RE.search(out):
            return bytes(out)
    raise TimeoutError("serial prompt timeout")


def read_until_rc_and_prompt(fd: int, timeout: float) -> bytes:
    out = bytearray()
    end = time.monotonic() + timeout
    rc_seen = False
    while time.monotonic() < end:
        remaining = max(0.0, end - time.monotonic())
        ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not chunk:
            continue
        out.extend(chunk)
        if re.search(rb"__NQ_SERIAL_RC__\d+", out):
            rc_seen = True
        if rc_seen and PROMPT_RE.search(out):
            return bytes(out)
    raise TimeoutError("serial command completion timeout")


def send_line(fd: int, line: str, delay: float) -> None:
    os.write(fd, line.encode("utf-8") + b"\r\n")
    if delay:
        time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--baud", type=int, default=termios.B115200)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--line-delay", type=float, default=0.002)
    parser.add_argument("command", nargs="*")
    args = parser.parse_args()

    script = " ".join(args.command) if args.command else sys.stdin.read()
    if not script.strip():
        parser.error("no command or stdin script supplied")

    fd = os.open(args.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure_serial(fd, args.baud)
        read_available(fd, 0.2)
        os.write(fd, b"\r\n")
        read_until_prompt(fd, args.timeout)

        marker = "__NQ_SERIAL_EOF_6BE8CB1C__"
        send_line(fd, f"cat >/tmp/nq_serial_exec.sh <<'{marker}'", args.line_delay)
        for line in script.splitlines():
            send_line(fd, line, args.line_delay)
        send_line(fd, marker, args.line_delay)
        read_available(fd, 0.2)
        send_line(fd, "sh /tmp/nq_serial_exec.sh; rc=$?; echo __NQ_SERIAL_RC__$rc; rm -f /tmp/nq_serial_exec.sh", args.line_delay)

        out = read_until_rc_and_prompt(fd, args.timeout)
        sys.stdout.write(out.decode("utf-8", "replace"))
        match = re.search(rb"__NQ_SERIAL_RC__(\d+)", out)
        return int(match.group(1)) if match else 1
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
