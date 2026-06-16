#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
OUTDIR="${OUTDIR:-$ROOT/artifacts/audio-rootcause-linux66-compare-$(date +%Y%m%d-%H%M%S)}"
RATE="${RATE:-48000}"
FREQ="${FREQ:-440}"
DURATION="${DURATION:-20}"
TONE_AMP="${TONE_AMP:-0.02}"
PCM_SOURCE_MODE="${PCM_SOURCE_MODE:-normal}"
REMOTE_WAV="${REMOTE_WAV:-/tmp/nq-linux66-left-${FREQ}-${RATE}.wav}"
NQ_PROBE_MASTER_VOLUME="${NQ_PROBE_MASTER_VOLUME:-180}"
NQ_PROBE_SPEAKER_VOLUME="${NQ_PROBE_SPEAKER_VOLUME:-180}"
APLAY_EXTRA_ARGS="${APLAY_EXTRA_ARGS:-}"
FFMPEG_INPUT="${FFMPEG_INPUT:-}"
PCM_STATUS_INTERVAL="${PCM_STATUS_INTERVAL:-0.10}"
PCM_STATUS_SAMPLES="${PCM_STATUS_SAMPLES:-$((DURATION * 10 + 30))}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10}"
SCP_OPTS="${SCP_OPTS:--o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10}"

mkdir -p "$OUTDIR"
WAV="$OUTDIR/source-nq-left-${FREQ}-${RATE}-S16_LE.wav"
INTENDED_WAV="$OUTDIR/intended-output-nq-left-${FREQ}-${RATE}-S16_LE.wav"

case "$PCM_SOURCE_MODE" in
  normal|byteswap16-safe) ;;
  *)
    echo "unsupported PCM_SOURCE_MODE=$PCM_SOURCE_MODE; expected normal or byteswap16-safe" >&2
    exit 2
    ;;
esac

python3 - "$WAV" "$INTENDED_WAV" "$RATE" "$FREQ" "$DURATION" "$TONE_AMP" "$PCM_SOURCE_MODE" <<'PY'
import math
import struct
import sys
import wave

path = sys.argv[1]
intended_path = sys.argv[2]
rate = int(sys.argv[3])
freq = float(sys.argv[4])
duration = float(sys.argv[5])
amp = float(sys.argv[6])
mode = sys.argv[7]
frames = int(rate * duration)

def s16(value):
    value &= 0xffff
    return value - 0x10000 if value & 0x8000 else value

def bswap16_signed(value):
    value &= 0xffff
    return s16(((value & 0x00ff) << 8) | ((value & 0xff00) >> 8))

def quantize_256(value):
    return max(-32768, min(32767, int(round(value / 256.0)) * 256))

with wave.open(path, "wb") as wav:
    wav.setnchannels(2)
    wav.setsampwidth(2)
    wav.setframerate(rate)
    intended = wave.open(intended_path, "wb") if mode == "byteswap16-safe" else None
    if intended:
        intended.setnchannels(2)
        intended.setsampwidth(2)
        intended.setframerate(rate)
    try:
        for n in range(frames):
            sample = int(amp * 32767.0 * math.sin(2.0 * math.pi * freq * n / rate))
            if mode == "byteswap16-safe":
                target = quantize_256(sample)
                wav.writeframesraw(struct.pack("<hh", bswap16_signed(target), 0))
                intended.writeframesraw(struct.pack("<hh", target, 0))
            else:
                wav.writeframesraw(struct.pack("<hh", sample, 0))
    finally:
        if intended:
            intended.close()
PY

python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" "$WAV" \
  > "$OUTDIR/source-wav-analysis.txt"
if [ "$PCM_SOURCE_MODE" = "byteswap16-safe" ]; then
  python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" "$INTENDED_WAV" \
    > "$OUTDIR/intended-output-analysis.txt"
fi
shasum -a 256 "$WAV" > "$OUTDIR/source-wav.sha256"
if [ "$PCM_SOURCE_MODE" = "byteswap16-safe" ]; then
  shasum -a 256 "$INTENDED_WAV" > "$OUTDIR/intended-output.sha256"
fi

cat > "$OUTDIR/run-info.txt" <<EOF_RUN_INFO
host: $NQ_HOST
user: $NQ_USER
remote_wav: $REMOTE_WAV
rate: $RATE
freq: $FREQ
duration: $DURATION
tone_amp: $TONE_AMP
pcm_source_mode: $PCM_SOURCE_MODE
master_volume: $NQ_PROBE_MASTER_VOLUME
speaker_volume: $NQ_PROBE_SPEAKER_VOLUME
aplay_extra_args: $APLAY_EXTRA_ARGS
ffmpeg_input: $FFMPEG_INPUT
pcm_status_interval: $PCM_STATUS_INTERVAL
pcm_status_samples: $PCM_STATUS_SAMPLES
outdir: $OUTDIR
date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
purpose: Linux 6.6 comparison capture against Linux 3.0 McBSP2/SDMA baseline
EOF_RUN_INFO

