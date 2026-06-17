#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
OUT="${OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-public-debian-modular}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10}"
SCP_OPTS="${SCP_OPTS:--o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10}"
NQ_INSTALL_DMA="${NQ_INSTALL_DMA:-0}"

[ -f "$OUT/include/config/kernel.release" ] || {
	echo "missing kernel release file in $OUT" >&2
	exit 1
}
release="$(cat "$OUT/include/config/kernel.release")"

modules="
sound/soc/codecs/snd-soc-tas571x.ko
sound/soc/ti/snd-soc-ti-sdma.ko
sound/soc/ti/snd-soc-omap-mcbsp.ko
sound/soc/ti/snd-soc-steelhead-tas5713.ko
"

if [ "$NQ_INSTALL_DMA" = "1" ]; then
	modules="drivers/dma/ti/omap-dma.ko
$modules"
fi

for relpath in $modules; do
	[ -f "$OUT/$relpath" ] || {
		echo "missing module: $OUT/$relpath" >&2
		exit 1
	}
done

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" "mkdir -p /lib/modules/$release/kernel/drivers/dma/ti /lib/modules/$release/kernel/sound/soc/codecs /lib/modules/$release/kernel/sound/soc/ti"

for relpath in $modules; do
	dest="/lib/modules/$release/kernel/$relpath"
	scp $SCP_OPTS "$OUT/$relpath" "$NQ_USER@$NQ_HOST:$dest"
done

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" "depmod -a $release"
echo "installed audio modules for $release on $NQ_USER@$NQ_HOST"
