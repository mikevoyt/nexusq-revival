#!/usr/bin/env python3

import argparse
import shutil
from pathlib import Path


MODULE_PATTERNS = (
    "drivers/dma/ti/omap-dma.ko",
    "sound/soc/codecs/snd-soc-tas571x.ko",
    "sound/soc/ti/snd-soc-ti-sdma.ko",
    "sound/soc/ti/snd-soc-omap-mcbsp.ko",
    "sound/soc/ti/snd-soc-steelhead-tas5713.ko",
    "drivers/net/wireless/broadcom/brcm80211/**/*.ko",
)


def kernel_release(build_dir):
    release_file = build_dir / "include/config/kernel.release"
    if not release_file.exists():
        raise SystemExit(f"missing kernel release file: {release_file}")
    release = release_file.read_text().strip()
    if not release:
        raise SystemExit(f"empty kernel release file: {release_file}")
    return release


def copy_modules(build_dir, rootfs, release):
    copied = []
    modules_root = rootfs / "lib/modules" / release
    for pattern in MODULE_PATTERNS:
        for src in sorted(build_dir.glob(pattern)):
            rel = src.relative_to(build_dir)
            dest = modules_root / "kernel" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(dest)

    if not copied:
        raise SystemExit(f"no kernel modules matched in {build_dir}")

    modules_root.mkdir(parents=True, exist_ok=True)
    order = modules_root / "modules.order"
    order.write_text(
        "\n".join(str(path.relative_to(modules_root)) for path in copied) + "\n"
    )

    load_dir = rootfs / "etc/modules-load.d"
    load_dir.mkdir(parents=True, exist_ok=True)
    (load_dir / "nexusq-wifi.conf").write_text("brcmfmac\n")

    return copied


def main():
    parser = argparse.ArgumentParser(
        description="Install Nexus Q Linux 6.6 audio and Wi-Fi modules into the Debian rootfs."
    )
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--rootfs", required=True, type=Path)
    parser.add_argument("--kernel-release", default=None)
    args = parser.parse_args()

    build_dir = args.build_dir.resolve()
    rootfs = args.rootfs.resolve()
    if not build_dir.exists():
        raise SystemExit(f"missing build dir: {build_dir}")
    if not rootfs.exists():
        raise SystemExit(f"missing rootfs: {rootfs}")

    release = args.kernel_release or kernel_release(build_dir)
    copied = copy_modules(build_dir, rootfs, release)
    print(f"installed {len(copied)} modules for {release}")
    for path in copied:
        print(path.relative_to(rootfs))


if __name__ == "__main__":
    main()
