# Building

## Host Setup

Validated host:

- macOS
- Android platform-tools
- GNU make
- STM32CubeCLT ARM EABI toolchain
- Homebrew e2fsprogs
- Python 3

The default cross compiler path is:

```sh
/opt/ST/STM32CubeCLT/GNU-tools-for-STM32/bin/arm-none-eabi-
```

Override it if needed:

```sh
export CROSS_COMPILE=/path/to/arm-none-eabi-
export HOST_ELF_H=/path/to/arm-none-eabi/include/elf.h
export MAKE=gmake
export MKE2FS=/opt/homebrew/opt/e2fsprogs/sbin/mke2fs
```

## Source Inputs

Place Linux 6.6.142 at:

```text
kernel/linux-6.6.142
```

For a clean reproducibility check without modifying that working source tree,
copy or extract Linux elsewhere and pass `SRC=/path/to/linux-6.6.142` to the
kernel build scripts.

The release build applies:

```text
patches/linux-6.6.142-nexusq-steelhead.patch
```

That patch adds the Steelhead TAS5713 ASoC machine driver and fixes the TI
composite clock divider rate callbacks needed by the audio clock tree. It also
keeps the Steelhead ABE DPLL reference parent on `sys_clkin_ck`, matching the
vendor 3.0 kernel and fixing the Linux 6.6 TAS5713 speaker flutter. The patch
carries the current McBSP and OMAP SDMA diagnostic toggles used during speaker
quality bring-up.

The build script then copies:

```text
linux66/omap4-steelhead.dts
```

into the kernel tree before building.

## Build Command

```sh
tools/build_release_artifacts_local.sh
```

Outputs:

```text
artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian.img
artifacts/nexusq-debian-trixie-armhf-rootfs.ext4
artifacts/nexusq-debian-trixie-armhf-rootfs.sparse.img
artifacts/SHA256SUMS-v0.2.0.txt
```

The boot image is intended for `fastboot flash boot`. The sparse image is the
one intended for `fastboot flash userdata`. The public release command line does
not include `nq.autoreboot`, so the device boots normally and stays running by
default.

## Audio Diagnostic Build

The current TAS5713 speaker-quality investigation uses non-release boot images
with boot-time toggles for OMAP SDMA cyclic hypotheses.

To test only the cyclic synchronization hypothesis:

```sh
tools/build_audio_dmasync_image_local.sh
```

This emits:

```text
artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-dmasync.img
```

To test the closest current match to the old Steelhead DMA path, including
memory-side-only cyclic burst bits, disabled cyclic packed mode,
old-style McBSP TX-underflow IRQ masking, descriptor logging, hardware DMA
register readback at cyclic load/start, and TAS5713
hardware register readback around codec power/format/mute transitions. It also
replays the TAS5713 legacy reset/init sequence on stream unmute with
`nq.tas571x_legacy_stream_reinit=1`, preserving MCLK after reinit for
Steelhead. The image also logs the Steelhead machine-driver rate calculation
(`format`, `inversion`, `mclk`, `bclk`, and McBSP clock divider) with
`nq.steelhead_audio_dump=1`:

```sh
tools/build_audio_legacydma_image_local.sh
```

This emits:

```text
artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma.img
```

For faster McBSP/TAS5713/ASoC iteration, build the audio-modular diagnostic
image:

```sh
tools/build_audio_modular_image_local.sh
fastboot boot artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-modular.img
```

After it reaches SSH, a driver-only edit cycle can avoid a full reboot:

```sh
tools/build_audio_modules_local.sh
tools/install_audio_modules_remote.sh
tools/reload_audio_modules_remote.sh
```

Set `NQ_MCBSP_NO_XRST_RESET=1` only for the transmitter-ready reset timing
experiment. That test did not fix the distortion because the normal playback
path was not taking the reset branch (`xready=0`).

