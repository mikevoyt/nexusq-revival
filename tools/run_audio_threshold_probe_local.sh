#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

: "${NQ_MCBSP_DMA_OP_MODE:=threshold}"
: "${NQ_MCBSP_MAX_TX_THRES:=32}"

export NQ_MCBSP_DMA_OP_MODE
export NQ_MCBSP_MAX_TX_THRES

exec "$ROOT/tools/run_audio_legacydma_probe_local.sh" "$@"
