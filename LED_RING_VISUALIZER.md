# LED Ring Visualizer

The Nexus Q LED ring is controlled by the same ATmega328P front-panel AVR that
reports the top-ring input events. The Linux 6.6 port keeps one kernel owner of
that AVR I2C address and exposes the old Nexus Q LED ioctl ABI as `/dev/leds`.

## Kernel Interface

`steelhead_avr.ko` owns I2C address `0x20` on Linux adapter `i2c-1`. In
addition to the `Steelhead Front Panel` input device, it registers:

```text
/dev/leds
```

The misc device implements the legacy `AVR_LED_MAGIC` ioctls used by the old
Android driver:

- `AVR_LED_GET_FIRMWARE_REVISION`
- `AVR_LED_GET_HARDWARE_TYPE`
- `AVR_LED_GET_HARDWARE_REVISION`
- `AVR_LED_GET_MODE`
- `AVR_LED_SET_MODE`
- `AVR_LED_GET_COUNT`
- `AVR_LED_SET_ALL_VALS`
- `AVR_LED_SET_RANGE_VALS`
- `AVR_LED_COMMIT_LED_STATE`
- `AVR_LED_RESET`
- `AVR_LED_SET_MUTE`

The AVR register map behind that ABI is documented in
[FRONT_PANEL_AVR.md](FRONT_PANEL_AVR.md). Full-ring frames use the AVR
`SET_RANGE` register and raw I2C writes because a 32 LED RGB frame is larger
than a standard SMBus block write.

## Visualizer Utility

The rootfs includes:

```text
/usr/sbin/nq-led-visualizer
```

Useful manual commands:

```sh
nq-led-visualizer --info
nq-led-visualizer --all 8 0 0
nq-led-visualizer --all 0 8 0
nq-led-visualizer --all 0 0 8
nq-led-visualizer --sweep --brightness 16
nq-led-visualizer --off
```

The music visualizer mode reads Squeezelite's `-v` shared-memory export from
`/dev/shm/squeezelite-<mac>`. Upstream Squeezelite's `output_vis.c` defines
that export as a 16-bit PCM ring buffer with `VIS_BUF_SIZE=16384`. The Q reader
does not take the shared `pthread_rwlock_t`; it detects the layout and reads
recent samples locklessly so it does not depend on matching libc pthread lock
ABI details between Squeezelite and the visualizer.

The first implementation is intentionally simple: it computes recent PCM
amplitude and renders a rotating color frame. It is not an FFT or
frequency-band visualizer yet.

## Persistent Configuration

Create an LED visualizer config:

```sh
mkdir -p /run/nexusq
cat >/run/nexusq/led-visualizer.env <<'EOF'
NQ_LED_VISUALIZER_ENABLE=1
NQ_LED_VISUALIZER_FPS=20
NQ_LED_VISUALIZER_BRIGHTNESS=255
NQ_LED_VISUALIZER_IDLE_BRIGHTNESS=6
NQ_LED_VISUALIZER_GAIN=8
EOF
```

Persist it:

```sh
/sbin/nq-provision \
  --led-visualizer /run/nexusq/led-visualizer.env \
  --start-squeezelite \
  --status
```

When `NQ_LED_VISUALIZER_ENABLE=1`, `/sbin/nq-start-squeezelite` automatically
adds Squeezelite's `-v` flag unless `NQ_SQUEEZELITE_VISUALIZER` overrides it.
`/sbin/nq-init` starts `/sbin/nq-start-led-visualizer` after Squeezelite and the
knob volume daemon.

For a current-boot-only test:

```sh
mkdir -p /run/nexusq
cp /run/nexusq/led-visualizer.env /tmp/led-visualizer.env
/sbin/nq-start-squeezelite
/sbin/nq-start-led-visualizer
```

Check status and logs:

```sh
/sbin/nq-player-status
cat /run/nexusq-led-visualizer.log
ls -l /dev/shm
```

## Live Validation

Validated on real Nexus Q hardware:

- `steelhead_avr.ko` registers `/dev/leds`
- `nq-led-visualizer --info` reports firmware `0.13`, hardware type `1`,
  hardware revision `1`, and `32` LEDs
- low-brightness `--all` and `--sweep` commands complete through the kernel
  misc device
- Squeezelite started with `-v` creates
  `/dev/shm/squeezelite-f8:8f:ca:20:05:48`
- `nq-led-visualizer` detects that shared-memory buffer and stays running while
  driving the ring

## Known Gaps

- The visualizer is amplitude-based only.
- Music Assistant does not control visualizer state directly yet.
- LED brightness and animation style are local Q config values, not MA UI
  controls.
- The cap-touch center button and ring LEDs are not yet mapped to Music
  Assistant transport state.

Reference:

- Squeezelite visualizer export source:
  <https://github.com/ralph-irving/squeezelite/blob/master/output_vis.c>