The reload helper also accepts environment overrides for controlled A/B tests,
including `NQ_TAS571X_LEGACY_STREAM_REINIT=0`,
`NQ_MCBSP_LEGACY_THRESHOLD_FRAME=0`, and, on the DMA-modular image,
`NQ_RELOAD_DMA=1 NQ_DMA_LEGACY_CYCLIC_BLOCK_IRQ=1`. Defaults keep the current
legacy-style diagnostic settings. `NQ_MCBSP_TX_BURST=16` is a reloadable
McBSP-side burst/threshold experiment; it is separate from
`NQ_DMA_CYCLIC_BURST_BITS=16`, which only forces the OMAP SDMA CSDP burst
field. `NQ_MCBSP_TRIGGER_THRESHOLD=1` is another reloadable McBSP experiment
that reapplies the cached FIFO threshold immediately before McBSP trigger/start,
matching the timing of the old downstream PCM path more closely.

There is also an experimental DMA-modular build:

```sh
tools/build_audio_dma_modular_image_local.sh
```

It produces
`artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
and `drivers/dma/ti/omap-dma.ko`. This build embeds `omap-dma.ko` in the
Debian loader initramfs and loads it before the eMMC root handoff, so the same
driver can later be rebuilt and reloaded over SSH. This is currently the
fastest audio debug loop: rebuild modules, install them over SSH, reload the
audio/DMA stack, and run the guarded playback probe without fastboot rebooting
between cases. Full reboots are still needed for device tree, initramfs,
bootargs, or a wedged driver stack.

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_module_reload_sweep_local.sh
```

If the Q is in fastboot, boot the DMA-modular image once and then use module
reloads for all cases:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' FASTBOOT_BOOT=1 \
  tools/run_audio_module_reload_sweep_local.sh
```

If the current device state is unknown, the waiting wrapper polls for SSH or
fastboot and then chooses the right path. It waits forever by default; set
`WAIT_READY_TIMEOUT=600` to stop after ten minutes.

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' \
  tools/run_audio_module_reload_sweep_when_ready_local.sh
```

The waiting wrapper also has conservative SSH discovery enabled by default. If
`NQ_HOST` is stale, it derives a `/24` from `NQ_DISCOVER_KNOWN_HOST`
(`NQ_HOST` by default), scans for open SSH ports, and switches to a candidate
only when `ssh-keyscan` returns the same ED25519 host key already recorded for
that known host in `NQ_KNOWN_HOSTS` (`~/.ssh/known_hosts` by default). Set
`NQ_DISCOVER_SSH=0` to disable this, `NQ_DISCOVER_INTERVAL=120` to reduce scan
frequency, or `NQ_DISCOVER_CIDR=192.168.86.0/24` to choose the scanned subnet
explicitly.

