#!/usr/bin/env python3

import argparse
import lzma
import math
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path


MIRROR = "https://deb.debian.org/debian"
SUITE = "trixie"
ARCH = "armhf"
COMPONENTS = ("main", "non-free-firmware")

EXTRA_PACKAGES = {
    "apt",
    "bash",
    "ca-certificates",
    "busybox-static",
    "dropbear-bin",
    "mpg123",
    "openssh-client",
    "openssh-sftp-server",
    "iproute2",
    "iputils-ping",
    "ifupdown",
    "isc-dhcp-client",
    "bind9-dnsutils",
    "kmod",
    "netbase",
    "procps",
    "psmisc",
    "ntpsec",
    "tzdata",
    "systemd",
    "systemd-sysv",
    "udev",
    "dbus",
    "alsa-utils",
    "alsa-ucm-conf",
    "squeezelite",
    "wpasupplicant",
    "wireless-regdb",
    "firmware-brcm80211",
    "iw",
    "wireless-tools",
    "curl",
    "less",
    "nano",
    "netcat-openbsd",
    "tcpdump",
    "htop",
    "strace",
    "lsof",
    "file",
    "rsync",
    "libccid",
    "libfreefare-bin",
    "libnfc-bin",
    "pcscd",
    "vim-tiny",
}


def run(cmd, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size:
        return
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    print(f"download {url}", flush=True)
    with urllib.request.urlopen(url) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)


def parse_packages(path, component):
    text = lzma.decompress(path.read_bytes()).decode("utf-8", "replace")
    packages = {}
    provides = {}
    for stanza in text.split("\n\n"):
        fields = {}
        key = None
        for line in stanza.splitlines():
            if not line:
                continue
            if line.startswith(" ") and key:
                fields[key] += "\n" + line[1:]
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key] = value.strip()
        name = fields.get("Package")
        if not name or "Filename" not in fields:
            continue
        fields["Component"] = component
        packages[name] = fields
        for virtual in split_provides(fields.get("Provides", "")):
            provides.setdefault(virtual, []).append(name)
    return packages, provides


def split_provides(value):
    if not value:
        return []
    result = []
    for item in value.split(","):
        name = clean_dep_name(item)
        if name:
            result.append(name)
    return result


def split_dep_groups(value):
    if not value:
        return []
    groups = []
    for group in value.replace("\n", " ").split(","):
        choices = []
        for choice in group.split("|"):
            name = clean_dep_name(choice)
            if name:
                choices.append(name)
        if choices:
            groups.append(choices)
    return groups


def clean_dep_name(value):
    value = value.strip()
    value = re.sub(r"\s*\(.*?\)", "", value)
    value = re.sub(r":any\b", "", value)
    value = re.sub(r":native\b", "", value)
    value = re.sub(r"\s*\[.*?\]", "", value)
    value = value.strip()
    if not value:
        return ""
    return value.split()[0]


def resolve(packages, provides, requested):
    selected = set()
    queue = list(requested)
    missing = set()

    while queue:
        name = queue.pop(0)
        if name in selected:
            continue
        if name not in packages:
            providers = provides.get(name, [])
            provider = next((p for p in providers if p in packages), None)
            if provider:
                name = provider
            else:
                missing.add(name)
                continue
        if name in selected:
            continue
        selected.add(name)
        fields = packages[name]
        deps = []
        deps.extend(split_dep_groups(fields.get("Pre-Depends", "")))
        deps.extend(split_dep_groups(fields.get("Depends", "")))
        for choices in deps:
            choice = next((c for c in choices if c in packages), None)
            if not choice:
                choice = next(
                    (provides[c][0] for c in choices if c in provides and provides[c]),
                    None,
                )
            if choice and choice not in selected:
                queue.append(choice)
            elif not choice:
                missing.add(" | ".join(choices))

    return selected, missing


def extract_deb(deb, rootfs):
    listing = subprocess.check_output(["ar", "t", str(deb)], text=True)
    data_member = next(
        (line.strip() for line in listing.splitlines() if line.startswith("data.tar")),
        None,
    )
    if not data_member:
        raise RuntimeError(f"{deb} has no data.tar member")

    if data_member.endswith(".xz"):
        p1 = subprocess.Popen(["ar", "p", str(deb), data_member], stdout=subprocess.PIPE)
        p2 = subprocess.Popen(["xz", "-dc"], stdin=p1.stdout, stdout=subprocess.PIPE)
        assert p1.stdout is not None
        p1.stdout.close()
        run(["tar", "-C", str(rootfs), "-xf", "-"], stdin=p2.stdout)
        if p2.stdout is not None:
            p2.stdout.close()
        p1.wait()
        p2.wait()
    elif data_member.endswith(".zst"):
        p1 = subprocess.Popen(["ar", "p", str(deb), data_member], stdout=subprocess.PIPE)
        p2 = subprocess.Popen(["zstd", "-dc"], stdin=p1.stdout, stdout=subprocess.PIPE)
        assert p1.stdout is not None
        p1.stdout.close()
        run(["tar", "-C", str(rootfs), "-xf", "-"], stdin=p2.stdout)
        if p2.stdout is not None:
            p2.stdout.close()
        p1.wait()
        p2.wait()
    elif data_member.endswith(".gz"):
        p1 = subprocess.Popen(["ar", "p", str(deb), data_member], stdout=subprocess.PIPE)
        run(["tar", "-C", str(rootfs), "-xzf", "-"], stdin=p1.stdout)
        if p1.stdout is not None:
            p1.stdout.close()
        p1.wait()
    else:
        raise RuntimeError(f"unsupported data member {data_member} in {deb}")


def write_text(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    set_owner_mode(path, mode)


def write_binary(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    set_owner_mode(path, mode)


def make_tone_wav(seconds=0.9, rate=48000, amplitude=0.20):
    frames = int(rate * seconds)
    notes = (
        (0.00, 0.32, 523.25),
        (0.18, 0.36, 659.25),
        (0.38, 0.40, 880.00),
        (0.58, 0.28, 1174.66),
    )
    data = bytearray()
    for i in range(frames):
        t = i / rate
        mixed = 0.0
        for start, duration, freq in notes:
            local = t - start
            if local < 0 or local >= duration:
                continue
            env = min(1.0, local / 0.018, (duration - local) / 0.075)
            phase = 2 * math.pi * freq * local
            mixed += env * (math.sin(phase) + 0.28 * math.sin(phase * 2))
        mixed = max(-1.0, min(1.0, mixed * amplitude))
        sample = int(32767 * mixed)
        data.extend(struct.pack("<hh", sample, sample))
    byte_rate = rate * 2 * 2
    block_align = 2 * 2
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 2, rate, byte_rate, block_align, 16)
        + b"data"
        + struct.pack("<I", len(data))
        + bytes(data)
    )


def random_password_hash():
    password = secrets.token_urlsafe(32)
    proc = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        check=True,
        input=password + "\n",
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip()


def maybe_reexec_under_fakeroot():
    if os.environ.get("FAKEROOTKEY") or os.environ.get("NQ_NO_FAKEROOT"):
        return
    fakeroot = shutil.which("fakeroot")
    if not fakeroot:
        print("warning: fakeroot not found; rootfs image may inherit host file owners")
        return
    os.execv(fakeroot, [fakeroot, sys.executable, *sys.argv])


def set_owner_mode(path, mode=None, uid=0, gid=0):
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        pass
    if mode is not None:
        path.chmod(mode)


def configure_rootfs(root, rootfs):
    write_text(rootfs / "etc/hostname", "nexusq\n")
    write_text(rootfs / "etc/passwd", "root:x:0:0:root:/root:/bin/bash\n")
    write_text(rootfs / "etc/group", "root:x:0:\n")
    write_text(
        rootfs / "etc/shadow",
        f"root:{random_password_hash()}:19723:0:99999:7:::\n",
        0o600,
    )
    write_text(
        rootfs / "etc/hosts",
        "127.0.0.1 localhost\n127.0.1.1 nexusq\n",
    )
    write_text(
        rootfs / "etc/shells",
        "/bin/sh\n/bin/dash\n/bin/bash\n/usr/bin/bash\n",
    )
    write_text(
        rootfs / "etc/apt/sources.list",
        "\n".join(
            [
                f"deb {MIRROR} {SUITE} main non-free-firmware",
                f"deb {MIRROR}-security {SUITE}-security main non-free-firmware",
                f"deb {MIRROR} {SUITE}-updates main non-free-firmware",
                "",
            ]
        ),
    )
    write_text(
        rootfs / "etc/network/interfaces",
        """auto lo
iface lo inet loopback

allow-hotplug usb0
iface usb0 inet static
    address 169.254.42.2
    netmask 255.255.0.0

iface usb0:rescue inet static
    address 172.16.42.2
    netmask 255.255.255.0
""",
    )
    write_text(
        rootfs / "sbin/nq-udhcpc-script",
        """#!/bin/sh

case "$1" in
    deconfig)
        ip addr flush dev "$interface" 2>/dev/null || true
        ;;
    bound|renew)
        ip addr flush dev "$interface" 2>/dev/null || true
        busybox ifconfig "$interface" "$ip" netmask "$subnet" ${broadcast:+broadcast "$broadcast"} 2>/dev/null || \
            ifconfig "$interface" "$ip" netmask "$subnet" ${broadcast:+broadcast "$broadcast"}
        ip link set "$interface" up 2>/dev/null || true
        ip route del default dev "$interface" 2>/dev/null || true
        for router in $router; do
            ip route add default via "$router" dev "$interface" 2>/dev/null || \
                route add default gw "$router" dev "$interface" 2>/dev/null || true
            break
        done
        : >/etc/resolv.conf
        for dns in $dns; do
            echo "nameserver $dns" >>/etc/resolv.conf
        done
        ;;
esac

exit 0
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-reboot-fastboot",
        """#!/bin/sh

sync

fallback="${NQ_REBOOT_FALLBACK:-15}"
case "$fallback" in
    ""|*[!0-9]*) fallback=15 ;;
esac

(
    sleep "$fallback"
    echo "reboot-bootloader fallback stage 1 after ${fallback}s" >/dev/console 2>/dev/null || true
    sync
    /sbin/reboot-bootloader bootloader >/dev/console 2>&1 &
    sleep 8
    echo "reboot-bootloader fallback stage 2: forced reboot" >/dev/console 2>/dev/null || true
    reboot -f >/dev/console 2>&1 &
    sleep 8
    echo "reboot-bootloader fallback stage 3: sysrq reboot" >/dev/console 2>/dev/null || true
    echo b >/proc/sysrq-trigger 2>/dev/null || true
) &

if [ -x /sbin/reboot-bootloader ]; then
    exec /sbin/reboot-bootloader bootloader
fi

exec reboot -f
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-autoreboot-cancel",
        """#!/bin/sh

if [ -s /run/nq-autoreboot.pid ]; then
    kill "$(cat /run/nq-autoreboot.pid)" 2>/dev/null || true
    rm -f /run/nq-autoreboot.pid
fi
echo "nq autoreboot cancelled"
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-autoreboot-status",
        """#!/bin/sh

if [ -s /run/nq-autoreboot.pid ] && kill -0 "$(cat /run/nq-autoreboot.pid)" 2>/dev/null; then
    echo "nq autoreboot armed pid=$(cat /run/nq-autoreboot.pid)"
else
    echo "nq autoreboot not armed"
fi
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-appliance-status",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

echo "Nexus Q appliance status"

if [ -s /etc/nexusq/wpa_supplicant.conf ]; then
    echo "wifi: persistent config present"
else
    echo "wifi: persistent config missing"
fi

if [ -s /etc/nexusq/authorized_keys ]; then
    echo "ssh: persistent authorized_keys present"
elif [ -s /root/.ssh/authorized_keys ]; then
    echo "ssh: root authorized_keys present"
else
    echo "ssh: authorized_keys missing"
fi

if [ -s /var/lib/nexusq/rng.seed ]; then
    echo "rng: persistent seed present"
else
    echo "rng: persistent seed missing"
fi

if [ -s /etc/nexusq/squeezelite.env ]; then
    echo "squeezelite: persistent config present"
else
    echo "squeezelite: persistent config missing"
fi

if [ -s /etc/nexusq/somafm.env ]; then
    echo "somafm: persistent config present"
else
    echo "somafm: persistent config missing"
fi

if [ -s /etc/nexusq/somafm-tags.conf ]; then
    echo "nfc-jukebox: persistent tag map present"
else
    echo "nfc-jukebox: persistent tag map missing"
fi

/sbin/nq-autoreboot-status 2>/dev/null || true

if [ -e /sys/class/net/wlan0 ]; then
    ip -brief addr show wlan0 2>/dev/null || ip addr show wlan0 2>/dev/null || true
else
    echo "wifi: wlan0 missing"
fi

if pgrep -x dropbear >/dev/null 2>&1 || pidof dropbear >/dev/null 2>&1; then
    echo "ssh: dropbear running"
else
    echo "ssh: dropbear not running"
fi

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

proc_name_live() {
    name="$1"
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_live "$pid" && return 0
    done
    return 1
}

pid_file_live() {
    pid_file="$1"
    [ -s "$pid_file" ] || return 1
    pid_live "$(cat "$pid_file" 2>/dev/null || true)"
}

if ls /sys/class/nfc/nfc* >/dev/null 2>&1; then
    for dev in /sys/class/nfc/nfc*; do
        [ -e "$dev" ] || continue
        echo "nfc: kernel device $(basename "$dev") present"
    done
else
    echo "nfc: kernel device missing"
fi

if command -v nq-nfc-poll >/dev/null 2>&1; then
    echo "nfc: kernel poller installed"
else
    echo "nfc: kernel poller missing"
fi

if command -v nfc-poll >/dev/null 2>&1; then
    echo "nfc: external-reader libnfc tools installed"
else
    echo "nfc: external-reader libnfc tools missing"
fi

if pid_file_live /run/nq-nfc-jukebox.pid; then
    echo "nfc-jukebox: running"
else
    echo "nfc-jukebox: not running"
fi

if grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null; then
    echo "input: Steelhead Front Panel present"
else
    echo "input: Steelhead Front Panel missing"
fi

if proc_name_live squeezelite; then
    echo "squeezelite: running"
else
    echo "squeezelite: not running"
fi

if proc_name_live nq-knob-volume; then
    echo "knob-volume: running"
else
    echo "knob-volume: not running"
fi

if [ -e /dev/leds ]; then
    echo "led-ring: /dev/leds present"
else
    echo "led-ring: /dev/leds missing"
fi

if [ -s /run/nexusq-audio-levels ]; then
    echo "audio-levels: /run/nexusq-audio-levels present"
    sed -n '1,9p' /run/nexusq-audio-levels 2>/dev/null || true
else
    echo "audio-levels: /run/nexusq-audio-levels missing"
fi

if ps | grep '[n]q-led-visualiz' >/dev/null 2>&1; then
    echo "led-visualizer: running"
else
    echo "led-visualizer: not running"
fi

if proc_name_live nq-adbd-lite; then
    echo "adb: nq-adbd-lite running"
else
    echo "adb: nq-adbd-lite not running"
fi
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-provision",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

CONFIG_DIR=/etc/nexusq
STATE_DIR=/var/lib/nexusq
WPA_DEST="$CONFIG_DIR/wpa_supplicant.conf"
AUTH_DEST="$CONFIG_DIR/authorized_keys"
SQUEEZELITE_DEST="$CONFIG_DIR/squeezelite.env"
LED_VISUALIZER_DEST="$CONFIG_DIR/led-visualizer.env"
SOMAFM_DEST="$CONFIG_DIR/somafm.env"
SOMAFM_TAGS_DEST="$CONFIG_DIR/somafm-tags.conf"
RNG_DEST="$STATE_DIR/rng.seed"

usage() {
    cat <<'USAGE'
Usage: nq-provision [options]

Persist appliance provisioning files into the Debian rootfs.

Options:
  --wifi PATH              Copy PATH to /etc/nexusq/wpa_supplicant.conf
  --authorized-keys PATH   Copy PATH to /etc/nexusq/authorized_keys
  --squeezelite PATH       Copy PATH to /etc/nexusq/squeezelite.env
  --led-visualizer PATH    Copy PATH to /etc/nexusq/led-visualizer.env
  --somafm PATH            Copy PATH to /etc/nexusq/somafm.env
  --somafm-tags PATH       Copy PATH to /etc/nexusq/somafm-tags.conf
  --rng-seed PATH          Copy PATH to /var/lib/nexusq/rng.seed
  --clear-wifi             Remove persistent Wi-Fi config
  --clear-authorized-keys  Remove persistent SSH authorized_keys
  --clear-squeezelite      Remove persistent Squeezelite config
  --clear-led-visualizer   Remove persistent LED visualizer config
  --clear-somafm           Remove persistent SomaFM config
  --clear-somafm-tags      Remove persistent NFC jukebox tag map
  --clear-rng-seed         Remove persistent RNG seed
  --cancel-autoreboot      Cancel the current safety return-to-fastboot timer
  --start-network          Start or restart Wi-Fi, DHCP, and Dropbear
  --start-squeezelite      Start or restart the Music Assistant player endpoint
  --start-led-visualizer   Start or restart the LED-ring visualizer
  --start-nfc-jukebox      Start or restart the NFC SomaFM jukebox
  --status                 Print appliance status after changes
  -h, --help               Show this help
USAGE
}

die() {
    echo "nq-provision: $*" >&2
    exit 1
}

copy_secret() {
    src="$1"
    dest="$2"
    mode="$3"

    [ -s "$src" ] || die "missing or empty source: $src"
    mkdir -p "$(dirname "$dest")" || die "cannot create $(dirname "$dest")"
    chmod 700 "$(dirname "$dest")" 2>/dev/null || true
    tmp="${dest}.tmp.$$"
    cp "$src" "$tmp" || die "copy failed: $src -> $tmp"
    chmod "$mode" "$tmp" 2>/dev/null || true
    chown 0:0 "$tmp" 2>/dev/null || true
    mv "$tmp" "$dest" || die "install failed: $dest"
    echo "installed $dest"
}

