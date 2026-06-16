#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DMA_IMAGE="${DMA_IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img}"
DMA_OUT="${DMA_OUT:-$ROOT/build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular}"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
WAIT_READY_TIMEOUT="${WAIT_READY_TIMEOUT:-0}"
WAIT_READY_INTERVAL="${WAIT_READY_INTERVAL:-5}"
WAIT_SSH_TIMEOUT="${WAIT_SSH_TIMEOUT:-180}"
BUILD_MODULES="${BUILD_MODULES:-1}"
INSTALL_MODULES="${INSTALL_MODULES:-1}"
RUN_PREFLIGHT="${RUN_PREFLIGHT:-1}"
NQ_AUTOREBOOT_SECONDS="${NQ_AUTOREBOOT_SECONDS:-900}"
NQ_WATCHDOG_TIMEOUT="${NQ_WATCHDOG_TIMEOUT:-60}"
NQ_WATCHDOG_INTERVAL="${NQ_WATCHDOG_INTERVAL:-20}"
NQ_PIO_LEGACY_CODEC="${NQ_PIO_LEGACY_CODEC:-0}"
NQ_PIO_OUTDIR="${NQ_PIO_OUTDIR:-$ROOT/artifacts/audio-pio-safe-$(date +%Y%m%d-%H%M%S)}"
NQ_MCBSP_STOP_ON_TX_UNDERFLOW="${NQ_MCBSP_STOP_ON_TX_UNDERFLOW:-0}"
NQ_MCBSP_PIO_XRDY_POLL="${NQ_MCBSP_PIO_XRDY_POLL:-0}"
APLAY_TIMEOUT_SECONDS="${APLAY_TIMEOUT_SECONDS:-$((${DURATION:-6} + 6))}"

SSH_CHECK_OPTS="${SSH_CHECK_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10}"

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to run playback because NQ_SPEAKER_CONNECTED=1 is not set.

After confirming the speaker is connected:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0
EOF
	exit 2
fi

if [ "${REQUIRE_MIC:-1}" = "1" ] && [ -z "${FFMPEG_INPUT:-}" ]; then
	cat >&2 <<EOF
Refusing to run PIO probe because REQUIRE_MIC=1 and FFMPEG_INPUT is empty.

List Mac inputs first if needed:

  LIST_AUDIO_INPUTS=1 tools/run_audio_legacydma_probe_local.sh
EOF
	exit 2
fi

ssh_ready() {
	ssh $SSH_CHECK_OPTS "$NQ_USER@$NQ_HOST" 'true' >/dev/null 2>&1
}

fastboot_ready() {
	command -v fastboot >/dev/null 2>&1 || return 1
	fastboot devices | awk 'NF >= 2 && $2 == "fastboot" { found=1 } END { exit found ? 0 : 1 }'
}

wait_for_ssh() {
	echo "waiting for SSH on $NQ_USER@$NQ_HOST"
	elapsed=0
	while ! ssh_ready; do
		if [ "$elapsed" -ge "$WAIT_SSH_TIMEOUT" ]; then
			echo "timed out waiting for SSH on $NQ_HOST after ${WAIT_SSH_TIMEOUT}s" >&2
			exit 1
		fi
		sleep 2
		elapsed=$((elapsed + 2))
	done
}

wait_until_ready() {
	start="$(date +%s)"
	echo "waiting for Nexus Q over SSH or fastboot"
	while :; do
		if ssh_ready; then
			echo "Nexus Q is reachable over SSH"
			return 0
		fi
		if fastboot_ready; then
			echo "Nexus Q is in fastboot"
			return 0
		fi
		if [ "$WAIT_READY_TIMEOUT" -gt 0 ]; then
			now="$(date +%s)"
			if [ $((now - start)) -ge "$WAIT_READY_TIMEOUT" ]; then
				echo "timed out waiting for Nexus Q after ${WAIT_READY_TIMEOUT}s" >&2
				exit 1
			fi
		fi
		sleep "$WAIT_READY_INTERVAL"
	done
}

