#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT/tools/audio_diag_required_args.sh"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img}"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
OUTDIR="${OUTDIR:-$ROOT/artifacts/audio-probe-$(date +%Y%m%d-%H%M%S)}"
RATE="${RATE:-48000}"
FREQ="${FREQ:-440}"
DURATION="${DURATION:-4}"
PROBE_CHANNELS="${PROBE_CHANNELS:-both}"
PCM_FORMAT="${PCM_FORMAT:-S16_LE}"
REMOTE_WAV="${REMOTE_WAV:-/tmp/nq-${PROBE_CHANNELS}-${FREQ}-${RATE}-${PCM_FORMAT}.wav}"
NQ_MCBSP_DMA_OP_MODE="${NQ_MCBSP_DMA_OP_MODE:-}"
NQ_MCBSP_MAX_TX_THRES="${NQ_MCBSP_MAX_TX_THRES:-}"
NQ_MCBSP_MAX_RX_THRES="${NQ_MCBSP_MAX_RX_THRES:-}"
APLAY_EXTRA_ARGS="${APLAY_EXTRA_ARGS:-}"
APLAY_TIMEOUT_SECONDS="${APLAY_TIMEOUT_SECONDS:-0}"
NQ_PROBE_SET_MIXER="${NQ_PROBE_SET_MIXER:-1}"
NQ_PROBE_MIXER_CARD="${NQ_PROBE_MIXER_CARD:-0}"
NQ_PROBE_MASTER_VOLUME="${NQ_PROBE_MASTER_VOLUME:-190}"
NQ_PROBE_SPEAKER_VOLUME="${NQ_PROBE_SPEAKER_VOLUME:-204}"
NQ_PROBE_SPEAKER_SWITCH="${NQ_PROBE_SPEAKER_SWITCH:-on}"
NQ_PROBE_TONE_AMP="${NQ_PROBE_TONE_AMP:-0.20}"
NQ_TAS571X_REGMAP_SAMPLE="${NQ_TAS571X_REGMAP_SAMPLE:-0}"
REQUIRE_REMOTE_CMDLINE="${REQUIRE_REMOTE_CMDLINE:-1}"
REQUIRED_REMOTE_CMDLINE_ARGS="${REQUIRED_REMOTE_CMDLINE_ARGS:-$NQ_AUDIO_DIAG_REQUIRED_ARGS}"
REQUIRED_REMOTE_MODULE_PARAMS="${REQUIRED_REMOTE_MODULE_PARAMS:-}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4"

shell_quote() {
	printf "'"
	printf '%s' "$1" | sed "s/'/'\\\\''/g"
	printf "'"
}

remote_sh_command() {
	printf 'sh -s --'
	for arg do
		printf ' %s' "$(shell_quote "$arg")"
	done
}

if [ "${LIST_AUDIO_INPUTS:-0}" = "1" ]; then
	if ! command -v ffmpeg >/dev/null 2>&1; then
		echo "ffmpeg is not installed or not in PATH" >&2
		exit 1
	fi
	ffmpeg -f avfoundation -list_devices true -i "" </dev/null || true
	exit 0
fi

if [ "${NQ_SPEAKER_CONNECTED:-0}" != "1" ]; then
	cat >&2 <<EOF
Refusing to run playback because NQ_SPEAKER_CONNECTED=1 is not set.

Reconnect the speaker, boot the legacydma image if needed, then run:

  NQ_SPEAKER_CONNECTED=1 $0

