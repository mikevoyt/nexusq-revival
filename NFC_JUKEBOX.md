# NFC SomaFM Jukebox

## Direction

The idea fits the Nexus Q well: printed SomaFM channel cards become the physical
UI, and the Q turns a tap into immediate radio playback.

The practical first prototype is a local SomaFM player plus an NFC tag listener.
It uses `mpg123` through the existing `nq-play` wrapper, so streams are resampled
to the validated 48 kHz TAS5713 path. It does not require Music Assistant.

The original Nexus Q hardware has an NXP PN544 NFC controller on the mezzanine
board. The Linux 6.6 device tree now describes that built-in controller using
the original Steelhead I2C/GPIO wiring, and the rootfs includes load-on-demand
kernel NFC modules plus a small poller for card UID scans.

The scripts still support external USB NFC readers through `libnfc` as a
fallback. External-reader testing needs a host-mode USB setup; the normal
appliance image configures USB gadget serial/networking for bring-up.

Useful references:

- <https://www.wired.com/gallery/nexus-q-teardown/>
- <https://gist.github.com/vvakame/3009802>
- <https://android.googlesource.com/kernel/omap/+/android-omap-steelhead-3.0-ics-aah/arch/arm/mach-omap2/board-steelhead.c>
- <https://docs.kernel.org/driver-api/nfc/nfc-pn544.html>
- <https://somafm.com/live/directstreamlinks.html>

## How It Works

The rootfs includes:

- `nq-somafm-url STATION_ID_OR_URL`
  - Resolves a SomaFM station id through the permanent SomaFM M3U playlist.
  - Example: `groovesalad` resolves through
    `http://somafm.com/m3u/groovesalad.m3u`.
  - The default is HTTP because a freshly booted Q may still have a 1970 clock,
    which breaks HTTPS certificate validation before time is synchronized.
- `nq-somafm-stations`
  - Lists current SomaFM station ids and names from the SomaFM channel feed.
- `nq-somafm-play STATION_ID_OR_URL`
  - Stops prior local `mpg123` playback.
  - Stops Squeezelite by default so ALSA is available.
  - Starts the SomaFM stream through `nq-play`.
  - Use `nq-somafm-play --list` for current station ids.
- `nq-nfc-scan`
  - Prefers the built-in PN544 through Linux NFC generic netlink.
  - Falls back to `nfc-poll` for external libnfc-compatible readers.
- `nq-nfc-poll`
  - Low-level built-in PN544 test helper.
  - Powers the kernel NFC device, starts a poll, and prints target UID data.
- `/sbin/nq-start-nfc-jukebox`
  - Starts an opt-in NFC polling loop.
  - Maps tag UID to station id using `/etc/nexusq/somafm-tags.conf`.

## First Manual Test

Boot the Q with Wi-Fi provisioned, then test a station without NFC:

```sh
nq-somafm-play --help
nq-somafm-play --list
nq-somafm-url groovesalad
nq-somafm-play groovesalad
tail -n 80 /run/nexusq-somafm.log
```

Stop local SomaFM playback:

```sh
nq-somafm-play --stop
```

## Bench Recovery And USB Proxy

When the Q is in an unknown state during audio/NFC bring-up, a host-side watcher
can take over as soon as any control path comes back. It tries fastboot first,
then ADB, SSH, and USB serial. If Linux responds, it asks the Q to reboot to
fastboot; once fastboot is visible, it temporarily boots the legacy-DMA audio
image without flashing:

```sh
tools/nq-recover-boot-legacydma.sh
```

If the Q has USB networking but no Wi-Fi/default route, run a host-side SomaFM
proxy and point the Q at the proxy URL:

```sh
tools/nq_somafm_usb_proxy.py --bind 0.0.0.0 --port 8766
nq-somafm-play http://HOST_USB_IP:8766/station/secretagent
```

`HOST_USB_IP` is the Mac-side USB interface address, for example the `inet`
address on `en12`.

Check that the built-in PN544 can load and probe:

```sh
nq-player-status
dmesg | grep -Ei 'pn544|nfc|i2c3'
nq-nfc-scan --backend kernel --timeout 5
ls -l /sys/class/nfc
nq-nfc-poll --list
```

## Learn Card UIDs

Tap each card/tag and record the UID:

```sh
nq-nfc-scan --timeout 20
```

Force a specific scanner backend when debugging:

```sh
NQ_NFC_SCAN_BACKEND=kernel nq-nfc-scan --timeout 20
NQ_NFC_SCAN_BACKEND=libnfc nq-nfc-scan
```

The prototype maps immutable card UIDs instead of requiring NDEF parsing. You
can still program the cards with a text or URL payload such as
`somafm:groovesalad` for your own inspection tools, but the Q uses the UID map.

Create a tag map:

```sh
cat >/run/nexusq/somafm-tags.conf <<'EOF'
# UID              SomaFM station id
04aabbccddeeff     groovesalad
04112233445566     dronezone
04778899aabbcc     secretagent
EOF
```

Channel ids are visible directly on the Q:

```sh
nq-somafm-play --list
```

Common examples: `groovesalad`, `dronezone`, `secretagent`, `spacestation`,
`beatblender`, `bootliquor`, `indiepop`, `lush`, `u80s`, `reggae`, `synphaera`,
`tikitime`, and `bossa`.

## Enable The Jukebox

Create runtime config:

```sh
cat >/run/nexusq/somafm.env <<'EOF'
NQ_NFC_JUKEBOX_ENABLE=1
NQ_NFC_COOLDOWN_SECONDS=5
NQ_SOMAFM_STOP_SQUEEZELITE=1
NQ_SOMAFM_MASTER_VOLUME=190
NQ_SOMAFM_SPEAKER_VOLUME=204
EOF
```

Persist the config and tag map:

```sh
/sbin/nq-provision \
  --somafm /run/nexusq/somafm.env \
  --somafm-tags /run/nexusq/somafm-tags.conf \
  --start-nfc-jukebox \
  --status
```

Check logs:

```sh
nq-player-status
cat /run/nexusq-nfc-jukebox.log
cat /run/nexusq-nfc-unknown-tags.log
```

Unknown cards are appended to `/run/nexusq-nfc-unknown-tags.log`, which makes
it easy to tap a fresh card, copy its UID into the tag map, and restart:

```sh
NQ_NFC_JUKEBOX_RESTART=1 /sbin/nq-start-nfc-jukebox
```

## Tag Map Format

Each non-comment line is:

```text
UID STATION_ID
```

The UID may contain colons or dashes; it is normalized before matching:

```text
04:aa:bb:cc:dd:ee:ff groovesalad
04-11-22-33-44-55-66 dronezone
```

## Built-In NFC Bring-Up

The built-in PN544 node is based on Google's old Steelhead board file, not a
generic PN544 example:

- I2C bus 3 at 400 kHz.
- PN544 I2C address `0x28`.
- Firmware/download GPIO `162` (`gpio6 2`), initially low.
- Enable GPIO `163` (`gpio6 3`), initially low.
- IRQ GPIO `164` (`gpio6 4`), input pull-up, rising-edge interrupt.
- Pad muxes:
  - `usbb2_ulpitll_dat1.gpio_162`
  - `usbb2_ulpitll_dat2.gpio_163`
  - `usbb2_ulpitll_dat3.gpio_164`

The release build includes `linux66/nexusq-linux66-nfc.fragment`, which builds
the Linux NFC core, HCI, and PN544 I2C driver as modules. `nq-nfc-scan` loads
`pn544_i2c` on demand, then expects `/sys/class/nfc/nfc0` and
`nq-nfc-poll --list` to show a kernel NFC device.

If the PN544 does not appear, capture:

```sh
dmesg | grep -Ei 'pn544|nfc|i2c3|gpio'
find /sys/bus/i2c/devices -maxdepth 2 -type l -o -type d | sort
```
