#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
NQ_HOST="${NQ_HOST:-fe80::16:42ff:fe00:2%en12}"
NQ_USER="${NQ_USER:-root}"
OUTDIR="${OUTDIR:-$ROOT/artifacts/audio-rootcause-linux66-full-tas-dump-kdmatone-$(date +%Y%m%d-%H%M%S)}"
REFERENCE="${REFERENCE:-$ROOT/artifacts/audio-rootcause-linux30-expanded-runtime-500hz-20260615-230312/remote-during.txt}"
EXPECTED="${EXPECTED:-500}"
DURATION="${DURATION:-8}"
PERIOD_SIZE="${PERIOD_SIZE:-1032}"
BUFFER_SIZE="${BUFFER_SIZE:-4128}"
TONE_AMP="${TONE_AMP:-4096}"
MASTER_VOLUME="${MASTER_VOLUME:-175}"
SPEAKER_VOLUME="${SPEAKER_VOLUME:-207}"
PYTHON="${PYTHON:-python3}"

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
  set +e
  /sbin/nq-autoreboot-cancel 2>/dev/null || true
  ip link set wlan0 down 2>/dev/null || true
  mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
  uname -a
' >"$OUTDIR/prep.txt" 2>&1

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
  printf 0 >/sys/module/omap_dma/parameters/nq_audio_tone_no_irq
  if [ -e /sys/module/omap_dma/parameters/nq_audio_tone_fake_period ]; then
    printf 0 >/sys/module/omap_dma/parameters/nq_audio_tone_fake_period
  fi
  echo '=== module params ==='
  for f in \
    /sys/module/snd_soc_steelhead_tas5713/parameters/nq_period_size \
    /sys/module/snd_soc_steelhead_tas5713/parameters/nq_periods \
    /sys/module/omap_dma/parameters/nq_audio_tone \
    /sys/module/omap_dma/parameters/nq_audio_tone_freq \
    /sys/module/omap_dma/parameters/nq_audio_tone_amp \
    /sys/module/omap_dma/parameters/nq_audio_tone_channel \
    /sys/module/omap_dma/parameters/nq_audio_tone_no_irq; do
    printf '%s=' \"\$f\"
    cat \"\$f\"
  done
  echo '=== mixer ==='
  amixer -c 0 sget Master 2>/dev/null | grep Mono: || true
  amixer -c 0 sget Speaker 2>/dev/null | grep 'Front Left:' || true
" >"$OUTDIR/setup.txt" 2>&1

remote "EXPECTED=$EXPECTED DURATION=$DURATION PERIOD_SIZE=$PERIOD_SIZE BUFFER_SIZE=$BUFFER_SIZE sh -s" >"$OUTDIR/remote-during.txt" 2>&1 <<'REMOTE'
set +e

word_bytes() {
  reg="$1"
  len="$2"
  bytes=$(i2ctransfer -f -y 3 w1@0x1b "$reg" r"$len" 2>/dev/null)
  if [ -z "$bytes" ]; then
    printf " read-failed"
    return
  fi
  set -- $bytes
  idx=0
  word=""
  for byte in "$@"; do
    hex="${byte#0x}"
    case "${#hex}" in
      1) hex="0$hex" ;;
    esac
    word="${word}${hex}"
    idx=$((idx + 1))
    if [ $((idx % 4)) -eq 0 ]; then
      printf " %s" "$word"
      word=""
    fi
  done
  if [ -n "$word" ]; then
    printf " %s" "$word"
  fi
}

dump_reg() {
  reg="$1"
  len="$2"
  name="$3"
  reg_label=$(printf "%02x" "$reg")
  printf "%40s[%s] :" "$name" "$reg_label"
  word_bytes "$(printf "0x%02x" "$reg")" "$len"
  printf "\n"
}

