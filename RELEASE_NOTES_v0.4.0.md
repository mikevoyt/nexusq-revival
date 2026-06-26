# v0.4.0 Release Notes

Nexus Q Debian/Linux 6.6 release focused on turning the bring-up image into a
minimum standalone appliance platform for the SomaFM NFC jukebox prototype.

## Validated

- Boots Linux 6.6.142 no-SMP from the normal Nexus Q `boot` partition.
- Runs Debian 13.5 armhf from a sparse ext4 image flashed to `userdata`.
- Preserves stock `recovery`; manual return to fastboot remains available.
- Plays local SomaFM streams directly from the Q over Wi-Fi, without requiring a
  Mac-side USB proxy.
- Scans built-in PN544 NFC cards and maps tag UIDs to SomaFM station ids through
  `/etc/nexusq/somafm-tags.conf`.
- Starts station playback from NFC card taps with a tap-confirmation chime.
- Preserves TAS5713 hardware volume across SomaFM station changes.
- Provides trusted-local-network ADB and Dropbear SSH iteration paths.
- Boots with HTTP-based clock bootstrap plus `ntpsec` so TLS package operations
  do not fail on devices that start with a 1970 clock.

## Platform Additions

- Adds the standard appliance/debug package set:
  `ntpsec`, `iputils-ping`, `bind9-dnsutils`, `iw`, `wireless-tools`, `less`,
  `nano`, `netcat-openbsd`, `tcpdump`, `htop`, `strace`, `lsof`, `file`,
  `rsync`, and `tzdata`.
- Starts `ntpsec` from the custom network bootstrap after Wi-Fi, DHCP, and the
  initial HTTP time sync.
- Adds deterministic `ntpsec` user/group setup for images built without Debian
  maintainer-script execution.
- Strips release images of apt caches/indexes, package docs except copyright
  files, man pages, locales, Python tests, and Python bytecode caches.
- Keeps SomaFM playlist/channel resolution on HTTP by default so first-boot
  clock skew does not break TLS before time is synchronized.
- Includes improved SomaFM/NFC process cleanup, timing logs, station listing,
  and host-side proxy warm-stream helpers for bench iteration.

## Flash Instructions

This overwrites `boot` and `userdata`. It does not overwrite `recovery`.

```sh
fastboot flash boot nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img
fastboot flash userdata nexusq-debian-trixie-armhf-rootfs.sparse.img
fastboot reboot
```

Manual return to fastboot from Debian:

```sh
/sbin/nq-reboot-fastboot
```

For temporary kernel testing without changing the installed boot partition, use
`fastboot boot nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`.

## Assets

- `nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`
  - Android boot image for `fastboot flash boot`
  - Linux 6.6.142, no-SMP, USB ACM+ECM, TAS5713 speaker playback, modular
    BCM4330 Wi-Fi, modular PN544 NFC, modular front-panel AVR input support
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Android sparse image for `fastboot flash userdata`
  - Debian 13.5 armhf rootfs with Dropbear SSH, trusted-local ADB,
    Squeezelite, `mpg123`, SomaFM/NFC jukebox helpers, time sync, and common
    network/debugging tools
- `SHA256SUMS-v0.4.0.txt`

## Known Gaps

- SomaFM NFC jukebox behavior is validated as a prototype, not a polished
  consumer setup flow.
- Full systemd appliance boot is staged but not the default init path.
- HDMI, S/PDIF, advanced LED effects, and cap-touch handling are not finished.
- Wi-Fi depends on stock `system` calibration or a user-provided NVRAM text
  file.
- The TAS5713 path is validated at 48 kHz; 44.1 kHz content should be resampled
  by Music Assistant Queue Flow Mode or userspace.
