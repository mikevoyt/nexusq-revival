# Nexus Q Front Panel AVR

The Nexus Q front panel is managed by an Atmel ATmega328P connected to OMAP4
I2C2. The old 3.0 Steelhead board file used:

- I2C bus: hardware I2C2, 400 kHz
- I2C address: `0x20`
- Reset GPIO: `gpio_48` (`gpmc_a24.gpio_48`), initialized high
- Interrupt GPIO: `gpio_49` (`gpmc_a25.gpio_49`), input pull-up, wake-capable

The AVR exposes a key FIFO and LED control registers. The known key events are:

- `0x00`: mute / center touch
- `0x01`: volume up
- `0x02`: volume down

The Linux 6.6 port currently adds a modular `steelhead_avr.ko` input driver.
It exposes the controls as an evdev device named `Steelhead Front Panel` and
maps the AVR events to `KEY_MUTE`, `KEY_VOLUMEUP`, and `KEY_VOLUMEDOWN`.

## Current Strategy

Keep the front-panel driver modular while bring-up is still active. The 6.6 DT
now registers the AVR on OMAP hardware I2C2, Linux adapter `i2c-1`, at address
`0x20`, with reset on GPIO48 and IRQ on GPIO49.

The driver can run from IRQs, poll the AVR FIFO for diagnostics, or both. Manual
binding remains useful when testing from a known-good boot:

```sh
insmod /lib/modules/$(uname -r)/kernel/drivers/input/misc/steelhead_avr.ko poll_ms=50 force_poll=1 debug_events=1
echo 'steelhead-avr 0x20' >/sys/bus/i2c/devices/i2c-1/new_device
cat /proc/bus/input/devices
```

On OMAP4 Linux, hardware I2C2 is expected to appear as adapter `i2c-1` because
the DT aliases are zero-based (`i2c1 = &i2c2`). Confirm live adapter names before
making this persistent.

The generated Debian rootfs supports a binding helper. To test or override it
at runtime:

```sh
mkdir -p /tmp
printf 'NQ_INPUT_I2C_ADAPTER=i2c-1\nNQ_INPUT_I2C_ADDR=0x20\n' >/tmp/input.env
/sbin/nq-load-input
```

Current release rootfs builds default to `NQ_INPUT_I2C_ADAPTER=i2c-1`,
`NQ_INPUT_I2C_ADDR=0x20`, `NQ_AVR_POLL_MS=50`, `NQ_AVR_FORCE_POLL=1`, and
`NQ_AVR_LEGACY_INIT=1`.
Set `NQ_INPUT_ENABLE=0` in `/etc/nexusq/input.env` to disable automatic
front-panel binding, or override these values there for diagnostics:

- `NQ_AVR_FORCE_POLL=1`: poll even when the IRQ is registered
- `NQ_AVR_DEBUG_EVENTS=1`: log raw FIFO bytes
- `NQ_AVR_RESET_PULSE_MS=100`: pulse AVR reset during probe for experiments
- `NQ_AVR_LEGACY_INIT=0`: skip the legacy LED/control init sequence

For an already-running Q, the host-side helper installs the current module and
knob daemon over SSH, attempts the same manual bind, and starts
`nq-knob-volume`:

```sh
tools/install_front_panel_remote.sh
```

Set `TARGET`, `NQ_INPUT_I2C_ADAPTER`, `NQ_INPUT_I2C_ADDR`,
`NQ_AVR_POLL_MS`, `NQ_AVR_FORCE_POLL`, `NQ_AVR_DEBUG_EVENTS`,
`NQ_AVR_RESET_PULSE_MS`, or `NQ_START_KNOB_VOLUME=0` to override its defaults.

## Direct AVR Debug Helper

The rootfs includes `/usr/sbin/nq-avr-i2c`, a small direct I2C debug utility.
It uses `I2C_SLAVE_FORCE`, so it can inspect the AVR even when the kernel driver
owns the normal client. Reads and writes retry transient AVR busy responses like
the old 3.0 driver. Avoid long direct polling while `steelhead_avr.ko` is also
polling.

Useful commands:

```sh
nq-avr-i2c dump
nq-avr-i2c read 0x0a 2
nq-avr-i2c mode 1
nq-avr-i2c fifo 20 50
```

Known live register values after the 6.6 legacy init:

- `0x00`: `0xff` when the FIFO is empty
- `0x01`: `0x08` observed mute/touch threshold
- `0x02`: LED/control mode, usually `0x01` after reset
- `0x07`: `0x20` LED count
- `0x08`: `0x01` hardware type
- `0x09`: `0x01` hardware revision
- `0x0a`: firmware `0.13` when read as two bytes

## TAS5713 Volume Daemon

The userspace helper `nq-knob-volume` reads `Steelhead Front Panel` evdev
events and adjusts the TAS5713 ALSA mixer through `amixer`.

