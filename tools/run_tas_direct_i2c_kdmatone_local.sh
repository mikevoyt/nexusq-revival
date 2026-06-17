#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NQ_HOST="${NQ_HOST:-169.254.42.2}"
NQ_USER="${NQ_USER:-root}"
OUTDIR="${OUTDIR:-$ROOT/artifacts/audio-rootcause-linux66-tas-direct-i2c-kdmatone-$(date +%Y%m%d-%H%M%S)}"
EXPECTED="${EXPECTED:-512}"
DURATION="${DURATION:-10}"
CAPTURE_DURATION="${CAPTURE_DURATION:-13}"
PERIOD_SIZE="${PERIOD_SIZE:-6000}"
BUFFER_SIZE="${BUFFER_SIZE:-24000}"
TONE_AMP="${TONE_AMP:-4096}"
TONE_NO_IRQ="${TONE_NO_IRQ:-0}"
TONE_FAKE_PERIOD="${TONE_FAKE_PERIOD:-0}"
MASTER_VOLUME="${MASTER_VOLUME:-80}"
SPEAKER_VOLUME="${SPEAKER_VOLUME:-207}"
I2C_POLL="${I2C_POLL:-1}"
MCBSP_WAKEUPEN_DURING="${MCBSP_WAKEUPEN_DURING:-}"
LIVE_POLL="${LIVE_POLL:-0}"
LIVE_POLL_MS="${LIVE_POLL_MS:-200}"
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

remote '
  /sbin/nq-autoreboot-cancel 2>/dev/null || true
  ip link set wlan0 down 2>/dev/null || true
  mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
  true
' > "$OUTDIR/prep.txt" 2>&1

remote "
  set -eu
  printf $PERIOD_SIZE >/sys/module/snd_soc_steelhead_tas5713/parameters/nq_period_size
  printf 4 >/sys/module/snd_soc_steelhead_tas5713/parameters/nq_periods
  amixer -q -c 0 cset name='Speaker Switch' on || true
  amixer -q -c 0 cset name='Speaker Volume' $SPEAKER_VOLUME,$SPEAKER_VOLUME || true
  amixer -q -c 0 cset name='Master Volume' $MASTER_VOLUME || true
  printf 1 >/sys/module/omap_dma/parameters/nq_audio_tone
  printf $EXPECTED >/sys/module/omap_dma/parameters/nq_audio_tone_freq
  printf $TONE_AMP >/sys/module/omap_dma/parameters/nq_audio_tone_amp
  printf 0 >/sys/module/omap_dma/parameters/nq_audio_tone_channel
  printf $TONE_NO_IRQ >/sys/module/omap_dma/parameters/nq_audio_tone_no_irq
  if [ -e /sys/module/omap_dma/parameters/nq_audio_tone_fake_period ]; then
    printf $TONE_FAKE_PERIOD >/sys/module/omap_dma/parameters/nq_audio_tone_fake_period
  elif [ "$TONE_FAKE_PERIOD" != 0 ]; then
    echo "missing /sys/module/omap_dma/parameters/nq_audio_tone_fake_period" >&2
    exit 1
  fi
  printf 'configured period_size='
  cat /sys/module/snd_soc_steelhead_tas5713/parameters/nq_period_size
  printf 'configured tone_freq='
  cat /sys/module/omap_dma/parameters/nq_audio_tone_freq
  printf 'configured tone_amp='
  cat /sys/module/omap_dma/parameters/nq_audio_tone_amp
  printf 'configured tone_no_irq='
  cat /sys/module/omap_dma/parameters/nq_audio_tone_no_irq
  printf 'configured tone_fake_period='
  if [ -e /sys/module/omap_dma/parameters/nq_audio_tone_fake_period ]; then
    cat /sys/module/omap_dma/parameters/nq_audio_tone_fake_period
  else
    printf 'missing\n'
  fi
  printf 'configured mixer='
  amixer -c 0 sget Master 2>/dev/null | grep Mono: || true
  amixer -c 0 sget Speaker 2>/dev/null | grep 'Front Left:' || true
" > "$OUTDIR/setup.txt" 2>&1

