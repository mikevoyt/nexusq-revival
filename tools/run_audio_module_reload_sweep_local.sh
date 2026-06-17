#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SWEEP_DIR="${SWEEP_DIR:-$ROOT/artifacts/audio-module-sweep-$(date +%Y%m%d-%H%M%S)}"
DMA_IMAGE="${DMA_IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img}"
DMA_OUT="${DMA_OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular}"
RUN_CASES="${RUN_CASES:-legacy-parity codec-first codec-first-link-only codec-first-link-no-reinit codec-first-link-bclk64 codec-first-link-bclk64-no-reinit no-trigger-mute stop-on-underflow legacy-burst16 mcbsp-txburst16 trigger-threshold txburst-trigger-threshold forced-bclk32 forced-bclk64 no-dma-blockirq no-tas-reinit mainline-packet mainline-dma}"
RUN_PREFLIGHT="${RUN_PREFLIGHT:-1}"
BUILD_MODULES="${BUILD_MODULES:-1}"
INSTALL_MODULES="${INSTALL_MODULES:-1}"
REQUIRE_MIC="${REQUIRE_MIC:-1}"
FASTBOOT_BOOT="${FASTBOOT_BOOT:-0}"
WAIT_SSH_TIMEOUT="${WAIT_SSH_TIMEOUT:-120}"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
NQ_WAIT_SSH_OPTS="${NQ_WAIT_SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4}"
BASELINE_JSON="${BASELINE_JSON:-$ROOT/artifacts/audio-baselines/jun12-bad-capture-expected-440.json}"
AUDIO_CMDLINE_ARGS="${AUDIO_CMDLINE_ARGS:-nq.audio_format=i2s nq.audio_inversion=nb-nf nq.steelhead_audio_dump=1 nq.tas571x_dump_regs=1 nq.tas571x_legacy_stream_reinit=1 nq.mcbsp_legacy_element=1 nq.mcbsp_legacy_threshold_frame=1 nq.mcbsp_legacy_tx_irq=1 nq.mcbsp_no_rx_err_irq=1}"
NQ_PROBE_MASTER_VOLUME="${NQ_PROBE_MASTER_VOLUME:-180}"
NQ_PROBE_SPEAKER_VOLUME="${NQ_PROBE_SPEAKER_VOLUME:-190}"
NQ_MCBSP_DMA_OP_MODE="${NQ_MCBSP_DMA_OP_MODE:-}"
NQ_MCBSP_MAX_TX_THRES="${NQ_MCBSP_MAX_TX_THRES:-}"
NQ_MCBSP_MAX_RX_THRES="${NQ_MCBSP_MAX_RX_THRES:-}"
NQ_DMA_DUMP_IRQ_LIMIT="${NQ_DMA_DUMP_IRQ_LIMIT:-24}"
NQ_DMA_CYCLIC_BURST_BITS="${NQ_DMA_CYCLIC_BURST_BITS:--1}"
NQ_BCLK_FS="${NQ_BCLK_FS:-0}"
NQ_LEGACY_S16_ONLY="${NQ_LEGACY_S16_ONLY:-1}"
NQ_TAS571X_MUTE_ON_TRIGGER="${NQ_TAS571X_MUTE_ON_TRIGGER:--1}"
NQ_TAS571X_SDI_OVERRIDE="${NQ_TAS571X_SDI_OVERRIDE:--1}"
NQ_STEELHEAD_CODEC_POWER_FIRST="${NQ_STEELHEAD_CODEC_POWER_FIRST:-0}"
export NQ_PROBE_MASTER_VOLUME NQ_PROBE_SPEAKER_VOLUME NQ_MCBSP_DMA_OP_MODE NQ_MCBSP_MAX_TX_THRES NQ_MCBSP_MAX_RX_THRES NQ_DMA_DUMP_IRQ_LIMIT NQ_DMA_CYCLIC_BURST_BITS NQ_BCLK_FS NQ_LEGACY_S16_ONLY NQ_TAS571X_MUTE_ON_TRIGGER NQ_TAS571X_SDI_OVERRIDE NQ_STEELHEAD_CODEC_POWER_FIRST

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to run playback because NQ_SPEAKER_CONNECTED=1 is not set.

