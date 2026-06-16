#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT/tools/audio_diag_required_args.sh"

TMP="${TMPDIR:-/tmp}/nq-audio-shell-guards.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

good_cmdline="console=ttyO2,115200n8 ignore_loglevel root=/dev/ram0 $NQ_AUDIO_DIAG_REQUIRED_ARGS"
bad_cmdline="console=ttyO2,115200n8 ignore_loglevel root=/dev/ram0 nq.audio_format=i2s"

write_image() {
	path="$1"
	cmdline="$2"
	printf 'padding-before\n%s\npadding-after\n' "$cmdline" > "$path"
}

expect_success() {
	name="$1"
	shift
	if "$@" > "$TMP/$name.out" 2> "$TMP/$name.err"; then
		return 0
	fi
	echo "expected success: $name" >&2
	sed 's/^/  /' "$TMP/$name.out" >&2 || true
	sed 's/^/  /' "$TMP/$name.err" >&2 || true
	exit 1
}

expect_failure() {
	name="$1"
	shift
	if "$@" > "$TMP/$name.out" 2> "$TMP/$name.err"; then
		echo "expected failure: $name" >&2
		sed 's/^/  /' "$TMP/$name.out" >&2 || true
		sed 's/^/  /' "$TMP/$name.err" >&2 || true
		exit 1
	fi
}

good_image="$TMP/good.img"
bad_image="$TMP/bad.img"
write_image "$good_image" "$good_cmdline"
write_image "$bad_image" "$bad_cmdline"

expect_success good-image \
	env IMAGE="$good_image" REQUIRE_MIC=0 RUN_AUDIO_ANALYSIS_TESTS=0 RUN_AUDIO_SHELL_GUARD_TESTS=0 \
		"$ROOT/tools/check_audio_probe_prereqs_local.sh"

expect_failure missing-image-arg \
	env IMAGE="$bad_image" REQUIRE_MIC=0 RUN_AUDIO_ANALYSIS_TESTS=0 RUN_AUDIO_SHELL_GUARD_TESTS=0 \
		"$ROOT/tools/check_audio_probe_prereqs_local.sh"
rg -q 'image cmdline missing nq.audio_inversion=nb-nf' "$TMP/missing-image-arg.err"

expect_failure image-cmdline-limit \
	env IMAGE="$good_image" IMAGE_CMDLINE_MAX=32 REQUIRE_MIC=0 RUN_AUDIO_ANALYSIS_TESTS=0 RUN_AUDIO_SHELL_GUARD_TESTS=0 \
		"$ROOT/tools/check_audio_probe_prereqs_local.sh"
rg -q 'image cmdline length .* exceeds 32' "$TMP/image-cmdline-limit.err"

fakebin="$TMP/fakebin"
mkdir -p "$fakebin"
cat > "$fakebin/ssh" <<'SH'
#!/bin/sh
case "$*" in
	*"cat /proc/cmdline"*)
		printf '%s\n' "${FAKE_REMOTE_CMDLINE:-console=ttyO2 nq.audio_format=i2s}"
		;;
	*"sh -s --"*)
		cat >/dev/null
		printf '%s\n' "${FAKE_REMOTE_MODULE_PARAMS_RESULT:-ok: fake}"
		exit "${FAKE_REMOTE_MODULE_PARAMS_EXIT:-0}"
		;;
	*)
		exit 0
		;;
esac
SH
chmod +x "$fakebin/ssh"
for tool in scp ffmpeg aplay amixer; do
	cat > "$fakebin/$tool" <<'SH'
#!/bin/sh
echo "unexpected fake media/transfer tool invocation: $0 $*" >&2
exit 97
SH
	chmod +x "$fakebin/$tool"
done

remote_out="$TMP/remote"
mkdir -p "$remote_out"
expect_failure stale-remote-cmdline \
	env PATH="$fakebin:$PATH" NQ_SPEAKER_CONNECTED=1 OUTDIR="$remote_out" \
		NQ_HOST=fake NQ_USER=root FAKE_REMOTE_CMDLINE="$bad_cmdline" \
		"$ROOT/tools/run_audio_legacydma_probe_local.sh"
