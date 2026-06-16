#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SWEEP_DIR="${SWEEP_DIR:-$ROOT/artifacts/audio-period-sweep-$(date +%Y%m%d-%H%M%S)}"
PERIOD_CASES="${PERIOD_CASES:-1200:4800 2400:9600 4800:19200 6000:24000 9600:38400}"
BASELINE_JSON="${BASELINE_JSON:-$ROOT/artifacts/audio-baselines/jun12-bad-capture-expected-440.json}"
RUN_PREFLIGHT="${RUN_PREFLIGHT:-1}"
NQ_MCBSP_DMA_OP_MODE="${NQ_MCBSP_DMA_OP_MODE:-threshold}"
NQ_MCBSP_MAX_TX_THRES="${NQ_MCBSP_MAX_TX_THRES:-112}"
NQ_MCBSP_MAX_RX_THRES="${NQ_MCBSP_MAX_RX_THRES:-}"

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to run playback because NQ_SPEAKER_CONNECTED=1 is not set.

Reconnect the speaker, then run:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0

Optional:
  PERIOD_CASES="$PERIOD_CASES"
                         space-separated period:buffer pairs, plus optional default
  NQ_MCBSP_DMA_OP_MODE=$NQ_MCBSP_DMA_OP_MODE
                         McBSP DMA sysfs mode to write before each playback
  NQ_MCBSP_MAX_TX_THRES=$NQ_MCBSP_MAX_TX_THRES
                         McBSP TX FIFO threshold limit before each playback
  SWEEP_DIR=$SWEEP_DIR
                         output directory for all runs
  RUN_PREFLIGHT=$RUN_PREFLIGHT
                         run no-playback host/image preflight before sweeping
EOF
	exit 2
fi

if [ "$RUN_PREFLIGHT" = "1" ]; then
	"$ROOT/tools/check_audio_probe_prereqs_local.sh"
fi

mkdir -p "$SWEEP_DIR"

{
	echo "sweep_dir=$SWEEP_DIR"
	echo "period_cases=$PERIOD_CASES"
	echo "freq=${FREQ:-440}"
	echo "rate=${RATE:-48000}"
	echo "duration=${DURATION:-4}"
	echo "probe_channels=${PROBE_CHANNELS:-both}"
	echo "ffmpeg_input=${FFMPEG_INPUT:-}"
	echo "nq_mcbsp_dma_op_mode=$NQ_MCBSP_DMA_OP_MODE"
	echo "nq_mcbsp_max_tx_thres=$NQ_MCBSP_MAX_TX_THRES"
	echo "nq_mcbsp_max_rx_thres=$NQ_MCBSP_MAX_RX_THRES"
	echo "nq_probe_master_volume=${NQ_PROBE_MASTER_VOLUME:-190}"
	echo "nq_probe_speaker_volume=${NQ_PROBE_SPEAKER_VOLUME:-204}"
	echo "nq_probe_speaker_switch=${NQ_PROBE_SPEAKER_SWITCH:-on}"
	echo "nq_probe_tone_amp=${NQ_PROBE_TONE_AMP:-0.20}"
	echo "baseline_json=$BASELINE_JSON"
} > "$SWEEP_DIR/sweep-plan.txt"

run_probe() {
	label="$1"
	aplay_extra="$2"
	run_dir="$SWEEP_DIR/$label"

	echo "=== $label aplay_extra=${aplay_extra:-none} ==="
	mkdir -p "$run_dir"
	set +e
	OUTDIR="$run_dir" \
	FASTBOOT_BOOT=0 \
	NQ_MCBSP_DMA_OP_MODE="$NQ_MCBSP_DMA_OP_MODE" \
	NQ_MCBSP_MAX_TX_THRES="$NQ_MCBSP_MAX_TX_THRES" \
	NQ_MCBSP_MAX_RX_THRES="$NQ_MCBSP_MAX_RX_THRES" \
	APLAY_EXTRA_ARGS="$aplay_extra" \
		"$ROOT/tools/run_audio_legacydma_probe_local.sh"
	status="$?"
	set -e
	echo "$status" > "$run_dir/sweep-status.txt"
}

i=0
for case_spec in $PERIOD_CASES; do
	if [ "$case_spec" = "default" ]; then
		label="$(printf '%02d-default' "$i")"
		run_probe "$label" ""
	else
		period="${case_spec%%:*}"
		buffer="${case_spec#*:}"
		if [ -z "$period" ] || [ -z "$buffer" ] || [ "$period" = "$buffer" ]; then
			echo "invalid period case: $case_spec" >&2
			exit 2
		fi
		label="$(printf '%02d-period-%s-buffer-%s' "$i" "$period" "$buffer")"
		run_probe "$label" "--period-size=$period --buffer-size=$buffer"
	fi
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