Boot the DMA-modular image, confirm the speaker is connected, then run:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0

Optional:
  RUN_CASES="$RUN_CASES"
  BUILD_MODULES=$BUILD_MODULES
  INSTALL_MODULES=$INSTALL_MODULES
  RUN_PREFLIGHT=$RUN_PREFLIGHT
  REQUIRE_MIC=$REQUIRE_MIC
  FASTBOOT_BOOT=$FASTBOOT_BOOT
  WAIT_SSH_TIMEOUT=$WAIT_SSH_TIMEOUT
  NQ_HOST=$NQ_HOST
  NQ_PROBE_MASTER_VOLUME=$NQ_PROBE_MASTER_VOLUME
  NQ_PROBE_SPEAKER_VOLUME=$NQ_PROBE_SPEAKER_VOLUME
  NQ_MCBSP_DMA_OP_MODE=$NQ_MCBSP_DMA_OP_MODE
  NQ_MCBSP_MAX_TX_THRES=$NQ_MCBSP_MAX_TX_THRES
  NQ_MCBSP_MAX_RX_THRES=$NQ_MCBSP_MAX_RX_THRES
  SWEEP_DIR=$SWEEP_DIR
EOF
	exit 2
fi

if [ "$REQUIRE_MIC" = "1" ] && [ -z "${FFMPEG_INPUT:-}" ]; then
	cat >&2 <<EOF
Refusing to run module sweep because REQUIRE_MIC=1 and FFMPEG_INPUT is empty.

List Mac inputs first if needed:

  LIST_AUDIO_INPUTS=1 tools/run_audio_legacydma_probe_local.sh

Then run with an avfoundation input, for example:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0
EOF
	exit 2
fi

mkdir -p "$SWEEP_DIR"

wait_for_ssh() {
	echo "waiting for SSH on $NQ_USER@$NQ_HOST"
	elapsed=0
	while ! ssh $NQ_WAIT_SSH_OPTS "$NQ_USER@$NQ_HOST" 'true' >/dev/null 2>&1; do
		if [ "$elapsed" -ge "$WAIT_SSH_TIMEOUT" ]; then
			echo "timed out waiting for SSH on $NQ_HOST after ${WAIT_SSH_TIMEOUT}s" >&2
			return 1
		fi
		sleep 2
		elapsed=$((elapsed + 2))
	done
}

if [ "$RUN_PREFLIGHT" = "1" ]; then
	FASTBOOT_BOOT="$FASTBOOT_BOOT" \
	REQUIRED_IMAGE_ARGS="$AUDIO_CMDLINE_ARGS" \
		IMAGE="$DMA_IMAGE" \
		BASELINE_JSON="$BASELINE_JSON" \
		REQUIRE_MIC="$REQUIRE_MIC" \
		"$ROOT/tools/check_audio_probe_prereqs_local.sh"
fi

if [ "$BUILD_MODULES" = "1" ]; then
	"$ROOT/tools/build_audio_dma_modules_local.sh"
fi

if [ "$FASTBOOT_BOOT" = "1" ]; then
	fastboot boot "$DMA_IMAGE"
	wait_for_ssh
fi

if [ "$INSTALL_MODULES" = "1" ]; then
	OUT="$DMA_OUT" NQ_INSTALL_DMA=1 NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" \
		"$ROOT/tools/install_audio_modules_remote.sh"
fi

