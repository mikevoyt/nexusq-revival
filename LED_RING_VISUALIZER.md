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

The music visualizer mode's primary audio source is standalone playback:

- Standalone SomaFM playback writes coarse PCM levels to
  `/run/nexusq-audio-levels` through `nq-pcm-level-tap`. This is the default
  appliance path.
- Legacy Squeezelite support can still expose its `-v` shared-memory buffer at
  `/dev/shm/squeezelite-<mac>` for Music Assistant playback.

Upstream Squeezelite's `output_vis.c` defines that shared-memory export as a
16-bit PCM ring buffer with `VIS_BUF_SIZE=16384`. The Q reader does not take the
shared `pthread_rwlock_t`; it detects the layout and reads recent samples
locklessly so it does not depend on matching libc pthread lock ABI details
between Squeezelite and the visualizer.

The default visualizer style is `pulse`: it derives live PCM energy from the
selected source, normalizes against recent track dynamics, pulses all LEDs from
low-frequency energy, and layers independently rotating color bands for bass,
midrange, and upper-frequency accents. Those bands slowly pick new clockwise or
counterclockwise drift speeds while the palette and texture blends continue to
evolve. A simpler `spectrum` style is also available for experiments.

## Audio Sync

Standalone playback meters decoded PCM before the same PCM drains through
`aplay` and ALSA. If the LEDs visibly lag the speaker output,
`nq-pcm-level-tap` can delay the audio stream after metering:

```sh
NQ_PLAY_AUDIO_DELAY_MS=100 nq-play somafm:groovesalad
```

The SomaFM appliance path defaults to `NQ_SOMAFM_AUDIO_DELAY_MS=0`. Raise the
value only if the LEDs visibly lag the speaker output.

If the LEDs visibly lead the speaker output, delay the visualizer instead. The
default appliance visualizer uses `NQ_LED_VISUALIZER_SYNC_DELAY_MS=170`, and the
running daemon can be tuned live with:

```sh
echo 170 >/run/nexusq-led-sync-delay-ms
```

Use the sync test when the direction is unclear:

```sh
nq-visualizer-sync-test 0
nq-visualizer-sync-test 170
nq-visualizer-sync-test --sweep
```

The test stops local playback and sends metronome-like PCM bursts through the
same `nq-pcm-level-tap` and `/run/nexusq-audio-levels` path used by SomaFM.
Higher test values move the LED pulse later relative to the audible pip.

## Persistent Configuration

The visualizer is enabled by default. Create an LED visualizer config only when
you want to tune brightness, style, or source selection:

```sh
mkdir -p /run/nexusq
cat >/run/nexusq/led-visualizer.env <<'EOF'
NQ_LED_VISUALIZER_ENABLE=1
NQ_LED_VISUALIZER_SOURCE=auto
NQ_LED_VISUALIZER_LEVELS=/run/nexusq-audio-levels
NQ_LED_VISUALIZER_FPS=60
NQ_LED_VISUALIZER_BRIGHTNESS=255
NQ_LED_VISUALIZER_IDLE_BRIGHTNESS=6
NQ_LED_VISUALIZER_GAIN=8
NQ_LED_VISUALIZER_STYLE=pulse
NQ_LED_VISUALIZER_SWIRL=1
NQ_LED_VISUALIZER_SWIRL_MIN_MS=10000
NQ_LED_VISUALIZER_SWIRL_MAX_MS=15000
NQ_LED_VISUALIZER_SWIRL_DURATION_MS=2200
NQ_LED_VISUALIZER_SYNC_DELAY_MS=170
EOF
```

Persist it:

```sh
/sbin/nq-provision \
  --led-visualizer /run/nexusq/led-visualizer.env \
  --start-led-visualizer \
  --status
```

With `NQ_LED_VISUALIZER_SOURCE=auto`, the visualizer reads
`/run/nexusq-audio-levels` when standalone SomaFM playback is active and falls
back to legacy Squeezelite shared memory when that level file is missing or
stale. Set `NQ_LED_VISUALIZER_SOURCE=squeezelite` to force that legacy path.

With the pulse style, `NQ_LED_VISUALIZER_SWIRL=1` adds an occasional rotating
trail over the music-reactive frame. The default interval is randomized between
10 and 15 seconds while playback is active, with each swirl lasting 2.2 seconds.

When Squeezelite is enabled, `/sbin/nq-start-squeezelite` automatically adds
Squeezelite's `-v` flag unless `NQ_SQUEEZELITE_VISUALIZER` overrides it.
`/sbin/nq-init` starts `/sbin/nq-start-led-visualizer` after audio/input bringup
and before the NFC jukebox listener.

For a current-boot-only test:

```sh
mkdir -p /run/nexusq
cp /run/nexusq/led-visualizer.env /tmp/led-visualizer.env
/sbin/nq-start-led-visualizer
```

Check status and logs:

```sh
/sbin/nq-player-status
cat /run/nexusq-led-visualizer.log
cat /run/nexusq-audio-levels
ls -l /dev/shm
```

## Live Validation

Validated on real Nexus Q hardware:

- `steelhead_avr.ko` registers `/dev/leds`
- `nq-led-visualizer --info` reports firmware `0.13`, hardware type `1`,
  hardware revision `1`, and `32` LEDs
- low-brightness `--all` and `--sweep` commands complete through the kernel
  misc device
- SomaFM playback through `nq-play` creates `/run/nexusq-audio-levels`, and
  `nq-led-visualizer --levels /run/nexusq-audio-levels` stays running while
  driving the ring
- Squeezelite started with `-v` creates
  `/dev/shm/squeezelite-f8:8f:ca:20:05:48`, and the same visualizer can fall
  back to that shared-memory buffer

## Known Gaps

- The default `pulse` visualizer is a lightweight integer approximation, not a
  full FFT.
- Music Assistant does not control visualizer state directly yet.
- LED brightness and animation style are local Q config values, not MA UI
  controls.
- The cap-touch center button and ring LEDs are not yet mapped to Music
  Assistant transport state.

Reference:

- Squeezelite visualizer export source:
  <https://github.com/ralph-irving/squeezelite/blob/master/output_vis.c>
