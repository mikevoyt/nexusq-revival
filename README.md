# Nexus Q Revival

Modern Linux for Google's abandoned spherical streaming box.

This project brings the Nexus Q / Steelhead back as a small Debian-based
network audio target. The current public release boots Debian 13.5 armhf from
`userdata` with a Linux 6.6.142 kernel installed to the normal `boot`
partition.

## Current Status

Validated on real Nexus Q hardware in June 2026:

- Linux 6.6.142 no-SMP boots from the normal `boot` partition.
- Debian 13.5 armhf runs from a sparse ext4 image flashed to `userdata`.
- USB ACM serial shell and USB ECM gadget are configured by early init.
- BCM4330 Wi-Fi works with public Debian firmware plus first-boot calibration
  copied from the device's stock Android `system` partition.
- Dropbear SSH accepts injected root public-key auth over Wi-Fi.
- ALSA exposes `card 0: TAS5713 [Steelhead TAS5713]`.
- The internal TAS5713 speaker path plays 48 kHz stereo PCM and MP3 on Linux
  6.6 after the Steelhead ABE DPLL clock-parent fix.
- Opt-in Squeezelite endpoint support is validated for Music Assistant
  playback.
- The Nexus Q top ring controls TAS5713 hardware volume through the front-panel
  AVR input driver and `nq-knob-volume`.
- The LED ring is controllable through `/dev/leds`, and an opt-in Squeezelite
  amplitude visualizer can drive it during Music Assistant playback.
- An opt-in ADB-compatible debug bridge provides root Bash shell and file sync
  for trusted local bring-up networks.
- Prototype SomaFM NFC jukebox helpers can scan NFC tag/card UIDs through the
  built-in PN544 or an external reader, map them to SomaFM channel ids, and
  start local stream playback.
- Built-in PN544 NFC card scans have been validated on real hardware, including
  UID-to-station playback through the SomaFM jukebox loop.
- The public boot image stays running by default; return-to-fastboot is now an
  explicit recovery command or diagnostic boot option.

Still experimental:

- Full unattended appliance use is still early, but the release now supports
  normal boot from the `boot` partition.
- Full systemd service bring-up is not the default init path.
- HDMI, S/PDIF, advanced LED effects, and cap-touch handling are not finished.
- The LED visualizer is an early amplitude-based effect, not a frequency-band
  or Music Assistant UI-integrated visualizer yet.
- TAS5713 speaker validation has focused on one wired speaker so far; full
  stereo/channel-routing validation is still pending.
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

The v0.3.0 release assets are:

- `nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`
  - Android boot image for `fastboot flash boot`
  - Linux 6.6.142, no-SMP, USB ACM+ECM, TAS5713 speaker playback, modular
    BCM4330 Wi-Fi
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Android sparse image for `fastboot flash userdata`
  - Debian 13.5 armhf rootfs
- `SHA256SUMS-v0.3.0.txt`

Download them from:

<https://github.com/mikevoyt/nexusq-revival/releases/tag/v0.3.0>

Release notes are in [RELEASE_NOTES_v0.3.0.md](RELEASE_NOTES_v0.3.0.md).

## Flash And Boot

This overwrites `boot` and `userdata`. It does not flash `recovery`.

```sh
fastboot flash boot nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img
fastboot flash userdata nexusq-debian-trixie-armhf-rootfs.sparse.img
fastboot reboot
```

For a temporary no-flash kernel test, use `fastboot boot` instead of flashing
`boot`. The public image does not auto-return to fastboot. Manual recovery from
Debian is:

```sh
/sbin/nq-reboot-fastboot
```

Detailed instructions are in [FLASHING.md](FLASHING.md).
Persistent Wi-Fi/SSH provisioning for appliance-style use is documented in
[APPLIANCE.md](APPLIANCE.md).
Music Assistant player endpoint setup is documented in
[MUSIC_ASSISTANT.md](MUSIC_ASSISTANT.md).
LED ring control and the Squeezelite visualizer are documented in
[LED_RING_VISUALIZER.md](LED_RING_VISUALIZER.md).
The SomaFM NFC jukebox prototype is documented in [NFC_JUKEBOX.md](NFC_JUKEBOX.md).

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
The speaker-clock root cause and fix are documented in [AUDIO_CLOCK_FIX.md](AUDIO_CLOCK_FIX.md).

## Secret Handling

Do not commit Wi-Fi credentials, SSH private keys, stock firmware, or device
calibration dumps. The repo ignores `.secrets/`, `wifi.env`,
`wpa_supplicant*.conf`, build outputs, downloads, and generated artifacts.

The public release image does not embed private Broadcom firmware or calibration.
At first Wi-Fi startup, Debian copies `/etc/wifi/bcmdhd.cal` from the stock
Android `system` partition mounted read-only from `/dev/mmcblk0p11`.

## Project Page

GitHub Pages content lives in [docs/](docs/).
