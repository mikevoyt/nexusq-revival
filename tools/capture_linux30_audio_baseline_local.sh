#!/usr/bin/env bash
set -euo pipefail

NQ_HOST="${NQ_HOST:-169.254.42.2}"
NQ_TELNET_PORT="${NQ_TELNET_PORT:-2323}"
NQ_STREAM_PORT="${NQ_STREAM_PORT:-5555}"
TAS5713_VOLUME="${TAS5713_VOLUME:-0x50}"
TAS5713_HELPER="${TAS5713_HELPER:-/bin/nq-tas5713-volume}"
SOURCE_WAV="${SOURCE_WAV:-artifacts/audio-baseline-amp002-i2s-nbnf-20260613-215222/nq-left-440-48000-S16_LE.wav}"
OUTDIR="${OUTDIR:-artifacts/audio-rootcause-linux30-known-good-$(date +%Y%m%d-%H%M%S)}"

if [[ ! -r "$SOURCE_WAV" ]]; then
  echo "missing SOURCE_WAV: $SOURCE_WAV" >&2
  exit 1
fi

mkdir -p "$OUTDIR"
cp "$SOURCE_WAV" "$OUTDIR/source-nq-left-440-48000-S16_LE.wav"
shasum -a 256 "$OUTDIR/source-nq-left-440-48000-S16_LE.wav" > "$OUTDIR/source-wav.sha256"

cat > "$OUTDIR/run-info.txt" <<EOF_RUN_INFO
host: $NQ_HOST
telnet_port: $NQ_TELNET_PORT
stream_port: $NQ_STREAM_PORT
tas5713_helper: $TAS5713_HELPER
tas5713_volume: $TAS5713_VOLUME
source_wav: $SOURCE_WAV
outdir: $OUTDIR
date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
purpose: Linux 3.0 known-good baseline capture using correct McBSP2 base 0x40124000 and private TAS5713 volume ioctl
EOF_RUN_INFO

