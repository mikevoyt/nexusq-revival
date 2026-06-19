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

Keep the front-panel driver modular while bring-up is still active. The first
DT attempt added an AVR child under `&i2c2`, but the resulting diagnostic boot
image did not reach the USB serial loader. A follow-up diagnostic image with
the AVR DT node removed also failed to reach the loader, so the immediate boot
regression is not proven to be the AVR node itself.

To avoid blocking knob bring-up on DT, the driver can now run without an IRQ and
poll the AVR FIFO. That allows live testing from a known-good boot by manually
creating the I2C client:

```sh
insmod /lib/modules/$(uname -r)/kernel/drivers/input/misc/steelhead_avr.ko poll_ms=50
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
`NQ_INPUT_I2C_ADDR=0x20`, and `NQ_AVR_POLL_MS=50`. Set
`NQ_INPUT_ENABLE=0` in `/etc/nexusq/input.env` to disable automatic
front-panel binding, or override those values there for diagnostics.

For an already-running Q, the host-side helper installs the current module and
knob daemon over SSH, attempts the same manual bind, and starts
`nq-knob-volume`:

```sh
tools/install_front_panel_remote.sh
```

Set `TARGET`, `NQ_INPUT_I2C_ADAPTER`, `NQ_INPUT_I2C_ADDR`,
`NQ_AVR_POLL_MS`, or `NQ_START_KNOB_VOLUME=0` to override its defaults.

## TAS5713 Volume Daemon

The userspace helper `nq-knob-volume` reads `Steelhead Front Panel` evdev
events and adjusts the TAS5713 ALSA mixer through `amixer`.

Default mixer bounds are intentionally conservative:

- `NQ_KNOB_CONTROL=Master Volume`
- `NQ_KNOB_MUTE_CONTROL=Speaker Switch`
- `NQ_KNOB_MIN=120`
- `NQ_KNOB_MAX=207`
- `NQ_KNOB_STEP=2`

`207` is the current safe cap near 0 dB. The TAS5713 control can go higher, but
values above this are much louder and should not be the default for a shared
release image.

## Live Validation

Validated on a Nexus Q booted into the Linux 6.6 Debian image:

- `steelhead-avr 1-0020: front panel AVR firmware 0.13`
- `/proc/bus/input/devices` reports `Name="Steelhead Front Panel"`
- clockwise ring motion emits `KEY_VOLUMEUP` (`code 115`) and increments
  `Master Volume`
- counterclockwise ring motion emits `KEY_VOLUMEDOWN` (`code 114`) and
  decrements `Master Volume`
- center/touch events emit `KEY_MUTE` (`code 113`) and toggle `Speaker Switch`

The first validation was run with `poll_ms=50` and the daemon range
`120..207`. Clockwise movement raised `Master Volume` from `120` into the
130s; counterclockwise movement lowered it again.

## Future LED Work

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
second userspace I2C client. A future extension can expose the ring through the
LED subsystem or a small misc device, while preserving one kernel-side owner of
the AVR I2C address.
