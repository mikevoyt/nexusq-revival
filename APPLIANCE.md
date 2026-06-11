# Appliance Provisioning

This project is still conservative about boot: the recommended image is flashed
to `userdata`, while the kernel/initramfs is launched with `fastboot boot`.
That keeps the stock `boot` and `recovery` partitions untouched until longer
soak tests justify a permanent boot install.

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
NQ_SQUEEZELITE_RATES=48000
NQ_SQUEEZELITE_MASTER_VOLUME=190
NQ_SQUEEZELITE_SPEAKER_VOLUME=204
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

The TAS5713 volume controls use raw ALSA values. The default
`NQ_SQUEEZELITE_MASTER_VOLUME=190` is about `-8.5 dB`; `207` is roughly 0 dB.

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

The release boot image still arms `nq.autoreboot=180`. If the boot reaches
userspace and the timer is not cancelled, the Q should return to fastboot.

Manual recovery from Debian:

```sh
/sbin/nq-reboot-fastboot
```

Clear persistent appliance state:

```sh
/sbin/nq-provision --clear-wifi --clear-authorized-keys --clear-squeezelite --clear-rng-seed
```

If userspace does not start, use the Nexus Q manual fastboot procedure and boot
again with `fastboot boot`.
