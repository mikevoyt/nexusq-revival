#!/bin/sh

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

cmdline_value() {
    key="$1"
    tr ' ' '\n' </proc/cmdline 2>/dev/null | sed -n "s/^${key}=//p" | head -n 1
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

configure_usb_gadget
start_usb_shell
start_watchdog_feeder

autoreboot="$(cmdline_value nq.autoreboot)"
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

if [ -x /sbin/nq-load-audio ]; then
    /sbin/nq-load-audio || true
fi

if [ -x /sbin/nq-start-squeezelite ]; then
    /sbin/nq-start-squeezelite || true
fi

if command -v busybox >/dev/null 2>&1; then
    busybox telnetd -l /bin/sh -p 2323 &
fi

echo "Nexus Q Debian rescue shell on serial; usb0: 169.254.42.2"
exec /bin/sh