Default mixer bounds use the currently tested loud passive-speaker profile:

- `NQ_KNOB_CONTROL=Master Volume`
- `NQ_KNOB_MUTE_CONTROL=Speaker Switch`
- `NQ_KNOB_MIN=120`
- `NQ_KNOB_MAX=231`
- `NQ_KNOB_STEP=2`
- `NQ_KNOB_MUTE_ACTION=auto`
- `NQ_KNOB_BLUETOOTH_PLAYER=/usr/sbin/nq-bluetooth-player`
- `NQ_KNOB_AUDIO_OWNER_FILE=/run/nexusq-audio-owner`
- `NQ_KNOB_MUTE_COOLDOWN_MS=8000`

`207` is roughly 0 dB. The release default of `231` is about +12 dB and was
validated with an external passive speaker. If playback clips or the speaker
sounds strained, lower `NQ_KNOB_MAX` to `207`.

The center touch event is still `KEY_MUTE`, but userspace policy is now
configurable:

- `NQ_KNOB_MUTE_ACTION=auto`: when `nq-audio-owner` reports Bluetooth as the
  active owner, launch `nq-bluetooth-player toggle`; otherwise fall back to the
  TAS5713 `Speaker Switch`.
- `NQ_KNOB_MUTE_ACTION=bluetooth-toggle`: only send AVRCP play/pause.
- `NQ_KNOB_MUTE_ACTION=mixer`: only toggle the TAS5713 speaker switch.
- `NQ_KNOB_MUTE_ACTION=none`: ignore the center touch.

The default `auto` behavior lets Bluetooth playback take priority: when a phone
is connected over A2DP/AVRCP, tapping the top center toggles phone playback
instead of muting the amplifier. Local SomaFM playback keeps the old speaker
mute fallback. `NQ_KNOB_MUTE_COOLDOWN_MS` filters repeat center-touch events so
one tap does not produce multiple play/pause toggles.

## Live Validation

Validated on a Nexus Q booted into the Linux 6.6 Debian image:

- `steelhead-avr 1-0020: front panel AVR firmware 0.13`
- `/proc/bus/input/devices` reports `Name="Steelhead Front Panel"`
- GPIO49 interrupt registration works; the IRQ count increments for AVR reset
  notifications
- The driver can run with `force_poll=1`, which drains the FIFO every 50 ms
  even if GPIO49 rotation interrupts are missed.
- AVR reset notification `0xfe` is read from the FIFO after a reset pulse
- `nq-knob-volume` starts and preserves the current `Master Volume`
- `nq-knob-volume` can adjust `Master Volume` through ALSA when it receives
  `KEY_VOLUMEUP` or `KEY_VOLUMEDOWN` evdev events.
- Physical ring rotation now produces `KEY_VOLUMEUP` and `KEY_VOLUMEDOWN`
  events on `/dev/input/event0`, and `nq-knob-volume` drives the TAS5713
  `Master Volume` control from those events.

The main runtime trap during bring-up was stale or hangup-killed userspace
state after reloading the modular input driver from an ADB shell. The rootfs
starter scripts now ignore `SIGHUP` before backgrounding daemons, and
`nq-knob-volume` ignores `SIGHUP` directly as well.

Historical testing before the final fix showed:

- The Linux input bridge is registered and reports events when FIFO bytes
  arrive.
- The FIFO path works because reset event `0xfe` and physical ring events are
  observed.
- Direct FIFO polling through `/dev/i2c-1` also sees only `0xff` idle values
  during current tests, including a 15 s capture with `steelhead_avr.ko`
  unloaded and retrying direct I2C reads.
- Sweeping LED/control modes `0`, `1`, `2`, and `3` did not produce motion
  events during the available capture windows.

If front-panel input appears dead during future module-reload experiments, first
check that `nq-knob-volume` is still running and attached to the current
`/dev/input/event0`, then restart `/sbin/nq-start-knob-volume` after the input
driver reload.

## LED Ring Control

The old AVR LED register map is:

- `0x02`: LED mode
- `0x03`: set all LEDs
- `0x04`: set LED range
- `0x05`: commit buffered LED state
- `0x06`: mute LED
- `0x07`: LED count
- `0x08`: hardware type
- `0x09`: hardware revision
- `0x0a`: firmware version

LED support should live with the same AVR owner as the input driver, not in a
second userspace I2C client. The Linux 6.6 driver now follows that model:
`steelhead_avr.ko` owns the AVR and exposes the legacy Nexus Q LED ioctl ABI at
`/dev/leds`.

The generated rootfs includes `/usr/sbin/nq-led-visualizer`, which can set test
colors, run a sweep, or read Squeezelite's shared-memory PCM export to animate
the ring during playback. See [LED_RING_VISUALIZER.md](LED_RING_VISUALIZER.md)
for configuration and validation details.
