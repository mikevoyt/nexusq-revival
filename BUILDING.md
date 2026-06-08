# Building

## Host Setup

Validated host:

- macOS
- Android platform-tools
- GNU make
- STM32CubeCLT ARM EABI toolchain
- Homebrew e2fsprogs
- Python 3

The default cross compiler path is:

```sh
/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/bin/arm-none-eabi-
```

Override it if needed:

```sh
export CROSS_COMPILE=/path/to/arm-none-eabi-
export HOST_ELF_H=/path/to/arm-none-eabi/include/elf.h
export MAKE=gmake
export MKE2FS=/opt/homebrew/opt/e2fsprogs/sbin/mke2fs
```

## Source Inputs

Place Linux 6.6.142 at:

```text
kernel/linux-6.6.142
```

The release build applies:

```text
patches/linux-6.6.142-nexusq-steelhead.patch
```

That patch adds the Steelhead TAS5713 ASoC machine driver and fixes the TI
composite clock divider rate callbacks needed by the audio clock tree.

The build script then copies:

```text
linux66/omap4-steelhead.dts
```

into the kernel tree before building.

## Build Command

```sh
tools/build_release_artifacts_local.sh
```

Outputs:

```text
artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img
artifacts/nexusq-debian-trixie-armhf-rootfs.ext4
artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img
```

The sparse image is the one intended for `fastboot flash userdata`.

## What The Build Does

1. Rebuilds a Debian 13 `trixie` armhf rootfs by resolving package metadata and
   extracting selected `.deb` archives.
2. Builds the Debian loader initramfs.
3. Builds Linux 6.6.142 with no SMP, USB ACM+ECM, TAS5713 audio, and modular
   Broadcom FullMAC Wi-Fi.
4. Builds only the `drivers/net/wireless/broadcom/brcm80211` module subtree.
5. Installs `brcmutil.ko`, `brcmfmac.ko`, and the Broadcom helper modules into
   the rootfs.
6. Creates raw ext4 and Android sparse `userdata` images.

## Firmware Policy

The public kernel image does not embed `.secrets/nexusq-firmware`.

The Debian rootfs includes Debian's `firmware-brcm80211` package for
`brcmfmac4330-sdio.bin`. Device calibration is prepared at first Wi-Fi startup:

- copy `/etc/wifi/bcmdhd.cal` from the stock Android `system` partition when
  `/dev/mmcblk0p11` is still intact;
- write it as
  `/lib/firmware/brcm/brcmfmac4330-sdio.google,steelhead.txt`;
- also write the generic `brcmfmac4330-sdio.txt` fallback.

If the stock system partition is missing, provide the NVRAM text file manually
inside the rootfs before starting Wi-Fi.

