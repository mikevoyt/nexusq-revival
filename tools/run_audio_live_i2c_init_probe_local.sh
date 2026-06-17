#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUTDIR="${OUTDIR:-$ROOT/artifacts/audio-live-i2c-init-$(date +%Y%m%d-%H%M%S)}"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4}"
RATE="${RATE:-48000}"
FREQ="${FREQ:-440}"
DURATION="${DURATION:-20}"
PROBE_CHANNELS="${PROBE_CHANNELS:-left}"
NQ_PROBE_TONE_AMP="${NQ_PROBE_TONE_AMP:-0.05}"
NQ_PROBE_MASTER_VOLUME="${NQ_PROBE_MASTER_VOLUME:-170}"
NQ_PROBE_SPEAKER_VOLUME="${NQ_PROBE_SPEAKER_VOLUME:-180}"
NQ_MCBSP_DMA_OP_MODE="${NQ_MCBSP_DMA_OP_MODE:-threshold}"
NQ_MCBSP_MAX_TX_THRES="${NQ_MCBSP_MAX_TX_THRES:-112}"
APLAY_EXTRA_ARGS="${APLAY_EXTRA_ARGS:---period-size=6000 --buffer-size=24000}"
REMOTE_WAV="${REMOTE_WAV:-/tmp/nq-live-i2c-init-${PROBE_CHANNELS}-${FREQ}-${RATE}.wav}"
FFMPEG_INPUT="${FFMPEG_INPUT:-:0}"
LIVE_I2C_DELAY="${LIVE_I2C_DELAY:-1}"

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to run playback because NQ_SPEAKER_CONNECTED=1 is not set.
EOF
	exit 2
fi

mkdir -p "$OUTDIR"
WAV="$OUTDIR/nq-${PROBE_CHANNELS}-${FREQ}-${RATE}-S16_LE-${DURATION}s.wav"

ffmpeg -nostdin -y \
	-f lavfi -i "sine=frequency=$FREQ:duration=$DURATION:sample_rate=$RATE" \
	-filter_complex "[0:a]volume=$NQ_PROBE_TONE_AMP,pan=stereo|c0=c0|c1=0*c0[a]" \
	-map "[a]" -c:a pcm_s16le "$WAV" \
	> "$OUTDIR/wav-generate.log" 2>&1

python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" "$WAV" \
	> "$OUTDIR/source-wav-analysis.txt"
python3 "$ROOT/tools/analyze_audio_probe_capture.py" --json --expected "$FREQ" "$WAV" \
	> "$OUTDIR/source-wav-analysis.json"

scp $SSH_OPTS "$WAV" "$NQ_USER@$NQ_HOST:$REMOTE_WAV" \
	> "$OUTDIR/scp.log" 2>&1

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
	"NQ_MCBSP_DMA_OP_MODE=$NQ_MCBSP_DMA_OP_MODE NQ_MCBSP_MAX_TX_THRES=$NQ_MCBSP_MAX_TX_THRES NQ_PROBE_MASTER_VOLUME=$NQ_PROBE_MASTER_VOLUME NQ_PROBE_SPEAKER_VOLUME=$NQ_PROBE_SPEAKER_VOLUME sh -s" \
	> "$OUTDIR/mixer-state.txt" 2>&1 <<'REMOTE_SETUP'
set -eu
find /sys/devices -type f -name dma_op_mode 2>/dev/null |
	while read -r f; do printf '%s\n' "$NQ_MCBSP_DMA_OP_MODE" > "$f"; done
find /sys/devices -type f -name max_tx_thres 2>/dev/null |
	while read -r f; do printf '%s\n' "$NQ_MCBSP_MAX_TX_THRES" > "$f"; done
