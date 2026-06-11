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
- TAS5713 speaker playback has a viable 6.6 path with the local
  `google,steelhead-tas5713` machine driver.
- The current validated audio artifact is:
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-machine-mclkfix2.img`.
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
- TAS5713/McBSP audio now has a working local 6.6 implementation, but it is
  not upstream-quality yet and still needs cleanup before publishing.

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
