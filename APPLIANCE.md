# Appliance Provisioning

The v0.2.0 release is intended to boot normally: flash Debian to `userdata`,
flash the Linux 6.6 image to `boot`, and then use `fastboot reboot`. The stock
`recovery` partition is left untouched so manual fastboot recovery remains
available.

## Provisioning Model

The Debian rootfs supports two configuration layers:

- Runtime test config in `/run/nexusq/` or `/tmp/`.
- Persistent device-local config in `/etc/nexusq/`.

Runtime config takes precedence so host-side tests can override saved appliance
settings without erasing them. Persistent config is intended for a Q that should
join Wi-Fi and start SSH automatically on later boots.

Persistent files:

- `/etc/nexusq/wpa_supplicant.conf`
- `/etc/nexusq/authorized_keys`
- `/etc/nexusq/squeezelite.env`
- `/etc/nexusq/adbd.env`
- `/var/lib/nexusq/rng.seed`

Do not commit real Wi-Fi config, private keys, or generated seeds. They belong
only on the device or in ignored local files.

## Serial Provisioning

Boot the public Debian image, open the USB serial shell, then upload temporary
files and persist them:

```sh
mkdir -p /run/nexusq
cat >/run/nexusq/wpa_supplicant.conf <<'EOF'
ctrl_interface=DIR=/run/wpa_supplicant
update_config=0
ap_scan=1
p2p_disabled=1
country=US
network={
    ssid="YOUR_SSID"
    psk="YOUR_PASSWORD"
}
EOF

cat >/run/nexusq/authorized_keys <<'EOF'
ssh-ed25519 AAAA... your-key-comment
EOF

head -c 64 /dev/urandom >/run/nexusq/rng.seed
chmod 600 /run/nexusq/*

/sbin/nq-provision \
  --wifi /run/nexusq/wpa_supplicant.conf \
  --authorized-keys /run/nexusq/authorized_keys \
  --rng-seed /run/nexusq/rng.seed \
  --cancel-autoreboot \
  --start-network
```

Check status:

```sh
/sbin/nq-appliance-status
cat /run/nexusq-network.log
```

## ADB Debug Bridge

Development images can start a small ADB-compatible debug daemon on TCP port
5555. It is disabled unless explicitly enabled in device-local config:

```sh
cat >/etc/nexusq/adbd.env <<'EOF'
NQ_ADBD_ENABLE=1
NQ_ADBD_PORT=5555
# Optional; defaults to /bin/bash when available, then /bin/sh.
# NQ_ADBD_SHELL=/bin/bash
EOF

/sbin/nq-start-adbd
```

Connect from a development host with Android platform-tools:

```sh
adb connect 192.168.86.38:5555
adb -s 192.168.86.38:5555 shell 'id; uname -a'
adb -s 192.168.86.38:5555 push local-file.txt /tmp/local-file.txt
adb -s 192.168.86.38:5555 pull /tmp/local-file.txt ./local-file.txt
```

The repository includes a host smoke test for this surface:

```sh
ADB=/path/to/platform-tools/adb tools/test_adb_lite.sh 192.168.86.38:5555
```

The daemon provides unauthenticated root access for trusted local bring-up
networks. It supports the classic ADB transport handshake, root Bash shells,
recursive `adb push`/`adb pull` file sync, `adb root`, and `adb reboot
bootloader`. It is not Android userspace `adbd`: there is no authentication,
property service, package manager, logcat, JDWP, or Android framework shell
protocol.

## Music Assistant Player

The appliance rootfs can act as a Music Assistant Squeezelite player endpoint.
Run the Music Assistant server on a supported 64-bit host and keep it on the
same local network as the Q.

Persist an opt-in Squeezelite config:

```sh
cat >/run/nexusq/squeezelite.env <<'EOF'
NQ_SQUEEZELITE_ENABLE=1
NQ_SQUEEZELITE_NAME='Nexus Q'
NQ_SQUEEZELITE_OUTPUT=hw:0,0
NQ_SQUEEZELITE_RATES=48000-48000
NQ_SQUEEZELITE_RESAMPLE=hLX
NQ_SQUEEZELITE_MASTER_VOLUME=231
NQ_SQUEEZELITE_SPEAKER_VOLUME=207
# Optional if SlimProto discovery does not work:
# NQ_SQUEEZELITE_SERVER=192.168.1.20:3483
EOF

/sbin/nq-provision \
  --squeezelite /run/nexusq/squeezelite.env \
  --start-squeezelite \
  --status
```

Check the player:

```sh
/sbin/nq-player-status
cat /run/nexusq-squeezelite.log
```

The TAS5713 volume controls use raw ALSA values. `207` is roughly 0 dB, and the
default `NQ_SQUEEZELITE_MASTER_VOLUME=231` is the tested loud passive-speaker
profile at about +12 dB. If tracks sound harsh or clipped, lower
`NQ_SQUEEZELITE_MASTER_VOLUME` and `NQ_KNOB_MAX` to `207`.
In Music Assistant, enable Queue Flow Mode for the Q player and set the Flow
Mode sample rate to 48 kHz.

## Local MP3 Test

The appliance image includes `mpg123` and OpenSSH SFTP server support, so modern
`scp` can copy files through the default Dropbear SSH server:

```sh
scp test.mp3 root@192.168.86.38:/root/test.mp3
ssh root@192.168.86.38 'nq-play /root/test.mp3'
```

Use `nq-play` instead of plain `mpg123` for local tests. The current TAS5713
kernel path is validated at 48 kHz/S16 stereo, while many MP3s are 44.1 kHz.
`nq-play` forces `mpg123` to resample to 48 kHz, selects `hw:0,0`, applies the
same audible mixer defaults as Squeezelite, and uses a larger ALSA buffer to
avoid short writes. For direct playback, wait a few seconds after stopping Music
Assistant playback so Squeezelite can release the ALSA device.

See [MUSIC_ASSISTANT.md](MUSIC_ASSISTANT.md) for the porting rationale and
Music Assistant setup notes.

## Host-Side Provisioning

The Debian serial runner can provision persistently without writing secrets into
the repository:

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

`--leave-running` cancels the safety timer and does not ask the target to return
to fastboot at the end. Omit it during risky tests. Omit
`--enable-squeezelite` when you only want Wi-Fi/SSH provisioning.

## Recovery

The public release image stays running by default. It only returns to fastboot
automatically when booted with an explicit diagnostic command-line argument
such as `nq.autoreboot=180`.

Manual recovery from Debian:

```sh
/sbin/nq-reboot-fastboot
```

Clear persistent appliance state:

```sh
/sbin/nq-provision --clear-wifi --clear-authorized-keys --clear-squeezelite --clear-rng-seed
```

If userspace does not start, use the Nexus Q manual fastboot procedure and boot
again with `fastboot boot`, or reinstall the release image with
`fastboot flash boot`.
