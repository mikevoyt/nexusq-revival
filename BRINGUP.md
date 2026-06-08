# Nexus Q Bring-Up Notes

## Current Device State

- Device: Google Nexus Q / Steelhead
- Serial observed in fastboot: `AW1S12250524`
- Bootloader: `steelheadB4H0J`
- Bootloader state: unlocked
- Secure flag after unlock: `secure: no`
- The user data partition was erased by `fastboot oem unlock_accept`.

## Working Rescue Boot

Artifact:

- `artifacts/nexusq-rescue-acm-ecm.img`

Boot command used:

```sh
fastboot boot artifacts/nexusq-rescue-acm-ecm.img
```

Result:

- Fastboot accepted and booted the image without flashing.
- macOS enumerated the device as:
  - USB product: `NexusQ`
  - VID/PID: `18d1:4e23`
  - Serial device: `/dev/cu.usbmodemAW1S122505241`
- Serial shell command:

```sh
screen /dev/cu.usbmodemAW1S122505241 115200
```

Kernel reported:

- `Linux (none) 3.0.8-g03a9286b-dirty`
- Hardware: `Steelhead`
- CPU: dual-core ARMv7 Cortex-A9 class, with NEON/VFPv3

## Built Artifacts

- `artifacts/steelhead-zImage`
- `artifacts/nexusq-initramfs.cpio`
- `artifacts/nexusq-initramfs.cpio.gz`
- `artifacts/nexusq-rescue-acm-ecm.img`
- `artifacts/nexusq-rescue-acm.img`
- `artifacts/bin/tinyplay`
- `artifacts/bin/nqstreamd`
- `artifacts/bin/reboot-bootloader`
- `artifacts/test-tone-1khz-48k-stereo.wav`

Rebuild command for the current rescue image:

```sh
tools/build_rescue_image.sh
```

The kernel was built from AOSP `kernel/omap` branch:

- `android-omap-steelhead-3.0-ics-aah`
- Commit observed: `03a9286bb61a9acd28027206c4937990ac817f1b`

The successful kernel build used Android GCC:

- `arm-eabi-gcc (GCC) 4.6.x-google 20120106 (prerelease)`
- A modern GCC 9 cross-compiler failed on old ARM hard-register inline assembly in `put_user()`.

One build-time host compatibility patch was needed:

- `patches/steelhead-kernel-modern-host-tools.patch`
- Fixes `defined(@array)` in `kernel/timeconst.pl` for modern Perl.

One runtime USB patch was needed:

- `patches/steelhead-kernel-android-gadget-ecm.patch`
- Adds CDC ECM as an Android USB gadget function, enabling the current `acm,ecm`
  rescue configuration.

## Boot Image Header

Stock factory image used for header reference:

- `tungsten-ian67k-factory-d766e5f1.zip`

Stock `boot.img` header values:

- `kernel_addr=0x80008000`
- `ramdisk_addr=0x81000000`
- `second_addr=0x80f00000`
- `tags_addr=0x80000100`
- `page_size=2048`
- boot header cmdline: empty

Kernel config carries the command line:

```text
console=ttyFIQ0 androidboot.console=ttyFIQ0 mem=1G vmalloc=768M omap_wdt.timer_margin=30 no_console_suspend
```

## Hardware Observed From Rescue Shell

Storage:

- eMMC is visible as `mmcblk0`.
- Stock Android partitions are visible.
- `/system` mounted read-only from `/dev/mmcblk0p11`.

Audio:

- ALSA card 0: `OMAP4HDMI`
- ALSA card 1: `SPDIF` / `Steelhead SPDIF Card`
- ALSA card 2: `TAS5713` / `Steelhead TAS5713 Card`

Controls:

- Input device: `Steelhead Front Panel`

USB:

- Android USB gadget sysfs exists.
- ACM function works and provides a serial shell.
- ECM function is configured alongside ACM.
- Device-side `usb0` comes up as `172.16.42.2/24`.
- macOS sees USB network interfaces, but assigning the host-side address needs
  administrator permission, for example:

```sh
sudo ifconfig enX inet 172.16.42.1 netmask 255.255.255.0 up
```

Network:

