# Nexus Q Revival

Modern Linux for Google's abandoned spherical streaming box.

This project brings the Nexus Q / Steelhead back as a small Debian-based
network audio target. The current public release boots Debian 13.5 armhf from
`userdata` with a Linux 6.6.142 kernel launched by fastboot.

## Current Status

Validated on real Nexus Q hardware on June 8, 2026:

- Linux 6.6.142 no-SMP boots from `fastboot boot`.
- Debian 13.5 armhf runs from a sparse ext4 image flashed to `userdata`.
- USB ACM serial shell and USB ECM gadget are configured by early init.
- BCM4330 Wi-Fi works with public Debian firmware plus first-boot calibration
  copied from the device's stock Android `system` partition.
- Dropbear SSH accepts injected root public-key auth over Wi-Fi.
- ALSA exposes `card 0: TAS5713 [Steelhead TAS5713]`.
- `speaker-test` opens `hw:0,0` at 48 kHz stereo.
- The boot image arms an automatic return-to-fastboot timer for safer testing.

Still experimental:

- The release is intended for `fastboot boot`, not permanent daily-driver boot
  flashing yet.
- Full systemd service bring-up is not the default init path.
- HDMI, S/PDIF, LEDs, top ring controls, and a real streaming protocol are not
  finished.
- Wi-Fi depends on calibration from an existing stock `system` partition, or a
  user-supplied Broadcom NVRAM text file.

## Why This Exists

Google introduced Nexus Q at Google I/O on June 27, 2012 as a spherical,
Android-controlled social streaming device for Google Play and YouTube. Google
priced it at $299 and planned mid-July shipping. The consumer launch was later
postponed, and pre-order customers received preview/developer units instead.

The hardware is unusual and still interesting: OMAP4460, eMMC, Wi-Fi, optical
audio, HDMI, and an integrated TAS5713 speaker amplifier path. This repo treats
the Q as a Linux-capable embedded audio platform rather than a museum object.

History links:

- [Google launch post, June 27, 2012](https://blog.google/products/android/android-io-playground-is-open/)
- [Engadget on the postponed launch, July 31, 2012](https://www.engadget.com/2012-07-31-google-postponing-nexus-q-launch-to-make-it-better.html)

## Release Artifacts

The v0.1.0 release assets are:

- `nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`
  - fastboot boot image
  - Linux 6.6.142, no-SMP, USB ACM+ECM, TAS5713 audio, modular BCM4330 Wi-Fi
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Android sparse image for `fastboot flash userdata`
  - Debian 13.5 armhf rootfs
- `SHA256SUMS-v0.1.0.txt`

Download them from:

<https://github.com/mikevoyt/nexusq-revival/releases>

## Flash And Boot

This overwrites `userdata`. It does not flash `boot` or `recovery`.

```sh
fastboot flash userdata nexusq-debian-trixie-armhf-rootfs.sparse.img
fastboot boot nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img
```

The boot image uses `nq.autoreboot=180`, so a normal test boot returns to
fastboot after about three minutes unless cancelled from the serial shell:

```sh
/sbin/nq-autoreboot-cancel
```

Detailed instructions are in [FLASHING.md](FLASHING.md).

## Build

The release build is currently host-local and expects:

- Android platform-tools for `fastboot`.
- GNU make.
- An ARM EABI cross compiler. The tested host used STM32CubeCLT:
  `/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/bin/arm-none-eabi-`.
- e2fsprogs `mke2fs`.
- Linux 6.6.142 source extracted at `kernel/linux-6.6.142`.

Build everything:

```sh
tools/build_release_artifacts_local.sh
```

The build script applies `patches/linux-6.6.142-nexusq-steelhead.patch`, copies
`linux66/omap4-steelhead.dts`, builds the boot image, installs only the needed
Broadcom Wi-Fi modules into the Debian rootfs, and creates raw plus sparse ext4
rootfs images.

More detail is in [BUILDING.md](BUILDING.md).

## Secret Handling

Do not commit Wi-Fi credentials, SSH private keys, stock firmware, or device
calibration dumps. The repo ignores `.secrets/`, `wifi.env`,
`wpa_supplicant*.conf`, build outputs, downloads, and generated artifacts.

The public release image does not embed private Broadcom firmware or calibration.
At first Wi-Fi startup, Debian copies `/etc/wifi/bcmdhd.cal` from the stock
Android `system` partition mounted read-only from `/dev/mmcblk0p11`.

## Project Page

GitHub Pages content lives in [docs/](docs/).
