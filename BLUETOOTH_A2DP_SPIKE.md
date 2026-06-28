# Bluetooth A2DP Sink Spike

This spike builds on `BLUETOOTH_HCI_SPIKE.md`. The controller already reaches
`hci0`; this branch adds the first user-space A2DP sink path.

## Scope

- Start `bluetoothd` through the existing `/sbin/nq-start-bluetooth` path.
- Register a `NoInputNoOutput` pairing agent so a phone can pair without
  keyboard/display confirmation on the Q.
- Start `bluealsa` with the `a2dp-sink` profile and optional higher-quality
  codecs enabled by default: `aptX-HD`, `aptX`, and `Opus`. SBC remains the
  mandatory fallback.
- Route incoming Bluetooth PCM through `bluealsa-cli open`,
  `nq-pcm-level-tap`, and `aplay`, so Bluetooth playback feeds the same LED
  visualizer level file as local SomaFM playback. The tap accepts `S16_LE`,
  `S24_LE`, and `S32_LE` input and normalizes playback output to `S16_LE` for
  the Nexus Q ALSA profile.
- Route playback through `nexusq48` by default so common 44.1 kHz phone streams
  are converted to the TAS5713 path's 48 kHz hardware rate.
- Prefer aptX-HD automatically when BlueALSA exposes a connected A2DP source
  PCM and the phone supports that codec.
- Set the BlueALSA PCM volume to full scale on reconnect, avoiding quiet
  sessions when the transport volume comes up low.
- Claim `nq-audio-owner bluetooth streaming` while a BlueALSA A2DP source PCM is
  active, and release the claim when it disappears.
- Stop local SomaFM/Squeezelite playback when Bluetooth claims audio priority.

## Test Config

Use a runtime config first:

```sh
cat >/run/nexusq/bluetooth.env <<'EOF'
NQ_BLUETOOTH_ENABLE=1
NQ_BLUETOOTH_ALIAS='Nexus Q'
NQ_BLUETOOTH_PAIRABLE=1
NQ_BLUETOOTH_DISCOVERABLE=1
NQ_BLUETOOTH_AGENT_ENABLE=1
NQ_BLUETOOTH_A2DP_ENABLE=1
NQ_BLUETOOTH_A2DP_RESTART=1
NQ_BLUETOOTH_A2DP_CODECS='aptX-HD aptX Opus'
NQ_BLUETOOTH_A2DP_PREFERRED_CODEC=aptX-HD
NQ_BLUETOOTH_A2DP_PCM=nexusq48
NQ_BLUETOOTH_A2DP_VOLUME=software
NQ_BLUETOOTH_A2DP_PCM_VOLUME=127
EOF

/sbin/nq-start-bluetooth
/sbin/nq-player-status
```

The expected process state is:

- `bluetoothd` running
- `bt-agent --capability=NoInputNoOutput` running
- `bluealsa -p a2dp-sink --codec=aptX-HD --codec=aptX --codec=Opus` running
- `/run/nq-bluetooth-tap.pid` live, with `bluealsa-cli`, `nq-pcm-level-tap`,
  and `aplay` in the playback pipeline

From the phone, pair with `Nexus Q`, connect it for media audio, and start
playback. Once the phone is streaming, `bluealsa-cli list-pcms` should show an
A2DP source PCM, `bluealsa-cli info ...` should show the selected codec, and
`nq-audio-owner status` should report `bluetooth streaming`. If the phone
initially selects SBC but supports aptX-HD, the tap worker now asks BlueALSA to
switch that live PCM to aptX-HD before opening the stream.

Useful logs:

```sh
tail -n 120 \
  /run/nexusq-bluetooth-hci.log \
  /run/nexusq-bluetooth.log \
  /run/nexusq-bluetooth-audio.log

nq-audio-owner status
bluealsa-cli list-pcms
bluealsa-cli info /org/bluealsa/hci0/dev_XX_XX_XX_XX_XX_XX/a2dpsnk/source
bluealsa-cli codec /org/bluealsa/hci0/dev_XX_XX_XX_XX_XX_XX/a2dpsnk/source aptX-HD
bluealsa-cli volume /org/bluealsa/hci0/dev_XX_XX_XX_XX_XX_XX/a2dpsnk/source 127 127
```

## AVRCP Media-Control Groundwork

The rootfs includes `nq-bluetooth-player`, a small BlueZ D-Bus helper for the
phone-side AVRCP media-control surface. It does not change daemon behavior yet;
it gives us a reproducible command-line probe before binding physical Q inputs
to phone playback controls.

Useful commands:

```sh
nq-bluetooth-player status
nq-bluetooth-player devices
nq-bluetooth-player play
nq-bluetooth-player pause
nq-bluetooth-player toggle
nq-bluetooth-player next
nq-bluetooth-player previous
```

`status` reports paired devices that expose `org.bluez.MediaControl1` and, when
BlueZ exposes one for the active AVRCP session, the current
`org.bluez.MediaPlayer1` object and raw track/status properties. The explicit
control commands call BlueZ `MediaControl1` methods on the active media-capable
device.

`nq-knob-volume` uses the same helper for the top center touch when
`NQ_KNOB_MUTE_ACTION=auto`, which is the default. With a phone connected over
Bluetooth, tap the top center once to toggle AVRCP play/pause. If no Bluetooth
media-control session is active, the daemon falls back to the local TAS5713
speaker-switch mute behavior.

## Current Codec Result

The first Pixel 9 Pro baseline negotiated SBC at 44.1 kHz with bitpool 53,
about 328 kbps. Enabling optional codecs advertised `aptX-HD`, `aptX`, and
`Opus`; after reconnect, the Pixel negotiated `aptX-HD` at 48 kHz, but the
original tap path treated BlueALSA's `S24_LE` PCM as `S16_LE`, which produced
static.

This branch fixes that by reading the negotiated `Format:` from
`bluealsa-cli info`, passing it to `nq-pcm-level-tap --input-format`, and
converting higher-width input to clean `S16_LE` before metering, chime/delay
processing, and ALSA playback.

The live Pixel 9 Pro retest passed after deploying the conversion path:
`aptX-HD`, `S24_LE`, stereo 48 kHz, Bluetooth volume `127/127`, nonzero
visualizer levels, and clean audible playback on the Nexus Q.

The initial live run logged a burst of BlueALSA `PCM overrun` warnings during
stream startup, but the count did not increase during a 15-second steady
playback window. The tap worker now polls for a newly exposed A2DP PCM every
100 ms while idle, reducing the startup window where BlueALSA can decode before
the PCM reader is attached.

A later live tap/play-pause stress test exposed a separate steady-playback
failure: the original 80 ms `aplay` buffer was too small after A2DP transport
restarts, causing audible stutter, ALSA underruns, and a BlueALSA
`PCM overrun` storm. The default tap path now uses
`NQ_BLUETOOTH_A2DP_TAP_APLAY_BUFFER_TIME=500000` and
`NQ_BLUETOOTH_A2DP_TAP_APLAY_PERIOD_TIME=100000`. With aptX-HD selected and
the larger buffer, a 25-second live playback window logged zero BlueALSA
overruns, zero ALSA underruns, and zero missing RTP warnings.

For byte-alignment experiments, set `NQ_BLUETOOTH_A2DP_INPUT_FORMAT=S32_LE` in
the runtime env to force the tap to treat 24-in-32 PCM as high-aligned.

Android may still reconnect on SBC if the phone does not accept a live codec
switch or aptX-HD is disabled in developer Bluetooth codec settings. In that
case the Q continues with the phone-selected codec rather than dropping audio.
