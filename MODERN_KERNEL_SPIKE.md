# Nexus Q Linux 6.6 Viability Spike

## Goal

Boot a Linux 6.6 LTS kernel on Nexus Q / Steelhead using `fastboot boot`
only. The first success criterion is deliberately narrow:

- kernel starts on the OMAP4 SoC
- initramfs reaches a shell or emits useful logs
- device can return to fastboot without flashing

Full parity with the Android 3.0 vendor kernel is out of scope for the first
spike.

## Safety Rules

- Use `fastboot boot`, never `fastboot flash`, during the spike.
- Keep the known-good 3.0 rescue image available:
  `artifacts/nexusq-rescue-acm-ecm.img`
- If a test kernel hangs before userspace, recover by manually returning the
  unit to fastboot.

## Starting Point

- Device: Google Nexus Q / Steelhead
- Fastboot serial: `AW1S12250524`
- Bootloader: `steelheadB4H0J`
- Bootloader state: unlocked
- Known-good rescue kernel: Android OMAP Steelhead 3.0.8
- Known-good rescue image: `artifacts/nexusq-rescue-acm-ecm.img`
- Known-good rescue features:
  - ACM serial shell
  - ECM USB networking
  - TAS5713 and S/PDIF playback
  - `/bin/reboot-bootloader`
  - `/bin/nqstreamd`

## Target

- Kernel line: Linux 6.6 LTS
- Initial approach:
  - build ARM `multi_v7_defconfig`
  - add a minimal `omap4-steelhead.dts`
  - append the DTB to `zImage` for the legacy Android bootloader
  - reuse the existing rescue initramfs
  - pack with the existing legacy Android boot image header values

## Current Status

- Linux 6.6.142 boots on Steelhead with the no-SMP OMAP build.
- Recovery is workable during non-persistent testing: images use
  `nq.autoreboot=300 panic=30 oops=panic`, and a live serial shell can run
  `/bin/reboot-bootloader`.
- TAS5713 speaker playback works on 6.6 with the local
  `google,steelhead-tas5713` machine driver after matching the vendor 3.0 ABE
  DPLL reference parent on `sys_clkin_ck` for `google,steelhead`.
- The current validated audio/rootfs test artifact is:
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`.
- Wi-Fi has reached the first kernel milestone: MMC5/SDIO enumerates the
  BCM4330 path and creates `wlan0` in the 6.6 no-SMP image.
- SMP bring-up remains unresolved; keep `linux66/nexusq-linux66-nosmp.fragment`
  in the working image until the OMAP4 SMP failure is isolated.
- USB ACM serial is currently the reliable live shell. USB ECM has enumerated
  before, but macOS ECM exposure is inconsistent and should not be treated as
  the only recovery channel yet.

## Working 3.0 Boot Header Values

- `kernel_addr=0x80008000`
- `ramdisk_addr=0x81000000`
- `second_addr=0x80f00000`
- `tags_addr=0x80000100`
- `page_size=2048`

## Current Risks

- Early boot logging may be unavailable if USB gadget serial never appears.
- Steelhead has no modern upstream device tree in this workspace.
- The legacy board file is large and board-specific:
  `kernel/omap-steelhead/arch/arm/mach-omap2/board-steelhead.c`
- Modern kernel support will need a device-tree description for at least:
  - OMAP4 CPU/platform
  - TWL6030 PMIC/regulators
  - eMMC
  - USB gadget path
  - GPIO/pinctrl
  - BCM4330 SDIO Wi-Fi
- TAS5713/McBSP audio now has a local 6.6 implementation that enumerates,
  opens the PCM, and plays raw PCM/MP3 without the earlier flutter regression.

## Log

- Created spike log and confirmed device is currently visible in fastboot.
- Built `nexusq-linux66-build` Docker image from
  `docker/linux66-build.Dockerfile`.
- Downloaded and extracted Linux `6.6.142` into `kernel/linux-6.6.142`.
- Added a first-pass Steelhead device tree:
  `linux66/omap4-steelhead.dts`.
- Added `linux66/nexusq-linux66.fragment` for appended DTB, initramfs,
  MUSB gadget, configfs ACM/ECM, TWL6030 USB, OMAP HS MMC, and basic
  networking/storage support.
- Updated the rescue initramfs to configure a modern configfs USB gadget when
  the legacy Android gadget sysfs is not present.
- Rebuilt the known-good 3.0 rescue image after the initramfs change:
  `artifacts/nexusq-rescue-acm-ecm.img`.
- Built and packed the first Linux 6.6 Steelhead image:
  `artifacts/nexusq-linux66-steelhead.img`.
  - `zImage`: `11125248` bytes
  - appended `zImage+dtb`: `11214222` bytes
  - `omap4-steelhead.dtb`: `88974` bytes
  - Android boot image: `11986944` bytes
- Confirmed important 6.6 config values:
  - `CONFIG_ARM_APPENDED_DTB=y`
  - `CONFIG_ARM_ATAG_DTB_COMPAT=y`
  - `CONFIG_USB_MUSB_HDRC=y`
  - `CONFIG_USB_MUSB_GADGET=y`
  - `CONFIG_USB_MUSB_OMAP2PLUS=y`
  - `CONFIG_USB_CONFIGFS=y`
  - `CONFIG_USB_CONFIGFS_ACM=y`
  - `CONFIG_USB_CONFIGFS_ECM=y`
  - `CONFIG_TWL6030_USB=y`
  - `CONFIG_MMC_OMAP_HS=y`
  - `CONFIG_BRCMFMAC=m`
- Confirmed device is visible before first 6.6 boot test:
  `AW1S12250524 fastboot`.
- First Linux 6.6 boot test:
  - Command: `fastboot boot artifacts/nexusq-linux66-steelhead.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (11706 KB) OKAY`, `Booting OKAY`.
  - Waited about 60 seconds after handoff.
  - No `/dev/cu.usbmodem*` ACM serial device appeared.
  - `fastboot devices` produced no output after handoff.
  - `ifconfig -l` showed no new USB ECM/NCM network interface.
  - `system_profiler SPUSBDataType` showed only the host hubs; no Nexus,
    Google, Android, ACM, or ECM device was visible.
  - Interpretation: the 6.6 kernel either did not reach userspace, or it
    reached userspace but failed before binding a USB gadget. Without an
    external UART these two cases are indistinguishable from the host.
- Added a bootarg-gated userspace probe to `initramfs/init`:
  `nq.autoreboot=<seconds>`.
  - If userspace starts, the initramfs waits the requested delay and runs
    `/bin/reboot-bootloader`.
  - The normal rescue image is unaffected unless that bootarg is present.
- Docker Desktop started returning an API/server mismatch for all Docker
  commands after the first 6.6 build. Added `tools/build_initramfs_local.sh`
  as a rootless local fallback for generating the `newc` initramfs cpio.
  The local fallback skips archived device nodes because `/init` creates the
  needed nodes at boot.
- Rebuilt the initramfs locally:
  `artifacts/nexusq-initramfs.cpio.gz` (`769343` bytes).
- Repacked the known-good 3.0 rescue image with the new gated initramfs:
  `artifacts/nexusq-rescue-acm-ecm.img`.
- Packed a second 6.6 test image with the userspace auto-reboot probe:
  `artifacts/nexusq-linux66-steelhead-autoreboot.img`.
  - Cmdline includes `nq.autoreboot=20`.
  - Expected result if 6.6 reaches `/init`: device returns to fastboot after
    roughly 20 seconds, even if USB gadget setup fails.
  - Expected result if 6.6 hangs before `/init`: device remains unreachable
    until manually returned to fastboot.
- Second Linux 6.6 boot test, using the auto-reboot probe:
  - Command: `fastboot boot artifacts/nexusq-linux66-steelhead-autoreboot.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (11706 KB) OKAY`, `Booting OKAY`.
  - Polled for about 80 seconds.
  - Device did not return to fastboot after the `nq.autoreboot=20` deadline.
  - No ACM serial device or new network interface appeared.
  - Interpretation: 6.6 most likely did not reach `/init`.
- Found a concrete issue with the legacy boot header layout:
  - 6.6 decompressed `Image`: `28741152` bytes (`0x1b68e20`)
  - If decompressed at `0x80008000`, the image ends at `0x81b70e20`.
  - The old rescue header places the ramdisk at `0x81000000`.
  - That means the modern decompressed kernel overlaps and likely corrupts the
    ramdisk before userspace can start.
- Updated `tools/build_linux66_spike.sh` to accept `RAMDISK_ADDR`.
- Packed a high-ramdisk 6.6 probe image:
  `artifacts/nexusq-linux66-steelhead-autoreboot-rd830.img`.
  - Kernel address remains `0x80008000`.
  - Ramdisk address is moved to `0x83000000`.
  - Cmdline still includes `nq.autoreboot=20`.
  - Next expected test: boot this image from fastboot. If it returns to
    fastboot after about 20 seconds, the previous failure was the ramdisk
    overlap. If it remains unreachable, the next likely suspects are earlier
    kernel handoff/DTB/decompressor issues.
- Third Linux 6.6 boot test, using the high-ramdisk auto-reboot probe:
  - Command:
    `fastboot boot artifacts/nexusq-linux66-steelhead-autoreboot-rd830.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (11706 KB) OKAY`, `Booting OKAY`.
  - Polled for about 120 seconds.
  - No ACM serial device, new USB network interface, or fastboot return was
    observed.
  - Interpretation: moving the ramdisk out of the decompressed kernel range
    fixed a real boot-image-layout bug, but did not produce a host-visible
    userspace signal. It is still possible that 6.6 reached `/init` and the
    generic OMAP restart path ignored the `bootloader` reboot command, but the
    lack of ACM/ECM enumeration means this remains unproven.
- Replaced `tools/build_initramfs_local.sh` with a proper rootless `newc`
  generator:
  `tools/gen_init_cpio_newc.py`.
  - Preserves root ownership, file modes, symlinks, and char device nodes from
    `initramfs/initramfs.list`.
  - Verified the archive contains `/init`, `/bin/busybox`, and char devices
    `/dev/console`, `/dev/null`, `/dev/zero`, `/dev/tty`.
- Rebuilt initramfs with the new local generator:
  `artifacts/nexusq-initramfs.cpio.gz` (`769731` bytes).
- Repacked the 3.0 rescue image with the regenerated initramfs:
  `artifacts/nexusq-rescue-acm-ecm.img`.
- Packed another high-ramdisk 6.6 probe using the corrected `newc` archive:
  `artifacts/nexusq-linux66-steelhead-autoreboot-rd830-newc.img`.
- Investigated an OMAP-focused 6.6 build:
  - `omap2plus_defconfig` exists in Linux 6.6.
  - Docker Desktop is currently failing even for `docker version` with an API
    server error.
  - Local macOS `make` is GNU Make `3.81`; Linux 6.6 requires `>= 3.82`.
  - A local `omap2plus_defconfig` build probe failed at the make-version check
    before compiling anything.
- Fourth Linux 6.6 boot test, using the high-ramdisk probe with the corrected
  `newc` initramfs:
  - Command:
    `fastboot boot artifacts/nexusq-linux66-steelhead-autoreboot-rd830-newc.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (11706 KB) OKAY`, `Booting OKAY`.
  - Polled for about 120 seconds.
  - No ACM serial device, new USB network interface, or fastboot return was
    observed.
  - Interpretation: initramfs archive formatting and missing device nodes were
    not the primary blocker. Current evidence points to a pre-userspace failure
    in kernel handoff, decompressor, early DT boot, or an early platform init
    path. Next iteration should reduce variables with an `omap2plus_defconfig`
    kernel and keep the high ramdisk address.
- Built a narrower Linux 6.6 image from `omap2plus_defconfig` using the local
  macOS host plus the STM32 ARM cross toolchain:
  `tools/build_linux66_omap2plus_local.sh`.
  - Local host-tool fixes needed on macOS:
    - GNU Make 4.4.1 from `tools/host/bin/make`.
    - `tools/host/bin/sed` shim for Linux `merge_config.sh` GNU `sed -i`
      usage.
    - `tools/host/bin/cp` shim for Linux `merge_config.sh` GNU `cp -T`
      usage.
    - `tools/host/include/elf.h` symlinked to the STM32 toolchain's musl
      `elf.h` so Linux host tools can build on macOS.
    - Small local source compatibility patch in
      `kernel/linux-6.6.142/scripts/mod/file2alias.c` to avoid macOS
      `uuid_t` conflicting with Linux's host-tool `uuid_t`.
  - Avoided the host OpenSSL/libcrypto architecture mismatch by disabling
    cfg80211/Broadcom Wi-Fi for this boot-handoff image. Wi-Fi should be added
    back after the modern kernel visibly reaches userspace.
  - Forced the USB signal path built in:
    `CONFIG_USB_MUSB_OMAP2PLUS=y`, `CONFIG_OMAP_USB2=y`,
    `CONFIG_TWL6030_USB=y`, `CONFIG_USB_CONFIGFS_ACM=y`,
    `CONFIG_USB_CONFIGFS_ECM=y`.
  - Resolved config check:
    - `CONFIG_ARM_APPENDED_DTB=y`
    - `CONFIG_ARM_ATAG_DTB_COMPAT=y`
    - `CONFIG_USB_MUSB_HDRC=y`
    - `CONFIG_USB_MUSB_GADGET=y`
    - `CONFIG_USB_MUSB_OMAP2PLUS=y`
    - `CONFIG_OMAP_USB2=y`
    - `CONFIG_TWL6030_USB=y`
    - `CONFIG_USB_CONFIGFS=y`
    - `CONFIG_USB_CONFIGFS_ACM=y`
    - `CONFIG_USB_CONFIGFS_ECM=y`
    - `CONFIG_MMC_OMAP_HS=y`
    - `# CONFIG_CFG80211 is not set`
  - Produced:
    - `artifacts/linux66-omap2plus-steelhead-zImage-dtb` (`5471262` bytes)
    - `artifacts/nexusq-linux66-omap2plus-rd830-autoreboot.img`
      (`6244352` bytes)
  - Appended DTB sanity check:
    - zImage size: `5382288` bytes
    - appended DTB starts at offset `5382288`
    - DTB size: `88974` bytes
  - Boot image header sanity check:
    - kernel address: `0x80008000`
    - ramdisk address: `0x83000000`
    - tags address: `0x80000100`
    - page size: `2048`
    - cmdline:
      `console=ttyO2,115200n8 earlyprintk ignore_loglevel root=/dev/ram0 rdinit=/init init=/init nq.autoreboot=20`