Optional:
  FASTBOOT_BOOT=1       boot $IMAGE with fastboot first
  LIST_AUDIO_INPUTS=1   list Mac ffmpeg/avfoundation capture devices and exit
  FFMPEG_INPUT=':0'     capture a Mac microphone input with ffmpeg/avfoundation
  PROBE_CHANNELS=both|left|right|diff
                         choose which PCM channels carry the test tone
  PCM_FORMAT=S16_LE|S32_LE
                         choose the generated WAV sample format
  NQ_MCBSP_DMA_OP_MODE=threshold|element
                         set McBSP DMA mode before playback
  NQ_MCBSP_MAX_TX_THRES=32
                         set McBSP TX FIFO threshold limit before playback
  APLAY_EXTRA_ARGS='--period-size=1024 --buffer-size=4096'
                         pass extra arguments to aplay
  NQ_PROBE_SET_MIXER=0   do not set ALSA mixer controls before playback
  NQ_PROBE_MASTER_VOLUME=$NQ_PROBE_MASTER_VOLUME
                         set TAS5713 master volume before playback
  NQ_PROBE_SPEAKER_VOLUME=$NQ_PROBE_SPEAKER_VOLUME
                         set TAS5713 speaker volume before playback
  NQ_PROBE_TONE_AMP=$NQ_PROBE_TONE_AMP
                         generated sine amplitude, 0.0 to 1.0 full-scale
  NQ_TAS571X_REGMAP_SAMPLE=1
                         sample TAS5713 hardware registers during playback
  NQ_HOST=$NQ_HOST      target Nexus Q SSH host
  OUTDIR=$OUTDIR        output log/capture directory
  REQUIRE_REMOTE_CMDLINE=$REQUIRE_REMOTE_CMDLINE
                         require running Nexus Q kernel cmdline diagnostics
  REQUIRED_REMOTE_MODULE_PARAMS='omap_dma:nq_dump_cyclic=1'
                         require module parameter values before playback
EOF
	exit 2
fi

case "$PROBE_CHANNELS" in
	both|left|right|diff) ;;
	*)
		echo "unsupported PROBE_CHANNELS=$PROBE_CHANNELS; expected both, left, right, or diff" >&2
		exit 2
		;;
esac
case "$PCM_FORMAT" in
	S16_LE|S32_LE) ;;
	*)
		echo "unsupported PCM_FORMAT=$PCM_FORMAT; expected S16_LE or S32_LE" >&2
		exit 2
		;;
esac

mkdir -p "$OUTDIR"

if [ "${FASTBOOT_BOOT:-0}" = "1" ]; then
	fastboot boot "$IMAGE"
fi

echo "waiting for SSH on $NQ_USER@$NQ_HOST"
i=0
while ! ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'true' >/dev/null 2>&1; do
	i=$((i + 1))
	if [ "$i" -ge 60 ]; then
		echo "timed out waiting for SSH on $NQ_HOST" >&2
		exit 1
	fi
	sleep 2
done

if [ "$REQUIRE_REMOTE_CMDLINE" = "1" ]; then
	remote_cmdline="$(ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'cat /proc/cmdline')"
	missing_args=""
	{
		echo "$remote_cmdline"
		echo
		for arg in $REQUIRED_REMOTE_CMDLINE_ARGS; do
			case " $remote_cmdline " in
				*" $arg "*) echo "ok: $arg" ;;
				*)
					echo "missing: $arg"
					missing_args="$missing_args $arg"
					;;
			esac
		done
	} > "$OUTDIR/remote-cmdline-check.txt"
	if [ -n "$missing_args" ]; then
		cat >&2 <<EOF
Refusing to run playback because the running Nexus Q kernel is missing audio
diagnostic bootargs. See:

  $OUTDIR/remote-cmdline-check.txt

Boot the current diagnostic image with FASTBOOT_BOOT=1, or set
REQUIRE_REMOTE_CMDLINE=0 only for a deliberate stale-kernel test.
EOF
		exit 2
	fi
fi

if [ -n "$REQUIRED_REMOTE_MODULE_PARAMS" ]; then
	if ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
		"$(remote_sh_command "$REQUIRED_REMOTE_MODULE_PARAMS")" \
		> "$OUTDIR/remote-module-params-check.txt" <<'REMOTE_MODULE_PARAMS'
set -eu
required="$1"
missing=""

normalize_bool() {
	case "$1" in
		1|y|Y|yes|Yes|YES|true|True|TRUE|on|On|ON) echo 1 ;;
		0|n|N|no|No|NO|false|False|FALSE|off|Off|OFF) echo 0 ;;
		*) echo "$1" ;;
	esac
}

for spec in $required; do
	module="${spec%%:*}"
	param_value="${spec#*:}"
	param="${param_value%%=*}"
	expected="${param_value#*=}"
	path="/sys/module/$module/parameters/$param"
	if [ ! -r "$path" ]; then
		echo "missing: $path"
		missing="$missing $spec"
		continue
	fi
	actual="$(cat "$path" 2>/dev/null || true)"
	expected_norm="$(normalize_bool "$expected")"
	actual_norm="$(normalize_bool "$actual")"
	if [ "$actual_norm" = "$expected_norm" ]; then
		echo "ok: $spec actual=$actual"
	else
		echo "mismatch: $spec actual=$actual"
		missing="$missing $spec"
	fi