{
	echo "sweep_dir=$SWEEP_DIR"
	echo "dma_image=$DMA_IMAGE"
	echo "dma_out=$DMA_OUT"
	echo "run_cases=$RUN_CASES"
	echo "run_preflight=$RUN_PREFLIGHT"
	echo "build_modules=$BUILD_MODULES"
	echo "install_modules=$INSTALL_MODULES"
	echo "fastboot_boot=$FASTBOOT_BOOT"
	echo "wait_ssh_timeout=$WAIT_SSH_TIMEOUT"
	echo "nq_host=$NQ_HOST"
	echo "nq_user=$NQ_USER"
	echo "require_mic=$REQUIRE_MIC"
	echo "ffmpeg_input=${FFMPEG_INPUT:-}"
	echo "freq=${FREQ:-440}"
	echo "rate=${RATE:-48000}"
	echo "duration=${DURATION:-4}"
	echo "probe_channels=${PROBE_CHANNELS:-both}"
	echo "pcm_format=${PCM_FORMAT:-S16_LE}"
	echo "aplay_extra_args=${APLAY_EXTRA_ARGS:-}"
	echo "nq_probe_master_volume=$NQ_PROBE_MASTER_VOLUME"
	echo "nq_probe_speaker_volume=$NQ_PROBE_SPEAKER_VOLUME"
	echo "nq_mcbsp_dma_op_mode=$NQ_MCBSP_DMA_OP_MODE"
	echo "nq_mcbsp_max_tx_thres=$NQ_MCBSP_MAX_TX_THRES"
	echo "nq_mcbsp_max_rx_thres=$NQ_MCBSP_MAX_RX_THRES"
	echo "nq_dma_dump_irq_limit=$NQ_DMA_DUMP_IRQ_LIMIT"
	echo "nq_dma_cyclic_burst_bits_default=$NQ_DMA_CYCLIC_BURST_BITS"
	echo "nq_bclk_fs_default=$NQ_BCLK_FS"
	echo "nq_legacy_s16_only=$NQ_LEGACY_S16_ONLY"
	echo "nq_tas571x_mute_on_trigger=$NQ_TAS571X_MUTE_ON_TRIGGER"
	echo "nq_tas571x_sdi_override_default=$NQ_TAS571X_SDI_OVERRIDE"
	echo "nq_steelhead_codec_power_first=$NQ_STEELHEAD_CODEC_POWER_FIRST"
	echo "baseline_json=$BASELINE_JSON"
} > "$SWEEP_DIR/sweep-plan.txt"

required_params() {
	sync="$1"
	burst="$2"
	pack="$3"
	block_irq="$4"
	tas_reinit="$5"
	format="$6"
	inversion="$7"
	mcbsp_legacy_element="$8"
	mcbsp_legacy_threshold_frame="$9"
	burst_bits="${10}"
	bclk_fs="${11}"
	stop_on_underflow="${12}"
	tx_burst="${13}"
	trigger_threshold="${14}"
	tas_mute_on_trigger="${15}"
	codec_power_first="${16}"
	tas_sdi_override="${17}"
	cat <<EOF
omap_dma:nq_legacy_cyclic_sync=$sync omap_dma:nq_legacy_cyclic_burst=$burst omap_dma:nq_legacy_cyclic_pack=$pack omap_dma:nq_legacy_cyclic_block_irq=$block_irq omap_dma:nq_dump_cyclic=1 omap_dma:nq_dump_irq_limit=$NQ_DMA_DUMP_IRQ_LIMIT omap_dma:nq_cyclic_burst_bits=$burst_bits snd_soc_omap_mcbsp:nq_legacy_element=$mcbsp_legacy_element snd_soc_omap_mcbsp:nq_legacy_threshold_frame=$mcbsp_legacy_threshold_frame snd_soc_omap_mcbsp:nq_no_rx_err_irq=1 snd_soc_omap_mcbsp:nq_legacy_tx_irq=1 snd_soc_omap_mcbsp:nq_stop_on_tx_underflow=$stop_on_underflow snd_soc_omap_mcbsp:nq_tx_burst=$tx_burst snd_soc_omap_mcbsp:nq_trigger_threshold=$trigger_threshold snd_soc_tas571x:nq_dump_regs=1 snd_soc_tas571x:nq_legacy_stream_reinit=$tas_reinit snd_soc_tas571x:nq_mute_on_trigger=$tas_mute_on_trigger snd_soc_tas571x:nq_sdi_override=$tas_sdi_override snd_soc_steelhead_tas5713:nq_audio_dump=1 snd_soc_steelhead_tas5713:nq_audio_format=$format snd_soc_steelhead_tas5713:nq_audio_inversion=$inversion snd_soc_steelhead_tas5713:nq_legacy_s16_only=$NQ_LEGACY_S16_ONLY snd_soc_steelhead_tas5713:nq_codec_power_first=$codec_power_first snd_soc_steelhead_tas5713:nq_bclk_fs=$bclk_fs
EOF
}

