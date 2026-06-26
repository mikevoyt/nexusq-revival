# Music Assistant Player Endpoint

## Direction

The feasible Music Assistant path for Nexus Q is to run the Music Assistant
server on another always-on machine and make the Q a native player endpoint.

As of June 10, 2026, upstream Music Assistant documents the server as requiring
a 64-bit OS, Raspberry Pi 4-class or newer hardware, and at least 2 GB RAM. The
Nexus Q currently runs Debian armhf on a 32-bit OMAP4460, so running the full
Music Assistant server on-device is not a supported target.

Squeezelite is the supported Music Assistant endpoint mode. It is now an
optional alternative to the standalone SomaFM NFC jukebox:

- Music Assistant has a native Squeezelite/SlimProto player provider.
- Debian trixie ships `squeezelite` for `armhf`.
- The client can use the Q's internal TAS5713 ALSA path at `hw:0,0`.
- The server can resample to 48 kHz, matching the audio mode already validated
  on the Q.

Useful upstream references:

- <https://www.music-assistant.io/installation/>
- <https://www.music-assistant.io/player-support/squeezelite/>

## Server Setup

Run Music Assistant on a supported machine such as Home Assistant OS, a
Raspberry Pi 4 or newer, a NAS, or a small x86 host. Keep the server and Nexus Q
on the same layer-2 network so discovery and streaming work normally.

In Music Assistant, add or enable the `Squeezelite` player provider. The default
SlimProto port is `3483`. If discovery does not work on your network, configure
the Q with the server host explicitly.

For the Nexus Q player, enable Queue Flow Mode and set Flow Mode sample rate to
`48 kHz`. The current Linux 6.6 TAS5713 path is validated at 48 kHz; 44.1 kHz
streams fail to derive a valid serial bit clock and must be resampled before
they reach ALSA.

## Nexus Q Configuration

Create a Squeezelite config on the running Q:

```sh
mkdir -p /run/nexusq
cat >/run/nexusq/squeezelite.env <<'EOF'
NQ_SQUEEZELITE_ENABLE=1
NQ_SQUEEZELITE_NAME='Nexus Q'
NQ_SQUEEZELITE_OUTPUT=hw:0,0
NQ_SQUEEZELITE_RATES=48000-48000
NQ_SQUEEZELITE_RESAMPLE=hLX
NQ_SQUEEZELITE_MASTER_VOLUME=231
NQ_SQUEEZELITE_SPEAKER_VOLUME=207
# Optional: bypass SlimProto discovery.
# NQ_SQUEEZELITE_SERVER=192.168.1.20:3483
EOF
```

To enable the LED-ring visualizer, add a separate config:

```sh
cat >/run/nexusq/led-visualizer.env <<'EOF'
NQ_LED_VISUALIZER_ENABLE=1
NQ_LED_VISUALIZER_SOURCE=squeezelite
NQ_LED_VISUALIZER_BRIGHTNESS=255
NQ_LED_VISUALIZER_IDLE_BRIGHTNESS=6
NQ_LED_VISUALIZER_GAIN=8
NQ_LED_VISUALIZER_STYLE=pulse
EOF
```

Persist it:

```sh
/sbin/nq-provision \
  --squeezelite /run/nexusq/squeezelite.env \
  --led-visualizer /run/nexusq/led-visualizer.env \
  --start-squeezelite \
  --start-led-visualizer \
  --status
```

Or start it only for the current boot:

```sh
/sbin/nq-start-squeezelite
```

Check status and logs:

```sh
/sbin/nq-player-status
cat /run/nexusq-squeezelite.log
cat /run/nexusq-led-visualizer.log
```

If the Q disappears from Music Assistant, first check that `squeezelite` is
actually running:

```sh
/sbin/nq-player-status
```

If the log says `disabled; set NQ_SQUEEZELITE_ENABLE=1`, create or restore
`/etc/nexusq/squeezelite.env` and restart the endpoint:

```sh
/sbin/nq-provision \
  --squeezelite /run/nexusq/squeezelite.env \
  --start-squeezelite \
  --status
```

When setting `NQ_SQUEEZELITE_NAME` manually, quote names with spaces, for
example `NQ_SQUEEZELITE_NAME='Nexus Q'`.

If this Q should be dedicated to Music Assistant, disable the NFC jukebox in
`/etc/nexusq/somafm.env`:

```sh
NQ_NFC_JUKEBOX_ENABLE=0
```

## Host-Side Test Runner

The serial runner can upload a temporary player config while it provisions Wi-Fi
and SSH:

```sh
python3 tools/run_debian_serial_test.py \
  --image artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img \
  --flash-userdata \
  --rootfs artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img \
  --ssid "<ssid>" \
  --keychain-service nexusq-wifi \
  --enable-squeezelite \
  --persist-provisioning \
  --leave-running
```

Add `--squeezelite-server host:3483` if the server is not discovered
automatically.

## Current Caveats

- Squeezelite startup is handled by `nq-init`, not by a normal systemd unit.
- Squeezelite is disabled unless `/etc/nexusq/squeezelite.env` or runtime config
  sets `NQ_SQUEEZELITE_ENABLE=1`.
- The default sample-rate advertisement is `48000-48000` because the TAS5713
  path is currently validated only at 48 kHz.
- `NQ_SQUEEZELITE_RESAMPLE=hLX` enables Squeezelite's SoX resampler as a
  backstop. Music Assistant Queue Flow Mode at 48 kHz is still recommended so
  the server sends a fixed-rate FLAC stream.
- TAS5713 mixer values are raw ALSA control values, not linear loudness
  percentages. `207` is roughly 0 dB; the release default
  `NQ_SQUEEZELITE_MASTER_VOLUME=231` is the tested loud passive-speaker profile
  at about +12 dB. If tracks sound harsh or clipped, lower
  `NQ_SQUEEZELITE_MASTER_VOLUME` and `NQ_KNOB_MAX` to `207`.
- The physical top ring controls local TAS5713 volume. Music Assistant does not
  yet receive hardware-volume feedback from those local changes.
- The LED-ring visualizer is local to the Q. Music Assistant does not control
  the animation or brightness yet.
- Cap-touch handling is not wired into Music Assistant yet.
- Full Music Assistant server-on-Q support remains a research project, not the
  practical first integration path.