wifi_src=
auth_src=
squeezelite_src=
led_visualizer_src=
somafm_src=
somafm_tags_src=
rng_src=
clear_wifi=0
clear_auth=0
clear_squeezelite=0
clear_led_visualizer=0
clear_somafm=0
clear_somafm_tags=0
clear_rng=0
cancel_autoreboot=0
start_network=0
start_squeezelite=0
start_led_visualizer=0
start_nfc_jukebox=0
show_status=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --wifi)
            [ "$#" -ge 2 ] || die "--wifi requires a path"
            wifi_src="$2"
            shift 2
            ;;
        --authorized-keys)
            [ "$#" -ge 2 ] || die "--authorized-keys requires a path"
            auth_src="$2"
            shift 2
            ;;
        --squeezelite)
            [ "$#" -ge 2 ] || die "--squeezelite requires a path"
            squeezelite_src="$2"
            shift 2
            ;;
        --led-visualizer)
            [ "$#" -ge 2 ] || die "--led-visualizer requires a path"
            led_visualizer_src="$2"
            shift 2
            ;;
        --somafm)
            [ "$#" -ge 2 ] || die "--somafm requires a path"
            somafm_src="$2"
            shift 2
            ;;
        --somafm-tags)
            [ "$#" -ge 2 ] || die "--somafm-tags requires a path"
            somafm_tags_src="$2"
            shift 2
            ;;
        --rng-seed)
            [ "$#" -ge 2 ] || die "--rng-seed requires a path"
            rng_src="$2"
            shift 2
            ;;
        --clear-wifi)
            clear_wifi=1
            shift
            ;;
        --clear-authorized-keys)
            clear_auth=1
            shift
            ;;
        --clear-squeezelite)
            clear_squeezelite=1
            shift
            ;;
        --clear-led-visualizer)
            clear_led_visualizer=1
            shift
            ;;
        --clear-somafm)
            clear_somafm=1
            shift
            ;;
        --clear-somafm-tags)
            clear_somafm_tags=1
            shift
            ;;
        --clear-rng-seed)
            clear_rng=1
            shift
            ;;
        --cancel-autoreboot)
            cancel_autoreboot=1
            shift
            ;;
        --start-network)
            start_network=1
            shift
            ;;
        --start-squeezelite)
            start_squeezelite=1
            shift
            ;;
        --start-led-visualizer)
            start_led_visualizer=1
            shift
            ;;
        --start-nfc-jukebox)
            start_nfc_jukebox=1
            shift
            ;;
        --status)
            show_status=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

mkdir -p "$CONFIG_DIR" "$STATE_DIR" || die "cannot create provisioning directories"
chmod 700 "$CONFIG_DIR" "$STATE_DIR" 2>/dev/null || true

[ "$clear_wifi" -eq 0 ] || { rm -f "$WPA_DEST"; echo "removed $WPA_DEST"; }
[ "$clear_auth" -eq 0 ] || { rm -f "$AUTH_DEST"; echo "removed $AUTH_DEST"; }
[ "$clear_squeezelite" -eq 0 ] || { rm -f "$SQUEEZELITE_DEST"; echo "removed $SQUEEZELITE_DEST"; }
[ "$clear_led_visualizer" -eq 0 ] || { rm -f "$LED_VISUALIZER_DEST"; echo "removed $LED_VISUALIZER_DEST"; }
[ "$clear_somafm" -eq 0 ] || { rm -f "$SOMAFM_DEST"; echo "removed $SOMAFM_DEST"; }
[ "$clear_somafm_tags" -eq 0 ] || { rm -f "$SOMAFM_TAGS_DEST"; echo "removed $SOMAFM_TAGS_DEST"; }
[ "$clear_rng" -eq 0 ] || { rm -f "$RNG_DEST"; echo "removed $RNG_DEST"; }

[ -z "$wifi_src" ] || copy_secret "$wifi_src" "$WPA_DEST" 600
[ -z "$auth_src" ] || copy_secret "$auth_src" "$AUTH_DEST" 600
[ -z "$squeezelite_src" ] || copy_secret "$squeezelite_src" "$SQUEEZELITE_DEST" 644
[ -z "$led_visualizer_src" ] || copy_secret "$led_visualizer_src" "$LED_VISUALIZER_DEST" 644
[ -z "$somafm_src" ] || copy_secret "$somafm_src" "$SOMAFM_DEST" 644
[ -z "$somafm_tags_src" ] || copy_secret "$somafm_tags_src" "$SOMAFM_TAGS_DEST" 644
[ -z "$rng_src" ] || copy_secret "$rng_src" "$RNG_DEST" 600

if [ "$cancel_autoreboot" -eq 1 ]; then
    /sbin/nq-autoreboot-cancel || true
fi

if [ "$start_network" -eq 1 ]; then
    /sbin/nq-start-network
fi

if [ "$start_squeezelite" -eq 1 ]; then
    /sbin/nq-start-squeezelite
fi

if [ "$start_led_visualizer" -eq 1 ]; then
    /sbin/nq-start-led-visualizer
fi

if [ "$start_nfc_jukebox" -eq 1 ]; then
    /sbin/nq-start-nfc-jukebox
fi

if [ "$show_status" -eq 1 ] || [ "$start_network" -eq 1 ] || [ "$start_squeezelite" -eq 1 ] || [ "$start_led_visualizer" -eq 1 ] || [ "$start_nfc_jukebox" -eq 1 ]; then
    /sbin/nq-appliance-status
fi
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-prepare-wifi-firmware",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

FWDIR=/lib/firmware/brcm
MOUNT=/run/nexusq-stock-system
BIN="$FWDIR/brcmfmac4330-sdio.bin"
NVRAM_STEELHEAD="$FWDIR/brcmfmac4330-sdio.google,steelhead.txt"
NVRAM_GENERIC="$FWDIR/brcmfmac4330-sdio.txt"

log() {
    echo "[nq-wifi-fw] $*"
}

copy_file() {
    src="$1"
    dest="$2"
    [ -s "$src" ] || return 1
    cp "$src" "$dest" || return 1
    chmod 644 "$dest" 2>/dev/null || true
    log "copied ${src} -> ${dest}"
    return 0
}

try_tree() {
    base="$1"
    [ -d "$base" ] || return 1

    if [ ! -s "$BIN" ]; then
        for src in \
            "$base/vendor/firmware/brcmfmac4330-sdio.bin" \
            "$base/vendor/firmware/fw_bcmdhd.bin"
        do
            copy_file "$src" "$BIN" && break
        done
    fi

    if [ ! -s "$NVRAM_STEELHEAD" ]; then
        for src in \
            "$base/etc/wifi/bcmdhd.cal" \
            "$base/vendor/firmware/bcmdhd.cal" \
            "$base/vendor/firmware/brcmfmac4330-sdio.google,steelhead.txt" \
            "$base/vendor/firmware/brcmfmac4330-sdio.txt"
        do
            copy_file "$src" "$NVRAM_STEELHEAD" && break
        done
    fi

    if [ -s "$NVRAM_STEELHEAD" ] && [ ! -s "$NVRAM_GENERIC" ]; then
        cp "$NVRAM_STEELHEAD" "$NVRAM_GENERIC" 2>/dev/null || true
        chmod 644 "$NVRAM_GENERIC" 2>/dev/null || true
    fi
    if [ -s "$NVRAM_GENERIC" ] && [ ! -s "$NVRAM_STEELHEAD" ]; then
        cp "$NVRAM_GENERIC" "$NVRAM_STEELHEAD" 2>/dev/null || true
        chmod 644 "$NVRAM_STEELHEAD" 2>/dev/null || true
    fi
}

mkdir -p "$FWDIR"

for base in /system /mnt/system "$MOUNT"; do
    try_tree "$base"
done

if { [ ! -s "$NVRAM_STEELHEAD" ] || [ ! -s "$BIN" ]; } && [ -b /dev/mmcblk0p11 ]; then
    mkdir -p "$MOUNT"
    if ! mountpoint -q "$MOUNT" 2>/dev/null; then
        mount -o ro /dev/mmcblk0p11 "$MOUNT" 2>/dev/null || true
    fi
    try_tree "$MOUNT"
    umount "$MOUNT" 2>/dev/null || true
fi

rc=0
if [ ! -s "$BIN" ]; then
    log "missing $BIN"
    rc=1
fi
if [ ! -s "$NVRAM_STEELHEAD" ] && [ ! -s "$NVRAM_GENERIC" ]; then
    log "missing BCM4330 NVRAM calibration; expected Android /etc/wifi/bcmdhd.cal or /lib/firmware/brcm/brcmfmac4330-sdio.google,steelhead.txt"
    rc=1
fi

exit "$rc"
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-load-wifi",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

log() {
    echo "[nq-load-wifi] $*"
}

if [ -e /sys/class/net/wlan0 ]; then
    log "wlan0 already exists"
    exit 0
fi

/sbin/nq-prepare-wifi-firmware || true

krel="$(uname -r)"
mods="/lib/modules/$krel"
if [ -d "$mods" ]; then
    if command -v depmod >/dev/null 2>&1; then
        depmod -a "$krel" 2>/dev/null || true
    fi
    if command -v modprobe >/dev/null 2>&1; then
        modprobe brcmfmac 2>/dev/null || true
    fi
fi

i=0
while [ "$i" -lt 15 ]; do
    [ -e /sys/class/net/wlan0 ] && break
    i=$((i + 1))
    sleep 1
done

if [ ! -e /sys/class/net/wlan0 ] && command -v insmod >/dev/null 2>&1; then
    base="$mods/kernel/drivers/net/wireless/broadcom/brcm80211"
    for ko in \
        "$base/brcmutil/brcmutil.ko" \
        "$base/brcmfmac/brcmfmac.ko" \
        "$base/brcmfmac/wcc/brcmfmac-wcc.ko" \
        "$base/brcmfmac/cyw/brcmfmac-cyw.ko" \
        "$base/brcmfmac/bca/brcmfmac-bca.ko"
    do
        [ -s "$ko" ] || continue
        insmod "$ko" 2>/dev/null || true
    done
fi

i=0
while [ "$i" -lt 15 ]; do
    if [ -e /sys/class/net/wlan0 ]; then
        log "wlan0 ready"
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

log "wlan0 did not appear"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-load-input",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

log() {
    echo "[nq-load-input] $*"
}

for env in /etc/nexusq/input.env /run/nexusq/input.env /tmp/input.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_INPUT_ENABLE:=1}"
: "${NQ_INPUT_I2C_ADAPTER:=i2c-1}"
: "${NQ_INPUT_I2C_ADDR:=0x20}"
: "${NQ_AVR_POLL_MS:=50}"
: "${NQ_AVR_FORCE_POLL:=1}"
: "${NQ_AVR_DEBUG_EVENTS:=0}"
: "${NQ_AVR_LEGACY_INIT:=1}"
: "${NQ_AVR_RESET_PULSE_MS:=0}"

avr_args="poll_ms=$NQ_AVR_POLL_MS force_poll=$NQ_AVR_FORCE_POLL debug_events=$NQ_AVR_DEBUG_EVENTS legacy_init=$NQ_AVR_LEGACY_INIT reset_pulse_ms=$NQ_AVR_RESET_PULSE_MS"

if [ "$NQ_INPUT_ENABLE" != "1" ]; then
    log "disabled; set NQ_INPUT_ENABLE=1"
    exit 0
fi

if grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null; then
    log "Steelhead Front Panel already registered"
    exit 0
fi

krel="$(uname -r)"
mods="/lib/modules/$krel"

if [ -d "$mods" ] && command -v depmod >/dev/null 2>&1; then
    depmod -a "$krel" 2>/dev/null || true
fi

if command -v modprobe >/dev/null 2>&1; then
    modprobe steelhead_avr $avr_args 2>/dev/null || true
fi

if ! grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null && command -v insmod >/dev/null 2>&1; then
    ko="$mods/kernel/drivers/input/misc/steelhead_avr.ko"
    [ -s "$ko" ] && insmod "$ko" $avr_args 2>/dev/null || true
fi

if ! grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null; then
    adapter="/sys/bus/i2c/devices/$NQ_INPUT_I2C_ADAPTER"
    if [ -w "$adapter/new_device" ]; then
        log "binding steelhead-avr on $NQ_INPUT_I2C_ADAPTER at $NQ_INPUT_I2C_ADDR"
        echo "steelhead-avr $NQ_INPUT_I2C_ADDR" >"$adapter/new_device" 2>/dev/null || true
    else
        log "I2C adapter $NQ_INPUT_I2C_ADAPTER cannot bind new devices"
    fi
fi

i=0
while [ "$i" -lt 10 ]; do
    if grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null; then
        log "Steelhead Front Panel ready"
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

log "Steelhead Front Panel did not appear"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-load-audio",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

log() {
    echo "[nq-load-audio] $*"
}

if grep -q 'Steelhead TAS5713' /proc/asound/cards 2>/dev/null; then
    log "Steelhead TAS5713 already registered"
    exit 0
fi

krel="$(uname -r)"
mods="/lib/modules/$krel"

if [ -d "$mods" ] && command -v depmod >/dev/null 2>&1; then
    depmod -a "$krel" 2>/dev/null || true
fi

if command -v modprobe >/dev/null 2>&1; then
    modprobe snd_soc_ti_sdma \\
        nq_period_bytes=4128 \\
        nq_periods=4 2>/dev/null || true
    modprobe snd_soc_omap_mcbsp \\
        nq_legacy_element=1 \\
        nq_legacy_threshold_frame=1 \\
        nq_legacy_pm_runtime_hold=1 \\
        nq_no_rx_err_irq=1 \\
        nq_legacy_tx_irq=1 \\
        nq_pio_tone_ms=0 \\
        nq_fifo_poll_ms=0 2>/dev/null || true
    modprobe snd_soc_tas571x \\
        nq_dump_regs=0 \\
        nq_legacy_stream_reinit=1 \\
        nq_mute_on_trigger=-1 \\
        nq_async_legacy_stream_reinit_ms=0 \\
        nq_cycle_mclk_on_legacy_reset=1 \\
        nq_skip_hw_params=1 \\
        nq_sdi_override=-1 \\
        nq_err_poll_ms=0 2>/dev/null || true
    modprobe snd_soc_steelhead_tas5713 \\
        nq_audio_dump=0 \\
        nq_audio_format=i2s \\
        nq_audio_inversion=nb-nf \\
        nq_legacy_s16_only=1 \\
        nq_codec_power_first=0 \\
        nq_codec_mclk_startup=0 \\
        nq_mcbsp_clk_startup=0 \\
        nq_mcbsp_clk_hw_params=1 \\
        nq_skip_codec_fmt=1 2>/dev/null || true
fi

if ! grep -q 'Steelhead TAS5713' /proc/asound/cards 2>/dev/null && command -v insmod >/dev/null 2>&1; then
    audio_base="$mods/kernel/sound/soc"
    insmod "$audio_base/ti/snd-soc-ti-sdma.ko" \\
        nq_period_bytes=4128 \\
        nq_periods=4 2>/dev/null || true
    insmod "$audio_base/ti/snd-soc-omap-mcbsp.ko" \\
        nq_legacy_element=1 \\
        nq_legacy_threshold_frame=1 \\
        nq_legacy_pm_runtime_hold=1 \\
        nq_no_rx_err_irq=1 \\
        nq_legacy_tx_irq=1 \\
        nq_pio_tone_ms=0 \\
        nq_fifo_poll_ms=0 2>/dev/null || true
    insmod "$audio_base/codecs/snd-soc-tas571x.ko" \\
        nq_dump_regs=0 \\
        nq_legacy_stream_reinit=1 \\
        nq_mute_on_trigger=-1 \\
        nq_async_legacy_stream_reinit_ms=0 \\
        nq_cycle_mclk_on_legacy_reset=1 \\
        nq_skip_hw_params=1 \\
        nq_sdi_override=-1 \\
        nq_err_poll_ms=0 2>/dev/null || true
    insmod "$audio_base/ti/snd-soc-steelhead-tas5713.ko" \\
        nq_audio_dump=0 \\
        nq_audio_format=i2s \\
        nq_audio_inversion=nb-nf \\
        nq_legacy_s16_only=1 \\
        nq_codec_power_first=0 \\
        nq_codec_mclk_startup=0 \\
        nq_mcbsp_clk_startup=0 \\
        nq_mcbsp_clk_hw_params=1 \\
        nq_skip_codec_fmt=1 2>/dev/null || true
fi

i=0
while [ "$i" -lt 10 ]; do
    if grep -q 'Steelhead TAS5713' /proc/asound/cards 2>/dev/null; then
        log "Steelhead TAS5713 ready"
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

log "Steelhead TAS5713 did not appear"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "etc/modules-load.d/nexusq-audio.conf",
        "# Loaded by /sbin/nq-load-audio so module parameters are applied.\n",
    )
    write_text(
        rootfs / "sbin/nq-sync-time",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

: "${NQ_TIME_SYNC_MIN_YEAR:=2024}"
: "${NQ_TIME_SYNC_URLS:=http://deb.debian.org/debian/ http://somafm.com/}"

log() {
    echo "[nq-sync-time] $*"
}

year="$(date -u +%Y 2>/dev/null || echo 0)"
case "$year" in
    *[!0-9]*|"") year=0 ;;
esac

if [ "$year" -ge "$NQ_TIME_SYNC_MIN_YEAR" ] 2>/dev/null; then
    log "clock already plausible: $(date -u 2>/dev/null || true)"
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    log "curl is not installed"
    exit 1
fi

for url in $NQ_TIME_SYNC_URLS; do
    http_date="$(
        curl -fsSI --connect-timeout 5 --max-time 10 "$url" 2>/dev/null |
        awk '
            BEGIN { IGNORECASE = 1 }
            /^Date:[ \t]*/ {
                sub(/^Date:[ \t]*/, "")
                sub(/\r$/, "")
                print
                exit
            }
        '
    )"
    [ -n "$http_date" ] || continue
    if date -u -s "$http_date" >/dev/null 2>&1; then
        log "set clock from $url: $(date -u 2>/dev/null || true)"
        exit 0
    fi
    log "failed to apply date from $url: $http_date"
done

log "failed to sync time"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-start-network",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-network.log
mkdir -p /run /run/nexusq /run/wpa_supplicant /root/.ssh /etc/dropbear /var/lib/misc /var/lib/nexusq
: >"$LOG"
exec >>"$LOG" 2>&1

echo "[nq-network] starting"
date 2>/dev/null || true

seeded_rng=0
if [ -x /sbin/seed-rng ] && [ -s /tmp/rng.seed ]; then
    /sbin/seed-rng || true
    seeded_rng=1
fi
if [ "$seeded_rng" -eq 0 ] && [ -x /sbin/seed-rng ] && [ -s /var/lib/nexusq/rng.seed ]; then
    cp /var/lib/nexusq/rng.seed /tmp/rng.seed 2>/dev/null || true
    chmod 600 /tmp/rng.seed 2>/dev/null || true
    /sbin/seed-rng || true
fi

/sbin/nq-load-wifi || true

wifi_mac="$(tr ' ' '\\n' </proc/cmdline 2>/dev/null | sed -n 's/^androidboot.wifi_macaddr=//p' | head -n 1)"
ip link set wlan0 down 2>/dev/null || true
if [ -n "$wifi_mac" ]; then
    ip link set dev wlan0 address "$wifi_mac" 2>/dev/null || true
fi
ip link set wlan0 up 2>/dev/null || true

WPA_CONF="${1:-}"
if [ -z "$WPA_CONF" ]; then
    for candidate in /run/nexusq/wpa_supplicant.conf /etc/nexusq/wpa_supplicant.conf /tmp/wpa_supplicant.conf
    do
        if [ -s "$candidate" ]; then
            WPA_CONF="$candidate"
            break
        fi
    done
fi

