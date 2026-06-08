#!/usr/bin/env python3
import argparse
import glob
import os
import re
import select
import subprocess
import sys
import termios
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = ROOT / "artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-test.img"
DEFAULT_SSH_KEY = ROOT / ".secrets/nexusq-ssh-test/id_ed25519"


def shell_quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"


def marker_command(marker, status_var=None):
    text = marker.decode("ascii")
    split = max(1, len(text) // 2)
    first = text[:split]
    second = text[split:]
    if status_var:
        printf = f"printf '%s%s:%s\\n' \"$__nq_m1\" \"$__nq_m2\" \"${status_var}\""
    else:
        printf = "printf '%s%s\\n' \"$__nq_m1\" \"$__nq_m2\""
    return (
        f"__nq_m1={shell_quote(first)}; "
        f"__nq_m2={shell_quote(second)}; "
        f"{printf}"
    ).encode("ascii")


def run(args, **kwargs):
    return subprocess.run(args, check=False, text=True, capture_output=True, **kwargs)


def fastboot_devices():
    proc = run(["fastboot", "devices", "-l"])
    return proc.stdout.strip()


def wait_fastboot(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = fastboot_devices()
        if out:
            return out
        time.sleep(1)
    return ""


def wait_serial(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ports = sorted(glob.glob("/dev/cu.usbmodem*"))
        if ports:
            return ports[0]
        time.sleep(1)
    return None


def wait_shell(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for port in sorted(glob.glob("/dev/cu.usbmodem*")):
            try:
                fd = open_serial(port)
            except OSError:
                continue
            try:
                try:
                    os.read(fd, 65536)
                except BlockingIOError:
                    pass
                marker = f"__NQ_READY_{int(time.time() * 1000)}__".encode()
                write(fd, b"\x03\r\n" + marker_command(marker) + b"\r\n")
                data = read_until(fd, [marker], 2)
                if marker in data:
                    return port, fd
            except OSError:
                pass
            os.close(fd)
        time.sleep(1)
    return None, None


def open_serial(port):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = attrs[2] | termios.CLOCAL | termios.CREAD
    attrs[3] = 0
    attrs[4] = termios.B115200
    attrs[5] = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def read_until(fd, markers, timeout, print_output=False):
    deadline = time.time() + timeout
    data = b""
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.25)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not chunk:
            continue
        data += chunk
        if print_output:
            sys.stdout.write(chunk.decode("utf-8", "replace"))
            sys.stdout.flush()
        if any(marker in data for marker in markers):
            break
    return data


def require_marker(data, marker, label):
    if marker not in data:
        raise SystemExit(f"serial shell did not confirm {label}")


def write(fd, payload):
    written = 0
    while written < len(payload):
        _, ready, _ = select.select([], [fd], [], 1)
        if not ready:
            continue
        try:
            n = os.write(fd, payload[written:])
        except BlockingIOError:
            continue
        if n <= 0:
            raise OSError("serial write made no progress")
        written += n


def keychain_password(service, account):
    proc = run(["security", "find-generic-password", "-s", service, "-a", account, "-w"])
    if proc.returncode != 0:
        raise SystemExit(f"could not read Keychain item service={service!r} account={account!r}")
    return proc.stdout.rstrip("\n")


def wpa_quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def make_wpa_conf(ssid, password):
    return "\n".join(
        [
            "ctrl_interface=DIR=/run/wpa_supplicant",
            "update_config=0",
            "ap_scan=1",
            "p2p_disabled=1",
            "country=US",
            "network={",
            f"\tssid={wpa_quote(ssid)}",
            f"\tpsk={wpa_quote(password)}",
            "}",
            "",
        ]
    )


def ensure_ssh_key(path):
    path = Path(path)
    pub = Path(str(path) + ".pub")
    if path.exists() and pub.exists():
        return path, pub
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "nexusq-test", "-f", str(path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ssh-keygen failed: {proc.stderr.strip()}")
    os.chmod(path, 0o600)
    return path, pub


def extract_ipv4(log_text):
    patterns = [
        r"lease of ([0-9]+(?:\.[0-9]+){3}) obtained",
        r"inet addr:([0-9]+(?:\.[0-9]+){3})",
        r"inet ([0-9]+(?:\.[0-9]+){3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, log_text)
        if match:
            return match.group(1)
    return None


def run_ssh_check(ip, key_path, timeout):
    proc = subprocess.run(
        [
            "ssh",
            "-i",
            str(key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=12",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"root@{ip}",
            "uname -a; ifconfig wlan0",
        ],
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return proc


def main():
    parser = argparse.ArgumentParser(description="Boot the Nexus Q Wi-Fi image and run a secret-safe serial Wi-Fi test.")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--ssid", default=os.environ.get("NQ_WIFI_SSID", ""))
    parser.add_argument("--keychain-service", default=os.environ.get("NQ_WIFI_KEYCHAIN_SERVICE", "nexusq-wifi"))
    parser.add_argument("--keychain-account", default=os.environ.get("NQ_WIFI_KEYCHAIN_ACCOUNT"))
    parser.add_argument("--ssh-key", default=str(DEFAULT_SSH_KEY))
    parser.add_argument("--no-ssh-test", action="store_true")
    parser.add_argument("--no-boot", action="store_true", help="use an already-booted serial shell")
    parser.add_argument("--boot-timeout", type=int, default=90)
    parser.add_argument("--test-timeout", type=int, default=160)
    parser.add_argument("--ssh-timeout", type=int, default=30)
    args = parser.parse_args()
    if not args.ssid:
        raise SystemExit("missing Wi-Fi SSID; pass --ssid or set NQ_WIFI_SSID")
    if not args.keychain_account:
        args.keychain_account = args.ssid

    image = Path(args.image)
    if not args.no_boot and not image.exists():
        raise SystemExit(f"missing image: {image}")

    if not args.no_boot:
        fb = wait_fastboot(5)
        if not fb:
            raise SystemExit("fastboot device not visible")
        print(fb)
        proc = subprocess.run(["fastboot", "boot", str(image)], check=False)
        if proc.returncode != 0:
            raise SystemExit(f"fastboot boot failed: {proc.returncode}")

    port, fd = wait_shell(args.boot_timeout)
    if not port:
        raise SystemExit("serial shell did not become responsive")
    print(f"serial: {port}")

    password = keychain_password(args.keychain_service, args.keychain_account)
    conf = make_wpa_conf(args.ssid, password)
    seed_hex = os.urandom(64).hex()
    ssh_key = None
    ssh_pub = None
    if not args.no_ssh_test:
        ssh_key, ssh_pub = ensure_ssh_key(args.ssh_key)
        authorized_keys = ssh_pub.read_text()

    try:
        write(fd, b"stty -echo 2>/dev/null || true\r\n")

        seed_marker = f"__NQ_RNG_READY_{int(time.time() * 1000)}__".encode()
        write(fd, b"cat >/tmp/rng.seed <<'__NQ_RNG_SEED__'\r\n")
        write(fd, seed_hex.encode("ascii"))
        write(
            fd,
            b"\r\n__NQ_RNG_SEED__\r\n/bin/seed-rng >/dev/console 2>&1; rc=$?; "
            + marker_command(seed_marker, "rc")
            + b"\r\n",
        )
        seed_data = read_until(fd, [seed_marker], 20)
        require_marker(seed_data, seed_marker, "rng seed upload")
        if seed_marker + b":0" not in seed_data:
            sys.stdout.write(seed_data.decode("utf-8", "replace"))
            write(fd, b"\r\n/bin/nq-reboot-fastboot\r\n")
            os.close(fd)
            fd = None
            fb = wait_fastboot(90)
            if fb:
                print(f"fastboot returned:\n{fb}")
            raise SystemExit("rng seed helper failed")

        if ssh_pub is not None:
            ssh_marker = f"__NQ_AUTHKEY_READY_{int(time.time() * 1000)}__".encode()
            write(fd, b"cat >/tmp/authorized_keys <<'__NQ_AUTHORIZED_KEYS__'\r\n")
            write(fd, authorized_keys.encode("utf-8"))
            write(
                fd,
                b"__NQ_AUTHORIZED_KEYS__\r\nchmod 600 /tmp/authorized_keys\r\n"
                + marker_command(ssh_marker)
                + b"\r\n",
            )
            require_marker(read_until(fd, [ssh_marker], 20), ssh_marker, "ssh authorized_keys upload")

        config_marker = f"__NQ_CONFIG_READY_{int(time.time() * 1000)}__".encode()
        write(fd, b"cat >/tmp/wpa_supplicant.conf <<'__NQ_WIFI_CONF__'\r\n")
        write(fd, conf.encode("utf-8"))
        write(
            fd,
            b"__NQ_WIFI_CONF__\r\nchmod 600 /tmp/wpa_supplicant.conf\r\n"
            + marker_command(config_marker)
            + b"\r\n",
        )
        require_marker(read_until(fd, [config_marker], 20), config_marker, "wifi config upload")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = ROOT / "build" / f"live-6.6-wifi-association-{stamp}.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        begin_marker = f"__NQ_TEST_BEGIN_{int(time.time() * 1000)}__".encode()
        done_marker = f"__NQ_LOG_DONE_{int(time.time() * 1000)}__".encode()
        write(fd, marker_command(begin_marker) + b"\r\n")
        require_marker(read_until(fd, [begin_marker], 10), begin_marker, "test start")
        write(
            fd,
            b"/bin/test-wifi; rc=$?; echo __NQ_TEST_DONE__:$rc; cat /run/wifi-test.log 2>/dev/null; "
            + marker_command(done_marker)
            + b"\r\n",
        )
        data = read_until(fd, [done_marker], args.test_timeout, print_output=True)
        log_text = data.decode("utf-8", "replace")
        log_path.write_text(log_text)
        print(f"\nlog: {log_path}")

        if ssh_key is not None:
            ip = extract_ipv4(log_text)
            if not ip:
                raise SystemExit("wifi test completed but no DHCP IPv4 address was found for SSH")
            print(f"ssh target: root@{ip}")
            ssh_proc = run_ssh_check(ip, ssh_key, args.ssh_timeout)
            ssh_log = ROOT / "build" / f"live-6.6-wifi-ssh-{stamp}.txt"
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
            write(fd, b"\r\nsync\r\n/bin/nq-reboot-fastboot\r\n")
            time.sleep(1)
            os.close(fd)

    fb = wait_fastboot(90)
    if fb:
        print(f"fastboot returned:\n{fb}")
    else:
        print("fastboot did not return within timeout", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
