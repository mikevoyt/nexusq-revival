#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import run_wifi_serial_test as wifi


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = ROOT / "artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-debian.img"
DEFAULT_ROOTFS = ROOT / "artifacts/debian-trixie-armhf-rootfs.ext4"
DEFAULT_SSH_KEY = ROOT / ".secrets/nexusq-ssh-test/id_ed25519"


def fastboot(args):
    proc = subprocess.run(["fastboot", *args], check=False)
    if proc.returncode != 0:
        raise SystemExit(f"fastboot {' '.join(args)} failed: {proc.returncode}")


def main():
    parser = argparse.ArgumentParser(description="Boot the Nexus Q Debian rootfs and verify Wi-Fi SSH.")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--rootfs", default=str(DEFAULT_ROOTFS))
    parser.add_argument("--flash-userdata", action="store_true")
    parser.add_argument("--ssid", default=os.environ.get("NQ_WIFI_SSID", ""))
    parser.add_argument("--keychain-service", default=os.environ.get("NQ_WIFI_KEYCHAIN_SERVICE", "nexusq-wifi"))
    parser.add_argument("--keychain-account", default=os.environ.get("NQ_WIFI_KEYCHAIN_ACCOUNT"))
    parser.add_argument("--ssh-key", default=str(DEFAULT_SSH_KEY))
    parser.add_argument("--no-ssh-test", action="store_true")
    parser.add_argument(
        "--ssh-command",
        default="uname -a; cat /etc/debian_version; ip addr show wlan0",
        help="command to run on the target after Debian Wi-Fi SSH is up",
    )
    parser.add_argument("--no-boot", action="store_true", help="use an already-booted serial shell")
    parser.add_argument("--boot-timeout", type=int, default=150)
    parser.add_argument("--test-timeout", type=int, default=180)
    parser.add_argument("--ssh-timeout", type=int, default=35)
    args = parser.parse_args()
    if not args.ssid:
        raise SystemExit("missing Wi-Fi SSID; pass --ssid or set NQ_WIFI_SSID")
    if not args.keychain_account:
        args.keychain_account = args.ssid

    image = Path(args.image)
    rootfs = Path(args.rootfs)
    if not args.no_boot and not image.exists():
        raise SystemExit(f"missing image: {image}")
    if args.flash_userdata and not rootfs.exists():
        raise SystemExit(f"missing rootfs: {rootfs}")

    if not args.no_boot:
        fb = wifi.wait_fastboot(5)
        if not fb:
            raise SystemExit("fastboot device not visible")
        print(fb)
        if args.flash_userdata:
            fastboot(["flash", "userdata", str(rootfs)])
        fastboot(["boot", str(image)])

    port, fd = wifi.wait_shell(args.boot_timeout)
    if not port:
        fb = wifi.wait_fastboot(10)
        if fb:
            print(f"fastboot returned before Debian shell:\n{fb}")
        raise SystemExit("serial shell did not become responsive")
    print(f"serial: {port}")

    password = wifi.keychain_password(args.keychain_service, args.keychain_account)
    conf = wifi.make_wpa_conf(args.ssid, password)
    seed_hex = os.urandom(64).hex()
    ssh_key = None
    ssh_pub = None
    if not args.no_ssh_test:
        ssh_key, ssh_pub = wifi.ensure_ssh_key(args.ssh_key)
        authorized_keys = ssh_pub.read_text()

    try:
        wifi.write(fd, b"stty -echo 2>/dev/null || true\r\n")

        seed_marker = f"__NQ_DEBIAN_RNG_READY_{int(time.time() * 1000)}__".encode()
        wifi.write(fd, b"cat >/tmp/rng.seed <<'__NQ_RNG_SEED__'\r\n")
        wifi.write(fd, seed_hex.encode("ascii"))
        wifi.write(
            fd,
            b"\r\n__NQ_RNG_SEED__\r\nchmod 600 /tmp/rng.seed\r\n"
            + wifi.marker_command(seed_marker)
            + b"\r\n",
        )
        wifi.require_marker(wifi.read_until(fd, [seed_marker], 20), seed_marker, "rng seed upload")

        if ssh_pub is not None:
            ssh_marker = f"__NQ_DEBIAN_AUTHKEY_READY_{int(time.time() * 1000)}__".encode()
            wifi.write(fd, b"mkdir -p /run/nexusq\r\ncat >/run/nexusq/authorized_keys <<'__NQ_AUTHORIZED_KEYS__'\r\n")
            wifi.write(fd, authorized_keys.encode("utf-8"))
            wifi.write(
                fd,
                b"__NQ_AUTHORIZED_KEYS__\r\nchmod 600 /run/nexusq/authorized_keys\r\n"
                + wifi.marker_command(ssh_marker)
                + b"\r\n",
            )
            wifi.require_marker(wifi.read_until(fd, [ssh_marker], 20), ssh_marker, "ssh authorized_keys upload")

        config_marker = f"__NQ_DEBIAN_CONFIG_READY_{int(time.time() * 1000)}__".encode()
        wifi.write(fd, b"mkdir -p /run/nexusq\r\ncat >/run/nexusq/wpa_supplicant.conf <<'__NQ_WIFI_CONF__'\r\n")
        wifi.write(fd, conf.encode("utf-8"))
        wifi.write(
            fd,
            b"__NQ_WIFI_CONF__\r\nchmod 600 /run/nexusq/wpa_supplicant.conf\r\n"
            + wifi.marker_command(config_marker)
            + b"\r\n",
        )
        wifi.require_marker(wifi.read_until(fd, [config_marker], 20), config_marker, "wifi config upload")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = ROOT / "build" / f"live-debian-wifi-network-{stamp}.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        done_marker = f"__NQ_DEBIAN_LOG_DONE_{int(time.time() * 1000)}__".encode()
        wifi.write(
            fd,
            b"/sbin/nq-autoreboot-status; /sbin/nq-start-network; rc=$?; "
            b"echo __NQ_DEBIAN_TEST_DONE__:$rc; "
            b"cat /etc/debian_version 2>/dev/null; "
            b"cat /run/nexusq-network.log 2>/dev/null; "
            + wifi.marker_command(done_marker)
            + b"\r\n",
        )
        data = wifi.read_until(fd, [done_marker], args.test_timeout, print_output=True)
        log_text = data.decode("utf-8", "replace")
        log_path.write_text(log_text)
        print(f"\nlog: {log_path}")

        if ssh_key is not None:
            ip = wifi.extract_ipv4(log_text)
            if not ip:
                raise SystemExit("Debian network test completed but no DHCP IPv4 address was found for SSH")
            print(f"ssh target: root@{ip}")
            ssh_proc = subprocess.run(
                [
                    "ssh",
                    "-i",
                    str(ssh_key),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=12",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    f"root@{ip}",
                    args.ssh_command,
                ],
                check=False,
                text=True,
                capture_output=True,
                timeout=args.ssh_timeout,
            )
            ssh_log = ROOT / "build" / f"live-debian-wifi-ssh-{stamp}.txt"
            ssh_log.write_text(
                "stdout:\n"
                + ssh_proc.stdout
                + "\nstderr:\n"
                + ssh_proc.stderr
                + f"\nreturncode: {ssh_proc.returncode}\n"
            )
            print(f"ssh log: {ssh_log}")
            if ssh_proc.returncode != 0:
                sys.stdout.write(ssh_proc.stdout)
                sys.stderr.write(ssh_proc.stderr)
                raise SystemExit(f"ssh check failed: {ssh_proc.returncode}")
            sys.stdout.write(ssh_proc.stdout)
            sys.stdout.flush()
    finally:
        if fd is not None:
            wifi.write(fd, b"\r\nsync\r\n/sbin/nq-reboot-fastboot\r\n")
            time.sleep(1)
            os.close(fd)

    fb = wifi.wait_fastboot(120)
    if fb:
        print(f"fastboot returned:\n{fb}")
        return 0
    print("fastboot did not return within timeout", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