done

[ -z "$missing" ]
REMOTE_MODULE_PARAMS
	then
		:
	else
		cat >&2 <<EOF
Refusing to run playback because the running Nexus Q modules are missing
required audio diagnostic parameters. See:

  $OUTDIR/remote-module-params-check.txt

Reload the current diagnostic modules with tools/reload_audio_modules_remote.sh.
EOF
		exit 2
	fi
fi

WAV="$OUTDIR/nq-${PROBE_CHANNELS}-${FREQ}-${RATE}-${PCM_FORMAT}.wav"
python3 - "$WAV" "$RATE" "$FREQ" "$DURATION" "$PROBE_CHANNELS" "$PCM_FORMAT" "$NQ_PROBE_TONE_AMP" <<'PY'
import math
import struct
import sys
import wave

path = sys.argv[1]
rate = int(sys.argv[2])
freq = float(sys.argv[3])
duration = float(sys.argv[4])
channels = sys.argv[5]
pcm_format = sys.argv[6]
amp = float(sys.argv[7])
if not 0.0 <= amp <= 1.0:
    raise SystemExit(f"unsupported tone amplitude: {amp}")
frames = int(rate * duration)
if pcm_format == "S16_LE":
    sampwidth = 2
    sample_max = 32767.0
    pack = "<hh"
elif pcm_format == "S32_LE":
    sampwidth = 4
    sample_max = 2147483647.0
    pack = "<ii"
else:
    raise SystemExit(f"unsupported PCM format: {pcm_format}")
with wave.open(path, "wb") as wav:
    wav.setnchannels(2)
    wav.setsampwidth(sampwidth)
    wav.setframerate(rate)
    for n in range(frames):
        sample = int(amp * sample_max * math.sin(2.0 * math.pi * freq * n / rate))
        left = sample if channels in ("both", "left", "diff") else 0
        right = -sample if channels == "diff" else (
            sample if channels in ("both", "right") else 0
        )
        wav.writeframesraw(struct.pack(pack, left, right))
PY

SOURCE_ANALYSIS_ARGS=""
if [ "$PROBE_CHANNELS" = "diff" ]; then
	SOURCE_ANALYSIS_ARGS="--wav-channel left"
fi

# shellcheck disable=SC2086 # SOURCE_ANALYSIS_ARGS is an optional flag pair.
python3 "$ROOT/tools/analyze_audio_probe_capture.py" $SOURCE_ANALYSIS_ARGS --expected "$FREQ" "$WAV" \
	> "$OUTDIR/source-wav-analysis.txt"
# shellcheck disable=SC2086 # SOURCE_ANALYSIS_ARGS is an optional flag pair.
python3 "$ROOT/tools/analyze_audio_probe_capture.py" $SOURCE_ANALYSIS_ARGS --json --expected "$FREQ" "$WAV" \
	> "$OUTDIR/source-wav-analysis.json"

scp $SSH_OPTS "$WAV" "$NQ_USER@$NQ_HOST:$REMOTE_WAV" >/dev/null

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
	"$(remote_sh_command "$NQ_MCBSP_DMA_OP_MODE" "$NQ_MCBSP_MAX_TX_THRES" "$NQ_MCBSP_MAX_RX_THRES")" \
	> "$OUTDIR/mcbsp-sysfs-config.txt" <<'REMOTE_MCBSP_CONFIG'
set -eu
dma_op_mode="$1"
max_tx_thres="$2"
max_rx_thres="$3"

set_attr() {
	name="$1"
	value="$2"
	[ -n "$value" ] || return 0
	matches="$(find /sys/devices -type f -name "$name" 2>/dev/null | sort)"
	if [ -z "$matches" ]; then
		echo "missing requested McBSP sysfs attribute: $name" >&2
		return 1
	fi
	find /sys/devices -type f -name "$name" 2>/dev/null |
		sort |
		while read -r f; do
			echo "--- write $f = $value"
			printf '%s\n' "$value" > "$f"
			echo "--- read $f"
			cat "$f" 2>/dev/null || true
		done
}