run_remote_capture() {
  local phase="$1"
  local cmdfile="$OUTDIR/remote-${phase}.cmd"
  local outfile="$OUTDIR/remote-${phase}.txt"
  local expfile="$OUTDIR/remote-${phase}.expect"

  {
    printf 'echo "=== phase: %s ==="\n' "$phase"
    cat <<'REMOTE_SH'
set +e
mount -t debugfs debugfs /sys/kernel/debug >/dev/null 2>&1 || true

echo "=== identity ==="
uname -a
cat /proc/cmdline 2>/dev/null

echo "=== alsa ==="
cat /proc/asound/cards 2>/dev/null
cat /proc/asound/pcm 2>/dev/null

echo "=== interrupts-interest ==="
cat /proc/interrupts 2>/dev/null | grep -Ei 'mcbsp|dma|sdma|tas|i2c| 22:| 17:' || true

echo "=== clocks-interest ==="
for f in /sys/kernel/debug/clock/clock_summary /sys/kernel/debug/clk/clk_summary; do
  if [ -r "$f" ]; then
    echo "--- $f ---"
    cat "$f" | grep -Ei 'mcbsp2|auxclk|abe_24|dpll_per|sys_32k' || true
  fi
done

echo "=== tas5713-debugfs ==="
found_tas=0
for f in /sys/kernel/debug/tas5713-4-001b/dump_regs /sys/kernel/debug/tas5713*/dump_regs; do
  if [ -r "$f" ]; then
    found_tas=1
    echo "--- $f ---"
    cat "$f"
  fi
done
if [ "$found_tas" = 0 ]; then
  echo "no tas5713 dump_regs file found"
fi

echo "=== sdma-global-0x4a056000 ==="
for entry in \
  "IRQSTATUS_L0 0x08" \
  "IRQENABLE_L0 0x18" \
  "OCP_SYSCONFIG 0x2c" \
  "GCR 0x78"
do
  set -- $entry
  name="$1"
  off="$2"
  addr=$(printf '0x%08x' $((0x4a056000 + off)))
  printf '%-16s %-10s ' "$name" "$addr"
  busybox devmem "$addr" 32 2>&1 || true
done

echo "=== control-pad-mcbsp2-0x4a100000 ==="
for entry in \
  "CLKX 0x0f6" \
  "DR 0x0f8" \
  "DX 0x0fa" \
  "FSX 0x0fc"
do
  set -- $entry
  name="$1"
  off="$2"
  addr=$(printf '0x%08x' $((0x4a100000 + off)))
  printf '%-8s %-10s ' "$name" "$addr"
  busybox devmem "$addr" 16 2>&1 || true
done

echo "=== control-pad-tas5713-gpio-mclk-0x4a100000 ==="
for entry in \
  "IFACE_GPIO40_GPMC_A16 0x060" \
  "RESET_GPIO42_GPMC_A18 0x064" \
  "PDN_GPIO44_GPMC_A20 0x068" \
  "MCLK_FREF_CLK1_OUT 0x19a"
do
  set -- $entry
  name="$1"
  off="$2"
  addr=$(printf '0x%08x' $((0x4a100000 + off)))
  printf '%-24s %-10s ' "$name" "$addr"
  busybox devmem "$addr" 16 2>&1 || true
done

echo "=== gpio2-audio-lines-0x48055000 ==="
gpio2_base=$((0x48055000))
gpio2_oe=$(busybox devmem "$(printf '0x%08x' $((gpio2_base + 0x134)))" 32 2>/dev/null)
gpio2_datain=$(busybox devmem "$(printf '0x%08x' $((gpio2_base + 0x138)))" 32 2>/dev/null)
gpio2_dataout=$(busybox devmem "$(printf '0x%08x' $((gpio2_base + 0x13c)))" 32 2>/dev/null)
printf '%-16s %-10s %s\n' "GPIO2_OE" "$(printf '0x%08x' $((gpio2_base + 0x134)))" "${gpio2_oe:-read_failed}"
printf '%-16s %-10s %s\n' "GPIO2_DATAIN" "$(printf '0x%08x' $((gpio2_base + 0x138)))" "${gpio2_datain:-read_failed}"
printf '%-16s %-10s %s\n' "GPIO2_DATAOUT" "$(printf '0x%08x' $((gpio2_base + 0x13c)))" "${gpio2_dataout:-read_failed}"
for entry in \
  "IFACE_GPIO40 8" \
  "RESET_GPIO42 10" \
  "PDN_GPIO44 12"
do
  set -- $entry
  name="$1"
  bit="$2"
  oe_bit="?"
  datain_bit="?"
  dataout_bit="?"
  case "$gpio2_oe" in 0x*) oe_bit=$(( (gpio2_oe >> bit) & 1 ));; esac
  case "$gpio2_datain" in 0x*) datain_bit=$(( (gpio2_datain >> bit) & 1 ));; esac
  case "$gpio2_dataout" in 0x*) dataout_bit=$(( (gpio2_dataout >> bit) & 1 ));; esac
  printf '%-14s bit=%-2s oe_bit=%s datain=%s dataout=%s\n' "$name" "$bit" "$oe_bit" "$datain_bit" "$dataout_bit"
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
  busybox devmem "$addr" 32 2>&1 || true
done

echo "=== sdma-active-channels-0x4a056000 ==="
sdma_base=$((0x4a056000))
ch=0
while [ "$ch" -lt 32 ]; do
  chan_base=$((sdma_base + 0x80 + ch * 0x60))
  ccr_addr=$(printf '0x%08x' "$chan_base")
  ccr=$(busybox devmem "$ccr_addr" 32 2>/dev/null)
  if [ "$ccr" != "0x00000000" ]; then
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
      busybox devmem "$addr" 32 2>&1 || true
    done
  fi
  ch=$((ch + 1))
done
REMOTE_SH
  } > "$cmdfile"

  cat > "$expfile" <<'EXPECT_EOF'
set timeout 20
set host [lindex $argv 0]
set port [lindex $argv 1]
set cmdfile [lindex $argv 2]
set prompt_re {(^|\r|\n)/ # }

spawn telnet $host $port
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT"; exit 2 }
  eof { puts "EOF_BEFORE_PROMPT"; exit 3 }
}

send -- "cat >/tmp/nq_capture.sh <<'NQCAP_EOF'\r"
set send_slow {1 .001}
set fh [open $cmdfile r]
while {[gets $fh line] >= 0} {
  send -s -- "$line\r"
}
close $fh
send -s -- "NQCAP_EOF\r"
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT_AFTER_UPLOAD"; exit 4 }
}