if [ -s "$WPA_CONF" ] && command -v wpa_supplicant >/dev/null 2>&1; then
    killall wpa_supplicant 2>/dev/null || true
    wpa_supplicant -B -i wlan0 -c "$WPA_CONF" -P /run/wpa_supplicant.wlan0.pid
    wpa_ping() {
        wpa_cli -p /run/wpa_supplicant -i wlan0 ping 2>/dev/null
    }
    wpa_status() {
        wpa_cli -p /run/wpa_supplicant -i wlan0 status 2>/dev/null
    }
    i=0
    while [ "$i" -lt 20 ]; do
        if wpa_ping | grep -q PONG; then
            break
        fi
        i=$((i + 1))
        sleep 1
    done
    i=0
    while [ "$i" -lt 40 ]; do
        echo "--- wpa_cli status poll $i ---"
        wpa_status || true
        if wpa_status | grep -q '^wpa_state=COMPLETED'; then
            break
        fi
        i=$((i + 1))
        sleep 1
    done
else
    echo "[nq-network] no usable wpa_supplicant config found"
fi

if command -v busybox >/dev/null 2>&1; then
    busybox udhcpc -i wlan0 -s /sbin/nq-udhcpc-script -n -q -t 5 -T 3 || true
elif command -v dhclient >/dev/null 2>&1; then
    dhclient -v -1 wlan0 || true
fi

if [ -x /sbin/nq-sync-time ]; then
    /sbin/nq-sync-time || true
fi

if [ -x /etc/init.d/ntpsec ]; then
    mkdir -p /run/lock /run/ntpsec
    if ! pgrep -x ntpd >/dev/null 2>&1; then
        /etc/init.d/ntpsec start || true
    fi
fi

AUTH_KEYS=
for candidate in /run/nexusq/authorized_keys /etc/nexusq/authorized_keys /tmp/authorized_keys
do
    if [ -s "$candidate" ]; then
        AUTH_KEYS="$candidate"
        break
    fi
done

if [ -n "$AUTH_KEYS" ]; then
    cp "$AUTH_KEYS" /root/.ssh/authorized_keys
    chmod 700 /root /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
    chown 0:0 /root /root/.ssh /root/.ssh/authorized_keys 2>/dev/null || true
fi

if command -v dropbear >/dev/null 2>&1; then
    if [ ! -e /etc/dropbear/dropbear_ed25519_host_key ]; then
        dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key
    fi
    killall dropbear 2>/dev/null || true
    pkill -x dropbear 2>/dev/null || true
    sleep 1
    dropbear -E -F -s -p 22 &
    echo "[nq-network] dropbear pid=$!"
fi

ip addr show wlan0 2>/dev/null || ifconfig wlan0 2>/dev/null || true
if [ -d /var/lib/nexusq ]; then
    (
        umask 077
        if dd if=/dev/urandom of=/var/lib/nexusq/rng.seed.new bs=64 count=1 2>/dev/null; then
            mv /var/lib/nexusq/rng.seed.new /var/lib/nexusq/rng.seed
        fi
    ) &
fi
echo "[nq-network] done"
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-start-squeezelite",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-squeezelite.log
PID=/run/nq-squeezelite.pid
mkdir -p /run /run/nexusq
: >"$LOG"
exec >>"$LOG" 2>&1
trap '' HUP

echo "[nq-squeezelite] starting"
date 2>/dev/null || true

for env in /etc/nexusq/led-visualizer.env /run/nexusq/led-visualizer.env /tmp/led-visualizer.env /etc/nexusq/squeezelite.env /run/nexusq/squeezelite.env /tmp/squeezelite.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_SQUEEZELITE_ENABLE:=0}"
: "${NQ_SQUEEZELITE_NAME:=Nexus Q}"
: "${NQ_SQUEEZELITE_OUTPUT:=hw:0,0}"
: "${NQ_SQUEEZELITE_RATES:=48000-48000}"
: "${NQ_SQUEEZELITE_RESAMPLE:=hLX}"
: "${NQ_SQUEEZELITE_CLOSE_TIMEOUT:=5}"
: "${NQ_SQUEEZELITE_MIXER_CARD:=0}"
: "${NQ_SQUEEZELITE_MASTER_VOLUME:=231}"
: "${NQ_SQUEEZELITE_SPEAKER_VOLUME:=207}"
: "${NQ_SQUEEZELITE_SPEAKER_SWITCH:=on}"
: "${NQ_SQUEEZELITE_RESTART:=0}"
: "${NQ_SQUEEZELITE_VISUALIZER:=${NQ_LED_VISUALIZER_ENABLE:-0}}"

if [ "$NQ_SQUEEZELITE_ENABLE" != "1" ]; then
    echo "[nq-squeezelite] disabled; set NQ_SQUEEZELITE_ENABLE=1"
    exit 0
fi

if ! command -v squeezelite >/dev/null 2>&1; then
    echo "[nq-squeezelite] squeezelite command missing"
    exit 1
fi

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

proc_live() {
    name="$1"
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_live "$pid" && return 0
    done
    return 1
}

stop_proc() {
    name="$1"
    live_pids=
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_live "$pid" || continue
        live_pids="$live_pids $pid"
    done
    [ -z "$live_pids" ] || kill $live_pids 2>/dev/null || true
    sleep 1
    live_pids=
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_live "$pid" || continue
        live_pids="$live_pids $pid"
    done
    [ -z "$live_pids" ] || kill -KILL $live_pids 2>/dev/null || true
}

derive_mac() {
    if [ -n "$NQ_SQUEEZELITE_MAC" ]; then
        echo "$NQ_SQUEEZELITE_MAC"
        return
    fi
    tr ' ' '\\n' </proc/cmdline 2>/dev/null | sed -n 's/^androidboot.wifi_macaddr=//p' | head -n 1
    for iface in wlan0 usb0 eth0; do
        [ -r "/sys/class/net/$iface/address" ] || continue
        cat "/sys/class/net/$iface/address"
        return
    done
}

mac="$(derive_mac | head -n 1)"
case "$mac" in
    [0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F])
        ;;
    *)
        mac=
        ;;
esac

if command -v amixer >/dev/null 2>&1; then
    speaker_volume="$NQ_SQUEEZELITE_SPEAKER_VOLUME"
    case "$speaker_volume" in
        *,*) ;;
        *) speaker_volume="$speaker_volume,$speaker_volume" ;;
    esac

    echo "[nq-squeezelite] setting mixer: card=$NQ_SQUEEZELITE_MIXER_CARD master=$NQ_SQUEEZELITE_MASTER_VOLUME speaker=$speaker_volume switch=$NQ_SQUEEZELITE_SPEAKER_SWITCH"
    amixer -q -c "$NQ_SQUEEZELITE_MIXER_CARD" cset name="Speaker Switch" "$NQ_SQUEEZELITE_SPEAKER_SWITCH" || true
    amixer -q -c "$NQ_SQUEEZELITE_MIXER_CARD" cset name="Speaker Volume" "$speaker_volume" || true
    amixer -q -c "$NQ_SQUEEZELITE_MIXER_CARD" cset name="Master Volume" "$NQ_SQUEEZELITE_MASTER_VOLUME" || true
fi

if [ "$NQ_SQUEEZELITE_RESTART" != "1" ]; then
    if [ -s "$PID" ]; then
        old_pid="$(cat "$PID" 2>/dev/null || true)"
        if pid_live "$old_pid"; then
            echo "[nq-squeezelite] already running pid=$old_pid"
            exit 0
        fi
    fi
    if proc_live squeezelite; then
        echo "[nq-squeezelite] already running"
        exit 0
    fi
else
    stop_proc squeezelite
fi

set -- squeezelite \
    -n "$NQ_SQUEEZELITE_NAME" \
    -o "$NQ_SQUEEZELITE_OUTPUT" \
    -r "$NQ_SQUEEZELITE_RATES" \
    -C "$NQ_SQUEEZELITE_CLOSE_TIMEOUT" \
    -f "$LOG"

[ -z "$mac" ] || set -- "$@" -m "$mac"
[ -z "$NQ_SQUEEZELITE_SERVER" ] || set -- "$@" -s "$NQ_SQUEEZELITE_SERVER"
[ -z "$NQ_SQUEEZELITE_ALSA_PARAMS" ] || set -- "$@" -a "$NQ_SQUEEZELITE_ALSA_PARAMS"
[ -z "$NQ_SQUEEZELITE_CODEC_LIST" ] || set -- "$@" -c "$NQ_SQUEEZELITE_CODEC_LIST"
[ "$NQ_SQUEEZELITE_VISUALIZER" != "1" ] || set -- "$@" -v
case "$NQ_SQUEEZELITE_RESAMPLE" in
    ""|0|off|false|none) ;;
    *) set -- "$@" -u "$NQ_SQUEEZELITE_RESAMPLE" ;;
esac

echo "[nq-squeezelite] exec: $*"
if command -v setsid >/dev/null 2>&1; then
    setsid "$@" </dev/null &
else
    "$@" </dev/null &
fi
echo "$!" >"$PID"
sleep 1

if pid_live "$(cat "$PID")"; then
    echo "[nq-squeezelite] pid=$(cat "$PID")"
    exit 0
fi

echo "[nq-squeezelite] failed to stay running"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-start-knob-volume",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-knob-volume.log
PID=/run/nq-knob-volume.pid
mkdir -p /run /run/nexusq
: >"$LOG"
exec >>"$LOG" 2>&1
trap '' HUP

echo "[nq-knob-volume] starting"
date 2>/dev/null || true

for env in /etc/nexusq/knob-volume.env /run/nexusq/knob-volume.env /tmp/knob-volume.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_KNOB_ENABLE:=1}"
: "${NQ_KNOB_MIXER_CARD:=0}"
: "${NQ_KNOB_CONTROL:=Master Volume}"
: "${NQ_KNOB_MUTE_CONTROL:=Speaker Switch}"
: "${NQ_KNOB_MIN:=120}"
: "${NQ_KNOB_MAX:=231}"
: "${NQ_KNOB_STEP:=2}"
: "${NQ_KNOB_MUTE_ENABLE:=1}"
: "${NQ_KNOB_INPUT_NAME:=Steelhead Front Panel}"

export NQ_KNOB_MIXER_CARD NQ_KNOB_CONTROL NQ_KNOB_MUTE_CONTROL
export NQ_KNOB_MIN NQ_KNOB_MAX NQ_KNOB_STEP NQ_KNOB_MUTE_ENABLE
export NQ_KNOB_INPUT_NAME NQ_KNOB_INPUT

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

knob_live() {
    for pid in $(pgrep -x nq-knob-volume 2>/dev/null || pidof nq-knob-volume 2>/dev/null || true); do
        pid_live "$pid" && return 0
    done
    return 1
}

if [ "$NQ_KNOB_ENABLE" != "1" ]; then
    echo "[nq-knob-volume] disabled; set NQ_KNOB_ENABLE=1"
    exit 0
fi

if [ ! -x /usr/sbin/nq-knob-volume ]; then
    echo "[nq-knob-volume] /usr/sbin/nq-knob-volume missing"
    exit 0
fi

if [ -s "$PID" ]; then
    old_pid="$(cat "$PID" 2>/dev/null || true)"
    if pid_live "$old_pid"; then
        echo "[nq-knob-volume] already running pid=$old_pid"
        exit 0
    fi
fi
if knob_live; then
    echo "[nq-knob-volume] already running"
    exit 0
fi

/usr/sbin/nq-knob-volume ${NQ_KNOB_INPUT:+"$NQ_KNOB_INPUT"} &
echo "$!" >"$PID"
sleep 1

if pid_live "$(cat "$PID")"; then
    echo "[nq-knob-volume] pid=$(cat "$PID")"
    exit 0
fi

echo "[nq-knob-volume] failed to stay running"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-start-led-visualizer",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-led-visualizer.log
PID=/run/nq-led-visualizer.pid
mkdir -p /run /run/nexusq /dev/shm
: >"$LOG"
exec >>"$LOG" 2>&1
trap '' HUP

echo "[nq-led-visualizer] starting"
date 2>/dev/null || true

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env /etc/nexusq/led-visualizer.env /run/nexusq/led-visualizer.env /tmp/led-visualizer.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_LED_VISUALIZER_ENABLE:=1}"
: "${NQ_LED_VISUALIZER_DEVICE:=/dev/leds}"
: "${NQ_LED_VISUALIZER_SOURCE:=auto}"
: "${NQ_LED_VISUALIZER_LEVELS:=/run/nexusq-audio-levels}"
: "${NQ_LED_VISUALIZER_SHM:=}"
: "${NQ_LED_VISUALIZER_FPS:=60}"
: "${NQ_LED_VISUALIZER_BRIGHTNESS:=255}"
: "${NQ_LED_VISUALIZER_IDLE_BRIGHTNESS:=6}"
: "${NQ_LED_VISUALIZER_GAIN:=8}"
: "${NQ_LED_VISUALIZER_STYLE:=pulse}"
: "${NQ_LED_VISUALIZER_SWIRL:=1}"
: "${NQ_LED_VISUALIZER_SWIRL_MIN_MS:=10000}"
: "${NQ_LED_VISUALIZER_SWIRL_MAX_MS:=15000}"
: "${NQ_LED_VISUALIZER_SWIRL_DURATION_MS:=2200}"
: "${NQ_LED_VISUALIZER_SYNC_DELAY_MS:=220}"
: "${NQ_LED_VISUALIZER_SYNC_DELAY_FILE:=/run/nexusq-led-sync-delay-ms}"

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

visualizer_live() {
    if [ -s "$PID" ] && pid_live "$(cat "$PID" 2>/dev/null || true)"; then
        return 0
    fi
    ps | grep '[n]q-led-visualiz' >/dev/null 2>&1
}

if [ "$NQ_LED_VISUALIZER_ENABLE" != "1" ]; then
    echo "[nq-led-visualizer] disabled; set NQ_LED_VISUALIZER_ENABLE=1"
    exit 0
fi

if [ ! -x /usr/sbin/nq-led-visualizer ]; then
    echo "[nq-led-visualizer] /usr/sbin/nq-led-visualizer missing"
    exit 0
fi

if [ ! -e "$NQ_LED_VISUALIZER_DEVICE" ]; then
    echo "[nq-led-visualizer] $NQ_LED_VISUALIZER_DEVICE missing"
    exit 0
fi

if ! grep -q ' /dev/shm ' /proc/mounts 2>/dev/null; then
    mount -t tmpfs tmpfs /dev/shm 2>/dev/null || true
fi

if visualizer_live; then
    echo "[nq-led-visualizer] already running"
    exit 0
fi

set -- /usr/sbin/nq-led-visualizer \\
    --device "$NQ_LED_VISUALIZER_DEVICE" \\
    --fps "$NQ_LED_VISUALIZER_FPS" \\
    --brightness "$NQ_LED_VISUALIZER_BRIGHTNESS" \\
    --idle-brightness "$NQ_LED_VISUALIZER_IDLE_BRIGHTNESS" \\
    --gain "$NQ_LED_VISUALIZER_GAIN" \\
    --style "$NQ_LED_VISUALIZER_STYLE" \\
    --swirl "$NQ_LED_VISUALIZER_SWIRL" \\
    --swirl-min-ms "$NQ_LED_VISUALIZER_SWIRL_MIN_MS" \\
    --swirl-max-ms "$NQ_LED_VISUALIZER_SWIRL_MAX_MS" \\
    --swirl-duration-ms "$NQ_LED_VISUALIZER_SWIRL_DURATION_MS" \\
    --sync-delay-ms "$NQ_LED_VISUALIZER_SYNC_DELAY_MS" \\
    --sync-delay-file "$NQ_LED_VISUALIZER_SYNC_DELAY_FILE"

case "$NQ_LED_VISUALIZER_SOURCE" in
    levels|somafm)
        [ -z "$NQ_LED_VISUALIZER_LEVELS" ] || set -- "$@" --levels "$NQ_LED_VISUALIZER_LEVELS"
        ;;
    squeezelite|shm)
        [ -z "$NQ_LED_VISUALIZER_SHM" ] || set -- "$@" --shm "$NQ_LED_VISUALIZER_SHM"
        ;;
    auto|"")
        [ -z "$NQ_LED_VISUALIZER_LEVELS" ] || set -- "$@" --levels "$NQ_LED_VISUALIZER_LEVELS"
        [ -z "$NQ_LED_VISUALIZER_SHM" ] || set -- "$@" --shm "$NQ_LED_VISUALIZER_SHM"
        ;;
    *)
        echo "[nq-led-visualizer] unknown source=$NQ_LED_VISUALIZER_SOURCE; using auto"
        [ -z "$NQ_LED_VISUALIZER_LEVELS" ] || set -- "$@" --levels "$NQ_LED_VISUALIZER_LEVELS"
        [ -z "$NQ_LED_VISUALIZER_SHM" ] || set -- "$@" --shm "$NQ_LED_VISUALIZER_SHM"
        ;;
esac

echo "[nq-led-visualizer] exec: $*"
if command -v setsid >/dev/null 2>&1; then
    setsid "$@" </dev/null &
else
    "$@" </dev/null &
fi
echo "$!" >"$PID"
sleep 1

if pid_live "$(cat "$PID")"; then
    echo "[nq-led-visualizer] pid=$(cat "$PID")"
    exit 0
fi

echo "[nq-led-visualizer] failed to stay running"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-start-adbd",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-adbd.log
PID=/run/nq-adbd-lite.pid
LOCK=/run/nq-adbd-lite.lock
mkdir -p /run /run/nexusq
: >"$LOG"
exec >>"$LOG" 2>&1
trap '' HUP

echo "[nq-adbd-lite] starting"
date 2>/dev/null || true