- `wlan0` appears in `/sys/class/net`.
- Broadcom firmware exists on stock `/system`:
  - `/system/vendor/firmware/fw_bcmdhd.bin`
  - `/system/vendor/firmware/fw_bcmdhd_apsta.bin`
  - `/system/vendor/firmware/fw_bcmdhd_p2p.bin`
- The rescue init mounts stock `/system` read-only, links
  `/lib/firmware -> /system/vendor/firmware`, and brings `wlan0` up. This
  successfully loaded the Broadcom Wi-Fi firmware on the test unit.

Firmware:

- Stock `/system/vendor/firmware` also contains `ducati-m3.bin`, `bcm4330.hcd`, NFC firmware, and related blobs.
- Initial rescue boot still shows firmware wait warnings for HDCP/Ducati. The
  observed failures are not blocking serial, ECM, Wi-Fi firmware load, ALSA card
  enumeration, or TAS5713/S/PDIF playback.

## Audio Validation

The rescue image includes:

- `/bin/tinyplay`
- `/bin/nqstreamd`
- `/bin/reboot-bootloader`
- `/bin/test-audio`
- `/tmp/test-tone-1khz-48k-stereo.wav`
- `/tmp/test.wav` symlinked to the same tone

Commands tested from the rescue serial shell:

```sh
/bin/tinyplay /tmp/test.wav -c 2 -d 0
/bin/tinyplay /tmp/test.wav -c 1 -d 0
/bin/tinyplay /tmp/test.wav -c 0 -d 0
```

Results:

- Card 2 `TAS5713` accepted and played the 48 kHz stereo 16-bit WAV path.
- Card 1 `SPDIF` accepted and played the same WAV path.
- Card 0 `OMAP4HDMI` failed to open without an active HDMI audio sink/mode,
  which is expected for this setup.

## First Streaming Daemon

`/bin/nqstreamd` is a minimal TCP WAV-to-ALSA daemon intended to prove the
future Android app protocol path before adding codecs or persistence.

The current initramfs starts it automatically:

```sh
/bin/nqstreamd -p 5555 -c 2 -d 0
```

For one-shot manual testing on the Nexus Q serial shell, use:

```sh
/tmp/nqstreamd --once -p 5555 -c 2 -d 0
```

From macOS over the USB ECM link-local interface:

```sh
nc -6 'fe80::18ed:a6ff:fe2f:c19d%en9' 5555 < artifacts/test-tone-1khz-48k-stereo.wav
```

The IPv6 address is derived from the device-side `usb0` MAC for the current
boot, so re-check `ifconfig usb0` if the USB gadget MAC changes.

Live test result:

- Host command `nc -6 'fe80::18ed:a6ff:fe2f:c19d%en9' 5555 <
  artifacts/test-tone-1khz-48k-stereo.wav` completed with exit `0`.
- Device-side `nqstreamd --once` reported `streaming WAV: card=2 device=0
  channels=2 rate=48000 bits=16 bytes=96000` and exited `0`.

## Reboot To Fastboot

The rescue image includes `/bin/reboot-bootloader`. It calls the Linux reboot
syscall with `LINUX_REBOOT_CMD_RESTART2` and the restart command `bootloader`.
The Steelhead kernel reboot notifier writes that command into OMAP SAR RAM,
where the bootloader can see it on the next warm reset.

From the rescue serial shell:

```sh
/bin/reboot-bootloader
```

Live test result:

- Uploaded the helper to the running rescue image as `/tmp/reboot-bootloader`.
- The helper printed `rebooting with restart command 'bootloader'`.
- The serial ACM endpoint disappeared and `fastboot devices` reported
  `AW1S12250524 fastboot`.

## Next Steps

1. Reboot the updated rescue image and re-run `/bin/test-audio` to confirm the
   baked-in TinyALSA path.
2. Assign a host-side ECM address with administrator permission and validate
   ping/SSH or a minimal TCP service over USB.
3. Decide whether the persistent base should be Android-with-custom-daemon or a
   small Debian-style rootfs on `userdata`. Android is likely the shorter path
   if the final control surface is a custom Android app and stock blobs remain
   useful.
4. Build the first streaming daemon around the proven ALSA card, starting with
   raw PCM or WAV over TCP before adding codec/metadata support.
5. Integrate ring/front-panel controls after boot, audio, and network are
   repeatable.
