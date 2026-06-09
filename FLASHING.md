# Flashing

## Requirements

- Nexus Q in fastboot mode.
- Unlocked bootloader.
- Android platform-tools installed on the host.
- Release assets from <https://github.com/mikevoyt/nexusq-revival/releases>.

Check the device:

```sh
fastboot devices -l
```

## Boot The Public Debian Image

This flashes only `userdata` and RAM-boots the kernel image:

```sh
fastboot flash userdata nexusq-debian-trixie-armhf-rootfs.sparse.img
fastboot boot nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img
```

The raw ext4 image is intentionally not used for fastboot flashing. The Nexus Q
bootloader rejected the raw 768 MiB image as too large; the Android sparse image
is the validated `userdata` flash path.

## Serial Shell

The boot image configures USB ACM. On macOS the device appeared as:

```text
/dev/cu.usbmodemAW1S122505241
```

Open it at 115200 baud:

```sh
screen /dev/cu.usbmodemAW1S122505241 115200
```

## Wi-Fi And SSH Test

For local validation, keep the Wi-Fi password in macOS Keychain:

```sh
security add-generic-password -s nexusq-wifi -a "<ssid>" -w "<password>" -U
```

Then run:

```sh
python3 tools/run_debian_serial_test.py \
  --image artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img \
  --flash-userdata \
  --rootfs artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img \
  --ssid "<ssid>" \
  --keychain-service nexusq-wifi \
  --ssh-command 'cat /etc/debian_version; uname -r; lsmod | grep brcm || true; aplay -l'
```

The runner injects Wi-Fi config and an SSH public key through the temporary
serial shell. It does not write the Wi-Fi password into tracked files or the
shareable release images.

For appliance-style use, add `--persist-provisioning --leave-running`. That
copies the runtime Wi-Fi, SSH, and RNG seed files into device-local persistent
state under `/etc/nexusq/` and `/var/lib/nexusq/`, cancels the safety timer, and
leaves Debian running. See [APPLIANCE.md](APPLIANCE.md).

## Fastboot Recovery

The release boot command line includes `nq.autoreboot=180`. If the boot reaches
Debian init, it should return to fastboot automatically after roughly three
minutes.

Manual reboot from the Debian shell:

```sh
/sbin/nq-reboot-fastboot
```

Cancel the timer for longer sessions:

```sh
/sbin/nq-autoreboot-cancel
```

If userspace does not start, use the Nexus Q's normal manual fastboot recovery
procedure and boot again with `fastboot boot`.