That wrapper builds and installs the DMA/audio modules by default, reloads
`omap-dma`, `snd_soc_ti_sdma`, `snd_soc_omap_mcbsp`, `snd_soc_tas571x`, and the
Steelhead machine driver for each case, and requires the expected remote module
parameters before playback. `FASTBOOT_BOOT=1` is consumed only by the wrapper;
the per-case probe is forced back to `FASTBOOT_BOOT=0`, so the device does not
reboot between audio cases. Set `BUILD_MODULES=0` or `INSTALL_MODULES=0` only
when deliberately reusing an already-built or already-installed module set. It
defaults to the lower debug mixer levels used during the June 13 speaker tests:
`NQ_PROBE_MASTER_VOLUME=180` and `NQ_PROBE_SPEAKER_VOLUME=190`. The DMA reload
path also enables bounded cyclic interrupt logging with
`NQ_DMA_DUMP_IRQ_LIMIT=24` by default, which records the first DMA interrupt
snapshots for each run without logging indefinitely during playback. The
`omap-dma` stop snapshot also records the total callback count and global DMA
IRQ mask/status; the sweep summary exposes these as `scnt`, `simask`, and
`sistat1` so a run can distinguish missing DMA service from distorted output
with normal period callbacks. The
Steelhead TAS5713 codec path defaults to trigger-time mute/unmute sequencing via
`snd_soc_tas571x:nq_mute_on_trigger=-1`, which means "use the Steelhead
compatibility default." This moves the TAS5713 shutdown exit and legacy stream
reinit to the PCM trigger path, closer to the old 3.x codec driver's trigger
power transition. The Steelhead DAI link is marked `nonatomic` because that
trigger-time path can perform I2C writes and TAS5713 reset/shutdown delays. The
default sweep includes `no-trigger-mute`, which reloads the same modules with
`snd_soc_tas571x:nq_mute_on_trigger=0` for a direct A/B comparison without
rebooting. It also includes `codec-first`, which sets
`snd_soc_steelhead_tas5713:nq_codec_power_first=1` and
`snd_soc_tas571x:nq_mute_on_trigger=1` so the Steelhead link trigger runs the
TAS5713 unmute/reinit before dmaengine starts, matching the old 3.x start order
more closely: codec trigger, platform DMA trigger, then McBSP CPU trigger. The
`codec-first-link-only` case keeps `nq_codec_power_first=1` but disables the
later TAS571x DAI trigger mute/unmute with `nq_mute_on_trigger=0`, isolating the
link-trigger codec transition from the modern DAI trigger callback. The
Steelhead TAS5713 machine driver is reloaded with
`snd_soc_steelhead_tas5713:nq_legacy_s16_only=1` by default. This keeps the
modern generic TAS571x codec path constrained to the old Steelhead codec
contract, which advertised stereo `S16_LE` only; set `NQ_LEGACY_S16_ONLY=0`
only when deliberately testing wider ALSA formats. The default module sweep
includes both legacy element-mode DMA and a
`stop-on-underflow` case that enables `snd_soc_omap_mcbsp:nq_stop_on_tx_underflow`.
That case intentionally treats McBSP TX underflow as an ALSA XRUN, matching the
old Steelhead driver's fail-fast behavior so a live run can distinguish FIFO
starvation from a continuously clocked but misframed I2S stream. The sweep also
includes `legacy-burst16`, which explicitly sets the cyclic SDMA CSDP burst
field to 16, and `mcbsp-txburst16`, which forces the McBSP/ASoC TX
`maxburst`/threshold override to 16. The `trigger-threshold` case enables
`snd_soc_omap_mcbsp:nq_trigger_threshold=1`, which writes the same McBSP FIFO
threshold again at PCM trigger time before starting the port. The
`txburst-trigger-threshold` case enables both McBSP-side changes together, so a
single no-reboot run can catch an interaction between FIFO threshold timing and
the old 16-word TX burst sizing. The per-case probe also records
`interrupts-before.txt`, `interrupts-after.txt`, and repeated `/proc/interrupts`
snapshots in `aplay.log` while playback is active. It also includes a
`mainline-packet` case that disables the Nexus Q `nq_legacy_element` McBSP
override. It also includes
`forced-bclk32` and `forced-bclk64`, which reload the Steelhead machine driver
with
`snd_soc_steelhead_tas5713:nq_bclk_fs` set explicitly instead of deriving BCLK
from ALSA physical width. This lets the next live run compare old-style
element sync, fail-fast TX underflow handling, an exact burst-field hypothesis,
McBSP-side TX burst sizing, trigger-time FIFO threshold programming, their
combination, trigger-time TAS5713 mute sequencing, forced BCLK framing, and
codec-first TAS5713 power sequencing, link-trigger-only codec power sequencing,
forced BCLK framing, and mainline
packet-mode McBSP/DMA without another fastboot cycle. Add
`legacy-dma-packet` or `mainline-packet-burst16` to
`RUN_CASES` for hybrid packet-mode runs.

