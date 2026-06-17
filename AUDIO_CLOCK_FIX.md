# Nexus Q Audio Clock Fix

## Summary

The Linux 6.6 port originally exposed the TAS5713 ALSA device and could play
PCM, but the internal speaker output had an obvious low-frequency flutter. The
root cause was not ALSA userspace, MP3 decoding, TAS5713 register programming,
or McBSP/SDMA period geometry. It was the OMAP4 ABE DPLL reference parent.

For Nexus Q / Steelhead, the vendor Linux 3.0 kernel used `sys_clkin_ck` as the
ABE DPLL reference. Mainline Linux 6.6 used the generic OMAP4 workaround that
parents `abe_dpll_refclk_mux_ck` to `sys_32k_ck`. The final audio rates still
looked nominally correct, but the TAS5713 speaker path was audibly unstable.

The fix is a Steelhead-only clock quirk in the Linux 6.6 patch:

```text
google,steelhead: abe_dpll_refclk_mux_ck -> sys_clkin_ck
other OMAP4 boards: keep generic sys_32k_ck behavior
```

## Symptom

The failure sounded like a pulsing or fluttering tone, sometimes described as a
square-wave-like wobble. It reproduced below userspace:

- raw PCM through `aplay` fluttered;
- MP3 playback through `mpg123` fluttered;
- an in-kernel DMA tone also fluttered, which removed userspace refill and MP3
  decode from the suspect list.

Mac microphone captures of bad 6.6 runs showed a repeatable envelope modulation
near 12-13.5 Hz. Good 3.0 runs did not have that modulation by ear.

## What Was Ruled Out

The investigation compared Linux 3.0 and Linux 6.6 at several layers:

- TAS5713 init/register parity: full register dumps matched the accepted 3.0
  reference during bad 6.6 playback.
- McBSP2 register shape: serial framing registers matched the 3.0 reference
  closely.
- SDMA channel geometry: playback could be forced to the same channel,
  destination address, element size, period geometry, and interrupt behavior as
  the 3.0 reference.
- Userspace data path: an in-kernel DMA tone still reproduced the flutter.
- Codec start ordering, mute sequencing, gain, DRC/limiter settings, FIFO
  thresholds, pinmux variants, CPU idle, and ABE clockdomain idle did not remove
  the wobble.

Those results are preserved in [AUDIO_ROOT_CAUSE_LOG.md](AUDIO_ROOT_CAUSE_LOG.md).

## The Critical Difference

The accepted Linux 3.0 reference programmed the ABE DPLL like this during
playback:

```text
ABE_DPLL_REF_CLKSEL = 0x00000000
ABE_CLKMODE_DPLL    = 0x00000007
ABE_CLKSEL_DPLL     = 0x00804018
ABE_DIV_M2_DPLL     = 0x00000801
ABE_IDLEST_DPLL     = 0x00000001
```

Before the fix, Linux 6.6 used:

```text
ABE_DPLL_REF_CLKSEL = 0x00000001
ABE_CLKMODE_DPLL    = 0x00000C07
ABE_CLKSEL_DPLL     = 0x0082EE00
```

The clock framework reported:

```text
abe_dpll_refclk_mux_ck parent = sys_32k_ck
dpll_abe_ck                  = 98304000
abe_24m_fclk                 = 24576000
```

The output rates looked right, which made this easy to miss. The issue was the
reference source/quality, not a simple 48 kHz arithmetic error.

## Discriminator Test

On a running 6.6 image, the ABE DPLL was manually reprogrammed to the 3.0
`sys_clkin_ck` setup with `devmem` before playback. That changed only the ABE
DPLL reference setup and left the rest of the playback stack intact.

Result:

- ABE locked with the 3.0-style values.
- TAS5713 error register stayed clear.
- The bad 12-13 Hz envelope modulation disappeared from the Mac mic metrics.
- The user-listening verdict moved from fluttering to clean.

That made the ABE DPLL reference parent the first test that both explained the
3.0/6.6 difference and moved the acoustic result.

## Code Fix

The persisted fix lives in:

```text
patches/linux-6.6.142-nexusq-steelhead.patch
```

It changes `drivers/clk/ti/clk-44xx.c` so only `google,steelhead` uses
`sys_clkin_ck` for `abe_dpll_refclk_mux_ck`. Other OMAP4 boards keep the
generic mainline `sys_32k_ck` parent.

This is intentionally board-specific. The Nexus Q audio path depends on the
OMAP4 ABE clock tree driving McBSP2 and the external TAS5713 amplifier, and the
vendor Steelhead kernel established `sys_clkin_ck` as the working reference.

## Validation

Validated on real Nexus Q hardware:

- Rebuilt Linux `6.6.142 #5` with the Steelhead clock quirk.
- Confirmed a clean boot reports `abe_dpll_refclk_mux_ck` parent
  `sys_clkin_ck` without runtime `devmem` pokes.
- Played a real WAV through ALSA with the diagnostic DMA tone override disabled:
  - `nq_audio_tone=N`
  - `aplay_status=0`
  - no underrun/XRUN/diagnostic override lines
  - envelope CV `0.0066`
  - no 12 Hz modulation peak
- Played a real MP3 through `mpg123` with `nq_audio_tone=N`:
  - `mpg123_status=0`
  - post-run ALSA state returned to `closed`
- User ear check confirmed the 6.6 test tone sounded correct.

Key artifact directories from the final validation:

```text
artifacts/audio-rootcause-linux66-clean-clockfix-realpcm-20260616-010321
artifacts/audio-rootcause-linux66-clean-clockfix-realmp3-20260616-010346
```

## Lessons

- Nominal sample rates are not enough for audio clock validation. The bad 6.6
  setup produced the expected derived rates while still causing audible
  instability.
- When a vendor 3.0 reference sounds good, preserve its clock parent choices as
  carefully as its codec and serial-register choices.
- In-kernel tone generation is useful because it separates hardware clocking
  faults from userspace decode/refill problems.
