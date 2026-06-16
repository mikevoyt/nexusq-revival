#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SWEEP_DIR="${SWEEP_DIR:-$ROOT/artifacts/audio-sweep-$(date +%Y%m%d-%H%M%S)}"
THRESHOLDS="${THRESHOLDS:-2 4 8 16 32 64 128}"
BASELINE_MODE="${BASELINE_MODE:-element}"
BASELINE_JSON="${BASELINE_JSON:-$ROOT/artifacts/audio-baselines/jun12-bad-capture-expected-440.json}"
REQUIRE_MIC="${REQUIRE_MIC:-1}"
RUN_LEGACY_FRAME_CASE="${RUN_LEGACY_FRAME_CASE:-1}"
LEGACY_FRAME_MAX_TX_THRES="${LEGACY_FRAME_MAX_TX_THRES:-112}"
LEGACY_FRAME_APLAY_EXTRA_ARGS="${LEGACY_FRAME_APLAY_EXTRA_ARGS:---period-size=56 --buffer-size=672}"
RUN_PREFLIGHT="${RUN_PREFLIGHT:-1}"

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to run playback because NQ_SPEAKER_CONNECTED=1 is not set.

Reconnect the speaker, then run:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0

Optional:
  FASTBOOT_BOOT=1       boot the legacydma image before the first run
	  REQUIRE_MIC=0         allow a sweep without Mac microphone capture
	  PROBE_CHANNELS=both|left|right
	                         choose which PCM channels carry the test tone
	  THRESHOLDS="$THRESHOLDS"
                         McBSP threshold values to test
  RUN_LEGACY_FRAME_CASE=$RUN_LEGACY_FRAME_CASE
                         include a threshold-mode run that exercises the
                         old period-sized frame threshold path
  LEGACY_FRAME_MAX_TX_THRES=$LEGACY_FRAME_MAX_TX_THRES
                         McBSP TX threshold for the legacy-frame case
  LEGACY_FRAME_APLAY_EXTRA_ARGS='$LEGACY_FRAME_APLAY_EXTRA_ARGS'
                         ALSA period/buffer args for the legacy-frame case
  RUN_PREFLIGHT=$RUN_PREFLIGHT
                         run no-playback host/image preflight before sweeping
  SWEEP_DIR=$SWEEP_DIR
                         output directory for all runs
EOF
	exit 2
fi

if [ "$REQUIRE_MIC" = "1" ] && [ -z "${FFMPEG_INPUT:-}" ]; then
	cat >&2 <<EOF
Refusing to run sweep because REQUIRE_MIC=1 and FFMPEG_INPUT is empty.

The sweep is meant to compare actual speaker output, not just the generated
source WAV. List Mac inputs first if needed:

  LIST_AUDIO_INPUTS=1 tools/run_audio_legacydma_probe_local.sh

Then run with an avfoundation input, for example:

  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' $0

Set REQUIRE_MIC=0 only for a deliberate no-microphone smoke run.
EOF
	exit 2
fi

if [ "$RUN_PREFLIGHT" = "1" ]; then
	"$ROOT/tools/check_audio_probe_prereqs_local.sh"
fi

mkdir -p "$SWEEP_DIR"

{
	echo "sweep_dir=$SWEEP_DIR"
	echo "baseline_mode=$BASELINE_MODE"
	echo "thresholds=$THRESHOLDS"
	echo "require_mic=$REQUIRE_MIC"
	echo "freq=${FREQ:-440}"
	echo "rate=${RATE:-48000}"
	echo "duration=${DURATION:-4}"
	echo "probe_channels=${PROBE_CHANNELS:-both}"
	echo "ffmpeg_input=${FFMPEG_INPUT:-}"
	echo "aplay_extra_args=${APLAY_EXTRA_ARGS:-}"
	echo "run_preflight=$RUN_PREFLIGHT"
	echo "run_legacy_frame_case=$RUN_LEGACY_FRAME_CASE"
	echo "legacy_frame_max_tx_thres=$LEGACY_FRAME_MAX_TX_THRES"
	echo "legacy_frame_aplay_extra_args=$LEGACY_FRAME_APLAY_EXTRA_ARGS"
	echo "nq_probe_set_mixer=${NQ_PROBE_SET_MIXER:-1}"
	echo "nq_probe_master_volume=${NQ_PROBE_MASTER_VOLUME:-190}"
	echo "nq_probe_speaker_volume=${NQ_PROBE_SPEAKER_VOLUME:-204}"
	echo "nq_probe_speaker_switch=${NQ_PROBE_SPEAKER_SWITCH:-on}"
	echo "baseline_json=$BASELINE_JSON"
} > "$SWEEP_DIR/sweep-plan.txt"

run_probe() {
	label="$1"
	mode="$2"
	tx_thres="$3"
	boot="$4"
	probe_aplay_extra="${5-${APLAY_EXTRA_ARGS:-}}"
	run_dir="$SWEEP_DIR/$label"

	echo "=== $label mode=$mode tx_thres=${tx_thres:-none} aplay_extra=${probe_aplay_extra:-none} ==="
	mkdir -p "$run_dir"
	set +e
	OUTDIR="$run_dir" \
	FASTBOOT_BOOT="$boot" \
	NQ_MCBSP_DMA_OP_MODE="$mode" \
	NQ_MCBSP_MAX_TX_THRES="$tx_thres" \
	APLAY_EXTRA_ARGS="$probe_aplay_extra" \
		"$ROOT/tools/run_audio_legacydma_probe_local.sh"
	status="$?"
	set -e
	echo "$status" > "$run_dir/sweep-status.txt"
	return 0
}

boot_once="${FASTBOOT_BOOT:-0}"
run_probe "00-${BASELINE_MODE}" "$BASELINE_MODE" "" "$boot_once"

if [ "$RUN_LEGACY_FRAME_CASE" = "1" ]; then
	run_probe "01-threshold-frame" "threshold" "$LEGACY_FRAME_MAX_TX_THRES" "0" "$LEGACY_FRAME_APLAY_EXTRA_ARGS"
	i=2
else
	i=1
fi

for thres in $THRESHOLDS; do
	label="$(printf '%02d-threshold-%s' "$i" "$thres")"
	run_probe "$label" "threshold" "$thres" "0"
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
