# Bluetooth HCI Spike

This spike brings the Nexus Q BCM4330 Bluetooth controller into the Linux 6.6
appliance image far enough to test HCI bring-up. It does not yet implement an
A2DP sink.

## Hardware Notes

The stock 3.0 Steelhead board file wires Bluetooth to OMAP UART2 with hardware
flow control:

- `uart2_cts`, `uart2_rts`, `uart2_rx`, `uart2_tx`
- `gpio_46`: BCM4330 `BT_REG_ON`
- `gpio_52`: BCM4330 active-low reset
- `gpio_45`: controller wake
- `gpio_47`: host wake interrupt

The unused Bluetooth McBSP1 pins are kept as GPIO outputs, matching the stock
board file's low-power idle setup.

## Firmware Policy

Do not commit `bcm4330.hcd` to the public repository. The rootfs includes
`/sbin/nq-prepare-bluetooth-firmware`, which copies the firmware from the
device's existing stock Android `system` partition at runtime and installs the
names Linux 6.6 searches for:

- `/lib/firmware/brcm/bcm4330.hcd`
- `/lib/firmware/brcm/BCM4330B1.hcd`
- `/lib/firmware/brcm/BCM4330B1.google,steelhead.hcd`

## Runtime Test

Bluetooth is opt-in for this spike. Enable it on a test image with:

```sh
cat >/run/nexusq/bluetooth.env <<'EOF'
NQ_BLUETOOTH_ENABLE=1
NQ_BLUETOOTH_ALIAS='Nexus Q'
EOF

/sbin/nq-provision --bluetooth /run/nexusq/bluetooth.env --start-bluetooth --status
```

Useful diagnostics:

```sh
ls /sys/class/bluetooth
btmgmt info
bluetoothctl show
tail -n 120 /run/nexusq-bluetooth-hci.log /run/nexusq-bluetooth.log
dmesg | grep -i -E 'bluetooth|bcm|uart2|hci'
```

## Hardware Result

Tested on a Nexus Q on 2026-06-27 with the Linux 6.6 Bluetooth spike kernel
booted by `fastboot boot`.

Result: **pass for HCI bring-up**.

- `hci_uart`, `btbcm`, `bluetooth`, `rfcomm`, `bnep`, and `hidp` loaded.
- `/sys/class/bluetooth/hci0` appeared on the OMAP UART2 serdev path.
- The runtime firmware helper copied stock firmware from the Android system
  partition into `/lib/firmware/brcm`.
- The kernel loaded `brcm/BCM4330B1.google,steelhead.hcd`.
- `dmesg` identified the controller as `BCM4330B1` and then as
  `Google Phantasm BCM4330B1 37.4MHz Class1.5`.

Observed caveat: Linux reports the Broadcom default Bluetooth address
`43:30:b1:00:00:00`. The next spike should set a per-device address from the
Nexus Q boot argument `board_steelhead_bluetooth.btaddr`.

If the serdev path does not create `hci0`, the script has an explicit fallback
for manual attach:

```sh
cat >/run/nexusq/bluetooth.env <<'EOF'
NQ_BLUETOOTH_ENABLE=1
NQ_BLUETOOTH_MANUAL_ATTACH=1
NQ_BLUETOOTH_TTY=/dev/ttyS1
NQ_BLUETOOTH_ATTACH_SPEED=115200
EOF

/sbin/nq-start-bluetooth
```

## Source Priority Contract

Bluetooth must coexist with the standalone SomaFM jukebox:

- When Bluetooth is connected or streaming, Bluetooth owns local playback.
- While Bluetooth owns playback, SomaFM NFC taps and the boot default station
  do not stop or replace Bluetooth audio.
- Bluetooth audio should publish visualizer levels to
  `/run/nexusq-audio-levels`, the same file the LED visualizer already follows.

This spike adds `/usr/bin/nq-audio-owner` as the shared priority mechanism. The
future A2DP sink should claim audio on stream start and release it on stream
stop:

```sh
nq-audio-owner claim bluetooth streaming "$sink_pid"
nq-audio-owner release bluetooth
```

SomaFM, NFC jukebox autostart, and Squeezelite startup now check this owner file
before starting local playback. Only `bluetooth` is treated as a blocking owner
today, so existing local source behavior stays unchanged unless Bluetooth has
explicitly claimed priority.

## Next Spike

After `hci0` is reliable, the next PR should add A2DP sink support, most likely
with BlueALSA:

- Start `bluealsa` for A2DP sink profiles.
- Route decoded PCM to `hw:0,0` through the existing 48 kHz TAS5713 path.
- Claim `nq-audio-owner bluetooth streaming`.
- Feed Bluetooth PCM levels into `/run/nexusq-audio-levels` so the LED ring
  follows Bluetooth audio while connected.
