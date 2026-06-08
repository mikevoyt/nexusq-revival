#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BASE_LIST="$ROOT/initramfs/initramfs.list"
WIFI_LIST="$ROOT/build/nexusq-initramfs-wifi.list"
OUT_CPIO="$ROOT/artifacts/nexusq-initramfs-wifi.cpio"
OUT_GZ="$ROOT/artifacts/nexusq-initramfs-wifi.cpio.gz"
DEB="$ROOT/build/debian-trixie-armhf/rootfs"
LIB="$DEB/usr/lib/arm-linux-gnueabihf"
ARM_CC="${ARM_CC:-${CROSS_COMPILE:-/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/bin/arm-none-eabi-}gcc}"
SEED_RNG="$ROOT/build/seed-rng-arm"

required_files="
$DEB/usr/sbin/wpa_supplicant
$DEB/usr/sbin/wpa_cli
$DEB/usr/sbin/dropbear
$DEB/usr/bin/dropbearkey
$LIB/ld-linux-armhf.so.3
$LIB/libc.so.6
$LIB/libcrypt.so.1.1.0
$LIB/libm.so.6
$LIB/libcrypto.so.3
$LIB/libssl.so.3
$LIB/libpcsclite.so.1
$LIB/libdbus-1.so.3.38.3
$LIB/libnl-3.so.200.26.0
$LIB/libnl-genl-3.so.200.26.0
$LIB/libnl-route-3.so.200.26.0
$LIB/libreadline.so.8.2
$LIB/libtinfo.so.6.5
$LIB/libsystemd.so.0.40.0
$LIB/libcap.so.2.75
$LIB/libz.so.1.3.1
$LIB/libzstd.so.1.5.7
$LIB/libtomcrypt.so.1.0.1
$LIB/libtommath.so.1.3.0
$LIB/libgmp.so.10.5.0
"

for f in $required_files; do
	[ -f "$f" ] || {
		echo "missing $f; build the Debian rootfs first" >&2
		exit 1
	}
done

mkdir -p "$ROOT/build" "$ROOT/artifacts"

"$ARM_CC" -nostdlib -static -fno-builtin -fno-stack-protector \
	-march=armv7-a -marm -Wl,-e,_start -Wl,--build-id=none \
	-Wl,-Ttext-segment=0x10000 \
	-o "$SEED_RNG" "$ROOT/initramfs/seed-rng.c"