set_attr dma_op_mode "$dma_op_mode"
set_attr max_tx_thres "$max_tx_thres"
set_attr max_rx_thres "$max_rx_thres"
REMOTE_MCBSP_CONFIG

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
	"$(remote_sh_command "$NQ_PROBE_SET_MIXER" "$NQ_PROBE_MIXER_CARD" "$NQ_PROBE_MASTER_VOLUME" "$NQ_PROBE_SPEAKER_VOLUME" "$NQ_PROBE_SPEAKER_SWITCH")" \
	> "$OUTDIR/mixer-state.txt" <<'REMOTE_MIXER'
set -eu
set_mixer="$1"
card="$2"
master_volume="$3"
speaker_volume="$4"
speaker_switch="$5"

echo "requested:"
echo "  set_mixer=$set_mixer"
echo "  card=$card"
echo "  master_volume=$master_volume"
echo "  speaker_volume=$speaker_volume"
echo "  speaker_switch=$speaker_switch"

if ! command -v amixer >/dev/null 2>&1; then
	echo "amixer missing"
	exit 0
fi

echo
echo "before:"
amixer -c "$card" contents 2>/dev/null || true

if [ "$set_mixer" = "1" ]; then
	case "$speaker_volume" in
		*,*) ;;
		*) speaker_volume="$speaker_volume,$speaker_volume" ;;
	esac
	amixer -q -c "$card" cset name="Speaker Switch" "$speaker_switch" || true
	amixer -q -c "$card" cset name="Speaker Volume" "$speaker_volume" || true
	amixer -q -c "$card" cset name="Master Volume" "$master_volume" || true
fi

echo
echo "after:"
amixer -c "$card" contents 2>/dev/null || true
REMOTE_MIXER

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
	'uname -a; echo; cat /proc/cmdline; echo; cat /proc/asound/cards; echo; cat /proc/asound/pcm; echo; aplay -l 2>/dev/null || true; echo; amixer -c 0 scontents 2>/dev/null || true' \
	> "$OUTDIR/preflight.txt"

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'cat /proc/interrupts' \
	> "$OUTDIR/interrupts-before.txt"

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" '
	for dir in \
		/sys/module/omap_dma/parameters \
		/sys/module/snd_soc_ti_sdma/parameters \
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

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" '
	find /sys/devices -type f \( -name dma_op_mode -o -name max_tx_thres -o -name max_rx_thres \) 2>/dev/null |
		sort |
		while read -r f; do
			echo "--- $f"
			cat "$f" 2>/dev/null || true
		done
' > "$OUTDIR/mcbsp-sysfs-before.txt"

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'dmesg | tail -n 250' > "$OUTDIR/dmesg-before.txt"

ffmpeg_pid=""
if [ -n "${FFMPEG_INPUT:-}" ]; then
	ffmpeg -y -f avfoundation -i "$FFMPEG_INPUT" -t "$((DURATION + 2))" "$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/ffmpeg.log" 2>&1 &
	ffmpeg_pid="$!"
	sleep 1
fi

set +e
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
	"$(remote_sh_command "$REMOTE_WAV" "$APLAY_EXTRA_ARGS" "$NQ_TAS571X_REGMAP_SAMPLE" "$APLAY_TIMEOUT_SECONDS")" \
	> "$OUTDIR/aplay.log" 2>&1 <<'REMOTE_APLAY'
set -eu
remote_wav="$1"
aplay_extra_args="$2"
tas571x_regmap_sample="$3"
aplay_timeout_seconds="$4"
echo "starting aplay: $remote_wav"
echo "aplay_timeout_seconds=$aplay_timeout_seconds"
echo "=== live dmesg during playback ==="
if dmesg --help 2>&1 | grep -q -- '--follow-new'; then
	dmesg --follow-new 2>/dev/null &
else
	dmesg -w 2>/dev/null &
fi
dmesg_watch_pid="$!"
trap 'kill "$dmesg_watch_pid" 2>/dev/null || true' EXIT INT TERM
sleep 0.2
if [ "$aplay_timeout_seconds" -gt 0 ]; then
	timeout "$aplay_timeout_seconds" aplay -D hw:0,0 -q $aplay_extra_args "$remote_wav" &
