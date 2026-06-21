# v0.3.0 Release Notes

Nexus Q Debian/Linux 6.6 release focused on Music Assistant playback, local
hardware volume, and faster network iteration.

## Validated

- Boots Linux 6.6.142 no-SMP from the normal Nexus Q `boot` partition.
- Runs Debian 13.5 armhf from a sparse ext4 image flashed to `userdata`.
- Plays clean 48 kHz PCM/MP3 through the TAS5713 speaker amplifier path with
  the Steelhead ABE DPLL clock-parent fix from v0.2.0.
- Streams successfully from Music Assistant using the Squeezelite/SlimProto
  player path when the Q advertises `48000-48000` and Music Assistant Queue
  Flow Mode is set to 48 kHz.
- Uses the Nexus Q top ring as local TAS5713 hardware volume through the
  `steelhead_avr` input driver and `nq-knob-volume`.
- Ships the tested loud passive-speaker profile by default:
  `Master Volume=231`, `Speaker Volume=207`, and knob cap `231`.
- Provides an ADB-compatible debug bridge on TCP 5555 with root Bash shell,
  recursive `adb push`/`adb pull`, `adb root`, and `adb reboot bootloader` for
  trusted local prototype networks.
- Preserves stock `recovery`; manual return to fastboot remains available.

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
    BCM4330 Wi-Fi, modular front-panel AVR input support
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Android sparse image for `fastboot flash userdata`
  - Debian 13.5 armhf rootfs with Dropbear SSH, Bash, SFTP server support,
    `mpg123`, Squeezelite, `nq-knob-volume`, `nq-avr-i2c`, and opt-in
    `nq-adbd-lite`
- `SHA256SUMS-v0.3.0.txt`

## Music Assistant

Run Music Assistant on a supported 64-bit host and use the Q as a Squeezelite
endpoint. Enable Queue Flow Mode for the Q player and set the Flow Mode sample
rate to 48 kHz. The release image also enables Squeezelite's local SoX
resampler as a backstop.

## Volume Profile

`207` is roughly 0 dB on the TAS5713 volume controls. This release defaults to
`231` for the master control, about +12 dB, because that profile was validated
with an external passive speaker during Music Assistant playback. If tracks
sound harsh or clipped, lower `NQ_SQUEEZELITE_MASTER_VOLUME` and `NQ_KNOB_MAX`
to `207`.

## Known Gaps

- Full systemd appliance boot is staged but not the default init path.
- HDMI, S/PDIF, LED-ring control, and cap-touch handling are not finished.
- Music Assistant does not yet receive feedback when the physical Q ring changes
  local hardware volume.
- Stereo/channel-routing validation should be expanded beyond the current
  one-speaker test setup.
- Wi-Fi depends on stock `system` calibration or a user-provided NVRAM text
  file.
- The TAS5713 path is validated at 48 kHz; 44.1 kHz content should be resampled
  by Music Assistant Queue Flow Mode or userspace.
