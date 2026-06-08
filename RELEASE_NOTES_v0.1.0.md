# v0.1.0 Release Notes

First public Nexus Q Debian/Linux 6.6 bring-up release.

## Validated

- Booted Linux 6.6.142 no-SMP from fastboot.
- Flashed Debian 13.5 armhf sparse rootfs to `userdata`.
- Mounted `/run` as tmpfs to avoid stale injected test credentials.
- Copied BCM4330 NVRAM calibration from stock Android `/system`.
- Loaded modular `brcmfmac`, `brcmfmac_wcc`, and `brcmutil`.
- Associated to WPA2 Wi-Fi, obtained DHCP, and accepted Dropbear SSH.
- ALSA listed `Steelhead TAS5713`.
- `speaker-test -D hw:0,0 -c 2 -r 48000 -t sine -f 1000 -l 1` opened the PCM
  path.
- Returned to fastboot automatically through the runner.

## Assets

- `nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`
- `nexusq-debian-trixie-armhf-rootfs.sparse.img`
- `SHA256SUMS-v0.1.0.txt`

## Known Gaps

- The release is a bring-up image, not an installed appliance OS.
- Full systemd boot is not the default path.
- HDMI, S/PDIF, front-panel controls, ring LEDs, and streaming apps are future
  work.
- Wi-Fi requires stock `system` calibration or a user-provided NVRAM text file.

