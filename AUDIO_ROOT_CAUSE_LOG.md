# Nexus Q Audio Root-Cause Log

Last updated: 2026-06-16

## Goal

Get left-channel speaker playback on the Nexus Q sounding correct on the Linux
6.6 port, starting with raw PCM and only then moving back up to MP3/music
playback.

The immediate success condition is simple:

- A 440 Hz raw PCM sine played through the left channel sounds continuous.
- No audible pulsing, flutter, wobble, or square-wave-like distortion.
- The same path can then play a normal stereo WAV/MP3 without choppiness.

Right-channel behavior is explicitly out of scope until the left channel is
fixed.

## Current Safety State

- The device can still recover to fastboot.
- The device is currently reachable in the Linux 6.6 image over USB SSH at
  `root@fe80::16:42ff:fe00:2%en12`. The Mac currently has a stale IPv4
  `169.254.42.2` host route pinned to Wi-Fi, so use IPv6 unless that route is
  repaired.
- The current boot is the rebuilt DMA-modular image with the corrected
  `omap_dma.nq_audio_tone` diagnostic available.
- The watchdog feeder was started after boot. Keep it running for normal
  SSH-safe tests, but remember the hardware watchdog is still armed.
- The Linux 3.0 comparison image is reachable at `169.254.42.2` over USB
  networking when that image is booted. Telnet shell is then available on
  `169.254.42.2:2323`.
- The 3.0 comparison image has an auto-fastboot fallback in its boot command
  line: `nq.autoreboot=600 panic=30 oops=panic`.
- If the 3.0 image is running, return it to fastboot with
  `/bin/nq-reboot-fastboot`.
- The most recent risky branch is PIO. IRQ-driven PIO wedged SSH and recovered
  to fastboot. A later quiet timer50 PIO attempt also lost SSH and recovered to
  fastboot before producing an artifact. Do not repeat these PIO variants
  without redesigning the harness.

Volume discipline for further speaker tests:

- Use `NQ_PROBE_MASTER_VOLUME=180`.
- Use `NQ_PROBE_SPEAKER_VOLUME=180`.
- Use `TONE_AMP=0.02` for long comparison captures. `0.03` is acceptable for
  short human-listening probes, but do not keep increasing it.
- Do not increase volume as a debugging shortcut.

## Operating Rules From Here

- Every experiment must have one hypothesis and one stop condition.
- Do not run broad 6.6 audio parameter sweeps. Use one bounded A/B at a time
  with the same low-volume raw PCM source unless the hypothesis requires
  otherwise.
- Always capture the exact command, image, module set, source WAV, and register
  evidence in an artifact directory.
- Update this file after each meaningful experiment before starting another.
- Keep the acceptance gate human and simple: the left-channel 440 Hz tone must
  sound continuous, with no wobble.

## Working Assumptions

- Audio was good on the vendor Linux 3.0/Android path, so the speaker, amp, and
  basic board wiring are assumed good.
- The Linux 3.0 500 Hz raw tone heard clean by the user is now the control.
  The 6.6 wobble is therefore treated as a port regression until proven
  otherwise.
- The user has one left speaker wired. Tests and conclusions should focus on
  left-channel output.
- The audible wobble is real. The Mac microphone analysis is useful supporting
  evidence, but the user hearing the wobble is the primary acceptance signal.

## Artifacts

Experiment artifacts are under `artifacts/audio-rootcause-*`. Each useful run
usually contains:

- `source-wav-analysis.txt`: host-generated WAV sanity check.
- `mic-capture-analysis.txt`: Mac microphone analysis.
- `audio-kernel-events.txt`: filtered kernel events during playback.
- `dmesg-delta.txt`: full kernel log delta.
- `module-params.txt`: runtime module parameter state.
- `aplay.log`: playback command output and captured device diagnostics.

Key artifacts referenced below:

- `artifacts/nexusq-linux30-rescue-audio-baseline-autofastboot.img`
- `artifacts/audio-rootcause-linux30-known-good-20260614-125903`
- `artifacts/audio-rootcause-linux30-known-good-20260614-130922`
- `artifacts/audio-rootcause-linux66-compare-20260614-131448`
- `artifacts/audio-rootcause-linux66-legacy-compare-20260614-131639`
- `artifacts/audio-rootcause-linux66-period2064-20260614-131905`
- `artifacts/audio-rootcause-linux66-period1032-20260614-132006`
- `artifacts/audio-rootcause-linux66-period1032-controlled-20260614-132456`
- `artifacts/audio-rootcause-linux66-period1032-async0-20260614-132944`
- `artifacts/audio-rootcause-linux66-period1032-pcmstatus-20260614-133516`
- `artifacts/audio-rootcause-linux66-byteswap16-safe-20260614-134912`
- `artifacts/audio-rootcause-pio-dxr-fix-20260614-135443`
- `artifacts/audio-rootcause-pio-detached-20260614-140445`
- `artifacts/audio-rootcause-pio-detached-timer50-20260614-140916`
- `artifacts/audio-rootcause-dma-kernel-tone-20260614-150220`
- `artifacts/audio-rootcause-dma-kernel-tone-fixed-20260614-150623`
- `artifacts/audio-rootcause-dma-kernel-tone-period1032-20260614-150848`
- `artifacts/audio-rootcause-dma-kernel-tone-period1032-dualmono-20260614-151023`
- `artifacts/audio-rootcause-dma-kernel-tone-codec-power-first-20260614-151435`
- `artifacts/audio-rootcause-dma-kernel-tone-master-only-gain-20260614-151810`
- `artifacts/audio-rootcause-dma-kernel-tone-noirq-20260614-152622`
- `artifacts/audio-rootcause-dma-kernel-tone-codec-inert-20260614-152906`
- `artifacts/audio-rootcause-dma-kernel-tone-codec-mclk-owned-20260614-153233`
- `artifacts/audio-rootcause-dma-kernel-tone-buffer24000-20260614-153642`
- `artifacts/audio-rootcause-lowvol-element-after-fifo-label-20260614-122336`
- `artifacts/audio-rootcause-mclkcycle-lowvol-20260614-122656`
- `artifacts/audio-rootcause-burst64-lowvol-20260614-122921`
- `artifacts/audio-rootcause-flatdsp-lowvol-20260614-123116`
- `artifacts/audio-rootcause-async-trigger-lowvol-20260614-123453`
- `artifacts/audio-rootcause-forcexrst100-lowvol-20260614-123858`
- `artifacts/audio-rootcause-codecfmt-lowvol-20260614-124041`
- `artifacts/audio-rootcause-pio-xrdy-lowvol-20260614-124249`

## Experiment Log

2026-06-14 restart note:

- The current target is not "less bad"; it is a clean continuous tone on 6.6.
- Broad parameter sweeps and volume changes are stopped.
- The 3.0 baseline produced a clean tone with McBSP2 and TAS5713 key registers
  matching the intended configuration.
- Multiple 6.6 paths still wobble, including userspace WAV, old tinyalsa-style
  playback, and an in-kernel DMA-backed tone. That keeps the fault below normal
  ALSA/userspace refill.
- PIO diagnostics are not accepted as evidence because they underflowed and one
  prefill attempt wedged the board. Leave PIO off unless the harness is
  redesigned.
- Next discriminator: force the 6.6 McBSP2 TX DMA request 17 onto physical SDMA
  logical channel 0, matching the clean 3.0 baseline, then compare register
  state and human audio. If this is clean, focus on SDMA channel allocation or
  channel priority/reservation behavior. If it still wobbles, stop blaming ALSA
  pacing or the selected physical channel and move to serial timing/McBSP
  start-order differences.
- First forced-channel attempt did not reach audio playback: channel 0 was
  already mapped before the McBSP2 TX request was allocated, so
  `omap-mcbsp` failed card registration with `Missing dma channel for stream:
  0`. Next step is allocation-owner logging, not speaker playback.
- Fresh rebuilt image with allocation-owner logging shows early SDMA assignment
  order before audio: request 36 takes logical channel 0, followed by request
  35 on channel 1, then 38/37/40/39/42/41/44/43/46/45, etc. This explains why
  post-boot forcing request 17 to channel 0 fails. The next valid test must
  reserve channel 0 from module load for request 17 before those early clients
  allocate channels.
- An attempted marker-file version packed `/etc/nq-force-lch-sig` and
  `/etc/nq-force-lch` into the initramfs, but the live module parameters still
  came up as `nq_force_lch_sig=0` and `nq_force_lch=-1`. Treat the marker
  plumbing as unresolved and use compiled diagnostic defaults for the immediate
  SDMA-channel discriminator.
- Compiled diagnostic defaults succeeded: live module parameters show
  `nq_force_lch_sig=17` and `nq_force_lch=0`; early request 36 skips channel 0
  and allocates channel 1; McBSP2 TX request 17 then allocates channel 0 and
  the Steelhead TAS5713 card registers. Next evidence is a single low-volume
  raw PCM left-tone playback on this channel-0 setup.
- First channel-0 raw PCM run:
  `artifacts/audio-rootcause-linux66-force-lch0-500hz-amp02-20260614-175329`.
  Kernel playback completed (`aplay_status=0`) with TX DMA channel 0, no ALSA
  underrun, no DMA error, and McBSP/TAS5713 register geometry matching the
  expected path. Mic capture is not decisive because the captured 500 Hz
  component is too quiet relative to room/mic noise. Envelope modulation is much
  lower than the prior bad 6.6 capture, but this still needs a louder capture
  or direct human listening confirmation before calling the wobble fixed.
- Follow-up channel-0 captures at amp `0.05` and `0.10` also completed without
  kernel playback errors, but Mac mic analysis still did not isolate a strong
  500 Hz component. Do not keep increasing volume. Next software-only
  discriminator is channel 0 plus the old 3.0 DMA period geometry (`CEN=2064`,
  `CFN=4`) instead of the large `CEN=12000` period used by the first channel-0
  probe.
- Channel 0 plus old period geometry:
  `artifacts/audio-rootcause-linux66-force-lch0-period1032-500hz-amp05-20260614-175655`.
  Playback completed with `CEN=2064`, `CFN=4`, `CDSA=0x49024008`,
  `CLNK=0x8000`, and no kernel underrun/DMA failure. This now matches the key
  3.0 DMA shape while preserving the 6.6 McBSP/TAS path. Mic capture remains
  too weak/noisy for acceptance. If user reports wobble persists, stop blaming
  physical SDMA channel or ALSA period geometry and focus on McBSP/TAS serial
  timing, especially the persistent 6.6 `IRQST=0x0710` vs 3.0 `0x0700`.
- User confirmation after the next reboot/test cycle: the 500 Hz tone produced
  under the channel 0 / period 1032 condition sounded clean. Treat this as the
  first accepted 6.6 low-level audio pass, and treat the prior wobble as a 6.6
  port regression rather than a speaker, source-file, or listener issue.
- First music-content climb from the passing condition decoded
  `/root/into-the-oceans-and-the-air.mp3` to WAV and played 12 seconds with
  `aplay -D hw:0,0 --period-size=1032 --buffer-size=4128`. Artifact:
  `artifacts/audio-rootcause-linux66-force-lch0-period1032-song-20260614-180142`.
  The kernel-side run stayed on SDMA channel 0 with `period_size=1032`,
  `buffer_size=4128`, `CEN=2064`, `CFN=4`, and 12 sampled PCM states in
  `RUNNING`; no ALSA underrun/xrun/error was logged. Audible quality still needs
  the user's ear verdict for this song run.
- After the user reported flutter in the later full validation run, retried the
  simplest fixed tone only. Artifact:
  `artifacts/audio-rootcause-retry-fixed-tone-20260614-190116`. This used the
  same forced SDMA channel 0 and period geometry (`CEN=2064`, `CFN=4`), with
  later clock-lifecycle cleanup still active (`nq_codec_mclk_startup=0`,
  `nq_mcbsp_clk_startup=0`). ALSA returned success and the PCM closed cleanly.
  Audible verdict is pending.
- Retried the exact older "clean" clock-startup condition for one tone by
  temporarily enabling `nq_codec_mclk_startup=1` and
  `nq_mcbsp_clk_startup=1`. Artifact:
  `artifacts/audio-rootcause-retry-fixed-tone-clockstartup-20260614-190212`.
  ALSA returned success, but this reproduced the known clock warning
  (`abe-clkctrl:0030:26 already disabled`) on shutdown, so the hook is useful as
  a discriminator but not acceptable as the final fix. Audible verdict is
  pending.

