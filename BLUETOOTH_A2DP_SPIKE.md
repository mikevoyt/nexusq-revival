# Bluetooth A2DP Sink Spike

This spike builds on `BLUETOOTH_HCI_SPIKE.md`. The controller already reaches
`hci0`; this branch adds the first user-space A2DP sink path.

## Scope

- Start `bluetoothd` through the existing `/sbin/nq-start-bluetooth` path.
- Start `bluealsa` with the `a2dp-sink` profile.
- Start `bluealsa-aplay` so incoming Bluetooth audio plays through the Nexus Q
  ALSA output.
- Route playback through `plughw:0,0` by default so ALSA can adapt common phone
  stream rates to the TAS5713 path.
- Claim `nq-audio-owner bluetooth streaming` when BlueALSA exposes A2DP PCMs,
  and release the claim when they disappear.
- Stop local SomaFM/Squeezelite playback when Bluetooth claims audio priority.

## Test Config

Use a runtime config first:

```sh
cat >/run/nexusq/bluetooth.env <<'EOF'
NQ_BLUETOOTH_ENABLE=1
NQ_BLUETOOTH_ALIAS='Nexus Q'
NQ_BLUETOOTH_PAIRABLE=1
NQ_BLUETOOTH_DISCOVERABLE=1
NQ_BLUETOOTH_A2DP_ENABLE=1
NQ_BLUETOOTH_A2DP_RESTART=1
NQ_BLUETOOTH_A2DP_PCM=plughw:0,0
NQ_BLUETOOTH_A2DP_VOLUME=software
EOF

/sbin/nq-start-bluetooth
/sbin/nq-player-status
```

The expected process state is:

- `bluetoothd` running
- `bluealsa -p a2dp-sink` running
- `bluealsa-aplay --profile-a2dp ...` running
- `/run/nq-bluetooth-audio-monitor.pid` live

Useful logs:

```sh
tail -n 120 \
  /run/nexusq-bluetooth-hci.log \
  /run/nexusq-bluetooth.log \
  /run/nexusq-bluetooth-audio.log

nq-audio-owner status
bluealsa-aplay --list-pcms
```

## Current Limit

The priority path is wired, but live Bluetooth visualizer levels are not tapped
yet. The next step after phone playback works is to replace direct
`bluealsa-aplay -> ALSA` output with a PCM path that feeds
`/run/nexusq-audio-levels` through `nq-pcm-level-tap` before playback.