send -- "sh /tmp/nq_capture.sh\r"
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT_AFTER_CAPTURE"; exit 5 }
  eof { puts "EOF_DURING_CAPTURE"; exit 6 }
}

send -- "rm -f /tmp/nq_capture.sh\r"
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT_AFTER_RM"; exit 7 }
}
send -- "exit\r"
expect eof
EXPECT_EOF

  expect "$expfile" "$NQ_HOST" "$NQ_TELNET_PORT" "$cmdfile" > "$outfile"
}

run_remote_tas_volume_prime() {
  local cmdfile="$OUTDIR/remote-tas-volume-prime.cmd"
  local outfile="$OUTDIR/remote-tas-volume-prime.txt"
  local expfile="$OUTDIR/remote-tas-volume-prime.expect"

  cat > "$cmdfile" <<EOF_REMOTE_TAS
set +e
echo "=== tas5713 private volume prime ==="
mount -t debugfs debugfs /sys/kernel/debug >/dev/null 2>&1 || true
echo "helper=$TAS5713_HELPER volume=$TAS5713_VOLUME"
ls -l "$TAS5713_HELPER" /dev/snd/pcmC2D0p 2>&1 || true
"$TAS5713_HELPER" "$TAS5713_VOLUME" /dev/snd/pcmC2D0p &
tas_pid=\$!
tas_wait=0
while kill -0 "\$tas_pid" 2>/dev/null && [ "\$tas_wait" -lt 5 ]; do
  sleep 1
  tas_wait=\$((tas_wait + 1))
done
if kill -0 "\$tas_pid" 2>/dev/null; then
  echo "tas_volume_prime_timeout_after=\${tas_wait}s"
  kill "\$tas_pid" 2>/dev/null || true
  wait "\$tas_pid" 2>/dev/null || true
  tas_rc=124
else
  wait "\$tas_pid"
  tas_rc=\$?
fi
echo "tas_volume_prime_rc=\$tas_rc"
for f in /sys/kernel/debug/tas5713-4-001b/dump_regs /sys/kernel/debug/tas5713*/dump_regs; do
  if [ -r "\$f" ]; then
    echo "--- \$f ---"
    cat "\$f"
  fi
done
EOF_REMOTE_TAS

  cat > "$expfile" <<'EXPECT_EOF'
set timeout 20
set host [lindex $argv 0]
set port [lindex $argv 1]
set cmdfile [lindex $argv 2]
set prompt_re {(^|\r|\n)/ # }

spawn telnet $host $port
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT"; exit 2 }
  eof { puts "EOF_BEFORE_PROMPT"; exit 3 }
}

send -- "cat >/tmp/nq_tas_volume_prime.sh <<'NQTAS_EOF'\r"
set fh [open $cmdfile r]
while {[gets $fh line] >= 0} {
  send -- "$line\r"
}
close $fh
send -- "NQTAS_EOF\r"
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT_AFTER_UPLOAD"; exit 4 }
}

send -- "sh /tmp/nq_tas_volume_prime.sh\r"
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT_AFTER_TAS_VOLUME"; exit 5 }
  eof { puts "EOF_DURING_TAS_VOLUME"; exit 6 }
}

send -- "rm -f /tmp/nq_tas_volume_prime.sh\r"
expect {
  -re $prompt_re {}
  timeout { puts "NO_PROMPT_AFTER_RM"; exit 7 }
}
send -- "exit\r"
expect eof
EXPECT_EOF

  expect "$expfile" "$NQ_HOST" "$NQ_TELNET_PORT" "$cmdfile" > "$outfile"
}

echo "Capturing pre-playback state into $OUTDIR"
run_remote_capture pre

echo "Priming TAS5713 private master volume on $NQ_HOST"
run_remote_tas_volume_prime

echo "Streaming low-amplitude WAV to nqstreamd on $NQ_HOST:$NQ_STREAM_PORT"
(
  set +e
  nc -w 12 "$NQ_HOST" "$NQ_STREAM_PORT" < "$SOURCE_WAV" > "$OUTDIR/nc-playback.log" 2>&1
  echo "$?" > "$OUTDIR/nc-playback.status"
) &
playback_pid=$!

sleep 1
echo "Capturing during-playback state into $OUTDIR"
run_remote_capture during

wait "$playback_pid" || true

echo "Capturing post-playback state into $OUTDIR"
run_remote_capture after

echo "capture complete: $OUTDIR"