| Area | Test | Result | Conclusion |
| --- | --- | --- | --- |
| Source WAV | Generated 440 Hz S16_LE left-channel WAV and analyzed it before upload. | Source has stable envelope and near-exact 440 Hz tone. | The test source is not causing the wobble. |
| DMA FIFO status | Renamed misleading FIFO counters from `zero_*` to `free0_*` after confirming `XBUFFSTAT==0` means 0 free TX FIFO slots. | FIFO is usually full or almost full during bad playback. | The bad sound is not explained by obvious McBSP TX starvation. |
| DMA burst mapping | Tested modern `nq_cyclic_burst_bits=64`, matching old `OMAP_DMA_DATA_BURST_16` CSDP bits better than `16`. | CSDP became `0x00000181`, but wobble remained. | Burst mapping mismatch was real, but not the root cause by itself. |
| DMA/period behavior | Tested larger periods, element mode, legacy cyclic sync/pack/block IRQ combinations. | `aplay_status=0`; DMA callbacks and stop logs looked coherent. | No clear evidence yet that ALSA period cadence is the wobble source. |
| McBSP clocks | Checked live clock tree. | `dpll_per_m3x2_ck=61.44 MHz`, `auxclk1_ck=12.288 MHz`, `abe_24m_fclk=24.576 MHz`, McBSP fck/sync at `24.576 MHz`. | Obvious clock rates match the vendor board-file intent. |
| McBSP divider | Confirmed 48 kHz S16 stereo uses 24.576 MHz / 16 = 1.536 MHz BCLK and 32 BCLK per frame. | Logs show `bclk=1536000 div=16 bclk_fs=32`. | The nominal sample-rate math is exact. |
| McBSP register parity | Compared static modern register values to the vendor 3.0 setup. | RCR/XCR/SRGR/PCR/XCCR/RCCR values match the obvious old configuration. | A simple static register mismatch is unlikely, but dynamic sequencing may still differ. |
| Runtime PM | Sampled McBSP runtime PM during playback. | McBSP and target module were `active` during playback. | Runtime autosuspend is not currently the lead suspect. |
| TAS5713 error polling | Polled TAS error/sys2 registers while playback was bad. | `err_nonzero=0`, `last_err=0x00`, `last_sys2=0x00`. | The codec is not reporting an obvious clock/input/backend fault. |
| TAS DSP/EQ/DRC | Forced flat DSP path with DRC disabled. | Wobble remained. | TAS EQ/DRC coefficients are not the root cause. |
| TAS/MCLK reset sequencing | Tried cycling/altering MCLK around legacy reset. | Wobble remained. | MCLK reset ordering alone is not the root cause. |
| TAS stream timing | Moved closer to old async trigger behavior using delayed legacy stream reinit/unmute after McBSP/DMA start. | Slightly less bad in one run, still wobbled. | Timing may matter, but this did not fix the problem. |
| TAS codec DAI format | Enabled codec `set_fmt`/`hw_params` instead of skipping it; SDI stayed `0x03`. | Wobble remained. | Modern codec hw_params skipping is not the root cause. |
| McBSP forced XRST | Added `nq_force_xrst_reset_us` and forced a delayed XRST pulse after startup. | Pulse fired; wobble remained. | Startup XRST timing alone is not the root cause. |
| PIO XRDY path | Tried kernel-generated PIO sine paced by McBSP `XRDY`, disabling TX DMA for audio data. | Device/SSH wedged; fallback recovered to fastboot. | Do not repeat this implementation. It is too intrusive and not a useful safe diagnostic. |
| Linux 3.0 comparison image | Booted `artifacts/nexusq-linux30-rescue-audio-baseline-autofastboot.img`. | Linux 3.0.8 boots, USB networking works at `169.254.42.2`, telnet works, and ALSA card 2 is `Steelhead TAS5713 Card`. | The old kernel can now be used as the baseline comparison target. |
| Linux 3.0 first baseline capture | Played the same low-amplitude 48 kHz S16_LE left-channel WAV through `nqstreamd` and captured TAS5713 debugfs state. | Artifact saved at `artifacts/audio-rootcause-linux30-known-good-20260614-125903`, but mic capture was very quiet and the McBSP dump used the wrong address. | Baseline boot path is good, but this first capture is not sufficient for root cause. Rerun with the correct McBSP2 address. |
| McBSP instance audit | Checked vendor 3.0 hwmod data and Linux 6.6 DTS. | Vendor 3.0 McBSP1 is `0x40122000`/`0x49022000`; vendor 3.0 McBSP2 is `0x40124000`/`0x49024000`. Linux 6.6 `mcbsp2` also maps target-module `@24000`, with DMA address `0x49024000`. | Any dump or log treating `0x40122000` as McBSP2 is wrong. The next capture must use `0x40124000` and must verify the live 6.6 card is bound to `mcbsp2`. |
| Linux 3.0 corrected McBSP2 capture | Added `tools/capture_linux30_audio_baseline_local.sh` and reran the low-amplitude WAV through `nqstreamd`. | Artifact saved at `artifacts/audio-rootcause-linux30-known-good-20260614-130922`. During playback, McBSP2 at `0x40124000` read cleanly: `SPCR2=0x2f5`, `SPCR1=0x30`, `XCR2/RCR2=0x8041`, `SRGR2=0x101f`, `SRGR1=0x0f0f`, `PCR0=0x0f0f`, `XCCR=0x1008`, `RCCR=0x0809`, `XBUFFSTAT=0`. Active SDMA channel 0 wrote to `CDSA=0x49024008` with `CCR=0x1091`, `CICR=0x092a`, `CSDP=0x0181`, `CEN=0x0810`, `CFN=4`. | We now have a usable 3.0 low-level register baseline for comparison. The audible known-good baseline is still not proven in this rescue path because TAS master volume stayed `0xff`. |
| Linux 6.6 live path audit | Booted `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`, installed audio modules, and checked live sysfs/devicetree before playback. | Live device path is `/sys/devices/.../4012408c.target-module/40124000.mcbsp`, pinmux consumer is `platform:40124000.mcbsp`, and `sound-tas5713/google,mcbsp` resolves to the `target-module@24000` McBSP2 node. | The 6.6 DTS/machine-driver path is not accidentally using McBSP1. H0 is mostly closed. |
| Linux 6.6 default-module comparison | Added `tools/capture_linux66_audio_compare_local.sh` and captured a low-volume 20 s left-channel `aplay` run before reloading legacy module parameters. | Artifact saved at `artifacts/audio-rootcause-linux66-compare-20260614-131448`. It proved McBSP2 and the source WAV were good, but module params were defaults: `nq_legacy_element=N`, `nq_audio_format=(null)`, TAS dump off. | Useful only as a harness/path check. Do not use it as the main 3.0 comparison. |
| Linux 6.6 legacy-parameter comparison | Reloaded modules with `tools/reload_audio_modules_remote.sh` and reran the low-volume 20 s left-channel `aplay` comparison. | Artifact saved at `artifacts/audio-rootcause-linux66-legacy-compare-20260614-131639`. Module params match the intended diagnostic config. McBSP2 serial registers nearly match 3.0: `RCR/XCR/SRGR/PCR/XCCR/RCCR/THRSH/IRQEN` all align; 6.6 has `SPCR2=0x2f7` vs 3.0 `0x2f5`, `IRQST=0x710` vs `0x700`, `XBUFFSTAT=1` vs `0`. Active McBSP2 TX DMA channel 20 has `CCR=0x1091`, `CICR=0x092a`, `CSDP=0x0181`, `CDSA=0x49024008`, matching the important 3.0 TX path. Material remaining deltas are `CLNK=0x8014` vs 3.0 `0x8000`, and period geometry: 6.6 `CEN=0x2ee0`, `CCEN=0x11c8`, while 3.0 had `CEN=0x0810`, `CCEN=0x06dc`. | McBSP instance, clocking, format, and DMA destination are no longer the lead. The next lead is DMA cyclic linking/period-boundary behavior. |
| Linux 6.6 period-size 2064 | Ran `tools/capture_linux66_audio_compare_local.sh` with `APLAY_EXTRA_ARGS='--period-size=2064 --buffer-size=8256'` and Mac mic capture. | Artifact saved at `artifacts/audio-rootcause-linux66-period2064-20260614-131905`. DMA `CEN=0x1020`, exactly double the Linux 3.0 `0x0810`, meaning ALSA period-size is counted in stereo frames while OMAP DMA `CEN` is counted in 16-bit elements. Mic capture was low-SNR: tone-to-RMS around `-39 dB`, zero-cross estimate not trustworthy. | `period-size=2064` does not match the 3.0 DMA geometry; use `period-size=1032` for that. |
| Linux 6.6 period-size 1032 | Ran `tools/capture_linux66_audio_compare_local.sh` with `APLAY_EXTRA_ARGS='--period-size=1032 --buffer-size=4128'` and Mac mic capture. | Artifact saved at `artifacts/audio-rootcause-linux66-period1032-20260614-132006`. DMA channel 20 now matches the 3.0 geometry: `CEN=0x0810`, `CFN=4`, `CSDP=0x0181`, `CICR=0x092a`, `CDSA=0x49024008`, `CDEI/CDFI=0`. McBSP serial registers match 3.0 except `IRQST=0x710` vs `0x700`; `XBUFFSTAT` sampled as `1` in this run. Mic capture remained low-SNR: tone-to-RMS around `-42 dB`, so it cannot be used as proof of audio quality. | The software register path is now very close to the old 3.0 baseline. Further software guessing has lower expected value than either human confirmation on this specific run or direct BCLK/LRCLK/DATA/MCLK measurement. |
| DMA self-link audit | Checked old 3.0 `sound/soc/omap/omap-pcm.c` and 6.6 `drivers/dma/ti/omap-dma.c`. | Linux 3.0 explicitly calls `omap_dma_link_lch(prtd->dma_ch, prtd->dma_ch)`, so old `CLNK=0x8000` is self-link on channel 0. Linux 6.6 `CLNK=0x8014` is self-link on channel 20. | CLNK is not the root-cause delta. Treat it as equivalent unless future evidence contradicts this. |
| Linux 6.6 period-size 1032 controlled rerun | Reran the period-matched 20 s left-channel tone with `TONE_AMP=0.02`, `NQ_PROBE_MASTER_VOLUME=180`, `NQ_PROBE_SPEAKER_VOLUME=180`, and `APLAY_EXTRA_ARGS='--period-size=1032 --buffer-size=4128'`. | Artifact saved at `artifacts/audio-rootcause-linux66-period1032-controlled-20260614-132456`. `aplay_status=0` and no ALSA underrun. Source WAV analysis stayed clean. McBSP2 still matched the 3.0 serial setup except `IRQST=0x710`; SDMA channel 20 still matched the 3.0 geometry with `CEN=0x0810`, `CFN=4`, `CSDP=0x0181`, `CICR=0x092a`, and `CDSA=0x49024008`. Mic capture was still low-SNR. | The register-level McBSP/SDMA path is reproducible. The current evidence does not justify more McBSP instance, clock-divider, DMA geometry, or CLNK experiments. |
| TAS5713 init parity and live dump | Ran `tools/check_tas5713_init_parity.py` and compared the 6.6 live TAS dump from module reload against the old board init table. | Script reported `tas5713-init-parity-ok entries=49`. Live multiword registers matched the expected old init values for input mux, PWM mux, high-pass biquads, DRC control, bank EQ, and output/channel mix registers. | A static TAS5713 coefficient or register-table typo is not the current lead. Leave TAS init alone unless a new live 3.0 TAS dump shows a material difference. |
| Async TAS stream reinit at period-size 1032 | Reloaded TAS with `nq_async_legacy_stream_reinit_ms=0` to mimic the old workqueue-style trigger timing, then reran the same period-matched left-channel tone. | Artifact saved at `artifacts/audio-rootcause-linux66-period1032-async0-20260614-132944`. `aplay.log` reported an underrun. Mic metrics were worse. McBSP/SDMA registers stayed essentially unchanged, so the added failure was sequencing/pacing, not a useful register shift. | Async TAS reinit with zero delay is not a fix. Return to non-async baseline before further tests. |
| ALSA/dmaengine pacing sample | Patched `tools/capture_linux66_audio_compare_local.sh` to sample `/proc/asound/card0/pcm0p/sub0/{status,hw_params,sw_params}` during playback, then reran the period-matched low-volume tone. | Artifact saved at `artifacts/audio-rootcause-linux66-period1032-pcmstatus-20260614-133516`. `aplay_status=0`; no underrun. Running samples showed smooth pointer movement: delay `2762..4183`, avail `9..1430`, no bad `hw_ptr` steps, median observed `hw_ptr` rate around `48079` frames/s. McBSP/SDMA registers still matched the 3.0 geometry. | H5 is weakened. Userspace refill and dmaengine pointer accounting do not currently look like the wobble source. Do not reboot only to test DMA residue unless new evidence points back there. |
| McBSP IRQ/start-sequence audit | Compared old `omap_mcbsp_start_capture_start_time()` to the current 6.6 `omap_mcbsp_start()` port, and decoded the persistent `IRQST=0x710` delta. | The old and new start routines both enable SRG, enable TX, delay 500 us, enable frame sync, enable TX-underflow IRQ, release `XCCR`, then reset `XRST` if `XRDY` is already set. `IRQST=0x700` is normal TX frame/EOF/ready status; `0x710` adds `RUNDFLEN`, an RX-underflow status bit. Playback only enables `IRQEN=0x800` (`XUNDFLEN`). | The McBSP start-order port is mostly closed. Track the RX-underflow status bit, but do not chase it as the primary cause unless it correlates with an audible improvement or new underflow evidence. |
| Byteswap-safe representation probe | Added `PCM_SOURCE_MODE=byteswap16-safe` to `tools/capture_linux66_audio_compare_local.sh`. This sends tiny on-disk samples if the path is normal, but would become a low-volume 440 Hz sine if the path effectively byte-swaps 16-bit samples. | Artifact saved at `artifacts/audio-rootcause-linux66-byteswap16-safe-20260614-134912`. `aplay_status=0`; McBSP/SDMA geometry remained period-matched. The intended byte-swapped output WAV is a clean quantized 440 Hz sine, but the Mac mic capture showed no strong 440 Hz tone (`expected_tone_to_rms_db` about `-48 dB`). PCM status again showed smooth movement: delay `2983..4090`, avail `102..1209`, no bad `hw_ptr` steps. | A simple 16-bit byte-swap is not supported by this run. Leave H6 open only for human confirmation; otherwise move on to pin-level timing or a narrower McBSP/TAS dynamic-path check. |
| PIO DXR register audit | Rechecked the kernel-generated PIO diagnostic after noticing it wrote `DXR1` directly. | On OMAP4/McBSP reg_size 4, the actual DMA target is `DXR` at McBSP DMA offset `0x08` (`CDSA=0x49024008`). `DXR1` is only correct for 16-bit register layouts. Patched PIO writes to use `DXR` for reg_size 4 and `DXR1` only for reg_size 2. | Previous PIO runs are not valid evidence about audio quality. The PIO diagnostic had a real bug. |
| Corrected PIO DXR run | Rebuilt and reloaded the corrected `audio-dma-wifi` module set, then ran a 6 s kernel-generated PIO tone at safe volume. | Artifact saved at `artifacts/audio-rootcause-pio-dxr-fix-20260614-135443`. Dmesg showed `nq pio tone start`, but ALSA returned `aplay_status=1` with `Input/output error` after about 1.3 s. The run did not log `nq pio tone done`, and the remote "during" register capture happened after McBSP/TAS teardown (`SPCR2=0x2b0`, TAS `sys2=0x40`). | The corrected PIO test is still an invalid audio-quality test. It currently proves the PIO harness is coupled to ALSA/DMA teardown, not that the hardware path is good or bad. |
| Detached PIO harness | Added diagnostic `snd_soc_omap_mcbsp.nq_pio_detached_stop=1` and `snd_soc_tas571x.nq_ignore_mute=1`, then reran a 6 s kernel-generated left tone. | Artifact saved at `artifacts/audio-rootcause-pio-detached-20260614-140445`. `aplay_status=1` still occurred, but the intended diagnostic survived it: dmesg logged `nq pio tone done elapsed_ms=6314`, then cleanup stopped McBSP and freed the port (`active=0 configured=0`). TAS mute was ignored as intended. However the PIO path logged `underflows=81`, `irqst_before=0x4f00`, and `max_free_words=128`. | The detached harness survived teardown, but this run is not a valid audio-quality verdict because the kernel-generated PIO stream underflowed. Later PIO variants did not reach a safe zero-underflow result. |
| Detached PIO IRQ fill | Tried the same detached PIO harness with `nq_pio_irq=1` to refill from TX-ready IRQs instead of timer-only fill. | No artifact was completed. SSH dropped during the run and the device recovered to fastboot. | Treat IRQ-driven PIO as unsafe in the current implementation. Do not repeat it. Use a safer timer-fill refinement if continuing PIO, or move to pin-level measurement. |
| Detached PIO timer 50 us | Reran detached timer-only PIO with `nq_pio_timer_us=50`, same safe volume, and same PIO amplitude. | Artifact saved at `artifacts/audio-rootcause-pio-detached-timer50-20260614-140916`. Dmesg logged `nq pio tone done elapsed_ms=6287` and cleanup completed. Underflows improved from 81 to 33, but did not reach zero. Mic analysis still did not show a clean 440 Hz tone. | Shorter timer cadence helped but did not close H7. A later reduced-logging retry also failed, so this branch should not continue as parameter tuning. |
| Detached PIO timer50 quiet logging | Repeated the timer50 detached PIO idea with TAS, machine-driver, and DMA cyclic register dumps disabled: `NQ_TAS571X_DUMP_REGS=0`, `NQ_STEELHEAD_AUDIO_DUMP=0`, and `NQ_DMA_DUMP_CYCLIC=0`. | No artifact directory was produced. SSH dropped with `Host is down`, a later SSH probe timed out, and `fastboot devices` showed `AW1S12250524 fastboot`. | Reducing diagnostic logging did not make the PIO branch safe or conclusive. Stop PIO parameter chasing; the current PIO harness is not a reliable lowest-layer acceptance test. |
| DMA-backed kernel tone implementation | Added `omap_dma.nq_audio_tone` diagnostic mode. When enabled for McBSP2 TX cyclic DMA to DXR `0x49024008`, the DMA driver allocates a coherent kernel-owned S16 stereo tone buffer and points the cyclic descriptor at that buffer instead of the ALSA/userspace buffer. | First run saved partial artifact `artifacts/audio-rootcause-dma-kernel-tone-20260614-150220` but recovered to fastboot. Root cause was a diagnostic bug: the 256-entry sine-table phase index used an unwrapped 64-bit phase and could read past the table. | The fastboot recovery was caused by our diagnostic implementation, not useful audio evidence. The phase accumulator was corrected to 32-bit wrapping before rerun. |
| DMA-backed kernel tone fixed | Reran the corrected DMA-tone diagnostic at 48 kHz, 440 Hz, left-only, `amp=3072`, mixer `Master=220`, `Speaker=220`, `aplay --period-size=6000 --buffer-size=24000`. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-fixed-20260614-150623`. `aplay_status=0`; SSH survived. Dmesg proves DMA source override: `tone_buf=0xbf020000`, `cssa=0xbf020000`, `cdsa=0x49024008`, `csdp=0x0181`, `cicr=0x092a`, `cen=12000`, `cfn=4`. No TX-underflow evidence appeared; McBSP `IRQST=0x0710` remained the tracked RX-underflow status. Mic capture found a strong tone near 440 Hz, low harmonic distortion, but large envelope modulation: `envelope_cv_25ms=0.496`, `envelope_peak_to_trough_db_25ms=17.1`, `envelope_mod_peak_hz_25ms=12.15`. | Userspace source data and userspace refill are no longer plausible primary causes for this run. Unless human listening contradicts the mic capture, the wobble is now below userspace PCM data, in DMA pacing/geometry, McBSP serial behavior, TAS5713 stream handling, or the board-level serial pins. |
| DMA-backed kernel tone with 3.0 DMA geometry | Reran the same DMA-tone path with `aplay --period-size=1032 --buffer-size=4128`, matching the captured Linux 3.0 DMA geometry (`cen=2064`, `cfn=4`). Used `nq_audio_tone_freq=500` so the 4128-frame cyclic buffer contains exactly 43 cycles and does not create an artificial wrap discontinuity. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-period1032-20260614-150848`. `aplay_status=0`; SSH survived. Dmesg showed `tone_buf=0xbf008000`, `cssa=0xbf008000`, `cdsa=0x49024008`, `csdp=0x0181`, `cicr=0x092a`, `cen=2064`, `cfn=4`. Mic capture still showed large envelope modulation: `envelope_cv_25ms=0.435`, `envelope_peak_to_trough_db_25ms=13.7`, `envelope_mod_peak_hz_25ms=12.49`. | Matching the captured 3.0 DMA period geometry did not remove the wobble. The next single diagnostic is channel content: drive both left and right slots with the same kernel tone to check whether TAS routing/output behavior depends on the silent right slot. |
| DMA-backed kernel tone dual-mono | Kept the period-matched 500 Hz DMA-tone setup and changed only `nq_audio_tone_channel=2`, so both stereo slots carried the same kernel tone. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-period1032-dualmono-20260614-151023`. `aplay_status=0`; SSH survived. Dmesg again showed `cssa=0xbf008000`, `cdsa=0x49024008`, `csdp=0x0181`, `cicr=0x092a`, `cen=2064`, `cfn=4`. Mic metrics were effectively unchanged from left-only: `envelope_cv_25ms=0.440`, `envelope_peak_to_trough_db_25ms=14.0`, `envelope_mod_peak_hz_25ms=11.95`. | Silent right-slot content is not the root cause. Stop channel-content tests. Next evidence should come from TAS5713 stream/power behavior or physical serial-pin measurement. |
| DMA-backed kernel tone codec-power-first | Reloaded the audio modules with `snd_soc_steelhead_tas5713.nq_codec_power_first=1` and kept the period-matched 500 Hz left-only DMA tone. This forced TAS digital mute/unmute through the Steelhead trigger hook while leaving DMA/McBSP geometry unchanged. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-codec-power-first-20260614-151435`. `aplay_status=0`; SSH survived. Dmesg confirmed `nq_codec_power_first=Y`, legacy stream reinit still enabled, and the same DMA setup (`cssa=0xbf008000`, `cdsa=0x49024008`, `csdp=0x0181`, `cicr=0x092a`, `cen=2064`, `cfn=4`). Mic metrics were still bad: `envelope_cv_25ms=0.468`, `envelope_peak_to_trough_db_25ms=14.8`, `envelope_mod_peak_hz_25ms=12.53`. | Machine-driver codec trigger ordering is not sufficient. Do not keep chasing TAS start ordering unless a new register or pin-level observation points there. |
| DMA-backed kernel tone old-style TAS gain | Restored channel/speaker volume to the old init value / 0 dB (`Speaker Volume=207`, TAS `ch1_vol/ch2_vol=0x30`) while keeping master volume audible (`Master=220`, TAS `mvol=0x23`). This tested whether the previous double gain (`mvol/ch1/ch2=0x23`) was causing TAS DSP/limiter pumping. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-master-only-gain-20260614-151810`. `aplay_status=0`; SSH survived. Dmesg confirmed `unmute mvol=0x23`, `ch1_vol=0x30`, and `ch2_vol=0x30`; DMA/McBSP geometry remained period-matched. Mic capture was quieter but still strongly modulated: `envelope_cv_25ms=0.452`, `envelope_peak_to_trough_db_25ms=14.2`, `envelope_mod_peak_hz_25ms=12.08`. | TAS double-gain/limiter pumping is not the primary cause. Keep channel volume at 0 dB for future tests because it is closer to the old init path, but do not treat it as the fix. |
| DMA-backed kernel tone with periodic DMA IRQs masked | Added `omap_dma.nq_audio_tone_no_irq=1`, which suppresses `CICR_FRAME_IE` and `CICR_BLOCK_IE` only when the DMA-generated tone override is active. Reran the 500 Hz left-only kernel tone with period `1032`, buffer `4128`, `Speaker=207`, and `Master=220`. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-noirq-20260614-152622`. Dmesg confirmed the tone override and `no_irq=1`; the prepared cyclic descriptor used `cicr=0x0902`, so the frame/block period bits were removed. The Mac mic result stayed in the same bad band: `envelope_cv_25ms=0.440`, `envelope_peak_to_trough_db_25ms=14.45`, `envelope_mod_peak_hz_25ms=12.84`, `zero_cross_freq_hz=522.7`. | Periodic DMA/ALSA completion IRQ cadence is weakened as the root cause. The wobble persists even when the DMA engine loops over a kernel-owned tone buffer without normal period callbacks. Move lower: serial clocking/format, TAS stream interpretation, or physical pin behavior. |
| DMA-backed kernel tone with old-style inert codec DAI | Matched the old TAS5713 codec driver more closely by skipping the modern codec DAI `set_fmt` call (`snd_soc_steelhead_tas5713.nq_skip_codec_fmt=1`) and skipping the modern TAS571x `hw_params` SDI rewrite (`snd_soc_tas571x.nq_skip_hw_params=1`). Kept 500 Hz left-only DMA tone, period `1032`, buffer `4128`, `Speaker=207`, and `Master=220`. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-codec-inert-20260614-152906`. `aplay_status=0`; dmesg/module params confirmed `nq_skip_codec_fmt=Y`, `nq_skip_hw_params=Y`, DMA tone active, and normal period IRQs (`nq_audio_tone_no_irq=N`). Mic metrics remained bad: `envelope_cv_25ms=0.462`, `envelope_peak_to_trough_db_25ms=14.49`, `envelope_mod_peak_hz_25ms=13.17`, `zero_cross_freq_hz=520.7`. | Modern codec `set_fmt`/`hw_params` callbacks are not the root cause. This leaves McBSP clock/frame generation, MCLK/clock-domain behavior, TAS power sequencing, or physical serial-pin behavior as the remaining software-visible leads. |
| DMA-backed kernel tone with old-style codec MCLK ownership | Kept the old-style inert codec DAI setup and additionally disabled the modern Steelhead machine-driver startup MCLK enable (`snd_soc_steelhead_tas5713.nq_codec_mclk_startup=0`). This leaves MCLK ownership closer to the old TAS5713 reset/power path while keeping the same 500 Hz left-only DMA tone, period `1032`, buffer `4128`, `Speaker=207`, and `Master=220`. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-codec-mclk-owned-20260614-153233`. `aplay_status=0`; module params confirmed `nq_codec_mclk_startup=N`, `nq_skip_codec_fmt=Y`, and `nq_skip_hw_params=Y`. Mic metrics remained bad: `envelope_cv_25ms=0.448`, `envelope_peak_to_trough_db_25ms=14.58`, `envelope_mod_peak_hz_25ms=13.13`, `zero_cross_freq_hz=525.1`. | The extra machine-driver MCLK startup reference is not the root cause. Codec DAI callbacks plus MCLK startup ownership are now weakened together; remaining software-visible leads are McBSP dynamic clock/frame behavior, TAS stream interpretation/power state that is not exposed by the tested callbacks, or physical serial-pin behavior. |
| DMA-backed kernel tone with longer cyclic buffer | Kept the 500 Hz left-only DMA tone and old-style inert codec/MCLK ownership settings, but changed only the ALSA cyclic geometry from period/buffer `1032/4128` to `6000/24000`. With a 48 kHz ring, a buffer-wrap artifact should have moved from about `11.6 Hz` to about `2 Hz`. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-buffer24000-20260614-153642`. `aplay_status=0`; module params confirmed the same DMA-tone and codec settings. During playback the DMA registers showed the intended longer geometry (`CEN=12000`, `CFN=4`, `CICR=0x092a`, `CSSA=0xbf020000`, `CDSA=0x49024008`). Mic metrics stayed in the same band: `envelope_cv_25ms=0.412`, `envelope_peak_to_trough_db_25ms=13.90`, `envelope_mod_peak_hz_25ms=12.35`. | A simple cyclic-buffer wrap artifact is weakened. The wobble frequency did not follow the ring repeat rate, so the cause is more likely a fixed lower-layer pacing/clocking/power artifact or acoustic/codec behavior than the ALSA ring length itself. |
| DMA-backed kernel tone with flat TAS DSP | Reran the old-style inert codec/MCLK setup with `snd_soc_tas571x.nq_flat_dsp=1`, explicitly set the mixer before playback, and kept the 500 Hz kernel-generated DMA tone at period/buffer `1032/4128`. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-flatdsp-light-vol-20260614-154617`. `aplay_status=0`; no ALSA underrun was logged. The capture was audible and still strongly modulated: `envelope_cv_25ms=0.425`, `envelope_peak_to_trough_db_25ms=13.95`, `envelope_mod_peak_hz_25ms=12.39`. | TAS DRC/EQ coefficient behavior is weakened. A flat DSP path does not remove the wobble when the mixer is set correctly. |
| SDMA `NO_PERIOD_WAKEUP` parity | Added `SNDRV_PCM_INFO_NO_PERIOD_WAKEUP` to the 6.6 `sdma-pcm` hardware capabilities to match the old 3.0 OMAP PCM hardware flags, rebuilt/reinstalled the audio module stack, and reran the same flat-DSP DMA-tone capture. | Artifact saved at `artifacts/audio-rootcause-dma-kernel-tone-noperiodwake-flatdsp-20260614-154914`. `aplay_status=0`; mic metrics remained in the same bad band: `envelope_cv_25ms=0.416`, `envelope_peak_to_trough_db_25ms=13.60`, `envelope_mod_peak_hz_25ms=12.74`. | PCM capability parity is not sufficient. Combined with the earlier `nq_audio_tone_no_irq=1` result, period-wakeup behavior is unlikely to be the root cause. |
| McBSP sidetone audit | Checked whether the modern `if (mcbsp->st_data)` sidetone start/stop path is active on Nexus Q McBSP2. | The live 6.6 McBSP2 sysfs node has no `sidetone` attributes and ALSA exposes only `Master` and `Speaker` mixer controls. The OMAP4 McBSP2 DT node has only `mpu` and `dma` register ranges, not a named `sidetone` resource. | The old-vs-new sidetone start condition is not active on this board. Do not chase sidetone. |
| McBSP FIFO metadata audit | Compared the old OMAP4 McBSP platform-data buffer sizing with the 6.6 DT and live sysfs values. | Linux 3.0 set OMAP4 McBSP `buffer_size=0x80` for all instances. Linux 6.6 DT has `ti,buffer-size=<128>`, and the live node reports `max_tx_thres=112`, `max_rx_thres=112`, and `dma_op_mode=[element] threshold`. | FIFO metadata matches the old path. A wrong McBSP FIFO size is not the mismatch. |
| TAS SDI format sweep | Reloaded the old-style inert codec path with TAS `nq_sdi_override` values `0x00`, `0x03`, `0x05`, and `0x06`, then replayed the same 500 Hz DMA-backed kernel tone. | Artifact root `artifacts/audio-rootcause-sdi-sweep-20260614-155342`. All candidates remained bad: `0x00 cv=0.400 p2p=11.64 dB`, `0x03 cv=0.407 p2p=12.33 dB`, `0x05 cv=0.410 p2p=13.10 dB`, `0x06 cv=0.386 p2p=11.29 dB`. | A simple TAS5713 SDI serial-format mismatch is not the root cause. Keep the known old value unless a pin-level capture contradicts it. |
| GPIO, regulator, and pinmux audit | Checked live GPIO, regulator, and pinctrl debugfs while the TAS card was active. | `gpio-552` (`regulator-tas5713-in`) was output high. `gpio-554` reset and `gpio-556` PDN are active-low outputs and were high, meaning deasserted. Regulator `tas5713-interface` was enabled at 3.3 V. Pinctrl entries for pads 16/18/20 correspond to the DTS comments for `gpio_40`, `gpio_42`, and `gpio_44`. | The TAS5713 is not being held in reset or powerdown, and the GPIO pinmux audit does not show a reset/power pin assignment bug. |
| DMA-backed kernel tone amplitude sweep | Kept the same old-style inert codec, flat DSP, 500 Hz left-only DMA-backed kernel tone and varied only `omap_dma.nq_audio_tone_amp` across `256`, `512`, `1024`, and `2048`. | Artifacts saved under `artifacts/audio-rootcause-dma-kernel-tone-amp-*`. The lowest amplitude was still modulated (`amp=256 cv=0.413 p2p=13.61 dB mod=12.79 Hz`), and higher amplitudes stayed bad (`amp=512 cv=0.480`, `amp=1024 cv=0.477`, `amp=2048 cv=0.494`). No clipping was detected. | The wobble is not just TAS output limiting, clipping, or excessive test amplitude. Very small kernel-generated samples still wobble. |
| Old-vs-new McBSP register audit | Rechecked the old 3.0 Steelhead machine driver and the live 6.6 McBSP register state for 48 kHz S16 stereo. | The old driver computes `target_rate = params_rate * 32`, so expected BCLK is 32 fs, not 64 fs. Live 6.6 DMA-tone playback shows the same effective serial setup: `XCR2=0x8041`, `XCR1=0x0040`, `SRGR2=0x101f`, `SRGR1=0x0f0f`, `PCR0=0x0f0f`, and `THRSH2=0`. | Do not chase 64 fs or a static McBSP register mismatch unless physical pin measurement shows the pins disagree with the registers. The remaining lead is dynamic timing/clock behavior or TAS stream/power state. |
| Current DMA-tone FIFO/TAS polling baseline | After watchdog recovery, rebooted the modular 6.6 image, reloaded the old-style inert codec path, and reran 500 Hz left-only DMA-backed kernel tone with `amp=512`, period/buffer `1032/4128`, FIFO polling every 10 ms, and TAS error polling every 50 ms. | Artifact `artifacts/audio-rootcause-current-dmatone-clkfifo-20260614-161428`. `aplay_status=0`; mic capture still modulated (`cv=0.283`, `p2p=8.43 dB`, `mod=12.96 Hz`). FIFO stayed full or almost full (`xbuf_free_min=0`, `xbuf_free_max=1`, 823 samples). TAS poll stayed quiet (`err_nonzero=0`, `sys2_changes=0`, `last_err=0`, `last_sys2=0`). | This reconfirms the current failure below userspace with no TX starvation and no TAS-reported input/backend fault. |
| Current DMA-tone with deep cpuidle disabled | Disabled OMAP cpuidle states C2/C3 (`state1/disable=1`, `state2/disable=1`) and reran the same 500 Hz DMA-backed kernel tone. Restored cpuidle after the run. | Artifact `artifacts/audio-rootcause-dmatone-cpuidleoff-20260614-161626`. `aplay_status=0`; mic capture did not improve (`cv=0.299`, `p2p=8.40 dB`, `mod=13.29 Hz`). FIFO and TAS error summaries stayed in the same band. | Deep CPU/MPUSS idle transitions are not the root cause of the fixed-rate wobble. |