To revisit the earlier DAI format/polarity matrix without rebooting between
each trial, use:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_format_module_sweep_local.sh
```

That wrapper reloads the modular stack for `i2s` and `left_j` with all four
McBSP clock-polarity settings. It intentionally skips `right_j` because the
current OMAP McBSP DAI does not implement right-justified format setup.

After reconnecting the speaker, the guarded local probe runner can generate a
dual-channel 440 Hz WAV, copy it to the device, play it once, and collect ALSA
preflight, McBSP sysfs state, active-playback ALSA status samples, register/DMA
kernel logs, optional microphone capture, and an `audio-summary.txt`:

```sh
NQ_SPEAKER_CONNECTED=1 tools/run_audio_legacydma_probe_local.sh
```

The script refuses to run playback unless `NQ_SPEAKER_CONNECTED=1` is set. It
also checks the running Nexus Q kernel's `/proc/cmdline` before playback and
fails if required diagnostic bootargs are missing, writing
`remote-cmdline-check.txt` in the run directory. Set
`REQUIRE_REMOTE_CMDLINE=0` only for a deliberate stale-kernel comparison. It
records ALSA mixer state and, by default, sets known probe values before
playback: `NQ_PROBE_MASTER_VOLUME=190`, `NQ_PROBE_SPEAKER_VOLUME=204`, and
`NQ_PROBE_SPEAKER_SWITCH=on`. Set `NQ_PROBE_SET_MIXER=0` to leave existing
mixer state untouched. Use `LIST_AUDIO_INPUTS=1` to list Mac ffmpeg/avfoundation
capture devices without playing audio, `FASTBOOT_BOOT=1` to boot the legacydma
image first, and `FFMPEG_INPUT=':0'` to capture a Mac microphone input.
`PROBE_CHANNELS=both` is the default so a single wired speaker is less likely
to miss the test tone; use `PROBE_CHANNELS=left` or `right` for channel-specific
checks. Before collecting `/proc/asound/.../status`, the probe waits for the
PCM state to become `RUNNING` for up to roughly six seconds; if playback exits
or never reaches `RUNNING`, the captured `pcm_state` in the summary makes that
visible. It then records repeated ALSA status samples during playback; the
summary table reports sample count plus first-to-last `hw_ptr` and `appl_ptr`
deltas so stalled PCM/DMA progress is visible without rebooting between cases.

For the current flutter investigation, the same legacy-DMA image can also be
tested with McBSP FIFO threshold mode instead of element mode:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_threshold_probe_local.sh
```

That wrapper sets `NQ_MCBSP_DMA_OP_MODE=threshold` and
`NQ_MCBSP_MAX_TX_THRES=32` before playback by writing the kernel's existing
McBSP sysfs controls. Override `NQ_MCBSP_MAX_TX_THRES` to sweep other values,
for example `2`, `4`, `16`, `64`, or `128`. The generic probe also accepts
`APLAY_EXTRA_ARGS`, such as `--period-size=1024 --buffer-size=4096`, when ALSA
period geometry needs to be held constant between runs. Requested McBSP sysfs
controls are mandatory: if a control is missing or rejects the value, the probe
aborts before playback instead of silently running the wrong mode.

