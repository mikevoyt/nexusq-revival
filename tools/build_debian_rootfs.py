#!/usr/bin/env python3

import argparse
import lzma
import os
import re
import secrets
import shutil
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
    "ca-certificates",
    "busybox-static",
    "dropbear-bin",
    "mpg123",
    "openssh-client",
    "openssh-sftp-server",
    "iproute2",
    "ifupdown",
    "isc-dhcp-client",
    "kmod",
    "netbase",
    "procps",
    "psmisc",
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
    "curl",
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
    write_text(rootfs / "etc/passwd", "root:x:0:0:root:/root:/bin/sh\n")
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

if pgrep -x squeezelite >/dev/null 2>&1 || pidof squeezelite >/dev/null 2>&1; then
    echo "squeezelite: running"
else
    echo "squeezelite: not running"
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
RNG_DEST="$STATE_DIR/rng.seed"

usage() {
    cat <<'USAGE'
Usage: nq-provision [options]

Persist appliance provisioning files into the Debian rootfs.

Options:
  --wifi PATH              Copy PATH to /etc/nexusq/wpa_supplicant.conf
  --authorized-keys PATH   Copy PATH to /etc/nexusq/authorized_keys
  --squeezelite PATH       Copy PATH to /etc/nexusq/squeezelite.env
  --rng-seed PATH          Copy PATH to /var/lib/nexusq/rng.seed
  --clear-wifi             Remove persistent Wi-Fi config
  --clear-authorized-keys  Remove persistent SSH authorized_keys
  --clear-squeezelite      Remove persistent Squeezelite config
  --clear-rng-seed         Remove persistent RNG seed
  --cancel-autoreboot      Cancel the current safety return-to-fastboot timer
  --start-network          Start or restart Wi-Fi, DHCP, and Dropbear
  --start-squeezelite      Start or restart the Music Assistant player endpoint
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
rng_src=
clear_wifi=0
clear_auth=0
clear_squeezelite=0
clear_rng=0
cancel_autoreboot=0
start_network=0
start_squeezelite=0
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
[ "$clear_rng" -eq 0 ] || { rm -f "$RNG_DEST"; echo "removed $RNG_DEST"; }

[ -z "$wifi_src" ] || copy_secret "$wifi_src" "$WPA_DEST" 600
[ -z "$auth_src" ] || copy_secret "$auth_src" "$AUTH_DEST" 600
[ -z "$squeezelite_src" ] || copy_secret "$squeezelite_src" "$SQUEEZELITE_DEST" 644
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

if [ "$show_status" -eq 1 ] || [ "$start_network" -eq 1 ] || [ "$start_squeezelite" -eq 1 ]; then
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

echo "[nq-squeezelite] starting"
date 2>/dev/null || true

for env in /etc/nexusq/squeezelite.env /run/nexusq/squeezelite.env /tmp/squeezelite.env; do
    [ -r "$env" ] || continue
    # shellcheck disable=SC1090
    . "$env"
done

: "${NQ_SQUEEZELITE_ENABLE:=0}"
: "${NQ_SQUEEZELITE_NAME:=Nexus Q}"
: "${NQ_SQUEEZELITE_OUTPUT:=hw:0,0}"
: "${NQ_SQUEEZELITE_RATES:=48000}"
: "${NQ_SQUEEZELITE_CLOSE_TIMEOUT:=5}"
: "${NQ_SQUEEZELITE_MIXER_CARD:=0}"
: "${NQ_SQUEEZELITE_MASTER_VOLUME:=190}"
: "${NQ_SQUEEZELITE_SPEAKER_VOLUME:=204}"
: "${NQ_SQUEEZELITE_SPEAKER_SWITCH:=on}"
: "${NQ_SQUEEZELITE_RESTART:=0}"

if [ "$NQ_SQUEEZELITE_ENABLE" != "1" ]; then
    echo "[nq-squeezelite] disabled; set NQ_SQUEEZELITE_ENABLE=1"
    exit 0
fi

if ! command -v squeezelite >/dev/null 2>&1; then
    echo "[nq-squeezelite] squeezelite command missing"
    exit 1
fi

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
    if [ -s "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
        echo "[nq-squeezelite] already running pid=$(cat "$PID")"
        exit 0
    fi
    if pgrep -x squeezelite >/dev/null 2>&1 || pidof squeezelite >/dev/null 2>&1; then
        echo "[nq-squeezelite] already running"
        exit 0
    fi
else
    killall squeezelite 2>/dev/null || true
    pkill -x squeezelite 2>/dev/null || true
    sleep 1
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

echo "[nq-squeezelite] exec: $*"
"$@" &
echo "$!" >"$PID"
sleep 1

if kill -0 "$(cat "$PID")" 2>/dev/null; then
    echo "[nq-squeezelite] pid=$(cat "$PID")"
    exit 0
fi

echo "[nq-squeezelite] failed to stay running"
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
: "${NQ_PLAY_DEVBUFFER:=0.5}"
: "${NQ_PLAY_BUFFER:=1024}"
: "${NQ_PLAY_PRELOAD:=1}"

if ! command -v mpg123 >/dev/null 2>&1; then
    echo "nq-play: mpg123 is not installed" >&2
    exit 1
fi

if command -v amixer >/dev/null 2>&1; then
    speaker_volume="$NQ_PLAY_SPEAKER_VOLUME"
    case "$speaker_volume" in
        *,*) ;;
        *) speaker_volume="$speaker_volume,$speaker_volume" ;;
    esac

    amixer -q -c "$NQ_PLAY_MIXER_CARD" cset name="Speaker Switch" "$NQ_PLAY_SPEAKER_SWITCH" || true
    amixer -q -c "$NQ_PLAY_MIXER_CARD" cset name="Speaker Volume" "$speaker_volume" || true
    amixer -q -c "$NQ_PLAY_MIXER_CARD" cset name="Master Volume" "$NQ_PLAY_MASTER_VOLUME" || true
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