## Important Observations

The strongest facts so far:

- The source PCM is clean.
- The user hears audible wobble/distortion on every successful 6.6 playback
  experiment.
- McBSP TX FIFO is not obviously starving during DMA-backed tests.
- The codec is not reporting input clock or backend errors.
- Flat TAS DSP does not fix it.
- Suppressing DMA frame/block period interrupts for the kernel-tone diagnostic
  does not fix it.
- Skipping the modern TAS codec DAI format/hw_params callbacks does not fix it.
- Disabling the modern Steelhead machine-driver startup MCLK enable does not
  fix it.
- Obvious clocks and static serial registers match the old path.
- Several "maybe it is just X" software toggles have not fixed it.
- The Linux 3.0 comparison image now boots and exposes the old TAS5713 ALSA
  card.
- The correct McBSP2 register base is `0x40124000`; `0x40122000` is McBSP1.
- On Linux 3.0, McBSP2 `devmem` reads bus-error while the port is powered down,
  but read cleanly during playback. That is expected and should not be treated
  as a failed base address.
- Linux 3.0 playback used SDMA channel 0 in the captured run, with destination
  `0x49024008`, which is McBSP2 DXR.
- Linux 6.6 legacy-parameter playback used the same McBSP2 register bank and
  destination `0x49024008`.
- `CLNK=0x8014` on 6.6 and `CLNK=0x8000` on 3.0 are both self-linking; the
  apparent difference is just the DMA channel number.
- With `aplay --period-size=1032 --buffer-size=4128`, the 6.6 DMA `CEN`,
  `CFN`, `CSDP`, `CICR`, `CDSA`, `CDEI`, and `CDFI` match the captured 3.0
  geometry closely.
- The Mac microphone captures at the current safe volume are too low-SNR for
  reliable root-cause analysis.
- The Linux 3.0 `omap-pcm` driver advertises
  `SNDRV_PCM_INFO_NO_PERIOD_WAKEUP`; Linux 6.6 `sound/soc/ti/sdma-pcm.c` does
  not. This is a playback-pacing difference above the static McBSP/SDMA
  registers.
- The 6.6 dmaengine PCM pointer path depends on DMA residue reporting unless
  the platform forces no-residue pointer accounting. If residue/pointer
  accounting is wrong, ALSA can pace refills incorrectly while the hardware
  registers still look correct.
- The controlled PCM status sampler did not show refill starvation, pointer
  discontinuities, or ALSA-level underruns during the latest period-matched
  bad run.
- `IRQST=0x710` decodes as normal TX status bits plus `RUNDFLEN` (RX
  underflow). Since playback only enables TX underflow IRQ, this is a tracked
  difference but not currently the strongest root-cause lead.
- The `byteswap16-safe` probe did not produce a strong 440 Hz mic capture, so a
  simple 16-bit byte-swap is unlikely.
- The old PIO diagnostic wrote the wrong McBSP data register on OMAP4. It is
  patched now, but all earlier PIO listening results must be ignored.
- The corrected PIO diagnostic still is not a valid quality test because ALSA
  stops the stream once DMA no longer advances, and the TAS mute/shutdown path
  runs before the intended 6 s tone finishes.
- The detached PIO harness now survives ALSA teardown and cleans itself up, but
  the first detached run underflowed 81 times. Do not use that run to decide
  whether the wobble is below DMA.
- IRQ-driven PIO fill dropped SSH and recovered through fastboot. Do not repeat
  that path.
- Timer-only PIO at 50 us reduced TX underflows but still logged 33 underflows,
  so the PIO output is still not clean enough to judge the audio stack.
- Repeating timer50 PIO with reduced diagnostic logging lost SSH and recovered
  to fastboot before an artifact was created. That makes the current PIO branch
  both unsafe and non-convergent.
- The corrected DMA-backed kernel tone completed without SSH loss and proved
  the DMA engine was reading a kernel-generated coherent tone buffer, not the
  ALSA/userspace buffer.
- The fixed DMA-tone run still shows strong microphone envelope modulation
  despite clean DMA setup and no ALSA underrun. This narrows the problem below
  userspace PCM source/refill.
- Matching the 3.0 DMA period geometry with a clean-wrap 500 Hz kernel tone did
  not remove the modulation, so ALSA/userspace refill and gross DMA period
  geometry are both weakened as root causes.
- Changing the DMA-tone cyclic ring from 4128 frames to 24000 frames did not
  move the modulation frequency, so simple cyclic-ring wrap is weakened.
- A valid flat-DSP rerun still showed the same 12-13 Hz modulation, so TAS
  DRC/EQ coefficient behavior is weakened.
- Adding 3.0-style `SNDRV_PCM_INFO_NO_PERIOD_WAKEUP` to the 6.6 SDMA PCM
  wrapper did not remove the DMA-tone modulation.
- McBSP2 sidetone is not present in the live 6.6 DT/sysfs path, and FIFO
  metadata matches the old OMAP4 path (`buffer_size=128`, max threshold 112).
- Driving both stereo slots with the same kernel tone did not materially change
  the modulation, so the wobble is not explained by a silent right slot or
  basic left/right slot content.
- Forcing TAS unmute/reinit through the Steelhead trigger hook did not remove
  the DMA-tone modulation, so codec start-order alone is not the fix.
- Restoring TAS channel/speaker volume registers to 0 dB made the capture
  quieter but did not remove the modulation, so double-applying master and
  channel gain is not the primary cause.
- For module reloads on the current image, use the
  `audio-dma-wifi-public-debian-modular` build output. Accidentally installing
  the older `audio-wifi` module output causes unknown TAS/machine parameter
  warnings and invalidates the run.

The most important gap:

- We now have a valid DMA-backed kernel-tone path, but not a clean continuous
  tone. The fixed run completed and still measured large envelope modulation.

Without direct serial-pin evidence or a redesigned isolated tone path, continued
6.6-only parameter sweeps are too likely to repeat old ground.

## Current Hypotheses

### H0: The 6.6 path may not be using the exact same McBSP2 path as Linux 3.0

Status: mostly closed.

Evidence:

- Steelhead board code configures `abe_mcbsp2_*` pins.
- Vendor 3.0 maps McBSP2 at MPU `0x40124000` and DMA `0x49024000`.
- Linux 6.6 DTS maps `&mcbsp2` through target-module `@24000`, with DMA address
  `0x49024000`.
- A prior 3.0 dump attempt used `0x40122000`, which is McBSP1, so that result
  must be discarded.
- Live Linux 6.6 sysfs confirms the card/pinmux path is `40124000.mcbsp`.
- Live Linux 6.6 playback writes to `CDSA=0x49024008`, matching the 3.0 McBSP2
  DXR path.

Stop condition:

- Leave this closed unless future evidence shows a live binding regression.

### H1: Dynamic McBSP/DMA behavior still differs from Linux 3.0

Static McBSP registers match, but dynamic behavior could still differ:

- DMA sync mode or event polarity could be subtly different.
- FIFO threshold handling could differ at stream start.
- The order of DMA start, McBSP XRST/FRST/GRST, XCCR release, and codec unmute
  may still differ in a way the current logs do not reveal.
- The serial shifter may be outputting data with a periodic slip even while the
  FIFO looks full.

Status: still plausible. Needs 3.0 comparison or electrical measurement.

Refinement after `audio-rootcause-linux66-legacy-compare-20260614-131639`:

- Static McBSP serial setup is almost identical to Linux 3.0.
- DMA destination, CSDP, CICR, and CCR match the 3.0 TX path.
- The earlier suspected cyclic-link delta is not real; old and new paths both
  self-link DMA.
- With period-size `1032`, the 6.6 DMA geometry can match the 3.0 capture.
- If the period-size `1032` run still audibly wobbles, the likely issue is not
  visible in these software registers. Move to electrical measurement or a
  human A/B check against a louder but still safe known-good path.

### H2: TAS5713 consumes the serial stream differently on 6.6

The TAS5713 visible registers look correct:

- SDI register is `0x03` for 16-bit I2S.
- Clock control is `0x6c`.
- Error/sys2 polling is clean.
- Flat DSP did not fix the wobble.

Status: less likely than H1, but not fully disproven until the live 3.0 TAS
register state is captured and compared.

### H3: The hardware clocks look right in Linux but the actual pins are wrong

The Linux clock tree reports the right rates, but that does not prove the
actual BCLK/LRCLK/DOUT waveforms at the TAS input are clean and correctly
phased.

Status: plausible. A logic analyzer or scope on BCLK, LRCLK, DATA, and MCLK
would answer this much faster than software-only guessing.

### H4: The microphone analysis is misleading

The Mac mic analysis sometimes estimates the tone frequency far from 440 Hz.
That could be analysis weakness at low volume and low SNR.

Status: not a root-cause explanation, because the user consistently hears the
same audible wobble. The mic analysis should be treated as supporting evidence,
not the source of truth.

### H5: ALSA/dmaengine playback pacing differs from old `omap-pcm`

The register-level path can now be made very close to Linux 3.0, but 6.6 uses
generic dmaengine PCM (`sound/soc/soc-generic-dmaengine-pcm.c` plus
`sound/soc/ti/sdma-pcm.c`) while Linux 3.0 used the OMAP-specific
`sound/soc/omap/omap-pcm.c`.

Relevant differences:

- Linux 3.0 `omap-pcm.c` advertises `SNDRV_PCM_INFO_NO_PERIOD_WAKEUP`.
- Linux 6.6 `sdma-pcm.c` currently advertises only mmap/interleaved/pause/resume
  and does not advertise no-period-wakeup.
- Linux 6.6 generic dmaengine PCM chooses between residue-based and
  no-residue pointer accounting based on DMA capability and registration flags.
- The current OMAP DMA module has `nq_force_descriptor_residue=N`.

Status: weakened after direct PCM status sampling.

Stop condition:

- Reopen this only if a later run shows underruns, `hw_ptr` discontinuities,
  delay collapsing toward zero, or an audible change that tracks period/refill
  geometry.
- The existing `nq_force_descriptor_residue=1` switch probably requires a real
  `omap_dma` reprobe to affect DMA capability registration. The current module
  has a nonzero refcount, so do not burn a reboot on this unless pacing evidence
  points back here.

### H6: PCM data representation is wrong below the clean source WAV

If byte order, word alignment, or slot packing is wrong, the McBSP clock and DMA
registers can look correct while the TAS5713 receives a badly shaped waveform.
This can sound like clipping, square-wave distortion, or pulsing even with a
mathematically clean source sine.

Status: weakened after the `byteswap16-safe` probe, pending human confirmation.

Evidence for checking it now:

- All clock, serial-format, DMA-target, and period-geometry comparisons are now
  close to the Linux 3.0 baseline.
- The source WAV analysis is clean, but the user hears a square/pulsing tone.
- Linux 3.0 and 6.6 both advertise `S16_LE`; this does not prove the actual
  bytes arriving at DXR match what the TAS5713 expects.
- Prior PIO tests do not cleanly close this. Some direct-DXR PIO paths bypassed
  userspace/DMA, but the saved runs include underflows, hard hangs, and no
  reliable "heard clean" acceptance result.

Stop condition:

- If the user heard a clean continuous tone during
  `audio-rootcause-linux66-byteswap16-safe-20260614-134912`, reopen H6 and
  patch toward that representation. Otherwise close the byte-swap branch and
  move to the next specific hardware-path delta.

### H7: The lowest-level PIO diagnostic is not isolated enough yet

The intent of PIO is to bypass userspace WAV generation and DMA, then ask a
very narrow question: can McBSP plus TAS5713 produce a continuous kernel-made
440 Hz left-channel tone?

Status: blocked as a current test path. The implementation is useful for code
inspection, but it is not a valid audio-quality acceptance test.

Evidence:

- The original PIO implementation wrote `DXR1` on an OMAP4 reg_size 4 McBSP,
  while DMA and Linux 3.0 both target `DXR`/`0x49024008`.
- The corrected PIO run started, but `aplay` hit an I/O error after about
  1.3 s because DMA no longer advanced.
- ALSA teardown then stopped McBSP and muted/shut down TAS5713 before the
  intended 6 s tone completed.
- The detached-stop/mute-ignore diagnostic fixed the teardown problem, but the
  first timer-filled run still produced TX underflows.
- IRQ-driven PIO fill was unsafe.
- Timer-cadence tuning reduced but did not eliminate underflows.
- The timer50 run still printed large TAS and machine-driver diagnostic dumps
  during stream start, so reducing that logging was tested as a possible
  hrtimer-jitter cause.
- A quiet timer50 retry, with the large diagnostic dumps disabled, still lost
  SSH and recovered to fastboot before producing an artifact.

Stop condition:

- Do not run more IRQ, XRDY-polled, or timer-cadence PIO experiments in this
  harness.
- Reopen PIO only if it is redesigned so the expected result is a zero-underflow
  continuous tone without depending on hrtimer service under printk/I2C/SSH
  load.
- Until then, use either serial-pin measurement or a DMA-backed in-kernel tone
  path for the next lowest-layer test.

## What Not To Do Next

- Do not keep sweeping random module parameters without a hypothesis and stop
  condition.
- Do not reopen the 3.0 audible-baseline task unless a specific comparison
  needs it. The corrected 3.0 low-level register baseline is already usable.
- Do not use `0x40122000` as the McBSP2 register base. That is McBSP1.
- Do not repeat `nq_pio_xrdy_poll=1`; it wedged the device.
- Do not repeat `nq_pio_irq=1`; it dropped SSH and recovered through fastboot.
- Do not repeat timer50 PIO logging tweaks; the quiet retry also recovered
  through fastboot and produced no artifact.
- Do not keep `nq_async_legacy_stream_reinit_ms=0` enabled as the baseline; it
  introduced an ALSA underrun in the period-matched run.
- Do not increase volume to make the analyzer happier.
- Do not spend time on right-channel behavior until left channel is correct.
- Do not treat `XBUFFSTAT==0` as starvation. It means the TX FIFO has 0 free
  slots.

## Concrete Next Plan

The plan is reset to a bounded lowest-layer ladder. Do not move upward until
the lower rung has one documented pass/fail result.

### Phase 0: Stop the Current Loop

Status:

- Complete.
- The device is currently in the corrected 6.6 DMA-tone boot and reachable over
  SSH.
- The quiet timer50 PIO attempt is documented as a failed/unsafe branch.
- No more PIO parameter sweeps should run in the current harness.

Stop condition:

- This file is updated before any new audio experiment starts.

### Phase 1: Recover a Clean 6.6 Test Boot

Goal:

- Boot the current known 6.6 image, verify SSH, start the watchdog feeder, and
  install the matching current audio module set if needed.

Commands:

```sh
fastboot devices
# boot the current 6.6 test image used by the project scripts
tools/build_audio_dma_modules_local.sh
OUT=build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular \
  NQ_HOST=192.168.86.38 NQ_USER=root NQ_INSTALL_DMA=1 \
  tools/install_audio_modules_remote.sh
tools/start_watchdog_feeder_remote.sh
```

Stop condition:

- SSH works.
- The watchdog feeder is running.
- No speaker playback is attempted in this phase.

### Phase 2: Measure the Serial Boundary

Preferred next evidence is a logic analyzer or scope capture. This is the
cleanest way to stop guessing because software registers now largely match the
old 3.0 baseline.

Signals to capture:

- MCLK
- BCLK
- LRCLK/FSX
- DATA/DX

Expected values for the current 48 kHz S16 stereo test:

- MCLK: 12.288 MHz
- BCLK: 1.536 MHz
- LRCLK: 48 kHz
- DATA: 16-bit left sample then 16-bit right sample, I2S one-bit delay

Stop condition:

- If BCLK/LRCLK are not stable or the data timing is wrong, fix McBSP clocking,
  mux, or format.
- If the pins are clean and correctly phased while audio still wobbles, focus
  back on TAS5713 initialization/amp behavior.

### Phase 3: Software Fallback if No Analyzer Is Available

Goal:

- Replace the hrtimer/PIO acceptance path with a deterministic in-kernel
  DMA-backed tone path that bypasses userspace refill and ALSA period wakeups
  but still uses the real McBSP DXR and TAS5713 serial input.

Implementation shape:

- Implemented `omap_dma.nq_audio_tone`.
- Generate a stereo S16_LE sine buffer in kernel coherent DMA memory.
- Drive McBSP2 DXR with cyclic DMA to `CDSA=0x49024008`, with the expected
  `CSDP=0x0181` and `CICR=0x092a`.
- Keep TAS5713 unmuted at the same safe volume.
- Avoid hrtimer-driven per-sample writes.
- Avoid broad module parameter sweeps.

Progress:

- First implementation had an out-of-bounds sine lookup and recovered to
  fastboot; fixed by using a 32-bit wrapping phase accumulator.
- Corrected 440 Hz DMA-tone run completed with `aplay_status=0` and no SSH
  loss.
- Mic evidence still shows strong envelope modulation, so Phase 3 is not
  clean.

Next single test:

- Stop channel-content tests.
- Reinspect TAS5713 stream/power sequencing and old-vs-new register behavior
  around playback start/stop.
- If no specific software delta is found, use serial-pin measurement as the
  next evidence source: MCLK, BCLK, LRCLK/FSX, and DATA/DX.

Stop condition:

- A 60 s left-channel 440 Hz tone runs without SSH loss, watchdog recovery, DMA
  errors, or McBSP TX underflow evidence.
- The user reports either "continuous and clean" or "still wobbles".

Decision:

- Clean in-kernel DMA tone means move upward to ALSA/userspace pacing and PCM
  packing.
- Wobbly in-kernel DMA tone means stay below ALSA and inspect McBSP/TAS/pins.

### Phase 4: Move Up Only After a Clean Continuous Tone

Once a continuous 440 Hz tone is clean:

1. Retest DMA-backed raw PCM through ALSA.
2. Retest a normal WAV through `aplay`.
3. Retest MP3 through `mpg123`.
4. Package persistent module defaults only after those pass.

Every future patch must have one stated hypothesis, one artifact directory, one
success/failure result, and no unrelated parameter changes in the same run.

## Current 6.6 Baseline Command Shape

For future 6.6 DMA-backed raw PCM tests, use the low-volume baseline unless a
specific experiment says otherwise:

```sh
OUTDIR=artifacts/audio-rootcause-NAME-$(date +%Y%m%d-%H%M%S) \
NQ_SPEAKER_CONNECTED=1 FFMPEG_INPUT=':0' \
NQ_HOST=192.168.86.38 NQ_USER=root \
REQUIRE_REMOTE_CMDLINE=0 \
PROBE_CHANNELS=left DURATION=6 RATE=48000 FREQ=440 PCM_FORMAT=S16_LE \
NQ_MCBSP_DMA_OP_MODE=element \
NQ_PROBE_MASTER_VOLUME=180 \
NQ_PROBE_SPEAKER_VOLUME=180 \
NQ_PROBE_TONE_AMP=0.03 \
NQ_TAS571X_REGMAP_SAMPLE=1 \
APLAY_EXTRA_ARGS='--period-size=6000 --buffer-size=24000' \
tools/run_audio_legacydma_probe_local.sh
```

Before using diagnostics added after the boot image was built, reinstall the
current modules:

```sh
tools/build_audio_dma_modules_local.sh
OUT=build/linux-6.6-omap2plus-steelhead-nosmp-audio-dma-wifi-public-debian-modular \
  NQ_HOST=192.168.86.38 NQ_USER=root NQ_INSTALL_DMA=1 \
  tools/install_audio_modules_remote.sh
```

## Open Questions

- Can the 3.0 comparison image produce a sufficiently audible known-good
  baseline without changing too much of the old path?
- Which TAS5713 volume path did the old Android userspace normally use, given
  that the first 3.0 capture showed master volume `0xff` during playback?
- Does the old 3.0 kernel expose enough devmem access to dump McBSP2 and DMA
  registers cleanly while audio is playing?
- Does live 6.6 sysfs/devicetree/logging confirm the TAS5713 card is using
  McBSP2 target-module `@24000`?
- Is a logic analyzer or scope available for direct BCLK/LRCLK/DATA/MCLK
  capture if the 3.0 build path stalls?

## 2026-06-14: Confirmed 6.6 Port Regression

Evidence:

- The Linux 3.0 baseline produced a clean tone on the same Nexus Q, amplifier,
  speaker wiring, and user listening position.
- The Linux 6.6 path produced audible envelope wobble/flutter through multiple
  ALSA, MP3, period, channel, and volume tests.
- A Linux 6.6 500 Hz tone became clean only after forcing McBSP2 TX DMA request
  `17` onto OMAP SDMA logical channel `0` and using the legacy-like period
  geometry:
  - ALSA `--period-size=1032`
  - ALSA `--buffer-size=4128`
  - SDMA `CEN=2064`
  - SDMA `CFN=4`
- User verdict after that 6.6 test: "wow that sounded like a clean tone".

Current working condition:

- Image:
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
- Booted live device at `192.168.86.38`.
- `/sys/module/omap_dma/parameters/nq_force_lch_sig` is `17`.
- `/sys/module/omap_dma/parameters/nq_force_lch` is `0`.
- ALSA card is present as `Steelhead TAS5713`.
- Hardware watchdog cmdline arguments were removed from this audio image because
  they were rebooting the device to fastboot around the old 60 second window.
  The software fallback `nq.autoreboot=900` remains.
- Loader now uses BusyBox `cat` to read `/etc/nq-force-lch-sig` and
  `/etc/nq-force-lch`, so the forced DMA channel survives a normal boot.
- Rootfs `/sbin/nq-init` calls `/sbin/nq-load-audio`, so the audio module stack
  auto-loads after boot.

Most recent climb up the stack:

- Controlled WAV/song playback through ALSA completed with the same legacy
  period geometry:

```sh
aplay -D hw:0,0 --period-size=1032 --buffer-size=4128 --duration=12 \
  /tmp/into-the-oceans-and-the-air.wav
```

- Artifact:
  `artifacts/audio-rootcause-linux66-stable-period1032-song-20260614-182623`
- Kernel log showed `dma-start ch=0 sig=17 ... cen=2064 cfn=4` and a clean
  stop.

Next rule:

- Do not treat "less bad" as success. The acceptance criterion is continuous,
  wobble-free left-channel PCM playback, then WAV, then MP3.
- Preserve DMA request `17` on logical channel `0` while climbing the stack.
- Vary only one thing per run: either playback period geometry, player path, or
  driver behavior.

## 2026-06-14 Evening: Clean Condition Retracted

Later user feedback invalidated the earlier "clean" interpretation. Treat the
channel-0 / period-1032 condition as necessary for reproducing the closest
known 3.0 DMA geometry, not as a fix. The current acceptance state is:

- No Linux 6.6 run has a confirmed wobble-free tone after the later retries.
- The Linux 3.0 baseline is accepted as the clean actual-speaker reference by
  direct user listening. The MacBook microphone metrics are noisy in the room
  and should not override the ear verdict unless they are backed by direct
  electrical capture.
- The confirmed breakage is therefore in the modern Linux 6.6 port, not the
  speaker, amplifier, or room hardware.

Additional discriminators run after the retry:

| Test | Artifact | Result | Conclusion |
| --- | --- | --- | --- |
| DMA-backed tone with cpuidle disabled | `artifacts/audio-rootcause-dma-tone-cpuidle-off-20260614-192901` | `aplay_status=0`, cpuidle states disabled during playback, strong acoustic output, but mic capture still bad: `envelope_cv_25ms=0.572`, `peak_to_trough=39.36 dB`; McBSP stop still showed `IRQST=0x0710`, TAS pre-mute `err=0x10`. | Deep CPU idle / MPUSS idle is not the wobble root cause. |
| Runtime DR pad remux to old S/PDIF mode | `artifacts/audio-rootcause-dr-pad-mcasp-runtime-20260614-193414` | Temporarily changed `abe_mcbsp2_dr` pad from `0x0108` to mode2/output `0x0002`, played the same DMA tone, then restored `0x0108`. Mic capture was weak/bad; McBSP still stopped with `IRQST=0x0710`, TAS pre-mute `err=0x10`. | The unused DR pad mux and RX-underflow status are not sufficient to explain the wobble. |
| Runtime CLKX/FSX input receiver enable | `artifacts/audio-rootcause-clkfs-input-enable-runtime-20260614-193515` | Temporarily changed CLKX and FSX pads from output-only `0x0000` to input-enabled `0x0100`, played the same DMA tone, then restored `0x0000`. Mic capture stayed bad: `envelope_cv_25ms=0.648`, `peak_to_trough=41.41 dB`; McBSP stop changed to `IRQST=0x0712`. | Enabling pad receivers on generated CLKX/FSX is not a fix and may worsen status bits. |
| Linux 3.0 actual-speaker reference, harnessed | `artifacts/audio-rootcause-linux30-speaker-reference-20260614-200414` | Booted `artifacts/nexusq-linux30-rescue-audio-baseline-autofastboot.img`, primed TAS5713 volume `0x50`, streamed the existing 500 Hz left-channel WAV through `nqstreamd`, and captured with the MacBook microphone. Harness and ffmpeg exited `0`, but the long capture window was too quiet/delayed for a clean verdict. | The old-kernel reference needs a direct, tightly-windowed playback test before it can be trusted. |
| Linux 3.0 actual-speaker reference, direct | `artifacts/audio-rootcause-linux30-speaker-reference-direct-20260614-200654` | Generated a clean 12 s 500 Hz left-channel WAV at source peak `0.05`, primed TAS5713 volume `0x50`, streamed directly to `nqstreamd`, and captured the fixed 2-14 s mic window. Source WAV is clean (`zero_cross_freq_hz=499.958`, `envelope_peak_to_trough_db_25ms=0`). Mic capture was noisy and over-reported room/background artifacts. | Do not reject 3.0 from Mac mic metrics alone. |
| Linux 3.0 user replay | `artifacts/audio-rootcause-linux30-speaker-replay-20260614-201933` | Replayed the same 12 s 500 Hz left-channel WAV on Linux 3.0 at TAS volume `0x50`. User verdict: "WAY better" and "sounds perfect to me." | Linux 3.0 is the accepted known-good acoustic reference. Diff 6.6 against this path. |

Current software-visible narrowing:

- Userspace PCM/MP3 source, ALSA refill, period wakeups, DMA logical channel,
  DMA cyclic geometry, obvious McBSP registers, nominal clocks, TAS static init
  table, TAS DSP coefficients, TAS DAI callbacks, MCLK ownership, cpuidle, and
  tested pad-mux deltas have all been weakened.
- The remaining plausible causes are in the 6.6 port layer: TAS5713 power/mute
  sequencing, TAS5713 register state during stream start, McBSP start/FIFO/DMA
  ordering, DMA programming differences not visible in the headline McBSP
  registers, or a subtle ASoC format/trigger-order mismatch.
- The next high-signal step is to diff the accepted 3.0 path against 6.6 using
  both source and live runtime state from the same 500 Hz playback.

## 2026-06-14 Late Evening: 3.0 Is The Acoustic Reference

Reset the working assumption after the user replayed the 3.0 kernel through the
actual speaker:

- The Linux 3.0 speaker path is accepted as clean. Do not use the MacBook mic
  alone to reject it; room noise and capture timing produced misleading
  envelope metrics.
- The Linux 6.6 path is still a port regression until a user-heard test is
  confirmed wobble-free.
- "Less bad" remains a failed test. The next success criterion is a continuous
  left-channel 500 Hz PCM tone without audible flutter, then WAV/MP3 playback.

Latest 3.0 runtime state from
`artifacts/audio-rootcause-linux30-speaker-reference-20260614-200414`:

- SDMA channel 0 during playback:
  - `CCR=0x00001091`
  - `CLNK=0x00008000`
  - `CICR=0x0000092A`
  - `CSDP=0x00000181`
  - `CEN=0x00000810`
  - `CFN=0x00000004`
  - `CDSA=0x49024008`