To run the element-mode baseline plus a threshold sweep in one guarded pass:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_probe_sweep_local.sh
```

The sweep requires `FFMPEG_INPUT` by default because the goal is comparing
actual speaker output. Set `REQUIRE_MIC=0` only for a deliberate no-microphone
smoke run; those runs will be marked `no-mic` and cannot prove audio quality.
The current sweep also includes `01-threshold-frame` by default. That run uses
threshold mode without forcing a small TX threshold and passes
`--period-size=512 --buffer-size=2048` to `aplay`, which should exercise the
`nq.mcbsp_legacy_threshold_frame=1` kernel diagnostic path. That path emulates
the old 3.x behavior where a period that fits within the McBSP FIFO threshold
uses a period-sized McBSP threshold instead of packet-sized DMA bursts.

The sweep writes `artifacts/audio-sweep-*`, including one probe directory per
mode, per-run `sweep-status.txt` files, and
`sweep-summary.txt`/`sweep-summary.json`. It also writes
`sweep-triage.txt`/`sweep-triage.json`, which summarize whether there is a
candidate and what to inspect next. Triage output also records the top run's
McBSP/period settings, DMA health, and a guarded one-run retest command, so a
promising configuration can be rechecked before being promoted into the default
audio path. When a run came from `tools/run_audio_module_reload_sweep_local.sh`,
triage also prints a `module_retest:` command. That command keeps
`FASTBOOT_BOOT=0` and skips rebuild/reinstall work, so it is the fastest way to
repeat one modular case after the DMA-modular image is already booted. Fresh
DMA-modular runs include a `dma:` triage line that separates missing period
callbacks, masked DMA IRQs, and normal callback service with remaining
distorted output. Fresh runs also include a `pcm:` triage line when active ALSA
status samples are available; this separates stalled `hw_ptr`, missing active
samples, and normal PCM pointer progress. Fresh McBSP diagnostics also emit and
summarize `nq mcbsp stop` state, including stop-time IRQ/FIFO fields, so a run
can distinguish clean pointer/DMA progress from a McBSP stop with pending IRQ
status. The summary compares microphone captures
against the local June 12 bad-output baseline when
`artifacts/audio-baselines/jun12-bad-capture-expected-440.json` is present:
`env_x` is the baseline `envelope_cv_25ms` divided by the run's
`envelope_cv_25ms`, so values greater than `1.0` are better than the known-bad
flutter capture. The table also reports the accepted ALSA PCM hw params
(`pcm_fmt`, `pcm_rate`, `pcm_ch`, `period`, and `buffer`) plus live PCM status
(`pcm_state`, `delay`, `avail`, `avail_max`, `hwptr`, and `applptr`) captured
from `/proc/asound` during playback, the actual McBSP sysfs readback for
`dma_op_mode` and `max_tx_thres`, the McBSP hw-params diagnostic
(`mhw`, `frame`, `pwords`, `pkt`, `thw`) from `nq mcbsp hw` lines, TAS5713
stream-reinit evidence (`reinit`, `kmclk`) from
`nq tas571x legacy-stream-reinit` lines, trigger-mute evidence (`tmute`) from
the `nq tas571x probe` line, codec-power-first evidence (`cpwr`) from the
`nq steelhead trigger` line or the per-case plan, the logged cyclic DMA
descriptor's
`sig`, `ccr`, and `csdp` fields, the hardware-readback `rccr`, `rcsdp`, and
`rclnk` fields captured after `CCR.EN` when `nq.omap_dma_dump_cyclic=1`
produced `nq cyclic` and `nq dma-start` lines, bounded DMA IRQ diagnostics
(`icnt`, `istat`, `iavg_ms`, `imax_ms`), stop-time DMA callback/IRQ state
(`scnt`, `simask`, `sistat1`), `/proc/interrupts` progress
(`pisamp`, `pidelta`, `pba_delta`, `pitop`) from active playback and
before/after snapshots, trigger/event ordering (`seq`, `d2m_ms`, `m2irq_ms`)
from TAS5713 reinit/unmute, DMA start, McBSP start, and first DMA IRQ lines,
McBSP FIFO/IRQ readbacks
(`irqen`, `irqst`, `xbuf`, `rbuf`, `thr2`, `thr1`) from the register dump,
McBSP stop-state readbacks (`stirq`, `stxbuf`, `strbuf`, and `stspcr2`) from
the `nq mcbsp stop` line,
Steelhead machine-driver `fmt`/`inv`/`s16`/`bclk`/`div`/`mclk` fields when
`nq.steelhead_audio_dump=1` produced `nq steelhead` lines, and TAS5713
readbacks for `sdi`, `sys2`, `err`, and `mvol` when
`nq.tas571x_dump_regs=1` produced `nq tas571x` lines. The TAS5713 stop path
also emits a `pre-mute` snapshot before asserting shutdown, summarized as
`pm_sys2` and `pm_err`, so playback-time codec faults are not hidden by the
mute transition. A `candidate` verdict
means the run had mic metrics, exit status `0`, matching requested/readback
McBSP sysfs values, TAS5713 stream-reinit evidence with `reinit=1` and
`kmclk=1`, microphone RMS at or above `0.003`,
`envelope_cv_25ms <= 0.20`, carrier error within `1%`, harmonic ratio at or
below `0.05`, clipping at or below `1%`, `envelope_low_pct_25ms <= 10%`, and
`envelope_peak_to_trough_db_25ms <= 6 dB`, with no flagged ALSA/McBSP/DMA/
TAS5713 kernel events. The special `threshold-frame` run must also show
`frame=1`, `pkt=0`, and `thw` equal to `pwords`. Low-level mic captures are
marked `quiet`; runs without microphone metrics are marked `no-mic`. Missing
diagnostic evidence is marked with verdicts such as `tas-reinit-missing`,
`threshold-frame-missing`, `threshold-frame-packet`, or
`threshold-frame-threshold`. The summary table reports `rms` and `tone`
(`expected_tone_rms`) so silence/no-signal cases are distinct from distorted
output. The summary's `kernel` column flags runtime issues such as `xrun`,
`sync`, `alsa-error`, `codec-error`, or `dma-error`. It still needs a
listening check before calling audio fixed.

For element-mode ALSA period/buffer tests, use:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' tools/run_audio_period_sweep_local.sh
```

The June 13 low-volume period sweep did not find a clean setting. Default and
large periods still produced flutter/dropout/pumping verdicts, while smaller
periods such as `256:1024` and `1024:4096` added ALSA underruns.