run_case() {
	index="$1"
	case_name="$2"
	sync="$3"
	burst="$4"
	pack="$5"
	block_irq="$6"
	tas_reinit="$7"
	format="$8"
	inversion="$9"
	mcbsp_legacy_element="${10}"
	mcbsp_legacy_threshold_frame="${11}"
	burst_bits="${12:--1}"
	bclk_fs="${13:-0}"
	stop_on_underflow="${14:-0}"
	tx_burst="${15:-0}"
	trigger_threshold="${16:-0}"
	tas_mute_on_trigger="${17:-$NQ_TAS571X_MUTE_ON_TRIGGER}"
	codec_power_first="${18:-$NQ_STEELHEAD_CODEC_POWER_FIRST}"
	tas_sdi_override="${19:-$NQ_TAS571X_SDI_OVERRIDE}"
	label="$(printf '%02d-%s' "$index" "$case_name")"
	run_dir="$SWEEP_DIR/$label"
	module_params="$(required_params "$sync" "$burst" "$pack" "$block_irq" "$tas_reinit" "$format" "$inversion" "$mcbsp_legacy_element" "$mcbsp_legacy_threshold_frame" "$burst_bits" "$bclk_fs" "$stop_on_underflow" "$tx_burst" "$trigger_threshold" "$tas_mute_on_trigger" "$codec_power_first" "$tas_sdi_override")"

	echo "=== $label sync=$sync burst=$burst pack=$pack block_irq=$block_irq burst_bits=$burst_bits bclk_fs=$bclk_fs stop_on_underflow=$stop_on_underflow tx_burst=$tx_burst trigger_threshold=$trigger_threshold tas_reinit=$tas_reinit tas_mute_on_trigger=$tas_mute_on_trigger tas_sdi_override=$tas_sdi_override codec_power_first=$codec_power_first format=$format inversion=$inversion legacy_element=$mcbsp_legacy_element legacy_threshold_frame=$mcbsp_legacy_threshold_frame ==="
	mkdir -p "$run_dir"
	{
		echo "case=$case_name"
		echo "sync=$sync"
		echo "burst=$burst"
		echo "pack=$pack"
		echo "block_irq=$block_irq"
		echo "burst_bits=$burst_bits"
		echo "bclk_fs=$bclk_fs"
		echo "tas_reinit=$tas_reinit"
		echo "tas_mute_on_trigger=$tas_mute_on_trigger"
		echo "tas_sdi_override=$tas_sdi_override"
		echo "codec_power_first=$codec_power_first"
		echo "format=$format"
		echo "inversion=$inversion"
		echo "mcbsp_legacy_element=$mcbsp_legacy_element"
		echo "mcbsp_legacy_threshold_frame=$mcbsp_legacy_threshold_frame"
		echo "mcbsp_stop_on_tx_underflow=$stop_on_underflow"
		echo "mcbsp_tx_burst=$tx_burst"
		echo "mcbsp_trigger_threshold=$trigger_threshold"
		echo "required_module_params=$module_params"
	} > "$run_dir/case-plan.txt"

	set +e
	NQ_RELOAD_DMA=1 \
	NQ_DMA_LEGACY_CYCLIC_SYNC="$sync" \
	NQ_DMA_LEGACY_CYCLIC_BURST="$burst" \
	NQ_DMA_LEGACY_CYCLIC_PACK="$pack" \
	NQ_DMA_LEGACY_CYCLIC_BLOCK_IRQ="$block_irq" \
	NQ_DMA_DUMP_CYCLIC=1 \
	NQ_DMA_DUMP_IRQ_LIMIT="$NQ_DMA_DUMP_IRQ_LIMIT" \
	NQ_DMA_CYCLIC_BURST_BITS="$burst_bits" \
	NQ_MCBSP_LEGACY_ELEMENT="$mcbsp_legacy_element" \
	NQ_MCBSP_LEGACY_THRESHOLD_FRAME="$mcbsp_legacy_threshold_frame" \
	NQ_MCBSP_STOP_ON_TX_UNDERFLOW="$stop_on_underflow" \
	NQ_MCBSP_TX_BURST="$tx_burst" \
	NQ_MCBSP_TRIGGER_THRESHOLD="$trigger_threshold" \
	NQ_TAS571X_LEGACY_STREAM_REINIT="$tas_reinit" \
	NQ_TAS571X_MUTE_ON_TRIGGER="$tas_mute_on_trigger" \
	NQ_TAS571X_SDI_OVERRIDE="$tas_sdi_override" \
	NQ_STEELHEAD_CODEC_POWER_FIRST="$codec_power_first" \
	NQ_AUDIO_FORMAT="$format" \
	NQ_AUDIO_INVERSION="$inversion" \
	NQ_LEGACY_S16_ONLY="$NQ_LEGACY_S16_ONLY" \
	NQ_BCLK_FS="$bclk_fs" \
	NQ_HOST="$NQ_HOST" \
	NQ_USER="$NQ_USER" \
		"$ROOT/tools/reload_audio_modules_remote.sh" \
		> "$run_dir/reload.log" 2>&1
	reload_status="$?"
	set -e
	echo "$reload_status" > "$run_dir/reload-status.txt"
	if [ "$reload_status" -ne 0 ]; then
		echo "reload failed for $label; see $run_dir/reload.log" >&2
		return 0
	fi

	set +e
	OUTDIR="$run_dir" \
	IMAGE="$DMA_IMAGE" \
	FASTBOOT_BOOT=0 \
	NQ_HOST="$NQ_HOST" \
	NQ_USER="$NQ_USER" \
	NQ_MCBSP_DMA_OP_MODE="$NQ_MCBSP_DMA_OP_MODE" \
	NQ_MCBSP_MAX_TX_THRES="$NQ_MCBSP_MAX_TX_THRES" \
	NQ_MCBSP_MAX_RX_THRES="$NQ_MCBSP_MAX_RX_THRES" \
	REQUIRED_REMOTE_CMDLINE_ARGS="$AUDIO_CMDLINE_ARGS" \
	REQUIRED_REMOTE_MODULE_PARAMS="$module_params" \
	REQUIRE_REMOTE_CMDLINE=1 \
		"$ROOT/tools/run_audio_legacydma_probe_local.sh"
	probe_status="$?"
	set -e
	echo "$probe_status" > "$run_dir/probe-status.txt"
	return 0
}

