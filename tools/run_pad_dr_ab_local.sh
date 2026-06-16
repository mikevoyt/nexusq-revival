#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NQ_HOST="${NQ_HOST:-169.254.42.2}"
NQ_USER="${NQ_USER:-root}"
OUTDIR="${OUTDIR:-$ROOT/artifacts/audio-rootcause-linux66-pad-dr-ab-$(date +%Y%m%d-%H%M%S)}"
EXPECTED="${EXPECTED:-512}"
DURATION="${DURATION:-10}"
CAPTURE_DURATION="${CAPTURE_DURATION:-13}"
PERIOD_SIZE="${PERIOD_SIZE:-6000}"
BUFFER_SIZE="${BUFFER_SIZE:-24000}"
TONE_AMP="${TONE_AMP:-4096}"
FFMPEG_INPUT="${FFMPEG_INPUT:-:0}"

SSH_OPTS=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=10
)

mkdir -p "$OUTDIR"

remote() {
  ssh "${SSH_OPTS[@]}" "$NQ_USER@$NQ_HOST" "$@"
}

capture_pad_state() {
  local phase="$1"
  remote '
    for off in 0x19a 0x0f6 0x0f8 0x0fa 0x0fc; do
      addr=$(printf 0x%08x $((0x4a100000 + off)))
      printf "%s %s " "$off" "$addr"
      busybox devmem "$addr" 16 2>&1 || true
    done
  ' > "$OUTDIR/pads-${phase}.txt" 2>&1
}

run_capture() {
  local name="$1"
  local padval="$2"
  local wav="$OUTDIR/${name}.wav"

  remote "
    busybox devmem 0x4a1000f8 16 $padval
    printf $PERIOD_SIZE >/sys/module/snd_soc_steelhead_tas5713/parameters/nq_period_size
    printf 4 >/sys/module/snd_soc_steelhead_tas5713/parameters/nq_periods
    printf 1 >/sys/module/omap_dma/parameters/nq_audio_tone
    printf $EXPECTED >/sys/module/omap_dma/parameters/nq_audio_tone_freq
    printf $TONE_AMP >/sys/module/omap_dma/parameters/nq_audio_tone_amp
    printf 0 >/sys/module/omap_dma/parameters/nq_audio_tone_channel
    printf 'pad='
    busybox devmem 0x4a1000f8 16
  " > "$OUTDIR/${name}-setup.txt" 2>&1

  ffmpeg -nostdin -hide_banner -loglevel error \
    -f avfoundation -i "$FFMPEG_INPUT" \
    -t "$CAPTURE_DURATION" -ac 1 -ar 48000 -sample_fmt s16 "$wav" \
    > "$OUTDIR/${name}-ffmpeg.out" \
    2> "$OUTDIR/${name}-ffmpeg.err" &
  local ffmpeg_pid=$!

  sleep 1.2
  remote "
    aplay -D hw:0,0 -q -f S16_LE -c 2 -r 48000 \
      --period-size=$PERIOD_SIZE --buffer-size=$BUFFER_SIZE \
      -d $DURATION /dev/zero
    echo aplay_status=\$?
    for r in 0x02 0x04 0x05 0x06 0x07 0x08 0x09; do
      printf '%s=' \"\$r\"
      i2cget -f -y 3 0x1b \"\$r\" || true
    done
  " > "$OUTDIR/${name}.log" 2>&1

  wait "$ffmpeg_pid"

  python3 "$ROOT/tools/analyze_audio_probe_capture.py" \
    --expected "$EXPECTED" --json "$wav" > "$OUTDIR/${name}-analysis.json"
  python3 "$ROOT/tools/analyze_audio_probe_capture.py" \
    --expected "$EXPECTED" "$wav" > "$OUTDIR/${name}-analysis.txt"
}

remote '/sbin/nq-autoreboot-cancel 2>/dev/null || true; ip link set wlan0 down 2>/dev/null || true; true' \
  > "$OUTDIR/prep.txt" 2>&1

capture_pad_state before
run_capture baseline-dr0108 0x0108
run_capture vendor-dr0002 0x0002

remote '
  busybox devmem 0x4a1000f8 16 0x0108
  for off in 0x19a 0x0f6 0x0f8 0x0fa 0x0fc; do
    addr=$(printf 0x%08x $((0x4a100000 + off)))
    printf "%s %s " "$off" "$addr"
    busybox devmem "$addr" 16 2>&1 || true
  done
' > "$OUTDIR/pads-after-restore.txt" 2>&1

python3 - "$OUTDIR" <<'PY'
import json
import pathlib
import sys

outdir = pathlib.Path(sys.argv[1])
for name in ("baseline-dr0108", "vendor-dr0002"):
    data = json.loads((outdir / f"{name}-analysis.json").read_text())
    print(
        name,
        "cv=", data.get("envelope_cv_25ms"),
        "p2t=", data.get("envelope_peak_to_trough_db_25ms"),
        "mod=", data.get("envelope_mod_peak_hz_25ms"),
        "rms=", data.get("rms"),
    )
print(f"ART={outdir}")
PY