Override `THRESHOLDS` to change the tested FIFO thresholds, for example:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' THRESHOLDS="2 4 8 16 32 64" \
  tools/run_audio_probe_sweep_local.sh
```

Use `PROBE_CHANNELS=left` or `right` with the sweep only when intentionally
checking channel mapping. The default `both` is the preferred quality test with
one external speaker connected.

When a microphone capture is present, the probe also writes
`mic-capture-analysis.txt` and `mic-capture-analysis.json` with simple
frequency, harmonic, clipping, and 25 ms envelope-variation metrics. Existing
captures can be analyzed manually:

```sh
tools/analyze_audio_probe_capture.py --expected 440 path/to/capture.m4a
tools/analyze_audio_probe_capture.py --json --expected 440 path/to/capture.m4a
tools/summarize_audio_probe_runs.py artifacts/audio-sweep-YYYYMMDD-HHMMSS
tools/triage_audio_sweep.py artifacts/audio-sweep-YYYYMMDD-HHMMSS
```

Offline analyzer and summarizer behavior can be regression-tested without the
device or speaker:

```sh
tools/test_audio_offline_local.sh
tools/test_audio_analysis.py
tools/test_audio_shell_guards.sh
tools/check_tas5713_init_parity.py
```

The combined offline runner performs shell syntax checks, Python syntax checks,
the analyzer/triage regression, TAS5713 init table parity, the shell guard
regression, no-playback preflight, and `git diff --check` for non-kernel-patch files. The analyzer test checks
synthetic sine/square/flutter metrics, threshold-run ranking, McBSP sysfs
readback parsing, cyclic DMA descriptor and DMA start-register parsing,
low-level/quiet verdict handling, kernel-event verdict flags, and failed-run
handling. The shell guard test uses fake boot images and fake SSH to verify
local image cmdline validation and stale remote-kernel refusal without
contacting the Nexus Q or generating playback audio.
The TAS5713 parity check parses the old 3.0 Steelhead
`tas5713_reg_init.h` table and the Linux 6.6 `steelhead_tas5713_init_sequence`
and fails if the raw codec initialization bytes diverge.

Before reconnecting the speaker for a live sweep, run the no-playback preflight:

```sh
FFMPEG_INPUT=':0' tools/check_audio_probe_prereqs_local.sh
```

It checks host commands, required diagnostic artifacts, executable probe tools,
the offline audio-analysis tests, the offline shell guard tests, TAS5713 init
table parity, and the diagnostic boot image command line. The broader
`tools/test_audio_offline_local.sh` wrapper also dry-runs the tracked Linux
6.6.142 patch against `build/patch-pristine/linux-6.6.142`, so clean-source
reproduction failures are caught before a live speaker run. By default, the
preflight fails if the image is missing any required audio bootarg or if the
extracted boot-image command line exceeds the Android boot image 512-byte
limit. Set `CHECK_IMAGE_CMDLINE=0` only when intentionally validating a
stale or experimental image.

For the current low-level McBSP/TAS5713 bring-up, prefer the focused safe PIO
runner before any broad module sweep:

```sh
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' \
  tools/run_audio_pio_when_ready_local.sh