amixer -q -c 0 cset name="Speaker Switch" on || true
amixer -q -c 0 cset name="Speaker Volume" "$NQ_PROBE_SPEAKER_VOLUME,$NQ_PROBE_SPEAKER_VOLUME" || true
amixer -q -c 0 cset name="Master Volume" "$NQ_PROBE_MASTER_VOLUME" || true
amixer -c 0 contents 2>/dev/null || true
REMOTE_SETUP

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'cat /proc/interrupts' \
	> "$OUTDIR/interrupts-before.txt"
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'dmesg | tail -n 250' \
	> "$OUTDIR/dmesg-before.txt"
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" '
	for dir in \
		/sys/module/omap_dma/parameters \
		/sys/module/snd_soc_omap_mcbsp/parameters \
		/sys/module/snd_soc_tas571x/parameters \
		/sys/module/snd_soc_steelhead_tas5713/parameters
	do
		[ -d "$dir" ] || continue
		echo "--- $dir"
		for f in "$dir"/*; do
			[ -r "$f" ] || continue
			printf "%s=" "${f##*/}"
			cat "$f" 2>/dev/null || true
		done
	done
' > "$OUTDIR/module-params.txt"

ffmpeg_pid=""
if [ -n "$FFMPEG_INPUT" ]; then
	ffmpeg -nostdin -y -f avfoundation -i "$FFMPEG_INPUT" \
		-t "$((DURATION + 3))" "$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/ffmpeg.log" 2>&1 &
	ffmpeg_pid="$!"
	sleep 1
fi

set +e
python3 "$ROOT/tools/render_tas5713_i2cset_script.py" \
	"$ROOT/tools/nq_tas5713_i2c_init.c" \
	"$REMOTE_WAV" \
	"$APLAY_EXTRA_ARGS" \
	"$LIVE_I2C_DELAY" |
	ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'sh -s' \
		> "$OUTDIR/aplay-live-i2c.log" 2>&1
aplay_status="$?"
set -e
echo "aplay_status=$aplay_status" > "$OUTDIR/result.txt"

if [ -n "$ffmpeg_pid" ]; then
	wait "$ffmpeg_pid" || true
fi

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'cat /proc/interrupts' \
	> "$OUTDIR/interrupts-after.txt"
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'dmesg | tail -n 350' \
	> "$OUTDIR/dmesg-after.txt"
diff -u "$OUTDIR/dmesg-before.txt" "$OUTDIR/dmesg-after.txt" \
	> "$OUTDIR/dmesg-delta.txt" || true

if [ -s "$OUTDIR/mic-capture.m4a" ]; then
	python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" \
		"$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/mic-capture-analysis.txt" 2> "$OUTDIR/mic-capture-analysis.err" || true
	python3 "$ROOT/tools/analyze_audio_probe_capture.py" --json --expected "$FREQ" \
		"$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/mic-capture-analysis.json" 2>> "$OUTDIR/mic-capture-analysis.err" || true
	python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" \
		--window-start 4 --window-duration 10 --no-active-region \
		"$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/mic-capture-after-live-i2c-analysis.txt" 2>> "$OUTDIR/mic-capture-analysis.err" || true
	python3 "$ROOT/tools/analyze_audio_probe_capture.py" --json --expected "$FREQ" \
		--window-start 4 --window-duration 10 --no-active-region \
		"$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/mic-capture-after-live-i2c-analysis.json" 2>> "$OUTDIR/mic-capture-analysis.err" || true
fi

{
	echo "outdir=$OUTDIR"
	echo "duration=$DURATION"
	echo "live_i2c_delay=$LIVE_I2C_DELAY"
	echo "aplay_extra_args=$APLAY_EXTRA_ARGS"
	echo "aplay_status=$aplay_status"
	echo
	echo "source:"
	sed 's/^/  /' "$OUTDIR/source-wav-analysis.txt"
	if [ -s "$OUTDIR/mic-capture-analysis.txt" ]; then
		echo
		echo "mic full:"
		sed 's/^/  /' "$OUTDIR/mic-capture-analysis.txt"
	fi
	if [ -s "$OUTDIR/mic-capture-after-live-i2c-analysis.txt" ]; then
		echo
		echo "mic after live i2c:"
		sed 's/^/  /' "$OUTDIR/mic-capture-after-live-i2c-analysis.txt"
	fi
} > "$OUTDIR/audio-summary.txt"

cat "$OUTDIR/audio-summary.txt"