- Fifth Linux 6.6 boot test, using the OMAP-focused image:
  - Command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-rd830-autoreboot.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (6098 KB) OKAY`, `Booting OKAY`.
  - Poll results:
    - `fastboot devices` still showed `AW1S12250524 fastboot` for the first
      two polls immediately after `Booting OKAY`.
    - Fastboot then disappeared, which indicates the bootloader did hand off.
    - Polled for 90 iterations at 2 seconds each, about 180 seconds total.
    - No ACM serial device appeared.
    - No new host network interface appeared.
    - The device did not return to fastboot after `nq.autoreboot=20`.
  - Interpretation:
    - This eliminated the `multi_v7_defconfig` breadth and the missing built-in
      TWL6030/OMAP USB PHY path as primary causes.
    - The result still does not prove whether the kernel reaches `/init`,
      because upstream 6.6 OMAP restart does not save the `bootloader`
      restart command for Steelhead's bootloader.
    - Next diagnostic should port the old Steelhead SAR reboot-command write
      into 6.6, then re-test. If the SAR-patched image returns to fastboot
      after the userspace autoreboot deadline, 6.6 is reaching `/init` and the
      remaining issue is USB gadget/userspace bring-up. If it stays silent,
      the failure is earlier than `/init` or the reboot path is not reached.
- Ported Steelhead reboot-to-bootloader SAR handling into local Linux 6.6:
  - Source patch:
    `kernel/linux-6.6.142/arch/arm/mach-omap2/omap4-restart.c`
  - The old Steelhead board code wrote a 32-byte string at
    `omap4_get_sar_ram_base() + 0xA0C`.
  - The local 6.6 patch only activates for
    `of_machine_is_compatible("google,steelhead")`.
  - Supported strings match the old board code:
    `normal`, `recovery`, `recovery:wipe_data`, `bootloader`.
  - Built diagnostic artifacts:
    - `artifacts/linux66-omap2plus-steelhead-sar-zImage-dtb` (`5470150`
      bytes)
    - `artifacts/nexusq-linux66-omap2plus-rd830-autoreboot-sar.img`
      (`6242304` bytes)
  - Next live test command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-rd830-autoreboot-sar.img`
  - Expected outcomes:
    - Fastboot returns after about 20 seconds: kernel reached `/init`; focus
      next on why ACM/ECM did not enumerate.
    - No fastboot/USB return: kernel likely stalls before `/init`, or panics
      before userspace can run the reboot helper.
- Sixth Linux 6.6 boot test, using the SAR-patched OMAP-focused image:
  - Command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-rd830-autoreboot-sar.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (6096 KB) OKAY`, `Booting OKAY`.
  - Poll results:
    - `fastboot devices` showed `AW1S12250524 fastboot` only on the first
      immediate poll after `Booting OKAY`.
    - Fastboot disappeared by the second poll, so the bootloader handed off.
    - Polled for 90 iterations at 2 seconds each, about 180 seconds total.
    - No ACM serial device appeared.
    - No new host network interface appeared.
    - The device did not return to fastboot after `nq.autoreboot=20`, even
      with the Steelhead SAR reboot-command write ported into 6.6.
  - Interpretation:
    - The SAR patch removed the ambiguity around generic OMAP restart not
      preserving the `bootloader` command.
    - Current evidence points to failure before `/init` runs, or a kernel
      panic/hang before the autoreboot helper can execute.
    - Next useful isolation image: disable SMP to remove OMAP4 secondary CPU
      startup, wakeupgen, and SAR low-power paths from the early boot surface.
- Built a no-SMP Linux 6.6 SAR diagnostic image:
  - Added `tools/build_linux66_omap2plus_local.sh` support for `FRAGMENTS` so
    diagnostic config fragments can be layered without replacing the base
    rescue fragment.
  - Added `linux66/nexusq-linux66-nosmp.fragment`:
    `# CONFIG_SMP is not set`.
  - Build command:
    `OUT=build/linux-6.6-omap2plus-steelhead-nosmp IMAGE=artifacts/nexusq-linux66-omap2plus-nosmp-rd830-autoreboot-sar.img ZIMAGE_DTB=artifacts/linux66-omap2plus-steelhead-nosmp-sar-zImage-dtb FRAGMENTS="linux66/nexusq-linux66.fragment linux66/nexusq-linux66-nosmp.fragment" tools/build_linux66_omap2plus_local.sh`
  - Resolved config check:
    - `# CONFIG_SMP is not set`
    - `CONFIG_USB_MUSB_OMAP2PLUS=y`
    - `CONFIG_OMAP_USB2=y`
    - `CONFIG_TWL6030_USB=y`
    - `CONFIG_USB_CONFIGFS_ACM=y`
    - `CONFIG_USB_CONFIGFS_ECM=y`
  - Produced:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-sar-zImage-dtb`
      (`5135670` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-rd830-autoreboot-sar.img`
      (`5908480` bytes)
  - Appended DTB sanity check:
    - zImage size: `5046696` bytes
    - appended DTB starts at offset `5046696`
    - DTB size: `88974` bytes
  - Next live test command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-rd830-autoreboot-sar.img`
  - Expected outcome:
    - If no-SMP returns to fastboot or enumerates USB, the previous blocker is
      likely in OMAP4 SMP/secondary CPU/wakeupgen bring-up.
    - If no-SMP stays silent, move earlier: boot wrapper/decompressor/DT
      handoff, memory map/reservations, or a missing early board dependency.
- Seventh Linux 6.6 boot test, using the no-SMP SAR diagnostic image:
  - Command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-rd830-autoreboot-sar.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (5770 KB) OKAY`, `Booting OKAY`.
  - Poll results:
    - Fastboot disappeared after handoff, confirming the bootloader launched
      the kernel.
    - A new host network interface, `en11`, appeared for several polls.
      This is strong evidence that Linux 6.6 reached `/init`, configfs USB
      gadget setup ran, and ECM enumerated on the host.
    - No ACM serial device appeared during this short autoreboot run.
    - After the `nq.autoreboot=20` userspace probe expired, `en11`
      disappeared and `fastboot devices` again reported
      `AW1S12250524 fastboot`.
  - Interpretation:
    - The no-SMP 6.6 kernel reaches userspace on Steelhead.
    - The Steelhead SAR reboot-command port works: userspace can command a
      reboot back to fastboot from Linux 6.6.
    - The prior silent SAR-patched SMP run likely fails before `/init`, so the
      current blocker is probably in OMAP4 SMP/secondary CPU/wakeupgen bringup
      or a related early SMP path.
    - The next practical image should keep the no-SMP kernel running instead
      of using `nq.autoreboot`, then inspect ECM networking and userspace
      services live.