for env in /etc/nexusq/adbd.env /run/nexusq/adbd.env /tmp/adbd.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_ADBD_ENABLE:=1}"
: "${NQ_ADBD_PORT:=5555}"
: "${NQ_ADBD_SHELL:=}"
: "${NQ_ADBD_RESTART:=0}"
export NQ_ADBD_SHELL

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    comm="$(cat "/proc/$pid/comm" 2>/dev/null || true)"
    [ "$comm" = "nq-adbd-lite" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

adbd_live() {
    for pid in $(pgrep -x nq-adbd-lite 2>/dev/null || pidof nq-adbd-lite 2>/dev/null || true); do
        pid_live "$pid" && return 0
    done
    return 1
}

port_listening() {
    port_hex="$(printf '%04X' "$NQ_ADBD_PORT" 2>/dev/null || true)"
    [ -n "$port_hex" ] || return 1
    awk -v port=":$port_hex" '
        $2 ~ port "$" && $4 == "0A" { found = 1 }
        END { exit found ? 0 : 1 }
    ' /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

acquire_lock() {
    tries=0
    while ! mkdir "$LOCK" 2>/dev/null; do
        tries=$((tries + 1))
        if [ "$tries" -ge 10 ]; then
            echo "[nq-adbd-lite] another start is active"
            exit 0
        fi
        sleep 1
    done
    trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT INT TERM
}

stop_adbd() {
    live_pids=
    for pid in $(pgrep -x nq-adbd-lite 2>/dev/null || pidof nq-adbd-lite 2>/dev/null || true); do
        pid_live "$pid" || continue
        live_pids="$live_pids $pid"
    done
    [ -z "$live_pids" ] || kill $live_pids 2>/dev/null || true
    sleep 1
    for pid in $live_pids; do
        pid_live "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    rm -f "$PID"
}

if [ "$NQ_ADBD_ENABLE" != "1" ]; then
    echo "[nq-adbd-lite] disabled; set NQ_ADBD_ENABLE=1 to enable"
    exit 0
fi

if [ ! -x /usr/sbin/nq-adbd-lite ]; then
    echo "[nq-adbd-lite] /usr/sbin/nq-adbd-lite missing"
    exit 0
fi

acquire_lock

if [ "$NQ_ADBD_RESTART" = "1" ]; then
    stop_adbd
fi

if [ -s "$PID" ]; then
    old_pid="$(cat "$PID" 2>/dev/null || true)"
    if pid_live "$old_pid" && port_listening; then
        echo "[nq-adbd-lite] already running pid=$old_pid"
        exit 0
    fi
fi
if adbd_live && port_listening; then
    echo "[nq-adbd-lite] already running"
    exit 0
fi
if adbd_live; then
    echo "[nq-adbd-lite] stale process without listener; restarting"
    stop_adbd
fi

attempt=1
while [ "$attempt" -le 5 ]; do
    /usr/sbin/nq-adbd-lite "$NQ_ADBD_PORT" &
    echo "$!" >"$PID"
    sleep 1

    if pid_live "$(cat "$PID")" && port_listening; then
        echo "[nq-adbd-lite] pid=$(cat "$PID") port=$NQ_ADBD_PORT"
        exit 0
    fi
    echo "[nq-adbd-lite] start attempt $attempt failed"
    pid_live "$(cat "$PID" 2>/dev/null || true)" && kill "$(cat "$PID")" 2>/dev/null || true
    sleep 1
    attempt=$((attempt + 1))
done

echo "[nq-adbd-lite] failed to stay running"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-play",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

usage() {
    echo "usage: nq-play FILE_OR_URL..." >&2
}

if [ "$#" -eq 0 ]; then
    usage
    exit 2
fi

: "${NQ_PLAY_MIXER_CARD:=0}"
: "${NQ_PLAY_MASTER_VOLUME:=190}"
: "${NQ_PLAY_SPEAKER_VOLUME:=204}"
: "${NQ_PLAY_SPEAKER_SWITCH:=on}"
: "${NQ_PLAY_OUTPUT:=hw:0,0}"
: "${NQ_PLAY_RATE:=48000}"
: "${NQ_PLAY_ENCODING:=s16}"
: "${NQ_PLAY_CHANNELS:=2}"
: "${NQ_PLAY_DEVBUFFER:=0.5}"
: "${NQ_PLAY_BUFFER:=1024}"
: "${NQ_PLAY_PRELOAD:=1}"
: "${NQ_PLAY_VISUALIZER_ENABLE:=0}"
: "${NQ_PLAY_LEVELS:=/run/nexusq-audio-levels}"
: "${NQ_PLAY_LEVEL_UPDATE_MS:=16}"
: "${NQ_PLAY_AUDIO_DELAY_MS:=0}"
: "${NQ_PLAY_STARTUP_MUTE_MS:=0}"
: "${NQ_PLAY_STARTUP_FADE_MS:=0}"
: "${NQ_PLAY_CHIME_TRIGGER:=}"
: "${NQ_PLAY_CHIME_MS:=550}"
: "${NQ_PLAY_CHIME_GAIN:=900}"
: "${NQ_PLAY_CHIME_DUCK_PERCENT:=30}"
: "${NQ_PLAY_APLAY_BUFFER_TIME_US:=80000}"
: "${NQ_PLAY_APLAY_PERIOD_TIME_US:=20000}"

if ! command -v mpg123 >/dev/null 2>&1; then
    echo "nq-play: mpg123 is not installed" >&2
    exit 1
fi

preserve_value() {
    case "${1:-}" in
        ""|preserve|keep|current|none) return 0 ;;
    esac
    return 1
}

if command -v amixer >/dev/null 2>&1; then
    preserve_value "$NQ_PLAY_SPEAKER_SWITCH" || \\
        amixer -q -c "$NQ_PLAY_MIXER_CARD" cset name="Speaker Switch" "$NQ_PLAY_SPEAKER_SWITCH" || true

    if ! preserve_value "$NQ_PLAY_SPEAKER_VOLUME"; then
        speaker_volume="$NQ_PLAY_SPEAKER_VOLUME"
        case "$speaker_volume" in
            *,*) ;;
            *) speaker_volume="$speaker_volume,$speaker_volume" ;;
        esac
        amixer -q -c "$NQ_PLAY_MIXER_CARD" cset name="Speaker Volume" "$speaker_volume" || true
    fi

    preserve_value "$NQ_PLAY_MASTER_VOLUME" || \\
        amixer -q -c "$NQ_PLAY_MIXER_CARD" cset name="Master Volume" "$NQ_PLAY_MASTER_VOLUME" || true
fi

if [ "$NQ_PLAY_VISUALIZER_ENABLE" = "1" ] &&
    [ "$NQ_PLAY_ENCODING" = "s16" ] &&
    command -v nq-pcm-level-tap >/dev/null 2>&1 &&
    command -v aplay >/dev/null 2>&1; then
    mkdir -p "$(dirname "$NQ_PLAY_LEVELS")" 2>/dev/null || true
    mpg123 \\
        --no-control \\
        -s \\
        -r "$NQ_PLAY_RATE" \\
        --resample fine \\
        -e s16 \\
        --buffer "$NQ_PLAY_BUFFER" \\
        --preload "$NQ_PLAY_PRELOAD" \\
        "$@" |
    nq-pcm-level-tap \\
        --levels "$NQ_PLAY_LEVELS" \\
        --update-ms "$NQ_PLAY_LEVEL_UPDATE_MS" \\
        --rate "$NQ_PLAY_RATE" \\
        --channels "$NQ_PLAY_CHANNELS" \\
        --audio-delay-ms "$NQ_PLAY_AUDIO_DELAY_MS" \\
        --startup-mute-ms "$NQ_PLAY_STARTUP_MUTE_MS" \\
        --startup-fade-ms "$NQ_PLAY_STARTUP_FADE_MS" \\
        --chime-trigger "$NQ_PLAY_CHIME_TRIGGER" \\
        --chime-ms "$NQ_PLAY_CHIME_MS" \\
        --chime-gain "$NQ_PLAY_CHIME_GAIN" \\
        --chime-duck-percent "$NQ_PLAY_CHIME_DUCK_PERCENT" |
    aplay \\
        -q \\
        -D "$NQ_PLAY_OUTPUT" \\
        -f S16_LE \\
        -r "$NQ_PLAY_RATE" \\
        -c "$NQ_PLAY_CHANNELS" \\
        --buffer-time="$NQ_PLAY_APLAY_BUFFER_TIME_US" \\
        --period-time="$NQ_PLAY_APLAY_PERIOD_TIME_US"
    exit $?
fi

exec mpg123 \\
    --no-control \\
    -o alsa \\
    -a "$NQ_PLAY_OUTPUT" \\
    -r "$NQ_PLAY_RATE" \\
    --resample fine \\
    -e "$NQ_PLAY_ENCODING" \\
    --devbuffer "$NQ_PLAY_DEVBUFFER" \\
    --buffer "$NQ_PLAY_BUFFER" \\
    --preload "$NQ_PLAY_PRELOAD" \\
    "$@"
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-visualizer-sync-test",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-sync-test.log
LED_DELAY_FILE=/run/nexusq-led-sync-delay-ms

usage() {
    cat >&2 <<'EOF'
usage:
  nq-visualizer-sync-test [LED_DELAY_MS...]
  nq-visualizer-sync-test --sweep

Play metronome-like PCM pulse trains through the normal visualizer tap path.
Watch whether the LED pulse is before or after the audible pip, then tune the
delay. Higher LED_DELAY_MS makes the LED pulse later relative to audio.
EOF
}

: "${NQ_SYNC_RATE:=48000}"
: "${NQ_SYNC_CHANNELS:=2}"
: "${NQ_SYNC_OUTPUT:=hw:0,0}"
: "${NQ_SYNC_LEVELS:=/run/nexusq-audio-levels}"
: "${NQ_SYNC_UPDATE_MS:=10}"
: "${NQ_SYNC_BEATS:=12}"
: "${NQ_SYNC_INTERVAL_MS:=800}"
: "${NQ_SYNC_TONE_MS:=70}"
: "${NQ_SYNC_FREQ:=880}"
: "${NQ_SYNC_AMPLITUDE:=9000}"
: "${NQ_SYNC_LEADIN_MS:=600}"
: "${NQ_SYNC_APLAY_BUFFER_TIME_US:=80000}"
: "${NQ_SYNC_APLAY_PERIOD_TIME_US:=20000}"
: "${NQ_SYNC_AUDIO_DELAY_MS:=0}"
: "${NQ_SYNC_DEFAULT_LED_DELAY_MS:=220}"
: "${NQ_SYNC_SWEEP_DELAYS:=0 40 80 120 160}"
: "${NQ_SYNC_STOP_PLAYER:=1}"

stamp() {
    awk '{ print $1; exit }' /proc/uptime 2>/dev/null || date +%s 2>/dev/null || echo 0
}

log() {
    mkdir -p /run /run/nexusq
    echo "[nq-sync-test] t=$(stamp) $*" | tee -a "$LOG"
}

is_delay() {
    case "${1:-}" in
        ""|*[!0-9]*) return 1 ;;
    esac
    [ "$1" -le 2000 ] 2>/dev/null
}

stop_player() {
    [ "$NQ_SYNC_STOP_PLAYER" = "1" ] || return 0
    command -v nq-somafm-play >/dev/null 2>&1 && nq-somafm-play --stop >/dev/null 2>&1 || true
    for name in mpg123 nq-pcm-level-tap aplay; do
        pids="$(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true)"
        [ -z "$pids" ] || kill $pids 2>/dev/null || true
    done
    sleep 0.25 2>/dev/null || true
}

ensure_ready() {
    if ! command -v nq-pcm-sync-pulse >/dev/null 2>&1; then
        echo "nq-visualizer-sync-test: nq-pcm-sync-pulse missing" >&2
        exit 1
    fi
    if ! command -v nq-pcm-level-tap >/dev/null 2>&1; then
        echo "nq-visualizer-sync-test: nq-pcm-level-tap missing" >&2
        exit 1
    fi
    if ! command -v aplay >/dev/null 2>&1; then
        echo "nq-visualizer-sync-test: aplay missing" >&2
        exit 1
    fi
    if command -v nq-start-led-visualizer >/dev/null 2>&1; then
        nq-start-led-visualizer >/dev/null 2>&1 || true
    fi
}

run_led_delay() {
    led_delay="$1"

    is_delay "$led_delay" || {
        echo "nq-visualizer-sync-test: invalid LED delay: $led_delay" >&2
        exit 2
    }
    is_delay "$NQ_SYNC_AUDIO_DELAY_MS" || {
        echo "nq-visualizer-sync-test: invalid audio delay: $NQ_SYNC_AUDIO_DELAY_MS" >&2
        exit 2
    }

    echo "$led_delay" >"$LED_DELAY_FILE" 2>/dev/null || true
    log "led_delay_ms=$led_delay audio_delay_ms=$NQ_SYNC_AUDIO_DELAY_MS beats=$NQ_SYNC_BEATS interval_ms=$NQ_SYNC_INTERVAL_MS tone_ms=$NQ_SYNC_TONE_MS"
    nq-pcm-sync-pulse \\
        --rate "$NQ_SYNC_RATE" \\
        --channels "$NQ_SYNC_CHANNELS" \\
        --beats "$NQ_SYNC_BEATS" \\
        --interval-ms "$NQ_SYNC_INTERVAL_MS" \\
        --tone-ms "$NQ_SYNC_TONE_MS" \\
        --freq "$NQ_SYNC_FREQ" \\
        --amplitude "$NQ_SYNC_AMPLITUDE" \\
        --leadin-ms "$NQ_SYNC_LEADIN_MS" |
    nq-pcm-level-tap \\
        --levels "$NQ_SYNC_LEVELS" \\
        --update-ms "$NQ_SYNC_UPDATE_MS" \\
        --rate "$NQ_SYNC_RATE" \\
        --channels "$NQ_SYNC_CHANNELS" \\
        --audio-delay-ms "$NQ_SYNC_AUDIO_DELAY_MS" |
    aplay \\
        -q \\
        -D "$NQ_SYNC_OUTPUT" \\
        -f S16_LE \\
        -r "$NQ_SYNC_RATE" \\
        -c "$NQ_SYNC_CHANNELS" \\
        --buffer-time="$NQ_SYNC_APLAY_BUFFER_TIME_US" \\
        --period-time="$NQ_SYNC_APLAY_PERIOD_TIME_US"
    rc="$?"
    log "led_delay_ms=$led_delay done rc=$rc"
    return "$rc"
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --sweep)
        shift
        [ "$#" -eq 0 ] || {
            usage
            exit 2
        }
        set -- $NQ_SYNC_SWEEP_DELAYS
        ;;
    "")
        set -- "$NQ_SYNC_DEFAULT_LED_DELAY_MS"
        ;;
esac

ensure_ready
stop_player

for led_delay in "$@"; do
    run_led_delay "$led_delay" || exit "$?"
    sleep 1 2>/dev/null || true
done
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-somafm-stations",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

usage() {
    cat <<'EOF'
usage:
  nq-somafm-stations
  nq-somafm-stations --help

List current SomaFM station ids and names.

Environment:
  NQ_SOMAFM_CHANNELS_URL      Channel feed URL
  NQ_SOMAFM_CONNECT_TIMEOUT   curl connect timeout seconds
  NQ_SOMAFM_MAX_TIME          curl max time seconds
EOF
}

case "${1:-}" in
    "")
        ;;
    -h|--help)
        [ "$#" -eq 1 ] || { usage >&2; exit 2; }
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_SOMAFM_CHANNELS_URL:=http://somafm.com/channels.xml}"
: "${NQ_SOMAFM_CONNECT_TIMEOUT:=10}"
: "${NQ_SOMAFM_MAX_TIME:=20}"

if ! command -v curl >/dev/null 2>&1; then
    echo "nq-somafm-stations: curl is not installed" >&2
    exit 1
fi

data="$(curl -fsSL --connect-timeout "$NQ_SOMAFM_CONNECT_TIMEOUT" --max-time "$NQ_SOMAFM_MAX_TIME" "$NQ_SOMAFM_CHANNELS_URL")" || {
    echo "nq-somafm-stations: failed to fetch $NQ_SOMAFM_CHANNELS_URL" >&2
    exit 1
}

printf '%s\\n' "$data" | awk '
    function trim(text) {
        sub(/^[[:space:]]*/, "", text)
        sub(/[[:space:]]*$/, "", text)
        return text
    }
    /<channel id="/ {
        id = $0
        sub(/^.*<channel id="/, "", id)
        sub(/".*$/, "", id)
        next
    }
    /<title>/ && id != "" {
        title = $0
        sub(/^.*<title><!\\[CDATA\\[/, "", title)
        sub(/\\]\\]><\\/title>.*$/, "", title)
        sub(/^.*<title>/, "", title)
        sub(/<\\/title>.*$/, "", title)
        printf "%-18s %s\\n", id, trim(title)
        id = ""
    }
'
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-somafm-url",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

usage() {
    cat <<'EOF'
usage:
  nq-somafm-url STATION_ID_OR_URL
  nq-somafm-url --help

Resolve a SomaFM station id, somafm: URI, playlist URL, or direct stream URL
to the first playable stream URL.

Examples:
  nq-somafm-url groovesalad
  nq-somafm-url somafm:dronezone
  nq-somafm-url http://somafm.com/m3u/secretagent.m3u

Use nq-somafm-play --list to show current station ids.
EOF
}

case "${1:-}" in
    -h|--help)
        [ "$#" -eq 1 ] || { usage >&2; exit 2; }
        usage
        exit 0
        ;;
esac

if [ "$#" -ne 1 ]; then
    usage >&2
    exit 2
fi

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_SOMAFM_PLAYLIST_PREFIX:=http://somafm.com/m3u/}"
: "${NQ_SOMAFM_PLAYLIST_SUFFIX:=.m3u}"
: "${NQ_SOMAFM_CONNECT_TIMEOUT:=10}"
: "${NQ_SOMAFM_MAX_TIME:=20}"

target="$1"
case "$target" in
    somafm:*)
        target="${target#somafm:}"
        ;;
esac