- McBSP2 during playback:
  - `SPCR2=0x000002F5`
  - `SPCR1=0x00000030`
  - `RCR2=0x00008041`
  - `RCR1=0x00000040`
  - `XCR2=0x00008041`
  - `XCR1=0x00000040`
  - `SRGR2=0x0000101F`
  - `SRGR1=0x00000F0F`
  - `PCR0=0x00000F0F`
  - `SYSCON=0x00000014`
  - `IRQST=0x00000700`
  - `IRQEN=0x00000800`
  - `XCCR=0x00001008`
  - `RCCR=0x00000809`

New 6.6 parity finding:

- A previous 6.6 "parity" test still forced SDMA read/write priority bits that
  3.0 did not use. Removing `NQ_DMA_FORCE_RW_PRIORITY` made the live 6.6 SDMA
  channel register state match the 3.0 headline DMA geometry:
  - Artifact:
    `artifacts/audio-rootcause-linux66-minimal-no-rw-priority-20260614-204024`
  - Reload key:
    `NQ_DMA_FORCE_LCH_SIG=17`, `NQ_DMA_FORCE_LCH=0`,
    `NQ_DMA_FORCE_RW_PRIORITY=0`, `NQ_DMA_CYCLIC_BURST_BITS=64`
  - During playback: `CCR=0x00001091`, `CLNK=0x00008000`,
    `CICR=0x0000092A`, `CSDP=0x00000181`, `CEN=0x00000810`,
    `CFN=0x00000004`, `CDSA=0x49024008`

Trigger-order experiments:

| Test | Artifact | Runtime result | Pending / conclusion |
| --- | --- | --- | --- |
| 6.6 minimal no forced SDMA priority | `artifacts/audio-rootcause-linux66-minimal-no-rw-priority-20260614-204024` | SDMA channel state matches 3.0 headline registers. McBSP2 still reports `IRQST=0x0710` instead of 3.0 `0x0700`. | Awaiting/needs user ear verdict. |
| 6.6 codec-first async old-order approximation | `artifacts/audio-rootcause-linux66-codec-first-old-order-20260614-204407` | Modern trigger order was changed to codec/link handling before DMA/McBSP. SDMA still matches 3.0 headline registers. McBSP2 still reports `IRQST=0x0710`. | Awaiting/needs user ear verdict. |
| 6.6 codec-first blocking TAS reinit | `artifacts/audio-rootcause-linux66-codec-first-blocking-reinit-20260614-204528` | Full TAS stream reinit completed before DMA/McBSP start. SDMA still matches 3.0 headline registers. McBSP2 still reports `IRQST=0x0710`. | Awaiting/needs user ear verdict. |

Other checks:

- `tools/check_tas5713_init_parity.py` reports the modern TAS5713 init table is
  byte-for-byte equivalent to the old 3.0 table for the programmed register
  sequence.
- The clock setup is nominally equivalent: both paths use a 12.288 MHz codec
  MCLK and 24.576 MHz McBSP functional clock, with the McBSP2 sync mux parented
  to the ABE 24 MHz clock.
- The only consistent live register diff left in the close-parity tests is
  McBSP2 `IRQST` bit `0x10` (`RUNDFLEN`, receive underflow) on 6.6. This is an
  RX-side status bit during TX-only playback, so it may be collateral rather
  than causal, but it is now one of the few concrete runtime differences.

Immediate next experiment if 6.6 still flutters:

1. Run the lowest-path tone test again with exact 3.0 SDMA parity and no forced
   SDMA priority bits.
2. Try clearing/suppressing the McBSP RX-underflow status around playback to
   see whether `IRQST=0x0710` is just a status artifact or tracks the audible
   wobble.
3. If underflow status is not causal, isolate the data path with an in-kernel
   DMA tone buffer so ALSA userspace refill and pointer accounting cannot be
   blamed.

## 2026-06-14 Late Evening: DMAengine Pointer/Residue Suspect

New low-level tests after exact 3.0 SDMA register parity:

| Test | Artifact | Result | Current interpretation |
| --- | --- | --- | --- |
| 6.6 in-kernel DMA tone, exact SDMA parity | `artifacts/audio-rootcause-linux66-dma-tone-exact-parity-20260614-205042` | `aplay.status=0`; DMA-tone override engaged; SDMA `CCR=0x1091`, `CICR=0x092a`, `CSDP=0x0181`, `CEN=2064`, `CFN=4`, destination `0x49024008`; McBSP still showed `IRQST=0x0710`. | This removes userspace PCM sample generation from the fault path. |
| 6.6 in-kernel DMA tone with mic/status capture | `artifacts/audio-rootcause-linux66-dma-tone-exact-parity-mic-20260614-205206` | The heavy capture run reported repeated `aplay` underruns/XRUNs even though the DMA source was generated in-kernel. | Strong clue that the modern dmaengine PCM period/pointer path can falsely or actually starve/restart playback under load. |
| 6.6 in-kernel DMA tone with `nq_force_descriptor_residue=1` | `artifacts/audio-rootcause-linux66-dma-tone-descriptor-residue-20260614-205441` | Direct playback completed with `aplay.status=0`, no printed underruns, 573 DMA IRQ callbacks over the 12 s WAV, and exact 3.0 SDMA geometry. | Forcing descriptor-level residue makes the generic PCM layer use period counting instead of SDMA residue reads. This is a plausible fix candidate. |
| 6.6 normal PCM with `nq_force_descriptor_residue=1` | `artifacts/audio-rootcause-linux66-pcm-descriptor-residue-20260614-205614` | Direct playback completed with `aplay.status=0`, no printed underruns, 573 DMA IRQ callbacks, and exact 3.0 SDMA geometry. | This climbs back from DMA-tone to normal ALSA PCM. Needs user ear verdict before calling it fixed. |
| 6.6 normal PCM with `nq_force_descriptor_residue=1`, lightweight mic capture | `artifacts/audio-rootcause-linux66-pcm-descriptor-residue-miclight-20260614-205659` | `aplay.status=0`, no printed underruns. Mic capture still had weak expected-tone energy and high envelope variation, so it is not suitable as a pass/fail oracle in this room. | Keep user listening verdict primary. |

Why this matters:

- The 6.6 generic dmaengine PCM layer normally uses DMA residue reads when the
  DMA driver advertises burst-level residue granularity.
- Setting `omap_dma.nq_force_descriptor_residue=1` makes the OMAP DMA driver
  advertise descriptor-level granularity. The ASoC dmaengine PCM wrapper then
  falls back to `snd_dmaengine_pcm_pointer_no_residue()`, which advances by
  period callbacks instead of live SDMA residue.
- The old 3.0 OMAP PCM path did not use the same modern generic dmaengine
  pointer path. A regression here is consistent with audible restart/flutter
  while the McBSP/SDMA headline registers are otherwise correct.

Important caveats:

- `IRQST=0x0710` remains present with and without descriptor-residue forcing,
  so `RUNDFLEN` is probably not the primary cause if descriptor-residue proves
  clean by ear.
- The mic capture remains too noisy/weak to adjudicate "clean" versus
  "flutter"; use it only for relative trends unless the expected-tone SNR is
  much stronger.
- The descriptor-residue condition is not yet accepted until the user confirms
  the normal PCM tone is wobble-free through the speaker.

Persistence work:

- Updated `tools/build_audio_dma_modular_image_local.sh` so the audio DMA
  modular image builder includes the loader marker
  `/etc/nq-force-descriptor-residue` by default.
- Rebuilt
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`.
- Verified the rebuilt initramfs contains:
  - `etc/nq-force-descriptor-residue`
  - `etc/nq-force-lch-sig`
  - `etc/nq-force-lch`
  - `lib/modules/omap-dma.ko`
- Booted the rebuilt image via fastboot and confirmed live module parameters:
  - `nq_force_descriptor_residue=Y`
  - `nq_force_lch_sig=17`
  - `nq_force_lch=0`
  - `nq_force_rw_priority=N`

Fresh-boot validation:

| Test | Artifact | Result | Current interpretation |
| --- | --- | --- | --- |
| Rebuilt image, normal PCM after fresh boot | `artifacts/audio-rootcause-linux66-booted-descriptor-residue-pcm-20260614-210454` | `aplay.status=0`, no printed underruns, SDMA `CCR=0x1091`, `CSDP=0x0181`, `CICR=0x092a`, `CEN=2064`, `CFN=4`, destination `0x49024008`. | Persistence path now matches the close-parity SDMA geometry and descriptor-residue fallback. Needs user ear verdict. |
| Rebuilt image, MP3 player smoke test | `artifacts/audio-rootcause-linux66-booted-descriptor-residue-mp3-20260614-210655` | `mpg123` decoded `/root/into-the-oceans-and-the-air.mp3` for 17 s until the local `timeout 20s` sent SIGTERM. The final `out123_play()` short write is attributed to that forced termination, not a standalone ALSA open failure. SDMA geometry remained exact. | MP3/player layer reaches hardware on the rebuilt image. Needs user ear verdict for quality. |

## 2026-06-14 Late Evening: Working 3.0 Reference And TAS Error Delta

Accepted reference:

- `artifacts/audio-rootcause-linux30-speaker-replay-20260614-201933`
- User verdict: Linux 3.0 playback sounds "WAY better" and "perfect" by ear.
- Treat Linux 3.0 as the known-good speaker reference. MacBook microphone
  metrics are not reliable enough in the room to overrule the user verdict.

Important delta:

- The accepted 3.0 reference had TAS5713 error register `0x02 = 0x00`.
- A rejected 6.6 replay had TAS5713 error register `0x02 = 0x50` during
  playback. Per the TAS5713 datasheet, `0x50` is PLL autolock plus frame-slip,
  which points at serial clock/frame instability, not an analog speaker problem.
- Earlier 6.6 runs sometimes had `err[0x02]=0x00` and still were not accepted,
  so `0x50` is not the only possible symptom. It is still a strong clue when it
  appears.

Code comparison results:

- The apparent TAS5713 GPIO polarity mismatch was checked and dismissed:
  the 6.6 DTS uses `GPIO_ACTIVE_LOW`, so `gpiod_set_value(..., 1)` asserts the
  physical low reset/PDN line just like the 3.0 `gpio_set_value(..., 0)` path.
- The TAS5713 static init table remains byte-for-byte equivalent to the 3.0
  table for the programmed register sequence.
- The remaining high-value behavioral mismatch is stream lifecycle:
  - 3.0 keeps TAS5713 powered down after probe and queues full reset/init/power
    work from the codec DAI trigger.
  - 3.0 does not call codec `set_fmt` or codec `hw_params` for TAS5713.
  - 3.0 enables `mcbsp2_sync_mux_ck` in machine `hw_params` and disables it in
    `hw_free`.
  - The current persisted 6.6 boot path keeps TAS5713 powered from probe and
    only mutes/unmutes at stream start unless diagnostic parameters override it.

New 3.0-shaped 6.6 experiments:

| Test | Artifact | Result | Current interpretation |
| --- | --- | --- | --- |
| 6.6 old-trigger-shaped, diagnostic | `artifacts/audio-rootcause-linux66-old3-trigger-shape-20260614-213604` | Reloaded 6.6 with descriptor-residue DMA parity, forced SDMA channel 0/sig 17, no SDMA RW priority, codec DAI callbacks skipped, McBSP sync clock held from `hw_params`, TAS legacy stream reinit enabled, async reinit delay `0`, and MCLK cycled on legacy reset. Heavy register dumping caused an initial `aplay` underrun/restart, but the full playback window then had TAS err-poll `samples=182`, `err_nonzero=0`, `last_err=0x00`. A final `pre-mute err[0x02]=0x10` appeared during stop. | This is the first 6.6 run that clearly keeps TAS error polling clean during playback while matching the old lifecycle more closely. Do not judge audio quality from the first logged run because the debug dumps caused startup disturbance. |
| 6.6 old-trigger-shaped, quiet replay | `artifacts/audio-rootcause-linux66-old3-trigger-shape-quiet-20260614-213724` | Same old-shaped module parameters, but TAS/DMA audio debug dumps and error polling disabled. `aplay.status=0` with no printed underrun. McBSP headline registers still match 3.0 except the recurring RX-side `IRQST=0x0710`. | Awaiting user ear verdict. If clean, collapse these parameters into the normal 6.6 boot defaults and remove the noisy debug paths from the production profile. If still fluttering, the next diff is below the visible TAS init/lifecycle layer: McBSP frame generation or DMA pacing under the modern ASoC trigger order. |
| 6.6 old-trigger-shaped, tinyalsa/nqstreamd replay | `artifacts/audio-rootcause-linux66-old3-trigger-shape-nqstreamd-20260614-214154` | Reused the exact WAV bytes from the accepted 3.0 reference and streamed them through `/tmp/nqstreamd -p 5555 -c 0 -d 0 --once`, matching the 3.0 userspace playback shape more closely than `aplay`. The stream completed, and a forced TAS read after close returned sticky `0x10`. McBSP start/stop stayed otherwise consistent with the old-shaped `aplay` run. | Awaiting user ear verdict. If `nqstreamd` sounds clean while `aplay` does not, focus above the kernel hardware path. If both flutter, continue below ALSA userspace and compare McBSP timing/runtime PM against 3.0. |

Candidate good 6.6 runtime profile if the quiet replay is accepted:

- `omap_dma.nq_force_descriptor_residue=1`
- `omap_dma.nq_force_lch_sig=17`
- `omap_dma.nq_force_lch=0`
- `omap_dma.nq_force_rw_priority=0`
- `snd_soc_tas571x.nq_legacy_stream_reinit=1`
- `snd_soc_tas571x.nq_async_legacy_stream_reinit_ms=0`
- `snd_soc_tas571x.nq_cycle_mclk_on_legacy_reset=1`
- `snd_soc_tas571x.nq_skip_hw_params=1`
- `snd_soc_steelhead_tas5713.nq_skip_codec_fmt=1`
- `snd_soc_steelhead_tas5713.nq_mcbsp_clk_hw_params=1`

Next step:

- Wait for user verdict on the quiet replay.
- If accepted, make the old-shaped profile the default runtime profile and
  rebuild the shareable image.
- If rejected, keep 3.0 as the reference and next instrument the exact start
  ordering and McBSP frame clock behavior rather than continuing broad sweeps.

## 2026-06-14 Late Evening: Persisted 3.0-Shaped 6.6 Profile

Changed the normal boot defaults to match the best 3.0-shaped 6.6 runtime
profile instead of requiring a manual module reload:

- `tools/nq-load-audio-rootfs.sh`
- generated `/sbin/nq-load-audio` block in `tools/build_debian_rootfs.py`
- `initramfs/debian-loader-init`
- `tools/build_audio_dma_modular_image_local.sh`

Persisted profile:

- `omap_dma.nq_force_descriptor_residue=1`
- `omap_dma.nq_force_lch_sig=17`
- `omap_dma.nq_force_lch=0`
- `omap_dma.nq_force_rw_priority=0`
- `omap_dma.nq_dump_cyclic=0`
- `omap_dma.nq_dump_irq_limit=0`
- `snd_soc_tas571x.nq_legacy_stream_reinit=1`
- `snd_soc_tas571x.nq_async_legacy_stream_reinit_ms=0`
- `snd_soc_tas571x.nq_cycle_mclk_on_legacy_reset=1`
- `snd_soc_tas571x.nq_skip_hw_params=1`
- `snd_soc_tas571x.nq_sdi_override=-1`
- `snd_soc_tas571x.nq_dump_regs=0`
- `snd_soc_steelhead_tas5713.nq_audio_dump=0`
- `snd_soc_steelhead_tas5713.nq_skip_codec_fmt=1`
- `snd_soc_steelhead_tas5713.nq_mcbsp_clk_hw_params=1`
- `snd_soc_steelhead_tas5713.nq_codec_power_first=0`

Build and boot validation:

| Test | Artifact | Result | Current interpretation |
| --- | --- | --- | --- |
| Manual current-profile replay | `artifacts/audio-rootcause-linux66-current-reference-replay-20260614-214729` | Same source WAV as accepted 3.0. `aplay.status=0`, no XRUN, forced TAS read after playback returned `0x00`. McBSP/SDMA headline state matched the accepted reference shape except recurring RX-side `IRQST=0x0710`. | The old-shaped profile no longer reproduces the hard `0x50` TAS frame-slip symptom. Mac mic capture remains too noisy/indirect to declare acoustic success. |
| Rebuilt image with persisted profile | `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img` | Fastboot boot succeeded. SSH returned. Audio card registered from rootfs loader. Live params confirmed TAS legacy reinit, skipped codec callbacks, McBSP sync clock from `hw_params`, descriptor-residue DMA, forced SDMA channel 0/sig 17. | Normal boot now uses the same profile as the manual tests. |
| Persisted profile replay before DMA-log cleanup | `artifacts/audio-rootcause-linux66-persisted-profile-replay-20260614-215324` | `aplay.status=0`, no XRUN, params correct, but `omap_dma.nq_dump_cyclic=Y` still emitted DMA start/stop diagnostics. Forced TAS read after playback returned sticky `0x10`. | Playback path worked, but production defaults were still too noisy. `0x10` appears at/after stop, unlike the earlier rejected during-playback `0x50`. |
| Clean persisted profile replay | `artifacts/audio-rootcause-linux66-clean-persisted-profile-replay-20260614-215843` | Rebuilt and booted cleaned image. Confirmed `DMA_DUMP=N`, `DMA_IRQ_LIMIT=0`, `TAS_REINIT=Y`, `SKIP_CODEC_FMT=Y`, `MCBSP_CLK_HW_PARAMS=Y`. `aplay.status=0`. No DMA cyclic debug output. McBSP registers matched the 3.0-shaped state. Forced TAS read after playback returned sticky `0x10`. | This is the current best 6.6 baseline. It is ready for user ear verdict against the accepted 3.0 reference. If flutter remains, continue below ALSA userspace by instrumenting McBSP frame-clock continuity and exact trigger timing. |
| Clean persisted profile replay with TAS error polling | `artifacts/audio-rootcause-linux66-clean-persisted-profile-errpoll-20260614-215946` | Same cleaned image and source WAV, with `snd_soc_tas571x.nq_err_poll_ms=100` enabled only for playback. `aplay.status=0`, `TASERR_AFTER=0x00`, and err-poll stopped with `samples=105`, `read_errors=0`, `err_nonzero=0`, `err_changes=0`, `last_err=0x00`, `last_sys2=0x00`. | The current persisted 6.6 profile does not reproduce the hard TAS `0x50` PLL/frame-slip error during the playback window. If flutter remains by ear, the failure is now more likely McBSP frame-clock continuity, trigger timing, or sample pacing than codec serial-error detection. |

Current status:

- Kernel-visible playback is stable on the clean persisted profile.
- The hard rejected `0x50` TAS error is not reproducing under this profile,
  including with TAS error polling active throughout playback.
- A sticky `0x10` after stop still occurs; do not treat it as equivalent to
  the rejected `0x50` unless it is observed during the audible playback window.
- The next decision still depends on user ear verdict for the clean persisted
  profile tone. If it is clean, promote this as the release image baseline. If
  flutter remains, the next target is McBSP frame generation/timing, not codec
  static init, DMA channel selection, or userspace PCM generation.

## 2026-06-14 Late Evening: 3.0 Diff Follow-Up

The user restated that Linux 3.0 is the working acoustic reference. Continued
from that assumption and tested only narrow differences against the current
3.0-shaped 6.6 profile.

New source-level findings:

- 3.0 configures the TAS5713 link by calling CPU DAI `set_fmt()` from machine
  `hw_params`; it does not call TAS5713 codec `set_fmt()` or codec
  `hw_params()`.
- 6.6's ASoC core applies `dai_link.dai_fmt` at card registration. With
  `CBC_CFC` on the link this still flips to CPU-provider mode for the McBSP,
  and the visible McBSP registers match the old CPU-provider setup.
- The 3.0 McBSP request path explicitly holds a runtime-PM reference with
  `pm_runtime_get_sync()` for the reservation lifetime. The 6.6 port did not
  hold the same reference in `omap_mcbsp_request()`.
- The 6.6 diagnostic path was still dumping McBSP registers at `dev_info`
  whenever legacy compatibility flags were enabled. 3.0 only had debug-level
  dumps, so this was a porting artifact in the normal profile.

Code changes from this pass:

- Added `snd_soc_steelhead_tas5713.nq_link_fmt` to isolate link-level ASoC
  format setup from the 3.0-style machine `hw_params()` setup.
- Added `snd_soc_omap_mcbsp.nq_legacy_pm_runtime_hold`; when enabled, McBSP
  request/free now hold/drop a runtime-PM reference like the downstream 3.0
  OMAP McBSP driver.
- Added `snd_soc_omap_mcbsp.nq_dump_regs`; McBSP start/stop register dumps are
  now explicit opt-in instead of being tied to the normal legacy profile.
- Updated the local and live `/sbin/nq-load-audio` profile to include
  `nq_legacy_pm_runtime_hold=1` and `nq_dump_regs=0`.

| Test | Artifact | Result | Current interpretation |
| --- | --- | --- | --- |
| 6.6 no link-level DAI format | `artifacts/audio-rootcause-linux66-linkfmt0-20260614-220854` and `artifacts/audio-rootcause-linux66-linkfmt0-miconly-20260614-221028` | Card registered with `nq_link_fmt=N`; minimal playback completed, but the heavy capture run produced `aplay` underruns and the Mac mic still did not resemble the 3.0 capture. | Link-level `dai_fmt` is not the leading root cause. Keep the default link format enabled unless a later diff proves otherwise. |
| 6.6 legacy McBSP runtime-PM hold | `artifacts/audio-rootcause-linux66-legacy-pmhold-minimal-20260614-221540` | `aplay_status=0`; module params confirmed `nq_legacy_pm_runtime_hold=Y`, old TAS lifecycle, skipped codec callbacks, and McBSP sync clock from `hw_params`. Visible McBSP/TAS register behavior otherwise unchanged. | This closes a real 3.0-vs-6.6 lifecycle difference. Needs user ear verdict; it is not disproven by register state. |
| 6.6 legacy PM hold under diagnostic stress | `artifacts/audio-rootcause-linux66-legacy-pmhold-stress-20260614-221617` | Heavy SSH/devmem/status capture still caused repeated `aplay` underruns. | PM hold does not make the heavy diagnostic sampler safe. Do not use the stress harness as an audio-quality oracle. |
| 6.6 quiet PM-hold replay, no McBSP dumps | `artifacts/audio-rootcause-linux66-quiet-pmhold-nodump-20260614-222217` | `aplay_status=0`; `nq_dump_regs=N`; `nq_legacy_pm_runtime_hold=Y`; dmesg line count stayed unchanged during playback. | Current best 6.6 candidate: no userspace XRUN, no TAS/McBSP diagnostic logging during playback, and closer 3.0 McBSP runtime-PM lifetime. Needs user speaker verdict against the accepted 3.0 tone. |
| Rebuilt quiet PM-hold image | `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img` | Rebuilt after updating the tracked kernel patch, rootfs loader, and live `/sbin/nq-load-audio` with `snd_soc_omap_mcbsp.nq_legacy_pm_runtime_hold=1` and `snd_soc_omap_mcbsp.nq_dump_regs=0`. | Shareable/fastboot boot image now contains the current best profile. It still needs the same user speaker verdict before being called the audio fix. |
| Rebuilt image clean-boot replay | `artifacts/audio-rootcause-linux66-rebuilt-image-pmhold-nodump-20260614-223041` | Fastboot-booted the rebuilt image. Boot defaults came up with `pm_hold=Y` and `mcbsp_dump=N`. Replayed the 500 Hz PCM tone: `aplay_status=0`, and dmesg line count stayed unchanged during playback. | The rebuilt image, not just a manual module reload, now boots into the current best quiet PM-hold profile. Remaining blocker is acoustic verdict versus the accepted Linux 3.0 reference. |

Current best runtime profile:

- `omap_dma.nq_force_descriptor_residue=1`
- `omap_dma.nq_force_lch_sig=17`
- `omap_dma.nq_force_lch=0`
- `omap_dma.nq_force_rw_priority=0`
- `omap_dma.nq_dump_cyclic=0`
- `omap_dma.nq_dump_irq_limit=0`
- `snd_soc_omap_mcbsp.nq_legacy_element=1`
- `snd_soc_omap_mcbsp.nq_legacy_threshold_frame=1`
- `snd_soc_omap_mcbsp.nq_legacy_pm_runtime_hold=1`
- `snd_soc_omap_mcbsp.nq_no_rx_err_irq=1`
- `snd_soc_omap_mcbsp.nq_legacy_tx_irq=1`
- `snd_soc_omap_mcbsp.nq_dump_regs=0`
- `snd_soc_tas571x.nq_legacy_stream_reinit=1`
- `snd_soc_tas571x.nq_async_legacy_stream_reinit_ms=0`
- `snd_soc_tas571x.nq_cycle_mclk_on_legacy_reset=1`
- `snd_soc_tas571x.nq_skip_hw_params=1`
- `snd_soc_tas571x.nq_dump_regs=0`
- `snd_soc_steelhead_tas5713.nq_link_fmt=1`
- `snd_soc_steelhead_tas5713.nq_skip_codec_fmt=1`
- `snd_soc_steelhead_tas5713.nq_mcbsp_clk_hw_params=1`
- `snd_soc_steelhead_tas5713.nq_audio_dump=0`

Next high-signal check:

- Ask for a direct speaker verdict on
  `artifacts/audio-rootcause-linux66-quiet-pmhold-nodump-20260614-222217`
  compared with the accepted Linux 3.0 replay. If it still flutters, continue
  below visible register parity by instrumenting frame-clock continuity or by
  building a deterministic DMA-to-DXR tone path that bypasses userspace without
  using the unsafe PIO harness.

## 2026-06-15 Fresh 3.0 vs 6.6 Acoustic A/B

The user corrected the acceptance reference: the Linux 3.0 replay through the
real speaker sounds essentially clean, while the 6.6 replay still has obvious
flutter. Treat this as the current control. Earlier notes that called one 6.6
run "clean" are not accepted evidence.

Fresh artifact root:

- `artifacts/fresh-3v6-acoustic-20260615-183849`

Fresh source:

- `nq-left-500-48000-S16_LE-12s-amp005.wav`
- 500 Hz, 48 kHz, S16_LE stereo, left channel only, 12 s, amplitude 0.05

Accepted Linux 3.0 reference:

- Image: `artifacts/nexusq-linux30-rescue-audio-baseline-autofastboot.img`
- Playback path: `/bin/nq-tas5713-volume 0x50 /dev/snd/pcmC2D0p`, source
  streamed through `nc`
- Mic capture: `linux30-mic.wav`
- Analysis: `linux30-mic-analysis.json`
- Detrended envelope std: `0.2038 dB`
- Detrended envelope p05-p95: `0.6364 dB`
- Dominant envelope modulation score: `0.026`

Bad Linux 6.6 reference:

- Image: `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
- Playback path: `aplay -D hw:0,0 --period-size=1032 --buffer-size=4128`
- Mic capture: `linux66-mic.wav`
- Analysis: `linux66-mic-analysis.json`
- Detrended envelope std: `1.6006 dB`
- Detrended envelope p05-p95: `5.2307 dB`
- `nqstreamd` on the same 6.6 image also remained bad.

