# Debian armhf rootfs spike

## Status

- Target release: Debian 13 `trixie` armhf.
- Build method: local package-metadata resolver and direct `.deb` extraction.
- Builder: `tools/build_debian_rootfs.py`.
- Staging directory: `build/debian-trixie-armhf/rootfs`.
- Package cache: `downloads/debian-trixie-armhf`.
- Package manifest: `build/debian-trixie-armhf/packages.txt`.
- Rootfs image: `artifacts/nexusq-debian-trixie-armhf-rootfs.ext4`.
- Fastboot sparse image:
  `artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img`.
- Public Debian loader boot image:
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`.

The generated ext4 image is 768 MiB logical size and about 222 MiB allocated on
the host filesystem. The Android sparse form is about 196 MiB and is required
for this bootloader's `fastboot flash userdata` path; flashing the raw ext4
image failed with `remote: 'data too large'`.

## Included bring-up pieces

- Debian base/required package closure.
- `apt` with `trixie`, `trixie-security`, and `trixie-updates` sources.
- `systemd`, `systemd-sysv`, `udev`, and `dbus`.
- USB/network tools: `iproute2`, `ifupdown`, `isc-dhcp-client`, `netbase`.
- Debug access: `dropbear-bin`, `busybox-static`.
- Debug/transfer access: `dropbear-bin`, `busybox-static`,
  `openssh-client`, `openssh-sftp-server`.
- Audio tools: `alsa-utils`, `alsa-ucm-conf`, `mpg123`.
- Music Assistant endpoint prep: `squeezelite`.
- Wi-Fi prep: `wpasupplicant`, `wireless-regdb`, `firmware-brcm80211`.

The current Linux 6.6 no-SMP kernel spike has validated TAS5713 ALSA from the
Debian rootfs on `userdata`. `aplay -l` reports `Steelhead TAS5713`, and
`speaker-test` opened `hw:0,0` at 48 kHz stereo.

The rootfs includes `/sbin/nq-init`, a conservative first-boot init that:

- mounts `proc`, `sysfs`, `devtmpfs`, and `devpts`;
- mounts `/run` as tmpfs so injected Wi-Fi/SSH runtime files do not persist
  across boots;
- configures the USB configfs ACM+ECM gadget and starts a USB serial shell on
  `/dev/ttyGS0`;
- arms an `nq.autoreboot` timer that reboots to fastboot through
  `/sbin/nq-reboot-fastboot`;
- configures `usb0` as `169.254.42.2/16` and `172.16.42.2/24`;
- starts BusyBox `telnetd` on TCP port 2323;
- drops to `/bin/sh`.

The rootfs also includes `/sbin/nq-prepare-wifi-firmware`,
`/sbin/nq-load-wifi`, `/sbin/nq-start-network`,
`/sbin/nq-start-squeezelite`, `/sbin/nq-player-status`,
`/sbin/nq-provision`, `/sbin/nq-appliance-status`, and `/usr/bin/nq-play`. The
public Wi-Fi path prepares Debian `brcmfmac4330-sdio.bin`, copies Steelhead
BCM4330 NVRAM calibration from the stock Android `system` partition when
available, loads the modular Broadcom driver, accepts runtime-only Wi-Fi and SSH
files in `/run/nexusq/` or `/tmp/`, accepts persistent device-local config in
`/etc/nexusq/`, seeds early boot entropy when `/tmp/rng.seed` or
`/var/lib/nexusq/rng.seed` exists, starts `wpa_supplicant`, obtains DHCP with
BusyBox `udhcpc`, installs an injected or persistent `authorized_keys`, and
restarts Dropbear for key-only SSH. Squeezelite starts only when an opt-in
`squeezelite.env` enables it. `nq-play` is a local MP3 test wrapper around
`mpg123` that forces 48 kHz/S16 stereo output on `hw:0,0`, applies audible mixer
defaults, and uses conservative ALSA buffering.

Because this builder extracts `.deb` archives without running maintainer
scripts, it writes minimal `/etc/passwd`, `/etc/group`, and `/etc/shadow`
entries and then populates Debian's standard base-passwd users/groups. The
root shadow entry uses a random unknown SHA-512 password hash generated at build
time; Dropbear is still launched with password logins disabled. The builder also
preserves package `Provides` metadata, writes the CA certificate bundle needed
for HTTPS apt, and creates a few basic alternatives such as `/usr/bin/awk` and
`/usr/bin/mpg123` that package maintainer scripts would normally install.

## Fastboot partition facts

`fastboot getvar all` reported:

- `boot`: 8 MiB
- `recovery`: 8 MiB
- `system`: 1 GiB
- `cache`: 512 MiB
- `userdata`: `0x349980000` bytes, about 13.2 GiB

`userdata` was flashed once during this spike with the sparse Debian image.
The boot and recovery partitions were not flashed; all 6.6 kernels in this
phase were launched with `fastboot boot`.

## Caveats

This is not a normal debootstrap/mmdebstrap rootfs. Homebrew did not provide
either tool in this environment, and Docker Desktop was unavailable, so the
builder extracts the selected Debian packages directly and writes a basic
`/var/lib/dpkg/status` file.

Implications:

- Package files are present and `dpkg` has a minimal installed-package view.
- Maintainer scripts have not been run.
- The safest first boot is with `init=/sbin/nq-init`, not full systemd.
- Once running on-device, use `dpkg --configure -a` and `apt-get -f install`
  only after USB networking and fastboot recovery are reliable.
- Wi-Fi userspace packages are staged. The modern no-SMP 6.6 public image now
  discovers the BCM4330 SDIO function, creates `wlan0`, loads Broadcom FullMAC
  as modules from the Debian rootfs, associates with WPA2-PSK, obtains a DHCP
  lease, starts Dropbear, and accepts root SSH.
- The older local Wi-Fi fragment,
  `linux66/nexusq-linux66-wifi.fragment`, embeds private local BCM4330
  firmware/NVRAM via `.secrets/nexusq-firmware`. Keep that fragment for local
  debugging only. The public release uses
  `linux66/nexusq-linux66-wifi-public.fragment` and does not embed those files.
- The current Steelhead TAS5713 audio path is validated at 48 kHz/S16 stereo.
  Plain 44.1 kHz playback cannot be clocked by the current 6.6 patch; use
  `nq-play` or Squeezelite's `-r 48000` configuration so userspace resamples.

## Secret Handling

Do not commit Wi-Fi credentials. Local secret material should stay in macOS
Keychain or in ignored files such as `.secrets/`, `wifi.env`, or
`wpa_supplicant*.conf`.

The old private-firmware Wi-Fi kernel test uses ignored local
firmware/calibration files under `.secrets/nexusq-firmware/`. Do not publish
those files or kernel images that embed them.

The public Debian release image uses Debian `firmware-brcm80211` for
`brcmfmac4330-sdio.bin`. On first Wi-Fi startup it mounts `/dev/mmcblk0p11`
read-only and copies the owner device's `/etc/wifi/bcmdhd.cal` into
`/lib/firmware/brcm/brcmfmac4330-sdio.google,steelhead.txt` and the generic
`brcmfmac4330-sdio.txt` fallback.

The host-side Wi-Fi association runner, `tools/run_wifi_serial_test.py`, reads
the network password from macOS Keychain at runtime and sends it only to the
device's temporary `/tmp/wpa_supplicant.conf`. It also uploads a fresh
temporary RNG seed to `/tmp/rng.seed` so `wpa_supplicant` does not block on
early-boot entropy. It does not write credentials to tracked files.

The Debian rootfs runner, `tools/run_debian_serial_test.py`, uses the same
secret handling model. It can flash the sparse rootfs to `userdata`, RAM-boot
the loader image, upload Wi-Fi config, upload an SSH public key, start
`/sbin/nq-start-network`, verify SSH, and then ask the device to return to
fastboot. It can also upload and start a non-secret Squeezelite config with
`--enable-squeezelite`. It does not write credentials into the shareable rootfs
image.

## Live Test Results

Validated on June 7-8, 2026:

- `tools/run_wifi_serial_test.py` succeeded from RAM:
  - Wi-Fi associated to the configured WPA2 network.
  - DHCP configured `wlan0` as `192.168.86.46`.
  - Dropbear accepted root SSH from the host.
  - The runner returned the device to fastboot automatically.
- `fastboot flash userdata artifacts/debian-trixie-armhf-rootfs.ext4` failed:
  - bootloader error: `remote: 'data too large'`.
- `tools/img2simg.py` produced
  `artifacts/debian-trixie-armhf-rootfs.sparse.img`.
- Flashing the sparse image to `userdata` succeeded:
  - fastboot reported `userdata is in sparse format`;
  - sparse output length was 768 MiB.
- Initial Debian failures and fixes:
  - first loader boot did not expose USB ACM, so the loader and Debian init now
    configure configfs ACM+ECM before switch-root/serial shell;
  - serial command markers were initially satisfied by echoed input, so the
    host runners now emit split markers from shell variables;
  - Debian Dropbear initially had no root account metadata, so the builder now
    creates minimal root passwd/group/shadow entries;
  - `/run` was initially persistent on the ext4 rootfs, so Debian init now
    mounts `/run` as tmpfs.
- Final Debian live validation on June 8, 2026:
  - command:
    `tools/run_debian_serial_test.py --flash-userdata --rootfs artifacts/debian-trixie-armhf-rootfs.sparse.img`
  - sparse `userdata` flash succeeded;
  - loader exposed USB ACM serial;
  - Debian reported version `13.5`;
  - `/run` was mounted as tmpfs;
  - Wi-Fi DHCP configured `wlan0` as `192.168.86.42/24`;
  - Dropbear accepted root SSH public-key auth from the host;
  - `aplay -l` reported `card 0: TAS5713 [Steelhead TAS5713]`;
  - a separate audio test ran
    `speaker-test -D hw:0,0 -c 2 -r 48000 -F S16_LE -t sine -f 1000 -l 1`;
  - the runner returned the unit to fastboot.
- Public release live validation on June 8, 2026:
  - command:
    `tools/run_debian_serial_test.py --image artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img --flash-userdata --rootfs artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - sparse `userdata` flash succeeded;
  - Debian reported version `13.5`;
  - Linux reported kernel `6.6.142`;
  - `/sbin/nq-prepare-wifi-firmware` copied `/etc/wifi/bcmdhd.cal` from the
    stock Android `system` partition into the Debian firmware directory;
  - `lsmod` showed `brcmfmac_wcc`, `brcmfmac`, and `brcmutil`;
  - DHCP configured `wlan0` as `192.168.86.42/24`;
  - Dropbear accepted root SSH public-key auth;
  - `aplay -l` reported `card 0: TAS5713 [Steelhead TAS5713]`;
  - `speaker-test -D hw:0,0 -c 2 -r 48000 -t sine -f 1000 -l 1` opened the
    TAS5713 PCM path;
  - the runner returned the unit to fastboot.

## Recommended next live test

The next safe live path is:

1. Publish the public release assets:
   - `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`
   - `artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img`
2. Keep using `fastboot boot` for the kernel image until longer soak tests
   justify flashing `boot`.
3. Start the audio-streamer phase on top of the validated Debian/Wi-Fi/SSH/ALSA
   base.