sample_pcm_status() {
  ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
    "sh -s -- '$PCM_STATUS_SAMPLES' '$PCM_STATUS_INTERVAL'" \
    > "$OUTDIR/pcm-status-samples.txt" <<'REMOTE_SH'
samples="$1"
interval="$2"
i=0
while [ "$i" -lt "$samples" ]; do
  echo "=== sample $i time $(date +%s.%N 2>/dev/null || date +%s) ==="
  for f in \
    /proc/asound/card0/pcm0p/sub0/status \
    /proc/asound/card0/pcm0p/sub0/hw_params \
    /proc/asound/card0/pcm0p/sub0/sw_params
  do
    echo "--- $f ---"
    cat "$f" 2>&1 || true
  done
  i=$((i + 1))
  sleep "$interval" 2>/dev/null || sleep 1
done
REMOTE_SH
}

remote_capture() {
  local phase="$1"
  ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" "sh -s -- '$phase'" > "$OUTDIR/remote-${phase}.txt" <<'REMOTE_SH'
phase="$1"
set +e
mount -t debugfs debugfs /sys/kernel/debug >/dev/null 2>&1 || true

if command -v busybox >/dev/null 2>&1; then
  devmem_cmd="busybox devmem"
elif command -v devmem >/dev/null 2>&1; then
  devmem_cmd="devmem"
else
  devmem_cmd=""
fi

read_reg32() {
  addr="$1"
  if [ -z "$devmem_cmd" ]; then
    echo "no devmem command"
  else
    $devmem_cmd "$addr" 32 2>&1 || true
  fi
}

echo "=== phase: $phase ==="

echo "=== identity ==="
uname -a
cat /proc/cmdline 2>/dev/null

echo "=== alsa ==="
cat /proc/asound/cards 2>/dev/null
cat /proc/asound/pcm 2>/dev/null
aplay -l 2>/dev/null || true
amixer -c 0 contents 2>/dev/null || true

echo "=== live-device-path ==="
find /sys/devices -iname '*mcbsp*' -o -iname '*tas571*' 2>/dev/null | sort
echo "--- sound-tas5713 google,mcbsp ---"
od -An -tx4 /sys/firmware/devicetree/base/sound-tas5713/google,mcbsp 2>/dev/null || true
echo "--- mcbsp2 dmas ---"
od -An -tx4 /sys/firmware/devicetree/base/ocp/interconnect@40100000/segment@0/target-module@24000/mcbsp@0/dmas 2>/dev/null || true

echo "=== module-parameters ==="
for dir in \
  /sys/module/omap_dma/parameters \
  /sys/module/snd_soc_omap_mcbsp/parameters \
  /sys/module/snd_soc_tas571x/parameters \
  /sys/module/snd_soc_steelhead_tas5713/parameters
do
  if [ -d "$dir" ]; then
    echo "--- $dir ---"
    for p in "$dir"/*; do
      [ -r "$p" ] || continue
      printf '%s=' "$(basename "$p")"
      cat "$p"
    done
  fi
done

echo "=== interrupts-interest ==="
cat /proc/interrupts 2>/dev/null | grep -Ei 'mcbsp|dma|sdma|tas|i2c| 22:| 17:' || true

echo "=== clocks-interest ==="
if [ -r /sys/kernel/debug/clk/clk_summary ]; then
  grep -Ei 'mcbsp2|auxclk|abe_24|dpll_per|sys_32k|abe-clkctrl:0018' /sys/kernel/debug/clk/clk_summary || true
fi
for f in \
  /sys/kernel/debug/clk/auxclk1_ck/clk_rate \
  /sys/kernel/debug/clk/dpll_per_m3x2_ck/clk_rate \
  /sys/kernel/debug/clk/abe_24m_fclk/clk_rate \
  /sys/kernel/debug/clk/abe-clkctrl:0018:24/clk_rate \
  /sys/kernel/debug/clk/abe-clkctrl:0018:26/clk_rate
do
  if [ -r "$f" ]; then
    printf '%s=' "$f"
    cat "$f"
  fi
done

echo "=== asoc-debugfs ==="
cat /sys/kernel/debug/asoc/components 2>/dev/null || true
cat /sys/kernel/debug/asoc/dais 2>/dev/null || true
cat "/sys/kernel/debug/asoc/Steelhead TAS5713/dapm/bias_level" 2>/dev/null || true

echo "=== tas5713-regmap ==="
for f in /sys/kernel/debug/regmap/*/registers /sys/kernel/debug/regmap/*/range; do
  case "$f" in
    *3-001b*|*tas*) ;;
    *) continue ;;
  esac
  [ -r "$f" ] || continue
  echo "--- $f ---"
  cat "$f" | sed -n '1,180p'
done

echo "=== mcbsp2-devmem-mpu-0x40124000 ==="
mcbsp_base=$((0x40124000))
for entry in \
  "SPCR2 0x10" \
  "SPCR1 0x14" \
  "RCR2 0x18" \
  "RCR1 0x1c" \
  "XCR2 0x20" \
  "XCR1 0x24" \
  "SRGR2 0x28" \
  "SRGR1 0x2c" \
  "PCR0 0x48" \
  "SYSCON 0x8c" \
  "THRSH2 0x90" \
  "THRSH1 0x94" \
  "IRQST 0xa0" \
  "IRQEN 0xa4" \
  "XCCR 0xac" \
  "RCCR 0xb0" \
  "XBUFFSTAT 0xb4" \
  "RBUFFSTAT 0xb8"
do
  set -- $entry
  name="$1"
  off="$2"
  addr=$(printf '0x%08x' $((mcbsp_base + off)))
  printf '%-10s %-10s ' "$name" "$addr"
  read_reg32 "$addr"
done

echo "=== sdma-active-channels-0x4a056000 ==="
sdma_base=$((0x4a056000))
ch=0
while [ "$ch" -lt 32 ]; do
  chan_base=$((sdma_base + 0x80 + ch * 0x60))
  ccr_addr=$(printf '0x%08x' "$chan_base")
  ccr=$(read_reg32 "$ccr_addr")
  if [ "$ccr" != "0x00000000" ] && [ "$ccr" != "no devmem command" ]; then
    echo "--- channel $ch base $ccr_addr CCR=$ccr ---"
    for entry in \
      "CLNK 0x04" \
      "CICR 0x08" \
      "CSR 0x0c" \
      "CSDP 0x10" \
      "CEN 0x14" \
      "CFN 0x18" \
      "CSSA 0x1c" \
      "CDSA 0x20" \
      "CSEI 0x24" \
      "CSFI 0x28" \
      "CDEI 0x2c" \
      "CDFI 0x30" \
      "CSAC 0x34" \
      "CDAC 0x38" \
      "CCEN 0x3c" \
      "CCFN 0x40"
    do
      set -- $entry
      name="$1"
      off="$2"
      addr=$(printf '0x%08x' $((chan_base + off)))
      printf '%-6s %-10s ' "$name" "$addr"
      read_reg32 "$addr"
    done
  fi
  ch=$((ch + 1))
done
REMOTE_SH
}

echo "Waiting for SSH on $NQ_USER@$NQ_HOST"
for _ in $(seq 1 30); do
  if ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" true >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

scp $SCP_OPTS "$WAV" "$NQ_USER@$NQ_HOST:$REMOTE_WAV"

echo "Capturing pre-playback state into $OUTDIR"
remote_capture pre

echo "Setting low playback mixer volume"
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
  "amixer -q -c 0 cset name='Speaker Switch' on || true; \
   amixer -q -c 0 cset name='Speaker Volume' '$NQ_PROBE_SPEAKER_VOLUME,$NQ_PROBE_SPEAKER_VOLUME' || true; \
   amixer -q -c 0 cset name='Master Volume' '$NQ_PROBE_MASTER_VOLUME' || true; \
   amixer -c 0 contents" \
  > "$OUTDIR/remote-mixer-set.txt" 2>&1

mic_pid=""
if [ -n "$FFMPEG_INPUT" ]; then
  echo "Starting Mac microphone capture from $FFMPEG_INPUT"
  ffmpeg -hide_banner -nostdin -y -f avfoundation -i "$FFMPEG_INPUT" \
    -t "$DURATION" "$OUTDIR/mic-capture.m4a" \
    > "$OUTDIR/ffmpeg-mic.log" 2>&1 &
  mic_pid=$!
  sleep 0.5
fi

echo "Starting low-amplitude aplay on $NQ_HOST"
ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" \
  "aplay -D hw:0,0 -q $APLAY_EXTRA_ARGS '$REMOTE_WAV'; echo aplay_status=\$?" \
  > "$OUTDIR/aplay.log" 2>&1 &
aplay_pid=$!

sample_pcm_status &
pcm_status_pid=$!

sleep 1
echo "Capturing during-playback state into $OUTDIR"
remote_capture during

wait "$aplay_pid" || true
wait "$pcm_status_pid" || true
if [ -n "$mic_pid" ]; then
  wait "$mic_pid" || true
  if [ -s "$OUTDIR/mic-capture.m4a" ]; then
    python3 "$ROOT/tools/analyze_audio_probe_capture.py" --expected "$FREQ" \
      "$OUTDIR/mic-capture.m4a" > "$OUTDIR/mic-capture-analysis.txt" || true
  fi
fi

echo "Capturing post-playback state into $OUTDIR"
remote_capture after

echo "capture complete: $OUTDIR"