if [ -s /etc/nexusq/squeezelite.env ]; then
    echo "config: /etc/nexusq/squeezelite.env present"
else
    echo "config: /etc/nexusq/squeezelite.env missing"
fi

if pgrep -x squeezelite >/dev/null 2>&1 || pidof squeezelite >/dev/null 2>&1; then
    echo "squeezelite: running"
    ps | grep '[s]queezelite' 2>/dev/null || true
else
    echo "squeezelite: not running"
fi

if command -v aplay >/dev/null 2>&1; then
    aplay -l 2>/dev/null || true
fi

if [ -s /run/nexusq-squeezelite.log ]; then
    echo "--- /run/nexusq-squeezelite.log ---"
    tail -n 80 /run/nexusq-squeezelite.log 2>/dev/null || cat /run/nexusq-squeezelite.log
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
mkdir -p /dev/pts /run
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount -t tmpfs tmpfs /run 2>/dev/null || true
mkdir -p /run
mount -o remount,rw / 2>/dev/null || true

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
        setsid sh -c 'exec /bin/sh </dev/ttyGS0 >/dev/ttyGS0 2>&1' &
    fi
}

configure_usb_gadget
start_usb_shell

autoreboot="$(tr ' ' '\\n' </proc/cmdline 2>/dev/null | sed -n 's/^nq.autoreboot=//p' | head -n 1)"
case "$autoreboot" in
    ""|*[!0-9]*) autoreboot=300 ;;
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

if [ -s /run/nexusq/wpa_supplicant.conf ] || [ -s /etc/nexusq/wpa_supplicant.conf ] || [ -s /tmp/wpa_supplicant.conf ]; then
    /sbin/nq-start-network
fi

if [ -x /sbin/nq-start-squeezelite ]; then
    /sbin/nq-start-squeezelite || true
fi

if command -v busybox >/dev/null 2>&1; then
    busybox telnetd -l /bin/sh -p 2323 &
fi

echo "Nexus Q Debian rescue shell on serial; usb0: 169.254.42.2"
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
- /etc/nexusq/squeezelite.env

Runtime-only test files in /run/nexusq override these persistent files.
""",
        0o644,
    )
    (rootfs / "var/lib/nexusq").mkdir(parents=True, exist_ok=True)
    (rootfs / "var/lib/nexusq").chmod(0o700)

    for src, dest in (
        (root / "artifacts/bin/reboot-bootloader", rootfs / "sbin/reboot-bootloader"),
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
