# NFC SomaFM Jukebox

## Direction

The idea fits the Nexus Q well: printed SomaFM channel cards become the physical
UI, and the Q turns a tap into immediate radio playback.

The practical first prototype is a local SomaFM player plus an NFC tag listener.
It uses `mpg123` through the existing `nq-play` wrapper, so streams are resampled
to the validated 48 kHz TAS5713 path. It does not require Music Assistant.

The original Nexus Q hardware does have NFC on the mezzanine board, and old
stock boot logs show a `pn544` driver probing successfully. The modern Linux
6.6 DTS in this repo does not yet describe that PN544 device, so the first
software prototype supports libnfc/PCSC-style reader tooling and keeps the
built-in PN544 bring-up as the next hardware task.

If you use an external USB NFC reader for early testing, the Q also needs a
host-mode USB setup. The normal appliance image configures USB gadget serial and
networking for bring-up, so external-reader testing may need a different USB
boot/test arrangement.

Useful references:

- <https://www.wired.com/gallery/nexus-q-teardown/>
- <https://gist.github.com/vvakame/3009802>
- <https://docs.kernel.org/driver-api/nfc/nfc-pn544.html>
- <https://somafm.com/live/directstreamlinks.html>

## How It Works

The rootfs includes:

- `nq-somafm-url STATION_ID_OR_URL`
  - Resolves a SomaFM station id through the permanent SomaFM M3U playlist.
  - Example: `groovesalad` resolves through
    `http://somafm.com/m3u/groovesalad.m3u`.
  - The default is HTTP because a freshly booted Q may still have a 1970 clock,
    which breaks HTTPS certificate validation before time is synchronized.
- `nq-somafm-play STATION_ID_OR_URL`
  - Stops prior local `mpg123` playback.
  - Stops Squeezelite by default so ALSA is available.
  - Starts the SomaFM stream through `nq-play`.
- `nq-nfc-scan`
  - Runs `nfc-poll` once and prints the ISO14443A UID.
- `/sbin/nq-start-nfc-jukebox`
  - Starts an opt-in NFC polling loop.
  - Maps tag UID to station id using `/etc/nexusq/somafm-tags.conf`.

## First Manual Test

Boot the Q with Wi-Fi provisioned, then test a station without NFC:

```sh
nq-somafm-url groovesalad
nq-somafm-play groovesalad
tail -n 80 /run/nexusq-somafm.log
```

Stop local SomaFM playback:

```sh
nq-somafm-play --stop
```

## Learn Card UIDs

Tap each card/tag and record the UID:

```sh
nq-nfc-scan
```

The prototype maps immutable card UIDs instead of requiring NDEF parsing. You
can still program the cards with a text or URL payload such as
`somafm:groovesalad` for your own inspection tools, but the Q uses the UID map.

Create a tag map:

```sh
cat >/run/nexusq/somafm-tags.conf <<'EOF'
# UID              SomaFM station id
04aabbccddeeff     groovesalad
04112233445566     dronezone
04778899aabbcc     secretagent
EOF
```

Channel ids are visible in SomaFM's channel feed:

```sh
curl -fsSL https://somafm.com/channels.xml
```

Common examples: `groovesalad`, `dronezone`, `secretagent`, `spacestation`,
`beatblender`, `bootliquor`, `indiepop`, `lush`, `u80s`, `reggae`, `synphaera`,
`tikitime`, and `bossa`.

## Enable The Jukebox

Create runtime config:

```sh
cat >/run/nexusq/somafm.env <<'EOF'
NQ_NFC_JUKEBOX_ENABLE=1
NQ_NFC_COOLDOWN_SECONDS=5
NQ_SOMAFM_STOP_SQUEEZELITE=1
NQ_SOMAFM_MASTER_VOLUME=190
NQ_SOMAFM_SPEAKER_VOLUME=204
EOF
```

Persist the config and tag map:

```sh
/sbin/nq-provision \
  --somafm /run/nexusq/somafm.env \
  --somafm-tags /run/nexusq/somafm-tags.conf \
  --start-nfc-jukebox \
  --status
```

Check logs:

```sh
nq-player-status
cat /run/nexusq-nfc-jukebox.log
cat /run/nexusq-nfc-unknown-tags.log
```

Unknown cards are appended to `/run/nexusq-nfc-unknown-tags.log`, which makes
it easy to tap a fresh card, copy its UID into the tag map, and restart:

```sh
NQ_NFC_JUKEBOX_RESTART=1 /sbin/nq-start-nfc-jukebox
```

## Tag Map Format

Each non-comment line is:

```text
UID STATION_ID
```

The UID may contain colons or dashes; it is normalized before matching:

```text
04:aa:bb:cc:dd:ee:ff groovesalad
04-11-22-33-44-55-66 dronezone
```

## Built-In NFC Bring-Up

The remaining hardware task is to bind the Q's onboard PN544 in the modern DTS.
Do not guess this from generic PN544 examples. We need the Steelhead-specific
board-file details:

- I2C bus and address.
- IRQ GPIO.
- Enable GPIO.
- Firmware/download GPIO.
- Any regulator or clock assumptions.

Once those are known, the likely kernel work is a small NFC config fragment plus
a PN544 device node in `linux66/omap4-steelhead.dts`.