- Eighth Linux 6.6 boot test, using a no-SMP stay-up image:
  - Built:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-stayup-sar-zImage-dtb`
      (`5135670` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-rd830-stayup-sar.img`
      (`5908480` bytes)
  - Command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-rd830-stayup-sar.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (5770 KB) OKAY`, `Booting OKAY`.
  - Poll results:
    - Fastboot disappeared after handoff.
    - Host network interface `en11` appeared and stayed present for repeated
      polls, confirming persistent USB ECM enumeration.
    - `ifconfig en11` on macOS showed an active interface with a link-local
      address assigned by macOS:
      `169.254.178.244/16`.
    - No ACM serial device appeared.
  - Limitation discovered:
    - The initramfs only assigned device-side IPv4 `172.16.42.2/24`.
    - The local Codex session could not run passwordless `sudo`, so it could
      not add host-side `172.16.42.1/24` to `en11`.
    - IPv6 link-local probing did not find the expected device address.
    - Because this stay-up image intentionally had no autoreboot timer and no
      reachable debug shell, the current boot cannot be commanded back to
      fastboot from the Mac without user intervention.
- Built a safer no-SMP link-local debug image for the next iteration:
  - Patched `initramfs/init` to add device-side
    `169.254.42.2/16` on `usb0:ll` after `usb0` comes up.
  - Patched `initramfs/init` to start a temporary USB-only BusyBox debug shell:
    `telnetd -l /bin/sh -p 2323`.
  - Rebuilt:
    - `artifacts/nexusq-initramfs.cpio`
    - `artifacts/nexusq-initramfs.cpio.gz`
  - Built:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-linklocal-sar-zImage-dtb`
      (`5135670` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-rd830-linklocal-autoreboot-sar.img`
      (`5908480` bytes)
  - Command line includes `nq.autoreboot=180`, so even if networking or the
    debug shell fails, this image should return to fastboot after about three
    minutes.
  - Next live test command after the device is manually returned to fastboot:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-rd830-linklocal-autoreboot-sar.img`
  - Expected validation steps:
    - Wait for `en11`.
    - Ping `169.254.42.2` from the Mac without adding a sudo-managed address.
    - Use `nc 169.254.42.2 2323` or a telnet client to run shell commands.
    - Confirm `/bin/reboot-bootloader` from the debug shell returns to
      fastboot, giving a self-service recovery path for subsequent iterations.
- Ninth Linux 6.6 boot test, using the no-SMP link-local debug image:
  - Command:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-rd830-linklocal-autoreboot-sar.img`
  - Fastboot accepted and launched the image:
    `Sending 'boot.img' (5770 KB) OKAY`, `Booting OKAY`.
  - Poll results:
    - Fastboot disappeared after handoff.
    - Host network interface `en11` appeared again.
    - macOS assigned host-side link-local IPv4 `169.254.11.154/16`.
    - Device-side `169.254.42.2` replied to ping with sub-millisecond latency.
  - Debug shell validation:
    - TCP port `2323` was open and answered BusyBox telnet negotiation.
    - A scripted telnet client reached a root shell and ran:
      - `uname -a`: `Linux (none) 6.6.142 ... armv7l GNU/Linux`
      - `id`: `uid=0 gid=0`
      - `cat /proc/cmdline`: confirmed the 6.6 rescue cmdline plus the
        bootloader-supplied Steelhead metadata.
      - `ifconfig usb0`: confirmed `172.16.42.2/24` and USB link-local IPv6.
      - `ps`: confirmed `/bin/nqstreamd -p 5555 -c 2 -d 0` and
        `telnetd -l /bin/sh -p 2323` were running.
    - TCP port `5555` accepted connections, confirming `nqstreamd` is
      listening under Linux 6.6.
  - Self-service fastboot validation:
    - From the USB debug shell, ran:
      `sync; /bin/reboot-bootloader`.
    - The telnet session disconnected during reboot.
    - `fastboot devices` immediately returned:
      `AW1S12250524 fastboot`.
  - Conclusion:
    - When Linux 6.6 reaches userspace on the no-SMP path, the Mac can now
      command the Nexus Q back into fastboot without physical intervention.
    - This does not help images that hang before USB/userspace comes up; those
      still need the `nq.autoreboot` safety timer, a kernel-level watchdog, or
      manual recovery.
- Tenth Linux 6.6 safety hardening attempt:
  - Added cancelable userspace autoreboot helpers to `initramfs/init` and the
    initramfs file list:
    - `/bin/nq-autoreboot-cancel`
    - `/bin/nq-autoreboot-status`
    - `/bin/nq-reboot-fastboot`
    - `/bin/nq-watchdog-status`
  - Changed the local Steelhead 6.6 restart hook so generic restarts default
    to SAR reason `bootloader`; explicit `normal`, `recovery`,
    `recovery:wipe_data`, and `bootloader` remain supported.
  - Added `linux66/nexusq-linux66-devsafe.fragment` with built-in watchdog and
    panic-on-oops settings:
    - `CONFIG_WATCHDOG_CORE=y`
    - `CONFIG_WATCHDOG_NOWAYOUT=y`
    - `CONFIG_OMAP_WATCHDOG=y`
    - `CONFIG_SOFT_WATCHDOG=y`
    - `CONFIG_PANIC_ON_OOPS=y`
    - `CONFIG_PANIC_TIMEOUT=30`
  - Built dev-safety artifacts:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-devsafe-zImage-dtb`
      (`5140902` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-devsafe.img`
      (`5916672` bytes)
  - Boot result:
    - Fastboot handoff succeeded.
    - No USB ECM interface appeared.
    - No ACM serial appeared.
    - The userspace `nq.autoreboot=300` path eventually returned the device to
      fastboot, so the image reached enough userspace to run the timer but did
      not expose USB.
  - Interpretation:
    - The built-in watchdog dev-safety image is not suitable as the working
      rescue image yet.
    - It is not a brick risk when booted non-persistently with
      `nq.autoreboot=300`, but it blocks the USB shell workflow.
- Eleventh Linux 6.6 safety isolation attempt:
  - Rebuilt a no-watchdog USB-safe image using the known no-SMP config plus the
    updated initramfs helpers and `nq.autoreboot=300 panic=30 oops=panic`:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-usbsafe-zImage-dtb`
      (`5136110` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-usbsafe.img`
      (`5910528` bytes)
  - Boot result:
    - Fastboot handoff succeeded.
    - No USB ECM interface appeared.
    - The userspace autoreboot timer returned the device to fastboot.
  - Retested the previously validated image:
    `artifacts/nexusq-linux66-omap2plus-nosmp-rd830-linklocal-autoreboot-sar.img`
  - Retest result:
    - Fastboot handoff succeeded.
    - No USB ECM interface appeared on this later run.
    - The old image's `nq.autoreboot=180` path returned the device to fastboot.
  - Interpretation:
    - The recovery timer is reliable enough for unattended non-persistent
      tests that reach userspace.
    - USB ECM enumeration became inconsistent after the safety experiments.
      This may be a board/USB-controller state issue across warm reboots, a
      host-side macOS USB networking state issue, or an initramfs/kernel delta
      that needs smaller live bisection.
    - Do not boot no-timer images while unattended. Leave the device in
      fastboot after failed USB enumeration and continue offline work until a
      manual power-cycle or a smaller recovery-tested image is available.
- Debian armhf rootfs staging:
  - Confirmed Debian 13 `trixie` is the current stable Debian target and armhf
    is an officially supported architecture.
  - Docker Desktop remained unavailable and Homebrew did not provide
    debootstrap/mmdebstrap, so added a local direct-extraction rootfs builder:
    `tools/build_debian_rootfs.py`.
  - Installed host-side tooling with Homebrew:
    - `qemu`
    - `fakeroot`
    - `e2fsprogs`
  - Built a Debian `trixie` armhf rootfs from Debian package metadata:
    - package cache: `downloads/debian-trixie-armhf`
    - staging tree: `build/debian-trixie-armhf/rootfs`
    - package manifest: `build/debian-trixie-armhf/packages.txt`
    - ext4 image: `artifacts/debian-trixie-armhf-rootfs.ext4`
  - Verification:
    - 159 packages in generated `/var/lib/dpkg/status`.
    - image label: `nq-debian`
    - `/sbin/nq-init` is present, root-owned, and executable.
    - USB defaults are staged for `169.254.42.2/16` and `172.16.42.2/24`.
    - Included packages include `alsa-utils`, `alsa-ucm-conf`,
      `firmware-brcm80211`, `wpasupplicant`, `dropbear-bin`,
      `busybox-static`, `systemd`, `udev`, and `apt`.
  - Fastboot partition facts from `fastboot getvar all`:
    - `boot`: 8 MiB
    - `recovery`: 8 MiB
    - `system`: 1 GiB
    - `cache`: 512 MiB
    - `userdata`: about 13.2 GiB
  - No partition was flashed.
  - Detailed rootfs notes: `DEBIAN_ROOTFS.md`.
- Linux 6.6 TAS5713/McBSP audio bring-up:
  - Added `linux66/nexusq-linux66-audio.fragment` with the built-in ALSA,
    OMAP McBSP, TAS571x, and Steelhead machine-driver config needed for the
    rescue image.
  - Added `sound/soc/ti/steelhead-tas5713.c`, a local ASoC machine driver for
    the Steelhead TAS5713 path.
  - Updated `linux66/omap4-steelhead.dts` with TAS5713 I2C4, GPIO, pinmux,
    McBSP2, and audio clock wiring.
  - Patched `drivers/clk/ti/composite.c` so TI composite divider
    `round_rate` and `set_rate` delegate to the divider ops. This lets the
    DPLL-derived audio clock path accept the old board rate plan.
  - Booted:
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-machine-mclkfix2.img`
  - Live dmesg reported the intended Steelhead audio clocks:
    `codec-mclk=12288000 codec-src=61440000 mcbsp=24576000`.
  - `/proc/asound/cards` reported:
    `0 [TAS5713]: Steelhead_TAS57 - Steelhead TAS5713`.
  - Debian `aplay` over the serial-transferred test bundle verified the PCM
    path:
    - `aplay -l` listed card 0, device 0:
      `Steelhead TAS5713`.
    - `aplay -D hw:0,0 --dump-hw-params /tmp/test.wav` returned 0 and showed
      stereo `S16_LE`/`S32_LE`, rates `[8000 48000]`.
    - `aplay -D hw:0,0 -q /tmp/test.wav` returned `play_ret:0`.
  - The initramfs copy of `tinyplay` still fails with `Error playing sample`.
    Treat that as an old userspace/tinyalsa issue, not a current kernel PCM
    blocker; Debian `aplay` is the better validation tool.
- Current audio conclusion:
  - 6.6 no-SMP boot, TAS5713 card registration, original-style MCLK rates, and
    PCM open/playback are viable.
  - Subjective speaker quality was later found to need more work; a sine tone
    could sound harsh or square-like even when ALSA returned success.
  - Next kernel work should keep tightening the TAS5713 codec/McBSP bring-up
    before treating the onboard amplifier as audio-quality validated.
- Linux 6.6 Wi-Fi discovery:
  - Extracted the original Android `/system` Wi-Fi board files from eMMC
    partition `mmcblk0p11` into ignored local storage:
    `.secrets/nexusq-firmware/`.
  - Files found on-device:
    - `/etc/wifi/bcmdhd.cal`
    - `/vendor/firmware/fw_bcmdhd.bin`
    - `/vendor/firmware/fw_bcmdhd_apsta.bin`
    - `/vendor/firmware/fw_bcmdhd_p2p.bin`
    - `/vendor/firmware/bcm4330.hcd`
  - Added `linux66/nexusq-linux66-wifi.fragment` with built-in `CFG80211`,
    `RFKILL`, `BRCMFMAC`, `BRCMFMAC_SDIO`, and local built-in firmware paths.
    The fragment references `.secrets/nexusq-firmware`; do not commit that
    directory or distribute images that embed private/proprietary firmware.
  - Updated `linux66/omap4-steelhead.dts` for:
    - WLAN enable GPIO 43 as a fixed active-high regulator.
    - WLAN IRQ GPIO 53 as the BCM4330 host-wake interrupt.
    - MMC5 SDIO pinmux.
    - `&mmc5` as a 4-bit non-removable SDIO bus with a
      `brcm,bcm4330-fmac` child.
  - Built:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-zImage-dtb`
      (`5655388` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi.img`
      (`6430720` bytes)
  - Boot result:
    - Fastboot accepted and launched the image.
    - ACM serial shell appeared and the userspace timer was cancelled.
    - `/sys/class/net` contained `wlan0`.
    - `ifconfig -a` showed `wlan0` with no carrier yet.
    - `/sys/bus/sdio/devices` contained `mmc4:0001:1` and `mmc4:0001:2`,
      confirming the OMAP alias for MMC5 discovered the SDIO function.
    - USB `usb0` was configured on-device, but macOS did not expose a host
      ECM interface for this boot.
  - Limitation:
    - A too-long serial diagnostic command was mangled and left the initramfs
      shell at an `ash` continuation prompt. Because USB ECM was not reachable
      from macOS, the boot could not be commanded back to fastboot remotely.
      The next live iteration may need manual fastboot recovery.
  - Current Wi-Fi conclusion:
    - Kernel-side SDIO and Broadcom FullMAC bring-up is feasible on 6.6:
      `wlan0` exists.
    - Next work should use shorter serial commands, verify `brcmfmac` dmesg,
      set the MAC from `androidboot.wifi_macaddr`, and bring in a small
      `iw`/`wpa_supplicant` userspace path for association testing.
- Wi-Fi association test preparation:
  - Removed the missing `artifacts/bin/tinymix` dependency from the base
    initramfs manifest. The current macOS host cannot execute the old Linux
    musl cross-compiler in `build/toolchains`, and Docker Desktop remains
    unavailable, so rebuilding `tinymix` locally is not currently practical.
    `tinyplay`, `nqstreamd`, and `reboot-bootloader` remain present.
  - Added `/bin/test-wifi` to the initramfs. It performs short diagnostics,
    brings up `wlan0`, and, if a runtime-only
    `/tmp/wpa_supplicant.conf` exists, runs `wpa_supplicant` and polls
    association status without printing the config.
  - Hardened `/bin/nq-reboot-fastboot` and the `nq.autoreboot` path:
    bootloader reboot now schedules a delayed hard-reboot fallback before
    invoking the reboot syscall. This is meant to avoid losing the serial shell
    forever if the bootloader reboot syscall wedges.
  - Added `/bin/seed-rng`, a tiny static ARM helper built from
    `initramfs/seed-rng.c`. The host runner uploads a fresh random hex seed to
    the device's RAM filesystem and `seed-rng` credits it with
    `RNDADDENTROPY`. This unblocks `wpa_supplicant`'s blocking `getrandom()`
    call in the tiny initramfs environment. OMAP HWRNG was also made built-in,
    but the live test still needed the explicit seed path.
  - Added `tools/build_wifi_initramfs_local.sh`, which builds a larger
    Wi-Fi-test initramfs containing Debian `wpa_supplicant`, `wpa_cli`, the
    entropy helper, and only the required runtime libraries. No Wi-Fi
    credentials are embedded.
  - Added `tools/run_wifi_serial_test.py`, a host-side runner that:
    - boots the Wi-Fi test image from fastboot;
    - uploads a fresh temporary RNG seed with TTY echo disabled;
    - reads the Wi-Fi password from macOS Keychain at runtime;
    - sends a temporary `/tmp/wpa_supplicant.conf` over the serial shell with
      TTY echo disabled;
    - captures `/run/wifi-test.log`; and
    - asks the device to return to fastboot.
  - Rebuilt the initramfs artifacts:
    - `artifacts/nexusq-initramfs.cpio.gz` (`771809` bytes)
    - `artifacts/nexusq-initramfs-wifi.cpio.gz` (`6356028` bytes)
    - `build/seed-rng-arm` (`67620` bytes)
  - Built the Wi-Fi association test image:
    - `artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-test-zImage-dtb`
      (`5657340` bytes)
    - `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-test.img`
      (`12017664` bytes)
  - Live test on June 7, 2026:
    - Command: `tools/run_wifi_serial_test.py`
    - The image booted from RAM with `fastboot boot`; no partition was flashed.
    - `wlan0` appeared via `brcmfmac` on SDIO `mmc4:0001`.
    - `wpa_supplicant` reached its control interface after the RNG seed helper
      ran.
    - `wpa_cli status` reached `wpa_state=COMPLETED` on the configured network.
    - `udhcpc` obtained `192.168.86.46`.
    - The test then returned the unit to fastboot:
      `AW1S12250524 fastboot usb:17891328X`.
  - Current Wi-Fi conclusion:
    - Linux 6.6 no-SMP Steelhead can bring up BCM4330 Wi-Fi, associate with
      WPA2-PSK, obtain DHCP from the rescue initramfs, and accept root SSH
      through Dropbear over Wi-Fi.
    - Remaining cleanup: set the `wlan0` MAC from
      `androidboot.wifi_macaddr`, understand why built-in OMAP HWRNG is not
      enough by itself, include regulatory data if needed, and finish moving
      the proven flow into the Debian rootfs.
- Debian rootfs/storage spike:
  - Added `tools/img2simg.py`, a small Android sparse image writer. The raw
    768 MiB ext4 rootfs was rejected by fastboot as too large, but the 196 MiB
    sparse image flashed to `userdata` successfully.
  - Added a Debian loader initramfs and boot image:
    - `initramfs/debian-loader-init`
    - `initramfs/debian-loader.list`
    - `tools/build_debian_loader_initramfs_local.sh`
    - `tools/build_debian_boot_image_local.sh`
    - `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-debian.img`
  - Added `tools/run_debian_serial_test.py`, which flashes the sparse Debian
    rootfs, RAM-boots the loader image, injects runtime-only Wi-Fi/SSH files,
    starts `/sbin/nq-start-network`, verifies SSH, and returns to fastboot.
  - First live Debian attempt on June 7, 2026:
    - Sparse `userdata` flash succeeded.
    - The loader image booted from RAM.
    - The host never saw a USB ACM serial shell, so the runner could not inject
      runtime Wi-Fi/SSH files.
    - The device did not return as fastboot or ACM within the host wait window.
  - Correction prepared after that attempt:
    - Debian `/sbin/nq-init` now configures USB configfs ACM+ECM and starts a
      shell on `/dev/ttyGS0`.
    - The loader initramfs configures the same USB gadget before switch-root.
    - The Debian live-test boot image uses `nq.autoreboot=180`.
  - Final Debian live validation on June 8, 2026:
    - `tools/run_debian_serial_test.py --flash-userdata --rootfs artifacts/debian-trixie-armhf-rootfs.sparse.img`
      succeeded.
    - Debian 13.5 booted from `userdata` with Linux 6.6.142.
    - `/run` is tmpfs, avoiding stale injected Wi-Fi/SSH runtime files.
    - Wi-Fi DHCP configured `wlan0` as `192.168.86.42/24`.
    - Dropbear accepted root SSH public-key auth.
    - ALSA in the Debian rootfs reports
      `card 0: TAS5713 [Steelhead TAS5713]`.
    - `speaker-test` opened `hw:0,0` at 48 kHz stereo.
    - The runner returned the unit to fastboot.
- Public release cleanup and validation:
  - Added `linux66/nexusq-linux66-wifi-public.fragment`, which builds
    `brcmfmac` and `brcmutil` as modules and clears `CONFIG_EXTRA_FIRMWARE`.
    This avoids embedding private firmware/NVRAM in the public boot image.
  - Added `/sbin/nq-prepare-wifi-firmware` and `/sbin/nq-load-wifi` to the
    Debian rootfs. On first Wi-Fi startup, Debian mounts the stock Android
    `system` partition read-only from `/dev/mmcblk0p11`, copies
    `/etc/wifi/bcmdhd.cal` into the Broadcom firmware directory, runs
    `depmod`, and loads `brcmfmac`.
  - Added `tools/install_linux66_modules.py` and
    `tools/build_release_artifacts_local.sh`. The release build compiles only
    the Broadcom module subtree after the built-in kernel image, installs five
    Wi-Fi modules into the Debian rootfs, and emits both raw and sparse
    `userdata` images.
  - Added `patches/linux-6.6.142-nexusq-steelhead.patch` and updated
    `tools/build_linux66_omap2plus_local.sh` to apply it automatically to a
    clean Linux 6.6.142 source tree. The patch carries the Steelhead TAS5713
    ASoC machine driver, the TI composite clock divider fix, and the
    Steelhead-specific TAS5713 codec init profile.
  - Public artifacts built:
    - `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img`
    - `artifacts/nexusq-debian-trixie-armhf-rootfs.ext4`
    - `artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img`
  - Public live validation on June 8, 2026:
    - Sparse `userdata` flash succeeded.
    - Debian reported `13.5`; kernel reported `6.6.142`.
    - NVRAM calibration was copied from stock `/system`.
    - `lsmod` showed `brcmfmac_wcc`, `brcmfmac`, and `brcmutil`.
    - DHCP configured `wlan0` as `192.168.86.42/24`.
    - Dropbear accepted root SSH public-key auth.
    - `aplay -l` listed `Steelhead TAS5713`.
    - `speaker-test -D hw:0,0 -c 2 -r 48000 -t sine -f 1000 -l 1` opened
      the speaker PCM path.
    - The runner returned the unit to fastboot.
- TAS5713 speaker-quality follow-up on June 10, 2026:
  - User listening reported the generated tones sounded harsh/square-like, so
    the audio result is no longer considered quality-validated solely because
    `speaker-test` opens the PCM.
  - Compared the modern upstream `tas571x` codec path with Google's old
    `tas5713_reg_init.h` table.
  - Added a Steelhead codec compatible,
    `google,steelhead-tas5713-codec`, and ported Google's TAS5713 init table:
    serial interface, PWM mux, input mux, channel mixes, output pre/post scale,
    high-pass biquads, DRC coefficients, volume config, interchannel delays,
    and backend-error behavior.
  - Matched the old power-up sequence more closely by enabling TAS5713 MCLK
    while applying oscillator trim and the raw init table.
  - Built and RAM-booted:
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-tasinit-mclk.img`.
  - Live register checks confirmed key TAS5713 values:
    `0x03=0x80`, `0x04=0x03`, `0x0e=0x91`, `0x10=0x02`,
    `0x1a=0x0f`, `0x1c=0x07`; multi-byte reads confirmed the PWM mux,
    input mux, high-pass biquads, output scaling, and channel mixer values.
  - During active 48 kHz/S16 playback, TAS5713 error status stayed clear
    (`0x02=0x00`) and shutdown was deasserted (`0x05=0x00`).
  - Low-gain test command:
    `speaker-test -D hw:0,0 -c 2 -r 48000 -F S16_LE -t sine -f 440 -l 1`.
  - Current status: kernel/codec state now matches the legacy profile much
    more closely, but subjective tone quality still needs listener
    confirmation.
- TAS5713 speaker-quality follow-up, later on June 10, 2026:
  - User listening still reported `./play-test-tone` sounded like a fluttery
    square wave after the init-table/MCLK image.
  - Ported more of Google's old TAS5713 power sequencing into the Steelhead
    codec path: assert `PDN` and `RESET`, wait 2 ms, enable MCLK, deassert
    `PDN`, wait 100 us, deassert `RESET`, wait 13.5 ms, trim the oscillator,
    wait 50 ms, apply the raw init table, explicitly exit shutdown, and use
    the legacy TAS5713 shutdown-transition delay.
  - Built and RAM-booted:
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-taspwr.img`.
  - Live boot checks showed `0x02=0x00`, `0x05=0x00`, `0x03=0x80`,
    `0x04=0x03`, `0x0e=0x91`, `0x10=0x02`, `0x1a=0x0f`, and `0x1c=0x07`.
  - Added a diagnostic command-line override,
    `nq.audio_inversion=nb-nf|nb-if|ib-nf|ib-if`, to sweep McBSP/TAS5713
    DAI inversion without rebuilding the kernel for each mode.
  - Built diagnostic boot images:
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-taspwr-inv-nb-nf.img`,
    `...-nb-if.img`, `...-ib-nf.img`, and `...-ib-if.img`.
  - Booted all four modes and played `/root/nq-tone-normal.wav` for listener
    comparison. Kernel-visible playback stayed healthy; subjective winner is
    still pending listener feedback.
- TAS5713 speaker-quality follow-up on June 13, 2026:
  - User listening and a MacBook microphone capture confirmed that the remaining
    failure is audio quality, not basic ALSA availability. Audible modes sound
    distorted/fluttery; some inverted-bit-clock modes were silent.
  - Best audible modes during the format/inversion sweep were the normal
    bit-clock cases, especially `nq.audio_format=i2s nq.audio_inversion=nb-nf`
    and `left_j nb-nf`. Inverted bit-clock modes either produced no sound or
    codec errors.
  - TAS5713 live registers stayed healthy during distorted playback:
    error status clear, shutdown deasserted, mute clear, and expected volume
    registers. Codec-side sweeps of backend-error handling, system control,
    output scaling, DRC-related registers, volume slew, and modulation limits
    did not fix the distortion.
  - McBSP live logging showed the expected 48 kHz stereo register shape, but
    playback start also logged RX-side underflow/noise on a playback-only path.
  - Working hypothesis at this point: Linux 6.6's OMAP SDMA cyclic playback
    path might be using source-trigger synchronization for MEM_TO_DEV playback
    where the old Steelhead path used destination synchronization. Later source
    comparison proved this specific assumption was wrong: mainline cyclic DMA
    already uses destination sync for MEM_TO_DEV playback and source sync for
    DEV_TO_MEM capture, matching the old `omap-pcm.c` direction choice.
  - Added diagnostic boot params:
    - `nq.omap_dma_legacy_cyclic_sync=1` to test cyclic DMA trigger-source
      behavior. This flag was later corrected because the first implementation
      inverted playback away from the legacy path.
    - `nq.mcbsp_no_rx_err_irq=1` to keep RX-side McBSP error IRQs out of a
      playback-only test.
  - Built:
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-dmasync.img`
    with command line:
    `nq.audio_format=i2s nq.audio_inversion=nb-nf nq.mcbsp_legacy_element=1 nq.omap_dma_legacy_cyclic_sync=1 nq.mcbsp_no_rx_err_irq=1`.
  - Smoke boot passed without playback: Linux 6.6.142 booted, SSH was reachable,
    and `/proc/asound/cards` listed `Steelhead TAS5713`.
  - Playback was intentionally paused because the speaker was unplugged. Next
    physical test after reconnecting the speaker: play the 440 Hz
    probe on the dmasync image, record with the MacBook microphone, and compare
    the envelope/carrier against the previous distorted capture.
  - Added `tools/build_audio_dmasync_image_local.sh` so the exact dmasync
    diagnostic command line can be rebuilt without copying a long environment
    block from the log.
  - Updated `tools/build_linux66_omap2plus_local.sh` to accept `SRC=...`,
    allowing clean-source reproducibility checks without modifying the working
    kernel tree.
  - Clean-source reproducibility check passed from a temporary copy of
    `build/patch-pristine/linux-6.6.142`. The tracked patch applied cleanly,
    the patched `tas571x`, `omap-mcbsp`, `steelhead-tas5713`, and `omap-dma`
    sources compiled, and the repro boot image had the same Android boot
    addresses, ramdisk size, and dmasync command line as the image currently
    running on the device. Byte-for-byte hashes differ because the kernel embeds
    build timestamps.
  - Follow-up source comparison against the legacy OMAP PCM/DMA stack found one
    more mismatch in the cyclic DMA descriptor: the old playback path programmed
    only the memory-side burst bits, while Linux 6.6's cyclic DMA path
    programmed both source and destination burst bits. Added
    `nq.omap_dma_legacy_cyclic_burst=1` to make cyclic DMA use
    memory-side-only burst bits for a reversible test.
  - A second pass found another CSDP difference: the old PCM path did not enable
    DMA packed mode for the McBSP playback channel, while the Linux 6.6 cyclic
    path enabled the memory-side packed bit. Added
    `nq.omap_dma_legacy_cyclic_pack=1` to leave cyclic packed mode disabled
    for this reversible test, and `nq.omap_dma_dump_cyclic=1` to log the final
    cyclic descriptor fields during the next playback attempt.
  - Added `tools/build_audio_legacydma_image_local.sh`, which combines
    `nq.audio_format=i2s`, `nq.audio_inversion=nb-nf`,
    `nq.mcbsp_legacy_element=1`, `nq.mcbsp_legacy_tx_irq=1`,
    `nq.omap_dma_legacy_cyclic_sync=1`, `nq.omap_dma_legacy_cyclic_burst=1`,
    `nq.omap_dma_legacy_cyclic_pack=1`, `nq.omap_dma_dump_cyclic=1`, and
    `nq.mcbsp_no_rx_err_irq=1`.
  - Next physical test after reconnecting the speaker: boot
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img`,
    play the 440 Hz probe, record with the MacBook microphone, and
    compare the envelope/carrier against the previous distorted capture.
  - Built `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img`
    from the working source tree and reproduced it from a clean temporary
    Linux 6.6.142 tree plus the tracked patch as
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma-repro.img`.
    Both builds succeeded; their hashes differ because the kernel embeds build
    timestamps. The clean build emitted the known macOS host-tool warning
    `find: -printf: unknown primary or operator` while generating initramfs
    metadata, but continued and produced a complete boot image.
  - Added `tools/run_audio_legacydma_probe_local.sh`, a guarded host-side
    playback probe. It refuses to play audio unless `NQ_SPEAKER_CONNECTED=1`
    is set, then generates a 440 Hz WAV, copies it to the Nexus Q,
    plays it once with `aplay`, and saves preflight, active-playback ALSA
    status, dmesg, optional microphone capture, and filtered `nq cyclic`/McBSP/
    TAS5713 kernel events under `artifacts/audio-probe-*`. It also has
    `LIST_AUDIO_INPUTS=1` to list Mac ffmpeg/avfoundation capture devices
    without playing audio.
  - Added `tools/analyze_audio_probe_capture.py` and wired it into the guarded
    probe. It computes basic capture metrics, including zero-cross frequency,
    harmonic power ratios, clipping percentage, crest factor, and 25 ms envelope
    variation, so the next microphone capture can quantify distortion/flutter
    across kernel images.
  - Baseline analysis of the user-recorded distorted capture
    `/Users/mikevoyt/Downloads/Jun 12 at 8-01 PM.m4a` was saved under
    `artifacts/audio-baselines/` for local comparison. Interpreting the capture
    as the 440 Hz probe gives:
    - zero-cross carrier estimate: `457.208 Hz` (`+3.9109%` from 440 Hz)
    - `clipped_pct: 0`
    - `harmonic_power_ratio_2_8: 1.09668e-05`
    - `odd_harmonic_power_ratio_3_5_7: 5.22388e-06`
    - `envelope_cv_25ms: 0.632408`
    - `envelope_low_pct_25ms: 28.5714`
    - `envelope_peak_to_trough_db_25ms: 23.3157`
    This supports the current "flutter/envelope instability" diagnosis more
    than hard clipping or TAS5713 register-level fault. Interpreting the same
    capture as 1 kHz gives a carrier estimate of only `457.208 Hz` and very
    high harmonic ratios, so the capture is most consistent with the 440 Hz
    test, not the earlier 1 kHz `speaker-test`.
  - While the speaker is unplugged, do not run playback commands. The next live
    iteration should run the guarded probe after reconnecting the speaker and
    compare `mic-capture-analysis.json` against the baseline above. A promising
    result should keep clipping near zero, keep the carrier close to 440 Hz, and
    substantially reduce `envelope_cv_25ms` from `0.632408`.
  - Offline static comparison against the legacy 3.0 Steelhead audio path:
    - The old Steelhead machine driver configured McBSP2 as I2S, normal
      bit/frame polarity, codec bit/frame consumer, and derived bit clock as
      `sample_rate * 32`. The current 6.6 machine driver derives bit clock
      from `physical_width * channels`, which matches the old `32fs` path for
      S16 stereo but can intentionally differ for S32 stereo. The guarded probe
      generates S16 stereo WAV, so it exercises the old-width path.
    - Old McBSP2 DMA requests were `16 + OMAP44XX_DMA_REQ_START` for TX and
      `17 + OMAP44XX_DMA_REQ_START` for RX, with `OMAP44XX_DMA_REQ_START = 1`;
      the modern inherited `omap4-l4-abe.dtsi` McBSP2 node uses the same SDMA
      signals: `<&sdma 17>` for TX and `<&sdma 18>` for RX.
    - With `nq.mcbsp_legacy_element=1` plus the legacy cyclic burst and pack
      toggles, the current `legacydma` image is the closest available
      reversible match to the old S16 playback DMA setup. If it still flutters,
      the next likely suspects are DMAengine cyclic scheduling/residue behavior
      or McBSP startup FIFO timing, not TAS5713 init data or McBSP2 DMA signal
      numbering.
  - Extended `tools/run_audio_legacydma_probe_local.sh` so the next guarded
    live test also records McBSP sysfs state before/during playback, extracts
    McBSP register and `nq cyclic` descriptor log lines into a compact
    `audio-register-events.txt`, and writes an `audio-summary.txt` that combines
    source WAV metrics, optional mic metrics, sysfs state, and kernel events.
    This should make the next run usable even if the subjective listening note
    is brief.
  - Added host-side McBSP sysfs controls to the guarded probe. The probe can now
    set `NQ_MCBSP_DMA_OP_MODE`, `NQ_MCBSP_MAX_TX_THRES`, and
    `NQ_MCBSP_MAX_RX_THRES` before opening the PCM. Added
    `tools/run_audio_threshold_probe_local.sh` as the next A/B test wrapper; it
    keeps the same legacy-DMA boot image but switches McBSP to threshold mode
    with a 32-word TX threshold. This targets the upstream McBSP warning that
    unsafe FIFO usage can cause runtime channel shifts, which fits the observed
    flutter better than clipping.
  - Added `tools/run_audio_probe_sweep_local.sh` to automate the next
    speaker-connected iteration. It runs the element-mode baseline and then
    threshold-mode probes for configurable `THRESHOLDS` values, with the same
    speaker guard and optional MacBook microphone capture. Added
    `tools/summarize_audio_probe_runs.py` to rank completed probe directories by
    microphone metrics, prioritizing lower `envelope_cv_25ms`, then lower
    carrier frequency error and harmonic ratio. This should make the next live
    session a data-driven FIFO/DMA threshold search instead of a one-off
    listening test.
  - Tightened the probe's McBSP sysfs configuration path so requested
    `dma_op_mode`, `max_tx_thres`, or `max_rx_thres` writes are required. If a
    requested control is missing or rejects the value, the run now fails before
    playback; the sweep harness creates the run directory up front and records
    the exit status in `sweep-status.txt`. This prevents a future threshold
    sweep from silently replaying element mode.
  - Extended `tools/summarize_audio_probe_runs.py` with baseline comparison and
    verdicts. The sweep passes the local June 12 bad-output JSON when present,
    so `env_x` reports how many times lower the run's 25 ms envelope variation
    is than the known-bad flutter capture. A `candidate` verdict currently means
    a successful mic-captured run with microphone RMS at or above `0.003`,
    `envelope_cv_25ms <= 0.20`, carrier error within `1%`, harmonic ratio at
    or below `0.05`, clipping at or below `1%`,
    `envelope_low_pct_25ms <= 10%`, and
    `envelope_peak_to_trough_db_25ms <= 6 dB`. This is an objective shortlist
    for listening, not final proof that speaker audio is fixed.
  - Refreshed the local June 12 baseline files with the expanded analyzer
    metrics. The known-bad capture now has `envelope_low_pct_25ms: 28.5714` and
    `envelope_peak_to_trough_db_25ms: 23.3157`, so the next live sweep can flag
    dropout/pumping separately from generic envelope CV.
  - Extended `tools/summarize_audio_probe_runs.py` to parse
    `audio-kernel-events.txt`, `audio-register-events.txt`, and `aplay.log` for
    runtime issues. The summary now exposes a `kernel` column and prevents a
    `candidate` verdict when ALSA/McBSP/DMA/TAS5713 logs contain `xrun`, `sync`,
    `alsa-error`, `codec-error`, or `dma-error` flags. This keeps a run with
    clean-looking microphone metrics but kernel-visible audio faults off the
    shortlist.
  - Added `tools/test_audio_analysis.py`, an offline regression test for the
    diagnostic layer. It verifies synthetic sine/square/flutter metric behavior,
    threshold-run parsing and ranking, low-level/quiet verdict handling,
    kernel-event verdict flags, and failed run handling without requiring the
    Nexus Q, speaker, SSH, or microphone.
  - Added `tools/check_audio_probe_prereqs_local.sh`, a no-playback host
    preflight for the next live sweep. It checks required local commands,
    diagnostic artifacts, executable probe tools, and the offline analyzer test.
    Optional modes list Mac ffmpeg/avfoundation inputs or verify SSH without
    copying files or playing audio.
  - Extended `tools/summarize_audio_probe_runs.py` to parse McBSP sysfs
    readback and the `nq cyclic` DMA descriptor. The sweep summary now reports
    actual `dma_op_mode`/`max_tx_thres` readback, flags requested/readback
    mismatches as non-candidates, and exposes `sig`, `ccr`, and `csdp` columns
    for the logged cyclic DMA descriptor. Updated the offline regression test
    to cover those parser paths.
  - Added a gated OMAP DMA hardware register readback under the existing
    `nq.omap_dma_dump_cyclic=1` boot flag. The kernel now emits `nq dma-load`
    before enabling a cyclic channel and `nq dma-start` immediately after
    `CCR.EN`, with `CCR`, `CSDP`, `CICR`, `CSR`, `CEN`, `CFN`, source/dest
    address/index registers, `CLNK_CTRL`, and `CDAC`. The cyclic descriptor log
    now includes `clnk` after self-link assignment. The sweep summarizer parses
    the `nq dma-start` line and reports `rccr`, `rcsdp`, and `rclnk`, giving the
    next live run direct evidence of the programmed channel state instead of
    only descriptor intent.
  - Added `nq.mcbsp_legacy_tx_irq=1` for the current legacy-DMA diagnostic
    image. With that flag, McBSP playback start clears stale IRQ status, enables
    only TX-underflow IRQs, and disables TX-underflow IRQ reporting after the
    first underflow, matching the downstream Steelhead handler more closely and
    avoiding a possible interrupt/log storm during distorted playback. The
    summarizer now treats `Underflow`/`Overflow` kernel messages as xrun-class
    faults.
  - Added a gated TAS571x hardware register readback with
    `nq.tas571x_dump_regs=1` in the current legacy-DMA diagnostic image. The
    codec now emits `nq tas571x` lines after legacy power-up, `hw_params`, and
    mute/unmute transitions, reading the actual hardware registers for clock,
    error, serial data interface, shutdown, soft mute, master/channel volume,
    input/PWM mux, and output pre/post scale. The probe runner keeps those lines
    in `audio-register-events.txt`, and the sweep summarizer exposes key codec
    values (`sdi`, `sys2`, `err`, `mvol`) beside the McBSP/DMA fields.
  - Added gated Steelhead machine-driver diagnostics with
    `nq.steelhead_audio_dump=1` in the current legacy-DMA diagnostic image. The
    machine driver now emits `nq steelhead` lines for stream startup,
    `hw_params`, and shutdown; the `hw_params` line records format, polarity,
    sample width, channels, MCLK, McBSP parent clock, BCLK target, and divider.
    The sweep summarizer exposes `fmt`, `inv`, `bclk`, `div`, and `mclk` so the
    next live run can confirm the port is still generating the legacy
    48 kHz/S16/stereo clock shape (`bclk=1536000`, `div=16`) while comparing
    DMA/FIFO hypotheses.
  - Expanded the McBSP register dump to include `THRSH1`, `IRQEN`, `XBUFFSTAT`,
    and `RBUFFSTAT` in addition to the existing control/status registers. These
    fields should help distinguish underrun/empty-FIFO behavior from codec-side
    distortion on the next speaker-connected run. The sweep summarizer now
    parses those dumps and reports `irqen`, `irqst`, `xbuf`, `rbuf`, `thr2`,
    and `thr1` as first-class table columns.
  - Added McBSP playback-start observability to the 6.6 port. The current
    startup path already includes the old Steelhead ready-reset behavior, so
    this logs `nq mcbsp start ...` fields instead of changing startup ordering
    blind. The sweep summarizer now reports `xrdy`, `xrst`, `rrdy`, and `rrst`
    from that line alongside the DMA, McBSP, and TAS5713 register evidence.
  - Updated the guarded live probe to capture ALSA mixer contents and set known
    moderate probe levels before playback by default:
    `NQ_PROBE_MASTER_VOLUME=190`, `NQ_PROBE_SPEAKER_VOLUME=204`, and
    `NQ_PROBE_SPEAKER_SWITCH=on`. Set `NQ_PROBE_SET_MIXER=0` if a future test
    intentionally needs to preserve the device's existing mixer state.
  - Updated the generated probe WAV to support `PROBE_CHANNELS=both|left|right`,
    defaulting to `both`. The default is now dual-channel mono so a single
    externally wired speaker is less likely to miss a left-only test signal.
    Left/right modes remain available for channel-mapping checks.
  - Tightened the sweep workflow so `tools/run_audio_probe_sweep_local.sh`
    requires `FFMPEG_INPUT` by default. This prevents accidentally spending a
    speaker-connected run collecting only source-WAV metrics, which cannot prove
    actual speaker quality. Use `REQUIRE_MIC=0` only for deliberate no-mic smoke
    tests; those runs remain non-candidates because they are marked `no-mic`.
  - Extended the capture analyzer and sweep summarizer to distinguish quiet or
    silent microphone captures from distorted captures. The analyzer now emits
    `rms`, `rms_dbfs`, `peak_dbfs`, `expected_tone_rms`, and
    `expected_tone_to_rms_db`; the sweep table exposes `rms` and `tone`, and
    verdicts mark captures below `--min-mic-rms` as `quiet`. This is useful for
    the modes that produced no audible output during listener testing.
  - Added `nq.mcbsp_legacy_threshold_frame=1` for the current legacy-DMA
    diagnostic image. In threshold mode, when the ALSA period fits within the
    configured McBSP FIFO threshold, this restores the old downstream behavior:
    leave DMA packet size at `0` and program the McBSP threshold to the whole
    period in words. The guarded sweep now includes `01-threshold-frame`, which
    uses `--period-size=512 --buffer-size=2048` without forcing
    `max_tx_thres`, so the next speaker-connected run can compare legacy
    period-sized threshold semantics against element mode and packet-threshold
    values.
  - Added `nq.tas571x_legacy_stream_reinit=1` for the current legacy-DMA
    diagnostic image. The old Android TAS5713 driver queued a reset, oscillator
    trim, raw init-table replay, and shutdown exit on every PCM START; the
    modern generic TAS571x path had Steelhead set to one-time probe init plus
    shutdown-bit mute/unmute. The new bootarg replays the legacy power/init
    sequence on unmute and keeps MCLK enabled afterward for Steelhead, while
    preserving the existing mute path. With `nq.tas571x_dump_regs=1`, the next
    probe should show a `nq tas571x legacy-stream-reinit` line plus fresh
    register readbacks if this path executes.
  - Extended the guarded probe and sweep summarizer to make those diagnostic
    paths machine-checkable. `audio-register-events.txt` now keeps
    `nq mcbsp hw` lines. The sweep table exposes McBSP hw-params fields
    (`mhw`, `frame`, `pwords`, `pkt`, `thw`) and TAS5713 stream-reinit fields
    (`reinit`, `kmclk`), and the offline regression test asserts that realistic
    kernel log lines populate those JSON/table fields. On the next live run,
    a threshold-frame probe should show `frame=1`, `pkt=0`, `thw` equal to the
    ALSA period in words, plus `reinit=1` and `kmclk=1`.
  - Strengthened `tools/check_audio_probe_prereqs_local.sh` so it now extracts
    the diagnostic boot-image command line with `strings`, verifies it is at or
    below the 512-byte Android boot image limit, and fails if any required audio
    diagnostic bootarg is missing. This caught the previous over-limit cmdline
    while adding TAS5713 stream reinit; the current legacy-DMA cmdline is
    503 bytes and retains the McBSP, DMA, TAS5713, and Steelhead diagnostics.
  - Wired that preflight into `tools/run_audio_probe_sweep_local.sh` with
    `RUN_PREFLIGHT=1` by default. After the explicit speaker/microphone guards
    pass, the sweep now validates host tools, executable probe scripts, offline
    analyzer tests, and the diagnostic boot-image cmdline before any fastboot,
    SSH, file copy, or playback step. `RUN_PREFLIGHT=0` is available only for a
    deliberate rerun after a separate successful preflight.
  - Tightened sweep verdicts so a run cannot be a `candidate` unless the
    expected diagnostic evidence is present. The summarizer now adds
    `tas-reinit-missing` when the TAS5713 stream-reinit log does not show
    `override=1` and `keep_mclk=1`. For the `threshold-frame` run it also
    requires `legacy_threshold_frame=1`, `pkt_size=0`, and
    `threshold_words == period_words`; otherwise it emits
    `threshold-frame-missing`, `threshold-frame-packet`, or
    `threshold-frame-threshold`. The offline regression test covers those
    non-candidate cases.
  - Fixed the TAS571x legacy stream-reinit diagnostic so repeated playback
    starts do not repeatedly increment the MCLK prepare/enable count. The
    driver now tracks when legacy MCLK is intentionally kept enabled, skips
    duplicate enables on subsequent reinit calls, and disables the kept clock
    exactly once on error, probe cleanup, or driver remove. The legacy-DMA
    diagnostic image was rebuilt after this fix.
  - Added `tools/audio_diag_required_args.sh` as the shared required audio
    diagnostic bootarg list for local-image and running-kernel validation.
    `tools/run_audio_legacydma_probe_local.sh` now reads `/proc/cmdline` over
    SSH after the device comes up but before WAV generation, file copy, mixer
    writes, or playback. If the running Nexus Q kernel is missing any required
    diagnostic bootarg, the probe writes `remote-cmdline-check.txt` and exits
    before audio. This protects runs where `FASTBOOT_BOOT=0` but the device is
    still running an older image.
  - Added `tools/test_audio_shell_guards.sh`, an offline regression test for
    the shell guardrails. It uses fake boot images and a fake SSH command to
    verify successful image cmdline validation, missing-bootarg failure,
    cmdline-length failure, and stale remote-kernel refusal before WAV
    generation or playback setup.
  - Wired the shell guard regression into
    `tools/check_audio_probe_prereqs_local.sh` with
    `RUN_AUDIO_SHELL_GUARD_TESTS=1` by default, alongside the existing Python
    analyzer regression. The shell guard test disables nested preflight test
    suites in its fake-image cases to avoid recursion.
  - Added `tools/test_audio_offline_local.sh` as the one-command no-playback
    validation runner. It covers shell syntax checks, Python syntax checks, the
    analyzer regression, shell guard regression, image/preflight checks, and
    `git diff --check` for non-kernel-patch files without contacting the Nexus Q
    or generating playback audio.
  - Fixed clean-source kernel patch application in
    `tools/build_linux66_omap2plus_local.sh`: the tracked patch is generated
    from repo-relative `build/patch-pristine/...` and `kernel/...` paths, so it
    must be applied with `patch -p2` when `SRC` points at a Linux source root.
    `tools/test_audio_offline_local.sh` now dry-runs that patch application
    against `build/patch-pristine/linux-6.6.142`.
  - Added `tools/triage_audio_sweep.py` to turn `sweep-summary.json` into a
    short post-run decision. It reports candidate count, the top candidate or
    best failed run, clustered verdict reasons, and the next likely action
    (listen/promote candidate, fix capture/speaker setup, inspect kernel faults,
    fix missing diagnostics, or continue McBSP/SDMA timing work). The triage
    logic is covered by the offline analyzer regression test. The guarded sweep
    now writes `sweep-triage.txt` and `sweep-triage.json` automatically after
    each sweep.
  - Fixed the guarded probe's SSH remote-argument handling. OpenSSH executes
    remote command strings through a shell, so empty optional arguments and
    `APLAY_EXTRA_ARGS` containing spaces were not reliably preserved. The probe
    runner now shell-quotes remote `sh -s -- ...` arguments before sending the
    script body.
  - Corrected the sweep's legacy threshold-frame case. McBSP2 exposes
    `max_tx_thres=112`; S16 stereo `--period-size=512` becomes
    `period_words=1024`, so it never tested the frame-threshold path. The
    default is now `LEGACY_FRAME_MAX_TX_THRES=112` with
    `--period-size=56 --buffer-size=672`, which gives `period_words=112`.
  - Live low-volume testing on June 13 used mixer settings
    `NQ_PROBE_MASTER_VOLUME=180` and `NQ_PROBE_SPEAKER_VOLUME=190`, below the
    earlier `190/204` probe level. Element mode and threshold mode with
    `max_tx_thres=32` and `64` still produced high envelope variation
    (`env_cv` around `0.43` to `0.46`) and dropout/pumping verdicts. The true
    legacy frame-threshold case did log `legacy_threshold_frame=1`,
    `pkt_size=0`, `threshold_words=112`, and `xrst_reset=1`, but immediately
    hit RX/TX underflow and `aplay` returned EIO. That makes old
    frame-threshold semantics a non-fix for this 6.6 port.
    producing `sweep-summary.txt` and `sweep-summary.json`.
  - Extended sweep triage to include the best/candidate run's concrete McBSP
    settings and a guarded one-run retest command in text and JSON output. This
    keeps the next live iteration explicit: if a sweep finds a candidate, re-run
    only that mode/threshold/period geometry for a listening check before
    promoting it into the default audio path; if it fails, use the same command
    to reproduce the best failed run while inspecting kernel logs.
  - Extended triage again for the DMA-modular workflow. When a summarized run
    includes a valid `case-plan.txt` module-sweep case, text and JSON triage now
    include a `module_retest` command that replays only that case with
    `FASTBOOT_BOOT=0`, `BUILD_MODULES=0`, and `INSTALL_MODULES=0`. This is the
    preferred low-volume loop for audio-driver experiments after the modular
    image is already booted.
  - Added PCM progress triage for the repeated active `/proc/asound` status
    samples. Fresh triage output now includes a `pcm:` line that distinguishes
    stalled `hw_ptr`, missing active samples, and normal pointer progress. If
    DMA callbacks and ALSA `hw_ptr` both advance while microphone metrics remain
    bad, the next recommendation shifts away from basic DMA service and toward
    McBSP framing/FIFO timing or TAS5713 state.
  - Added a McBSP stop-state diagnostic line and parser support. When Nexus Q
    McBSP diagnostics are enabled, the driver now logs `nq mcbsp stop` with
    pre/post stop SPCR, CCR, IRQ, FIFO, and threshold fields. The summarizer
    exposes compact stop columns, and triage emits an `mcbsp:` line that flags
    pending stop-time IRQ status before treating a distorted capture as a codec
    issue.
  - Added a TAS5713 pre-mute register snapshot. The codec now dumps diagnostic
    registers immediately before asserting shutdown on stream mute, and the
    summarizer exposes `pm_sys2` / `pm_err`. Triage emits a `tas571x:` line and
    treats non-zero pre-mute `ERR` as a codec-side lead from the playback
    interval rather than relying only on post-shutdown register state.
  - Built and booted
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-modular.img`
    with TAS571x, McBSP, Steelhead, and TI SDMA PCM as modules. The modular
    stack reproduces the bad audio signature, so McBSP/TAS5713/ASoC experiments
    can now use `tools/build_audio_modules_local.sh`,
    `tools/install_audio_modules_remote.sh`, and
    `tools/reload_audio_modules_remote.sh` instead of a fastboot reboot. OMAP
    DMA core changes still require a different boot image unless that driver is
    made safely modular.
  - Added a reloadable McBSP `nq_no_xrst_reset` experiment and tested it at low
    volume in `artifacts/audio-probe-modular-noxrst-20260613-080951`. The
    parameter was active, but the baseline path had `xready=0`, so the
    transmitter ready-reset was not firing either way. The capture still had
    flutter/pumping and was not a fix.
  - Fixed the guarded probe's event extraction to write `dmesg-delta.txt` and
    summarize only per-run kernel deltas. Earlier sweep summaries could inherit
    stale underrun lines from previous playback attempts because they grepped a
    raw `dmesg | tail`.
  - Added `tools/run_audio_period_sweep_local.sh` for repeatable element-mode
    ALSA period/buffer tests. The low-volume sweep in
    `artifacts/audio-period-sweep-modular-20260613-081545` found no clean
    period setting. Default/large periods still had flutter/dropout/pumping;
    smaller `256:1024` and `1024:4096` cases also logged userspace ALSA
    underruns and sounded worse by the microphone metrics.
  - Added module parameters to `drivers/dma/ti/omap-dma.c` for the existing
    Nexus Q cyclic DMA diagnostics, then built
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
    with `CONFIG_DMA_OMAP=m` plus audio modules. The image builds and includes
    `drivers/dma/ti/omap-dma.ko`, but the first `fastboot boot` did not reach
    SSH, USB ECM/ACM, ARP, or fastboot fallback. Treat this as a boot-regression
    experiment: `omap-dma=m` likely needs the module copied into the initramfs
    and loaded before the eMMC/rootfs/network path can be trusted.
  - Follow-up: added a post-module build hook for the DMA-modular image. The
    hook regenerates the Debian loader initramfs after `omap-dma.ko` exists,
    embeds it as `/lib/modules/omap-dma.ko`, and the loader now attempts a
    guarded BusyBox `insmod` before waiting for `/dev/mmcblk0p13`. This should
    let the device reach the rootfs with `CONFIG_DMA_OMAP=m`, after which DMA
    diagnostics can iterate with module reloads instead of full fastboot boots.
    It still needs a live fastboot retry before treating DMA reload as proven.
  - Added one more DMA reload experiment for old-kernel parity:
    `nq_legacy_cyclic_block_irq`. The downstream OMAP PCM path kept block IRQ
    enabled by default and added frame IRQ for period wakeups; mainline cyclic
    DMA normally uses frame IRQ only. This is not expected to change raw data
    movement, but it lets the modular DMA test match old interrupt programming
    exactly enough to rule it out.
  - Answered the iteration strategy question explicitly: yes, once the
    early-load DMA-modular image boots, the fast debug path is to rebuild,
    install, and reload the audio/DMA modules over SSH rather than fastboot
    booting every trial. Full reboots are still required for device tree,
    initramfs, bootargs, and anything compiled into the base kernel.
  - Added `tools/run_audio_module_reload_sweep_local.sh`, which automates that
    faster path. It can build modules, install them to the Q, reload
    `omap-dma` plus the ASoC audio modules per case, verify the active remote
    module parameters with `REQUIRED_REMOTE_MODULE_PARAMS`, then run the
    microphone-captured guarded playback probe and summarize/triage the sweep.
    The stale-module guard is covered by `tools/test_audio_shell_guards.sh`.
    The wrapper now also accepts `FASTBOOT_BOOT=1`, which boots the
    DMA-modular image once, waits for SSH, installs the rebuilt modules, and
    then forces per-case probes to `FASTBOOT_BOOT=0` so every tested case uses
    module reloads instead of another boot.
  - Added `tools/run_audio_module_reload_sweep_when_ready_local.sh` for
    unattended live iterations. It polls for either SSH or fastboot; SSH runs
    the module-reload sweep directly, while fastboot boots the DMA-modular
    image once and then lets the same sweep reload modules between cases.
  - Added `tools/run_audio_format_module_sweep_local.sh` for the same reload
    path but focused on DAI format and clock polarity. The Steelhead machine
    driver parses `nq_audio_format` and `nq_audio_inversion` at module probe
    time, so the modular image can retest `i2s`/`left_j` plus all four
    polarity settings without a fastboot reboot between cases. `right_j` is
    not included because the current OMAP McBSP DAI rejects that format.
  - Corrected the OMAP DMA cyclic sync diagnostic. Rechecking the old kernel
    constants showed `OMAP_DMA_DST_SYNC == 0` and `OMAP_DMA_SRC_SYNC == 1`;
    old playback set destination sync, and mainline cyclic DMA already matches
    that by leaving `CCR_TRIGGER_SRC` clear for `DMA_MEM_TO_DEV`. The earlier
    `nq_legacy_cyclic_sync=1` implementation had accidentally set
    `CCR_TRIGGER_SRC` for playback, pushing the diagnostic image away from the
    old Steelhead path. The code now keeps playback destination-synchronized
    and capture source-synchronized.
  - Added bounded OMAP SDMA cyclic interrupt logging for the DMA-modular path.
    `omap-dma` now accepts `nq_dump_irq_limit` / bootarg
    `nq.omap_dma_dump_irq_limit`, resets the per-channel counter on each
    descriptor start, logs the first N cyclic DMA interrupt callbacks plus any
    error-status callbacks, and logs a final stop-state register snapshot. The
    module reload sweep passes and verifies `nq_dump_irq_limit=24` by default,
    and `tools/summarize_audio_probe_runs.py` now surfaces the latest captured
    DMA IRQ count/status/CSR/CDAC values in sweep summaries.
  - Extended the DMA module-reload sweep with packet-mode McBSP/DMA cases. The
    default live sweep now includes `mainline-packet`, which disables
    `snd_soc_omap_mcbsp:nq_legacy_element` and
    `nq_legacy_threshold_frame` while using the mainline DMA packed/burst/block
    settings. A non-default `legacy-dma-packet` case keeps the legacy DMA
    toggles but disables the McBSP element-mode override. This lets the next
    speaker-connected run test whether the persistent flutter is tied to the
    old element-mode hypothesis versus packet-mode DMA pacing, without a new
    boot image.
  - Added `omap-dma:nq_cyclic_burst_bits`, a reloadable diagnostic override
    for cyclic CSDP burst bits. The existing behavior remains `-1`; explicit
    values `0`, `16`, `32`, and `64` force the direction-relevant CSDP burst
    field. The default module sweep now includes `legacy-burst16`, and the
    summarizer records `case-plan.txt` fields so `burst_bits` appears beside
    the observed DMA `csdp` register value.
  - Added `snd_soc_steelhead_tas5713:nq_bclk_fs`, a reloadable machine-driver
    override for BCLK frame size. The default remains `0`, which derives BCLK
    from `params_physical_width * channels`; explicit values such as `32` and
    `64` force the McBSP clock divider target. The default module sweep now
    includes `forced-bclk32` and `forced-bclk64`, and the summarizer shows both
    the planned BCLK override and the logged `bclk_override` from
    `nq steelhead hw_params`.
  - Added `tools/check_tas5713_init_parity.py` to parse the old 3.0
    `tas5713_reg_init.h` table and the Linux 6.6
    `steelhead_tas5713_init_sequence`, failing if the raw codec initialization
    bytes diverge. This makes codec-table parity verified evidence rather than
    another manual comparison before each live audio run.
  - Tightened TAS571x MCLK ownership for reload-based testing. The codec now
    tracks generic ASoC bias-level MCLK enables separately from Steelhead's
    legacy "keep MCLK after init" hold, so repeated module reloads and playback
    starts can balance both clock references independently. This avoids a false
    reload-only failure mode where bias OFF could disable the legacy-held MCLK
    or later replay could leave an extra prepare/enable reference behind.
  - Extended the DMA diagnostics for the next speaker-connected run. `omap-dma`
    now dumps cyclic channel state before and after terminate/stop, and
    `tools/summarize_audio_probe_runs.py` dedupes timestamped `nq dma-irq`
    events to report IRQ interval average/max plus stopped CSR/CDAC. The goal is
    to separate irregular or missing DMA period callbacks from continuous but
    incorrectly framed I2S output.
  - Tightened the DMA diagnostics again after older artifacts showed DMA start
    logs but no callback evidence. `omap-dma` now appends total cyclic callback
    count plus global DMA IRQ mask/status to `nq dma-*` snapshots, and the
    summarizer exposes the stopped values as `scnt`, `simask`, and `sistat1`.
    This is diagnostic-only and reloadable with `omap-dma.ko`; it should make
    the next low-volume module sweep prove whether the flutter path has missing
    period callbacks, masked DMA IRQs, or normal DMA service with a downstream
    framing/codec issue. Validation passed with `python3 tools/test_audio_analysis.py`,
    `tools/test_audio_shell_guards.sh`, `tools/build_audio_dma_modules_local.sh`,
    and `FFMPEG_INPUT=':0' tools/test_audio_offline_local.sh`.
  - Extended `tools/triage_audio_sweep.py` to consume the new stop-time DMA
    fields. Fresh triage output now includes a `dma:` line and changes the next
    action when callbacks are missing, DMA IRQs appear masked, or callbacks are
    present but microphone metrics still show flutter/distortion. This keeps
    the next live module sweep focused on SDMA IRQ service versus McBSP/TAS5713
    framing instead of producing a generic distorted-output recommendation.
  - Added a reloadable McBSP `nq_stop_on_tx_underflow` diagnostic. The old
    Steelhead 3.0 driver stopped playback on TX underflow; the 6.6 path only
    logged the interrupt. The module reload sweep now includes a
    `stop-on-underflow` case that restores the old fail-fast XRUN behavior for
    that one trial, which should make FIFO starvation show up as an aborted
    playback instead of another subjective distorted-tone result.
  - Extended `tools/summarize_audio_probe_runs.py` to parse the live
    `/proc/asound/.../hw_params` block captured in `aplay.log`. The next sweep
    summary will now show accepted PCM format/rate/channels/period/buffer next
    to the McBSP/TAS5713/DMA evidence, so a trial cannot be mistaken for a
    legacy S16/48 kHz comparison if ALSA negotiated a different stream shape.
    Re-summarizing the existing June 13 captures showed the bad runs were
    already negotiated as S16_LE/48 kHz/stereo, so the remaining distortion is
    not explained by userspace choosing a wider PCM format.
  - Rechecked the tempting McBSP2 FIFO-size hypothesis. The old ASoC comment
    mentions a 1024+256 word McBSP2 FIFO, but the old OMAP platform code only
    used `0x500` for config type 3; config type 4, which covers OMAP4, used
    `0x80` for all McBSP instances. Current DT's `ti,buffer-size = <128>` is
    therefore not changed without stronger hardware evidence.
  - Fixed another live-probe blind spot: existing `aplay.log` captures sampled
    `/proc/asound/.../status` after a fixed 0.35 s sleep, but the TAS5713
    legacy stream reinit can take longer. Re-summarizing older runs now exposes
    `pcm_state=SETUP`, `hwptr=0`, and `applptr=0`, so those status snapshots
    were pre-trigger and not useful evidence about runtime DMA progress. The
    guarded probe now waits up to roughly six seconds for `RUNNING` before
    collecting status, and the summarizer reports `pcm_state`, `delay`, `avail`,
    `avail_max`, `hwptr`, and `applptr`.
  - Extended the active-playback ALSA status capture again for the module-reload
    loop. The guarded probe now records an initial status snapshot plus repeated
    `/proc/asound/.../status` samples while `aplay` is still alive, and
    `tools/summarize_audio_probe_runs.py` reports sample count plus
    first-to-last `hw_ptr` / `appl_ptr` deltas. That should make the next
    no-reboot sweep show whether PCM/DMA pointers are advancing steadily,
    stalling, or underrunning while the speaker output sounds distorted.
  - Re-summarized the saved June 13 audio artifacts with the current parser and
    wrote `artifacts/audio-saved-runs-summary-current.txt`. There are still no
    saved candidates: element mode, threshold mode, period-size changes, LDC
    trigger order, and no-XRST all remain flutter/pumping/dropout/frequency or
    XRUN failures. All saved `/proc/asound/.../status` snapshots are also
    pre-trigger `SETUP`, so they cannot prove runtime DMA pointer progress; the
    next speaker-connected module-reload run needs the new repeated status
    samples.
  - Added one more reload-sweep case, `mcbsp-txburst16`, because the old
    Steelhead ASoC path always carried a 16-word DMA burst mode while the saved
    6.6 element-mode runs logged McBSP `maxburst=0`. This case passes
    `snd_soc_omap_mcbsp:nq_tx_burst=16` and verifies that parameter before
    playback. It is distinct from `legacy-burst16`, which only forces the OMAP
    SDMA CSDP burst field.
  - Added a guarded McBSP `nq_trigger_threshold` experiment after comparing the
    old Steelhead 3.x PCM path with the current 6.6 dmaengine path. The old
    driver programmed the McBSP FIFO threshold immediately before starting DMA;
    the current 6.6 path programs it during `hw_params`. The new
    `trigger-threshold` reload-sweep case caches the already-computed
    packet/threshold values and reapplies the McBSP threshold at PCM trigger
    time, before `omap_mcbsp_start()`, without changing the default behavior.
  - Added a combined `txburst-trigger-threshold` reload-sweep case. This keeps
    the two McBSP hypotheses independently testable while also checking whether
    old-style 16-word TX burst sizing and trigger-time FIFO threshold
    programming only work when enabled together.
  - Extended the guarded playback probe to capture `/proc/interrupts` before
    playback, after playback, and repeatedly inside `aplay.log` while playback
    is active. The saved artifacts did not show enough live interrupt/pointer
    evidence to distinguish distorted I2S framing from DMA/McBSP progress
    stalls, so the next module-reload run should preserve that evidence.
  - Extended `tools/summarize_audio_probe_runs.py` to parse those
    `/proc/interrupts` snapshots. The summary JSON now includes active
    playback and before/after interrupt deltas for relevant McBSP/DMA/audio
    lines, and the table exposes compact `pisamp`, `pidelta`, `pba_delta`, and
    `pitop` columns. This is diagnostic evidence only for now; it does not make
    a run pass or fail without the microphone/listening quality checks.
  - Rechecked the legacy 3.x Steelhead McBSP clock/format setup against the
    current 6.6 machine and DAI code. The important pieces still match: McBSP2
    is parented from the 24.576 MHz ABE clock, S16 stereo at 48 kHz derives a
    1.536 MHz BCLK with divider 16, I2S uses 1-bit data delay, normal
    bit/frame polarity maps to the same PCR0 semantics, and the default ASoC
    trigger order starts the dmaengine component before the McBSP DAI, matching
    the old platform-DMA-then-McBSP sequence more closely than the existing
    `nq.ldc=1` diagnostic. I did not add another clock-format experiment from
    this pass; the useful next evidence is live DMA/McBSP progress and event
    order.
  - Extended `tools/summarize_audio_probe_runs.py` again to parse event order
    from `aplay.log` / `dmesg-delta.txt`: TAS5713 legacy reinit, TAS5713
    unmute, DMA start, McBSP start, first DMA IRQ, and stop events. The summary
    JSON now has an `event_order` block, and the table reports `seq`, `d2m_ms`
    (DMA-start to McBSP-start), and `m2irq_ms` (McBSP-start to first DMA IRQ).
    These are diagnostic columns only; a run still needs microphone metrics and
    a listening check before audio can be called fixed.
  - Extended `tools/run_audio_module_reload_sweep_when_ready_local.sh` with
    conservative SSH rediscovery for DHCP changes. It still checks the explicit
    `NQ_HOST` and fastboot first, but when `NQ_DISCOVER_SSH=1` it scans the
    derived local `/24` for open SSH ports and accepts a new IP only when
    `ssh-keyscan` returns the same ED25519 host key already stored for the
    previous Nexus Q host in `~/.ssh/known_hosts`. This should reduce manual
    intervention if the Q boots at a different address, without attempting root
    login against every SSH host on the LAN.
  - Added a guarded Steelhead machine-driver `nq_legacy_s16_only` mode, enabled
    by default. The original 3.x TAS5713 codec DAI advertised stereo
    `S16_LE` only, while the modern generic TAS571x codec advertises wider
    formats. The new constraint rejects accidental S24/S32 negotiation on this
    board unless `NQ_LEGACY_S16_ONLY=0` / `nq_legacy_s16_only=0` is selected
    deliberately. The module-reload sweep verifies
    `snd_soc_steelhead_tas5713:nq_legacy_s16_only=1`, and the summarizer
    exposes the logged `legacy_s16_only` state in the `s16` column.
  - Added a reloadable TAS5713 trigger-power sequencing experiment after
    comparing the old 3.x TAS5713 codec trigger path with the modern TAS571x
    mute/unmute path. The old codec queued its power transition from
    `.trigger`, while the 6.6 generic driver normally unmutes during
    `prepare`. The patched `tas571x` driver now keeps a per-device DAI ops copy
    and defaults the Steelhead compatible to `mute_unmute_on_trigger=1`;
    `snd_soc_tas571x:nq_mute_on_trigger=-1` means use that Steelhead default,
    `0` disables it, and `1` forces it. The module-reload sweep passes and
    verifies `snd_soc_tas571x:nq_mute_on_trigger`, adds a `no-trigger-mute`
    A/B case, and the summarizer exposes the actual loaded value in the `tmute`
    column from the `nq tas571x probe` line. The Steelhead DAI link is now
    marked `nonatomic`, because trigger-time TAS5713 mute/unmute can run the
    legacy I2C/reset-delay path and must not sleep under ALSA's atomic PCM
    trigger locking.
  - Tightened that experiment with an explicit old-trigger-order case. The old
    Steelhead 3.x ASoC core called the codec DAI trigger first, then the OMAP
    platform DMA trigger, then the McBSP CPU DAI trigger. Modern 6.6 default
    trigger order starts the dmaengine component before DAI trigger, and
    `mute_unmute_on_trigger` unmutes the TAS5713 inside the DAI phase. The new
    Steelhead `nq_codec_power_first` module parameter lets the link trigger run
    TAS5713 digital mute/unmute before the component/DMA trigger for playback
    START. The module-reload sweep adds a `codec-first` case that pairs
    `snd_soc_steelhead_tas5713:nq_codec_power_first=1` with
    `snd_soc_tas571x:nq_mute_on_trigger=1`; the TAS571x driver now skips
    duplicate mute/unmute requests so the later DAI trigger does not replay the
    long legacy reset/init sequence a second time. Added
    `codec-first-link-only` as the sharper A/B case:
    `snd_soc_steelhead_tas5713:nq_codec_power_first=1` with
    `snd_soc_tas571x:nq_mute_on_trigger=0`, so only the Steelhead link trigger
    performs the TAS5713 power transition before DMA starts. The summarizer
    exposes this as `cpwr` and includes `steelhead-trigger` in the event-order
    sequence.
  - June 14 low-level audio retest: forced McBSP runtime PM `power/control=on`
    and captured `artifacts/audio-dma-pmcontrolon-left-440-amp005-20260614-003020`.
    The tone was still bad (`quiet,freq`), with McBSP FIFO polling showing no
    obvious starvation, so runtime autosuspend is not the primary wobble cause.
  - Built and booted a temporary pin-input DTS variant for McBSP2 CLKX/FSX
    using `PIN_INPUT` on those pads. Capture
    `artifacts/audio-dma-pininput-left-440-amp005-20260614-004259` was worse
    (`quiet,flutter,freq`), so the source tree was reverted to the prior pad
    direction for those pins.
  - Tested TAS5713 stream-reinit timing variants:
    `artifacts/audio-dma-noreinit-left-440-amp005-20260614-004417` and
    `artifacts/audio-dma-muteontrigger-left-440-amp005-20260614-004514`.
    Neither fixed the wobble, so the immediate failure is unlikely to be only
    TAS5713 reset/unmute timing.
  - Tested an 880 Hz baseline tone in
    `artifacts/audio-dma-baseline-left-880-amp005-20260614-004723`. The
    measured result was not a simple exact half-rate or double-rate error, so
    the remaining issue is probably not just one BCLK divider bit.
  - Rechecked the live clock tree before the board wedged: `mcbsp-sync` and
    `40124000.mcbsp fck` were both running at 24.576 MHz from `abe_24m_fclk`.
    This matches the old Steelhead `mcbsp2_sync_mux_ck` parent/rate and keeps
    the focus on McBSP start/framing, TAS5713 input interpretation, or DMA/FIFO
    service rather than parent clock rate.
  - The PIO diagnostic run
    `artifacts/audio-pio-left-440-amp005-20260614-004821` did not produce a
    usable tone and then left the board unreachable over both SSH and fastboot.
    Earlier saved PIO artifacts were also flutter/frequency failures, so raw
    McBSP/TAS playback is still not proven good. The last PIO implementation
    enabled McBSP TX-ready interrupts while also using an hrtimer filler; that
    may have caused an interrupt storm or hard lockup, and the userspace
    autoreboot timer cannot recover from that class of hang.
  - Added safer McBSP PIO diagnostics: `snd_soc_omap_mcbsp:nq_pio_irq=0` is now
    the default, PIO uses timer-only FIFO top-off unless explicitly opted into
    interrupts, underflow status is sampled/cleared during fills, and the
    `nq pio tone start` line is logged before the first MMIO FIFO write. The
    reload script exposes this as `NQ_MCBSP_PIO_IRQ`.
  - Added two old-driver codec-negotiation A/B switches. The 3.0 TAS5713 codec
    DAI did not implement `.set_fmt` or `.hw_params`; current 6.6 now has
    `snd_soc_steelhead_tas5713:nq_skip_codec_fmt` and
    `snd_soc_tas571x:nq_skip_hw_params`, exposed by
    `NQ_STEELHEAD_SKIP_CODEC_FMT` and `NQ_TAS571X_SKIP_HW_PARAMS`, to test
    that legacy shape without removing the modern generic path.
  - Rebuilt the DMA-modular diagnostic image with those changes:
    `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`.
    Also regenerated `patches/linux-6.6.142-nexusq-steelhead.patch` from
    `build/patch-pristine/linux-6.6.142` so clean-source rebuilds include the
    latest diagnostics.
  - Local validation after regeneration:
    `tools/test_audio_shell_guards.sh`, `tools/test_audio_offline_local.sh`,
    `python3 tools/test_audio_analysis.py`, and
    `git diff --check -- ':!patches/linux-6.6.142-nexusq-steelhead.patch'`
    passed. Full `git diff --check` is still intentionally not used because the
    generated kernel patch carries Linux-style whitespace that the repo-level
    check reports.
  - Next live sequence once the Q is back in fastboot:
    `fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`,
    wait for SSH, then extend the autoreboot timer. First test should reload
    timer-only PIO with `NQ_MCBSP_PIO_TONE_MS=6000`,
    `NQ_MCBSP_PIO_TONE_AMP=1638`, `NQ_MCBSP_PIO_TIMER_US=250`,
    `NQ_MCBSP_PIO_FILL_WORDS=128`, `NQ_MCBSP_PIO_IRQ=0`, and
    `NQ_TAS571X_REGMAP_SAMPLE=1`. If that still wobbles, repeat with
    `NQ_STEELHEAD_SKIP_CODEC_FMT=1 NQ_TAS571X_SKIP_HW_PARAMS=1` before going
    back to DMA/MP3 tests.
  - Added `tools/run_audio_pio_when_ready_local.sh` as the next preferred live
    entrypoint. It waits for SSH or fastboot, boots the DMA-modular image when
    necessary, installs the current modules, starts the rootfs watchdog feeder,
    arms the userspace autoreboot, reloads safe timer-only PIO diagnostics,
    captures one low-volume left-channel probe, and summarizes it.
    `NQ_PIO_LEGACY_CODEC=1` flips on the old-style codec-negotiation A/B
    switches for the same raw PIO test.
  - Hardened the DMA-modular diagnostic image for hard-hang recovery:
    `tools/build_audio_dma_modular_image_local.sh` now includes the existing
    `nexusq-linux66-devsafe.fragment` watchdog config and passes
    `nq.watchdog=60`, `nq.watchdog_boot_grace=240`,
    `omap_wdt.nowayout=1`, `omap_wdt.timer_margin=60`, and
    `omap_wdt.early_enable=1`. The Debian-loader initramfs now feeds
    `/dev/watchdog` only for a bounded boot lease. If Debian/SSH never comes
    up, the lease expires and the hardware watchdog should reset the board.
    Once SSH is reachable, `tools/start_watchdog_feeder_remote.sh` starts a
    rootfs feeder that waits for `/dev/watchdog` to become available and then
    keeps healthy short experiments from being interrupted. The previous
    infinite initramfs feeder could keep a non-networked boot alive forever,
    so that image may still require one manual fastboot recovery before the
    corrected image can take over.