case "$target" in
    http://*|https://*)
        case "$target" in
            *.pls|*.m3u|*/m3u/*) playlist="$target" ;;
            *) printf '%s\\n' "$target"; exit 0 ;;
        esac
        ;;
    *[!A-Za-z0-9_-]*|"")
        echo "nq-somafm-url: invalid station id: $target" >&2
        exit 2
        ;;
    *)
        playlist="${NQ_SOMAFM_PLAYLIST_PREFIX}${target}${NQ_SOMAFM_PLAYLIST_SUFFIX}"
        ;;
esac

if ! command -v curl >/dev/null 2>&1; then
    echo "nq-somafm-url: curl is not installed" >&2
    exit 1
fi

data="$(curl -fsSL --connect-timeout "$NQ_SOMAFM_CONNECT_TIMEOUT" --max-time "$NQ_SOMAFM_MAX_TIME" "$playlist")" || {
    echo "nq-somafm-url: failed to fetch $playlist" >&2
    exit 1
}

url="$(printf '%s\\n' "$data" | awk '
    /^[[:space:]]*#/ { next }
    tolower($0) ~ /^file[0-9]*=/ {
        sub(/^[^=]*=/, "")
        print
        exit
    }
    /^https?:\\/\\// {
        print
        exit
    }
')"

case "$url" in
    http://*|https://*) printf '%s\\n' "$url" ;;
    *)
        echo "nq-somafm-url: no stream URL found in $playlist" >&2
        exit 1
        ;;
esac
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-somafm-play",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-somafm.log
PID=/run/nq-somafm.pid
MODE=/run/nq-somafm.mode
PLAYER_PID=/run/nq-somafm-player.pid

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_SOMAFM_STOP_SQUEEZELITE:=1}"
: "${NQ_SOMAFM_MIXER_CARD:=0}"
: "${NQ_SOMAFM_MASTER_VOLUME:=preserve}"
: "${NQ_SOMAFM_SPEAKER_VOLUME:=preserve}"
: "${NQ_SOMAFM_SPEAKER_SWITCH:=on}"
: "${NQ_SOMAFM_OUTPUT:=hw:0,0}"
: "${NQ_SOMAFM_RATE:=48000}"
: "${NQ_SOMAFM_ENCODING:=s16}"
: "${NQ_SOMAFM_DEVBUFFER:=0.15}"
: "${NQ_SOMAFM_BUFFER:=128}"
: "${NQ_SOMAFM_PRELOAD:=0.2}"
: "${NQ_SOMAFM_RESTART:=1}"
: "${NQ_SOMAFM_RESTART_DELAY:=3}"
: "${NQ_SOMAFM_DIRECT_PREFIX:=}"
: "${NQ_SOMAFM_DIRECT_SUFFIX:=}"
: "${NQ_SOMAFM_STOP_GRACE:=0.25}"
: "${NQ_SOMAFM_STOP_POLL_INTERVAL:=0.02}"
: "${NQ_SOMAFM_STOP_POLL_COUNT:=5}"
: "${NQ_SOMAFM_STOP_ORPHAN_PLAYERS:=0}"
: "${NQ_SOMAFM_OUTPUT_RELEASE_DELAY:=0.45}"
: "${NQ_SOMAFM_START_CHECK_DELAY:=0.02}"
: "${NQ_SOMAFM_TIMING:=1}"
: "${NQ_SOMAFM_VISUALIZER_ENABLE:=1}"
: "${NQ_SOMAFM_VISUALIZER_LEVELS:=/run/nexusq-audio-levels}"
: "${NQ_SOMAFM_VISUALIZER_UPDATE_MS:=16}"
: "${NQ_SOMAFM_AUDIO_DELAY_MS:=0}"
: "${NQ_SOMAFM_APLAY_BUFFER_TIME_US:=80000}"
: "${NQ_SOMAFM_APLAY_PERIOD_TIME_US:=20000}"
: "${NQ_SOMAFM_STARTUP_MUTE:=1}"
: "${NQ_SOMAFM_STARTUP_MUTE_MS:=350}"
: "${NQ_SOMAFM_STARTUP_FADE_MS:=200}"
: "${NQ_SOMAFM_CHIME_TRIGGER:=/run/nexusq-audio-chime}"
: "${NQ_SOMAFM_CHIME_MS:=550}"
: "${NQ_SOMAFM_CHIME_GAIN:=900}"
: "${NQ_SOMAFM_CHIME_DUCK_PERCENT:=30}"
: "${NQ_SOMAFM_JUKEBOX_STREAM:=0}"
: "${NQ_SOMAFM_JUKEBOX_URL:=}"
: "${NQ_SOMAFM_SELECT_PREFIX:=}"
: "${NQ_SOMAFM_SELECT_SUFFIX:=}"
: "${NQ_SOMAFM_SELECT_TIMEOUT:=2}"

if [ -n "${NQ_SOMAFM_OUTPUT_RELEASE_DELAY_OVERRIDE:-}" ]; then
    NQ_SOMAFM_OUTPUT_RELEASE_DELAY="$NQ_SOMAFM_OUTPUT_RELEASE_DELAY_OVERRIDE"
fi

usage() {
    cat <<'EOF'
usage:
  nq-somafm-play STATION_ID_OR_URL
  nq-somafm-play --list
  nq-somafm-play --stop
  nq-somafm-play --help

Play a SomaFM station id, somafm: URI, playlist URL, or direct stream URL.

Examples:
  nq-somafm-play groovesalad
  nq-somafm-play dronezone
  nq-somafm-play somafm:secretagent

Commands:
  --list   List current SomaFM station ids and names.
  --stop   Stop local SomaFM playback.

Logs:
  /run/nexusq-somafm.log
EOF
}

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

pid_exists() {
    pid="$1"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

stamp() {
    awk '{ print $1; exit }' /proc/uptime 2>/dev/null || date +%s 2>/dev/null || echo 0
}

timing() {
    [ "$NQ_SOMAFM_TIMING" = "1" ] || return 0
    echo "[nq-somafm] t=$(stamp) $*" >>"$LOG" 2>/dev/null || true
}

short_sleep() {
    delay="$1"
    case "$delay" in
        ""|0|0.0|0.00|0.000) return 0 ;;
    esac
    sleep "$delay" 2>/dev/null || true
}

wait_pid_gone() {
    pid="$1"
    count="$NQ_SOMAFM_STOP_POLL_COUNT"
    case "$count" in
        ""|*[!0-9]*) count=13 ;;
    esac

    i=0
    while [ "$i" -lt "$count" ] 2>/dev/null; do
        pid_exists "$pid" || return 0
        short_sleep "$NQ_SOMAFM_STOP_POLL_INTERVAL"
        i=$((i + 1))
    done
    pid_exists "$pid" && return 1
    return 0
}

wait_pids_gone() {
    pids="$*"
    count="$NQ_SOMAFM_STOP_POLL_COUNT"
    case "$count" in
        ""|*[!0-9]*) count=13 ;;
    esac

    i=0
    while [ "$i" -lt "$count" ] 2>/dev/null; do
        still_live=
        for pid in $pids; do
            pid_exists "$pid" && still_live=1
        done
        [ -n "$still_live" ] || return 0
        short_sleep "$NQ_SOMAFM_STOP_POLL_INTERVAL"
        i=$((i + 1))
    done
    return 1
}

proc_children() {
    pid="$1"
    [ -r "/proc/$pid/task/$pid/children" ] || return 0
    cat "/proc/$pid/task/$pid/children" 2>/dev/null || true
}

stop_pid_file() {
    pid_file="$1"
    [ -s "$pid_file" ] || return 0
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if pid_exists "$old_pid"; then
        timing "stop pid=$old_pid file=$pid_file"
        kill "$old_pid" 2>/dev/null || true
        wait_pid_gone "$old_pid" || true
        pid_exists "$old_pid" && kill -KILL "$old_pid" 2>/dev/null || true
        timing "stopped pid=$old_pid file=$pid_file"
    fi
    rm -f "$pid_file"
    [ "$pid_file" = "$PID" ] && rm -f "$MODE" "$PLAYER_PID"
}

stop_player_tree() {
    [ -s "$PID" ] || return 1
    old_pid="$(cat "$PID" 2>/dev/null || true)"
    [ -n "$old_pid" ] || return 1
    child_pids="$(cat "$PLAYER_PID" 2>/dev/null || true) $(proc_children "$old_pid")"
    pids="$old_pid $child_pids"

    timing "stop player tree pids=$pids"
    kill $pids 2>/dev/null || true
    wait_pids_gone $pids || true
    for pid in $pids; do
        pid_exists "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    wait_pids_gone $pids || true
    rm -f "$PID" "$MODE" "$PLAYER_PID"
    timing "stopped player tree pids=$pids"
    return 0
}

stop_proc_name() {
    name="$1"
    live_pids=
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_exists "$pid" || continue
        live_pids="$live_pids $pid"
    done
    [ -n "$live_pids" ] || return 0
    timing "stop process=$name pids=$live_pids"
    kill $live_pids 2>/dev/null || true
    wait_pids_gone $live_pids || true
    for pid in $live_pids; do
        pid_exists "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    timing "stopped process=$name pids=$live_pids"
}

stop_players() {
    if ! stop_player_tree; then
        stop_proc_name mpg123
    elif [ "$NQ_SOMAFM_STOP_ORPHAN_PLAYERS" = "1" ]; then
        stop_proc_name mpg123
    fi
    stop_proc_name nq-pcm-level-tap
    stop_proc_name aplay
    if [ "$NQ_SOMAFM_STOP_SQUEEZELITE" = "1" ]; then
        if [ -s /run/nq-squeezelite.pid ]; then
            stop_pid_file /run/nq-squeezelite.pid
            stop_proc_name squeezelite
            rm -f /run/nq-squeezelite.pid
        fi
    fi
    if [ -n "$NQ_SOMAFM_OUTPUT_RELEASE_DELAY" ]; then
        timing "audio release wait delay=$NQ_SOMAFM_OUTPUT_RELEASE_DELAY"
        short_sleep "$NQ_SOMAFM_OUTPUT_RELEASE_DELAY"
    fi
}

station_id_for_select() {
    target="$1"
    case "$target" in
        somafm:*)
            target="${target#somafm:}"
            ;;
    esac
    case "$target" in
        *[!A-Za-z0-9_-]*|"") return 1 ;;
    esac
    printf '%s\\n' "$target"
}

start_jukebox_stream_player() {
    [ -n "$NQ_SOMAFM_JUKEBOX_URL" ] || return 1
    if pid_live "$(cat "$PID" 2>/dev/null || true)" && [ "$(cat "$MODE" 2>/dev/null || true)" = "jukebox-stream" ]; then
        return 0
    fi

    stop_players
    (
        trap '' HUP
        export NQ_PLAY_MIXER_CARD="$NQ_SOMAFM_MIXER_CARD"
        export NQ_PLAY_MASTER_VOLUME="$NQ_SOMAFM_MASTER_VOLUME"
        export NQ_PLAY_SPEAKER_VOLUME="$NQ_SOMAFM_SPEAKER_VOLUME"
        export NQ_PLAY_SPEAKER_SWITCH="$NQ_SOMAFM_SPEAKER_SWITCH"
        export NQ_PLAY_OUTPUT="$NQ_SOMAFM_OUTPUT"
        export NQ_PLAY_RATE="$NQ_SOMAFM_RATE"
        export NQ_PLAY_ENCODING="$NQ_SOMAFM_ENCODING"
        export NQ_PLAY_DEVBUFFER="$NQ_SOMAFM_DEVBUFFER"
        export NQ_PLAY_BUFFER="$NQ_SOMAFM_BUFFER"
        export NQ_PLAY_PRELOAD="$NQ_SOMAFM_PRELOAD"
        export NQ_PLAY_VISUALIZER_ENABLE="$NQ_SOMAFM_VISUALIZER_ENABLE"
        export NQ_PLAY_LEVELS="$NQ_SOMAFM_VISUALIZER_LEVELS"
        export NQ_PLAY_LEVEL_UPDATE_MS="$NQ_SOMAFM_VISUALIZER_UPDATE_MS"
        export NQ_PLAY_AUDIO_DELAY_MS="$NQ_SOMAFM_AUDIO_DELAY_MS"
        export NQ_PLAY_CHIME_TRIGGER="$NQ_SOMAFM_CHIME_TRIGGER"
        export NQ_PLAY_CHIME_MS="$NQ_SOMAFM_CHIME_MS"
        export NQ_PLAY_CHIME_GAIN="$NQ_SOMAFM_CHIME_GAIN"
        export NQ_PLAY_CHIME_DUCK_PERCENT="$NQ_SOMAFM_CHIME_DUCK_PERCENT"
        export NQ_PLAY_APLAY_BUFFER_TIME_US="$NQ_SOMAFM_APLAY_BUFFER_TIME_US"
        export NQ_PLAY_APLAY_PERIOD_TIME_US="$NQ_SOMAFM_APLAY_PERIOD_TIME_US"
        while :; do
            /usr/bin/nq-play "$NQ_SOMAFM_JUKEBOX_URL" &
            player_pid="$!"
            echo "$player_pid" >"$PLAYER_PID"
            wait "$player_pid"
            rc="$?"
            rm -f "$PLAYER_PID"
            echo "[nq-somafm] jukebox stream exited rc=$rc; restarting in ${NQ_SOMAFM_RESTART_DELAY}s"
            sleep "$NQ_SOMAFM_RESTART_DELAY"
        done
    ) </dev/null >>"$LOG" 2>&1 &
    echo "$!" >"$PID"
    echo "jukebox-stream" >"$MODE"
    timing "jukebox player spawned pid=$(cat "$PID" 2>/dev/null || true)"
    short_sleep "$NQ_SOMAFM_START_CHECK_DELAY"
    pid_live "$(cat "$PID" 2>/dev/null || true)"
}

play_jukebox_stream() {
    station_id="$1"
    [ -n "$NQ_SOMAFM_SELECT_PREFIX" ] || return 1
    select_url="${NQ_SOMAFM_SELECT_PREFIX}${station_id}${NQ_SOMAFM_SELECT_SUFFIX}"

    mkdir -p /run /run/nexusq
    : >"$LOG"
    {
        echo "[nq-somafm] station=$station_id"
        echo "[nq-somafm] jukebox_url=$NQ_SOMAFM_JUKEBOX_URL"
        echo "[nq-somafm] select_url=$select_url"
        date 2>/dev/null || true
    } >>"$LOG"

    if ! command -v curl >/dev/null 2>&1; then
        echo "nq-somafm-play: curl is not installed" >&2
        return 1
    fi
    timing "select request begin station=$station_id"
    curl -fsS --connect-timeout 1 --max-time "$NQ_SOMAFM_SELECT_TIMEOUT" "$select_url" >>"$LOG" 2>&1 || return 1
    timing "select request done station=$station_id"
    start_jukebox_stream_player || return 1
    timing "jukebox selected station=$station_id pid=$(cat "$PID" 2>/dev/null || true)"
    echo "nq-somafm: jukebox selected $station_id pid=$(cat "$PID" 2>/dev/null || true)"
}

resolve_target() {
    target="$1"
    case "$target" in
        somafm:*)
            target="${target#somafm:}"
            ;;
    esac

    case "$target" in
        http://*|https://*)
            /usr/bin/nq-somafm-url "$target"
            return
            ;;
        *[!A-Za-z0-9_-]*|"")
            /usr/bin/nq-somafm-url "$1"
            return
            ;;
    esac

    if [ -n "$NQ_SOMAFM_DIRECT_PREFIX" ]; then
        printf '%s%s%s\\n' "$NQ_SOMAFM_DIRECT_PREFIX" "$target" "$NQ_SOMAFM_DIRECT_SUFFIX"
        return
    fi

    /usr/bin/nq-somafm-url "$target"
}

if [ "$#" -ne 1 ]; then
    usage >&2
    exit 2
fi

case "${1:-}" in
    --list)
        exec /usr/bin/nq-somafm-stations
        ;;
    --stop)
        stop_players
        exit 0
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    --*)
        echo "nq-somafm-play: unknown option: $1" >&2
        usage >&2
        exit 2
        ;;
esac

station="$1"
if [ "$NQ_SOMAFM_JUKEBOX_STREAM" = "1" ]; then
    station_id="$(station_id_for_select "$station")" || {
        echo "nq-somafm-play: jukebox stream mode requires a station id, got: $station" >&2
        exit 2
    }
    play_jukebox_stream "$station_id" || {
        echo "nq-somafm-play: jukebox stream select failed for station=$station_id" >&2
        exit 1
    }
    exit 0
fi

mkdir -p /run /run/nexusq
: >"$LOG"
timing "request station=$station"
echo "nq-somafm: resolving $station" >&2
url="$(resolve_target "$station")" || exit 1
timing "resolved station=$station"

timing "stop players begin"
stop_players
timing "stop players done"
play_startup_mute_ms=0
play_startup_fade_ms=0
if [ "$NQ_SOMAFM_STARTUP_MUTE" = "1" ] && [ "$NQ_SOMAFM_VISUALIZER_ENABLE" = "1" ]; then
    play_startup_mute_ms="$NQ_SOMAFM_STARTUP_MUTE_MS"
    play_startup_fade_ms="$NQ_SOMAFM_STARTUP_FADE_MS"
    timing "startup pcm gate mute_ms=$play_startup_mute_ms fade_ms=$play_startup_fade_ms"
fi
{
    echo "[nq-somafm] station=$station"
    echo "[nq-somafm] url=$url"
    date 2>/dev/null || true
} >>"$LOG"

(
    trap '' HUP
    export NQ_PLAY_MIXER_CARD="$NQ_SOMAFM_MIXER_CARD"
    export NQ_PLAY_MASTER_VOLUME="$NQ_SOMAFM_MASTER_VOLUME"
    export NQ_PLAY_SPEAKER_VOLUME="$NQ_SOMAFM_SPEAKER_VOLUME"
    export NQ_PLAY_SPEAKER_SWITCH="$NQ_SOMAFM_SPEAKER_SWITCH"
    export NQ_PLAY_OUTPUT="$NQ_SOMAFM_OUTPUT"
    export NQ_PLAY_RATE="$NQ_SOMAFM_RATE"
    export NQ_PLAY_ENCODING="$NQ_SOMAFM_ENCODING"
    export NQ_PLAY_DEVBUFFER="$NQ_SOMAFM_DEVBUFFER"
    export NQ_PLAY_BUFFER="$NQ_SOMAFM_BUFFER"
    export NQ_PLAY_PRELOAD="$NQ_SOMAFM_PRELOAD"
    export NQ_PLAY_VISUALIZER_ENABLE="$NQ_SOMAFM_VISUALIZER_ENABLE"
    export NQ_PLAY_LEVELS="$NQ_SOMAFM_VISUALIZER_LEVELS"
    export NQ_PLAY_LEVEL_UPDATE_MS="$NQ_SOMAFM_VISUALIZER_UPDATE_MS"
    export NQ_PLAY_AUDIO_DELAY_MS="$NQ_SOMAFM_AUDIO_DELAY_MS"
    export NQ_PLAY_STARTUP_MUTE_MS="$play_startup_mute_ms"
    export NQ_PLAY_STARTUP_FADE_MS="$play_startup_fade_ms"
    export NQ_PLAY_CHIME_TRIGGER="$NQ_SOMAFM_CHIME_TRIGGER"
    export NQ_PLAY_CHIME_MS="$NQ_SOMAFM_CHIME_MS"
    export NQ_PLAY_CHIME_GAIN="$NQ_SOMAFM_CHIME_GAIN"
    export NQ_PLAY_CHIME_DUCK_PERCENT="$NQ_SOMAFM_CHIME_DUCK_PERCENT"
    export NQ_PLAY_APLAY_BUFFER_TIME_US="$NQ_SOMAFM_APLAY_BUFFER_TIME_US"
    export NQ_PLAY_APLAY_PERIOD_TIME_US="$NQ_SOMAFM_APLAY_PERIOD_TIME_US"
    if [ "$NQ_SOMAFM_RESTART" != "1" ]; then
        exec /usr/bin/nq-play "$url"
    fi
    while :; do
        /usr/bin/nq-play "$url" &
        player_pid="$!"
        echo "$player_pid" >"$PLAYER_PID"
        wait "$player_pid"
        rc="$?"
        rm -f "$PLAYER_PID"
        echo "[nq-somafm] player exited rc=$rc; restarting in ${NQ_SOMAFM_RESTART_DELAY}s"
        sleep "$NQ_SOMAFM_RESTART_DELAY"
    done
) </dev/null >>"$LOG" 2>&1 &
echo "$!" >"$PID"
echo "direct" >"$MODE"
echo "nq-somafm: starting $station pid=$(cat "$PID" 2>/dev/null || true)" >&2
timing "player spawned station=$station pid=$(cat "$PID" 2>/dev/null || true)"
short_sleep "$NQ_SOMAFM_START_CHECK_DELAY"

if pid_live "$(cat "$PID" 2>/dev/null || true)"; then
    timing "player live station=$station pid=$(cat "$PID" 2>/dev/null || true)"
    echo "nq-somafm: playing $station pid=$(cat "$PID")"
    exit 0
fi

echo "nq-somafm: player failed to stay running; see $LOG" >&2
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-nfc-scan",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

uid_only=0
loop=0
backend="${NQ_NFC_SCAN_BACKEND:-auto}"
timeout="${NQ_NFC_SCAN_TIMEOUT:-15}"

start_pcscd() {
    command -v pcscd >/dev/null 2>&1 || return 0
    if pgrep -x pcscd >/dev/null 2>&1 || pidof pcscd >/dev/null 2>&1; then
        return 0
    fi
    pcscd >/dev/null 2>&1 || true
    sleep 1
}

load_kernel_nfc() {
    command -v modprobe >/dev/null 2>&1 || return 0
    ls /sys/class/nfc/nfc* >/dev/null 2>&1 && return 0

    if ! modprobe pn544_i2c 2>/dev/null; then
        krel="$(uname -r 2>/dev/null || true)"
        if [ -n "$krel" ] && command -v depmod >/dev/null 2>&1; then
            depmod -a "$krel" 2>/dev/null || true
            modprobe pn544_i2c 2>/dev/null && {
                sleep 1
                return 0
            }
        fi
        if [ -n "$krel" ] && command -v insmod >/dev/null 2>&1; then
            mods="/lib/modules/$krel/kernel"
            for ko in \
                "$mods/net/nfc/nfc.ko" \
                "$mods/net/nfc/hci/hci.ko" \
                "$mods/drivers/nfc/pn544/pn544.ko" \
                "$mods/drivers/nfc/pn544/pn544_i2c.ko"; do
                [ -r "$ko" ] || continue
                insmod "$ko" 2>/dev/null || true
            done
        fi
    fi
    sleep 1
}

parse_uid() {
    awk '
        /^nq-nfc-poll: uid=/ {
            sub(/^nq-nfc-poll: uid=/, "")
            gsub(/[^0-9A-Fa-f]/, "")
            print tolower($0)
            exit
        }
        /^nq-nfc-poll: iso15693_uid=/ {
            sub(/^nq-nfc-poll: iso15693_uid=/, "")
            gsub(/[^0-9A-Fa-f]/, "")
            print tolower($0)
            exit
        }
        /UID \\(NFCID1\\):/ {
            for (i = 1; i <= NF; i++) {
                if ($i ~ /^[0-9A-Fa-f][0-9A-Fa-f]$/) {
                    printf "%s", tolower($i)
                }
            }
            printf "\\n"
            exit
        }
    '
}

kernel_available() {
    command -v nq-nfc-poll >/dev/null 2>&1 || return 1
    load_kernel_nfc
    ls /sys/class/nfc/nfc* >/dev/null 2>&1
}

scan_kernel() {
    if [ "$loop" = "1" ]; then
        if [ "$uid_only" = "1" ]; then
            exec nq-nfc-poll --timeout "$timeout" --loop --uid-only
        fi
        exec nq-nfc-poll --timeout "$timeout" --loop
    fi

    out="$(nq-nfc-poll --timeout "$timeout" 2>&1)"
    rc="$?"
    [ "$uid_only" = "1" ] || printf '%s\\n' "$out"
    uid="$(printf '%s\\n' "$out" | parse_uid)"
    if [ -n "$uid" ]; then
        if [ "$uid_only" = "1" ]; then
            printf '%s\\n' "$uid"
        else
            echo "nq-nfc-scan: uid=$uid"
        fi
        exit 0
    fi
    return "$rc"
}

scan_libnfc() {
    if ! command -v nfc-poll >/dev/null 2>&1; then
        echo "nq-nfc-scan: nfc-poll is not installed" >&2
        return 1
    fi

    while :; do
        start_pcscd
        out="$(nfc-poll 2>&1)"
        rc="$?"
        [ "$uid_only" = "1" ] || printf '%s\\n' "$out"
        uid="$(printf '%s\\n' "$out" | parse_uid)"
        if [ -n "$uid" ]; then
            if [ "$uid_only" = "1" ]; then
                printf '%s\\n' "$uid"
            else
                echo "nq-nfc-scan: uid=$uid"
            fi
            [ "$loop" = "1" ] || exit 0
        else
            [ "$loop" = "1" ] || return "$rc"
        fi
        sleep 0.1 2>/dev/null || true
    done
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --uid-only)
            uid_only=1
            shift
            ;;
        --loop)
            loop=1
            shift
            ;;
        --backend)
            [ "$#" -ge 2 ] || {
                echo "usage: nq-nfc-scan [--uid-only] [--loop] [--backend auto|kernel|libnfc] [--timeout seconds]" >&2
                exit 2
            }
            backend="$2"
            shift 2
            ;;
        --timeout)
            [ "$#" -ge 2 ] || {
                echo "usage: nq-nfc-scan [--uid-only] [--loop] [--backend auto|kernel|libnfc] [--timeout seconds]" >&2
                exit 2
            }
            timeout="$2"
            shift 2
            ;;
        -h|--help)
            echo "usage: nq-nfc-scan [--uid-only] [--loop] [--backend auto|kernel|libnfc] [--timeout seconds]"
            exit 0
            ;;
        *)
            echo "usage: nq-nfc-scan [--uid-only] [--loop] [--backend auto|kernel|libnfc] [--timeout seconds]" >&2
            exit 2
            ;;
    esac
done

case "$backend" in
    auto)
        if kernel_available; then
            scan_kernel
            rc="$?"
        else
            scan_libnfc
            rc="$?"
        fi
        ;;
    kernel)
        if ! kernel_available; then
            echo "nq-nfc-scan: kernel NFC device or nq-nfc-poll is missing" >&2
            exit 1
        fi
        scan_kernel
        rc="$?"
        ;;
    libnfc)
        scan_libnfc
        rc="$?"
        ;;
    *)
        echo "nq-nfc-scan: invalid backend: $backend" >&2
        exit 2
        ;;
esac

echo "nq-nfc-scan: no ISO14443A UID found" >&2
exit "$rc"
""",
        0o755,
    )
    write_text(
        rootfs / "usr/bin/nq-nfc-map",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_NFC_TAGS:=/etc/nexusq/somafm-tags.conf}"
: "${NQ_NFC_SCAN_BACKEND:=auto}"
: "${NQ_NFC_MAP_TIMEOUT:=20}"
: "${NQ_NFC_MAP_VALIDATE:=1}"
: "${NQ_NFC_MAP_RESTART:=auto}"

usage() {
    cat <<'USAGE'
Usage:
  nq-nfc-map STATION_ID_OR_URL
  nq-nfc-map --uid UID STATION_ID_OR_URL
  nq-nfc-map --list

Scan one NFC card/tag and persist its UID mapping to a SomaFM station.

Options:
  --uid UID             Use a known UID instead of scanning a card.
  --tags PATH           Tag map path. Default: /etc/nexusq/somafm-tags.conf
  --backend NAME        Scanner backend: auto, kernel, or libnfc.
  --timeout SECONDS     Scan timeout. Default: 20.
  --restart             Restart the jukebox after writing the map.
  --no-restart          Do not restart the jukebox after writing the map.
  --validate            Resolve the SomaFM station before writing. Default.
  --no-validate         Skip station resolution.
  --list                Print the current UID-to-station map.
  -h, --help            Show this help.

Examples:
  nq-somafm-play --list
  nq-nfc-map groovesalad
  nq-nfc-map dronezone
  nq-nfc-map --uid 04:11:22:33:44:55:66 secretagent
USAGE
}

die() {
    echo "nq-nfc-map: $*" >&2
    exit 1
}

normalize_uid() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d ':-'
}

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

stop_jukebox() {
    [ -s /run/nq-nfc-jukebox.pid ] || return 1
    old_pid="$(cat /run/nq-nfc-jukebox.pid 2>/dev/null || true)"
    pid_live "$old_pid" || return 1
    kill -TERM "-$old_pid" 2>/dev/null || true
    kill "$old_pid" 2>/dev/null || true
    sleep 1
    pid_live "$old_pid" && kill -KILL "-$old_pid" 2>/dev/null || true
    pid_live "$old_pid" && kill -KILL "$old_pid" 2>/dev/null || true
    rm -f /run/nq-nfc-jukebox.pid
    return 0
}

start_jukebox() {
    NQ_NFC_JUKEBOX_RESTART=1 /sbin/nq-start-nfc-jukebox >/dev/null 2>&1 || \\
        echo "nq-nfc-map: warning: failed to restart NFC jukebox" >&2
}

restart_on_exit=0
cleanup_jukebox() {
    [ "$restart_on_exit" = "1" ] || return 0
    restart_on_exit=0
    start_jukebox
}

list_map() {
    if [ ! -r "$NQ_NFC_TAGS" ]; then
        echo "nq-nfc-map: no tag map at $NQ_NFC_TAGS" >&2
        exit 1
    fi
    awk '
        BEGIN { FS = "[ \\t]+"; printf "%-18s %s\\n", "UID", "STATION" }
        /^[ \\t]*(#|$)/ { next }
        {
            uid = tolower($1)
            gsub(/[:-]/, "", uid)
            printf "%-18s %s\\n", uid, $2
        }
    ' "$NQ_NFC_TAGS"
}

uid=
list=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --uid)
            [ "$#" -ge 2 ] || die "--uid requires a UID"
            uid="$2"
            shift 2
            ;;
        --tags)
            [ "$#" -ge 2 ] || die "--tags requires a path"
            NQ_NFC_TAGS="$2"
            shift 2
            ;;
        --backend)
            [ "$#" -ge 2 ] || die "--backend requires auto, kernel, or libnfc"
            NQ_NFC_SCAN_BACKEND="$2"
            shift 2
            ;;
        --timeout)
            [ "$#" -ge 2 ] || die "--timeout requires seconds"
            NQ_NFC_MAP_TIMEOUT="$2"
            shift 2
            ;;
        --restart)
            NQ_NFC_MAP_RESTART=1
            shift
            ;;
        --no-restart)
            NQ_NFC_MAP_RESTART=0
            shift
            ;;
        --validate)
            NQ_NFC_MAP_VALIDATE=1
            shift
            ;;
        --no-validate)
            NQ_NFC_MAP_VALIDATE=0
            shift
            ;;
        --list)
            list=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            die "unknown option: $1"
            ;;
        *)
            break
            ;;
    esac
done

if [ "$list" -eq 1 ]; then
    list_map
    exit 0
fi
[ "$#" -eq 1 ] || { usage >&2; exit 2; }

station="$1"
case "$station" in
    ""|*[![:graph:]]*) die "station must be one non-empty word" ;;
esac

case "$NQ_NFC_SCAN_BACKEND" in
    auto|kernel|libnfc) ;;
    *) die "invalid backend: $NQ_NFC_SCAN_BACKEND" ;;
esac

if [ "$NQ_NFC_MAP_VALIDATE" = "1" ] && command -v nq-somafm-url >/dev/null 2>&1; then
    nq-somafm-url "$station" >/dev/null || \\
        die "station did not resolve: $station; use --no-validate to write anyway"
fi

jukebox_was_running=0

if [ -z "$uid" ]; then
    command -v nq-nfc-scan >/dev/null 2>&1 || die "nq-nfc-scan is not installed"
    if [ -s /run/nq-nfc-jukebox.pid ]; then
        old_pid="$(cat /run/nq-nfc-jukebox.pid 2>/dev/null || true)"
        pid_live "$old_pid" && jukebox_was_running=1
    fi
    if [ "$jukebox_was_running" -eq 1 ] && [ "$NQ_NFC_MAP_RESTART" != "0" ]; then
        restart_on_exit=1
        trap cleanup_jukebox EXIT INT TERM
    fi
    stop_jukebox >/dev/null 2>&1 || true
    echo "nq-nfc-map: tap the card for $station" >&2
    uid="$(nq-nfc-scan --uid-only --backend "$NQ_NFC_SCAN_BACKEND" --timeout "$NQ_NFC_MAP_TIMEOUT" 2>/dev/null | awk '/^[0-9a-f]+$/ { print; exit }')"
fi

uid="$(normalize_uid "$uid")"
case "$uid" in
    ""|*[!0-9a-f]*) die "invalid UID: $uid" ;;
esac

mkdir -p "$(dirname "$NQ_NFC_TAGS")" || die "cannot create $(dirname "$NQ_NFC_TAGS")"
tmp="${NQ_NFC_TAGS}.tmp.$$"
if [ -r "$NQ_NFC_TAGS" ]; then
    awk -v target="$uid" '
        BEGIN { FS = "[ \\t]+" }
        /^[ \\t]*(#|$)/ { print; next }
        {
            key = tolower($1)
            gsub(/[:-]/, "", key)
            if (key != target) print
        }
    ' "$NQ_NFC_TAGS" >"$tmp" || die "failed to rewrite $NQ_NFC_TAGS"
else
    {
        echo "# UID              SomaFM station id"
    } >"$tmp" || die "failed to create $NQ_NFC_TAGS"
fi
printf '%-18s %s\\n' "$uid" "$station" >>"$tmp" || die "failed to append mapping"
chmod 644 "$tmp" 2>/dev/null || true
chown 0:0 "$tmp" 2>/dev/null || true
mv "$tmp" "$NQ_NFC_TAGS" || die "failed to install $NQ_NFC_TAGS"

echo "nq-nfc-map: mapped $uid -> $station in $NQ_NFC_TAGS"

case "$NQ_NFC_MAP_RESTART" in
    1)
        restart_on_exit=0
        trap - EXIT INT TERM
        start_jukebox
        ;;
    auto)
        if [ "$jukebox_was_running" -ne 0 ]; then
            restart_on_exit=0
            trap - EXIT INT TERM
            start_jukebox
        fi
        ;;
esac
""",
        0o755,
    )
    write_binary(rootfs / "usr/share/nexusq/nfc-ack.wav", make_tone_wav(), 0o644)
    write_text(
        rootfs / "usr/bin/nq-nfc-ack",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_NFC_ACK_ENABLE:=1}"
: "${NQ_NFC_ACK_WAV:=/usr/share/nexusq/nfc-ack.wav}"
: "${NQ_NFC_ACK_MIXER_CARD:=0}"
: "${NQ_NFC_ACK_SPEAKER_SWITCH:=on}"
: "${NQ_NFC_ACK_OUTPUT:=hw:0,0}"
: "${NQ_NFC_ACK_TIMEOUT:=1}"
: "${NQ_NFC_ACK_STOP_PLAYER:=1}"
: "${NQ_NFC_ACK_STOP_POLL_INTERVAL:=0.01}"
: "${NQ_NFC_ACK_STOP_POLL_COUNT:=12}"
: "${NQ_NFC_ACK_INBAND:=1}"
: "${NQ_NFC_ACK_TRIGGER:=${NQ_SOMAFM_CHIME_TRIGGER:-/run/nexusq-audio-chime}}"
: "${NQ_NFC_ACK_INBAND_HOLD:=0.60}"
: "${NQ_NFC_ACK_INBAND_PRETRIGGERED:=0}"

stamp() {
    awk '{ print $1; exit }' /proc/uptime 2>/dev/null || date +%s 2>/dev/null || echo 0
}

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

stop_pid_file() {
    pid_file="$1"
    [ -s "$pid_file" ] || return 0
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
    [ -z "$old_pid" ] || kill "$old_pid" 2>/dev/null || true
    rm -f "$pid_file"
}

wait_pids_gone() {
    pids="$*"
    count="$NQ_NFC_ACK_STOP_POLL_COUNT"
    case "$count" in ""|*[!0-9]*) count=12 ;; esac

    i=0
    while [ "$i" -lt "$count" ] 2>/dev/null; do
        still_live=
        for pid in $pids; do
            pid_live "$pid" && still_live=1
        done
        [ -n "$still_live" ] || return 0
        sleep "$NQ_NFC_ACK_STOP_POLL_INTERVAL" 2>/dev/null || true
        i=$((i + 1))
    done
    return 1
}

proc_children() {
    pid="$1"
    [ -r "/proc/$pid/task/$pid/children" ] || return 0
    cat "/proc/$pid/task/$pid/children" 2>/dev/null || true
}

proc_name_pids() {
    name="$1"
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_live "$pid" && printf '%s\\n' "$pid"
    done
}

kill_audio_pids() {
    pids="$*"
    [ -n "$(printf '%s' "$pids" | tr -d '[:space:]')" ] || return 0
    kill $pids 2>/dev/null || true
    wait_pids_gone $pids || true
    for pid in $pids; do
        pid_live "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    wait_pids_gone $pids || true
}

collect_audio_pids() {
    old_pid="$(cat /run/nq-somafm.pid 2>/dev/null || true)"
    child_pids=
    [ -z "$old_pid" ] || child_pids="$(cat /run/nq-somafm-player.pid 2>/dev/null || true) $(proc_children "$old_pid")"
    printf '%s\\n' "$old_pid $child_pids $(proc_name_pids mpg123) $(proc_name_pids nq-pcm-level-tap) $(proc_name_pids aplay)"
}

stop_audio_pipeline() {
    kill_audio_pids $(collect_audio_pids)
    for _ in 1 2 3; do
        sleep "$NQ_NFC_ACK_STOP_POLL_INTERVAL" 2>/dev/null || true
        pids="$(proc_name_pids mpg123) $(proc_name_pids nq-pcm-level-tap) $(proc_name_pids aplay)"
        [ -n "$(printf '%s' "$pids" | tr -d '[:space:]')" ] || break
        kill_audio_pids $pids
    done
    rm -f /run/nq-somafm.pid /run/nq-somafm.mode /run/nq-somafm-player.pid
}

audio_pipeline_live() {
    [ -n "$(proc_name_pids nq-pcm-level-tap)" ] || return 1
    [ -n "$(proc_name_pids aplay)" ] || return 1
    return 0
}

trigger_inband_ack() {
    [ "$NQ_NFC_ACK_INBAND" = "1" ] || return 1
    [ -n "$NQ_NFC_ACK_TRIGGER" ] || return 1
    if [ "$NQ_NFC_ACK_INBAND_PRETRIGGERED" != "1" ]; then
        dir="$(dirname "$NQ_NFC_ACK_TRIGGER")"
        mkdir -p "$dir" 2>/dev/null || return 1
        tmp="${NQ_NFC_ACK_TRIGGER}.tmp.$$"
        printf '%s %s\\n' "$(stamp)" "$$" >"$tmp" 2>/dev/null || return 1
        mv "$tmp" "$NQ_NFC_ACK_TRIGGER" 2>/dev/null || {
            rm -f "$tmp" 2>/dev/null || true
            return 1
        }
    fi
    audio_pipeline_live || return 1
    sleep "$NQ_NFC_ACK_INBAND_HOLD" 2>/dev/null || true
    return 0
}

stop_player_tree() {
    [ -s /run/nq-somafm.pid ] || return 1
    old_pid="$(cat /run/nq-somafm.pid 2>/dev/null || true)"
    [ -n "$old_pid" ] || return 1
    child_pids="$(cat /run/nq-somafm-player.pid 2>/dev/null || true) $(proc_children "$old_pid")"
    pids="$old_pid $child_pids"

    kill $pids 2>/dev/null || true
    wait_pids_gone $pids || true
    for pid in $pids; do
        pid_live "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    wait_pids_gone $pids || true
    rm -f /run/nq-somafm.pid /run/nq-somafm.mode /run/nq-somafm-player.pid
    return 0
}

stop_proc_name() {
    name="$1"
    live_pids=
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        pid_live "$pid" || continue
        live_pids="$live_pids $pid"
    done
    [ -z "$live_pids" ] || kill $live_pids 2>/dev/null || true
    wait_pids_gone $live_pids || true
    for pid in $live_pids; do
        pid_live "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
}

[ "$NQ_NFC_ACK_ENABLE" = "1" ] || exit 0
if trigger_inband_ack; then
    exit 0
fi
command -v aplay >/dev/null 2>&1 || exit 0
[ -r "$NQ_NFC_ACK_WAV" ] || exit 0

if [ "$NQ_NFC_ACK_STOP_PLAYER" = "1" ]; then
    stop_audio_pipeline
fi

if command -v amixer >/dev/null 2>&1 && [ -n "$NQ_NFC_ACK_SPEAKER_SWITCH" ]; then
    amixer -q -c "$NQ_NFC_ACK_MIXER_CARD" cset name="Speaker Switch" "$NQ_NFC_ACK_SPEAKER_SWITCH" || true
fi

if command -v timeout >/dev/null 2>&1; then
    timeout "$NQ_NFC_ACK_TIMEOUT" aplay -D "$NQ_NFC_ACK_OUTPUT" -q "$NQ_NFC_ACK_WAV" || true
else
    aplay -D "$NQ_NFC_ACK_OUTPUT" -q "$NQ_NFC_ACK_WAV" || true
fi
exit 0
""",
        0o755,
    )
    write_text(
        rootfs / "usr/sbin/nq-nfc-jukebox",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_NFC_JUKEBOX_ENABLE:=1}"
: "${NQ_NFC_TAGS:=/etc/nexusq/somafm-tags.conf}"
: "${NQ_NFC_UNKNOWN_LOG:=/run/nexusq-nfc-unknown-tags.log}"
: "${NQ_NFC_COOLDOWN_SECONDS:=5}"
: "${NQ_NFC_IDLE_SLEEP:=0}"
: "${NQ_NFC_SCAN_BACKEND:=auto}"
: "${NQ_NFC_SCAN_TIMEOUT:=1}"
: "${NQ_NFC_SCAN_LOOP:=0}"
: "${NQ_NFC_SCAN_RESTART_SLEEP:=1}"
: "${NQ_NFC_DEBUG:=0}"
: "${NQ_NFC_ACK_ENABLE:=1}"
: "${NQ_NFC_ACK_INBAND:=1}"
: "${NQ_NFC_ACK_TRIGGER:=${NQ_SOMAFM_CHIME_TRIGGER:-/run/nexusq-audio-chime}}"
: "${NQ_NFC_AFTER_ACK_OUTPUT_RELEASE_DELAY:=0.05}"
: "${NQ_NFC_TIMING:=1}"

log() {
    if [ "$NQ_NFC_TIMING" = "1" ]; then
        echo "[nq-nfc-jukebox] t=$(stamp) $*"
    else
        echo "[nq-nfc-jukebox] $*"
    fi
}

pid_now() {
    date +%s 2>/dev/null || echo 0
}

stamp() {
    awk '{ print $1; exit }' /proc/uptime 2>/dev/null || date +%s 2>/dev/null || echo 0
}

station_for_uid() {
    uid="$1"
    [ -r "$NQ_NFC_TAGS" ] || return 1
    awk -v target="$uid" '
        BEGIN { FS = "[ \\t]+" }
        /^[ \\t]*(#|$)/ { next }
        {
            key = tolower($1)
            gsub(/[:-]/, "", key)
            if (key == target) {
                print $2
                exit
            }
        }
    ' "$NQ_NFC_TAGS"
}

trigger_inband_ack() {
    [ "$NQ_NFC_ACK_ENABLE" = "1" ] || return 1
    [ "$NQ_NFC_ACK_INBAND" = "1" ] || return 1
    [ -n "$NQ_NFC_ACK_TRIGGER" ] || return 1
    dir="$(dirname "$NQ_NFC_ACK_TRIGGER")"
    mkdir -p "$dir" 2>/dev/null || return 1
    tmp="${NQ_NFC_ACK_TRIGGER}.tmp.$$"
    printf '%s %s\\n' "$(stamp)" "$$" >"$tmp" 2>/dev/null || return 1
    mv "$tmp" "$NQ_NFC_ACK_TRIGGER" 2>/dev/null || {
        rm -f "$tmp" 2>/dev/null || true
        return 1
    }
    return 0
}

use_scan_loop() {
    case "$NQ_NFC_SCAN_LOOP" in
        1|yes|true|on)
            [ "$NQ_NFC_SCAN_BACKEND" = "libnfc" ] && return 1
            return 0
            ;;
        auto)
            [ "$NQ_NFC_SCAN_BACKEND" = "libnfc" ] && return 1
            command -v nq-nfc-poll >/dev/null 2>&1 || return 1
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

if [ "$NQ_NFC_JUKEBOX_ENABLE" != "1" ]; then
    log "disabled; set NQ_NFC_JUKEBOX_ENABLE=1"
    exit 0
fi

if ! command -v nq-nfc-scan >/dev/null 2>&1; then
    log "nq-nfc-scan is not installed"
    exit 1
fi

log "watching for NFC tags"
[ -r "$NQ_NFC_TAGS" ] || log "tag map missing: $NQ_NFC_TAGS"

last_uid=
last_time=0

handle_uid() {
    uid="$1"
    [ -n "$uid" ] || return 0
    now="$(pid_now)"

    if [ "$uid" = "$last_uid" ] && [ "$now" -gt 0 ] 2>/dev/null && [ "$last_time" -gt 0 ] 2>/dev/null; then
        delta=$((now - last_time))
        if [ "$delta" -lt "$NQ_NFC_COOLDOWN_SECONDS" ] 2>/dev/null; then
            log "ignored repeat tag uid=$uid"
            return 0
        fi
    fi

    station="$(station_for_uid "$uid" | head -n 1)"
    if [ -z "$station" ]; then
        log "unknown tag uid=$uid"
        printf '%s\\n' "$uid" >>"$NQ_NFC_UNKNOWN_LOG" 2>/dev/null || true
        last_uid="$uid"
        last_time="$now"
        return 0
    fi

    log "tag uid=$uid station=$station"
    ack_pretriggered=0
    if trigger_inband_ack; then
        ack_pretriggered=1
        log "ack trigger uid=$uid station=$station"
    fi
    play_target="$station"
    resolve_pid=
    resolve_tmp=
    if command -v nq-somafm-url >/dev/null 2>&1; then
        resolve_tmp="/run/nq-nfc-resolve.$$"
        rm -f "$resolve_tmp" "$resolve_tmp.err"
        ( nq-somafm-url "$station" >"$resolve_tmp" 2>"$resolve_tmp.err" ) &
        resolve_pid="$!"
    fi
    play_output_release_delay=
    if [ "$NQ_NFC_ACK_ENABLE" = "1" ] && command -v nq-nfc-ack >/dev/null 2>&1; then
        log "ack begin uid=$uid station=$station"
        if NQ_NFC_ACK_INBAND_PRETRIGGERED="$ack_pretriggered" nq-nfc-ack; then
            play_output_release_delay="$NQ_NFC_AFTER_ACK_OUTPUT_RELEASE_DELAY"
        else
            log "ack failed"
        fi
        log "ack done uid=$uid station=$station"
    fi
    if [ -n "$resolve_pid" ]; then
        if wait "$resolve_pid" && [ -s "$resolve_tmp" ]; then
            play_target="$(head -n 1 "$resolve_tmp")"
            log "resolve done uid=$uid station=$station"
        else
            log "resolve failed uid=$uid station=$station"
        fi
        rm -f "$resolve_tmp" "$resolve_tmp.err"
    fi
    log "play begin uid=$uid station=$station"
    if [ -n "$play_output_release_delay" ]; then
        NQ_SOMAFM_OUTPUT_RELEASE_DELAY_OVERRIDE="$play_output_release_delay" /usr/bin/nq-somafm-play "$play_target" || log "play failed for station=$station"
    else
        /usr/bin/nq-somafm-play "$play_target" || log "play failed for station=$station"
    fi
    log "play done uid=$uid station=$station"
    last_uid="$uid"
    last_time="$now"
}

if use_scan_loop; then
    log "using continuous scan backend=$NQ_NFC_SCAN_BACKEND timeout=$NQ_NFC_SCAN_TIMEOUT"
    while true; do
        nq-nfc-scan --uid-only --loop --backend "$NQ_NFC_SCAN_BACKEND" --timeout "$NQ_NFC_SCAN_TIMEOUT" 2>&1 | while IFS= read -r line; do
            case "$line" in
                [0-9a-f]*)
                    uid="$(printf '%s\\n' "$line" | awk '/^[0-9a-f]+$/ { print; exit }')"
                    [ -z "$uid" ] || handle_uid "$uid"
                    ;;
                *)
                    [ "$NQ_NFC_DEBUG" = "1" ] && printf '%s\\n' "$line"
                    ;;
            esac
        done
        rc="$?"
        log "scan loop exited rc=$rc; restarting"
        sleep "$NQ_NFC_SCAN_RESTART_SLEEP"
    done
fi

while true; do
    out="$(nq-nfc-scan --uid-only --backend "$NQ_NFC_SCAN_BACKEND" --timeout "$NQ_NFC_SCAN_TIMEOUT" 2>&1)"
    rc="$?"
    [ "$NQ_NFC_DEBUG" = "1" ] && printf '%s\\n' "$out"
    uid="$(printf '%s\\n' "$out" | awk '/^[0-9a-f]+$/ { print; exit }')"
    now="$(pid_now)"

    if [ -z "$uid" ]; then
        case "$rc" in
            0|1|16|62) ;;
            *) log "poll exited rc=$rc" ;;
        esac
        last_uid=
        sleep "$NQ_NFC_IDLE_SLEEP"
        continue
    fi

    handle_uid "$uid"
    sleep "$NQ_NFC_IDLE_SLEEP"
done
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-start-nfc-jukebox",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

LOG=/run/nexusq-nfc-jukebox.log
PID=/run/nq-nfc-jukebox.pid
mkdir -p /run /run/nexusq
: >"$LOG"
exec >>"$LOG" 2>&1
trap '' HUP

echo "[nq-nfc-jukebox] starting"
date 2>/dev/null || true

for env in /etc/nexusq/somafm.env /run/nexusq/somafm.env /tmp/somafm.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_NFC_JUKEBOX_ENABLE:=1}"
: "${NQ_NFC_JUKEBOX_RESTART:=0}"

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

stop_old() {
    [ -s "$PID" ] || return 0
    old_pid="$(cat "$PID" 2>/dev/null || true)"
    if pid_live "$old_pid"; then
        kill -TERM "-$old_pid" 2>/dev/null || true
        kill "$old_pid" 2>/dev/null || true
        sleep 1
        pid_live "$old_pid" && kill -KILL "-$old_pid" 2>/dev/null || true
        pid_live "$old_pid" && kill -KILL "$old_pid" 2>/dev/null || true
    fi
    rm -f "$PID"
}

if [ "$NQ_NFC_JUKEBOX_ENABLE" != "1" ]; then
    echo "[nq-nfc-jukebox] disabled; set NQ_NFC_JUKEBOX_ENABLE=1"
    exit 0
fi

if [ "$NQ_NFC_JUKEBOX_RESTART" != "1" ]; then
    if [ -s "$PID" ]; then
        old_pid="$(cat "$PID" 2>/dev/null || true)"
        if pid_live "$old_pid"; then
            echo "[nq-nfc-jukebox] already running pid=$old_pid"
            exit 0
        fi
    fi
else
    stop_old
fi

if ! command -v nq-nfc-scan >/dev/null 2>&1; then
    echo "[nq-nfc-jukebox] nq-nfc-scan command missing"
    exit 1
fi

run_loop='
trap "" HUP
while true; do
    /usr/sbin/nq-nfc-jukebox
    rc="$?"
    echo "[nq-nfc-jukebox] exited rc=$rc; restarting"
    sleep 2
done
'
if command -v setsid >/dev/null 2>&1; then
    setsid sh -c "$run_loop" </dev/null &
else
    sh -c "$run_loop" </dev/null &
fi
echo "$!" >"$PID"
sleep 1

if pid_live "$(cat "$PID" 2>/dev/null || true)"; then
    echo "[nq-nfc-jukebox] pid=$(cat "$PID")"
    exit 0
fi

echo "[nq-nfc-jukebox] failed to stay running"
exit 1
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-player-status",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

echo "Nexus Q player status"

if command -v squeezelite >/dev/null 2>&1; then
    echo "squeezelite: installed"
else
    echo "squeezelite: missing"
fi

if ls /sys/class/nfc/nfc* >/dev/null 2>&1; then
    for dev in /sys/class/nfc/nfc*; do
        [ -e "$dev" ] || continue
        echo "nfc: kernel device $(basename "$dev") present"
    done
else
    echo "nfc: kernel device missing"
fi

if command -v nq-nfc-poll >/dev/null 2>&1; then
    echo "nfc: kernel poller installed"
else
    echo "nfc: kernel poller missing"
fi

if command -v nfc-poll >/dev/null 2>&1; then
    echo "nfc: external-reader libnfc tools installed"
else
    echo "nfc: external-reader libnfc tools missing"
fi

if [ -s /etc/nexusq/squeezelite.env ]; then
    echo "config: /etc/nexusq/squeezelite.env present"
else
    echo "config: /etc/nexusq/squeezelite.env missing"
fi
if [ -s /etc/nexusq/led-visualizer.env ]; then
    echo "config: /etc/nexusq/led-visualizer.env present"
else
    echo "config: /etc/nexusq/led-visualizer.env missing"
fi
if [ -s /etc/nexusq/somafm.env ]; then
    echo "config: /etc/nexusq/somafm.env present"
else
    echo "config: /etc/nexusq/somafm.env missing"
fi
if [ -s /etc/nexusq/somafm-tags.conf ]; then
    echo "config: /etc/nexusq/somafm-tags.conf present"
else
    echo "config: /etc/nexusq/somafm-tags.conf missing"
fi

proc_name_live() {
    name="$1"
    for pid in $(pgrep -x "$name" 2>/dev/null || pidof "$name" 2>/dev/null || true); do
        [ -r "/proc/$pid/status" ] || continue
        state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
        [ "$state" = "Z" ] && continue
        return 0
    done
    return 1
}

pid_live() {
    pid="$1"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/status" ] || return 1
    state="$(awk '/^State:/ { print $2; exit }' "/proc/$pid/status" 2>/dev/null || true)"
    [ "$state" = "Z" ] && return 1
    kill -0 "$pid" 2>/dev/null
}

pid_file_live() {
    pid_file="$1"
    [ -s "$pid_file" ] || return 1
    pid_live "$(cat "$pid_file" 2>/dev/null || true)"
}

if proc_name_live squeezelite; then
    echo "squeezelite: running"
    ps | grep '[s]queezelite' 2>/dev/null || true
else
    echo "squeezelite: not running"
fi

if proc_name_live mpg123; then
    echo "somafm: mpg123 running"
    ps | grep '[m]pg123' 2>/dev/null || true
else
    echo "somafm: mpg123 not running"
fi

if pid_file_live /run/nq-nfc-jukebox.pid; then
    echo "nfc-jukebox: running"
    ps | grep '[n]q-nfc-jukebox' 2>/dev/null || true
else
    echo "nfc-jukebox: not running"
fi

if grep -q 'Steelhead Front Panel' /proc/bus/input/devices 2>/dev/null; then
    echo "input: Steelhead Front Panel present"
else
    echo "input: Steelhead Front Panel missing"
fi

if proc_name_live nq-knob-volume; then
    echo "knob-volume: running"
    ps | grep '[n]q-knob-volume' 2>/dev/null || true
else
    echo "knob-volume: not running"
fi

if [ -e /dev/leds ]; then
    echo "led-ring: /dev/leds present"
else
    echo "led-ring: /dev/leds missing"
fi

if [ -s /run/nexusq-audio-levels ]; then
    echo "audio-levels: /run/nexusq-audio-levels present"
    sed -n '1,9p' /run/nexusq-audio-levels 2>/dev/null || true
else
    echo "audio-levels: /run/nexusq-audio-levels missing"
fi

if ps | grep '[n]q-led-visualiz' >/dev/null 2>&1; then
    echo "led-visualizer: running"
    ps | grep '[n]q-led-visualiz' 2>/dev/null || true
else
    echo "led-visualizer: not running"
fi

if command -v aplay >/dev/null 2>&1; then
    aplay -l 2>/dev/null || true
fi

if [ -s /run/nexusq-squeezelite.log ]; then
    echo "--- /run/nexusq-squeezelite.log ---"
    tail -n 80 /run/nexusq-squeezelite.log 2>/dev/null || cat /run/nexusq-squeezelite.log
fi

if [ -s /run/nexusq-somafm.log ]; then
    echo "--- /run/nexusq-somafm.log ---"
    tail -n 80 /run/nexusq-somafm.log 2>/dev/null || cat /run/nexusq-somafm.log
fi

if [ -s /run/nexusq-nfc-jukebox.log ]; then
    echo "--- /run/nexusq-nfc-jukebox.log ---"
    tail -n 80 /run/nexusq-nfc-jukebox.log 2>/dev/null || cat /run/nexusq-nfc-jukebox.log
fi

if [ -s /run/nexusq-nfc-unknown-tags.log ]; then
    echo "--- /run/nexusq-nfc-unknown-tags.log ---"
    tail -n 40 /run/nexusq-nfc-unknown-tags.log 2>/dev/null || cat /run/nexusq-nfc-unknown-tags.log
fi

if [ -s /run/nexusq-knob-volume.log ]; then
    echo "--- /run/nexusq-knob-volume.log ---"
    tail -n 80 /run/nexusq-knob-volume.log 2>/dev/null || cat /run/nexusq-knob-volume.log
fi

if [ -s /run/nexusq-led-visualizer.log ]; then
    echo "--- /run/nexusq-led-visualizer.log ---"
    tail -n 80 /run/nexusq-led-visualizer.log 2>/dev/null || cat /run/nexusq-led-visualizer.log
fi
""",
        0o755,
    )
    write_text(
        rootfs / "sbin/nq-init",
        """#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /dev/shm /run
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount -t tmpfs tmpfs /run 2>/dev/null || true
grep -q ' /dev/shm ' /proc/mounts 2>/dev/null || mount -t tmpfs tmpfs /dev/shm 2>/dev/null || true
mkdir -p /run
mount -o remount,rw / 2>/dev/null || true

ensure_sbin_compat() {
    mkdir -p /sbin 2>/dev/null || true
    for tool in modprobe depmod; do
        if [ ! -x "/sbin/$tool" ] && [ -x "/usr/sbin/$tool" ]; then
            ln -sf "/usr/sbin/$tool" "/sbin/$tool" 2>/dev/null || true
        fi
    done
}

ensure_sbin_compat

configure_usb_gadget() {
    CFG=/sys/kernel/config
    mkdir -p "$CFG" 2>/dev/null || true
    mount -t configfs configfs "$CFG" 2>/dev/null || true
    [ -d "$CFG/usb_gadget" ] || return

    G="$CFG/usb_gadget/nexusq"
    mkdir -p "$G/strings/0x409" "$G/configs/c.1/strings/0x409" 2>/dev/null || true
    echo 0x18d1 >"$G/idVendor" 2>/dev/null || true
    echo 0x4e23 >"$G/idProduct" 2>/dev/null || true
    echo 0x0200 >"$G/bcdUSB" 2>/dev/null || true
    echo AW1S12250524 >"$G/strings/0x409/serialnumber" 2>/dev/null || true
    echo NexusQ >"$G/strings/0x409/manufacturer" 2>/dev/null || true
    echo "NexusQ Debian" >"$G/strings/0x409/product" 2>/dev/null || true
    echo "ACM+ECM" >"$G/configs/c.1/strings/0x409/configuration" 2>/dev/null || true
    echo 250 >"$G/configs/c.1/MaxPower" 2>/dev/null || true

    mkdir -p "$G/functions/acm.usb0" "$G/functions/ecm.usb0" 2>/dev/null || true
    echo 02:16:42:00:00:02 >"$G/functions/ecm.usb0/dev_addr" 2>/dev/null || true
    echo 02:16:42:00:00:01 >"$G/functions/ecm.usb0/host_addr" 2>/dev/null || true
    ln -s "$G/functions/acm.usb0" "$G/configs/c.1/acm.usb0" 2>/dev/null || true
    ln -s "$G/functions/ecm.usb0" "$G/configs/c.1/ecm.usb0" 2>/dev/null || true

    for udc in /sys/class/udc/*; do
        [ -e "$udc" ] || continue
        echo "${udc##*/}" >"$G/UDC" 2>/dev/null || true
        break
    done
}

