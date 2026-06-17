#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT/tools/audio_diag_required_args.sh"
IMAGE="${IMAGE:-$ROOT/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img}"
BASELINE_JSON="${BASELINE_JSON:-$ROOT/artifacts/audio-baselines/jun12-bad-capture-expected-440.json}"
REQUIRE_MIC="${REQUIRE_MIC:-1}"
NQ_HOST="${NQ_HOST:-192.168.86.38}"
NQ_USER="${NQ_USER:-root}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4"
CHECK_IMAGE_CMDLINE="${CHECK_IMAGE_CMDLINE:-1}"
IMAGE_CMDLINE_MAX="${IMAGE_CMDLINE_MAX:-512}"
REQUIRED_IMAGE_ARGS="${REQUIRED_IMAGE_ARGS:-$NQ_AUDIO_DIAG_REQUIRED_ARGS}"
failures=0

note() {
	printf '%s\n' "$*"
}

ok() {
	printf 'ok: %s\n' "$*"
}

warn() {
	printf 'warn: %s\n' "$*" >&2
}

fail() {
	printf 'fail: %s\n' "$*" >&2
	failures=$((failures + 1))
}

need_cmd() {
	if command -v "$1" >/dev/null 2>&1; then
		ok "command $1"
	else
		fail "missing command $1"
	fi
}

need_file() {
	if [ -f "$1" ]; then
		ok "file $1"
	else
		fail "missing file $1"
	fi
}

need_executable() {
	if [ -x "$1" ]; then
		ok "executable $1"
	else
		fail "not executable $1"
	fi
}

check_image_cmdline() {
	if [ "$CHECK_IMAGE_CMDLINE" != "1" ]; then
		warn "skipping image cmdline validation because CHECK_IMAGE_CMDLINE=$CHECK_IMAGE_CMDLINE"
		return 0
	fi
	if [ ! -f "$IMAGE" ]; then
		return 0
	fi
	if ! command -v strings >/dev/null 2>&1; then
		fail "missing command strings; cannot validate image cmdline"
		return 0
	fi

	cmdline="$(strings "$IMAGE" |
		awk '/^console=ttyO2/ && /nq[.]audio_format=/ { print; exit }')"
	if [ -z "$cmdline" ]; then
		fail "image cmdline with Nexus Q audio diagnostics not found in $IMAGE"
		return 0
	fi

	cmdline_len="$(printf '%s' "$cmdline" | wc -c | tr -d ' ')"
	if [ "$cmdline_len" -le "$IMAGE_CMDLINE_MAX" ]; then
		ok "image cmdline length $cmdline_len <= $IMAGE_CMDLINE_MAX"
	else
		fail "image cmdline length $cmdline_len exceeds $IMAGE_CMDLINE_MAX"
	fi

	for arg in $REQUIRED_IMAGE_ARGS; do
		case " $cmdline " in
			*" $arg "*) ok "image cmdline arg $arg" ;;
			*) fail "image cmdline missing $arg" ;;
		esac
	done
}

note "Nexus Q audio probe preflight"
note "root=$ROOT"
note "image=$IMAGE"
note "baseline_json=$BASELINE_JSON"
note "require_mic=$REQUIRE_MIC"

need_cmd python3
need_cmd ssh
need_cmd scp
need_cmd rg

if [ "${FASTBOOT_BOOT:-0}" = "1" ]; then
	need_cmd fastboot
else
	if command -v fastboot >/dev/null 2>&1; then
		ok "command fastboot"
	else
		warn "fastboot not found; required only when FASTBOOT_BOOT=1"
	fi
fi

if [ -n "${FFMPEG_INPUT:-}" ] || [ "${LIST_AUDIO_INPUTS:-0}" = "1" ]; then
	need_cmd ffmpeg
else
	if command -v ffmpeg >/dev/null 2>&1; then
		ok "command ffmpeg"
	else
		warn "ffmpeg not found; required for Mac microphone capture"
	fi
	if [ "$REQUIRE_MIC" = "1" ]; then
		fail "FFMPEG_INPUT is not set; the default sweep requires Mac microphone capture"
	else
		warn "FFMPEG_INPUT is not set; the next sweep will not capture Mac microphone audio"
	fi
