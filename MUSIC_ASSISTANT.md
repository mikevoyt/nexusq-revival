# Music Assistant Player Endpoint

## Direction

The feasible Music Assistant path for Nexus Q is to run the Music Assistant
server on another always-on machine and make the Q a native player endpoint.

As of June 10, 2026, upstream Music Assistant documents the server as requiring
a 64-bit OS, Raspberry Pi 4-class or newer hardware, and at least 2 GB RAM. The
Nexus Q currently runs Debian armhf on a 32-bit OMAP4460, so running the full
Music Assistant server on-device is not a supported target.

The first supported endpoint mode is Squeezelite:

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

## Nexus Q Configuration

Create a Squeezelite config on the running Q:

```sh
mkdir -p /run/nexusq
cat >/run/nexusq/squeezelite.env <<'EOF'
NQ_SQUEEZELITE_ENABLE=1
NQ_SQUEEZELITE_NAME='Nexus Q'
NQ_SQUEEZELITE_OUTPUT=hw:0,0
NQ_SQUEEZELITE_RATES=48000
NQ_SQUEEZELITE_MASTER_VOLUME=190
NQ_SQUEEZELITE_SPEAKER_VOLUME=204
# Optional: bypass SlimProto discovery.
# NQ_SQUEEZELITE_SERVER=192.168.1.20:3483
EOF
```

Persist it:

```sh
/sbin/nq-provision \
  --squeezelite /run/nexusq/squeezelite.env \
  --start-squeezelite \
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
- The default sample-rate advertisement is `48000` because `speaker-test` has
  only been validated on the TAS5713 path at 48 kHz.
- TAS5713 mixer values are raw ALSA control values, not linear loudness
  percentages. `NQ_SQUEEZELITE_MASTER_VOLUME=190` is about `-8.5 dB`; `207` is
  roughly 0 dB and should be treated as loud.
- LEDs, ring controls, and hardware volume integration are not wired into Music
  Assistant yet.
- Full Music Assistant server-on-Q support remains a research project, not the
  practical first integration path.