i=0
for case_name in $RUN_CASES; do
	case "$case_name" in
			legacy-parity)
				run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1
				;;
			codec-first)
				run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 0 0 0 1 1
				;;
			codec-first-link-only)
				run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 0 0 0 0 1
				;;
			codec-first-link-no-reinit)
				run_case "$i" "$case_name" 1 1 1 1 0 i2s nb-nf 1 1 -1 0 0 0 0 0 1
				;;
			codec-first-link-bclk64)
				run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 64 0 0 0 0 1
				;;
			codec-first-link-bclk64-no-reinit)
				run_case "$i" "$case_name" 1 1 1 1 0 i2s nb-nf 1 1 -1 64 0 0 0 0 1
				;;
			no-trigger-mute)
				run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 0 0 0 0
				;;
			stop-on-underflow)
				run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 1
			;;
		legacy-burst16)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 16
			;;
		mcbsp-txburst16)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 0 16
			;;
		trigger-threshold)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 0 0 1
			;;
		txburst-trigger-threshold)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 0 0 16 1
			;;
		forced-bclk32)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 32
			;;
		forced-bclk64)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1 -1 64
			;;
		no-dma-blockirq)
			run_case "$i" "$case_name" 1 1 1 0 1 i2s nb-nf 1 1
			;;
		no-tas-reinit)
			run_case "$i" "$case_name" 1 1 1 1 0 i2s nb-nf 1 1
			;;
		legacy-dma-packet)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 0 0
			;;
		mainline-packet)
			run_case "$i" "$case_name" 0 0 0 0 1 i2s nb-nf 0 0
			;;
		mainline-packet-burst16)
			run_case "$i" "$case_name" 0 0 0 0 1 i2s nb-nf 0 0 16
			;;
		mainline-dma)
			run_case "$i" "$case_name" 0 0 0 0 1 i2s nb-nf 1 1
			;;
		i2s-nbnf)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 1 1
			;;
		i2s-nbif)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-if 1 1
			;;
		i2s-ibnf)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s ib-nf 1 1
			;;
		i2s-ibif)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s ib-if 1 1
			;;
		leftj-nbnf)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j nb-nf 1 1
			;;
		leftj-nbif)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j nb-if 1 1
			;;
		leftj-ibnf)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j ib-nf 1 1
			;;
		leftj-ibif)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j ib-if 1 1
			;;
		tt-i2s-tas-i2s-nbnf)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 0 0 64 0 0 0 1 0 0 3
			;;
		tt-i2s-tas-i2s-nbif)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-if 0 0 64 0 0 0 1 0 0 3
			;;
		tt-i2s-tas-i2s-ibnf)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s ib-nf 0 0 64 0 0 0 1 0 0 3
			;;
		tt-i2s-tas-i2s-ibif)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s ib-if 0 0 64 0 0 0 1 0 0 3
			;;
		tt-i2s-tas-leftj-nbnf)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-nf 0 0 64 0 0 0 1 0 0 6
			;;
		tt-i2s-tas-leftj-nbif)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s nb-if 0 0 64 0 0 0 1 0 0 6
			;;
		tt-i2s-tas-leftj-ibnf)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s ib-nf 0 0 64 0 0 0 1 0 0 6
			;;
		tt-i2s-tas-leftj-ibif)
			run_case "$i" "$case_name" 1 1 1 1 1 i2s ib-if 0 0 64 0 0 0 1 0 0 6
			;;
		tt-leftj-tas-i2s-nbnf)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j nb-nf 0 0 64 0 0 0 1 0 0 3
			;;
		tt-leftj-tas-i2s-nbif)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j nb-if 0 0 64 0 0 0 1 0 0 3
			;;
		tt-leftj-tas-i2s-ibnf)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j ib-nf 0 0 64 0 0 0 1 0 0 3
			;;
		tt-leftj-tas-i2s-ibif)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j ib-if 0 0 64 0 0 0 1 0 0 3
			;;
		tt-leftj-tas-leftj-nbnf)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j nb-nf 0 0 64 0 0 0 1 0 0 6
			;;
		tt-leftj-tas-leftj-nbif)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j nb-if 0 0 64 0 0 0 1 0 0 6
			;;
		tt-leftj-tas-leftj-ibnf)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j ib-nf 0 0 64 0 0 0 1 0 0 6
			;;
		tt-leftj-tas-leftj-ibif)
			run_case "$i" "$case_name" 1 1 1 1 1 left_j ib-if 0 0 64 0 0 0 1 0 0 6
			;;
		*)
			echo "unknown module sweep case: $case_name" >&2
			exit 2
			;;
	esac
	i=$((i + 1))
done

"$ROOT/tools/summarize_audio_probe_runs.py" --baseline-json "$BASELINE_JSON" "$SWEEP_DIR" \
	> "$SWEEP_DIR/sweep-summary.txt" || true
"$ROOT/tools/summarize_audio_probe_runs.py" --baseline-json "$BASELINE_JSON" --json "$SWEEP_DIR" \
	> "$SWEEP_DIR/sweep-summary.json" || true
"$ROOT/tools/triage_audio_sweep.py" "$SWEEP_DIR" \
	> "$SWEEP_DIR/sweep-triage.txt" || true
"$ROOT/tools/triage_audio_sweep.py" --json "$SWEEP_DIR" \
	> "$SWEEP_DIR/sweep-triage.json" || true

cat "$SWEEP_DIR/sweep-summary.txt"
echo
cat "$SWEEP_DIR/sweep-triage.txt"
echo "wrote $SWEEP_DIR"