fi

need_file "$IMAGE"
check_image_cmdline
need_file "$BASELINE_JSON"
need_executable "$ROOT/tools/analyze_audio_probe_capture.py"
need_executable "$ROOT/tools/check_tas5713_init_parity.py"
need_executable "$ROOT/tools/summarize_audio_probe_runs.py"
need_executable "$ROOT/tools/triage_audio_sweep.py"
need_executable "$ROOT/tools/test_audio_analysis.py"
need_executable "$ROOT/tools/test_audio_shell_guards.sh"
need_executable "$ROOT/tools/start_watchdog_feeder_remote.sh"
need_executable "$ROOT/tools/run_audio_format_module_sweep_local.sh"
need_executable "$ROOT/tools/run_audio_legacydma_probe_local.sh"
need_executable "$ROOT/tools/run_audio_pio_when_ready_local.sh"
need_executable "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
need_executable "$ROOT/tools/run_audio_module_reload_sweep_when_ready_local.sh"
need_executable "$ROOT/tools/run_audio_threshold_probe_local.sh"
need_executable "$ROOT/tools/run_audio_probe_sweep_local.sh"

if [ "${RUN_AUDIO_ANALYSIS_TESTS:-1}" = "1" ]; then
	if "$ROOT/tools/test_audio_analysis.py" >/tmp/nq-audio-analysis-test.out 2>/tmp/nq-audio-analysis-test.err; then
		ok "offline audio analysis tests"
	else
		fail "offline audio analysis tests failed; see /tmp/nq-audio-analysis-test.out and .err"
	fi
fi

if [ "${RUN_AUDIO_SHELL_GUARD_TESTS:-1}" = "1" ]; then
	if "$ROOT/tools/test_audio_shell_guards.sh" >/tmp/nq-audio-shell-guard-test.out 2>/tmp/nq-audio-shell-guard-test.err; then
		ok "offline shell guard tests"
	else
		fail "offline shell guard tests failed; see /tmp/nq-audio-shell-guard-test.out and .err"
	fi
fi

if [ "${RUN_TAS5713_INIT_PARITY:-1}" = "1" ]; then
	if "$ROOT/tools/check_tas5713_init_parity.py" >/tmp/nq-tas5713-init-parity.out 2>/tmp/nq-tas5713-init-parity.err; then
		ok "TAS5713 init table parity"
	else
		fail "TAS5713 init table parity failed; see /tmp/nq-tas5713-init-parity.out and .err"
	fi
fi

if [ "${LIST_AUDIO_INPUTS:-0}" = "1" ]; then
	note "Listing ffmpeg/avfoundation inputs; this does not play audio."
	ffmpeg -f avfoundation -list_devices true -i "" </dev/null || true
fi

if [ "${CHECK_SSH:-0}" = "1" ]; then
	note "Checking SSH only; this does not play audio."
	if ssh $SSH_OPTS "$NQ_USER@$NQ_HOST" 'true' >/dev/null 2>&1; then
		ok "ssh $NQ_USER@$NQ_HOST"
	else
		fail "ssh $NQ_USER@$NQ_HOST failed"
	fi
fi

if [ "$failures" -ne 0 ]; then
	fail "$failures preflight check(s) failed"
	exit 1
fi

ok "audio probe preflight complete"
note "Next live legacy-DMA sweep after reconnecting the speaker:"
note "  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_probe_sweep_local.sh"
note "Next live module-reload sweep after booting the DMA-modular image:"
note "  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_module_reload_sweep_local.sh"
note "Or boot the DMA-modular image once from fastboot, then reload modules per case:"
note "  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' FASTBOOT_BOOT=1 tools/run_audio_module_reload_sweep_local.sh"
note "If the current device state is unknown, wait for SSH or fastboot and run the same sweep:"
note "  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_module_reload_sweep_when_ready_local.sh"
note "Next live module-reload format/inversion sweep:"
note "  NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_format_module_sweep_local.sh"