if [ "$RUN_PREFLIGHT" = "1" ]; then
	. "$ROOT/tools/audio_diag_required_args.sh"
	FASTBOOT_BOOT=1 IMAGE="$DMA_IMAGE" REQUIRE_MIC="${REQUIRE_MIC:-1}" \
		REQUIRED_IMAGE_ARGS="${REQUIRED_IMAGE_ARGS:-$NQ_AUDIO_DIAG_BASE_REQUIRED_ARGS}" \
		"$ROOT/tools/check_audio_probe_prereqs_local.sh"
fi

if [ "$BUILD_MODULES" = "1" ]; then
	"$ROOT/tools/build_audio_dma_modules_local.sh"
fi

wait_until_ready
if fastboot_ready; then
	fastboot boot "$DMA_IMAGE"
	wait_for_ssh
fi

if [ "$INSTALL_MODULES" = "1" ]; then
	OUT="$DMA_OUT" NQ_INSTALL_DMA=1 NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" \
		"$ROOT/tools/install_audio_modules_remote.sh"
fi

NQ_WATCHDOG_TIMEOUT="$NQ_WATCHDOG_TIMEOUT" \
	NQ_WATCHDOG_INTERVAL="$NQ_WATCHDOG_INTERVAL" \
	NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" \
	"$ROOT/tools/start_watchdog_feeder_remote.sh"

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" "
	/sbin/nq-autoreboot-cancel 2>/dev/null || true
	(sleep '$NQ_AUTOREBOOT_SECONDS'; echo nq safe pio autoreboot fired >/dev/console 2>/dev/null || true; /sbin/nq-reboot-fastboot) >/tmp/nq-safe-pio-autoreboot.log 2>&1 &
	echo \$! >/run/nq-autoreboot.pid
	/sbin/nq-autoreboot-status 2>/dev/null || true
	/sbin/nq-watchdog-status 2>/dev/null || true
	if [ -s /run/nq-watchdog-root.pid ] && kill -0 \$(cat /run/nq-watchdog-root.pid) 2>/dev/null; then
		echo nq root watchdog feeder launcher pid=\$(cat /run/nq-watchdog-root.pid)
	fi
" || true

if [ "$NQ_PIO_LEGACY_CODEC" = "1" ]; then
	NQ_STEELHEAD_SKIP_CODEC_FMT=1
	NQ_TAS571X_SKIP_HW_PARAMS=1
else
	NQ_STEELHEAD_SKIP_CODEC_FMT=0
	NQ_TAS571X_SKIP_HW_PARAMS=0
fi
export NQ_STEELHEAD_SKIP_CODEC_FMT NQ_TAS571X_SKIP_HW_PARAMS

env NQ_RELOAD_DMA=1 \
	NQ_MCBSP_PIO_TONE_MS="${NQ_MCBSP_PIO_TONE_MS:-6000}" \
	NQ_MCBSP_PIO_TONE_FREQ="${NQ_MCBSP_PIO_TONE_FREQ:-440}" \
	NQ_MCBSP_PIO_TONE_AMP="${NQ_MCBSP_PIO_TONE_AMP:-1638}" \
	NQ_MCBSP_PIO_THRESHOLD="${NQ_MCBSP_PIO_THRESHOLD:-96}" \
	NQ_MCBSP_PIO_TIMER_US="${NQ_MCBSP_PIO_TIMER_US:-500}" \
	NQ_MCBSP_PIO_FILL_WORDS="${NQ_MCBSP_PIO_FILL_WORDS:-48}" \
	NQ_MCBSP_PIO_IRQ="${NQ_MCBSP_PIO_IRQ:-0}" \
	NQ_MCBSP_PIO_XRDY_POLL="$NQ_MCBSP_PIO_XRDY_POLL" \
	NQ_MCBSP_PIO_DETACHED_STOP="${NQ_MCBSP_PIO_DETACHED_STOP:-1}" \
	NQ_MCBSP_FIFO_POLL_MS="${NQ_MCBSP_FIFO_POLL_MS:-10}" \
	NQ_MCBSP_STOP_ON_TX_UNDERFLOW="$NQ_MCBSP_STOP_ON_TX_UNDERFLOW" \
	NQ_TAS571X_LEGACY_STREAM_REINIT="${NQ_TAS571X_LEGACY_STREAM_REINIT:-1}" \
	NQ_TAS571X_MUTE_ON_TRIGGER="${NQ_TAS571X_MUTE_ON_TRIGGER:-0}" \
	NQ_TAS571X_IGNORE_MUTE="${NQ_TAS571X_IGNORE_MUTE:-1}" \
	NQ_STEELHEAD_CODEC_POWER_FIRST="${NQ_STEELHEAD_CODEC_POWER_FIRST:-0}" \
	NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" \
	"$ROOT/tools/reload_audio_modules_remote.sh"

