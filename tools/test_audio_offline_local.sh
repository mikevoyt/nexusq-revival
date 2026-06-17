#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "== shell syntax =="
sh -n \
	"$ROOT/tools/audio_diag_required_args.sh" \
	"$ROOT/tools/build_debian_loader_initramfs_omap_dma_local.sh" \
	"$ROOT/tools/build_audio_dma_modular_image_local.sh" \
	"$ROOT/tools/build_audio_dma_modules_local.sh" \
	"$ROOT/tools/build_audio_ldc_image_local.sh" \
	"$ROOT/tools/build_audio_legacydma_image_local.sh" \
	"$ROOT/tools/build_audio_modular_image_local.sh" \
	"$ROOT/tools/build_audio_modules_local.sh" \
	"$ROOT/tools/check_audio_probe_prereqs_local.sh" \
	"$ROOT/tools/check_tas5713_init_parity.py" \
	"$ROOT/tools/install_audio_modules_remote.sh" \
	"$ROOT/tools/reload_audio_modules_remote.sh" \
	"$ROOT/tools/run_audio_format_module_sweep_local.sh" \
	"$ROOT/tools/run_audio_legacydma_probe_local.sh" \
	"$ROOT/tools/run_audio_module_reload_sweep_local.sh" \
	"$ROOT/tools/run_audio_module_reload_sweep_when_ready_local.sh" \
	"$ROOT/tools/run_audio_period_sweep_local.sh" \
	"$ROOT/tools/run_audio_probe_sweep_local.sh" \
	"$ROOT/tools/run_audio_threshold_probe_local.sh" \
	"$ROOT/tools/test_audio_shell_guards.sh"

echo "== python syntax =="
python3 -m py_compile \
	"$ROOT/tools/analyze_audio_probe_capture.py" \
	"$ROOT/tools/check_tas5713_init_parity.py" \
	"$ROOT/tools/summarize_audio_probe_runs.py" \
	"$ROOT/tools/triage_audio_sweep.py" \
	"$ROOT/tools/test_audio_analysis.py"

echo "== analyzer regression =="
"$ROOT/tools/test_audio_analysis.py"

echo "== shell guard regression =="
"$ROOT/tools/test_audio_shell_guards.sh"

echo "== tas5713 init parity =="
"$ROOT/tools/check_tas5713_init_parity.py"

echo "== preflight =="
FFMPEG_INPUT="${FFMPEG_INPUT:-:0}" \
RUN_AUDIO_ANALYSIS_TESTS=0 \
RUN_AUDIO_SHELL_GUARD_TESTS=0 \
RUN_TAS5713_INIT_PARITY=0 \
	"$ROOT/tools/check_audio_probe_prereqs_local.sh"

echo "== kernel patch dry-run =="
patch --batch --dry-run -d "$ROOT/build/patch-pristine/linux-6.6.142" -p2 \
	< "$ROOT/patches/linux-6.6.142-nexusq-steelhead.patch"

echo "== diff check =="
git -C "$ROOT" diff --check -- ':!patches/linux-6.6.142-nexusq-steelhead.patch'

echo "audio-offline-tests-ok"