Fresh register/runtime facts:

- 6.6 bad playback has `TAS5713` error register `0x02 == 0x00`; the earlier
  observed `0x50` did not reproduce and is not treated as the root cause.
- Direct I2C reads of TAS multiword DSP registers match the 3.0 init table.
- McBSP2 live playback registers match the 3.0 baseline for the important
  serial setup: `SPCR2=0x02f5`, `SPCR1=0x0030`,
  `RCR/XCR=0x8041/0x0040`, `SRGR=0x101f/0x0f0f`, `PCR0=0x0f0f`,
  `XCCR=0x1008`, `RCCR=0x0809`.
- SDMA channel 0 in 6.6 playback also matches the 3.0 geometry for
  period-size 1032: `CCR=0x1091`, `CICR=0x092a`, `CSDP=0x0181`,
  `CEN=0x0810`, `CFN=4`, `CDSA=0x49024008`.

DMA progress instrumentation:

- Added `omap_dma.nq_progress_poll_ms` to sample cyclic DMA source progress.
- Rebuilt and booted the modular 6.6 image so the initramfs-loaded `omap_dma`
  contained the sampler.
- Run artifact:
  `artifacts/fresh-3v6-acoustic-20260615-183849/linux66-dma-progress-1ms.txt`
- McBSP FIFO polling saw no TX underrun and a full/nearly-full TX FIFO.
- DMA source progress summary at 1 ms polling:
  `avg_delta=190 bytes`, `avg_us=1007`, `zero_delta=150`,
  `out_of_range=0`.

Interpretation:

- Userspace refill, ALSA XRUNs, and gross TX FIFO starvation are weakened.
- Static McBSP/TAS/SDMA register parity is not sufficient; the remaining fault
  is dynamic behavior below userspace.
- The 6.6 mic spectrum has strong sidebands near the tone. A valid long-buffer
  discriminator did not prove simple full-ring wrap. The next focused test is
  an integer-cycles-per-period tone on the long-period setup to separate
  period-boundary discontinuity from fixed lower-layer clock/codec modulation.

Integer-period kernel-DMA tone discriminator:

- Corrected run:
  `artifacts/audio-rootcause-linux66-kdmatone-512-intperiod-irq-20260615-192057`
- Higher-SNR repeat:
  `artifacts/audio-rootcause-linux66-kdmatone-512-intperiod-amp4096-20260615-192328`
- Setup: `omap_dma.nq_audio_tone=Y`, 512 Hz, 48 kHz, left-only, period
  `6000` frames, buffer `24000` frames. This is exactly 64 tone cycles per
  period, so a basic period-boundary phase discontinuity should disappear.
- Both runs completed with `aplay_status=0`.
- The higher-SNR repeat still showed bad-family modulation:
  `envelope_cv_25ms=0.410`, `envelope_peak_to_trough_db_25ms=12.07`,
  `envelope_mod_peak_hz_25ms=13.52`.

Interpretation update:

- The wobble persists when the DMA engine loops over a kernel-owned tone buffer
  whose period contains an integer number of cycles.
- Simple ALSA/userspace refill, MP3 decode, and simple cyclic period-wrap phase
  discontinuity are no longer good explanations.
- The next high-signal branch is dynamic behavior below the DMA source buffer:
  McBSP clock/frame continuity, ASoC trigger ordering, or TAS5713 stream/power
  timing that differs from the 3.0 workqueue-trigger path.

DR pad discriminator:

- Run:
  `artifacts/audio-rootcause-linux66-dr-pad-mode7-20260615-193057`
- Setup: while the long-buffer 512 Hz kernel-DMA tone was configured, changed
  the `abe_mcbsp2_dr` pad at `0x4a1000f8` from `0x0108` to `0x011f`, played
  the tone, then restored `0x0108`. The transmit pins were left unchanged.
- Result: `aplay_status=0`, but the acoustic capture stayed in the bad family:
  `envelope_cv_25ms=0.366`, `envelope_peak_to_trough_db_25ms=10.40`,
  `envelope_mod_peak_hz_25ms=13.42`.

Interpretation update:

- The unused receive pad and RX-side status are not sufficient to explain the
  audible left-channel modulation.
- The old 3.0 board code also requested a global L3 bus-throughput floor via
  `omap_pm_set_min_bus_tput(..., 200 * 1000 * 4)`. The 6.6 port has no direct
  equivalent yet. Re-test idle/QoS behavior against the accepted 512 Hz
  kernel-DMA setup before touching wider audio sequencing.

Idle/QoS discriminator:

- Run:
  `artifacts/audio-rootcause-linux66-idleoff-kdmatone-20260615-193354`
- Setup: forced every exposed `cpu0/cpuidle/state*/disable` file to `1`,
  configured the same 512 Hz kernel-DMA tone, and played with period `6000`
  frames / buffer `24000` frames. Restored cpuidle state files after playback.
- Result: `aplay_status=0`; acoustic capture stayed in the same bad family:
  `envelope_cv_25ms=0.398`, `envelope_peak_to_trough_db_25ms=12.05`,
  `envelope_mod_peak_hz_25ms=14.62`.

Interpretation update:

- CPU idle residency and the missing old global L3 reserve are not sufficient
  to explain the accepted 6.6 flutter.
- The next branch is clock topology/rates during playback: matching McBSP
  divider registers does not prove that the 6.6 parent clocks and TAS MCLK
  match the 3.0 runtime path.

TAS live-volume discriminator:

- Initial run:
  `artifacts/audio-rootcause-linux66-tas-oldvol-kdmatone-20260615-193720`
- Live-set run:
  `artifacts/audio-rootcause-linux66-tas-oldvol-live-kdmatone-20260615-193758`
- Observation: setting `mvol=0x50`, `ch1=0x30`, and `ch2=0x30` before
  playback did not hold; the 6.6 stream start restored ALSA control values
  `0x4b/0x4b/0x4b`.
- Retest: applied the same old reference values after playback was already
  running. The values held during the post-set playback window:
  `mvol=0x50`, `ch1=0x30`, `ch2=0x30`, `err=0x00`, `sys2=0x00`.
- Result: the acoustic capture did not move convincingly toward the accepted
  3.0 reference. Treat TAS live volume/control mismatch as weakened.

Interpretation update:

- The remaining software-visible leads are now mostly lifecycle/timing at the
  serial boundary: whether TAS5713 lock/init relative to an already-running
  McBSP stream differs, or whether McBSP pin-level timing is bad despite clean
  software-visible state.

Newest 6.6 kernel-DMA tone runs:

- Invalid runs:
  `artifacts/audio-rootcause-linux66-kdmatone-512-clocktrace-20260615-195842`
  and
  `artifacts/audio-rootcause-linux66-kdmatone-512-clocktrace-1032-20260615-195934`.
  These failed before playback because the live Steelhead machine-driver period
  constraint was `1032` frames while the OMAP DMA PCM constraint was still
  `24000` bytes. ALSA correctly reported no usable configuration.
- Valid bad baseline:
  `artifacts/audio-rootcause-linux66-kdmatone-512-clocktrace-6000-20260615-200100`.
  Setup was the kernel-owned 512 Hz / 48 kHz / left-only DMA tone, period
  `6000` frames, buffer `24000` frames, amplitude `4096`. Playback completed
  with `aplay_status=0`, but the microphone analysis remained bad-family:
  `envelope_cv_25ms=0.450`,
  `envelope_peak_to_trough_db_25ms=14.10`, and
  `envelope_mod_peak_hz_25ms=11.94`.
- Valid clock/register trace:
  `artifacts/audio-rootcause-linux66-kdmatone-512-clocktrace-6000-regs-20260615-200211`.
  Playback again completed with `aplay_status=0`, and the clocks were active at
  the expected rates: TAS MCLK `auxclk1_ck=12.288 MHz`, McBSP fck/sync
  `24.576 MHz`, and PER DPLL M3x2 `61.44 MHz`. McBSP static serial registers
  still matched the 3.0 reference. This run caused non-fatal OMAP L3 abort
  warnings while reading some SDMA registers with userspace `devmem`; avoid
  broad SDMA devmem reads and prefer kernel-side instrumentation.
- TAS old-lifecycle retest:
  `artifacts/audio-rootcause-linux66-kdmatone-512-async-oldtas-6000-20260615-200418`.
  This enabled old-style stream reinit timing and held TAS volumes near the 3.0
  shape (`mvol=0x50`, channel volumes `0x30/0x30`) during playback. The tone
  still measured bad-family:
  `envelope_cv_25ms=0.438`,
  `envelope_peak_to_trough_db_25ms=14.42`, and
  `envelope_mod_peak_hz_25ms=13.56`.

Interpretation update:

- The current valid bad path is below userspace: a kernel-owned DMA source
  buffer, integer-period tone, correct McBSP serial register shape, expected
  clocks, and no TAS error register fault still produce audible wobble.
- Simple TAS volume/lifecycle differences are weakened.
- The next focused discriminator is McBSP2 pad/electrical setup. A 6.6 DTS
  pinmux value can produce correct-looking McBSP registers while still changing
  pad receiver/pull behavior versus the 3.0 board/bootloader state.

Clean 6.6 kernel-DMA baseline after module reload:

- Artifact: `artifacts/audio-rootcause-linux66-kdmatone-512-clean-baseline-20260615-201507`.
- First attempt is invalid. Steelhead `nq_period_size` was changed to `6000`
  frames while `snd_soc_ti_sdma` still constrained period bytes to the old
  value, so ALSA rejected the open (`aplay_status=1`). Ignore that
  `mic-capture.m4a`.
- Reloaded the audio stack with `snd_soc_ti_sdma.nq_period_bytes=24000` and
  `nq_periods=4`, then set Steelhead period size/periods to `6000/4`. The
  kernel-DMA tone was 512 Hz, 48 kHz, left-only, amplitude `4096`.
- Valid rerun `aplay-24000.log`: `aplay_status=0`.
- Mic metrics from `mic-capture-analysis-24000.txt`:
  `envelope_cv_25ms=0.437669`, peak-to-trough `13.8306 dB`, modulation peak
  `11.8627 Hz`, measured zero-cross tone `512.474 Hz`, and very low harmonic
  ratios.

Interpretation update:

- The 6.6 failure is cleanly reproduced below userspace with correct tone
  frequency and no clipping/square-wave signature. The symptom is amplitude
  modulation, not MP3 decode, userspace refill, ALSA XRUN, or tone generation.

Latest rejected TAS/control-path hypotheses:

- TAS literal 3.0 volume staging:
  `artifacts/audio-rootcause-linux66-kdmatone-512-tas-literal-oldvol-20260615-202243`.
  During the same 6.6 kernel-DMA tone, direct I2C forced the live hardware
  registers to the literal 3.0 dump values: master volume `0xff`, channel
  volumes `0x30/0x30`, soft mute off, and error register cleared. Playback
  completed with `aplay_status=0`, but the microphone capture did not improve
  (`envelope_cv_25ms=0.714`, peak-to-trough `13.36 dB`). This also bypassed
  regmap, so hardware/cache were resynchronized afterward. Literal TAS volume
  staging is not the fix.
- Wi-Fi down / USB control:
  `artifacts/audio-rootcause-linux66-kdmatone-512-wifi-down-20260615-202425`.
  The target was controlled over USB SSH (`169.254.42.2`), `wlan0` was set
  down, and the same 512 Hz kernel-DMA tone was played. Playback completed with
  `aplay_status=0`, but the capture stayed bad-family
  (`envelope_cv_25ms=0.392`, peak-to-trough `12.60 dB`, modulation peak
  `13.5 Hz`). Wi-Fi traffic/control path is not the root cause.
- TAS SDI register live-forced to the 3.0 value:
  `artifacts/audio-rootcause-linux66-kdmatone-512-force-sdi03-live-20260615-202556`.
  The live stream already reported TAS SDI register `0x04=0x03`; the run forced
  it to `0x03` again after playback start and confirmed it stayed there.
  Playback completed with `aplay_status=0`, but the capture stayed bad-family
  (`envelope_cv_25ms=0.422`, peak-to-trough `12.79 dB`, modulation peak
  `13.90 Hz`). This matches the earlier SDI sweep and rejects a simple
  TAS serial-format register mismatch.
- McBSP2 DR pad mux/control A/B:
  `artifacts/audio-rootcause-linux66-pad-dr-ab-20260615-203803`. Linux 3.0
  later muxes the unused `abe_mcbsp2_dr` pad as `abe_mcasp_axr` output for the
  S/PDIF path, while 6.6 leaves it as McBSP DR input/pulldown (`0x0108`). A
  live A/B tested `DR=0x0108` and vendor-style `DR=0x0002`, then restored
  `0x0108`. Auto-active analysis initially produced a false "clean" result by
  selecting only a 0.05 s window. Re-analysis over the known playback window
  showed both cases still bad-family:
  - `DR=0x0108`: peak-to-trough `12.76 dB`, modulation peak `14.13 Hz`.
  - `DR=0x0002`: peak-to-trough `12.32 dB`, modulation peak `14.13 Hz`.
  This rejects the unused DR/SPDIF pad mux as the root cause.

Interpretation update:

- Remaining high-value differences are now clock and McBSP porting details that
  are not captured by the headline McBSP register values: clock parent/source
  lifecycle, divider programming relative to enable, and any modern driver
  semantic changes around `set_sysclk()`/`set_clkdiv()`.

Direct TAS5713 hardware state during bad 6.6 kernel-DMA tone:

- Added repeatable script:
  `tools/run_tas_direct_i2c_kdmatone_local.sh`. It runs the same 6.6
  kernel-owned 512 Hz / 48 kHz / left-only SDMA tone, captures the Mac
  microphone, analyzes a fixed playback window (`--window-start 2
  --window-duration 8 --no-active-region`), and uses direct target-side
  `i2cget`/`i2ctransfer` reads instead of regmap debugfs.
- Artifact:
  `artifacts/audio-rootcause-linux66-tas-direct-i2c-kdmatone-20260615-204945`.
  Playback completed (`aplay_status=0`) and reproduced the bad-family acoustic
  result: peak-to-trough `13.823 dB`, envelope CV `0.428`, modulation peak
  `13.750 Hz`.
- During active playback, direct TAS low registers stayed clean after the
  initial unmute/reinit transition: error register `0x02=0x00` and
  `sys2=0x00`.
- All direct-read TAS multiword DSP/control registers were stable across the
  run and matched the accepted 3.0 reference values for the registers that
  matter here: `input_mux`, `pwm_mux`, `ch1_bq3`, `ch1_bq4`, DRC attack/energy/
  decay/control, `bank_eq`, output mixers, and channel mixers. This rejects the
  earlier concern that regmap debugfs was hiding a TAS DSP-state mismatch.
- The first sample did catch a short startup transient (`sys1=0xa0`,
  `sdi=0x05`, volumes old-ish), then subsequent samples were back at the old
  values (`sys1=0x80`, `sdi=0x03`). That makes startup ordering testable but
  does not by itself explain continuous 10 s modulation.

TAS pre-initialized/no-mute startup ordering A/B:

- Artifact:
  `artifacts/audio-rootcause-linux66-kdmatone-preinit-no-tas-mute-20260615-205123`.
- Before playback, direct I2C reapplied the old TAS5713 init table and left the
  codec unmuted (`sys1=0x80`, `sdi=0x03`, `sys2=0x00`, error clear). For this
  run only, `snd_soc_tas571x.nq_mute_on_trigger=0` and
  `nq_legacy_stream_reinit=N`, so 6.6 did not perform the stream-start TAS
  mute/reinit hook.
- Result: still bad-family, peak-to-trough `16.351 dB`, envelope CV `0.522`,
  modulation peak `13.875 Hz`, TAS error stayed `0x00`, and `sys2` stayed
  `0x00`. Higher RMS was expected from the restored live volume; the modulation
  remained.
- Restored TAS diagnostic params afterward:
  `nq_mute_on_trigger=-1`, `nq_legacy_stream_reinit=Y`,
  `nq_async_legacy_stream_reinit_ms=0`.

Invalid DMA-tone no-period-IRQ attempt:

- Artifact:
  `artifacts/audio-rootcause-linux66-kdmatone-no-dma-period-irq-20260615-205247`.
- This run set `omap_dma.nq_audio_tone_no_irq=1` to suppress DMA frame/block
  period interrupts for the kernel-owned tone path, but it is not a valid audio
  verdict. `aplay` exited with `aplay_status=1` and
  `write error: Input/output error`; the PCM stream did not stay in the normal
  `RUNNING` playback state, TAS `sys2` showed shutdown/mute state (`0x40`),
  and the mic capture collapsed to near silence.
- Reset `omap_dma.nq_audio_tone_no_irq=0` afterward. Do not use this artifact
  to support or reject the wobble hypothesis; it only shows that simply
  disabling the DMA callbacks breaks the ALSA diagnostic harness.

McBSP `WAKEUPEN` parity check:

- Artifact:
  `artifacts/audio-rootcause-linux66-kdmatone-wakeupen0-20260615-210208`.
- Correction: the 3.0 `omap_mcbsp_config()` path itself does not write
  `WAKEUPEN`, but the 3.0 OMAP4 request helper does enable `XRDY/RRDY`
  wakeups. This was therefore not a 3.0 parity fix. It was still a useful
  causal A/B: a live run cleared `WAKEUPEN` at `0x401240a8` after playback
  start while keeping the same 512 Hz kernel-DMA tone and TAS direct-I2C
  monitor.
- Result: still bad-family, peak-to-trough `12.901 dB`, envelope CV `0.416`,
  modulation peak `14.169 Hz`; TAS error register stayed `0x00` during the
  running stream. This rejects McBSP wakeup-event enablement as required for
  the wobble, but it is not evidence of a real old/new mismatch.

Interpretation update:

- TAS init/register/lifecycle is now strongly weakened. The codec is configured
  like the 3.0 reference during the bad tone, does not report clock/serial
  errors in this controlled run, and pre-initializing it before McBSP start does
  not remove the wobble.
- The remaining likely fault is in the 6.6 SDMA/McBSP handoff or McBSP runtime
  behavior below the headline static registers: how samples are paced into the
  transmit FIFO, start/stop/reset sequencing, or an OMAP DMAengine semantic
  difference that still leaves FIFO/status counters looking superficially sane.

DMA fake-period discriminator:

- Change under test: added `omap_dma.nq_audio_tone_fake_period` in
  `kernel/linux-6.6.142/drivers/dma/ti/omap-dma.c`. For the kernel-owned tone
  stream, this clears real DMA frame/block period IRQs and uses an hrtimer to
  call `vchan_cyclic_callback()` at the period interval. The actual SDMA data
  movement into McBSP continues unchanged.
- Build/live setup: rebuilt
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
  so the loader initramfs includes the updated `omap-dma.ko`. The live module
  then exposed `/sys/module/omap_dma/parameters/nq_audio_tone_fake_period`.
- Invalid first run:
  `artifacts/audio-rootcause-linux66-kdmatone-fake-period-20260615-213004`.
  This used the stale `period-size=6000` harness geometry against the rebuilt
  image's current `period_bytes=4128` SDMA constraint. `aplay` failed before
  opening the PCM (`Broken configuration for this PCM`, `aplay_status=1`) and
  the mic capture was near silence. Do not use this as an audio verdict.
- Valid fake-period run:
  `artifacts/audio-rootcause-linux66-kdmatone-fake-period-p1032-20260615-213055`.
  Command shape:
  `NQ_HOST='fe80::16:42ff:fe00:2%en12' TONE_FAKE_PERIOD=1 TONE_NO_IRQ=0 TONE_AMP=4096 PERIOD_SIZE=1032 BUFFER_SIZE=4128 tools/run_tas_direct_i2c_kdmatone_local.sh`.
  Playback completed with `aplay_status=0`; the stream stayed `RUNNING`; TAS
  error stayed `0x00`; TAS `sys2` showed only `0x00,0x40`; and the kernel log
  confirmed `nq fake-period start ... interval_ns=21500000` followed by
  `nq fake-period stop ... callbacks=473 skipped=0`.
- Acoustic result for valid fake-period run: still bad-family,
  peak-to-trough `15.566 dB`, envelope CV `0.448`, modulation peak
  `13.375 Hz`, RMS `0.023155`.
- Same-boot real-period control:
  `artifacts/audio-rootcause-linux66-kdmatone-real-period-p1032-20260615-213202`.
  Same tone/amplitude/geometry with `TONE_FAKE_PERIOD=0`. Playback completed
  with TAS error `0x00`, but remained bad-family: peak-to-trough `21.337 dB`,
  envelope CV `0.502`, modulation peak `14.125 Hz`, RMS `0.022444`.

Interpretation update:

- The wobble is not caused by ALSA/userspace refill, and it is not removed by
  replacing DMA hardware period wakeups with timer-generated ALSA period
  callbacks. The fault is therefore below period-callback delivery.
- The remaining suspect area is continuous SDMA-to-McBSP transfer behavior or
  McBSP serial output timing itself: sample/frame continuity, FIFO service
  timing, port reset/start sequencing, or a dynamic clock/runtime behavior not
  visible in the static register snapshots.

SDMA global-control and progress-trace follow-up:

- Found a real 3.0-vs-6.6 source difference in the SDMA driver init path:
  vendor Linux 3.0 calls
  `omap_dma_set_global_params(DMA_DEFAULT_ARB_RATE,
  DMA_DEFAULT_FIFO_DEPTH, 1)`, while upstream 6.6 initializes `GCR` with
  `tparams=0`. On the live 6.6 image, SDMA `GCR` read as `0x00010010`; the
  3.0-shaped value is `0x00011010`.
- Live `GCR` tparams A/B:
  `artifacts/audio-rootcause-linux66-kdmatone-gcr-tparams1-p1032-20260615-214544`.
  Set SDMA `GCR` to `0x00011010` with `busybox devmem`, then replayed the same
  500 Hz kernel-DMA tone at period/buffer `1032/4128`. Playback completed, TAS
  error stayed `0x00`, but the acoustic result stayed bad-family:
  peak-to-trough `22.354 dB`, envelope CV `0.571`, modulation peak `13.500 Hz`.
  This rejects the SDMA global thread-reserve mismatch as sufficient.
- Live SDMA no-standby A/B:
  `artifacts/audio-rootcause-linux66-kdmatone-sdma-nostandby-p1032-20260615-214618`.
  Restored `GCR=0x00010010`, forced SDMA `OCP_SYSCONFIG` from `0x00002011` to
  no-standby `0x00001011` for the playback window, then restored it afterward.
  Playback completed, but the capture stayed bad-family: peak-to-trough
  `15.707 dB`, envelope CV `0.470`, modulation peak `12.500 Hz`. This weakens
  controller-level idle/standby as the source of the wobble.
- Added `omap_dma.nq_progress_trace_samples`, a bounded in-memory trace of DMA
  source position deltas dumped only after playback stop. Rebuilt
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
  with the updated `omap-dma.ko`; module compile and image rebuild both passed.
- Progress-traced run:
  `artifacts/audio-rootcause-linux66-kdmatone-progress-trace-p1032-20260615-215111`.
  Setup was the same 500 Hz kernel-DMA tone, period/buffer `1032/4128`, with
  `nq_progress_poll_ms=1` and `nq_progress_trace_samples=4096`.
  Acoustic result still reproduced the bad family: peak-to-trough `26.301 dB`,
  envelope CV `0.580`, modulation peak `13.375 Hz`.
- Trace summary from the captured samples: `dt_us min=30 max=7080 avg=1163.9`,
  `delta min=2 max=1390 avg=223.5`, `zero=0`, no long zero-progress runs.
  The delta-series peak from the available trace was near `1.113 Hz`, not near
  the acoustic `13.375 Hz` flutter. The hrtimer sampling itself is jittery, but
  this trace does not show DMA source-progress stalls or a 13 Hz DMA-service
  cadence.

Interpretation update:

- SDMA global `GCR` thread reserve, SDMA no-standby, ALSA period callbacks,
  userspace refill, and gross DMA source-progress stalls are all weakened.
- The highest-value remaining branch is now a targeted 3.0 reference capture
  of the low-level control surface we had not recorded before: SDMA global
  registers, McBSP2 pad-control registers, McBSP2 live registers, and active
  SDMA channel state during the accepted 3.0 playback.
- `tools/capture_linux30_audio_baseline_local.sh` has been updated to include
  SDMA global and McBSP2 pad-control reads. The attempt to reboot the current
  6.6 image back to fastboot for this 3.0 capture did not re-enumerate over
  USB as fastboot or ECM. Next device-side step: manually return the Q to
  fastboot, then boot
  `artifacts/nexusq-linux30-rescue-audio-baseline-autofastboot.img` and run the
  updated 3.0 capture against
  `artifacts/fresh-3v6-acoustic-20260615-183849/nq-left-500-48000-S16_LE-12s-amp005.wav`.

## 2026-06-15 Late Night: FIFO Trace And Codec-First Rejection

This round intentionally reduced the search back down to the hardware playback
path: kernel-owned SDMA tone buffer, 48 kHz S16_LE stereo slot format, period /
buffer `1032/4128`, TAS direct I2C reads, and fixed-window Mac microphone
analysis.

Harness fixes made during this round:

- `tools/run_tas_direct_i2c_kdmatone_local.sh` now sets both `Speaker Volume`
  and `Master Volume` before playback. The first FIFO-trace run was misleadingly
  quiet because `Master` was still `0`.
- The same harness now supports `I2C_POLL=0`, allowing playback with no direct
  I2C polling during the active stream. This avoids perturbing the TAS5713 while
  still reading the final state after playback.
- `snd_soc_omap_mcbsp.nq_fifo_trace_samples` was added as a bounded in-memory
  trace of McBSP TX FIFO free-count/status samples. Trace lines are emitted only
  after playback stops.
- `tools/reload_audio_modules_remote.sh` now passes the FIFO trace parameter
  through to `snd_soc_omap_mcbsp`.

FIFO trace results:

- `artifacts/audio-rootcause-linux66-fifo-trace-512-master80-20260615-223417`.
  This was a normal 6.6 old-shaped stream-start path with the fixed mixer
  setup and a 512-sample McBSP FIFO trace.
- Playback completed with `aplay_status=0`. The McBSP FIFO summary was
  `samples=9226`, `xbuf_free_min=0`, `xbuf_free_max=1`, `free0_samples=8736`,
  `free0_runs=461`, `free0_run_max=115`, `irqst_seen=0x0700`, and
  `spcr2_seen=0x02f7`.
- Interpretation: the TX FIFO is full or almost full during bad playback. There
  is no evidence of gross FIFO starvation or a periodic McBSP TX-underflow
  cadence matching the audible flutter.

TAS stream-reinit control:

- `artifacts/audio-rootcause-linux66-fifo-trace-512-no-reinit-master80-20260615-223545`.
  Disabling `snd_soc_tas571x.nq_legacy_stream_reinit` is not a valid audio
  verdict in the current 6.6 stack: TAS `sys2` stayed `0x40` during playback,
  so the amplifier remained in its shutdown/mute state. The legacy reinit path
  is currently required to wake the TAS5713 for 6.6 playback.

Codec-first / no-I2C-poll clean reproduction:

- `artifacts/audio-rootcause-linux66-codec-first-clean-master175-20260615-223845`.
  Module state: `snd_soc_steelhead_tas5713.nq_codec_power_first=Y`,
  `nq_skip_codec_fmt=Y`, `nq_mcbsp_clk_hw_params=Y`,
  `snd_soc_tas571x.nq_skip_hw_params=Y`,
  `snd_soc_tas571x.nq_legacy_stream_reinit=Y`,
  `snd_soc_tas571x.nq_mute_on_trigger=0`, no McBSP FIFO poll/trace, and
  `I2C_POLL=0` during playback.
- Dmesg proves TAS5713 unmute completed before the kernel SDMA tone began:
  final pre-DMA TAS unmute ended at `1157.454071`, then
  `omap-dma-engine ... nq audio-tone cyclic override ... freq=500 amp=4096`
  started at `1157.461273`.
- TAS state before stop was clean: `err[0x02]=0x00`, `sys2[0x05]=0x00`,
  `sdi[0x04]=0x03`, `mvol[0x07]=0x50`, `ch1/ch2=0x30`. The final direct I2C
  read after playback also showed `err=0x00`.
- Acoustic result was still bad-family:
  `envelope_peak_to_trough_db_25ms=15.5453`,
  `envelope_cv_25ms=0.460818`, and
  `envelope_mod_peak_hz_25ms=13.633`.

Interpretation update:

- Codec lifecycle/start order, visible TAS register state, direct I2C polling,
  mixer-volume mistakes, and gross McBSP TX FIFO starvation are now rejected or
  strongly weakened for the persistent 6.6 flutter.
- The remaining lead is still below ALSA userspace and below the TAS control
  surface: a 6.6 porting difference in McBSP/SDMA dynamic timing, serial clock
  or frame continuity, FIFO service semantics, or a start/reset sequence that
  leaves the same static register values but a different live serial waveform.

Old-vs-new trigger-order check:

- Linux 3.0 ASoC `soc_pcm_trigger()` calls codec DAI trigger, then platform
  DMA trigger, then CPU DAI trigger. In the modern 6.6 stack, the default order
  is link trigger, DMA component trigger, then DAI triggers; with
  `nq_codec_power_first=1`, this already gives the closest useful ordering:
  TAS unmute/reinit first, DMA second, McBSP CPU DAI third.