start_usb_shell() {
    shell=/bin/sh
    [ -x /bin/bash ] && shell=/bin/bash

    for n in 1 2 3 4 5 6 7 8 9 10; do
        if [ -e /dev/ttyGS0 ]; then
            break
        fi
        if [ -r /sys/class/tty/ttyGS0/dev ]; then
            majmin="$(cat /sys/class/tty/ttyGS0/dev)"
            mknod /dev/ttyGS0 c "${majmin%:*}" "${majmin#*:}" 2>/dev/null || true
            break
        fi
        sleep 1
    done

    if [ -e /dev/ttyGS0 ]; then
        setsid sh -c "exec $shell </dev/ttyGS0 >/dev/ttyGS0 2>&1" &
    fi
}

configure_usb_gadget
start_usb_shell

cmdline_value() {
    key="$1"
    tr ' ' '\\n' </proc/cmdline 2>/dev/null | sed -n "s/^${key}=//p" | head -n 1
}

start_watchdog_feeder() {
    timeout="$(cmdline_value nq.watchdog)"
    case "$timeout" in
        ""|*[!0-9]*) return ;;
    esac
    [ "$timeout" -gt 0 ] 2>/dev/null || return

    for n in 1 2 3 4 5 6 7 8 9 10; do
        [ -e /dev/watchdog ] && break
        sleep 1
    done
    [ -e /dev/watchdog ] || return

    if [ -w /sys/class/watchdog/watchdog0/timeout ]; then
        echo "$timeout" >/sys/class/watchdog/watchdog0/timeout 2>/dev/null || true
    fi
    if [ -w /sys/class/watchdog/watchdog0/nowayout ]; then
        echo 1 >/sys/class/watchdog/watchdog0/nowayout 2>/dev/null || true
    fi

    interval=$((timeout / 3))
    [ "$interval" -ge 5 ] || interval=5
    (
        exec 3>/dev/watchdog || exit 0
        echo "nq watchdog feeder active timeout=${timeout}s interval=${interval}s" >/dev/console 2>/dev/null || true
        while true; do
            echo 1 >&3
            sleep "$interval"
        done
    ) &
    echo "$!" >/run/nq-watchdog.pid
}