rg -q 'missing: nq.audio_inversion=nb-nf' "$remote_out/remote-cmdline-check.txt"
if find "$remote_out" -name '*.wav' | rg -q .; then
	echo "remote cmdline guard generated WAV before failing" >&2
	exit 1
fi

remote_module_out="$TMP/remote-module"
mkdir -p "$remote_module_out"
expect_failure stale-remote-module-param \
	env PATH="$fakebin:$PATH" NQ_SPEAKER_CONNECTED=1 OUTDIR="$remote_module_out" \
		NQ_HOST=fake NQ_USER=root FAKE_REMOTE_CMDLINE="$good_cmdline" \
		FAKE_REMOTE_MODULE_PARAMS_EXIT=1 \
		FAKE_REMOTE_MODULE_PARAMS_RESULT='mismatch: omap_dma:nq_dump_cyclic=1 actual=0' \
		REQUIRED_REMOTE_MODULE_PARAMS='omap_dma:nq_dump_cyclic=1' \
		"$ROOT/tools/run_audio_legacydma_probe_local.sh"
rg -q 'mismatch: omap_dma:nq_dump_cyclic=1 actual=0' \
	"$remote_module_out/remote-module-params-check.txt"
if find "$remote_module_out" -name '*.wav' | rg -q .; then
	echo "remote module-parameter guard generated WAV before failing" >&2
	exit 1
fi

	rg -q 'fastboot boot "\$DMA_IMAGE"' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'FASTBOOT_BOOT=0 \\' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'mcbsp-txburst16' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'trigger-threshold' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'txburst-trigger-threshold' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'codec-first' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'codec-first-link-only' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'no-trigger-mute' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'snd_soc_omap_mcbsp:nq_tx_burst=\$tx_burst' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'snd_soc_omap_mcbsp:nq_trigger_threshold=\$trigger_threshold' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'snd_soc_tas571x:nq_mute_on_trigger=\$tas_mute_on_trigger' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'snd_soc_steelhead_tas5713:nq_legacy_s16_only=\$NQ_LEGACY_S16_ONLY' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'snd_soc_steelhead_tas5713:nq_codec_power_first=\$codec_power_first' "$ROOT/tools/run_audio_module_reload_sweep_local.sh"
	rg -q 'nq_tx_burst="\$NQ_MCBSP_TX_BURST"' "$ROOT/tools/reload_audio_modules_remote.sh"
	rg -q 'nq_trigger_threshold="\$NQ_MCBSP_TRIGGER_THRESHOLD"' "$ROOT/tools/reload_audio_modules_remote.sh"
	rg -q 'nq_mute_on_trigger="\$NQ_TAS571X_MUTE_ON_TRIGGER"' "$ROOT/tools/reload_audio_modules_remote.sh"
	rg -q 'nq_legacy_s16_only="\$NQ_LEGACY_S16_ONLY"' "$ROOT/tools/reload_audio_modules_remote.sh"
	rg -q 'nq_codec_power_first="\$NQ_STEELHEAD_CODEC_POWER_FIRST"' "$ROOT/tools/reload_audio_modules_remote.sh"
	rg -q 'set_module_param omap_dma nq_dump_irq_limit "\$NQ_DMA_DUMP_IRQ_LIMIT"' "$ROOT/tools/reload_audio_modules_remote.sh"
	rg -q 'interrupts-before.txt' "$ROOT/tools/run_audio_legacydma_probe_local.sh"
	rg -q 'interrupt samples during playback' "$ROOT/tools/run_audio_legacydma_probe_local.sh"
	rg -q 'interrupts-after.txt' "$ROOT/tools/run_audio_legacydma_probe_local.sh"
	rg -q 'NQ_DISCOVER_SSH' "$ROOT/tools/run_audio_module_reload_sweep_when_ready_local.sh"
	rg -q 'ssh-keyscan' "$ROOT/tools/run_audio_module_reload_sweep_when_ready_local.sh"
	rg -q 'known Nexus Q SSH host key' "$ROOT/tools/run_audio_module_reload_sweep_when_ready_local.sh"

	echo "audio-shell-guard-tests-ok"