cp "$BASE_LIST" "$WIFI_LIST"
cat >>"$WIFI_LIST" <<'EOF'
dir /var 755 0 0
dir /var/run 755 0 0
dir /etc 755 0 0
dir /etc/dropbear 700 0 0
dir /root 700 0 0
dir /root/.ssh 700 0 0
dir /usr 755 0 0
dir /usr/sbin 755 0 0
dir /usr/bin 755 0 0
dir /lib/arm-linux-gnueabihf 755 0 0
file /etc/passwd initramfs/passwd 644 0 0
file /etc/group initramfs/group 644 0 0
file /bin/udhcpc-script initramfs/udhcpc-script 755 0 0
file /sbin/wpa_supplicant build/debian-trixie-armhf/rootfs/usr/sbin/wpa_supplicant 755 0 0
file /sbin/wpa_cli build/debian-trixie-armhf/rootfs/usr/sbin/wpa_cli 755 0 0
file /sbin/dropbear build/debian-trixie-armhf/rootfs/usr/sbin/dropbear 755 0 0
file /bin/dropbearkey build/debian-trixie-armhf/rootfs/usr/bin/dropbearkey 755 0 0
file /bin/seed-rng build/seed-rng-arm 755 0 0
slink /usr/sbin/wpa_supplicant /sbin/wpa_supplicant 777 0 0
slink /usr/sbin/wpa_cli /sbin/wpa_cli 777 0 0
slink /usr/sbin/dropbear /sbin/dropbear 777 0 0
slink /usr/bin/dropbearkey /bin/dropbearkey 777 0 0
file /lib/ld-linux-armhf.so.3 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/ld-linux-armhf.so.3 755 0 0
file /lib/arm-linux-gnueabihf/libc.so.6 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libc.so.6 644 0 0
file /lib/arm-linux-gnueabihf/libcrypt.so.1.1.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libcrypt.so.1.1.0 644 0 0
slink /lib/arm-linux-gnueabihf/libcrypt.so.1 libcrypt.so.1.1.0 777 0 0
file /lib/arm-linux-gnueabihf/libm.so.6 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libm.so.6 644 0 0
file /lib/arm-linux-gnueabihf/libcrypto.so.3 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libcrypto.so.3 644 0 0
file /lib/arm-linux-gnueabihf/libssl.so.3 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libssl.so.3 644 0 0
file /lib/arm-linux-gnueabihf/libpcsclite.so.1 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libpcsclite.so.1 644 0 0
file /lib/arm-linux-gnueabihf/libdbus-1.so.3.38.3 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libdbus-1.so.3.38.3 644 0 0
slink /lib/arm-linux-gnueabihf/libdbus-1.so.3 libdbus-1.so.3.38.3 777 0 0
file /lib/arm-linux-gnueabihf/libnl-3.so.200.26.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libnl-3.so.200.26.0 644 0 0
slink /lib/arm-linux-gnueabihf/libnl-3.so.200 libnl-3.so.200.26.0 777 0 0
file /lib/arm-linux-gnueabihf/libnl-genl-3.so.200.26.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libnl-genl-3.so.200.26.0 644 0 0
slink /lib/arm-linux-gnueabihf/libnl-genl-3.so.200 libnl-genl-3.so.200.26.0 777 0 0
file /lib/arm-linux-gnueabihf/libnl-route-3.so.200.26.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libnl-route-3.so.200.26.0 644 0 0
slink /lib/arm-linux-gnueabihf/libnl-route-3.so.200 libnl-route-3.so.200.26.0 777 0 0
file /lib/arm-linux-gnueabihf/libreadline.so.8.2 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libreadline.so.8.2 644 0 0
slink /lib/arm-linux-gnueabihf/libreadline.so.8 libreadline.so.8.2 777 0 0
file /lib/arm-linux-gnueabihf/libtinfo.so.6.5 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libtinfo.so.6.5 644 0 0
slink /lib/arm-linux-gnueabihf/libtinfo.so.6 libtinfo.so.6.5 777 0 0
file /lib/arm-linux-gnueabihf/libsystemd.so.0.40.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libsystemd.so.0.40.0 644 0 0
slink /lib/arm-linux-gnueabihf/libsystemd.so.0 libsystemd.so.0.40.0 777 0 0
file /lib/arm-linux-gnueabihf/libcap.so.2.75 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libcap.so.2.75 644 0 0
slink /lib/arm-linux-gnueabihf/libcap.so.2 libcap.so.2.75 777 0 0
file /lib/arm-linux-gnueabihf/libz.so.1.3.1 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libz.so.1.3.1 644 0 0
slink /lib/arm-linux-gnueabihf/libz.so.1 libz.so.1.3.1 777 0 0
file /lib/arm-linux-gnueabihf/libzstd.so.1.5.7 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libzstd.so.1.5.7 644 0 0
slink /lib/arm-linux-gnueabihf/libzstd.so.1 libzstd.so.1.5.7 777 0 0
file /lib/arm-linux-gnueabihf/libtomcrypt.so.1.0.1 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libtomcrypt.so.1.0.1 644 0 0
slink /lib/arm-linux-gnueabihf/libtomcrypt.so.1 libtomcrypt.so.1.0.1 777 0 0
file /lib/arm-linux-gnueabihf/libtommath.so.1.3.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libtommath.so.1.3.0 644 0 0
slink /lib/arm-linux-gnueabihf/libtommath.so.1 libtommath.so.1.3.0 777 0 0
file /lib/arm-linux-gnueabihf/libgmp.so.10.5.0 build/debian-trixie-armhf/rootfs/usr/lib/arm-linux-gnueabihf/libgmp.so.10.5.0 644 0 0
slink /lib/arm-linux-gnueabihf/libgmp.so.10 libgmp.so.10.5.0 777 0 0
EOF

python3 "$ROOT/tools/gen_init_cpio_newc.py" "$WIFI_LIST" "$ROOT" > "$OUT_CPIO"
gzip -9 -n -c "$OUT_CPIO" > "$OUT_GZ"
ls -l "$WIFI_LIST" "$OUT_CPIO" "$OUT_GZ"