case "$NQ_MCBSP_STOP_ON_TX_UNDERFLOW" in
	1|y|Y|yes|Yes|YES|true|True|TRUE|on|On|ON) required_stop_on_tx_underflow=Y ;;
	*) required_stop_on_tx_underflow=N ;;
esac

required_params="snd_soc_steelhead_tas5713:nq_audio_format=i2s snd_soc_omap_mcbsp:nq_pio_tone_ms=${NQ_MCBSP_PIO_TONE_MS:-6000} snd_soc_omap_mcbsp:nq_pio_tone_freq=${NQ_MCBSP_PIO_TONE_FREQ:-440} snd_soc_omap_mcbsp:nq_pio_tone_amp=${NQ_MCBSP_PIO_TONE_AMP:-1638} snd_soc_omap_mcbsp:nq_pio_irq=${NQ_MCBSP_PIO_IRQ:-0} snd_soc_omap_mcbsp:nq_pio_xrdy_poll=$NQ_MCBSP_PIO_XRDY_POLL snd_soc_omap_mcbsp:nq_pio_detached_stop=${NQ_MCBSP_PIO_DETACHED_STOP:-1} snd_soc_omap_mcbsp:nq_fifo_poll_ms=${NQ_MCBSP_FIFO_POLL_MS:-10} snd_soc_omap_mcbsp:nq_stop_on_tx_underflow=$required_stop_on_tx_underflow snd_soc_tas571x:nq_legacy_stream_reinit=${NQ_TAS571X_LEGACY_STREAM_REINIT:-1} snd_soc_tas571x:nq_mute_on_trigger=${NQ_TAS571X_MUTE_ON_TRIGGER:-0} snd_soc_tas571x:nq_ignore_mute=${NQ_TAS571X_IGNORE_MUTE:-1} snd_soc_tas571x:nq_skip_hw_params=$NQ_TAS571X_SKIP_HW_PARAMS snd_soc_steelhead_tas5713:nq_skip_codec_fmt=$NQ_STEELHEAD_SKIP_CODEC_FMT"

OUTDIR="$NQ_PIO_OUTDIR" \
	NQ_HOST="$NQ_HOST" NQ_USER="$NQ_USER" \
	NQ_SPEAKER_CONNECTED=1 \
	REQUIRE_REMOTE_CMDLINE=0 \
	REQUIRED_REMOTE_MODULE_PARAMS="$required_params" \
	NQ_TAS571X_REGMAP_SAMPLE=1 \
	PROBE_CHANNELS=left \
	DURATION="${DURATION:-6}" \
	RATE="${RATE:-48000}" \
	FREQ="${FREQ:-440}" \
	PCM_FORMAT="${PCM_FORMAT:-S16_LE}" \
	NQ_MCBSP_DMA_OP_MODE="${NQ_MCBSP_DMA_OP_MODE:-threshold}" \
	NQ_MCBSP_MAX_TX_THRES="${NQ_MCBSP_MAX_TX_THRES:-96}" \
	NQ_PROBE_MASTER_VOLUME="${NQ_PROBE_MASTER_VOLUME:-170}" \
	NQ_PROBE_SPEAKER_VOLUME="${NQ_PROBE_SPEAKER_VOLUME:-180}" \
	NQ_PROBE_TONE_AMP="${NQ_PROBE_TONE_AMP:-0.05}" \
	APLAY_EXTRA_ARGS="${APLAY_EXTRA_ARGS:---period-size=6000 --buffer-size=24000}" \
	APLAY_TIMEOUT_SECONDS="$APLAY_TIMEOUT_SECONDS" \
	"$ROOT/tools/run_audio_legacydma_probe_local.sh"

"$ROOT/tools/summarize_audio_probe_runs.py" "$NQ_PIO_OUTDIR"