else
	aplay -D hw:0,0 -q $aplay_extra_args "$remote_wav" &
fi
pid="$!"

pcm_status_file() {
	find /proc/asound -path '*/pcm*p/sub*/status' -type f 2>/dev/null |
		sort |
		head -n 1
}

pcm_state() {
	status_file="$(pcm_status_file)"
	[ -n "$status_file" ] || return 0
	sed -n 's/^state:[[:space:]]*//p' "$status_file" 2>/dev/null | head -n 1
}

dump_pcm_snapshot() {
	label="$1"
	find /proc/asound \( -path '*/pcm*p/sub*/hw_params' -o -path '*/pcm*p/sub*/status' \) -type f 2>/dev/null |
		sort |
		while read -r f; do
			echo "--- $f sample=$label"
			cat "$f" 2>/dev/null || true
		done
}

dump_pcm_status_sample() {
	label="$1"
	find /proc/asound -path '*/pcm*p/sub*/status' -type f 2>/dev/null |
		sort |
		while read -r f; do
			echo "--- $f sample=$label"
			cat "$f" 2>/dev/null || true
		done
}

dump_interrupt_snapshot() {
	label="$1"
	echo "--- /proc/interrupts sample=$label"
	cat /proc/interrupts 2>/dev/null || true
}

dump_tas571x_regmap_sample() {
	label="$1"
	dir="$(find /sys/kernel/debug/regmap -maxdepth 1 -type d -name '*-001b' 2>/dev/null | sort | head -n 1)"
	if [ -z "$dir" ]; then
		echo "--- tas571x-regmap sample=$label missing"
		return 0
	fi

	echo "--- $dir sample=$label"
	if [ -w "$dir/cache_bypass" ]; then
		printf '1\n' > "$dir/cache_bypass" 2>/dev/null || true
		printf 'cache_bypass='
		cat "$dir/cache_bypass" 2>/dev/null || true
	fi
	if [ -r "$dir/registers" ]; then
		awk '
			/^(00|02|03|04|05|06|07|08|09|1b|1c):/ { print }
		' "$dir/registers" 2>/dev/null || true
	fi
}

last_state=""
attempt=0
while [ "$attempt" -lt 60 ]; do
	last_state="$(pcm_state || true)"
	if [ "$last_state" = "RUNNING" ]; then
		break
	fi
	if ! kill -0 "$pid" 2>/dev/null; then
		break
	fi
	attempt=$((attempt + 1))
	sleep 0.1
done
echo "pcm_status_wait_state=${last_state:-missing} attempts=$attempt"
echo
echo "=== ALSA status during playback ==="
dump_pcm_snapshot initial
echo
echo "=== interrupt snapshot during playback ==="
dump_interrupt_snapshot initial
echo
if [ "$tas571x_regmap_sample" = "1" ]; then
	echo "=== TAS5713 regmap hardware samples during playback ==="
	sample=0
	while [ "$sample" -lt 30 ]; do
		if ! kill -0 "$pid" 2>/dev/null; then
			break
		fi
		dump_tas571x_regmap_sample "$sample"
		sample=$((sample + 1))
		sleep 0.1
	done
	echo
fi
echo "=== ALSA status samples during playback ==="
sample=0
while [ "$sample" -lt 8 ]; do
	if ! kill -0 "$pid" 2>/dev/null; then
		break
	fi
	dump_pcm_status_sample "$sample"
	sample=$((sample + 1))
	sleep 0.25
done
echo
echo "=== interrupt samples during playback ==="
sample=0
while [ "$sample" -lt 8 ]; do
	if ! kill -0 "$pid" 2>/dev/null; then
		break
	fi
	dump_interrupt_snapshot "$sample"
	sample=$((sample + 1))
	sleep 0.25
done
echo
echo "=== McBSP sysfs during playback ==="
find /sys/devices -type f \( -name dma_op_mode -o -name max_tx_thres -o -name max_rx_thres \) 2>/dev/null |
	sort |
	while read -r f; do
		echo "--- $f"
		cat "$f" 2>/dev/null || true
	done