```

It waits for SSH or fastboot, boots the DMA-modular diagnostic image when
fastboot is present, installs the current audio modules, starts the rootfs
watchdog feeder, arms the userspace return-to-fastboot timer, reloads
timer-only McBSP PIO diagnostics, captures a low-volume left-channel 440 Hz
probe through the Mac microphone, and summarizes the result. The diagnostic
image uses a bounded initramfs watchdog boot lease (`nq.watchdog=60`,
`nq.watchdog_boot_grace=240`) so a boot that never reaches SSH can reset
itself, while the rootfs feeder keeps healthy short experiments from being
interrupted. Set `NQ_PIO_LEGACY_CODEC=1` to repeat the same PIO test while
skipping modern TAS571x codec DAI `set_fmt` and `hw_params` programming, which
matches the old Steelhead 3.0 codec-driver shape more closely.
Set `RUN_AUDIO_ANALYSIS_TESTS=0` or
`RUN_AUDIO_SHELL_GUARD_TESTS=0` only when deliberately skipping those offline
regression suites. `tools/run_audio_probe_sweep_local.sh` also runs this
preflight by default before any fastboot, SSH, file copy, or playback step; set
`RUN_PREFLIGHT=0` only after a deliberate separate preflight run. Optional
read-only checks:

```sh
LIST_AUDIO_INPUTS=1 tools/check_audio_probe_prereqs_local.sh
CHECK_SSH=1 tools/check_audio_probe_prereqs_local.sh
```

`LIST_AUDIO_INPUTS=1` lists Mac ffmpeg/avfoundation inputs without playback.
`CHECK_SSH=1` verifies SSH only and does not copy or play audio. Set
`REQUIRE_MIC=0` for preflight checks that intentionally skip Mac microphone
configuration.

The distorted June 12 MacBook microphone capture is locally analyzed under
`artifacts/audio-baselines/`. Treat its 440 Hz interpretation as the current
bad-output baseline: zero-cross carrier `457.208 Hz`, no clipping, and
`envelope_cv_25ms: 0.632408`,
`envelope_low_pct_25ms: 28.5714`, and
`envelope_peak_to_trough_db_25ms: 23.3157`. The next live-speaker probe should
reduce the envelope variation substantially while keeping the carrier near
440 Hz.

The current legacy-DMA image also logs one `nq mcbsp start ...` line per
playback start when the Nexus Q audio diagnostic bootargs are enabled. The
probe summarizer reports `xrdy`, `xrst`, `rrdy`, and `rrst` so the next
microphone sweep can distinguish a bad analog result from a McBSP startup path
that never reached the legacy ready-reset sequence.

The guarded sweep's legacy frame-threshold case uses
`LEGACY_FRAME_MAX_TX_THRES=112` with
`LEGACY_FRAME_APLAY_EXTRA_ARGS='--period-size=56 --buffer-size=672'`. For S16
stereo this gives `period_words=112`, matching McBSP2's exposed TX threshold
limit, so the kernel should log `legacy_threshold_frame=1`, `pkt_size=0`, and
`threshold_words=112`. Larger period sizes such as 512 frames do not exercise
that path on this board.

To prove the image can be reproduced from a clean kernel source plus the tracked
patch:

```sh
cp -R build/patch-pristine/linux-6.6.142 /tmp/nq-linux-6.6.142-legacydma-repro-src
SRC=/tmp/nq-linux-6.6.142-legacydma-repro-src \
OUT="$PWD/build/linux-6.6-omap2plus-steelhead-nosmp-audio-wifi-public-debian-legacydma-repro" \
IMAGE="$PWD/artifacts/nexusq-linux66-omap2plus-nosmp-audio-wifi-public-debian-legacydma-repro.img" \
ZIMAGE_DTB="$PWD/artifacts/linux66-omap2plus-steelhead-nosmp-audio-wifi-public-debian-legacydma-repro-zImage-dtb" \
  tools/build_audio_legacydma_image_local.sh
```

## What The Build Does

1. Rebuilds a Debian 13 `trixie` armhf rootfs by resolving package metadata and
   extracting selected `.deb` archives.
2. Builds the Debian loader initramfs.
3. Builds Linux 6.6.142 with no SMP, USB ACM+ECM, TAS5713 audio, and modular
   Broadcom FullMAC Wi-Fi.
4. Builds only the `drivers/net/wireless/broadcom/brcm80211` module subtree.
5. Installs `brcmutil.ko`, `brcmfmac.ko`, and the Broadcom helper modules into
   the rootfs.
6. Creates raw ext4 and Android sparse `userdata` images.

## Firmware Policy

The public kernel image does not embed `.secrets/nexusq-firmware`.

The Debian rootfs includes Debian's `firmware-brcm80211` package for
`brcmfmac4330-sdio.bin`. Device calibration is prepared at first Wi-Fi startup:

- copy `/etc/wifi/bcmdhd.cal` from the stock Android `system` partition when
  `/dev/mmcblk0p11` is still intact;
- write it as
  `/lib/firmware/brcm/brcmfmac4330-sdio.google,steelhead.txt`;
- also write the generic `brcmfmac4330-sdio.txt` fallback.

If the stock system partition is missing, provide the NVRAM text file manually
inside the rootfs before starting Wi-Fi.