start_watchdog_feeder

autoreboot="$(cmdline_value nq.autoreboot)"
case "$autoreboot" in
    ""|*[!0-9]*) autoreboot=0 ;;
esac
if [ "$autoreboot" -gt 0 ]; then
    (
        sleep "$autoreboot"
        echo "nq autoreboot fired after ${autoreboot}s" >/dev/console 2>/dev/null || true
        /sbin/nq-reboot-fastboot
    ) &
    echo "$!" >/run/nq-autoreboot.pid
fi

ip link set lo up 2>/dev/null || true
ip link set usb0 up 2>/dev/null || true
ip addr add 169.254.42.2/16 dev usb0 2>/dev/null || true
ip addr add 172.16.42.2/24 dev usb0 2>/dev/null || true

if [ -x /sbin/nq-start-adbd ]; then
    /sbin/nq-start-adbd || true
elif [ -x /usr/sbin/nq-start-adbd ]; then
    /usr/sbin/nq-start-adbd || true
fi

if [ -s /run/nexusq/wpa_supplicant.conf ] || [ -s /etc/nexusq/wpa_supplicant.conf ] || [ -s /tmp/wpa_supplicant.conf ]; then
    /sbin/nq-start-network
fi

if [ -x /sbin/nq-load-input ]; then
    /sbin/nq-load-input || true
