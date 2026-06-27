# v0.5.0 Release Notes

Nexus Q Debian/Linux 6.6 release focused on turning the hardware into a
standalone music appliance, not just a bring-up platform.

## Validated

- Boots Linux 6.6.142 no-SMP from the normal Nexus Q `boot` partition.
- Runs Debian 13.5 armhf from a sparse ext4 image flashed to `userdata`.
- Boots normally by default; return-to-fastboot is explicit via
  `/sbin/nq-reboot-fastboot` or diagnostic boot arguments.
- Plays local SomaFM streams directly from the Q over Wi-Fi.
- Starts the default SomaFM station on boot when Wi-Fi is provisioned.
- Scans built-in PN544 NFC cards and maps tag UIDs to SomaFM station ids.
- Starts station playback from NFC card taps with immediate audio and LED
  feedback while the new stream resolves.
- Runs the LED ring visualizer from the same PCM level tap used for local audio
  and Bluetooth audio.
- Drives the top power LED as a playback-active rainbow status indicator.
- Uses the physical top ring as a TAS5713 hardware volume control.
- Provides trusted-local-network ADB and Dropbear SSH iteration paths.
- Plays Bluetooth A2DP audio from Android through BlueALSA, the Nexus Q 48 kHz
  ALSA route, and the live visualizer path.
- Supports higher-quality Bluetooth codecs when the phone negotiates them,
  including aptX-HD on the tested Pixel path.

## Platform Additions Since v0.4.0

- Adds the built-in SomaFM/NFC jukebox as the default appliance flow.
- Adds tap-confirmation chimes, station-loading LED handoff cues, default
  station autostart, and safer local-player cleanup.
- Adds the `nq-pcm-level-tap` pipeline for local and Bluetooth audio, including
  `S16_LE`, `S24_LE`, and `S32_LE` input handling.
- Adds the fluid pulse LED visualizer with tuned bass/mid/high bands, full
  brightness defaults, sync-delay calibration, top-LED playback status, and
  occasional swirl accents.
- Adds the front-panel AVR input path and `nq-knob-volume` daemon for physical
  volume control.
- Adds the BlueZ/BlueALSA A2DP sink path with audio-priority ownership over
  local SomaFM playback.
- Keeps Squeezelite/Music Assistant support available as an opt-in legacy
  endpoint.
- Updates release tooling so generated checksums use the v0.5.0 release name.

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
    BCM4330 Wi-Fi, modular PN544 NFC, modular front-panel AVR input, and
    modular Bluetooth controller support
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Android sparse image for `fastboot flash userdata`
  - Debian 13.5 armhf rootfs with Dropbear SSH, trusted-local ADB, SomaFM/NFC
    jukebox helpers, BlueALSA Bluetooth A2DP support, LED visualizer utilities,
    knob-volume daemon, time sync, and common network/debugging tools
- `SHA256SUMS-v0.5.0.txt`

## Known Gaps

- Bluetooth playback is validated as an A2DP sink, but AVRCP phone media
  controls are not finished yet.
- Chromecast receiver behavior is not implemented.
- External USB storage support is planned but still waiting on host-mode/OTG
  validation.
- Full systemd appliance boot is staged but not the default init path.
- HDMI, S/PDIF, cap-touch behavior, and FFT-grade visualizer analysis are not
  finished.
- Wi-Fi depends on stock `system` calibration or a user-provided NVRAM text
  file.
