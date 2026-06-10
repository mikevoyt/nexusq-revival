#!/usr/bin/env python3
import argparse
import os
import shlex
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
        "--persist-provisioning",
        action="store_true",
        help="install uploaded Wi-Fi, SSH, and RNG seed files into persistent /etc/nexusq state",
    )
    parser.add_argument(
        "--cancel-autoreboot",
        action="store_true",
        help="cancel the target's safety return-to-fastboot timer during provisioning",
    )
    parser.add_argument(
        "--leave-running",
        action="store_true",
        help="leave the target running instead of asking it to return to fastboot at the end",
    )
    parser.add_argument(
        "--ssh-command",
        default="uname -a; cat /etc/debian_version; ip addr show wlan0",
        help="command to run on the target after Debian Wi-Fi SSH is up",
    )
    parser.add_argument(
        "--enable-squeezelite",
        action="store_true",
        help="upload and start an opt-in Music Assistant Squeezelite player config",
    )
    parser.add_argument(
        "--squeezelite-name",
        default=os.environ.get("NQ_SQUEEZELITE_NAME", "Nexus Q"),
        help="Squeezelite player name shown in Music Assistant",
    )
    parser.add_argument(
        "--squeezelite-server",
        default=os.environ.get("NQ_SQUEEZELITE_SERVER", ""),
        help="optional Music Assistant server host[:port]; omit for SlimProto discovery",
    )
    parser.add_argument(
        "--squeezelite-output",
        default=os.environ.get("NQ_SQUEEZELITE_OUTPUT", "hw:0,0"),
        help="ALSA output device for Squeezelite",
    )
    parser.add_argument(
        "--squeezelite-rates",
        default=os.environ.get("NQ_SQUEEZELITE_RATES", "48000"),
        help="comma-separated sample rates advertised by Squeezelite",
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
    if args.leave_running:
        args.cancel_autoreboot = True

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
            b"mkdir -p /run/nexusq\r\ncp /tmp/rng.seed /run/nexusq/rng.seed\r\nchmod 600 /run/nexusq/rng.seed\r\n"
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

        if args.enable_squeezelite:
            player_env = "".join(
                [
                    "NQ_SQUEEZELITE_ENABLE=1\n",
                    f"NQ_SQUEEZELITE_NAME={shlex.quote(args.squeezelite_name)}\n",
                    f"NQ_SQUEEZELITE_OUTPUT={shlex.quote(args.squeezelite_output)}\n",
                    f"NQ_SQUEEZELITE_RATES={shlex.quote(args.squeezelite_rates)}\n",
                ]
            )
            if args.squeezelite_server:
                player_env += f"NQ_SQUEEZELITE_SERVER={shlex.quote(args.squeezelite_server)}\n"
            player_marker = f"__NQ_DEBIAN_PLAYER_CONFIG_READY_{int(time.time() * 1000)}__".encode()
            wifi.write(fd, b"mkdir -p /run/nexusq\r\ncat >/run/nexusq/squeezelite.env <<'__NQ_SQUEEZELITE_ENV__'\r\n")
            wifi.write(fd, player_env.encode("utf-8"))
            wifi.write(
                fd,
                b"__NQ_SQUEEZELITE_ENV__\r\nchmod 644 /run/nexusq/squeezelite.env\r\n"
                + wifi.marker_command(player_marker)
                + b"\r\n",
            )
            wifi.require_marker(
                wifi.read_until(fd, [player_marker], 20),
                player_marker,
                "squeezelite config upload",
            )

        if args.cancel_autoreboot and not args.persist_provisioning:
            cancel_marker = f"__NQ_DEBIAN_CANCEL_AUTOREBOOT_{int(time.time() * 1000)}__".encode()
            wifi.write(
                fd,
                b"/sbin/nq-autoreboot-cancel; rc=$?; "
                + wifi.marker_command(cancel_marker, "rc")
                + b"\r\n",
            )
            cancel_data = wifi.read_until(fd, [cancel_marker], 20, print_output=True)
            wifi.require_marker(cancel_data, cancel_marker, "autoreboot cancellation")
            if cancel_marker + b":0" not in cancel_data:
                raise SystemExit("autoreboot cancellation failed")

        if args.persist_provisioning:
            provision_marker = f"__NQ_DEBIAN_PROVISION_READY_{int(time.time() * 1000)}__".encode()
            provision_cmd = (
                "/sbin/nq-provision "
                "--wifi /run/nexusq/wpa_supplicant.conf "
                "--rng-seed /run/nexusq/rng.seed "
            )
            if ssh_pub is not None:
                provision_cmd += "--authorized-keys /run/nexusq/authorized_keys "
            if args.enable_squeezelite:
                provision_cmd += "--squeezelite /run/nexusq/squeezelite.env "
            if args.cancel_autoreboot:
                provision_cmd += "--cancel-autoreboot "
            provision_cmd += "--status"
            wifi.write(
                fd,
                provision_cmd.encode("ascii")
                + b"; rc=$?; "
                + wifi.marker_command(provision_marker, "rc")
                + b"\r\n",
            )
            provision_data = wifi.read_until(fd, [provision_marker], 30, print_output=True)
            wifi.require_marker(provision_data, provision_marker, "persistent provisioning")
            if provision_marker + b":0" not in provision_data:
                raise SystemExit("persistent provisioning failed")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = ROOT / "build" / f"live-debian-wifi-network-{stamp}.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        done_marker = f"__NQ_DEBIAN_LOG_DONE_{int(time.time() * 1000)}__".encode()
        wifi.write(
            fd,
            b"/sbin/nq-autoreboot-status; /sbin/nq-start-network; rc=$?; "
            + (
                b"/sbin/nq-start-squeezelite; /sbin/nq-player-status; "
                if args.enable_squeezelite
                else b""
            )
            + b"echo __NQ_DEBIAN_TEST_DONE__:$rc; "
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
            if args.leave_running:
                wifi.write(fd, b"\r\nsync\r\n")
            else:
                wifi.write(fd, b"\r\nsync\r\n/sbin/nq-reboot-fastboot\r\n")
            time.sleep(1)
            os.close(fd)

    if args.leave_running:
        print("left target running by request")
        return 0

    fb = wifi.wait_fastboot(120)
    if fb:
        print(f"fastboot returned:\n{fb}")
        return 0
    print("fastboot did not return within timeout", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
