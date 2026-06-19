# v0.2.0 Release Notes

Nexus Q Debian/Linux 6.6 release focused on normal boot and clean internal
speaker playback.

## Validated

- Installed Linux 6.6.142 no-SMP to the Nexus Q `boot` partition.
- Flashed Debian 13.5 armhf sparse rootfs to `userdata`.
- Rebooted normally with `fastboot reboot`; the public image no longer arms an
  automatic return-to-fastboot timer by default.
- Kept stock `recovery` untouched so the normal manual fastboot recovery path
  remains available.
- Fixed the Linux 6.6 TAS5713 speaker flutter by matching the vendor Steelhead
  ABE DPLL reference parent: `abe_dpll_refclk_mux_ck` now uses `sys_clkin_ck`
  on `google,steelhead`.
- Verified clean 48 kHz PCM playback with ALSA and clean MP3 playback with
  `mpg123` on real Nexus Q hardware.
- Preserved BCM4330 Wi-Fi support using public Debian firmware plus first-boot
  calibration extraction from stock Android `system`.
- Included Dropbear SSH, OpenSSH SFTP server support, `mpg123`, `nq-play`, and
  opt-in Squeezelite endpoint support for Music Assistant experiments.
- Validated Music Assistant streaming with the Q as a Squeezelite endpoint when
  Music Assistant Queue Flow Mode is fixed to 48 kHz and the Q advertises
  `48000-48000`.

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
    BCM4330 Wi-Fi
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Android sparse image for `fastboot flash userdata`
  - Debian 13.5 armhf rootfs
- `SHA256SUMS-v0.2.0.txt`

## Audio Clock Fix

The speaker flutter root cause is documented in
[AUDIO_CLOCK_FIX.md](AUDIO_CLOCK_FIX.md). In short, the mainline OMAP4 ABE DPLL
reference parent was valid for generic OMAP4 boards but wrong for Steelhead's
speaker path. The v0.2.0 kernel patch keeps the generic behavior for other
OMAP4 boards and applies a Steelhead-only `sys_clkin_ck` parent quirk.

## Known Gaps

- Full systemd appliance boot is staged but not the default init path.
- HDMI, S/PDIF, LEDs, top ring controls, and hardware volume integration are
  not finished.
- Stereo/channel-routing validation should be expanded beyond the current
  internal speaker tests.
- Wi-Fi depends on stock `system` calibration or a user-provided NVRAM text
  file.
- The internal speaker path is validated at 48 kHz; 44.1 kHz content should be
  resampled by userspace. For Music Assistant, enable Queue Flow Mode at 48 kHz.
