#!/bin/sh

PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

log() {
    echo "[nq-load-audio] $*"
}

if grep -q 'Steelhead TAS5713' /proc/asound/cards 2>/dev/null; then
    log "Steelhead TAS5713 already registered"
    exit 0
fi

krel="$(uname -r)"
mods="/lib/modules/$krel"

if [ -d "$mods" ] && command -v depmod >/dev/null 2>&1; then
    depmod -a "$krel" 2>/dev/null || true
fi

if command -v modprobe >/dev/null 2>&1; then
    modprobe snd_soc_ti_sdma \
        nq_period_bytes=4128 \
        nq_periods=4 2>/dev/null || true
    modprobe snd_soc_omap_mcbsp \
        nq_legacy_element=1 \
        nq_legacy_threshold_frame=1 \
        nq_legacy_pm_runtime_hold=1 \
        nq_no_rx_err_irq=1 \
        nq_legacy_tx_irq=1 \
        nq_pio_tone_ms=0 \
        nq_fifo_poll_ms=0 2>/dev/null || true
    modprobe snd_soc_tas571x \
        nq_dump_regs=0 \
        nq_legacy_stream_reinit=1 \
        nq_mute_on_trigger=-1 \
        nq_async_legacy_stream_reinit_ms=0 \
        nq_cycle_mclk_on_legacy_reset=1 \
        nq_skip_hw_params=1 \
        nq_sdi_override=-1 \
        nq_err_poll_ms=0 2>/dev/null || true
    modprobe snd_soc_steelhead_tas5713 \
        nq_audio_dump=0 \
        nq_audio_format=i2s \
        nq_audio_inversion=nb-nf \
        nq_legacy_s16_only=1 \
        nq_codec_power_first=0 \
        nq_codec_mclk_startup=0 \
        nq_mcbsp_clk_startup=0 \
        nq_mcbsp_clk_hw_params=1 \
        nq_skip_codec_fmt=1 2>/dev/null || true
fi

if ! grep -q 'Steelhead TAS5713' /proc/asound/cards 2>/dev/null && command -v insmod >/dev/null 2>&1; then
    audio_base="$mods/kernel/sound/soc"
    insmod "$audio_base/ti/snd-soc-ti-sdma.ko" \
        nq_period_bytes=4128 \
        nq_periods=4 2>/dev/null || true
    insmod "$audio_base/ti/snd-soc-omap-mcbsp.ko" \
        nq_legacy_element=1 \
        nq_legacy_threshold_frame=1 \
        nq_legacy_pm_runtime_hold=1 \
        nq_no_rx_err_irq=1 \
        nq_legacy_tx_irq=1 \
        nq_pio_tone_ms=0 \
        nq_fifo_poll_ms=0 2>/dev/null || true
    insmod "$audio_base/codecs/snd-soc-tas571x.ko" \
        nq_dump_regs=0 \
        nq_legacy_stream_reinit=1 \
        nq_mute_on_trigger=-1 \
        nq_async_legacy_stream_reinit_ms=0 \
        nq_cycle_mclk_on_legacy_reset=1 \
        nq_skip_hw_params=1 \
        nq_sdi_override=-1 \
        nq_err_poll_ms=0 2>/dev/null || true
    insmod "$audio_base/ti/snd-soc-steelhead-tas5713.ko" \
        nq_audio_dump=0 \
        nq_audio_format=i2s \
        nq_audio_inversion=nb-nf \
        nq_legacy_s16_only=1 \
        nq_codec_power_first=0 \
        nq_codec_mclk_startup=0 \
        nq_mcbsp_clk_startup=0 \
        nq_mcbsp_clk_hw_params=1 \
        nq_skip_codec_fmt=1 2>/dev/null || true
fi

i=0
while [ "$i" -lt 10 ]; do
    if grep -q 'Steelhead TAS5713' /proc/asound/cards 2>/dev/null; then
        log "Steelhead TAS5713 ready"
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

log "Steelhead TAS5713 did not appear"
exit 1