remote '
  echo "=== clock summary before ==="
  grep -E "(mcbsp|abe_24m|auxclk1|dpll_per_m3x2)" /sys/kernel/debug/clk/clk_summary || true
  echo "=== tas low before ==="
  for r in 0x00 0x01 0x02 0x03 0x04 0x05 0x06 0x07 0x08 0x09 0x0a 0x1c; do
    printf "%s=" "$r"
    i2cget -f -y 3 0x1b "$r" || true
  done
' > "$OUTDIR/pre-state.txt" 2>&1

wav="$OUTDIR/mic-capture.wav"
ffmpeg -nostdin -hide_banner -loglevel error \
  -f avfoundation -i "$FFMPEG_INPUT" \
  -t "$CAPTURE_DURATION" -ac 1 -ar 48000 -sample_fmt s16 "$wav" \
  > "$OUTDIR/ffmpeg.out" \
  2> "$OUTDIR/ffmpeg.err" &
ffmpeg_pid=$!

sleep 1.2

remote "
  set +e
  max_i2c_polls=$((DURATION * 5 + 20))
  max_wait_polls=$((DURATION + 5))

  read_low() {
    for r in 0x00 0x01 0x02 0x03 0x04 0x05 0x06 0x07 0x08 0x09 0x0a 0x0b 0x0c 0x0e 0x10 0x11 0x12 0x13 0x14 0x1a 0x1b 0x1c; do
      printf '%s=' \"\$r\"
      i2cget -f -y 3 0x1b \"\$r\" 2>/dev/null | tr -d '\\n'
      printf ' '
    done
    printf '\\n'
  }

  read_multi() {
    for spec in \
      '0x20:4:input_mux' '0x25:4:pwm_mux' \
      '0x29:20:ch1_bq3' '0x2a:20:ch1_bq4' \
      '0x3b:8:drc1_ae' '0x3c:8:drc1_aa' \
      '0x3e:8:drc2_ae' '0x3f:8:drc2_aa' \
      '0x40:8:drc_energy' '0x43:8:drc_decay' \
      '0x46:4:drc_ctrl' '0x50:4:bank_eq' \
      '0x51:8:left_out_mix' '0x52:8:right_out_mix' \
      '0x70:4:ch1_left_mix' '0x71:4:ch1_right_mix' \
      '0x74:4:ch2_left_mix' '0x75:4:ch2_right_mix'; do
      reg=\${spec%%:*}
      rest=\${spec#*:}
      len=\${rest%%:*}
      name=\${rest#*:}
      printf '%s[%s]=' \"\$name\" \"\$reg\"
      i2ctransfer -f -y 3 w1@0x1b \"\$reg\" r\"\$len\" 2>/dev/null | tr -d '\\n'
      printf ' '
    done
    printf '\\n'
  }

	  aplay -D hw:0,0 -q -f S16_LE -c 2 -r 48000 \
	    --period-size=$PERIOD_SIZE --buffer-size=$BUFFER_SIZE \
	    -d $DURATION /dev/zero &
	  aplay_pid=\$!

	  live_pid=
	  if [ '$LIVE_POLL' = 1 ]; then
	    (
	      p=\$(find /sys/devices -path '*40124000.mcbsp/power/runtime_status' | head -1)
	      i=0
	      while kill -0 \$aplay_pid 2>/dev/null; do
	        printf '=== live %03d uptime=' \"\$i\"
	        cut -d' ' -f1 /proc/uptime
	        printf 'mcbsp_runtime='
	        cat \"\$p\" 2>/dev/null || printf 'missing\n'
	        printf 'mcbsp_power_control='
	        cat \"\$(dirname \"\$p\")/control\" 2>/dev/null || printf 'missing\n'
	        echo 'pcm_status_live:'
	        cat /proc/asound/card0/pcm0p/sub0/status 2>/dev/null || true
	        echo 'clock_summary_live:'
	        grep -E '(40124000\\.mcbsp|4012408c\\.target-module|sound-tas5713.*mcbsp-sync|abe_24m|auxclk1_ck|dpll_per_m3x2)' /sys/kernel/debug/clk/clk_summary 2>/dev/null || true
	        i=\$((i + 1))
	        usleep ${LIVE_POLL_MS}000 2>/dev/null || sleep 1
	      done
	    ) &
	    live_pid=\$!
	  fi

	  if [ -n '$MCBSP_WAKEUPEN_DURING' ]; then
	    usleep 150000 2>/dev/null || sleep 0.15
    echo 'forcing_mcbsp_wakeupen=$MCBSP_WAKEUPEN_DURING'
    devmem 0x401240a8 16 '$MCBSP_WAKEUPEN_DURING' 2>/dev/null || \
      busybox devmem 0x401240a8 16 '$MCBSP_WAKEUPEN_DURING' 2>/dev/null || \
      echo 'forcing_mcbsp_wakeupen_failed'
  fi

  if [ '$I2C_POLL' = 1 ]; then
    i=0
    while kill -0 \$aplay_pid 2>/dev/null && [ \$i -lt \$max_i2c_polls ]; do
      printf '=== sample %03d uptime=' \"\$i\"
      cut -d' ' -f1 /proc/uptime
      echo 'low:'
      read_low
      echo 'multi:'
      read_multi
      echo 'pcm_status:'
      cat /proc/asound/card0/pcm0p/sub0/status 2>/dev/null || true
      i=\$((i + 1))
      usleep 200000 2>/dev/null || sleep 0.2
    done
  else
    echo 'i2c_poll=0'
    i=0
    while kill -0 \$aplay_pid 2>/dev/null && [ \$i -lt \$max_wait_polls ]; do
      sleep 1
      i=\$((i + 1))
    done
    echo 'pcm_status_after:'
    cat /proc/asound/card0/pcm0p/sub0/status 2>/dev/null || true
    echo 'tas_low_after:'
    read_low
	  fi
	  if kill -0 \$aplay_pid 2>/dev/null; then
	    echo 'aplay_wait_timeout=1'
	    kill \$aplay_pid 2>/dev/null || true
	  fi
	  wait \$aplay_pid
	  aplay_status=\$?
	  if [ -n \"\$live_pid\" ]; then
	    wait \$live_pid 2>/dev/null || true
	  fi
	  echo aplay_status=\$aplay_status
  echo '=== clock summary after ==='
  grep -E '(mcbsp|abe_24m|auxclk1|dpll_per_m3x2)' /sys/kernel/debug/clk/clk_summary || true
" > "$OUTDIR/playback-i2c.log" 2>&1

wait "$ffmpeg_pid"

python3 "$ROOT/tools/analyze_audio_probe_capture.py" \
  --expected "$EXPECTED" \
  --window-start 2 \
  --window-duration 8 \
  --no-active-region \
  --json "$wav" > "$OUTDIR/mic-capture-fixed-analysis.json"
python3 "$ROOT/tools/analyze_audio_probe_capture.py" \
  --expected "$EXPECTED" \
  --window-start 2 \
  --window-duration 8 \
  --no-active-region \
  "$wav" > "$OUTDIR/mic-capture-fixed-analysis.txt"

python3 - "$OUTDIR" <<'PY'
import json
import pathlib
import re
import sys

outdir = pathlib.Path(sys.argv[1])
metrics = json.loads((outdir / "mic-capture-fixed-analysis.json").read_text())
log = (outdir / "playback-i2c.log").read_text(errors="replace")
err_vals = sorted(set(re.findall(r"0x02=(0x[0-9a-fA-F]+)", log)))
sys2_vals = sorted(set(re.findall(r"0x05=(0x[0-9a-fA-F]+)", log)))
print(
    "mic p2t={:.3f}dB cv={:.3f} mod={:.3f}Hz rms={:.6f}".format(
        metrics.get("envelope_peak_to_trough_db_25ms", 0.0),
        metrics.get("envelope_cv_25ms", 0.0),
        metrics.get("envelope_mod_peak_hz_25ms", 0.0),
        metrics.get("rms", 0.0),
    )
)
print("tas_err_values=", ",".join(err_vals) if err_vals else "none")
print("tas_sys2_values=", ",".join(sys2_vals) if sys2_vals else "none")
print(f"ART={outdir}")
PY