echo
echo "=== dmesg tail during playback ==="
dmesg | tail -n 80
set +e
wait "$pid"
status="$?"
set -e
echo "aplay_exit=$status"
exit "$status"
REMOTE_APLAY
aplay_status="$?"
set -e

if [ -n "$ffmpeg_pid" ]; then
	wait "$ffmpeg_pid" || true
fi

if [ -s "$OUTDIR/mic-capture.m4a" ]; then
	python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" "$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/mic-capture-analysis.txt" 2> "$OUTDIR/mic-capture-analysis.err" || true
	python3 "$ROOT/tools/analyze_audio_probe_capture.py" --json --expected "$FREQ" "$OUTDIR/mic-capture.m4a" \
		> "$OUTDIR/mic-capture-analysis.json" 2>> "$OUTDIR/mic-capture-analysis.err" || true
fi

ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'cat /proc/interrupts' \
	> "$OUTDIR/interrupts-after.txt"
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'dmesg | tail -n 400' > "$OUTDIR/dmesg-after.txt"
python3 - "$OUTDIR/dmesg-before.txt" "$OUTDIR/dmesg-after.txt" \
	> "$OUTDIR/dmesg-delta.txt" <<'PY'
import re
import sys

before_path, after_path = sys.argv[1:3]
stamp_re = re.compile(r"^\[\s*(\d+(?:\.\d+)?)\]")

with open(before_path, "r", encoding="utf-8", errors="replace") as f:
    before = f.read().splitlines()
with open(after_path, "r", encoding="utf-8", errors="replace") as f:
    after = f.read().splitlines()

before_set = set(before)
last_before = None
for line in before:
    match = stamp_re.match(line)
    if match:
        last_before = float(match.group(1))

if last_before is None:
    for line in after:
        if line not in before_set:
            print(line)
    raise SystemExit

for line in after:
    match = stamp_re.match(line)
    if not match:
        if line not in before_set:
            print(line)
        continue
    stamp = float(match.group(1))
    if stamp > last_before or (stamp == last_before and line not in before_set):
        print(line)
PY
rg -n "nq cyclic|nq steelhead|omap-dma|omap-mcbsp|mcbsp|tas571|TAS571|ALSA|XR?UN|underrun|overrun|error" \
	"$OUTDIR/dmesg-delta.txt" > "$OUTDIR/audio-kernel-events.txt" || true
rg -n "nq cyclic|nq dma-|nq tas571x|nq steelhead|nq mcbsp|McBSP|DRR[12]|DXR[12]|SPCR[12]|RCR[12]|XCR[12]|SRGR[12]|PCR0|XCCR|RCCR|THRSH[12]|IRQEN|IRQST|XBUFFSTAT|RBUFFSTAT|XUNDFL|RUNDFL|XSYNC|RSYNC" \
	"$OUTDIR/dmesg-delta.txt" > "$OUTDIR/audio-register-events.txt" || true

{
	echo "result:"
	echo "  aplay_status=$aplay_status"
	echo "probe:"
	echo "  channels=$PROBE_CHANNELS"
	echo "  pcm_format=$PCM_FORMAT"
	echo "  freq=$FREQ"
	echo "  rate=$RATE"
	echo "  duration=$DURATION"
	echo "  tone_amp=$NQ_PROBE_TONE_AMP"
	echo "source:"
	sed 's/^/  /' "$OUTDIR/source-wav-analysis.txt"
	if [ -s "$OUTDIR/mic-capture-analysis.txt" ]; then
		echo "mic:"
		sed 's/^/  /' "$OUTDIR/mic-capture-analysis.txt"
	fi
	echo "mcbsp_config:"
	sed 's/^/  /' "$OUTDIR/mcbsp-sysfs-config.txt"
	echo "mcbsp_sysfs:"
	sed 's/^/  /' "$OUTDIR/mcbsp-sysfs-before.txt"
	echo "mixer:"
	sed 's/^/  /' "$OUTDIR/mixer-state.txt"
	echo "kernel_events:"
	sed 's/^/  /' "$OUTDIR/audio-kernel-events.txt"
} > "$OUTDIR/audio-summary.txt"

echo "aplay_status=$aplay_status" | tee "$OUTDIR/result.txt"
echo "wrote $OUTDIR"
exit "$aplay_status"