fi

if [ -x /sbin/nq-load-audio ]; then
    /sbin/nq-load-audio || true
fi

if [ -x /sbin/nq-start-squeezelite ]; then
    /sbin/nq-start-squeezelite || true
fi

if [ -x /sbin/nq-start-knob-volume ]; then
    /sbin/nq-start-knob-volume || true
fi

if [ -x /sbin/nq-start-led-visualizer ]; then
    /sbin/nq-start-led-visualizer || true
fi

if [ -x /sbin/nq-start-nfc-jukebox ]; then
    /sbin/nq-start-nfc-jukebox || true
fi

if command -v busybox >/dev/null 2>&1; then
    shell=/bin/sh
    [ -x /bin/bash ] && shell=/bin/bash
    busybox telnetd -l "$shell" -p 2323 &
fi

echo "Nexus Q Debian rescue shell on serial; usb0: 169.254.42.2"
if [ -x /bin/bash ]; then
    exec /bin/bash
fi
exec /bin/sh
""",
        0o755,
    )
    write_text(rootfs / "etc/fstab", "proc /proc proc defaults 0 0\n")
    write_text(rootfs / "etc/resolv.conf", "nameserver 1.1.1.1\n")
    write_text(rootfs / "etc/motd", "Nexus Q Debian trixie armhf rootfs\n")
    write_text(
        rootfs / "etc/nexusq/README",
        """Nexus Q appliance provisioning

Place persistent device-local configuration here with /sbin/nq-provision.
Do not bake Wi-Fi passwords or private keys into public rootfs images.

Expected files:
- /etc/nexusq/wpa_supplicant.conf
- /etc/nexusq/authorized_keys
- /etc/nexusq/input.env
- /etc/nexusq/squeezelite.env
- /etc/nexusq/knob-volume.env
- /etc/nexusq/led-visualizer.env
- /etc/nexusq/somafm.env
- /etc/nexusq/somafm-tags.conf
- /etc/nexusq/adbd.env

Runtime-only test files in /run/nexusq override these persistent files.
""",
        0o644,
    )
    (rootfs / "var/lib/nexusq").mkdir(parents=True, exist_ok=True)
    (rootfs / "var/lib/nexusq").chmod(0o700)

    for src, dest in (
        (root / "artifacts/bin/reboot-bootloader", rootfs / "sbin/reboot-bootloader"),
        (root / "artifacts/bin/nq-knob-volume", rootfs / "usr/sbin/nq-knob-volume"),
        (root / "artifacts/bin/nq-adbd-lite", rootfs / "usr/sbin/nq-adbd-lite"),
        (root / "artifacts/bin/nq-avr-i2c", rootfs / "usr/sbin/nq-avr-i2c"),
        (root / "artifacts/bin/nq-led-visualizer", rootfs / "usr/sbin/nq-led-visualizer"),
        (root / "artifacts/bin/nq-pcm-level-tap", rootfs / "usr/bin/nq-pcm-level-tap"),
        (root / "artifacts/bin/nq-pcm-sync-pulse", rootfs / "usr/bin/nq-pcm-sync-pulse"),
        (root / "artifacts/bin/nq-nfc-poll", rootfs / "usr/bin/nq-nfc-poll"),
        (root / "build/seed-rng-arm", rootfs / "sbin/seed-rng"),
    ):
        if src.exists():
            shutil.copy2(src, dest)
            set_owner_mode(dest, 0o755)

    firmware = rootfs / "lib/firmware"
    for name in ("regulatory.db", "regulatory.db.p7s"):
        dest = firmware / name
        if dest.exists():
            continue
        for suffix in ("-debian", "-upstream"):
            src = firmware / f"{name}{suffix}"
            if src.exists():
                dest.symlink_to(src.name)
                break


def next_free_system_id(used_ids):
    for candidate in range(100, 1000):
        if candidate not in used_ids:
            return candidate
    raise RuntimeError("no free system uid/gid available")


def ensure_system_account(
    rootfs,
    name,
    preferred_uid,
    preferred_gid,
    home="/nonexistent",
    shell="/usr/sbin/nologin",
):
    group_path = rootfs / "etc/group"
    groups = group_path.read_text().splitlines()
    group_ids = set()
    group_gid = None
    for line in groups:
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) < 3:
            continue
        try:
            gid = int(parts[2])
        except ValueError:
            continue
        group_ids.add(gid)
        if parts[0] == name:
            group_gid = gid
    if group_gid is None:
        group_gid = preferred_gid if preferred_gid not in group_ids else next_free_system_id(group_ids)
        groups.append(f"{name}:x:{group_gid}:")
        write_text(group_path, "\n".join(groups) + "\n")

    passwd_path = rootfs / "etc/passwd"
    shadow_path = rootfs / "etc/shadow"
    passwd = passwd_path.read_text().splitlines()
    shadow = shadow_path.read_text().splitlines()
    user_ids = set()
    user_exists = False
    for line in passwd:
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) < 4:
            continue
        try:
            uid = int(parts[2])
        except ValueError:
            continue
        user_ids.add(uid)
        if parts[0] == name:
            user_exists = True
    if not user_exists:
        uid = preferred_uid if preferred_uid not in user_ids else next_free_system_id(user_ids)
        passwd.append(f"{name}:x:{uid}:{group_gid}::{home}:{shell}")
        write_text(passwd_path, "\n".join(passwd) + "\n")

    shadow_users = {line.split(":", 1)[0] for line in shadow if line and not line.startswith("#")}
    if name not in shadow_users:
        shadow.append(f"{name}:*:19723:0:99999:7:::")
        write_text(shadow_path, "\n".join(shadow) + "\n", 0o600)


def configure_base_accounts(rootfs):
    passwd_master = rootfs / "usr/share/base-passwd/passwd.master"
    group_master = rootfs / "usr/share/base-passwd/group.master"
    if not passwd_master.exists() or not group_master.exists():
        return

    group_path = rootfs / "etc/group"
    groups = group_path.read_text().splitlines()
    existing_groups = {line.split(":", 1)[0] for line in groups if line and not line.startswith("#")}
    for line in group_master.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name = line.split(":", 1)[0]
        if name not in existing_groups:
            groups.append(line)
            existing_groups.add(name)
    write_text(group_path, "\n".join(groups) + "\n")

    passwd_path = rootfs / "etc/passwd"
    shadow_path = rootfs / "etc/shadow"
    passwd = passwd_path.read_text().splitlines()
    shadow = shadow_path.read_text().splitlines()
    existing_users = {line.split(":", 1)[0] for line in passwd if line and not line.startswith("#")}
    existing_shadow = {line.split(":", 1)[0] for line in shadow if line and not line.startswith("#")}
    for line in passwd_master.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        name = parts[0]
        if name not in existing_users:
            parts[1] = "x"
            passwd.append(":".join(parts))
            existing_users.add(name)
        if name not in existing_shadow:
            shadow.append(f"{name}:*:19723:0:99999:7:::")
            existing_shadow.add(name)
    write_text(passwd_path, "\n".join(passwd) + "\n")
    write_text(shadow_path, "\n".join(shadow) + "\n", 0o600)
    ensure_system_account(rootfs, "ntpsec", 101, 102)


def configure_ca_certificates(rootfs):
    cert_root = rootfs / "usr/share/ca-certificates"
    certs = sorted(cert_root.rglob("*.crt")) if cert_root.exists() else []
    if not certs:
        return

    rels = [cert.relative_to(cert_root).as_posix() for cert in certs]
    write_text(rootfs / "etc/ca-certificates.conf", "\n".join(rels) + "\n")

    bundle = rootfs / "etc/ssl/certs/ca-certificates.crt"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with bundle.open("wb") as out:
        for cert in certs:
            data = cert.read_bytes()
            out.write(data)
            if not data.endswith(b"\n"):
                out.write(b"\n")
    set_owner_mode(bundle, 0o644)


def configure_standard_modes(rootfs):
    for path in (rootfs / "tmp", rootfs / "var/tmp"):
        path.mkdir(parents=True, exist_ok=True)
        set_owner_mode(path, 0o1777)
    for path in (rootfs / "run", rootfs / "var", rootfs / "var/lib"):
        if path.exists():
            set_owner_mode(path, path.stat().st_mode & 0o7777)


def ensure_relative_symlink(rootfs, link, target):
    path = rootfs / link
    target_path = path.parent / target
    if not target_path.exists():
        return
    if path.exists() or path.is_symlink():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def configure_basic_alternatives(rootfs):
    ensure_relative_symlink(rootfs, "usr/bin/awk", "gawk")
    ensure_relative_symlink(rootfs, "usr/bin/mpg123", "mpg123.bin")
    ensure_relative_symlink(rootfs, "usr/bin/mp3-decoder", "mpg123.bin")


def remove_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def strip_doc_payload(rootfs):
    doc_dir = rootfs / "usr/share/doc"
    if not doc_dir.exists():
        return
    for package_doc in doc_dir.iterdir():
        if package_doc.is_symlink() or package_doc.is_file():
            continue
        for child in package_doc.iterdir():
            if child.name == "copyright":
                continue
            remove_path(child)


def strip_nonessential_payload(rootfs):
    strip_doc_payload(rootfs)
    for rel in (
        "usr/share/info",
        "usr/share/lintian",
        "usr/share/man",
        "var/cache/apt",
        "var/lib/apt/lists",
    ):
        remove_path(rootfs / rel)

    locale_dir = rootfs / "usr/share/locale"
    if locale_dir.exists():
        for child in locale_dir.iterdir():
            remove_path(child)

    for python_dir in (rootfs / "usr/lib").glob("python*"):
        if not python_dir.is_dir():
            continue
        for rel in ("test", "tests"):
            remove_path(python_dir / rel)
        for pycache in list(python_dir.rglob("__pycache__")):
            remove_path(pycache)

    for rel in (
        "var/cache/apt/archives/partial",
        "var/lib/apt/lists/partial",
    ):
        path = rootfs / rel
        path.mkdir(parents=True, exist_ok=True)
        set_owner_mode(path, 0o755)


def write_dpkg_status(rootfs, packages, selected):
    dpkg_dir = rootfs / "var" / "lib" / "dpkg"
    dpkg_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ("alternatives", "info", "parts", "triggers", "updates"):
        (dpkg_dir / subdir).mkdir(exist_ok=True)

    stanzas = []
    keep_fields = [
        "Package",
        "Status",
        "Priority",
        "Section",
        "Installed-Size",
        "Maintainer",
        "Architecture",
        "Version",
        "Provides",
        "Pre-Depends",
        "Depends",
        "Recommends",
        "Suggests",
        "Conffiles",
        "Description",
    ]
    for name in sorted(selected):
        fields = dict(packages[name])
        fields["Status"] = "install ok installed"
        lines = []
        for field in keep_fields:
            value = fields.get(field)
            if not value:
                continue
            if "\n" in value:
                first, *rest = value.splitlines()
                lines.append(f"{field}: {first}")
                lines.extend(f" {line}" for line in rest)
            else:
                lines.append(f"{field}: {value}")
        stanzas.append("\n".join(lines))

    write_text(dpkg_dir / "status", "\n\n".join(stanzas) + "\n")
    write_text(dpkg_dir / "available", "")


def make_ext4(rootfs, image, size_mb):
    image.parent.mkdir(parents=True, exist_ok=True)
    if image.exists():
        image.unlink()
    run(
        [
            "/opt/homebrew/opt/e2fsprogs/sbin/mke2fs",
            "-t",
            "ext4",
            "-d",
            str(rootfs),
            "-L",
            "nq-debian",
            str(image),
            f"{size_mb}M",
        ]
    )


def main():
    maybe_reexec_under_fakeroot()

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    parser.add_argument("--size-mb", default=768, type=int)
    parser.add_argument("--no-ext4", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    work = root / "build" / "debian-trixie-armhf"
    cache = root / "downloads" / "debian-trixie-armhf"
    rootfs = work / "rootfs"
    packages = {}
    provides = {}

    for component in COMPONENTS:
        pkg_xz = cache / f"{component}_Packages.xz"
        url = f"{MIRROR}/dists/{SUITE}/{component}/binary-{ARCH}/Packages.xz"
        download(url, pkg_xz)
        component_packages, component_provides = parse_packages(pkg_xz, component)
        packages.update(component_packages)
        for virtual, providers in component_provides.items():
            provides.setdefault(virtual, []).extend(providers)

    requested = {
        name
        for name, fields in packages.items()
        if fields.get("Essential") == "yes" or fields.get("Priority") == "required"
    }
    requested.update(EXTRA_PACKAGES)

    selected, missing = resolve(packages, provides, requested)
    print(f"selected {len(selected)} packages")
    if missing:
        print("unresolved virtual/optional dependencies:")
        for name in sorted(missing):
            print(f"  {name}")

    debs = []
    for name in sorted(selected):
        fields = packages[name]
        deb = cache / Path(fields["Filename"]).name
        download(f"{MIRROR}/{fields['Filename']}", deb)
        debs.append(deb)

    if rootfs.exists():
        shutil.rmtree(rootfs)
    rootfs.mkdir(parents=True)
    for deb in debs:
        extract_deb(deb, rootfs)

    configure_rootfs(root, rootfs)
    configure_base_accounts(rootfs)
    configure_ca_certificates(rootfs)
    configure_standard_modes(rootfs)
    configure_basic_alternatives(rootfs)
    write_dpkg_status(rootfs, packages, selected)
    strip_nonessential_payload(rootfs)

    manifest = work / "packages.txt"
    manifest.write_text("\n".join(sorted(selected)) + "\n")
    print(f"wrote {manifest}")

    if not args.no_ext4:
        make_ext4(rootfs, root / "artifacts" / "debian-trixie-armhf-rootfs.ext4", args.size_mb)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