- `artifacts/audio-rootcause-linux66-ldc-codecfirst-clean-master175-20260615-225125`
  tested the alternative modern LDC order with the same kernel-owned 500 Hz
  tone, `Master=175`, `Speaker=207`, and no I2C polling during playback.
- Result: still bad-family and worse than the default clean run:
  `envelope_peak_to_trough_db_25ms=21.4738`,
  `envelope_cv_25ms=0.510389`, and
  `envelope_mod_peak_hz_25ms=13.8931`.
- Dmesg showed the expected ordering hazard for LDC:
  `omap-mcbsp ... TX Buffer Underflow!` logged just before the
  `omap-dma-engine ... nq audio-tone cyclic override` line. This is the
  opposite of the old 3.0 platform-before-CPU sequence and is not a fix.

Interpretation update:

- Do not keep chasing LDC/McBSP-before-DMA trigger order for this symptom. The
  closest old trigger shape is the default 6.6 order plus codec-first TAS
  handling, and that clean run still flutters.

McBSP threshold-mode closure:

- `artifacts/audio-rootcause-linux66-threshold-mode-kdmatone-master175-20260615-224949`
  tested McBSP `dma_op_mode=threshold` after resetting the audio stack to the
  non-LDC/default trigger order, with the same kernel-owned 500 Hz tone,
  `Master=175`, `Speaker=207`, period/buffer `1032/4128`, and no I2C polling
  during playback.
- The live McBSP sysfs state before playback was `element [threshold]` with
  `max_tx_thres=112` and `max_rx_thres=112`.
- Result: still bad-family: `envelope_peak_to_trough_db_25ms=14.267`,
  `envelope_cv_25ms=0.425`, and `envelope_mod_peak_hz_25ms=13.793`.
- The accepted Linux 3.0 speaker references showed `THRSH1=0x00000000` and
  `THRSH2=0x00000000` during playback, matching the normal one-word element /
  FIFO behavior rather than a large programmed threshold.

Interpretation update:

- McBSP threshold-mode DMA pacing is not the root cause. The old 3.0 reference
  appears to have used element/FIFO behavior, and forcing 6.6 threshold mode
  did not improve the low-level kernel-owned tone.
- The remaining useful comparison is time-varying McBSP clock/frame behavior,
  pin-control/clock-domain stability, or another dynamic condition that static
  McBSP register snapshots do not expose.

PM/clock-hold and expanded 3.0 register comparison:

- `artifacts/audio-rootcause-linux66-pmhold-inband-live-master175-20260615-225854`
  retested the minimal kernel-owned 500 Hz tone with McBSP runtime PM held
  active across playback, element DMA mode, no I2C polling, and in-band live
  clock/PCM sampling.
- Result: still bad-family:
  `envelope_peak_to_trough_db_25ms=18.617`, `envelope_cv_25ms=0.479`, and
  `envelope_mod_peak_hz_25ms=14.135`.
- The in-band sampler saw the stream genuinely `RUNNING`, McBSP runtime state
  `active`, and stable clock rows during playback:
  `dpll_per_m3x2_ck=61440000`, `auxclk1_ck=12288000`,
  `abe_24m_fclk=24576000`, and active prepared McBSP/target-module clocks.
- `artifacts/audio-rootcause-linux30-expanded-runtime-500hz-20260615-230312`
  captured the accepted Linux 3.0 speaker reference with expanded SDMA, pad,
  and McBSP register state during playback.
- The important 3.0 McBSP headline registers matched the bad 6.6 reference:
  `SPCR2=0x000002F5`, `SPCR1=0x00000030`, `RCR2/XCR2=0x00008041`,
  `RCR1/XCR1=0x00000040`, `SRGR2=0x0000101F`, `SRGR1=0x00000F0F`,
  `PCR0=0x00000F0F`, `SYSCON=0x00000014`, `THRSH1/2=0`.
- The important 3.0 SDMA channel geometry also matched the bad 6.6 reference:
  `CCR=0x00001091`, `CLNK=0x00008000`, `CICR=0x0000092A`,
  `CSDP=0x00000181`, `CEN=0x00000810`, `CFN=0x00000004`,
  `CDSA=0x49024008`. Source address/progress counters differ as expected.
- One hard hardware-facing delta remained visible: 3.0 had McBSP `DR` pad
  `0x0002` during playback while 6.6 defaults to `0x0108`.

3.0 McBSP pad-state retest on 6.6:

- `artifacts/audio-rootcause-linux66-pad-dr-old3-inband-master175-20260615-230641`
  forced the 6.6 McBSP pad registers to the 3.0 playback values before the
  same kernel-owned tone:
  `CLKX=0x0000`, `DR=0x0002`, `DX=0x0000`, `FSX=0x0000`.
  The original 6.6 values were restored immediately after playback.
- Result: still bad-family:
  `envelope_peak_to_trough_db_25ms=18.883`, `envelope_cv_25ms=0.485`, and
  `envelope_mod_peak_hz_25ms=13.727`.
- TAS state stayed clean (`err=0x00`, `sys2=0x40`) and the forced pad values
  did not change the symptom.

Interpretation update:

- Runtime PM/clock gating, static McBSP/SDMA register programming, SDMA global
  priority/standby, McBSP threshold mode, codec start order, and the one
  confirmed pad mux/pull delta are now rejected for the current kernel-owned
  500 Hz flutter.
- The remaining evidence points to a dynamic timing/servicing difference that
  leaves the static register snapshots identical: descriptor residue/period
  bookkeeping, SDMA interrupt/completion cadence, DMA memory/coherency behavior,
  or a McBSP start/prime sequence that affects the live serial waveform without
  changing the final programmed registers.

DMA-progress trace and static-parity closure:

- `artifacts/audio-rootcause-linux66-dma-progress-tracefull-20260615-235813`
  captured the same 6.6 kernel-owned 500 Hz DMA tone while tracing DMA source
  progress and McBSP FIFO status at 1 ms cadence.
- The acoustic result was still bad-family:
  `envelope_peak_to_trough_db_25ms=15.608`, `envelope_cv_25ms=0.481`, and
  `envelope_mod_peak_hz_25ms=13.184`.
- The DMA trace contained 3066 progress samples. Source-address deltas had
  `p50=192 bytes/ms`, exactly matching 48 kHz stereo S16 playback; there were
  no zero-delta samples, 42 samples with `delta <= 20`, and only one large
  terminal sample after/at stop. This rejects gross DMA source stalls as the
  source of the audible wobble.
- `artifacts/audio-rootcause-linux66-old3-static-combo-kdmatone-20260616-000151`
  then forced every known static hardware-facing 6.6 delta to the accepted 3.0
  playback state for the duration of a kernel-owned tone:
  SDMA `GCR=0x00011010`; McBSP pads `CLKX=0x0000`, `DR=0x0002`,
  `DX=0x0000`, `FSX=0x0000`; and the known-good McBSP/SDMA/TAS low-state
  registers.
- The forced-static combo still flutters. Generic detrended analysis reported
  `detrended_envelope_std_db=2.101`, `detrended_envelope_p05_p95_db=6.777`,
  `dominant_mod_hz=18.25`, and `mod_score=0.076`.
- During that bad 6.6 playback, the live register dump matched the accepted 3.0
  state for the important surfaces:
  `SPCR2=0x000002F5`, `SPCR1=0x00000030`, `RCR2/XCR2=0x00008041`,
  `RCR1/XCR1=0x00000040`, `SRGR2=0x0000101F`, `SRGR1=0x00000F0F`,
  `PCR0=0x00000F0F`, `SYSCON=0x00000014`, `THRSH1/2=0`,
  `XCCR=0x00001008`, `RCCR=0x00000809`, `XBUFFSTAT/RBUFFSTAT=0`,
  SDMA channel 0 `CCR=0x00001091`, `CLNK=0x00008000`, `CICR=0x0000092A`,
  `CSDP=0x00000181`, `CEN=0x00000810`, `CFN=0x00000004`,
  `CDSA=0x49024008`, and TAS `err[0x02]=0x00`, `sys2[0x05]=0x00`,
  `sdi[0x04]=0x03`, `mvol[0x07]=0x50`, `ch1/ch2=0x30`.
- The 6.6 DTS and live clock tree also mirror the 3.0 Steelhead clock intent:
  `dpll_per_m3x2_ck=61440000`, `auxclk1_src_ck` parented to it,
  `auxclk1_ck=12288000`, and McBSP2 parented to `abe_24m_fclk=24576000`.

Interpretation update:

- Static register differences are now closed. The 6.6 regression remains when
  the visible McBSP, SDMA, TAS, pad, and clock-rate state is forced to the 3.0
  reference.
- The next useful work is dynamic-only: clock/OPP perturbations that are too
  brief to appear in static debugfs snapshots, DMA/McBSP servicing jitter not
  visible as a source-address stall, cache/coherency behavior of the DMA tone
  buffer, or a start/prime sequence that changes the live serial waveform while
  settling to identical registers.

2026-06-16 continuation:

- The device came back as the 6.6 Debian USB gadget rather than fastboot. SSH
  over `root@fe80::16:42ff:fe00:2%en12` worked and `/sbin/nq-autoreboot-cancel`
  cancelled the autoreboot timer.
- Added `tools/analyze_audio_spectrum.py` to make the 3.0 vs 6.6 microphone
  comparison explicit. Artifact:
  `artifacts/audio-rootcause-spectrum-20260616-002631`.
- Fresh 3.0 vs 6.6 A/B using
  `artifacts/fresh-3v6-acoustic-20260615-183849`:
  - 3.0 `linux30-mic.wav`: `envelope_cv_25ms=0.044`.
  - 6.6 `linux66-mic.wav`: `envelope_cv_25ms=0.499`,
    `envelope_peak_hz=12.000`.
- Later bad 6.6 kernel-DMA captures have the same family signature:
  - `artifacts/audio-rootcause-linux66-clock-trace-kdmatone-20260616-001101`:
    `envelope_cv_25ms=0.467`, `envelope_peak_hz=12.955`.
  - `artifacts/audio-rootcause-linux66-abe-clkdm-wakeup-kdmatone-20260616-002214`:
    `envelope_cv_25ms=0.620`, `envelope_peak_hz=13.500`.
- Interpretation: the flutter is repeatable and deterministic around
  12-13.5 Hz, not random userspace refill noise. The current evidence still
  points below userspace PCM and below visible steady-state McBSP/SDMA/TAS
  register state.

Full TAS5713 parity closure:

- Added `tools/compare_tas5713_dumps.py` and
  `tools/capture_linux66_full_tas_dump_local.sh`.
- Captured full 6.6 TAS5713 state during a bad kernel-owned 500 Hz tone:
  `artifacts/audio-rootcause-linux66-full-tas-dump-kdmatone-20260616-001556`.
- Result: `expected_regs=70`, `actual_regs=70`, and
  `tas5713-dumps-match` against the accepted 3.0 dump.
- Interpretation: the codec init/runtime register path is closed. The 6.6 bad
  playback can occur with full TAS5713 state byte-for-byte matching the 3.0
  accepted reference.

Unsafe loopback branch:

- Tried the McBSP digital-loopback trace with
  `nq_dlb_trace_frames=48000`, `nq_dlb_block_frames=480`, and
  `nq_dlb_dump_blocks=120`.
- Artifact:
  `artifacts/audio-rootcause-linux66-mcbsp-dlb-kdmatone-20260616-001830`.
- The board lost SSH and watchdog recovered it to fastboot. The artifact only
  contains a short `remote.log` and no useful loopback data.
- Interpretation: do not repeat the current DLB harness. A redesigned loopback
  path may still be useful, but this implementation is not safe evidence.

Clock idle experiments:

- Disabled ABE DPLL autoidle by writing `0x00000000` to `0x4a0041e8`, then
  restored the original `0x00000001`. Artifact:
  `artifacts/audio-rootcause-linux66-abe-dpll-autoidle-off-kdmatone-20260616-002120`.
  Result remained bad-family: `p2t=15.536 dB`, `cv=0.466`,
  `mod=13.875 Hz`.
- Forced the ABE clockdomain wakeup mode by writing `0x2` to `0x4a004500`,
  then restored `0x3`. Artifact:
  `artifacts/audio-rootcause-linux66-abe-clkdm-wakeup-kdmatone-20260616-002214`.
  Result remained bad-family: `p2t=16.269 dB`, `cv=0.478`,
  `mod=13.500 Hz`.
- Interpretation: simple ABE DPLL autoidle and ABE clockdomain HW_AUTO idle are
  not the root cause.

Live 6.6 diagnostic state check:

- The current 6.6 image is already running with the important legacy-path
  knobs enabled: forced SDMA channel 0 for McBSP2 TX request 17, legacy cyclic
  sync/pack/burst/block IRQ, legacy McBSP element/threshold/IRQ behavior,
  legacy PM runtime hold, S16-only playback, codec DAI format/hw_params skipped,
  and `nq_ldc=N`.
- Because `nq_ldc=N`, the current ASoC trigger order is default
  `link -> component -> DAI`, so dmaengine starts before McBSP DAI start. That
  matches the important old 3.0 ordering at a high level and is not the active
  cause of the current bad run.

Root cause found: ABE DPLL reference parent

- Captured 3.0 over USB serial because macOS did not expose the 3.0 USB
  network interface in that boot. Added `tools/nq_serial_exec.py` for repeatable
  serial-shell control.
- Idle 3.0 clock artifact:
  `artifacts/audio-rootcause-linux30-serial-clockregs-20260616-003956`.
- Active 3.0 local-tone artifact:
  `artifacts/audio-rootcause-linux30-serial-during-20260616-004150`.
- During the accepted 3.0 tone, the audio-visible path was:
  `ABE_DPLL_REF_CLKSEL=0x00000000`, `ABE_CLKMODE_DPLL=0x00000007`,
  `ABE_CLKSEL_DPLL=0x00804018`, `ABE_DIV_M2_DPLL=0x00000801`,
  `ABE_IDLEST_DPLL=0x00000001`.
- Clean 6.6 before the fix used the mainline OMAP4 ABE setup:
  `ABE_DPLL_REF_CLKSEL=0x00000001`, `ABE_CLKMODE_DPLL=0x00000C07`,
  `ABE_CLKSEL_DPLL=0x0082EE00`. The clock framework reported
  `abe_dpll_refclk_mux_ck` parent `sys_32k_ck`.
- The visible output rates were still nominally correct in both cases
  (`dpll_abe_ck=98.304 MHz`, `abe_24m_fclk=24.576 MHz`), so this was a clock
  quality/reference-parent regression rather than a rate arithmetic error.
- Raw 6.6 discriminator:
  `artifacts/audio-rootcause-linux66-abe-ref-sysclkin-20260616-004448`.
  Reprogrammed only ABE DPLL to the 3.0 sys-clkin setup, then played the same
  kernel-owned 500 Hz tone. During playback, ABE locked and matched 3.0:
  `REF_CLKSEL=0`, `CLKSEL=0x00804018`, `IDLEST=1`. Mic analysis dropped from
  bad-family `envelope_cv_25ms ~= 0.47-0.62` with a 12-13.5 Hz modulation peak
  to `envelope_cv_25ms=0.119` with `envelope_peak_to_trough_db_25ms=0.190`.
- Implemented a Steelhead-only 6.6 clock quirk in
  `drivers/clk/ti/clk-44xx.c`: `google,steelhead` keeps the ABE DPLL reference
  parent on `sys_clkin_ck`, matching the vendor 3.0 kernel; other OMAP4 boards
  keep the generic `sys_32k_ck` workaround.
- Rebuilt image:
  `artifacts/nexusq-linux66-omap2plus-nosmp-audio-dma-wifi-public-debian-modular.img`
  from kernel `Linux (none) 6.6.142 #5 Tue Jun 16 00:49:05 PDT 2026`.
- Clean rebuilt-image artifact:
  `artifacts/audio-rootcause-linux66-abe-ref-sysclkin-built-20260616-005253`.
  Clean boot state shows `abe_dpll_refclk_mux_ck` parent `sys_clkin_ck` and
  `ABE_DPLL_REF_CLKSEL=0x00000000` without any runtime devmem poke.
- Clean rebuilt-image playback:
  `artifacts/audio-rootcause-linux66-abe-ref-sysclkin-built-20260616-005253/play-clean-built-20260616-005329`.
  During playback, ABE/McBSP/TAS matched the 3.0 reference and `aplay_rc=0`.
  Mac mic analysis stayed in the clean-family range:
  `envelope_cv_25ms=0.118`, `envelope_peak_to_trough_db_25ms=0.166`,
  `envelope_mod_peak_hz_25ms=0.590`, with TAS error register `0x02=0x00`.
- Project patch persistence: regenerated
  `patches/linux-6.6.142-nexusq-steelhead.patch` from targeted pristine-vs-live
  kernel diffs. Dry-run verified with
  `patch --dry-run -d build/patch-pristine/linux-6.6.142 -p2`.

Clean real-PCM and MP3 validation after the ABE DPLL fix:

- The device later presented as the booted 6.6 Debian USB gadget, not fastboot.
  Confirmed running kernel:
  `Linux (none) 6.6.142 #5 Tue Jun 16 00:49:05 PDT 2026 armv7l`.
- Cancelled the safety autoreboot and stopped Squeezelite before testing so the
  ALSA device was not held by the player endpoint.
- Important correction: the first two "clean-clockfix" smoke runs were useful
  clock-path checks but still had the diagnostic DMA tone override enabled
  (`/sys/module/omap_dma/parameters/nq_audio_tone=Y`). Do not use
  `artifacts/audio-rootcause-linux66-clean-clockfix-pcm-20260616-010131` or
  `artifacts/audio-rootcause-linux66-clean-clockfix-mp3-20260616-010201` as
  proof of userspace PCM/MP3 data playback.
- Disabled the DMA tone override at runtime:
  `echo N >/sys/module/omap_dma/parameters/nq_audio_tone`.
- Actual ALSA PCM validation:
  `artifacts/audio-rootcause-linux66-clean-clockfix-realpcm-20260616-010321`.
  Played `/root/nq-440-0.05-s16.wav` through
  `aplay -D hw:0,0 --period-size=1032 --buffer-size=4128` with
  `nq_audio_tone=N`. Result: `aplay_status=0`; no `audio-tone`, underrun, or
  XRUN lines appeared in the post-run kernel log. Mac mic analysis stayed
  clean-family: `envelope_cv_25ms=0.00662`,
  `envelope_peak_to_trough_db_25ms=0.180`, and no 12 Hz modulation peak.
- Actual MP3 player validation:
  `artifacts/audio-rootcause-linux66-clean-clockfix-realmp3-20260616-010346`.
  Played `/root/into-the-oceans-and-the-air.mp3` through
  `mpg123 -q -n 700` with `nq_audio_tone=N`. Result: `mpg123_status=0`; post-run
  state returned to `closed`, with no audio-tone override, underrun, or XRUN
  lines found in the captured post-state log.
