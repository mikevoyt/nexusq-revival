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
NQ_BLUETOOTH_A2DP_PCM=nexusq48
NQ_BLUETOOTH_A2DP_VOLUME=software
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
`nq-audio-owner status` should report `bluetooth streaming`.

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
```

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

For byte-alignment experiments, set `NQ_BLUETOOTH_A2DP_INPUT_FORMAT=S32_LE` in
the runtime env to force the tap to treat 24-in-32 PCM as high-aligned.

Android may still reconnect on SBC. If `bluealsa-cli info ...` reports
`Selected codec: SBC`, either select aptX-HD from Android developer Bluetooth
codec settings or switch the live PCM with `bluealsa-cli codec ... aptX-HD`.
