#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RUN_CASES="${RUN_CASES:-i2s-nbnf leftj-nbnf i2s-nbif leftj-nbif i2s-ibnf leftj-ibnf i2s-ibif leftj-ibif}"
SWEEP_DIR="${SWEEP_DIR:-$ROOT/artifacts/audio-format-module-sweep-$(date +%Y%m%d-%H%M%S)}"

RUN_CASES="$RUN_CASES" SWEEP_DIR="$SWEEP_DIR" \
	"$ROOT/tools/run_audio_module_reload_sweep_local.sh"