dump_tas() {
  dump_reg 0x00 1 "Clock control register"
  dump_reg 0x01 1 "Device ID register"
  dump_reg 0x02 1 "Error status register"
  dump_reg 0x03 1 "System control register 1"
  dump_reg 0x04 1 "Serial data interface register"
  dump_reg 0x05 1 "System control register 2"
  dump_reg 0x06 1 "Soft mute register"
  dump_reg 0x07 1 "Master volume"
  dump_reg 0x08 1 "Channel 1 vol"
  dump_reg 0x09 1 "Channel 2 vol"
  dump_reg 0x0a 1 "Channel 3 vol"
  dump_reg 0x0e 1 "Volume configuration register"
  dump_reg 0x10 1 "Modulation limit register"
  dump_reg 0x11 1 "IC delay channel 1"
  dump_reg 0x12 1 "IC delay channel 2"
  dump_reg 0x13 1 "IC delay channel 3"
  dump_reg 0x14 1 "IC delay channel 4"
  dump_reg 0x1a 1 "Start/stop period register"
  dump_reg 0x1b 1 "Oscillator trim register"
  dump_reg 0x1c 1 "BKND_ERR register"
  dump_reg 0x20 4 "Input MUX register"
  dump_reg 0x21 4 "Ch 4 source select register"
  dump_reg 0x25 4 "PWM MUX register"
  dump_reg 0x29 20 "ch1_bq[0]"
  dump_reg 0x2a 20 "ch1_bq[1]"
  dump_reg 0x2b 20 "ch1_bq[2]"
  dump_reg 0x2c 20 "ch1_bq[3]"
  dump_reg 0x2d 20 "ch1_bq[4]"
  dump_reg 0x2e 20 "ch1_bq[5]"
  dump_reg 0x2f 20 "ch1_bq[6]"
  dump_reg 0x30 20 "ch2_bq[0]"
  dump_reg 0x31 20 "ch2_bq[1]"
  dump_reg 0x32 20 "ch2_bq[2]"
  dump_reg 0x33 20 "ch2_bq[3]"
  dump_reg 0x34 20 "ch2_bq[4]"
  dump_reg 0x35 20 "ch2_bq[5]"
  dump_reg 0x36 20 "ch2_bq[6]"
  dump_reg 0x3b 8 "DRC1 softening filter alpha/omega"
  dump_reg 0x3c 8 "DRC1 attack/release rate"
  dump_reg 0x3e 8 "DRC2 softening filter alpha/omega"
  dump_reg 0x3f 8 "DRC2 attack/release rate"
  dump_reg 0x40 8 "DRC1 attack/release threshold"
  dump_reg 0x43 8 "DRC2 attack/decay threshold"
  dump_reg 0x46 4 "DRC control"
  dump_reg 0x50 4 "Bank switch control"
  dump_reg 0x51 8 "Ch 1 output mixer"
  dump_reg 0x52 8 "Ch 2 output mixer"
  dump_reg 0x53 16 "Ch 1 input mixers"
  dump_reg 0x54 16 "Ch 2 input mixers"
  dump_reg 0x56 4 "Output post-scale"
  dump_reg 0x57 4 "Output pre-scale"
  dump_reg 0x58 20 "ch1 BQ[7]"
  dump_reg 0x59 20 "ch1 BQ[8]"
  dump_reg 0x5a 20 "ch4 BQ[0]"
  dump_reg 0x5b 20 "ch4 BQ[1]"
  dump_reg 0x5c 20 "ch2 BQ[7]"
  dump_reg 0x5d 20 "ch2 BQ[8]"
  dump_reg 0x5e 20 "ch3 BQ[0]"
  dump_reg 0x5f 20 "ch3 BQ[1]"
  dump_reg 0x62 4 "IDF post scale"
  dump_reg 0x70 4 "ch1 inline mixer"
  dump_reg 0x71 4 "inline_DRC_en_mixer_ch1"
  dump_reg 0x72 4 "ch1 right_channel_mixer"
  dump_reg 0x73 4 "ch1 left_channel_mixer"
  dump_reg 0x74 4 "ch2 inline mixer"
  dump_reg 0x75 4 "inline_DRC_en_mixer_ch2"
  dump_reg 0x76 4 "ch2 right_channel_mixer"
  dump_reg 0x77 4 "ch2 left_channel_mixer"
  dump_reg 0xf8 4 "Update dev address key"
  dump_reg 0xf9 4 "Update dev address reg"
}

echo "=== identity ==="
uname -a
cat /proc/cmdline 2>/dev/null || true

echo "=== start playback ==="
aplay -D hw:0,0 -q -f S16_LE -c 2 -r 48000 \
  --period-size="$PERIOD_SIZE" --buffer-size="$BUFFER_SIZE" \
  -d "$DURATION" /dev/zero &
aplay_pid=$!
sleep 1

echo "=== pcm status before dump ==="
cat /proc/asound/card0/pcm0p/sub0/status 2>/dev/null || true

echo "=== tas5713-i2c-dump ==="
dump_tas

echo "=== mcbsp2 quick state ==="
for entry in \
  "SPCR2 0x40124010" \
  "SPCR1 0x40124014" \
  "IRQST 0x401240a0" \
  "IRQEN 0x401240a4" \
  "XBUFFSTAT 0x401240b4" \
  "RBUFFSTAT 0x401240b8"; do
  set -- $entry
  printf "%-10s %-10s " "$1" "$2"
  busybox devmem "$2" 32 2>/dev/null || devmem "$2" 32 2>/dev/null || true
done

wait "$aplay_pid"
status=$?
echo "aplay_status=$status"
exit "$status"
REMOTE

"$PYTHON" "$ROOT/tools/compare_tas5713_dumps.py" \
  "$REFERENCE" "$OUTDIR/remote-during.txt" \
  >"$OUTDIR/tas5713-diff.txt" 2>&1 || true

printf 'ART=%s\n' "$OUTDIR"
cat "$OUTDIR/tas5713-diff.txt"
